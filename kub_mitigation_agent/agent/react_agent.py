#!/usr/bin/env python3
"""
ReAct Agent - Reason + Act Approach
Simplified agent that uses ReAct loop without complex planning logic.
"""
import asyncio
import os
import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .config import KubernetesAgentConfig
from .llm_provider import get_llm
from .system_prompt import get_system_prompt
from kub_mitigation_agent.clients.mcp_client import MCPClient
from .tools import ALL_TOOLS, set_mcp_client, set_warmup_end_timestamp
from .agent_utils import log_thought_action_observation

logger = logging.getLogger(__name__)


class ReactAgentState(TypedDict, total=False):
    intent: str
    context: List[str]
    actions: List[Dict[str, Any]]
    round: int
    decision: Dict[str, Any]
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
                        "decision": {},
                        "current_plan": state.get("current_plan"),
                    }
                return {
                    "context": state.get("context", []) + [context_msg],
                    "round": current_round,
                    "decision": {},
                    "current_plan": state.get("current_plan"),
                }
            
            # Extract first tool call
            tc = ai.tool_calls[0]
            tool_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            
            # Capture agent's thinking/reasoning (the content before the tool call)
            thinking = ai.content if ai.content else ""

            # Build context with thinking and decision
            new_context = []
            full_output = getattr(self.cfg, "full_output", True)
            # Always maintain full context internally for reasoning
            if thinking:
                new_context.append(f"THOUGHT: {thinking}")
            new_context.append(f"ACTION: {tool_name}({json.dumps(tool_args, separators=(',', ':'))})")
            # Output logging behavior
            if tool_name == "generate_action_plan":
                # Always show a simple notice for action plan creation regardless of mode
                logger.info("AGENT CREATED ACTION PLAN")
            else:
                if full_output:
                    # Print thought (even if empty) and action; observation will be printed after tool execution
                    logger.info(f"THOUGHT: {thinking if thinking else '(none)'}")
                    logger.info(f"ACTION: {tool_name}({json.dumps(tool_args, separators=(',', ':'))})")
                else:
                    logger.info(f"ACTION: {tool_name}")
            
            # Store the decision for tool execution
            return {
                "context": state.get("context", []) + new_context,
                "decision": {"tool": tool_name, "arguments": tool_args},
                "current_plan": state.get("current_plan"),
            }

        async def tool_exec(state: ReactAgentState) -> ReactAgentState:
            """Execute the tool chosen by the agent."""
            decision = state.get("decision", {})
            if "tool" not in decision:
                return {}
            
            function_name = decision["tool"]
            args = decision.get("arguments", {})
            
            # Special handling for summary - this ends the loop
            if function_name == "generate_operational_summary":
                summary = {
                    "objective": args.get("objective", ""),
                    "actions_completed": args.get("actions_completed", []),
                    "results_achieved": args.get("results_achieved", []),
                    "status": args.get("status", ""),
                    "problem_location": args.get("problem_location", []),
                    "success": args.get("success", False)
                }
                # Always include status and problem location regardless of mode
                logger.info(f"Operation completed: {summary['status']}")
                if summary.get("problem_location"):
                    logger.info(f"PROBLEM LOCATION: {json.dumps(summary['problem_location'])}")
                return {
                    "final_summary": summary,
                    "context": state.get("context", []) + [f"OPERATION COMPLETE: {summary['status']}"]
                }
            
            # Execute the tool directly.
            tool = self._tools_by_name.get(function_name)
            if not tool:
                result = {"error": f"Unknown tool: {function_name}"}
                state_delta = {}
                action_record = {"type": "error", "function": function_name, "parameters": args}
            else:
                result = await tool.ainvoke(args)
                state_delta = {}
                action_record = {"function": function_name, "parameters": args}

            # If the tool generated an action plan, capture it so the agent can proceed
            if function_name == "generate_action_plan":
                plan_candidate = None
                if isinstance(result, dict):
                    # Some tools return { "plan": { ... } }, others may return the plan dict directly
                    plan_candidate = result.get("plan", None)
                    if plan_candidate is None and any(k in result for k in ("steps", "expected_outcomes", "objective", "situation")):
                        plan_candidate = result
                    # If plan is provided as a JSON string, attempt to parse
                    if isinstance(plan_candidate, str):
                        try:
                            plan_candidate = json.loads(plan_candidate)
                        except Exception:
                            plan_candidate = None
                if isinstance(plan_candidate, dict):
                    state_delta = {**state_delta, "current_plan": plan_candidate}

            # Record action
            action_record["result"] = result
            
            # Add observation to context (ReAct format)
            result_str = json.dumps(result)
            full_output = getattr(self.cfg, "full_output", True)
            if function_name == "generate_action_plan":
                # Always show the plan itself after the simple notice above, formatted
                plan_view = None
                if isinstance(result, dict):
                    plan_view = result.get("plan")
                    if plan_view is None and any(k in result for k in ("steps", "expected_outcomes", "objective", "situation")):
                        plan_view = result
                if isinstance(plan_view, str):
                    try:
                        plan_view = json.loads(plan_view)
                    except Exception:
                        plan_view = None
                if isinstance(plan_view, dict):
                    objective = plan_view.get("objective", "")
                    situation = plan_view.get("situation", "")
                    steps = plan_view.get("steps") or []
                    expected = plan_view.get("expected_outcomes") or []
                    lines = [
                        "📝 Action Plan:",
                        f"  • Objective: {objective}",
                        f"  • Situation: {situation}",
                        "  • Steps:",
                    ]
                    if steps:
                        for step in steps:
                            lines.append(f"    - {step}")
                    else:
                        lines.append("    - (none)")
                    lines.append("  • Expected outcomes:")
                    if expected:
                        for item in expected:
                            lines.append(f"    - {item}")
                    else:
                        lines.append("    - (none)")
                    logger.info("\n".join(lines))
                else:
                    # Fallback to raw observation if structure not recognized
                    logger.info(f"OBSERVATION: {result_str}")
            else:
                if full_output:
                    # After execution, print only the observation (no duplicate action)
                    logger.info(f"OBSERVATION: {result_str}")
                # In non-full mode do not log observations
            new_context = [f"OBSERVATION: {result_str}"]
            
            next_round = state.get("round", 0) + 1
            new_state = {
                **state_delta,
                "context": state.get("context", []) + new_context,
                "actions": state.get("actions", []) + [action_record],
                "round": next_round,
            }
            # End condition handled by routing; do not generate summaries here
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
        plan = state.get("current_plan")
        
        # Build context string
        context_text = "\n".join(context).strip()
        if not context_text:
            context_text = "(no observations yet)"

        if plan:
            steps = plan.get("steps") or []
            expected = plan.get("expected_outcomes") or []
            plan_lines = [
                f"Objective: {plan.get('objective', '')}",
                f"Situation: {plan.get('situation', '')}",
                "Steps:",
            ]
            if steps:
                plan_lines.extend(f"- {step}" for step in steps)
            else:
                plan_lines.append("- (none provided)")
            plan_lines.append("Expected outcomes:")
            if expected:
                plan_lines.extend(f"- {item}" for item in expected)
            else:
                plan_lines.append("- (none provided)")
            plan_text = "\n".join(plan_lines)
        else:
            plan_text = "No plan set."
        
        # Build user message with current situation
        user_message = (
            f"MISSION: {intent}\n\n"
            f"ROUND: {round_num}\n"
            f"CONTEXT LOG:\n{context_text}\n\n"
            f"PLAN STATUS:\n{plan_text}\n\n"
            "Respond with the next single tool call that best advances the plan."
        )

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
        
        # Initial state
        initial_state: ReactAgentState = {
            "intent": intent,
            "context": [
                f"Intent: {intent}",
                f"Initial Snapshot: {json.dumps(snapshot or {}, indent=2)}",
            ],
            "actions": [],
            "round": 0,
        }
        config = {"recursion_limit": self.cfg.recursion_limit}
        final_state: ReactAgentState = await self.graph.ainvoke(initial_state, config=config)
        logger.info(f"Agent loop completed: {len(final_state.get('actions', []))} actions taken")
        return final_state.get("actions", []), final_state.get("final_summary")