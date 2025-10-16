#!/usr/bin/env python3
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langsmith import trace

from .config import KubernetesAgentConfig
from .llm_provider import get_llm
from .system_prompt import get_system_prompt
from .reasoning_prompts import get_reasoning_summary_prompt
from .tool_schemas import get_all_tool_call_models
from .mcp_client import MCPClient
from .tools_router import ToolsRouter

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    intent: str
    snapshot: Dict[str, Any]
    context: List[str]
    actions_taken: List[Dict[str, Any]]
    plan: Dict[str, Any]
    plan_history: List[Dict[str, Any]]
    current_step_index: int
    final_summary: Dict[str, Any]
    round: int
    max_rounds: int
    decision: Dict[str, Any]


class GraphKubernetesAgent:
    def __init__(self, cfg: KubernetesAgentConfig):
        self.cfg = cfg
        self.llm = None
        self.llm_with_tools = None
        self.mcp_client: Optional[MCPClient] = None
        self.router: Optional[ToolsRouter] = None
        self.graph = None
        self.is_initialized = False

    async def initialize(self):
        if self.is_initialized:
            return
        # MCP
        self.mcp_client = MCPClient(self.cfg.mcp_server_command)
        await self.mcp_client.start()
        await self.mcp_client.initialize()
        # LLM
        self.llm = get_llm(self.cfg)
        tool_models = get_all_tool_call_models()
        self.llm_with_tools = self.llm.bind_tools(tool_models)
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

        async def controller(state: AgentState) -> AgentState:
            messages = self._build_messages(state)
            # async with trace("agent-controller-llm-step"):
            ai: AIMessage = await self.llm_with_tools.ainvoke(messages)
            decision: Dict[str, Any] = {"content": (ai.content or "").strip()}
            if getattr(ai, "tool_calls", None):
                # Prefer the first tool call for this step; normalize across providers
                tc = ai.tool_calls[0]
                tool_name: Optional[str] = None
                tool_args: Any = {}
                if isinstance(tc, dict):
                    # Common LC shape: {"name": str, "args": dict}
                    tool_name = tc.get("name")
                    tool_args = tc.get("args", {})
                    # OpenAI raw shape proxied by some LC versions: {"function": {"name": str, "arguments": str|dict}}
                    fn = tc.get("function") if not tool_name and "function" in tc else tc.get("function")
                    if isinstance(fn, dict):
                        tool_name = tool_name or fn.get("name")
                        tool_args = fn.get("arguments", tool_args)
                else:
                    # Object-like
                    tool_name = getattr(tc, "name", None)
                    tool_args = getattr(tc, "args", {})

                # If arguments are a JSON string, parse them
                if isinstance(tool_args, str):
                    try:
                        import json as _json
                        tool_args = _json.loads(tool_args)
                    except Exception:
                        tool_args = {}

                decision = {"tool": tool_name, "arguments": tool_args or {}}
            return {"decision": decision}

        async def tool_exec(state: AgentState) -> AgentState:
            decision = state.get("decision", {})
            if "tool" not in decision:
                return {}
            function_name = decision["tool"]
            args = decision.get("arguments", {})
            result, state_delta, action_record = await self.router.execute(function_name, args, state)
            canonical_function = action_record.get("function", function_name)
            new_context_items: List[str] = [f"Executed {function_name}", f"Result: {json.dumps(result)[:2000]}"]
            new_actions = [action_record]
            # Planning bookkeeping
            if canonical_function == "create_action_plan":
                plan_history = list(state.get("plan_history", []))
                if state_delta.get("plan"):
                    plan_history.append(state_delta["plan"])
                state_delta["plan_history"] = plan_history
            # Termination on summary
            done = False
            if (
                canonical_function == "generate_operational_summary"
                or (isinstance(state_delta, dict) and "final_summary" in state_delta)
                or (isinstance(result, dict) and bool(result.get("operation_complete")))
            ):
                done = True
            return {
                **state_delta,
                "context": state.get("context", []) + new_context_items,
                "actions_taken": state.get("actions_taken", []) + new_actions,
                "round": state.get("round", 0) + 1,
                "done": done,  # transient flag for routing
            }

        async def reasoning(state: AgentState) -> AgentState:
            if not self.cfg.show_reasoning:
                return {}
            # Build reasoning prompt and append to context
            context_text = "\n".join(state.get("context", [])[-5:])
            last_action = state.get("actions_taken", [])[-1] if state.get("actions_taken") else {}
            last_function = last_action.get("function", last_action.get("type", "unknown"))
            last_result_preview = state.get("context", [])[-1] if state.get("context") else ""
            prompt = get_reasoning_summary_prompt(
                context_text=context_text,
                last_function=last_function,
                last_result_preview=last_result_preview,
            )
            # async with trace("agent-reasoning-llm-step"):
            ai: AIMessage = await self.llm.ainvoke([HumanMessage(content=prompt)])
            reasoning_text = (ai.content or "").strip()
            if not reasoning_text:
                return {}
            return {"context": state.get("context", []) + [f"CRITICAL_ANALYSIS: {reasoning_text}"]}

        graph.add_node("controller", controller)
        graph.add_node("tool_exec", tool_exec)
        graph.add_node("reasoning", reasoning)

        def route_after_controller(state: AgentState):
            decision = state.get("decision", {})
            if "tool" in decision:
                return "tool_exec"
            return "controller"  # ask again if only text

        def route_after_tool(state: AgentState):
            # If the last tool produced a final summary or set the done flag, terminate.
            if state.get("done") or state.get("final_summary"):
                return "END"
            # If out of rounds without a summary, force summary by routing to controller with a system nudge
            if state.get("round", 0) >= state.get("max_rounds", self.cfg.max_rounds):
                forced = "SYSTEM: Maximum rounds reached. You MUST now call generate_operational_summary to conclude."
                state["context"] = state.get("context", []) + [forced]
                return "controller"
            return "reasoning"

        graph.set_entry_point("controller")
        graph.add_conditional_edges(
            "controller",
            route_after_controller,
            {
                "controller": "controller",
                "tool_exec": "tool_exec",
            },
        )
        graph.add_conditional_edges(
            "tool_exec",
            route_after_tool,
            {
                "reasoning": "reasoning",
                "controller": "controller",
                "END": END,
            },
        )
        graph.add_edge("reasoning", "controller")

        return graph.compile()

    def _build_messages(self, state: AgentState) -> List[Any]:
        context_text = "\n".join(state.get("context", []))
        plan_guidance = ""
        plan = state.get("plan")
        if plan and plan.get("status") == "active":
            steps = plan.get("steps", [])
            idx = state.get("current_step_index", 0)
            if idx < len(steps):
                plan_guidance = f"\n\nCURRENT PLAN GUIDANCE:\nObjective: {plan.get('objective')}\nCurrent Step ({idx + 1}/{len(steps)}): {steps[idx]}\n"
            else:
                plan_guidance = f"\n\nPLAN STATUS: All planned steps completed. Objective: {plan.get('objective')}\n"
        messages: List[Any] = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=f"Based on the following context, what should you do next?\n\n{context_text}{plan_guidance}"),
        ]
        return messages

    async def agent_loop(self, intent: str, snapshot: Optional[Dict[str, Any]] = None):
        if not self.is_initialized:
            await self.initialize()
        initial_state: AgentState = {
            "intent": intent,
            "snapshot": snapshot or {},
            "context": [f"Intent: {intent}", f"Snapshot: {json.dumps(snapshot or {}, indent=2)}"],
            "actions_taken": [],
            "plan_history": [],
            "current_step_index": 0,
            "round": 0,
            "max_rounds": self.cfg.max_rounds,
        }
        # async with trace("kube-mitigation-agent"):
        final_state: AgentState = await self.graph.ainvoke(initial_state)
        return final_state.get("actions_taken", []), final_state.get("final_summary")
