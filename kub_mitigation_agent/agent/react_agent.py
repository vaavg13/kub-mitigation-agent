#!/usr/bin/env python3
"""
ReAct Agent - Reason + Act Approach
Simplified agent that uses ReAct loop without complex planning logic.
"""
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
        
        # Initialize MCP client
        self.mcp_client = MCPClient(self.cfg.mcp_server_command)
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

    async def cleanup(self):
        if self.mcp_client:
            await self.mcp_client.stop()
        self.is_initialized = False

    def _build_graph(self):
        """Build simple ReAct graph: agent -> tool_exec -> agent (loop)."""
        graph = StateGraph(ReactAgentState)

        async def agent(state: ReactAgentState) -> ReactAgentState:
            """
            Main agent node: Observe context, think, and decide on next action.
            Uses ReAct approach - LLM decides what tool to call based on current context.
            """
            messages = self._build_agent_messages(state)
            
            ai: AIMessage = await self.llm.ainvoke(
                messages,
                config={"callbacks": [self.langfuse_handler]} if self.langfuse_handler else None,
            )
            
            if not ai.tool_calls:
                logger.warning("Agent did not call a tool, ending execution")
                return {"final_summary": {"status": "incomplete", "error": "No tool call made"}}
            
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
            
            return {
                **state_delta,
                "context": state.get("context", []) + new_context,
                "actions": state.get("actions", []) + [action_record],
                "round": state.get("round", 0) + 1,
            }

        # Add nodes
        graph.add_node("agent", agent)
        graph.add_node("tool_exec", tool_exec)

        # Define routing logic
        def route_after_agent(state: ReactAgentState):
            """Route from agent: if has decision, go to tool_exec, else end."""
            if "decision" in state and state.get("decision", {}).get("tool"):
                return "tool_exec"
            else:
                return END

        def route_after_tool(state: ReactAgentState):
            """Route from tool_exec: if summary generated, end, else continue loop."""
            # Check if we've completed (summary generated)
            if state.get("final_summary"):
                return END
            
            # Check max rounds
            if state.get("round", 0) >= self.cfg.max_rounds:
                logger.warning(f"Max rounds ({self.cfg.max_rounds}) reached")
                return END
            
            # Continue the loop
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
        
        self.langfuse_handler = self.langfuse_handler or CallbackHandler()
        
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
        
        # Run the graph
        final_state: ReactAgentState = await self.graph.ainvoke(
            initial_state,
            config={"callbacks": [self.langfuse_handler]},
        )
        
        return final_state.get("actions", []), final_state.get("final_summary")

