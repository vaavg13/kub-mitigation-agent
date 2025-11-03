#!/usr/bin/env python3
"""
Simple Experiment Logger
A clean, single-file logging solution for chaos experiments.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)

@dataclass
class ExperimentLog:
    """Complete log for a single experiment - all data in one place."""
    # Identification
    experiment_id: str
    batch_id: str
    experiment_index: int
    namespace: str
    
    # Timing
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    
    # Configuration - FULL chaos config stored
    chaos_config: Dict[str, Any] = field(default_factory=dict)
    
    # Phase metrics (simplified)
    baseline_metrics: Optional[Dict[str, Any]] = None
    chaos_metrics: Optional[Dict[str, Any]] = None
    recovery_metrics: Optional[Dict[str, Any]] = None
    
    # Agent execution (simplified - just actions)
    agent_actions: List[str] = field(default_factory=list)
    agent_success: bool = False
    agent_duration_seconds: Optional[float] = None
    
    # Agent operational summary (full details)
    operational_summary: Optional[Dict[str, Any]] = None
    problem_location: Optional[Dict[str, Any]] = None
    
    # Evaluation results
    location_evaluation: Optional[Dict[str, Any]] = None
    
    # Results
    experiment_success: bool = False
    recovery_successful: bool = False
    recovery_reason: str = ""
    error: Optional[str] = None
    
    # Searchable summary fields for easy querying
    chaos_mode: str = ""
    chaos_fault_type: str = ""
    chaos_intensity: str = ""
    final_success_rate: Optional[float] = None
    final_latency_p95: Optional[float] = None

class SimpleExperimentLogger:
    """Clean logger that saves complete experiment data in one call."""
    
    def __init__(self, output_dir: str, batch_id: str):
        self.output_dir = Path(output_dir) / batch_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def log_experiment(self, experiment_result: Dict[str, Any], batch_id: str) -> Path:
        """Log complete experiment using the structured experiment_result dict.

        The result is produced by the experiment runner and enriched by the batch
        runner (e.g., timing fields). Only the batch_id is provided separately.

        Returns:
            Path to saved log file
        """
        # Extract basic fields from the structured result
        experiment_id = experiment_result.get("experiment_id")
        experiment_index = experiment_result.get("index")
        namespace = experiment_result.get("namespace")
        started_at = experiment_result.get("started_at")
        completed_at = experiment_result.get("completed_at")
        duration_seconds = experiment_result.get("experiment_duration_seconds")
        chaos_config = (experiment_result.get("chaos_config") or {}).copy()
        phase_metrics = experiment_result.get("phase_metrics") or {}
        agent_actions = experiment_result.get("agent_actions") or []
        agent_success = bool(experiment_result.get("agent_success"))
        agent_duration_seconds = experiment_result.get("agent_execution_duration_seconds") or 0
        operational_summary = experiment_result.get("operational_summary")
        location_evaluation = experiment_result.get("location_evaluation")
        experiment_success = bool(experiment_result.get("success"))
        recovery_successful = bool(experiment_result.get("recovery_successful"))
        recovery_reason = experiment_result.get("recovery_reason") or ""
        error = experiment_result.get("error")

        # Extract phase metrics
        baseline = phase_metrics.get("baseline", {})
        chaos = phase_metrics.get("chaos", {})
        recovery = phase_metrics.get("recovery", {})

        # Create experiment log
        log = ExperimentLog(
            experiment_id=experiment_id,
            batch_id=batch_id,
            experiment_index=experiment_index,
            namespace=namespace,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            chaos_config=chaos_config,
            chaos_mode=chaos_config.get("mode", "unknown"),
            chaos_fault_type=chaos_config.get("fault_type", "unknown"),
            chaos_intensity=str(chaos_config.get("intensity", "unknown")),
            baseline_metrics=self._simplify_metrics(baseline),
            chaos_metrics=self._simplify_metrics(chaos),
            recovery_metrics=self._simplify_metrics(recovery),
            agent_actions=agent_actions,
            agent_success=agent_success,
            agent_duration_seconds=agent_duration_seconds,
            operational_summary=operational_summary,
            problem_location=(operational_summary.get("problem_location") if isinstance(operational_summary, dict) else None),
            location_evaluation=location_evaluation,
            experiment_success=experiment_success,
            recovery_successful=recovery_successful,
            recovery_reason=recovery_reason,
            error=error,
            final_success_rate=recovery.get("success_rate_percent"),
            final_latency_p95=recovery.get("p95_latency_seconds")
        )

        # Save to file
        log_file = self.output_dir / f"{experiment_id}.json"
        with open(log_file, 'w') as f:
            json.dump(asdict(log), f, indent=2)

        return log_file
    
    def _simplify_metrics(self, metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract essential metrics only."""
        if not metrics:
            return None
        return {
            "total_requests": metrics.get("total_requests", 0),
            "success_rate_percent": metrics.get("success_rate_percent", 0.0),
            "p95_latency_seconds": metrics.get("p95_latency_seconds", 0.0),
        }
        
    def save_batch_summary(self, batch_results: Dict[str, Any]) -> Path:
        """Save a simple batch summary."""
        summary_file = self.output_dir / "batch_summary.json"
        
        # Calculate location identification stats
        total_location_checks = 0
        correct_locations = 0
        for exp in batch_results.get("experiments", []):
            location_eval = exp.get("location_evaluation")
            if location_eval and location_eval.get("location_identified") is not None:
                total_location_checks += 1
                if location_eval.get("location_identified"):
                    correct_locations += 1
        
        location_accuracy = (correct_locations / total_location_checks * 100) if total_location_checks > 0 else 0
        
        # Create simplified summary
        summary = {
            "batch_id": batch_results.get("batch_id"),
            "total_experiments": batch_results.get("total_experiments", 0),
            "successful_experiments": batch_results.get("successful_experiments", 0),
            "failed_experiments": batch_results.get("failed_experiments", 0),
            "location_identification_accuracy": location_accuracy,
            "correct_location_identifications": correct_locations,
            "total_location_checks": total_location_checks,
            "started_at": batch_results.get("started_at"),
            "completed_at": batch_results.get("completed_at"),
            "experiments": [
                {
                    "id": exp.get("experiment_id"),
                    "chaos": f"{exp['chaos_config']['mode']}_{exp['chaos_config']['fault_type']}",
                    "success": exp.get("success", False),
                    "agent_actions": len(exp.get("agent_actions", [])),
                    "recovery_successful": exp.get("recovery_successful", False),
                    "location_identified": exp.get("location_evaluation", {}).get("location_identified") if exp.get("location_evaluation") else None
                }
                for exp in batch_results.get("experiments", [])
            ]
        }
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        return summary_file 