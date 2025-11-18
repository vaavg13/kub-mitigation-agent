#!/usr/bin/env python3
"""
Simple Experiment Logger
A clean, single-file logging solution for chaos experiments.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional
from .core.experiment import Experiment

logger = logging.getLogger(__name__)

class SimpleExperimentLogger:
    """Clean logger that saves complete experiment data in one call."""
    
    def __init__(self, output_dir: str, batch_id: str, prometheus_url: str = "http://localhost:9090", model_name: Optional[str] = None):
        self.batch_id = batch_id
        self.output_dir = self._setup_dir(output_dir, batch_id, model_name)
        self.prometheus_url = prometheus_url
    
    def _setup_dir(self, base_dir: str, batch_id: str, model_name: Optional[str]) -> Path:
        path = Path(base_dir)
        if model_name:
            safe_model = re.sub(r"[^a-zA-Z0-9._-]+", "-", model_name).strip("-") or "unknown"
            path /= safe_model
        path /= batch_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def log_experiment(self, experiment: Experiment) -> Path:
        """Log experiment to JSON file."""
        from .services.metrics import ExperimentMetrics
        from kub_mitigation_agent.clients.prometheus import get_prometheus_client
        
        # 1. Get base data
        log_data = experiment.to_dict()
        log_data["batch_id"] = self.batch_id
        
        # 2. Capture Timeseries Snapshot
        if experiment.started_at and experiment.duration_seconds > 0:
            try:
                prom_client = get_prometheus_client(self.prometheus_url)
                metrics_service = ExperimentMetrics(prom_client)
                
                log_data["prometheus_timeseries"] = metrics_service.get_experiment_snapshot(
                    started_at=experiment.started_at.isoformat(),
                    duration_seconds=experiment.duration_seconds,
                    namespace=experiment.namespace
                )
            except Exception as e:
                logger.warning(f"Failed to capture prometheus snapshot: {e}")
                log_data["prometheus_timeseries"] = None

        # 3. Add search shortcuts (flattened metrics)
        if experiment.recovery_metrics:
            log_data["final_success_rate"] = experiment.recovery_metrics.get("success_rate_percent")
            log_data["final_latency_p95"] = experiment.recovery_metrics.get("p95_latency_seconds")

        # 4. Save
        outfile = self.output_dir / f"{experiment.id}.json"
        with open(outfile, "w") as f:
            json.dump(log_data, f, indent=2)
            
        return outfile

    def save_batch_summary(self, batch_results: Dict[str, Any]) -> Path:
        """Save summary of all experiments in the batch."""
        summary_file = self.output_dir / "batch_summary.json"
        
        with open(summary_file, "w") as f:
            json.dump(batch_results, f, indent=2)
            
        return summary_file
