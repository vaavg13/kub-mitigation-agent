#!/usr/bin/env python3
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langfuse.langchain import CallbackHandler

from .config import KubernetesAgentConfig
from .llm_provider import get_llm
from .system_prompt import get_system_prompt, get_reasoning_prompt, get_controller_prompt, get_summarize_prompt
from .tool_schemas import get_reasoning_tool_models, get_execution_tool_models, GenerateOperationalSummary
from .mcp_client import MCPClient
from .tools_router import ToolsRouter

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    intent: str
    context: List[str]
    actions: List[Dict[str, Any]]
    plan: Dict[str, Any]
    current_step_index: int
    decision: Dict[str, Any]
    round: int
    final_summary: Dict[str, Any]
    plan_completed: bool


class GraphKubernetesAgent:
    def __init__(self, cfg: KubernetesAgentConfig):
        self.cfg = cfg
        self.llm = None
        self.llm_reasoning = None  # Reasoning tools only
        self.llm_controller = None  # Execution tools only
        self.llm_summarize = None  # Structured output for operational summary
        self.mcp_client: Optional[MCPClient] = None
        self.router: Optional[ToolsRouter] = None
        self.graph = None
        self.is_initialized = False
        self.langfuse_handler: Optional[CallbackHandler] = None

    async def initialize(self):
        if self.is_initialized:
            return
        # MCP
        self.mcp_client = MCPClient(self.cfg.mcp_server_command)
        await self.mcp_client.start()
        await self.mcp_client.initialize()
        # LLM with separate tool bindings
        self.llm = get_llm(self.cfg)
        self.llm_reasoning = self.llm.bind_tools(get_reasoning_tool_models())
        self.llm_controller = self.llm.bind_tools(get_execution_tool_models())
        self.llm_summarize = self.llm.with_structured_output(GenerateOperationalSummary)
        # Router
        self.router = ToolsRouter(self.mcp_client)
        # Graph
        self.graph = self._build_graph()
        self.is_initialized = True

    async def cleanup(self):
        if self.mcp_client:
            await self.mcp_client.stop()
        self.is_initialized = False

    def _build_graph(self):
        graph = StateGraph(AgentState)

        async def reasoning(state: AgentState) -> AgentState:
            """Reasoning module: analyze, evaluate, plan using reasoning tools."""
            messages = self._build_reasoning_messages(state)
            ai: AIMessage = await self.llm_reasoning.ainvoke(
                messages,
                config={"callbacks": [self.langfuse_handler]} if self.langfuse_handler else None,
            )
            
            if not ai.tool_calls:
                logger.warning("Reasoning did not call a tool")
                return {}
            
            tc = ai.tool_calls[0]
            tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            
            # Handle reasoning tool outputs
            state_delta = {"context": state.get("context", [])}
            
            if tool_name == "CreateReasoningPlan":
                # Create new plan
                plan = {
                    "objective": tool_args.get("objective"),
                    "steps": tool_args.get("steps", []),
                    "rationale": tool_args.get("rationale"),
                    "status": "active"
                }
                state_delta["plan"] = plan
                state_delta["current_step_index"] = 0
                context_msg = f"PLAN CREATED: {plan['objective']}\nSteps: {'; '.join(plan['steps'])}"
                state_delta["context"] = state_delta["context"] + [context_msg]
                logger.info(f"Plan created: {plan['objective']}")
                
            elif tool_name == "EvaluateStep":
                # Evaluate step and update tracking
                plan = state.get("plan", {})
                current_step_index = state.get("current_step_index", 0)
                plan_action = tool_args.get("plan_action")
                
                eval_msg = f"EVALUATION: Step '{tool_args.get('step_completed')}' - Success: {tool_args.get('success')}"
                eval_msg += f"\nObservations: {'; '.join(tool_args.get('observations', []))}"
                eval_msg += f"\nAnalysis: {tool_args.get('analysis', 'N/A')}"
                eval_msg += f"\nDecision: {plan_action}"
                state_delta["context"] = state_delta["context"] + [eval_msg]
                
                if plan_action == "proceed_to_next_step":
                    state_delta["current_step_index"] = current_step_index + 1
                    logger.info(f"Advancing to step {current_step_index + 1}")
                elif plan_action == "retry_current_step":
                    logger.info(f"Retrying step {current_step_index}")
                elif plan_action == "create_new_plan":
                    plan["status"] = "broken"
                    state_delta["plan"] = plan
                    state_delta["current_step_index"] = 0
                    logger.info("Plan broken - new plan needed")
                elif plan_action == "completed":
                    state_delta["plan_completed"] = True
                    logger.info("Plan completed - routing to summarize")
            
            return state_delta

        async def controller(state: AgentState) -> AgentState:
            """Controller: execute the current plan step using execution tools."""
            messages = self._build_controller_messages(state)
            ai: AIMessage = await self.llm_controller.ainvoke(
                messages,
                config={"callbacks": [self.langfuse_handler]} if self.langfuse_handler else None,
            )
            
            if not ai.tool_calls:
                # No tool call - add context message to help reasoning understand what happened
                logger.warning("Controller did not call a tool")
                return {
                    "context": state.get("context", []) + ["SYSTEM: Controller failed to produce a tool call. Reasoning should analyze why and decide next steps."]
                }
            
            tc = ai.tool_calls[0]
            tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            
            return {"decision": {"tool": tool_name, "arguments": tool_args}}

        async def tool_exec(state: AgentState) -> AgentState:
            """Execute the controller's tool decision."""
            decision = state.get("decision", {})
            if "tool" not in decision:
                return {}
            
            function_name = decision["tool"]
            args = decision.get("arguments", {})
            result, state_delta, action_record = await self.router.execute(function_name, args, state)
            
            action_record["result"] = result
            new_context = [f"Executed {function_name}", f"Result: {json.dumps(result)[:2000]}"]
            
            return {
                **state_delta,
                "context": state.get("context", []) + new_context,
                "actions": state.get("actions", []) + [action_record],
                "round": state.get("round", 0) + 1,
            }

        async def summarize(state: AgentState) -> AgentState:
            """Generate operational summary after plan completion using structured output."""
            messages = self._build_summarize_messages(state)
            summary_obj: GenerateOperationalSummary = await self.llm_summarize.ainvoke(
                messages,
                config={"callbacks": [self.langfuse_handler]} if self.langfuse_handler else None,
            )
            
            # Convert Pydantic model to dict for state storage
            problem_locations = []
            if summary_obj.problem_location:
                problem_locations = [
                    {"name": loc.name, "type": loc.type}
                    for loc in summary_obj.problem_location
                ]
            
            summary = {
                "objective": summary_obj.objective,
                "actions_completed": summary_obj.actions_completed,
                "results_achieved": summary_obj.results_achieved,
                "status": summary_obj.status,
                "problem_location": problem_locations,
                "success": summary_obj.success
            }
            
            logger.info(f"Operational summary generated: {summary_obj.status}")
            return {
                "final_summary": summary,
                "context": state.get("context", []) + [f"OPERATION COMPLETE: {summary_obj.status}"]
            }

        graph.add_node("reasoning", reasoning)
        graph.add_node("controller", controller)
        graph.add_node("tool_exec", tool_exec)
        graph.add_node("summarize", summarize)

        def route_after_reasoning(state: AgentState):
            # If plan is completed, go to summarize node
            if state.get("plan_completed"):
                return "summarize"
            # Otherwise go to controller to execute
            return "controller"

        def route_after_controller(state: AgentState):
            if "tool" in state.get("decision", {}):
                return "tool_exec"
            else:
                # Controller failed to produce a tool call - go back to reasoning
                # (warning already logged in controller node)
                return "reasoning"

        def route_after_tool(state: AgentState):
            if state.get("round", 0) >= self.cfg.max_rounds:
                state["context"] = state.get("context", []) + [
                    "SYSTEM: Maximum rounds reached. Evaluate and complete the plan."
                ]
            return "reasoning"

        # Flow: reasoning -> controller -> tool_exec -> reasoning (loop)
        # When plan_completed: reasoning -> summarize -> END
        graph.set_entry_point("reasoning")
        graph.add_conditional_edges("reasoning", route_after_reasoning)
        graph.add_conditional_edges("controller", route_after_controller)
        graph.add_edge("tool_exec", "reasoning")
        graph.add_edge("summarize", END)

        return graph.compile()

    def _build_reasoning_messages(self, state: AgentState) -> List[Any]:
        """Build messages for reasoning module."""
        context_text = "\n".join(state.get("context", []))
        plan = state.get("plan")
        current_step_index = state.get("current_step_index", 0)
        has_previous_action = len(state.get("actions", [])) > 0
        
        prompt = get_reasoning_prompt(
            intent=state.get("intent", ""),
            context=context_text,
            plan=plan,
            current_step_index=current_step_index,
            has_previous_action=has_previous_action
        )
        
        return [HumanMessage(content=prompt)]

    def _build_controller_messages(self, state: AgentState) -> List[Any]:
        """Build messages for controller module."""
        context_text = "\n".join(state.get("context", []))
        plan = state.get("plan")
        current_step_index = state.get("current_step_index", 0)
        
        prompt = get_controller_prompt(
            context=context_text,
            plan=plan,
            current_step_index=current_step_index
        )
        
        return [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=prompt)
        ]

    def _build_summarize_messages(self, state: AgentState) -> List[Any]:
        """Build messages for summarize module."""
        intent = state.get("intent", "")
        plan = state.get("plan", {})
        actions = state.get("actions", [])
        context_text = "\n".join(state.get("context", []))
        
        prompt = get_summarize_prompt(
            intent=intent,
            plan=plan,
            actions=actions,
            context=context_text
        )
        
        return [HumanMessage(content=prompt)]

    async def agent_loop(self, intent: str, snapshot: Optional[Dict[str, Any]] = None):
        if not self.is_initialized:
            await self.initialize()
        
        # Initialize Langfuse handler with error handling for connection issues
        if not self.langfuse_handler:
            try:
                self.langfuse_handler = CallbackHandler()
            except Exception as e:
                logger.warning(f"Failed to initialize Langfuse handler (tracing disabled): {e}")
                self.langfuse_handler = None
        
        initial_state: AgentState = {
            "intent": intent,
            "context": [f"Intent: {intent}", f"Snapshot: {json.dumps(snapshot or {}, indent=2)}"],
            "actions": [],
            "round": 0,
        }
        
        try:
            # Build config with callbacks only if Langfuse is available
            config = {"recursion_limit": 100}
            if self.langfuse_handler:
                config["callbacks"] = [self.langfuse_handler]
            
            final_state: AgentState = await self.graph.ainvoke(initial_state, config=config)
            
            return final_state.get("actions", []), final_state.get("final_summary")
            
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            error_type = "timeout" if isinstance(e, asyncio.TimeoutError) else "cancelled"
            logger.error(f"Agent execution {error_type} - generating emergency summary")
            
            # Generate minimal emergency summary
            emergency_summary = {
                "objective": "Agent execution incomplete",
                "actions_completed": [a.get("tool", "unknown") for a in initial_state.get("actions", [])],
                "results_achieved": ["Partial execution - agent terminated early"],
                "status": f"FAILED - Agent execution {error_type}",
                "problem_location": [],
                "success": False
            }
            
            return initial_state.get("actions", []), emergency_summary
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Agent execution failed with error: {error_msg}")
            
            # Generate emergency summary with error details
            emergency_summary = {
                "objective": "Agent execution failed",
                "actions_completed": [a.get("tool", "unknown") for a in initial_state.get("actions", [])],
                "results_achieved": ["Execution failed due to error"],
                "status": f"FAILED - {error_msg}",
                "problem_location": [],
                "success": False,
                "error": error_msg
            }
            
            return initial_state.get("actions", []), emergency_summary