#!/usr/bin/env python3
"""
Chaos Mitigation Test Orchestrator
Main test class that orchestrates app deployment, chaos injection, and agent mitigation.
"""

import asyncio
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import subprocess
import os
import json

# CRITICAL: Import TrafficGenerator FIRST (contains Locust) before Kubernetes
# This ensures proper SSL monkey-patching order to prevent recursion errors
from .traffic_generator import LocustTrafficGenerator

# Import other project modules
from ..anomalies.docker_constraints_handler import DockerConstraintsHandler
from ..anomalies.chaos_mesh_handler import ChaosMeshHandler
from kub_mitigation_agent.agent.agent import KubernetesAgent
from kub_mitigation_agent.agent.config import KubernetesAgentConfig
from kub_mitigation_agent.shared.prometheus_client import (
    get_prometheus_tool,
    prometheus_get_timeseries,
    prometheus_get_node_timeseries,
)
from .experiment_utils import extract_prometheus_latency
from .simple_experiment_logger import SimpleExperimentLogger
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

class ChaosAndMitigationExperiment:
    """Orchestrates chaos injection and agent mitigation testing."""
    
    def __init__(self, 
        experiment_config: Dict[str, Any], 
        alert_config: Dict[str, Any],
        simple_logger: Optional[SimpleExperimentLogger] = None
    ):
        self.config = experiment_config
        self.alert_config = alert_config
        self.simple_logger = simple_logger
        
        # Initialize components
        self.docker_handler = None
        self.chaos_mesh_handler = None
        self.agent = None
        self.traffic_generator = None
        self.chaos_experiment = None
        
        # Initialize Prometheus metrics tool using singleton
        self.prometheus_tool = get_prometheus_tool()
        
        # Store metrics for alert context
        self.baseline_metrics = None
        self.baseline_prometheus_metrics = None
        self.current_metrics = None
        
    async def setup(self):
        # Initialize Anomalie Handlers and Traffic Generator
        self.docker_handler = DockerConstraintsHandler(self.config)
        self.chaos_mesh_handler = ChaosMeshHandler(self.config)        
        self.traffic_generator = LocustTrafficGenerator(self.config["traffic_config"])
 
    async def inject_chaos(self) -> bool:
        """Inject chaos into the target application based on configuration mode."""
        config = self.config['chaos_config']
        mode = config['mode']

        if mode == "no_failure":
            # No chaos experiment to track
            self.chaos_experiment = None
            return True
        elif mode == "docker_only":
            exp = self.docker_handler.inject_docker_constraints_only(config)
            if exp:
                self.chaos_experiment = exp
                return True
            return False
        elif mode == "chaos_only":
            exp = self.chaos_mesh_handler.inject_chaos_mesh_only(config)
            if exp:
                self.chaos_experiment = exp
                return True
            return False
        else:
            print(f"  ❌ Unknown chaos mode: {mode}")
            return False
    
    def _prepare_agent_inputs(self, chaos_metrics: Dict[str, Any], chaos_prometheus_metrics: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        """Prepare intent and snapshot for agent execution."""
        self.current_metrics = chaos_metrics
        
        baseline_p95 = extract_prometheus_latency(
            self.baseline_prometheus_metrics, 
            self.config["namespace"]
        ) if self.baseline_prometheus_metrics else 'unknown'
        
        current_p95 = extract_prometheus_latency(
            chaos_prometheus_metrics, 
            self.config["namespace"]
        ) if chaos_prometheus_metrics else 'unknown'
        
        intent = self.alert_config["alert_template"].format(
            namespace=self.config["namespace"],
            timestamp=datetime.now(timezone.utc).isoformat(),
            baseline_latency_p95=f"{baseline_p95}ms",
            baseline_success_rate=f"{self.baseline_metrics.get('success_rate_percent', 'unknown')}",
            current_latency_p95=f"{current_p95}ms", 
            current_success_rate=f"{self.current_metrics.get('success_rate_percent', 'unknown')}"
        )
        
        snapshot = {
            field: self._get_context_value(field)
            for field in self.alert_config["context_fields"]
        }
        
        return intent, snapshot

    async def deploy_mitigation_agent(self, chaos_metrics: Dict[str, Any], chaos_prometheus_metrics: Dict[str, Any]) -> tuple[list, Optional[Dict[str, Any]]]:
        """Deploy the agent to mitigate the issues (inline execution)."""
        intent, snapshot = self._prepare_agent_inputs(chaos_metrics, chaos_prometheus_metrics)
        
        # Load agent config
        repo_root = Path(__file__).resolve().parents[2]
        agent_yaml_path = repo_root / "experiment_configs" / "agent.config.yaml"
        cfg_dict = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
        agent_cfg = KubernetesAgentConfig.from_yaml_dict(cfg_dict)

        print(f"  🤖 Deploying agent (max {agent_cfg.max_rounds} rounds, {agent_cfg.agent_timeout}s timeout)")
        print(f"  🚨 Performance degradation: {self.baseline_metrics['success_rate_percent']:.1f}% → {self.current_metrics['success_rate_percent']:.1f}% success")

        self.agent = KubernetesAgent(config=agent_cfg)
        await self.agent.initialize()
        
        if self.simple_logger:
            self.simple_logger.start_agent_execution()
        
        try:
            actions_taken, operational_summary = await self.agent.agent_loop(intent, snapshot)
            print(f"  ✅ Agent completed: {len(actions_taken)} actions taken")
            
            if self.simple_logger:
                summary_data = None
                if operational_summary and isinstance(operational_summary, dict):
                    summary_data = operational_summary.get("summary")
                self.simple_logger.complete_agent_execution(actions_taken, success=True, operational_summary=summary_data)
            
            return actions_taken, operational_summary
            
        except Exception as e:
            print(f"  ❌ Agent failed: {e}")
            if self.simple_logger:
                self.simple_logger.complete_agent_execution([], success=False)
            return [], None
    
    def _get_context_value(self, field: str) -> str:
        """Get context value for alert fields."""
        context_map = {
            "namespace": self.config["namespace"],
            "alert_type": "performance_degradation", 
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "baseline_latency_p95": str(self.baseline_metrics.get('p95_latency_seconds', 'unknown')) if self.baseline_metrics else 'unknown',
            "baseline_success_rate": str(self.baseline_metrics.get('success_rate_percent', 'unknown')) if self.baseline_metrics else 'unknown',
            "current_latency_p95": str(self.current_metrics.get('p95_latency_seconds', 'unknown')) if self.current_metrics else 'unknown',
            "current_success_rate": str(self.current_metrics.get('success_rate_percent', 'unknown')) if self.current_metrics else 'unknown'
        }
        return context_map.get(field, "unknown")

    def _collect_last_values_prometheus(self, namespace: str) -> Dict[str, Any]:
        """Build a compact metrics snapshot from last sample of timeseries."""
        # Enforce minimum duration of 1m for stable last sample
        duration = "1m"
        ns = namespace or ""

        pod_cpu = prometheus_get_timeseries("cpu", ns, duration)
        pod_mem = prometheus_get_timeseries("memory", ns, duration)
        svc_lat = prometheus_get_timeseries("latency", ns, duration)
        node_cpu = prometheus_get_node_timeseries("cpu", duration)
        node_mem = prometheus_get_node_timeseries("memory", duration)

        def last_values(ts_result: Dict[str, Any]) -> Dict[str, float]:
            if not ts_result or ts_result.get("error"):
                return {}
            entities = {}
            series_map = ts_result.get("values", {})
            for key, series in series_map.items():
                if isinstance(series, list) and series:
                    entities[key] = series[-1]
            return entities

        summary = {
            "metrics": {
                "pod_cpu": {"unit": pod_cpu.get("unit"), "values": last_values(pod_cpu)},
                "pod_memory": {"unit": pod_mem.get("unit"), "values": last_values(pod_mem)},
                "istio_latency": {"unit": svc_lat.get("unit"), "values": last_values(svc_lat)},
                "node_cpu": {"unit": node_cpu.get("unit"), "values": last_values(node_cpu)},
                "node_memory": {"unit": node_mem.get("unit"), "values": last_values(node_mem)},
            }
        }
        return summary

    async def cleanup_all(self, emergency: bool = False):
        """Clean up all experiment resources.
        
        Args:
            emergency: If True, print detailed status for emergency cleanup (CTRL+C)
        """
        if emergency:
            print(f"\nEMERGENCY CLEANUP - CTRL+C DETECTED")
            print("=" * 40)
        
        # 1. Stop traffic generation
        if self.traffic_generator:
            try:
                if emergency:
                    print("Stopping traffic generation...")
                await self.traffic_generator.stop_traffic()
                if emergency:
                    print("Traffic generation stopped")
            except Exception as e:
                print(f"Error stopping traffic: {e}")
        
        # 2. Clean up chaos experiment
        if self.chaos_experiment:
            try:
                if emergency:
                    print("Cleaning up chaos experiment...")
                
                mode = self.config.get("chaos_config", {}).get("mode")
                if mode == "docker_only":
                    if emergency:
                        print("Docker-only experiment: No Chaos Mesh cleanup required")
                else:
                    loop = asyncio.get_event_loop()
                    success = await loop.run_in_executor(
                        None, 
                        self.chaos_mesh_handler.cleanup_chaos_experiment, 
                        self.chaos_experiment
                    )
                    if not success and not emergency:
                        print("  ⚠️  Chaos cleanup had issues")
                    elif emergency:
                        print("Chaos experiment cleaned up" if success else "Chaos cleanup had issues")
                        
            except Exception as e:
                print(f"Error cleaning chaos experiment: {e}")
        
        # 3. Clean up agent
        if self.agent and self.config.get("test_settings", {}).get("cleanup_after_test", True):
            try:
                if emergency:
                    print("Cleaning up agent...")
                await self.agent.cleanup()
                if emergency:
                    print("Agent cleaned up")
            except Exception as e:
                print(f"Error cleaning agent: {e}")
        
        if emergency:
            print("=" * 40)
            print("Emergency cleanup completed - safe to exit")
            print("Next run will automatically set all nodes to proper resource limits")

    def evaluate_recovery_success(self, phase_metrics: Dict) -> Dict[str, Any]:
        """Evaluate if the agent successfully recovered the system to near baseline levels."""
        if "baseline" not in phase_metrics or "recovery" not in phase_metrics:
            return {
                "success": False,
                "reason": "Missing baseline or recovery metrics for comparison",
                "metrics_comparison": {}
            }
        
        baseline = phase_metrics["baseline"]
        recovery = phase_metrics["recovery"]
        
        # Define success thresholds (configurable)
        latency_threshold = 1.3  # Recovery latency should be within 20% of baseline
        success_rate_threshold = 5.0  # Recovery success rate should be within 5% of baseline
        
        # Check if baseline is placeholder (from skipped mode)
        is_placeholder_baseline = (baseline["p95_latency_seconds"] == 0.1 and 
                                 baseline["total_requests"] == 0)
        
        metrics_comparison = {
            "baseline_latency_p95": baseline["p95_latency_seconds"],
            "recovery_latency_p95": recovery["p95_latency_seconds"],
            "baseline_success_rate": baseline["success_rate_percent"],
            "recovery_success_rate": recovery["success_rate_percent"],
            "is_placeholder_baseline": is_placeholder_baseline
        }
        
        if is_placeholder_baseline:
            # In fast mode, use chaos metrics as baseline comparison
            if "chaos" in phase_metrics:
                chaos = phase_metrics["chaos"]
                # Success if recovery is better than chaos (improvement detected)
                latency_improved = recovery["p95_latency_seconds"] < chaos["p95_latency_seconds"]
                success_rate_improved = recovery["success_rate_percent"] > chaos["success_rate_percent"]
                
                success = latency_improved and success_rate_improved
                reason = f"Fast mode: Recovery {'improved' if success else 'did not improve'} compared to chaos phase"
                
                metrics_comparison.update({
                    "chaos_latency_p95": chaos["p95_latency_seconds"],
                    "chaos_success_rate": chaos["success_rate_percent"],
                    "latency_improved": latency_improved,
                    "success_rate_improved": success_rate_improved
                })
            else:
                success = False
                reason = "Fast mode: Missing chaos metrics for comparison"
        else:
            # Normal mode: compare recovery with baseline
            latency_ratio = recovery["p95_latency_seconds"] / baseline["p95_latency_seconds"] if baseline["p95_latency_seconds"] > 0 else float('inf')
            success_rate_diff = abs(recovery["success_rate_percent"] - baseline["success_rate_percent"])
            
            latency_acceptable = latency_ratio <= latency_threshold
            success_rate_acceptable = success_rate_diff <= success_rate_threshold
            
            success = latency_acceptable and success_rate_acceptable
            
            if success:
                reason = f"Recovery within acceptable thresholds: latency {latency_ratio:.2f}x baseline, success rate ±{success_rate_diff:.1f}%"
            else:
                issues = []
                if not latency_acceptable:
                    issues.append(f"latency {latency_ratio:.2f}x baseline (threshold: {latency_threshold}x)")
                if not success_rate_acceptable:
                    issues.append(f"success rate ±{success_rate_diff:.1f}% (threshold: ±{success_rate_threshold}%)")
                reason = f"Recovery exceeded thresholds: {', '.join(issues)}"
            
            metrics_comparison.update({
                "latency_ratio": latency_ratio,
                "success_rate_diff": success_rate_diff,
                "latency_acceptable": latency_acceptable,
                "success_rate_acceptable": success_rate_acceptable
            })
        
        return {
            "success": success,
            "reason": reason,
            "metrics_comparison": metrics_comparison
        }

    async def run_full_experiment(self, deployment_already_done: bool = False, deployment_namespace: str = "") -> Dict[str, Any]:
        """Run the simplified chaos injection and mitigation experiment."""
        results = {
            "success": False,
            "phases_completed": [],
            "agent_actions": [],
            "error": None,
            "interrupted": False,
            "phase_metrics": {},
            "operational_summary": None,
            "problem_location": {},
            "agent_duration_seconds": 0
        }
        
        try:
            # Setup
            await self.setup()
                        
            # === BASELINE METRICS (no warmup) ===
            print(f"\n▶ Phase 1: Baseline metrics ({self.config['baseline_duration']}s)")
            # Ensure traffic is running before measuring baseline
            await self.traffic_generator.start_traffic()
            # Reset metrics at START of baseline measurement phase
            self.traffic_generator.reset_phase_metrics()
            await asyncio.sleep(self.config["baseline_duration"])
            
            # Collect both traffic generator and Prometheus baseline metrics
            baseline_metrics = self.traffic_generator.get_phase_metrics(self.config["baseline_duration"])
            self.baseline_metrics = baseline_metrics
            
            # Collect Prometheus baseline metrics for agent context (last-of-timeseries)
            self.baseline_prometheus_metrics = self._collect_last_values_prometheus(self.config["namespace"]) 
            
            results["phase_metrics"]["baseline"] = baseline_metrics
            print(f"  ✅ Baseline: {baseline_metrics['success_rate_percent']:.1f}% success, P95: {baseline_metrics['p95_latency_seconds']:.3f}s")
            
            # Log baseline metrics if logging enabled
            if self.simple_logger:
                self.simple_logger.log_phase_metrics("baseline", baseline_metrics)
            
            results["phases_completed"].append("baseline")
            
            # === CHAOS INJECTION ===
            print(f"\n▶ Chaos injection: ", end="")
            if await self.inject_chaos():
                print("✅ Active")
                results["phases_completed"].append("chaos_injection")
            else:
                print("❌ Failed")
                raise Exception("Failed to inject chaos")
            
            # === PHASE 3: CHAOS WARMUP (record metrics during active chaos) ===
            print(f"\n▶ Phase 3: Chaos metrics ({self.config['chaos_warmup_duration']}s)")
            # Reset metrics at START of chaos measurement phase
            self.traffic_generator.reset_phase_metrics()
            await asyncio.sleep(self.config["chaos_warmup_duration"])
            
            chaos_metrics = self.traffic_generator.get_phase_metrics(self.config["chaos_warmup_duration"])
            results["phase_metrics"]["chaos"] = chaos_metrics
            print(f"  ⚠️  Chaos: {chaos_metrics['success_rate_percent']:.1f}% success, P95: {chaos_metrics['p95_latency_seconds']:.3f}s")
            
            # Collect Prometheus chaos metrics for agent context (last-of-timeseries)
            chaos_prometheus_metrics = self._collect_last_values_prometheus(self.config["namespace"]) 
            
            # Log chaos metrics if logging enabled
            if self.simple_logger:
                self.simple_logger.log_phase_metrics("chaos", chaos_metrics)
            
            results["phases_completed"].append("chaos_warmup")
            
            # === AGENT EXECUTION (during active chaos) ===
            print(f"\n▶ Agent execution (chaos active)")
            agent_start_time = time.time()
            agent_actions, operational_summary = await self.deploy_mitigation_agent(chaos_metrics, chaos_prometheus_metrics)
            agent_end_time = time.time()
            agent_duration = agent_end_time - agent_start_time
            results["agent_duration_seconds"] = agent_duration

            results["agent_actions"] = agent_actions
            results["phases_completed"].append("agent_execution")
            
            # Store operational summary if available
            if operational_summary and isinstance(operational_summary, dict):
                summary_data = operational_summary.get("summary")
                if summary_data:
                    results["operational_summary"] = summary_data
                    # Extract problem_location - it's now an array in the new format
                    problem_location = summary_data.get("problem_location", [])
                    # Ensure it's always stored as a list for consistency
                    if isinstance(problem_location, list):
                        results["problem_location"] = problem_location
                    elif isinstance(problem_location, dict):
                        # Convert old dict format to new list format if needed
                        results["problem_location"] = problem_location
                    else:
                        results["problem_location"] = []
            
            # === PHASE 4: RECOVERY METRICS ===
            print(f"\n▶ Phase 4: Recovery metrics ({self.config['recovery_duration']}s)")
            # Reset metrics at START of recovery measurement phase (after agent execution)
            self.traffic_generator.reset_phase_metrics()
            await asyncio.sleep(self.config["recovery_duration"])
            
            recovery_metrics = self.traffic_generator.get_phase_metrics(self.config["recovery_duration"])
            results["phase_metrics"]["recovery"] = recovery_metrics
            print(f"  🩹 Recovery: {recovery_metrics['success_rate_percent']:.1f}% success, P95: {recovery_metrics['p95_latency_seconds']:.3f}s")
            
            # Log recovery metrics if logging enabled
            if self.simple_logger:
                self.simple_logger.log_phase_metrics("recovery", recovery_metrics)
            
            results["phases_completed"].append("recovery")
            
            # === CLEANUP AND FINAL METRICS ===
            print(f"\n▶ Cleanup: ", end="")
            await self.cleanup_all()
            print("✅ Complete")
            
            # Evaluate recovery success
            recovery_evaluation = self.evaluate_recovery_success(results["phase_metrics"])
            results["recovery_evaluation"] = recovery_evaluation
            
            # Set overall experiment success based on recovery evaluation
            results["success"] = recovery_evaluation["success"]
            results["recovery_successful"] = recovery_evaluation["success"]
            results["recovery_reason"] = recovery_evaluation["reason"]
            
            # Mark that logging is enabled
            if self.simple_logger:
                results["dataset_logged"] = True
            
            return results
            
        except KeyboardInterrupt:
            results["interrupted"] = True
            results["error"] = "Experiment interrupted by user (Ctrl+C)"
            print(f"\nExperiment interrupted! Initiating cleanup...")            
            return results
            
        except Exception as e:
            results["error"] = str(e)
            print(f"\nTest failed: {e}")
            logger.exception("Test execution error")            
            return results
        
        finally:
            # Always cleanup (but skip if already cleaned in success path)
            if results.get("interrupted", False) or results.get("error"):
                await self.cleanup_all(emergency=results.get("interrupted", False))