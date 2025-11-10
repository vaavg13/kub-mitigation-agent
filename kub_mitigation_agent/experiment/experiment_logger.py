#!/usr/bin/env python3
"""
Simple Experiment Logger
A clean, single-file logging solution for chaos experiments.
"""

import json
import logging
from datetime import datetime, timedelta
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
    
    # Agent execution - complete trace with thought-action-observation
    agent_trace: List[Dict[str, Any]] = field(default_factory=list)
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
    interrupted: bool = False  # True if experiment was interrupted by user (Ctrl+C)
    
    # Searchable summary fields for easy querying
    chaos_mode: str = ""
    chaos_fault_type: str = ""
    chaos_intensity: str = ""
    final_success_rate: Optional[float] = None
    final_latency_p95: Optional[float] = None
    
    # Prometheus timeseries snapshot
    prometheus_timeseries: Optional[Dict[str, Any]] = None
    
    def get_completed_actions(self) -> List[str]:
        """
        Extract list of completed action names from the trace.
        
        Returns:
            List of action names in execution order
        """
        return [step["action"] for step in self.agent_trace if "action" in step]
    
    def get_trace_step(self, step_number: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific trace step by its step number.
        
        Args:
            step_number: The step number (1-indexed)
            
        Returns:
            The trace step dict or None if not found
        """
        for step in self.agent_trace:
            if step.get("step_number") == step_number:
                return step
        return None
    
    def get_trace_by_action(self, action_name: str) -> List[Dict[str, Any]]:
        """
        Get all trace steps that used a specific action.
        
        Args:
            action_name: The action/tool name to filter by
            
        Returns:
            List of trace steps that used this action
        """
        return [step for step in self.agent_trace if step.get("action") == action_name]
    
    def get_trace_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the trace execution.
        
        Returns:
            Dictionary with trace statistics and overview
        """
        if not self.agent_trace:
            return {
                "total_steps": 0,
                "actions_taken": [],
                "had_thoughts": 0,
                "duration_seconds": 0
            }
        
        actions = self.get_completed_actions()
        thoughts = sum(1 for step in self.agent_trace if step.get("thought"))
        
        # Calculate duration if we have timestamps
        start_time = self.agent_trace[0].get("timestamp", 0)
        end_time = self.agent_trace[-1].get("timestamp", 0)
        duration = end_time - start_time if start_time and end_time else 0
        
        return {
            "total_steps": len(self.agent_trace),
            "actions_taken": actions,
            "had_thoughts": thoughts,
            "duration_seconds": round(duration, 2)
        }

class SimpleExperimentLogger:
    """Clean logger that saves complete experiment data in one call."""
    
    def __init__(self, output_dir: str, batch_id: str, prometheus_url: str = "http://localhost:9090"):
        self.output_dir = Path(output_dir) / batch_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.prometheus_url = prometheus_url
    
    def snapshot_prometheus_metrics(
        self, 
        started_at: str, 
        duration_seconds: float,
        namespace: str
    ) -> Dict[str, Any]:
        """Capture Prometheus timeseries for the full experiment duration.
        
        Captures:
        - Istio ingress gateway latency (P95) and success rate timeseries
        - Node-level CPU usage (pod aggregates per node + actual non-idle CPU)
        - Node-level memory usage
        
        Args:
            started_at: ISO timestamp of experiment start
            duration_seconds: Total experiment duration
            namespace: Kubernetes namespace
            
        Returns:
            Dictionary with timeseries data and metadata
        """
        from kub_mitigation_agent.clients.prometheus_client import get_prometheus_tool
        import requests
        
        prom = get_prometheus_tool(self.prometheus_url)
        step = "15s"
        
        # Calculate time range
        start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
        end_time = start_time + timedelta(seconds=duration_seconds)
        
        # Query parameters
        params_base = {
            'start': start_time.timestamp(),
            'end': end_time.timestamp(),
            'step': step
        }
        
        # === INGRESS GATEWAY METRICS ===
        
        # P95 Latency timeseries
        latency_query = '''histogram_quantile(0.95,
            sum(rate(istio_request_duration_milliseconds_bucket{
                reporter="source",
                source_workload="istio-ingressgateway",
                source_workload_namespace="istio-system"
            }[1m]))
            by (le)
        )'''
        
        # Success rate timeseries (requires calculating ratio)
        total_requests_query = '''sum(rate(istio_requests_total{
            reporter="source",
            source_workload="istio-ingressgateway",
            source_workload_namespace="istio-system"
        }[1m]))'''
        
        success_requests_query = '''sum(rate(istio_requests_total{
            reporter="source",
            source_workload="istio-ingressgateway",
            source_workload_namespace="istio-system",
            response_code=~"[23].*"
        }[1m]))'''
        
        # Execute ingress queries
        latency_response = requests.get(
            f"{self.prometheus_url}/api/v1/query_range",
            params={**params_base, 'query': latency_query}
        ).json()
        
        total_response = requests.get(
            f"{self.prometheus_url}/api/v1/query_range",
            params={**params_base, 'query': total_requests_query}
        ).json()
        
        success_response = requests.get(
            f"{self.prometheus_url}/api/v1/query_range",
            params={**params_base, 'query': success_requests_query}
        ).json()
        
        # Parse ingress latency
        ingress_latency = []
        if latency_response.get('status') == 'success' and latency_response['data']['result']:
            for timestamp, value_ms in latency_response['data']['result'][0]['values']:
                latency_seconds = float(value_ms) / 1000.0
                ingress_latency.append({
                    'timestamp': timestamp,
                    'value': round(latency_seconds, 3)
                })
        
        # Parse and calculate success rate timeseries
        ingress_success_rate = []
        total_values = {}
        success_values = {}
        
        if total_response.get('status') == 'success' and total_response['data']['result']:
            for timestamp, value in total_response['data']['result'][0]['values']:
                total_values[timestamp] = float(value)
        
        if success_response.get('status') == 'success' and success_response['data']['result']:
            for timestamp, value in success_response['data']['result'][0]['values']:
                success_values[timestamp] = float(value)
        
        for timestamp in total_values:
            total = total_values[timestamp]
            success = success_values.get(timestamp, 0)
            success_rate = (success / total * 100) if total > 0 else 0
            ingress_success_rate.append({
                'timestamp': timestamp,
                'value': round(success_rate, 2)
            })
        
        # === NODE METRICS ===
        
        # Use existing methods from PrometheusMetricsTool
        duration_str = f"{int(duration_seconds)}s"
        
        # Node CPU - pod containers aggregated per node
        node_pod_cpu = prom.get_node_cpu_timeseries(duration=duration_str, step=step)
        
        # Node CPU - actual non-idle time
        node_core_cpu = prom.get_node_core_cpu_timeseries(duration=duration_str, step=step)
        
        # Node Memory
        node_memory = prom.get_node_memory_timeseries(duration=duration_str, step=step)
        
        return {
            'ingress_gateway': {
                'latency_p95_seconds': ingress_latency,
                'success_rate_percent': ingress_success_rate
            },
            'node_resources': {
                'pod_cpu_per_node': node_pod_cpu.get('data', []),
                'node_cpu_cores_non_idle': node_core_cpu.get('data', []),
                'node_memory_bytes': node_memory.get('data', [])
            },
            'metadata': {
                'start_time': started_at,
                'end_time': end_time.isoformat(),
                'duration_seconds': duration_seconds,
                'step': step,
                'namespace': namespace
            }
        }
    
    def log_experiment(self, experiment_result: Dict[str, Any], batch_id: str) -> Path:
        """Log complete experiment using the structured experiment_result dict.

        The result is produced by the experiment runner and enriched by the batch
        runner (e.g., timing fields). Only the batch_id is provided separately.

        Returns:
            Path to saved log file
        """
        from dataclasses import asdict as dataclass_asdict
        
        # Extract basic fields from the structured result
        experiment_id = experiment_result.get("experiment_id")
        experiment_index = experiment_result.get("index")
        namespace = experiment_result.get("namespace")
        started_at = experiment_result.get("started_at")
        completed_at = experiment_result.get("completed_at")
        duration_seconds = experiment_result.get("experiment_duration_seconds")
        chaos_config = experiment_result.get("chaos_config", {})
        phase_metrics = experiment_result.get("phase_metrics", {})
        agent_trace_raw = experiment_result.get("agent_trace", [])
        agent_success = bool(experiment_result.get("agent_success", False))
        agent_duration_seconds = experiment_result.get("agent_execution_duration_seconds", 0)
        operational_summary = experiment_result.get("operational_summary")
        location_evaluation = experiment_result.get("location_evaluation")
        experiment_success = bool(experiment_result.get("success", False))
        recovery_successful = bool(experiment_result.get("recovery_successful", False))
        recovery_reason = experiment_result.get("recovery_reason", "")
        error = experiment_result.get("error")
        interrupted = bool(experiment_result.get("interrupted", False))

        # Convert agent trace from AgentTraceStep objects to dicts
        agent_trace = []
        for step in agent_trace_raw:
            if hasattr(step, '__dataclass_fields__'):
                # It's a dataclass instance, convert to dict
                agent_trace.append(dataclass_asdict(step))
            elif isinstance(step, dict):
                # Already a dict
                agent_trace.append(step)

        # Extract phase metrics
        baseline = phase_metrics.get("baseline", {})
        chaos = phase_metrics.get("chaos", {})
        recovery = phase_metrics.get("recovery", {})

        # Capture Prometheus timeseries snapshot
        prometheus_snapshot = self.snapshot_prometheus_metrics(
            started_at=started_at,
            duration_seconds=duration_seconds,
            namespace=namespace
        )

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
            chaos_fault_type=chaos_config.get("fault_type") or chaos_config.get("type", "unknown"),
            chaos_intensity=str(chaos_config.get("intensity", "unknown")),
            baseline_metrics=self._simplify_metrics(baseline),
            chaos_metrics=self._simplify_metrics(chaos),
            recovery_metrics=self._simplify_metrics(recovery),
            agent_trace=agent_trace,
            agent_success=agent_success,
            agent_duration_seconds=agent_duration_seconds,
            operational_summary=operational_summary,
            problem_location=(operational_summary.get("problem_location") if isinstance(operational_summary, dict) else None),
            location_evaluation=location_evaluation,
            experiment_success=experiment_success,
            recovery_successful=recovery_successful,
            recovery_reason=recovery_reason,
            error=error,
            interrupted=interrupted,
            final_success_rate=recovery.get("success_rate_percent"),
            final_latency_p95=recovery.get("p95_latency_seconds"),
            prometheus_timeseries=prometheus_snapshot
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
                    "agent_trace_steps": len(exp.get("agent_trace", [])),
                    "recovery_successful": exp.get("recovery_successful", False),
                    "location_identified": exp.get("location_evaluation", {}).get("location_identified") if exp.get("location_evaluation") else None
                }
                for exp in batch_results.get("experiments", [])
            ]
        }
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        return summary_file 