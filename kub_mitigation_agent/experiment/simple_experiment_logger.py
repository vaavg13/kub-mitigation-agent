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
    """Simplified logger that saves complete experiment data once."""
    
    def __init__(self, output_dir: str, batch_id: str):
        self.output_dir = Path(output_dir) / batch_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.current_log: Optional[ExperimentLog] = None
        self.agent_start_time: Optional[float] = None
        
    def start_experiment(self, experiment_id: str, batch_id: str, experiment_index: int,
                        chaos_config: Dict[str, Any], namespace: str) -> None:
        """Start logging a new experiment."""
        self.current_log = ExperimentLog(
            experiment_id=experiment_id,
            batch_id=batch_id,
            experiment_index=experiment_index,
            namespace=namespace,
            started_at=datetime.now().isoformat(),
            chaos_config=chaos_config.copy(),  # Store FULL chaos config
            # Extract searchable fields
            chaos_mode=chaos_config.get("mode", "unknown"),
            chaos_fault_type=chaos_config.get("fault_type", "unknown"),
            chaos_intensity=str(chaos_config.get("intensity", "unknown"))
        )
        logger.info(f"📝 Started logging experiment: {experiment_id}")
        
    def log_phase_metrics(self, phase: str, metrics: Dict[str, Any]) -> None:
        """Log metrics for a phase (baseline, chaos, recovery)."""
        if not self.current_log:
            logger.warning(f"No active experiment log for phase: {phase}")
            return
            
        # Store only essential metrics
        simplified_metrics = {
            "total_requests": metrics.get("total_requests", 0),
            "success_rate_percent": metrics.get("success_rate_percent", 0.0),
            "p95_latency_seconds": metrics.get("p95_latency_seconds", 0.0),
            "timestamp": datetime.now().isoformat()
        }
        
        if phase == "baseline":
            self.current_log.baseline_metrics = simplified_metrics
        elif phase == "chaos":
            self.current_log.chaos_metrics = simplified_metrics
        elif phase == "recovery":
            self.current_log.recovery_metrics = simplified_metrics
            # Update final metrics for searchability
            self.current_log.final_success_rate = simplified_metrics["success_rate_percent"]
            self.current_log.final_latency_p95 = simplified_metrics["p95_latency_seconds"]
            
    def start_agent_execution(self) -> None:
        """Mark the start of agent execution."""
        if self.current_log:
            self.agent_start_time = datetime.now().timestamp()
            
    def complete_agent_execution(self, actions: List[str], success: bool = False, 
                               operational_summary: Optional[Dict[str, Any]] = None) -> None:
        """Record agent completion with actions taken and operational summary."""
        if not self.current_log:
            logger.warning("No active experiment log for agent completion")
            return
            
        self.current_log.agent_actions = actions
        self.current_log.agent_success = success
        
        if self.agent_start_time:
            self.current_log.agent_duration_seconds = datetime.now().timestamp() - self.agent_start_time
            
        # Store full operational summary if provided
        if operational_summary:
            self.current_log.operational_summary = operational_summary
            # Extract problem location for easy access
            if "problem_location" in operational_summary:
                self.current_log.problem_location = operational_summary["problem_location"]
            
    def complete_experiment(self, success: bool, recovery_successful: bool = False, 
                          recovery_reason: str = "", error: Optional[str] = None) -> Path:
        """Complete the experiment and save the log."""
        if not self.current_log:
            raise ValueError("No active experiment log to complete")
            
        # Update final fields
        self.current_log.completed_at = datetime.now().isoformat()
        self.current_log.experiment_success = success
        self.current_log.recovery_successful = recovery_successful
        self.current_log.recovery_reason = recovery_reason
        self.current_log.error = error
        
        # Calculate duration
        start_time = datetime.fromisoformat(self.current_log.started_at)
        end_time = datetime.fromisoformat(self.current_log.completed_at)
        self.current_log.duration_seconds = (end_time - start_time).total_seconds()
        
        # Save to single file
        log_file = self.output_dir / f"{self.current_log.experiment_id}.json"
        
        # Convert to dict and save
        log_dict = asdict(self.current_log)
        with open(log_file, 'w') as f:
            json.dump(log_dict, f, indent=2)
            
        logger.info(f"💾 Saved experiment log: {log_file}")
        
        # Clear current log
        self.current_log = None
        self.agent_start_time = None
        
        return log_file
        
    def save_batch_summary(self, batch_results: Dict[str, Any]) -> Path:
        """Save a simple batch summary."""
        summary_file = self.output_dir / "batch_summary.json"
        
        # Create simplified summary
        summary = {
            "batch_id": batch_results.get("batch_id"),
            "total_experiments": batch_results.get("total_experiments", 0),
            "successful_experiments": batch_results.get("successful_experiments", 0),
            "failed_experiments": batch_results.get("failed_experiments", 0),
            "started_at": batch_results.get("started_at"),
            "completed_at": batch_results.get("completed_at"),
            "experiments": [
                {
                    "id": exp.get("experiment_id"),
                    "chaos": f"{exp['chaos_config']['mode']}_{exp['chaos_config']['fault_type']}",
                    "success": exp.get("success", False),
                    "agent_actions": exp.get("results", {}).get("agent_actions", []) if exp.get("results") else [],
                    "recovery_successful": exp.get("recovery_successful", False),
                    "problem_location": exp.get("problem_location", {})
                }
                for exp in batch_results.get("experiments", [])
            ]
        }
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
            
        logger.info(f"📊 Saved batch summary: {summary_file}")
        return summary_file 