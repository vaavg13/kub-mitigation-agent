#!/usr/bin/env python3
"""
ReAct Agent - Reason + Act Approach
Simplified agent that uses ReAct loop without complex planning logic.
"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langfuse.langchain import CallbackHandler

from .config import KubernetesAgentConfig
from .llm_provider import get_llm
from .system_prompt import get_system_prompt
from .tool_schemas import get_all_tool_models
from .mcp_client import MCPClient
from .tools_router import ToolsRouter

logger = logging.getLogger(__name__)


class ReactAgentState(TypedDict, total=False):
    """Simplified state for ReAct agent."""
    intent: str
    context: List[str]
    actions: List[Dict[str, Any]]
    round: int
    decision: Dict[str, Any]
    final_summary: Optional[Dict[str, Any]]


class ReactAgent:
    """
    ReAct-based Kubernetes agent.
    
    Simple loop: agent thinks -> calls tool -> observes result -> repeats
    No separate reasoning/controller phases or complex plan evaluation.
    """
    
    def __init__(self, cfg: KubernetesAgentConfig):
        self.cfg = cfg
        self.llm = None
        self.mcp_client: Optional[MCPClient] = None
        self.router: Optional[ToolsRouter] = None
        self.graph = None
        self.is_initialized = False
        self.langfuse_handler: Optional[CallbackHandler] = None

    async def initialize(self):
        if self.is_initialized:
            return
        
        logger.info("Initializing agent...")
        # Initialize MCP client
        self.mcp_client = MCPClient(
            self.cfg.mcp_server_command,
            response_timeout_seconds=self.cfg.mcp_timeout_seconds,
        )
        await self.mcp_client.start()
        await self.mcp_client.initialize()
        
        # Initialize LLM with all tools
        self.llm = get_llm(self.cfg)
        self.llm = self.llm.bind_tools(get_all_tool_models())
        
        # Initialize router
        self.router = ToolsRouter(self.mcp_client)
        
        # Build graph
        self.graph = self._build_graph()
        self.is_initialized = True
        logger.info("Agent initialized successfully")

    async def cleanup(self):
        if self.mcp_client:
            await self.mcp_client.stop()
        
        self.langfuse_handler = None
        self.is_initialized = False

    def _build_graph(self):
        """Build simple ReAct graph: agent -> tool_exec -> agent (loop)."""
        graph = StateGraph(ReactAgentState)

        async def agent(state: ReactAgentState) -> ReactAgentState:
            """
            Main agent node: Observe context, think, and decide on next action.
            Uses ReAct approach - LLM decides what tool to call based on current context.
            """
            logger.info(f"Agent thinking (round {state.get('round', 0)})")
            messages = self._build_agent_messages(state)
            
            ai: AIMessage = await self.llm.ainvoke(
                messages,
                config={"callbacks": [self.langfuse_handler]} if self.langfuse_handler else None,
            )
            
            if not ai.tool_calls:
                # No tool call produced; add guidance to context and continue looping
                logger.warning("Agent did not call a tool")
                current_round = state.get("round", 0) + 1
                context_msg = "SYSTEM: Agent failed to produce a tool call. Re-analyze and try again."
                # If max rounds reached, emit an emergency summary to terminate properly
                if current_round >= self.cfg.max_rounds:
                    emergency_summary = {
                        "objective": "Agent execution incomplete",
                        "actions_completed": [a.get("tool", "unknown") for a in state.get("actions", [])],
                        "results_achieved": ["Maximum rounds reached"],
                        "status": "FAILED - Maximum rounds reached",
                        "problem_location": [],
                        "success": False
                    }
                    return {
                        "context": state.get("context", []) + [context_msg, "OPERATION COMPLETE: FAILED - Maximum rounds reached"],
                        "round": current_round,
                        "final_summary": emergency_summary,
                        "decision": {}
                    }
                return {
                    "context": state.get("context", []) + [context_msg],
                    "round": current_round,
                    "decision": {}
                }
            
            # Extract first tool call
            tc = ai.tool_calls[0]
            tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            
            # Capture agent's thinking/reasoning (the content before the tool call)
            thinking = ai.content if ai.content else ""
            
            # Build context with thinking and decision
            new_context = []
            if thinking:
                new_context.append(f"THOUGHT: {thinking}")
            new_context.append(f"ACTION: {tool_name}({json.dumps(tool_args, separators=(',', ':'))})")
            
            # Store the decision for tool execution
            return {
                "context": state.get("context", []) + new_context,
                "decision": {"tool": tool_name, "arguments": tool_args}
            }

        async def tool_exec(state: ReactAgentState) -> ReactAgentState:
            """Execute the tool chosen by the agent."""
            decision = state.get("decision", {})
            if "tool" not in decision:
                return {}
            
            function_name = decision["tool"]
            args = decision.get("arguments", {})
            logger.info(f"Executing tool: {function_name}")
            
            # Special handling for summary - this ends the loop
            if function_name == "GenerateOperationalSummary":
                summary = {
                    "objective": args.get("objective", ""),
                    "actions_completed": args.get("actions_completed", []),
                    "results_achieved": args.get("results_achieved", []),
                    "status": args.get("status", ""),
                    "problem_location": args.get("problem_location", []),
                    "success": args.get("success", False)
                }
                logger.info(f"Operation completed: {summary['status']}")
                return {
                    "final_summary": summary,
                    "context": state.get("context", []) + [f"OPERATION COMPLETE: {summary['status']}"]
                }
            
            # Execute the tool
            result, state_delta, action_record = await self.router.execute(function_name, args, state)
            
            # Record action
            action_record["result"] = result
            
            # Add observation to context (ReAct format)
            result_str = json.dumps(result)
            if len(result_str) > 2000:
                result_str = result_str[:2000] + "... (truncated)"
            
            new_context = [f"OBSERVATION: {result_str}"]
            
            next_round = state.get("round", 0) + 1
            new_state = {
                **state_delta,
                "context": state.get("context", []) + new_context,
                "actions": state.get("actions", []) + [action_record],
                "round": next_round,
            }
            # If we've hit the max rounds, emit an emergency summary so we terminate with a summary
            if next_round >= self.cfg.max_rounds:
                emergency_summary = {
                    "objective": "Agent execution incomplete",
                    "actions_completed": [a.get("tool", "unknown") for a in new_state.get("actions", [])],
                    "results_achieved": ["Maximum rounds reached"],
                    "status": "FAILED - Maximum rounds reached",
                    "problem_location": [],
                    "success": False
                }
                new_state["final_summary"] = emergency_summary
                new_state["context"] = new_state.get("context", []) + ["OPERATION COMPLETE: FAILED - Maximum rounds reached"]
            return new_state

        # Add nodes
        graph.add_node("agent", agent)
        graph.add_node("tool_exec", tool_exec)

        # Define routing logic
        def route_after_agent(state: ReactAgentState):
            """Route from agent: end only when final_summary is present; else continue."""
            if state.get("final_summary"):
                return END
            if "decision" in state and state.get("decision", {}).get("tool"):
                return "tool_exec"
            # No decision and no summary; continue trying
            return "agent"

        def route_after_tool(state: ReactAgentState):
            """Route from tool_exec: end only when summary present, else continue loop."""
            if state.get("final_summary"):
                return END
            return "agent"

        # Set up graph flow
        graph.set_entry_point("agent")
        graph.add_conditional_edges("agent", route_after_agent)
        graph.add_conditional_edges("tool_exec", route_after_tool)

        return graph.compile()

    def _build_agent_messages(self, state: ReactAgentState) -> List[Any]:
        """Build messages for the agent with system prompt and context."""
        intent = state.get("intent", "")
        context = state.get("context", [])
        round_num = state.get("round", 0)
        actions = state.get("actions", [])
        
        # Build context string
        context_text = "\n".join(context)
        
        # Build user message with current situation
        user_message = f"""MISSION: {intent}

