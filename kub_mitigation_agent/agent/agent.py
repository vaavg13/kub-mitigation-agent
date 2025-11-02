#!/usr/bin/env python3
"""Unified agent wrapper that delegates to the ReAct implementation."""

from typing import Any, Dict, List, Optional, Tuple

from .config import KubernetesAgentConfig
from .react_agent import ReactAgent
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
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        
        if not self.is_initialized:
            await self.initialize()
        try:
            actions, summary = await self._agent.agent_loop(intent, snapshot)
            if not summary:
                summary = build_emergency_summary(
                    actions or [], 
                    "FAILED - No summary generated", 
                    ["Execution ended without summary"]
                )
            return actions, summary
        except (Exception,) as e:
            error_msg = str(e)
            actions: List[Dict[str, Any]] = []
            summary = build_emergency_summary(
                actions, 
                f"FAILED - {error_msg}", 
                ["Execution failed due to error"], 
                error=error_msg
            )
            return actions, summary

    async def cleanup(self) -> None:
        await self._agent.cleanup()
        self.is_initialized = False
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()