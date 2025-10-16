#!/usr/bin/env python3
"""
LangGraph-based Kubernetes Agent wrapper.
This file keeps the `KubernetesAgent` interface while delegating to the graph agent.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
from ..shared.types import MetricViolation
from .config import KubernetesAgentConfig

from .config import KubernetesAgentConfig
from .graph_agent import GraphKubernetesAgent


class KubernetesAgent:
    def __init__(self, config: Optional[Union[Dict[str, Any], KubernetesAgentConfig]] = None):
        # Accept either a prebuilt config model or a YAML-style dict; default to env-driven
        if isinstance(config, KubernetesAgentConfig):
            self.cfg = config
        elif isinstance(config, dict):
            # Allow callers to pass a YAML-mapped dict; prefer using KubernetesAgentConfig.from_yaml_dict upstream
            try:
                self.cfg = KubernetesAgentConfig.from_yaml_dict(config)
            except Exception:
                # Fallback: instantiate with defaults if mapping fails
                self.cfg = KubernetesAgentConfig()
        else:
            self.cfg = KubernetesAgentConfig()
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

    # --- Convenience API for handling violations directly ---
    DEFAULT_INTENT_TEMPLATE = """
Handle {metric_type} issue in namespace {namespace} (deployment: {deployment_name}): 
current value is {metric_value}, threshold is {threshold_value}
"""

    async def handle_violation(self, violation: MetricViolation, intent_template: Optional[str] = None) -> Dict[str, Any]:
        template = intent_template or self.DEFAULT_INTENT_TEMPLATE
        intent = template.format(
            namespace=violation.namespace,
            deployment_name=violation.deployment_name or "all_deployments",
            metric_type=violation.metric_type.value,
            metric_value=violation.actual_value,
            threshold_value=violation.threshold_value,
            operator=violation.operator.value,
            unit=violation.unit or "",
            loop_id=getattr(violation, 'loop_id', 'unknown')
        )

        context = {
            "violation": {
                "loop_id": getattr(violation, 'loop_id', 'unknown'),
                "namespace": violation.namespace,
                "deployment_name": violation.deployment_name,
                "metric_type": violation.metric_type.value,
                "actual_value": violation.actual_value,
                "threshold_value": violation.threshold_value,
                "operator": violation.operator.value,
                "unit": violation.unit,
                "description": violation.description,
                "timestamp": violation.timestamp.isoformat()
            }
        }

        actions_taken, final_summary = await self.agent_loop(intent, context)

        return {
            "status": "success",
            "intent": intent,
            "actions_taken": actions_taken,
            "final_summary": final_summary,
            "violation_details": {
                "namespace": violation.namespace,
                "deployment_name": violation.deployment_name,
                "metric_type": violation.metric_type.value,
                "actual_value": violation.actual_value,
                "threshold_value": violation.threshold_value,
            },
        }