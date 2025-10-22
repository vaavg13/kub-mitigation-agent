#!/usr/bin/env python3
"""
LangGraph-based Kubernetes Agent wrapper.
This file keeps the `KubernetesAgent` interface while delegating to the graph agent.
"""

from typing import Any, Dict, List, Optional, Tuple

from .config import KubernetesAgentConfig
from .graph_agent import GraphKubernetesAgent
from .react_agent import ReactAgent


class KubernetesAgent:
    def __init__(self, config: Optional[KubernetesAgentConfig] = None):
        self.cfg = config or KubernetesAgentConfig()

        # Initialize the appropriate agent based on the configuration
        if self.cfg.agent_type == "react":
            self._agent = ReactAgent(self.cfg)
        else:
            self._agent = GraphKubernetesAgent(self.cfg)

        self.is_initialized = False
        
    async def initialize(self) -> None:
        await self._agent.initialize()
        self.is_initialized = True

    async def agent_loop(self, intent: str, snapshot: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not self.is_initialized:
            await self.initialize()
        return await self._agent.agent_loop(intent, snapshot)

    async def cleanup(self) -> None:
        await self._agent.cleanup()
        self.is_initialized = False
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()