"""
Shared types and data structures for the NL Interface system.
"""

from typing import Optional
from datetime import datetime
from enum import Enum
from dataclasses import dataclass

class MetricType(str, Enum):
    """Supported metric types for monitoring."""
    POD_CPU = "pod_cpu"
    POD_MEMORY = "pod_memory" 
    NODE_CPU = "node_cpu"
    NODE_MEMORY = "node_memory"
    ISTIO_LATENCY = "istio_latency"

class ComparisonOperator(str, Enum):
    """Comparison operators for threshold evaluation."""
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    EQUAL = "=="
    NOT_EQUAL = "!="

@dataclass
class MetricViolation:
    """Represents a metric threshold violation."""
    loop_id: str
    namespace: str
    deployment_name: Optional[str]
    metric_type: MetricType
    actual_value: float
    threshold_value: float
    operator: ComparisonOperator
    unit: Optional[str]
    description: Optional[str]
    timestamp: datetime
    consecutive_violations: int = 1
    
    def __str__(self):
        target = f"{self.namespace}/{self.deployment_name}" if self.deployment_name else self.namespace
        return (f"Violation in {self.loop_id}: {target} {self.metric_type.value} "
                f"{self.actual_value} {self.operator.value} {self.threshold_value}") 