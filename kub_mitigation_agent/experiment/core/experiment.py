from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

@dataclass
class Experiment:
    """
    A single chaos experiment.
    
    This object IS both:
    - The working state (mutated by phase functions)
    - The final result (serialized via to_dict())
    
    Lifecycle: create with config -> phases mutate it -> save to disk
    """
    
    # === CONFIGURATION (immutable, set at creation) ===
    namespace: str
    anomaly: Any  # Anomaly instance
    config: Dict[str, Any]  # Full experiment config
    agent_config: Optional[Any] = None
    
    # === IDENTITY (set by batch runner) ===
    id: str = ""  # Generated experiment ID
    index: int = 0 # Experiment index in batch
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    
    # === RESOURCES (managed by phases, cleaned up) ===
    traffic_generator: Optional[Any] = None
    anomaly_handle: Optional[Any] = None
    
    # === COLLECTED METRICS (populated during measurement phases) ===
    baseline_metrics: Optional[Dict[str, Any]] = None
    chaos_metrics: Optional[Dict[str, Any]] = None
    recovery_metrics: Optional[Dict[str, Any]] = None
    
    # === AGENT RESULTS (from mitigation phase) ===
    agent_trace: List[Dict[str, Any]] = field(default_factory=list)
    operational_summary: Optional[Dict[str, Any]] = None
    agent_success: bool = False
    agent_duration_seconds: float = 0.0
    
    # === EVALUATIONS (computed after phases complete) ===
    recovery_evaluation: Optional[Dict[str, Any]] = None
    location_evaluation: Optional[Dict[str, Any]] = None
    
    # === STATUS (updated throughout execution) ===
    success: bool = False
    interrupted: bool = False
    error: Optional[str] = None
    
    @property
    def duration_seconds(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging (matches current log format)."""
        
        # Helper to safely extract trace dicts
        clean_trace = []
        for step in self.agent_trace:
            if hasattr(step, "__dataclass_fields__"):
                clean_trace.append(asdict(step))
            elif isinstance(step, dict):
                clean_trace.append(step)
            else:
                clean_trace.append(str(step))

        return {
            "experiment_id": self.id,
            "experiment_index": self.index,
            "namespace": self.namespace,
            "chaos_config": self.anomaly.get_info() if self.anomaly else {},
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "agent_execution_duration_seconds": self.agent_duration_seconds,
            "baseline_metrics": self.baseline_metrics,
            "chaos_metrics": self.chaos_metrics,
            "recovery_metrics": self.recovery_metrics,
            "agent_trace": clean_trace,
            "operational_summary": self.operational_summary,
            "agent_success": self.agent_success,
            "recovery_evaluation": self.recovery_evaluation,
            "location_evaluation": self.location_evaluation,
            "success": self.success,
            "interrupted": self.interrupted,
            "error": self.error,
        }
