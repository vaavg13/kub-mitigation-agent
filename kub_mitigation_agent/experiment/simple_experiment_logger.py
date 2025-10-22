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
    
    def log_experiment(
        self,
        experiment_id: str,
        batch_id: str,
        experiment_index: int,
        namespace: str,
        chaos_config: Dict[str, Any],
        started_at: str,
        completed_at: str,
        duration_seconds: float,
        phase_metrics: Dict[str, Dict[str, Any]],
        agent_actions: List[str],
        agent_success: bool,
        agent_duration_seconds: float,
        operational_summary: Optional[Dict[str, Any]],
        location_evaluation: Optional[Dict[str, Any]],
        experiment_success: bool,
        recovery_successful: bool,
        recovery_reason: str,
        error: Optional[str] = None
    ) -> Path:
        """Log complete experiment data in a single call.
        
        Args:
            experiment_id: Unique experiment identifier
            batch_id: Batch this experiment belongs to
            experiment_index: Index in batch (1-based)
            namespace: Kubernetes namespace
            chaos_config: Complete chaos configuration
            started_at: ISO timestamp of experiment start
            completed_at: ISO timestamp of experiment completion
            duration_seconds: Total experiment duration
            phase_metrics: Dict with keys "baseline", "chaos", "recovery" containing metrics
            agent_actions: List of actions taken by agent
            agent_success: Whether agent execution succeeded
            agent_duration_seconds: Agent execution duration
            operational_summary: Agent's operational summary with problem location
            location_evaluation: Evaluation of problem location identification accuracy
            experiment_success: Overall experiment success
            recovery_successful: Whether recovery was successful
            recovery_reason: Reason for recovery outcome
            error: Error message if experiment failed
            
        Returns:
            Path to saved log file
        """
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
            chaos_config=chaos_config.copy(),
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
            problem_location=operational_summary.get("problem_location") if operational_summary else None,
            location_evaluation=location_evaluation,
            experiment_success=experiment_success,
            recovery_successful=recovery_successful,
            recovery_reason=recovery_reason,
            error=error,
            final_success_rate=recovery.get("success_rate_percent"),
            final_latency_p95=recovery.get("p95_latency_seconds")
        )
        
        # Print location evaluation result
        if location_evaluation and location_evaluation.get("location_identified") is not None:
            if location_evaluation.get("location_identified"):
                print(f"  🎯 Location identified correctly: {location_evaluation.get('match_details', '')}")
            else:
                print(f"  ❌ Location not identified: {location_evaluation.get('match_details', '')}")
        
        # Save to file
        log_file = self.output_dir / f"{experiment_id}.json"
        with open(log_file, 'w') as f:
            json.dump(asdict(log), f, indent=2)
            
        logger.info(f"💾 Saved experiment log: {log_file.name}")
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
            
        logger.info(f"📊 Saved batch summary: {summary_file}")
        return summary_file 