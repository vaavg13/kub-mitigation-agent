#!/usr/bin/env python3
"""
Chaos Mitigation Test Orchestrator
Main test class that orchestrates app deployment, chaos injection, and agent mitigation.
"""

import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import subprocess

# CRITICAL: Import TrafficGenerator FIRST (contains Locust) before Kubernetes
# This ensures proper SSL monkey-patching order to prevent recursion errors
from .traffic_generator import LocustTrafficGenerator

# Import other project modules
from ..anomalies.docker_constraints_handler import DockerConstraintsHandler
from ..anomalies.chaos_mesh_handler import ChaosMeshHandler
from kub_mitigation_agent.agent.agent import KubernetesAgent
from kub_mitigation_agent.shared.prometheus_client import (
    get_prometheus_tool,
    prometheus_get_timeseries,
    prometheus_get_node_timeseries,
)
from .experiment_utils import extract_prometheus_latency
from .experiment_utils import smart_warmup_with_monitoring
from .simple_experiment_logger import SimpleExperimentLogger

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
        """Setup chaos and mitigation components."""
        # Initialize handlers
        self.docker_handler = DockerConstraintsHandler(self.config)
        self.chaos_mesh_handler = ChaosMeshHandler(self.config)
        
        # NOTE: Docker constraint reset is handled by BatchChaosExperiment.reset_scheduling_policies()
        # If running this experiment standalone, ensure nodes are reset before calling this
        
        # Initialize traffic generator
        self.traffic_generator = LocustTrafficGenerator(self.config["traffic_config"])
        
        # Initialize agent (will be created fresh each time)
        self.agent = None
        self.baseline_metrics = None
        self.baseline_prometheus_metrics = None
 
    async def inject_chaos(self) -> bool:
        """Inject chaos into the target application based on configuration mode."""
        config = self.config['chaos_config']
        mode = config['mode']
        fault_type = config['fault_type']
        
        if mode == "no_failure":
            # No chaos experiment to track
            self.chaos_experiment = None
            return True
        elif mode == "docker_only":
            experiment_record = self.docker_handler.inject_docker_constraints_only(config)
            if experiment_record:
                # For docker_only mode, no specific app targeting
                self.chaos_experiment = experiment_record
                return True
            return False
        elif mode == "chaos_only":
            experiment_record = self.chaos_mesh_handler.inject_chaos_mesh_only(config)
            if experiment_record:
                self.chaos_experiment = experiment_record
                return True
            return False
        else:
            print(f"  ❌ Unknown chaos mode: {mode}")
            return False
    
    async def deploy_mitigation_agent(self, 
        chaos_metrics: Dict[str, Any], 
        chaos_prometheus_metrics: Dict[str, Any]
    ) -> tuple[list, Optional[Dict[str, Any]]]:
        """Deploy the agent to mitigate the issues."""
        print(f"  🤖 Deploying agent (max {self.config['agent_config']['max_rounds']} rounds, {self.config['agent_config']['agent_timeout']}s timeout)")
        
        # Initialize agent fresh for this execution (no trace logger)
        self.agent = KubernetesAgent(config=self.config["agent_config"])
        await self.agent.initialize()
        
        # Store metrics for context
        self.current_metrics = chaos_metrics
        
        # Extract Prometheus metrics for alert context
        baseline_p95 = extract_prometheus_latency(
            self.baseline_prometheus_metrics, 
            self.config["namespace"]
        ) if self.baseline_prometheus_metrics else 'unknown'
        
        current_p95 = extract_prometheus_latency(
            chaos_prometheus_metrics, 
            self.config["namespace"]
        ) if chaos_prometheus_metrics else 'unknown'
        
        # Create alert intent
        intent = self.alert_config["alert_template"].format(
            namespace=self.config["namespace"],
            timestamp=datetime.now().isoformat(),
            baseline_latency_p95=f"{baseline_p95}ms",
            baseline_success_rate=f"{self.baseline_metrics.get('success_rate_percent', 'unknown')}",
            current_latency_p95=f"{current_p95}ms", 
            current_success_rate=f"{self.current_metrics.get('success_rate_percent', 'unknown')}"
        )
        
        # Create monitoring context
        snapshot = {
            field: self._get_context_value(field)
            for field in self.alert_config["context_fields"]
        }
        
        print(f"  🚨 Performance degradation: {self.baseline_metrics['success_rate_percent']:.1f}% → {self.current_metrics['success_rate_percent']:.1f}% success")
        
        try:
            # Start agent timing if logger available
            if self.simple_logger:
                self.simple_logger.start_agent_execution()
            
            # Run the agent
            actions_taken, operational_summary = await self.agent.agent_loop(intent, snapshot)
            print(f"  ✅ Agent completed: {len(actions_taken)} actions taken")
            
            # Log agent completion with operational summary if logger available
            if self.simple_logger:
                # Extract the actual summary from the result if it exists
                summary_data = None
                if operational_summary and isinstance(operational_summary, dict):
                    summary_data = operational_summary.get("summary")
                
                self.simple_logger.complete_agent_execution(
                    actions_taken, 
                    success=True, 
                    operational_summary=summary_data
                )
            
            return actions_taken, operational_summary
            
        except Exception as e:
            print(f"  ❌ Agent failed: {e}")
            
            # Log failed agent execution if logger available
            if self.simple_logger:
                self.simple_logger.complete_agent_execution([], success=False)
            
            return [], None
    
    def _get_context_value(self, field: str) -> str:
        """Get context value for alert fields."""
        context_map = {
            "namespace": self.config["namespace"],
            "alert_type": "performance_degradation", 
            "timestamp": datetime.now().isoformat(),
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

    def _cleanup_chaos_sync(self) -> bool:
        """Synchronous chaos cleanup function to run in thread executor."""
        if self.chaos_experiment:
            # Check the mode from the original config for reliability
            mode = self.config.get("chaos_config", {}).get("mode")
            
            if mode == "docker_only":
                print(f"ℹ️  Docker-only experiment: No Chaos Mesh cleanup required.")
                print(f"   Node constraints are reset at the start of the next experiment run.")
                return True
            else:
                # Proceed with standard Chaos Mesh cleanup
                return self.chaos_mesh_handler.cleanup_chaos_experiment(self.chaos_experiment)
        
        # No experiment was run, so cleanup is successful by default
        return True

    async def cleanup_chaos(self):
        """Clean up the chaos experiment after agent completion."""
        if self.chaos_experiment is None:
            return
            
        # Run chaos cleanup in thread executor for consistency
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, self._cleanup_chaos_sync)
        
        if not success:
            print("  ⚠️  Chaos cleanup had issues")
    
    async def emergency_cleanup(self):
        """Emergency cleanup for when experiment is interrupted."""
        print(f"\nEMERGENCY CLEANUP - CTRL+C DETECTED")
        print("=" * 40)
        
        # Stop traffic generation immediately
        if self.traffic_generator:
            try:
                print("Stopping traffic generation...")
                await self.traffic_generator.stop_traffic()
                print("Traffic generation stopped")
            except Exception as e:
                print(f"Error stopping traffic: {e}")
        
        # Clean up chaos experiment with timeout
        if self.chaos_experiment:
            try:
                print("Cleaning up chaos experiment...")
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(None, self._cleanup_chaos_sync)
                if success:
                    print("Chaos experiment cleaned up")
                else:
                    print("Chaos experiment cleanup had issues")
            except Exception as e:
                print(f"Error cleaning chaos experiment: {e}")
        
        # Clean up agent
        if self.agent:
            try:
                print("Cleaning up agent...")
                await self.agent.cleanup()
                print("Agent cleaned up")
            except Exception as e:
                print(f"Error cleaning agent: {e}")
        
        print("=" * 40)
        print("Emergency cleanup completed - safe to exit")
        print("Next run will automatically set all nodes to proper resource limits")

    async def cleanup_remaining_resources(self):
        """Clean up remaining resources (traffic, agent) after chaos is already cleaned."""
        if not self.config["test_settings"]["cleanup_after_test"]:
            return
            
        # Stop traffic first
        if self.traffic_generator:
            await self.traffic_generator.stop_traffic()
            
        # Clean up agent
        if self.agent:
            await self.agent.cleanup()

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

    def print_experiment_summary(self, phase_metrics: Dict, agent_actions: list, recovery_evaluation: Dict[str, Any] = None):
        """Print final experiment summary with phase comparisons and recovery evaluation."""
        print(f"\n{'─'*50}")
        print(f"EXPERIMENT SUMMARY")
        print(f"{'─'*50}")
        
        # Phase results in compact format
        for phase_name, metrics in phase_metrics.items():
            phase_emojis = {"baseline": "📊", "chaos": "⚠️", "recovery": "🩹"}
            emoji = phase_emojis.get(phase_name, "📈")
            print(f"{emoji} {phase_name.capitalize()}: {metrics['success_rate_percent']:.1f}% success, P95: {metrics['p95_latency_seconds']:.3f}s")
        
        # Agent summary
        print(f"\n🤖 Agent: {len(agent_actions)} actions taken")
        
        # Recovery evaluation
        if recovery_evaluation:
            success_icon = "✅" if recovery_evaluation["success"] else "❌"
            print(f"{success_icon} Recovery: {recovery_evaluation['reason']}")
        
        print(f"{'─'*50}")

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
            results["phases_completed"].append("setup")
            
            # Application deployment handled before async context
            print(f"✅ Using already deployed application in namespace: {deployment_namespace}")
            results["phases_completed"].append("deployment")
            
            # Check if we should skip warmup and baseline phases
            skip_warmup_baseline = self.config.get("test_settings", {}).get("skip_warmup_baseline", False)
            
            if skip_warmup_baseline:
                # === FAST MODE: Skip warmup and baseline ===
                print(f"\n⚡ Fast mode: Skipping warmup and baseline phases")
                
                # Create placeholder baseline metrics for alert context
                placeholder_baseline = {
                    "total_requests": 0,
                    "expected_requests": 0,
                    "success_rate_percent": 100.0,
                    "p95_latency_seconds": 0.1,  # Placeholder value
                    "current_rps": 0.0,
                    "actual_duration_seconds": 0.0
                }
                self.baseline_metrics = placeholder_baseline
                results["phase_metrics"]["baseline"] = placeholder_baseline
                
                # Log baseline metrics if logging enabled
                if self.simple_logger:
                    self.simple_logger.log_phase_metrics("baseline", placeholder_baseline)
                
                # Skip baseline prometheus metrics (not needed for fast mode)
                self.baseline_prometheus_metrics = None
                
                results["phases_completed"].append("baseline_simulated")
                
            else:
                # === PHASE 1: POD WARMUP ===
                print(f"\n▶ Phase 1: Pod warmup")
                await self.traffic_generator.start_traffic()
                print(f"  Starting service warmup with latency monitoring...")
                
                # Smart warmup with latency stabilization detection
                await smart_warmup_with_monitoring(self.config, self.traffic_generator)
                
                results["phases_completed"].append("pod_warmup")
                
                # === PHASE 2: BASELINE METRICS ===
                print(f"\n▶ Phase 2: Baseline metrics ({self.config['baseline_duration']}s)")
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
            await self.traffic_generator.stop_traffic()
            await self.cleanup_chaos()
            print("✅ Complete")
            
            # Evaluate recovery success
            recovery_evaluation = self.evaluate_recovery_success(results["phase_metrics"])
            results["recovery_evaluation"] = recovery_evaluation
            
            # Final metrics comparison with recovery evaluation
            self.print_experiment_summary(results["phase_metrics"], agent_actions, recovery_evaluation)
            
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
            
            # Error will be logged when experiment completes
            
            return results
            
        except Exception as e:
            results["error"] = str(e)
            print(f"\nTest failed: {e}")
            logger.exception("Test execution error")
            
            # Error will be logged when experiment completes
            
            return results
        
        finally:
            # Always cleanup
            if results.get("interrupted", False):
                await self.emergency_cleanup()
            else:
                await self.cleanup_remaining_resources()