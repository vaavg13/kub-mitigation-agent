#!/usr/bin/env python3
"""
ReAct Agent - Reason + Act Approach
Simplified agent that uses a pure Python loop without complex graph logic.
"""
import os
import json
import logging
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, BaseMessage, ToolMessage

from .config import KubernetesAgentConfig
from .llm_provider import get_llm
from .prompts import get_system_prompt, DEFAULT_INTENT
from kub_mitigation_agent.mcp import MCPManager, get_kubernetes_config
from .tools import NON_MCP_TOOLS, set_warmup_end_timestamp

logger = logging.getLogger(__name__)


@dataclass
class AgentTraceStep:
    """
    Single step in agent execution trace.
    Can now support multiple parallel actions in a single step.
    """
    step_number: int
    thought: Optional[str]
    # action/action_args/observation are kept for backward compat, but logic should use list versions if present
    action: str  # Deprecated in favor of actions list
    action_args: Dict[str, Any] # Deprecated
    observation: Any # Deprecated
    
    # New fields for parallel execution support
    actions: List[Dict[str, Any]] = field(default_factory=list)  # List of {name, args}
    observations: List[Any] = field(default_factory=list)        # List of results corresponding to actions
    
    timestamp: float = field(default_factory=time.time)


class ReactAgent:
    """
    ReAct-based Kubernetes agent.
    
    Unified agent that manages the MCP client and executes the ReAct loop.
    Replaces the old split between KubernetesAgent (wrapper) and ReactAgent (logic).
    """
    
    def __init__(self, config: Optional[KubernetesAgentConfig] = None):
        self.cfg = config or KubernetesAgentConfig()
        self.llm = None
        self.mcp_manager: Optional[MCPManager] = None
        self.is_initialized = False
        
        # Internal state for tracing
        self._trace: List[AgentTraceStep] = []
        self._current_round = 0

        # Tools will be populated during initialization
        self._tools_by_name = {}
        
        # Optional callback for real-time step emission (for UI)
        # Signature: callback(step_number: int, thought: str, actions: list, observations: list)
        self.on_step_callback: Optional[callable] = None

    async def initialize(self):
        """Initialize MCP manager and LLM connection."""
        if self.is_initialized:
            return
        
        logger.info("Initializing agent...")
        
        # 1. Setup MCP Manager with server configurations
        server_configs = get_kubernetes_config(custom_command=self.cfg.mcp_server_command)
        # Future: Add more MCP servers here (prometheus, etc.)
        
        self.mcp_manager = MCPManager(
            server_configs,
            enable_logging=True,
            enable_progress=True,
        )
        
        # 2. Get MCP tools (kubectl operations from MCP server)
        mcp_tools = await self.mcp_manager.get_tools()
        logger.info(f"Loaded {len(mcp_tools)} MCP tools")
        
        # 3. Combine MCP tools with non-MCP tools (prometheus, core utils)
        all_tools = NON_MCP_TOOLS + mcp_tools
        logger.info(f"Total tools available: {len(all_tools)}")
        
        # 4. Setup tools lookup
        self._tools_by_name = {t.name: t for t in all_tools}
        
        # 5. Initialize LLM with all tools
        llm_base = get_llm(self.cfg)
        self.llm = llm_base.bind_tools(all_tools)
        
        # 6. Setup warmup timestamp for prometheus queries
        set_warmup_end_timestamp(os.environ.get("KMA_WARMUP_END_TS"))
        
        self.is_initialized = True
        logger.info("Agent initialized successfully")

    async def cleanup(self):
        """Stop MCP manager and clean up resources."""
        if self.mcp_manager:
            await self.mcp_manager.cleanup()
        self.is_initialized = False

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    def _build_initial_messages(self, intent: str, snapshot: Optional[Dict[str, Any]]) -> List[BaseMessage]:
        """Construct the initial prompt history."""
        context_str = json.dumps({
            "mission": intent,
            "initial_snapshot": snapshot or {},
            "instruction": "Respond with the next single tool call that best advances the plan."
        }, indent=2)
        
        return [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=context_str)
        ]

    async def agent_loop(
        self, 
        intent: Optional[str] = None, 
        snapshot: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[AgentTraceStep], Dict[str, Any]]:
        """
        Run the main ReAct loop.
        
        Args:
            intent: The mission/objective (optional, uses DEFAULT_INTENT if None)
            snapshot: Initial system state
            
        Returns:
            (trace, summary)
        """
        if not self.is_initialized:
            await self.initialize()
            
        # Configure logger to respect show_observations
        # We need to access the root handler setup or re-configure it
        # For now, we assume setup_agent_logging is called externally or we can try to update it
        if self.mcp_manager: # Just a proxy check if we are running
             # Re-configure logger if needed, or assume the runner set it up.
             # But the cleanest way is to pass config to the formatter if it was already set up.
             # Since we can't easily access the handler instance without digging, we'll re-run setup
             from .agent_formatter import setup_agent_logging
             setup_agent_logging(show_observations=self.cfg.show_observations)
            
        # Use default intent if none provided
        intent = intent or DEFAULT_INTENT
        
        logger.info(f"Starting agent loop for intent: {intent}")
        self._trace = []
        self._current_round = 0
        
        messages = self._build_initial_messages(intent, snapshot)
        
        final_summary = None
        
        try:
            while self._current_round < self.cfg.max_rounds:
                self._current_round += 1
                logger.info(f"Agent thinking (round {self._current_round})")
                
                # 1. LLM Call (Think)
                response: AIMessage = await self.llm.ainvoke(messages)
                
                # Handle Single-Tool Constraint (Optional)
                if not self.cfg.allow_parallel_tools and response.tool_calls and len(response.tool_calls) > 1:
                    logger.info(f"Parallel tools disabled: Selecting first tool from {len(response.tool_calls)} calls")
                    # Truncate to only the first tool call to avoid API errors with unfulfilled calls
                    response.tool_calls = [response.tool_calls[0]]
                    
                messages.append(response)
                
                # Check if tool call exists
                if not response.tool_calls:
                    logger.warning("Agent did not call a tool. Retrying with guidance...")
                    messages.append(HumanMessage(content="SYSTEM: You did not call a tool. Please analyze the situation and call a valid tool."))
                    continue
                
                # 2. Process Tool Calls
                # We iterate through all tool calls to satisfy API requirements.
                # We aggregate them into a single trace step to match the "Round" concept.
                
                thought = response.content if response.content else None
                logger.info(f"THOUGHT: {thought or '(none)'}")
                
                step_actions = []
                step_observations = []
                found_summary = False
                
                # First, log all actions that are about to happen
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    logger.info(f"ACTION: {tool_name}({json.dumps(tool_args)})")
                    step_actions.append({"name": tool_name, "args": tool_args})

                # Then execute them and collect results
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_id = tool_call["id"]
                    
                    # 3. Execute Tool (Act)
                    tool_result = await self._execute_tool(tool_name, tool_args)
                    step_observations.append(tool_result)
                    
                    logger.info(f"OBSERVATION: {json.dumps(tool_result)}")
                    
                    # 5. Add Observation to History
                    messages.append(ToolMessage(
                        content=json.dumps(tool_result),
                        tool_call_id=tool_id,
                        name=tool_name
                    ))
                    
                    # 6. Check for Terminal State
                    if tool_name == "generate_operational_summary":
                        if isinstance(tool_result, dict):
                            final_summary = tool_result
                        else:
                            final_summary = {"status": "completed", "raw_output": tool_result}
                        found_summary = True
                
                # 4. Record Aggregated Trace Step
                if step_actions:
                    primary_action = step_actions[0]
                    step = AgentTraceStep(
                        step_number=len(self._trace) + 1,
                        thought=thought,
                        # Legacy fields - use first action
                        action=primary_action["name"],
                        action_args=primary_action["args"],
                        observation=step_observations[0] if step_observations else None,
                        # New fields
                        actions=step_actions,
                        observations=step_observations
                    )
                    self._trace.append(step)
                    
                    # Emit step event for UI if callback is set
                    if self.on_step_callback:
                        try:
                            self.on_step_callback(
                                step.step_number,
                                thought,
                                step_actions,
                                step_observations
                            )
                        except Exception as e:
                            logger.warning(f"Step callback failed: {e}")
                
                if found_summary:
                    break

            if not final_summary:
                # Loop finished without summary
                logger.warning("Agent reached max rounds without summary.")
                final_summary = self._build_emergency_summary(
                    [s.action for s in self._trace],
                    "FAILED - Max rounds reached",
                    ["Agent execution timed out"]
                )

            return self._trace, final_summary

        except Exception as e:
            print(f"❌ Agent loop crashed with exception: {e}")
            traceback.print_exc()
            logger.exception("Agent loop failed with exception")
            emergency_summary = self._build_emergency_summary(
                [s.action for s in self._trace],
                f"FAILED - {type(e).__name__}",
                [str(e)],
                error=str(e)
            )
            return self._trace, emergency_summary

    async def _execute_tool(self, name: str, args: Dict[str, Any]) -> Any:
        """Execute a tool by name safely."""
        tool = self._tools_by_name.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}"}
        
        try:
            return await tool.ainvoke(args)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {
                "error": f"{type(e).__name__}: {str(e)}",
                "tool": name
            }

    def _build_emergency_summary(self, actions: List[str], status: str, results: List[str], error: Optional[str] = None) -> Dict[str, Any]:
        """Build a fallback summary when the agent fails to produce one."""
        summary: Dict[str, Any] = {
            "objective": "Agent execution incomplete",
            "actions_completed": actions,
            "results_achieved": results,
            "status": status,
            "problem_location": [],
            "success": False,
        }
        if error:
            summary["error"] = error
        return summary
