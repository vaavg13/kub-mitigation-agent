import asyncio
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

# CRITICAL: Import TrafficGenerator FIRST (contains Locust) before Kubernetes
# This ensures proper SSL monkey-patching order to prevent recursion errors
from .traffic_generator import LocustTrafficGenerator

from ..anomalies.anomaly_base import Anomaly
from kub_mitigation_agent.agent.agent import KubernetesAgent
from kub_mitigation_agent.agent.config import KubernetesAgentConfig
from .alert_config import build_intent, build_snapshot
from .recovery_evaluator import evaluate_metrics_recovery, evaluate_problem_location_match
from .experiment_k8s_ops import collect_istio_ingress_metrics

logger = logging.getLogger(__name__)

class MitigationExperimentRunner:
    """Orchestrates chaos injection and agent mitigation testing."""
    
    def __init__(self, 
        experiment_config: Dict[str, Any],
        experiment_id: Optional[str] = None,
        agent_config: Optional[KubernetesAgentConfig] = None,
        anomaly: Anomaly = None,
    ):
        self.config = experiment_config
        self.experiment_id = experiment_id
        self.agent_config = agent_config or KubernetesAgentConfig()
        
        self.anomaly = anomaly
        self.agent = None
        self.traffic_generator = None
        self.chaos_experiment = None
                
    async def setup(self):
        self.traffic_generator = LocustTrafficGenerator(self.config["traffic_config"])
        
        if self.agent_config.enabled:
            self.agent = KubernetesAgent(self.agent_config)
 
    async def inject_chaos(self) -> bool:
        """Inject chaos via bound anomaly instance."""
        handle = self.anomaly.start()
        self.chaos_experiment = handle
        return True
    
    def _prepare_agent_inputs(
        self, 
        baseline_metrics: Dict[str, Any],
        current_metrics: Dict[str, Any]
    ) -> tuple[str, Dict[str, Any]]:
        # Extract traffic generator metrics
        baseline_success = baseline_metrics.get('success_rate_percent', 0)
        current_success = current_metrics.get('success_rate_percent', 0)
        baseline_p95_seconds = baseline_metrics.get('p95_latency_seconds', 0)
        current_p95_seconds = current_metrics.get('p95_latency_seconds', 0)
        
        timestamp = datetime.now(timezone.utc).isoformat()
        namespace = self.config["namespace"]
        
        # Build simple intent describing what's happening
        intent = build_intent()
        
        # Build snapshot with all metrics from traffic generator
        snapshot = build_snapshot(
            namespace=namespace,
            baseline_latency_p95=baseline_p95_seconds,
            baseline_success_rate=baseline_success,
            current_latency_p95=current_p95_seconds,
            current_success_rate=current_success,
            timestamp=timestamp
        )
        
        return intent, snapshot

    async def deploy_mitigation_agent(
        self, 
        baseline_metrics: Dict[str, Any],
        current_metrics: Dict[str, Any]
    ) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
        if not self.agent.is_initialized:
            await self.agent.initialize()
        
        # Build intent and snapshot from traffic generator metrics
        intent, snapshot = self._prepare_agent_inputs(baseline_metrics, current_metrics)
        
        # Run agent - let exceptions propagate
        actions, summary = await self.agent.agent_loop(intent, snapshot)
        return actions, summary, True


    async def cleanup_all(self):
        """Clean up all experiment resources."""
        
        # 1. Stop traffic generation
        if self.traffic_generator:
            try:
                await self.traffic_generator.stop_traffic()
            except Exception as e:
                print(f"Error stopping traffic: {e}")
        
        # 2. Clean up chaos experiment
        if self.chaos_experiment:
            try:
                self.anomaly.stop()
            except Exception as e:
                print(f"Error cleaning chaos experiment: {e}")
        
        # 3. Clean up agent
        if self.agent:
            try:
                await self.agent.cleanup()
            except Exception as e:
                print(f"Error cleaning agent: {e}")

    def _evaluate_and_report(self, results: Dict[str, Any]) -> None:
        """Compute recovery and location evaluations, update results, and print summary."""
        recovery_evaluation = evaluate_metrics_recovery(results["phase_metrics"])
        results["recovery_evaluation"] = recovery_evaluation

        problem_location = results.get("operational_summary", {}).get("problem_location") if results.get("operational_summary") else None
        
        # Get chaos config from anomaly for evaluation
        chaos_config = self.anomaly.get_info()
        location_evaluation = evaluate_problem_location_match(chaos_config, problem_location)
        results["location_evaluation"] = location_evaluation

        # Print
        cmp = recovery_evaluation.get("metrics_comparison", {})
        chaos_sr = cmp.get("chaos_success_rate")
        chaos_p95 = cmp.get("chaos_latency_p95")
        if isinstance(chaos_sr, (int, float)) and isinstance(chaos_p95, (int, float)):
            print(f"  📊 Chaos: {chaos_sr:.1f}% success, P95: {chaos_p95:.3f}s")

        base_sr = cmp.get("baseline_success_rate")
        base_p95 = cmp.get("baseline_latency_p95")
        rec_sr = cmp.get("recovery_success_rate")
        rec_p95 = cmp.get("recovery_latency_p95")
        if isinstance(base_sr, (int, float)) and isinstance(base_p95, (int, float)):
            print(f"  📊 Baseline: {base_sr:.1f}% success, P95: {base_p95:.3f}s")
        if isinstance(rec_sr, (int, float)) and isinstance(rec_p95, (int, float)):
            print(f"  📊 Recovery: {rec_sr:.1f}% success, P95: {rec_p95:.3f}s")

        lr = cmp.get("latency_ratio")
        sd = cmp.get("success_rate_diff")
        ok = bool(recovery_evaluation.get("success"))
        status_label = "within baseline range" if ok else "outside baseline range"
        emoji = "✅" if ok else "❌"
        if isinstance(lr, (int, float)) and isinstance(sd, (int, float)):
            print(f"  📈 Recovery evaluation: {emoji} {status_label} (latency {lr:.2f}x baseline, success ±{sd:.1f}% vs baseline)")
        else:
            print(f"  📈 Recovery evaluation: {emoji} {status_label}")

        expected_target = location_evaluation.get('expected_target')
        expected_label = expected_target if expected_target is not None else "none"
        reported_locations = location_evaluation.get('reported_locations') or []
        if isinstance(reported_locations, list):
            reported_label = ", ".join([str(x) for x in reported_locations]) if reported_locations else "none"
        else:
            reported_label = str(reported_locations)
        result_emoji = "✅" if location_evaluation.get("location_identified") else "❌"
        print(f"  🎯 Problem location: expected={expected_label}; agent={reported_label}; result={result_emoji}")

    async def run_full_experiment(self) -> Dict[str, Any]:
        """Run the simplified chaos injection and mitigation experiment."""
        results = {
            "success": False,
            "agent_actions": [],
            "error": None,
            "interrupted": False,
            "phase_metrics": {},
            "operational_summary": None,
            "problem_location": [],
            "agent_execution_duration_seconds": 0,
            "agent_success": False
        }
        
        try:
            await self.setup()
            
            # === WARMUP PHASE ===
            warmup_duration = self.config.get("warmup_duration", 0)
            if warmup_duration > 0:
                print(f"\n▶ Phase 1: Warmup ({warmup_duration}s)")
                await self.traffic_generator.start_traffic()
                await asyncio.sleep(warmup_duration)
                print(f"  ✅ Warmup complete")
            
            # === BASELINE METRICS ===
            print(f"\n▶ Phase 2:Baseline metrics ({self.config['baseline_duration']}s)")
            if warmup_duration == 0:
                await self.traffic_generator.start_traffic()
            await asyncio.sleep(self.config["baseline_duration"])
            baseline_metrics = collect_istio_ingress_metrics(self.config["baseline_duration"])
            results["phase_metrics"]["baseline"] = baseline_metrics
            print(
                f"  ✅ Measured: {baseline_metrics['success_rate_percent']:.1f}% success, "
                f"P95: {baseline_metrics['p95_latency_seconds']:.3f}s"
            )
            
            # === CHAOS INJECTION ===
            print(f"\n▶ Phase 3: Chaos")

            print(f"\n  Chaos injection: ", end="")
            if not await self.inject_chaos():
                print("❌ Failed")
                raise Exception("Failed to inject chaos")
            print("✅ Active")

            print(f" Chaos warmup duration: {self.config['chaos_warmup_duration']}s")
            await asyncio.sleep(self.config["chaos_warmup_duration"])
            
            chaos_metrics = collect_istio_ingress_metrics(self.config["chaos_warmup_duration"])
            results["phase_metrics"]["chaos"] = chaos_metrics
            print(
                f"  ⚠️  Chaos: {chaos_metrics['success_rate_percent']:.1f}% success, "
                f"P95: {chaos_metrics['p95_latency_seconds']:.3f}s"
            )
            
            # === AGENT EXECUTION ===
            if self.agent_config.enabled:
                print(f"\n▶ Agent execution (chaos active)")
                agent_execution_start_time = time.time()

                # Deploy agent
                agent_actions, operational_summary, agent_success = await self.deploy_mitigation_agent(
                    baseline_metrics, 
                    chaos_metrics
                )

                # Store agent execution results
                results["agent_execution_duration_seconds"] = time.time() - agent_execution_start_time
                results["agent_actions"] = agent_actions
                results["agent_success"] = agent_success
                results["operational_summary"] = operational_summary
                results["problem_location"] = operational_summary.get("problem_location", []) if operational_summary else []
            else:
                print(f"\n▶ Agent execution: DISABLED (baseline-chaos-recovery mode)")
            
            # === RECOVERY METRICS ===
            print(f"\n▶ Phase 4: Recovery metrics ({self.config['recovery_duration']}s)")
            await asyncio.sleep(self.config["recovery_duration"])
            
            recovery_metrics = collect_istio_ingress_metrics(self.config["recovery_duration"])
            results["phase_metrics"]["recovery"] = recovery_metrics
            print(f"  🩹 Recovery: {recovery_metrics['success_rate_percent']:.1f}% success, "
                f"P95: {recovery_metrics['p95_latency_seconds']:.3f}s"
            )

            # Evaluate and print via helper
            self._evaluate_and_report(results)
            
            # === CLEANUP AND FINAL METRICS ===
            print(f"\n▶ Cleanup: ", end="")
            await self.cleanup_all()
            print("✅ Complete")
            
            # Set overall experiment success based on the earlier recovery evaluation
            recovery_evaluation = results.get("recovery_evaluation", {})
            results["success"] = bool(recovery_evaluation.get("success"))
            results["recovery_successful"] = bool(recovery_evaluation.get("success"))
            results["recovery_reason"] = recovery_evaluation.get("reason")
            
            return results
            
        except Exception as e:
            results["error"] = str(e)
            print(f"\nTest failed: {e}")
            logger.exception("Test execution error")            
            return results
        
        finally:
            # Always cleanup (but skip if already cleaned in success path)
            if results.get("error"):
                await self.cleanup_all()