CURRENT SITUATION (Round {round_num}):
{context_text}

ACTIONS TAKEN SO FAR: {len(actions)}

Based on the evidence and context above, decide what to do next:
- If you need more information, call investigation tools (prometheus_get_timeseries, kubectl_get, etc.)
- If you've identified the problem, take corrective action (kubectl_scale, kubectl_patch, kubectl_delete, kubectl_drain, etc.)
- When the issue is resolved or you've exhausted options, call GenerateOperationalSummary to complete

Remember: Always act based on evidence. Use clear operational language."""

        return [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=user_message)
        ]

    async def agent_loop(self, intent: str, snapshot: Optional[Dict[str, Any]] = None):
        """
        Run the ReAct agent loop.
        
        Args:
            intent: The mission/objective for the agent
            snapshot: Optional initial snapshot of the system state
            
        Returns:
            Tuple of (actions list, final summary dict)
        """
        if not self.is_initialized:
            await self.initialize()
        
        logger.info("Starting agent loop")
        
        try:
            self.langfuse_handler = CallbackHandler()
        except Exception as e:
            logger.warning(f"Failed to initialize Langfuse handler (tracing disabled): {e}")
            self.langfuse_handler = None
        
        # Initial state
        initial_state: ReactAgentState = {
            "intent": intent,
            "context": [
                f"Intent: {intent}",
                f"Initial Snapshot: {json.dumps(snapshot or {}, indent=2)}"
            ],
            "actions": [],
            "round": 0,
        }
        
        try:
            config = {"recursion_limit": 100}
            final_state: ReactAgentState = await self.graph.ainvoke(initial_state, config=config)
            
            logger.info(f"Agent loop completed: {len(final_state.get('actions', []))} actions taken")
            # Ensure we always return an operational summary
            final_summary = final_state.get("final_summary")
            if not final_summary:
                emergency_summary = {
                    "objective": "Agent execution incomplete",
                    "actions_completed": [a.get("tool", "unknown") for a in final_state.get("actions", [])],
                    "results_achieved": ["Execution ended without summary"],
                    "status": "FAILED - No summary generated",
                    "problem_location": [],
                    "success": False
                }
                final_summary = emergency_summary
            return final_state.get("actions", []), final_summary
            
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            error_type = "timeout" if isinstance(e, asyncio.TimeoutError) else "cancelled"
            logger.error(f"Agent execution {error_type}")
            logger.info("Generating emergency summary")
            
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
            logger.error(f"Agent execution failed: {error_msg}", exc_info=True)
            logger.info("Generating emergency summary")
            
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

