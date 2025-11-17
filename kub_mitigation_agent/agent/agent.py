#!/usr/bin/env python3
"""Unified agent wrapper that delegates to the ReAct implementation."""

from typing import Any, Dict, List, Optional, Tuple

from .config import KubernetesAgentConfig
from .react_agent import ReactAgent, AgentTraceStep
from .agent_utils import build_emergency_summary


class KubernetesAgent:
    def __init__(self, config: Optional[KubernetesAgentConfig] = None):
        self.cfg = config or KubernetesAgentConfig()
        self._agent = ReactAgent(self.cfg)

        self.is_initialized = False
        
    async def initialize(self) -> None:
        await self._agent.initialize()
        self.is_initialized = True

    async def agent_loop(
        self, 
        intent: str, 
        snapshot: Optional[Dict[str, Any]] = None,
        emergency: bool = False
    ) -> Tuple[List[AgentTraceStep], Optional[Dict[str, Any]]]:
        """
        Run the agent loop.
        
        Returns:
            Tuple of (trace, summary)
            - trace: Complete list of AgentTraceStep objects with thought-action-observation
            - summary: Final operational summary
        """
        if not self.is_initialized:
            await self.initialize()
        
        trace, summary = await self._agent.agent_loop(intent, snapshot)
        if not summary:
            action_names = [step.action for step in (trace or []) if getattr(step, "action", None)]
            summary = build_emergency_summary(
                action_names, 
                "FAILED - No summary generated", 
                ["Execution ended without summary"]
            )
        return trace, summary

    async def cleanup(self) -> None:
        await self._agent.cleanup()
        self.is_initialized = False
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()