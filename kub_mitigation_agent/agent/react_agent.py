#!/usr/bin/env python3
"""
ReAct Agent - Reason + Act Approach
Simplified agent that uses ReAct loop without complex planning logic.
"""
import asyncio
import os
import json
import logging
import time
from typing import Any, Dict, List, Optional, TypedDict
from dataclasses import dataclass

from langgraph.graph import END, StateGraph
from langgraph.errors import GraphRecursionError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .config import KubernetesAgentConfig
from .llm_provider import get_llm
from .system_prompt import get_system_prompt
from kub_mitigation_agent.clients.mcp_client import MCPClient
from .tools import ALL_TOOLS, set_mcp_client, set_warmup_end_timestamp
from .agent_utils import build_emergency_summary

logger = logging.getLogger(__name__)


@dataclass
class AgentTraceStep:
    """Single step in agent execution trace: Thought -> Action -> Observation"""
    step_number: int
    thought: Optional[str]
    action: str
    action_args: Dict[str, Any]
    observation: Any
    timestamp: float


class ReactAgentState(TypedDict, total=False):
    intent: str
    context: List[str]
    trace: List[AgentTraceStep]  # New: complete thought-action-observation trace
    round: int
    decision: Dict[str, Any]
    pending_thought: Optional[str]  # Thought waiting to be paired with observation
    final_summary: Optional[Dict[str, Any]]
    current_plan: Optional[Dict[str, Any]]


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
        self.graph = None
        self.is_initialized = False
        self._state_snapshot: ReactAgentState = {}

    # Emergency summaries are built in outer agent wrapper

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
        self.llm = self.llm.bind_tools(ALL_TOOLS)
        # Build tool lookup by name for direct invocation
        self._tools_by_name = {t.name: t for t in ALL_TOOLS}
        # Share MCP client with tools
        set_mcp_client(self.mcp_client)
        # Initialize warmup cutoff timestamp from env if provided
        set_warmup_end_timestamp(os.environ.get("KMA_WARMUP_END_TS"))
        
        # Build graph
        self.graph = self._build_graph()
        self.is_initialized = True
        logger.info("Agent initialized successfully")

    async def cleanup(self):
        if self.mcp_client:
            await self.mcp_client.stop()
        
        self.is_initialized = False

    def _reset_state_snapshot(self, initial_state: ReactAgentState):
        """Store a copy of the initial state for partial-trace recovery."""
        self._state_snapshot = dict(initial_state)

    def _update_state_snapshot(self, delta: ReactAgentState):
        """Merge latest state updates into snapshot for exception recovery."""
        for key, value in delta.items():
            self._state_snapshot[key] = value

    def _get_state_snapshot(self) -> ReactAgentState:
        """Return the most recent known state."""
        return self._state_snapshot

    async def _force_operational_summary(
        self,
        status: str,
        results: List[str],
        error: Optional[str] = None,
        success: bool = False,
    ):
        """Force-generate operational summary and store in snapshot. Used for error recovery scenarios."""
        snapshot = self._get_state_snapshot()
        trace = snapshot.get("trace", [])
        action_names = [step.action for step in trace]
        intent = snapshot.get("intent") or "Mitigation mission"
        
        args = {
            "objective": intent,
            "actions_completed": action_names,
            "results_achieved": results,
            "status": status,
            "problem_location": [],
            "success": success,
        }
        
        # Try agent tool first, fallback to emergency summary
        summary_tool = self._tools_by_name["generate_operational_summary"]
        try:
            summary = await summary_tool.ainvoke(args)
            logger.info("Operational summary generated via agent tool.")
        except Exception as tool_error:
            logger.error(f"Summary tool failed: {tool_error}")
            summary = build_emergency_summary(action_names, status, results, error=error)
        
        # Store summary in snapshot (no trace step - summary is returned separately)
        self._update_state_snapshot({
            "final_summary": summary,
        })

    async def _handle_agent_failure(self, exc: Exception) -> tuple[List[AgentTraceStep], Dict[str, Any]]:
        """Recover partial trace from snapshot and force operational summary generation."""
        error_name = type(exc).__name__
        logger.warning(f"Agent failed with {error_name}: {exc}")
        
        snapshot = self._get_state_snapshot()
        logger.warning(f"⚠️  Recovered {len(snapshot.get('trace', []))} trace steps from snapshot")
        
        # Force operational summary (updates snapshot)
        await self._force_operational_summary(
            status=f"FAILED - {error_name}",
            results=[f"Agent failed: {str(exc)}"],
            error=f"{error_name}: {str(exc)}",
            success=False,
        )
        
        # Read back from snapshot
        updated_snapshot = self._get_state_snapshot()
        return updated_snapshot.get("trace", []), updated_snapshot.get("final_summary")

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
            
            ai: AIMessage = await self.llm.ainvoke(messages)
            
            if not ai.tool_calls:
                # No tool call produced; add guidance to context and continue looping
                logger.warning("Agent did not call a tool")
                current_round = state.get("round", 0) + 1
                context_msg = "SYSTEM: Agent failed to produce a tool call. Re-analyze and try again."
                # If max rounds reached, force operational summary to terminate
                if current_round >= self.cfg.max_rounds:
                    # Update snapshot with current round
                    self._update_state_snapshot({"round": current_round})
                    # Force summary generation
                    await self._force_operational_summary(
                        status="FAILED - Maximum rounds reached",
                        results=["Agent reached maximum rounds without completion"],
                        success=False,
                    )
                    # Return state with summary from snapshot
                    snapshot = self._get_state_snapshot()
                    return {
                        "context": state.get("context", []) + [context_msg],
                        "round": current_round,
                        "final_summary": snapshot.get("final_summary"),
                        "decision": {},
                        "current_plan": state.get("current_plan"),
                    }
                state_update = {
                    "context": state.get("context", []) + [context_msg],
                    "round": current_round,
                    "decision": {},
                    "current_plan": state.get("current_plan"),
                }
                self._update_state_snapshot(state_update)
                return state_update
            
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
            
            # Log thought and action
            logger.info(f"THOUGHT: {thinking if thinking else '(none)'}")
            logger.info(f"ACTION: {tool_name}({json.dumps(tool_args, separators=(',', ':'))})")
            
            # Store the decision for tool execution and pending thought
            state_update = {
                "context": state.get("context", []) + new_context,
                "decision": {"tool": tool_name, "arguments": tool_args},
                "pending_thought": thinking if thinking else None,
                "current_plan": state.get("current_plan"),
            }
            self._update_state_snapshot(state_update)
            return state_update

        async def tool_exec(state: ReactAgentState) -> ReactAgentState:
            """Execute the tool chosen by the agent."""
            decision = state.get("decision", {})
            if "tool" not in decision:
                return {}
            
            function_name = decision["tool"]
            args = decision.get("arguments", {})
            pending_thought = state.get("pending_thought")
            current_trace = state.get("trace", [])
            
            # Execute the tool directly.
            tool = self._tools_by_name.get(function_name)
            if not tool:
                result = {"error": f"Unknown tool: {function_name}"}
            else:
                try:
                    result = await tool.ainvoke(args)
                except Exception as tool_error:
                    # Catch tool execution errors (ValidationError, network errors, etc.)
                    # Create error result and continue - agent can decide how to proceed
                    error_name = type(tool_error).__name__
                    error_msg = str(tool_error)
                    logger.warning(f"Tool {function_name} failed with {error_name}: {error_msg}")
                    result = {
                        "error": f"{error_name}: {error_msg}",
                        "error_type": error_name,
                        "tool": function_name
                    }

            # Build trace step with thought-action-observation
            trace_step = AgentTraceStep(
                step_number=len(current_trace) + 1,
                thought=pending_thought,
                action=function_name,
                action_args=args,
                observation=result,
                timestamp=time.time()
            )

            # Add observation to context (ReAct format)
            result_str = json.dumps(result)
            
            # Log observation
            logger.info(f"OBSERVATION: {result_str}")
            
            # Build state update
            new_state = {
                "context": state.get("context", []) + [f"OBSERVATION: {result_str}"],
                "trace": current_trace + [trace_step],
                "round": state.get("round", 0) + 1,
            }
            
            # Store special tool outputs in state
            if function_name == "generate_action_plan" and isinstance(result, dict):
                new_state["current_plan"] = result
            if function_name == "generate_operational_summary" and isinstance(result, dict):
                new_state["final_summary"] = result
            
            self._update_state_snapshot(new_state)
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
        user_message = json.dumps({
            "mission": state.get("intent", ""),
            "round": state.get("round", 0),
            "context_log": state.get("context", []),
            "current_plan": state.get("current_plan"),
            "instruction": "Respond with the next single tool call that best advances the plan."
        }, indent=2)

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
            Tuple of (trace list, final summary dict)
            - trace: Complete list of AgentTraceStep objects with thought-action-observation
            - summary: Final operational summary
        """
        if not self.is_initialized:
            await self.initialize()
        
        logger.info("Starting agent loop")
        
        # Initial state
        initial_state: ReactAgentState = {
            "intent": intent,
            "context": [
                f"Intent: {intent}",
                f"Initial Snapshot: {json.dumps(snapshot or {}, indent=2)}",
            ],
            "trace": [],
            "round": 0,
        }
        self._reset_state_snapshot(initial_state)
        config = {"recursion_limit": self.cfg.recursion_limit}
        
        try:
            final_state: ReactAgentState = await self.graph.ainvoke(initial_state, config=config)
            
            trace = final_state.get("trace", [])
            logger.info(f"Agent loop completed: {len(trace)} trace steps recorded")
            
            return trace, final_state.get("final_summary")
            
        except KeyboardInterrupt:
            logger.warning("Agent loop interrupted by user (Ctrl+C)")
            
            # Force operational summary from snapshot
            await self._force_operational_summary(
                status="INTERRUPTED - User interrupted execution",
                results=["Agent execution interrupted before completion"],
                error="KeyboardInterrupt",
                success=False,
            )
            
            # Re-raise so upstream handlers know we were interrupted
            raise
            
        except Exception as e:
            return await self._handle_agent_failure(e)