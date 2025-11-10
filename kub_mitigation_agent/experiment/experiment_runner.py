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
    ) -> tuple[List[Dict[str, Any]], List[Any], Optional[Dict[str, Any]], bool]:
        """
        Deploy the mitigation agent.
        
        Returns:
            Tuple of (actions, trace, summary, success)
            - actions: Legacy list of action dicts
            - trace: Complete agent trace with thought-action-observation
            - summary: Operational summary
            - success: Whether agent completed successfully
        """
        from kub_mitigation_agent.agent.agent_utils import build_emergency_summary
        
        if not self.agent.is_initialized:
            await self.agent.initialize()
        
        # Build intent and snapshot from traffic generator metrics
        intent, snapshot = self._prepare_agent_inputs(baseline_metrics, current_metrics)
        
        try:
            # Run agent
            actions, trace, summary = await self.agent.agent_loop(intent, snapshot)
            return actions, trace, summary, True
            
        except Exception as e:
            # Catch any agent errors - the agent should have already built an emergency summary
            # and returned partial trace if possible
            error_name = type(e).__name__
            
            # Check if agent already handled it and returned partial results
            # (GraphRecursionError is handled in react_agent.py and returns partial trace)
            if error_name == "GraphRecursionError":
                # Agent should have already returned partial trace/summary, but let's verify
                print(f"⚠️  Agent hit recursion limit - should have partial trace")
                # This shouldn't actually be reached because react_agent.py catches it
                # But if it does reach here, we have no trace to return
                
            print(f"⚠️  Agent execution failed with {error_name}: {str(e)}")
            
            # For KeyboardInterrupt, re-raise so it propagates properly
            if isinstance(e, KeyboardInterrupt):
                raise
            
            # For other exceptions, return empty trace and emergency summary
            from kub_mitigation_agent.agent.agent_utils import build_emergency_summary
            emergency_summary = build_emergency_summary(
                [],
                f"ERROR - {error_name}",
                [f"Agent execution failed: {str(e)}"],
                error=f"{error_name}: {str(e)}"
            )
            
            return [], [], emergency_summary, False


    async def cleanup_all(self):
        """Clean up all experiment resources."""
        from kub_mitigation_agent.anomalies import cleanup_all_anomalies
        
        # 1. Stop traffic generation
        if self.traffic_generator:
            try:
                await self.traffic_generator.stop_traffic()
            except Exception as e:
                print(f"Error stopping traffic: {e}")
        
        # 2. Clean up chaos experiment (specific anomaly)
        if self.chaos_experiment:
            try:
                self.anomaly.stop()
            except Exception as e:
                print(f"Error cleaning chaos experiment: {e}")
        
        # 3. Clean ALL anomalies (comprehensive cleanup)
        try:
            namespace = self.config.get("namespace")
            nodes = self.config.get("nodes", {})
            chaosd_port = self.config.get("chaosd_port", 31767)
            
            cleanup_all_anomalies(
                namespaces=[namespace] if namespace else None,
                nodes=nodes if nodes else None,
                chaosd_port=chaosd_port
            )
        except Exception as e:
            print(f"Error in comprehensive anomaly cleanup: {e}")
        
        # 4. Clean up agent
        if self.agent:
            try:
                await self.agent.cleanup()
            except Exception as e:
                print(f"Error cleaning agent: {e}")

    def _evaluate_and_report(self, results: Dict[str, Any]) -> None:
        """Compute recovery and location evaluations, update results, and print summary."""
        recovery_evaluation = evaluate_metrics_recovery(results["phase_metrics"])
        results["recovery_evaluation"] = recovery_evaluation

        operational_summary = results.get("operational_summary")
        problem_location = operational_summary.get("problem_location") if operational_summary else None
        
        chaos_config = self.anomaly.get_info()
        location_evaluation = evaluate_problem_location_match(chaos_config, problem_location)
        results["location_evaluation"] = location_evaluation

        # Print metrics comparison: Baseline → Chaos → Recovery
        cmp = recovery_evaluation["metrics_comparison"]
        print(f"  📊 Baseline: {cmp['baseline_success_rate']:.1f}% success, P95: {cmp['baseline_latency_p95']:.3f}s")
        if "chaos_success_rate" in cmp:
            print(f"  📊 Chaos: {cmp['chaos_success_rate']:.1f}% success, P95: {cmp['chaos_latency_p95']:.3f}s")
        print(f"  📊 Recovery: {cmp['recovery_success_rate']:.1f}% success, P95: {cmp['recovery_latency_p95']:.3f}s")

        # Print recovery index metrics if available
        if recovery_evaluation.get("composite_recovery_score") is not None:
            comp_score = recovery_evaluation["composite_recovery_score"] * 100
            lat_index = recovery_evaluation["recovery_index_latency"] * 100
            sr_index = recovery_evaluation["recovery_index_success"] * 100
            within_20pct = recovery_evaluation["within_20pct_baseline"]
            within_20_label = " | ✓ Within 20% of baseline" if within_20pct else ""
            print(f"  📈 Recovery Index: {comp_score:.0f}% (latency: {lat_index:.0f}%, success: {sr_index:.0f}%){within_20_label}")

        # Print recovery evaluation
        ok = recovery_evaluation["success"]
        status = "within baseline range" if ok else "outside baseline range"
        emoji = "✅" if ok else "❌"
        print(f"  📈 Recovery evaluation: {emoji} {status} (latency {cmp['latency_ratio']:.2f}x baseline, success ±{cmp['success_rate_diff']:.1f}% vs baseline)")

        # Print problem location evaluation
        expected = location_evaluation["expected_target"]
        expected_label = expected if expected is not None else "none"
        reported = location_evaluation["reported_locations"]
        reported_label = ", ".join(reported) if reported else "none"
        result_emoji = "✅" if location_evaluation["location_identified"] else "❌"
        print(f"  🎯 Problem location: expected={expected_label}; agent={reported_label}; result={result_emoji}")

    async def run_full_experiment(self) -> Dict[str, Any]:
        """Run the simplified chaos injection and mitigation experiment."""
        results = {
            "success": False,
            "agent_actions": [],
            "agent_trace": [],
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

                try:
                    # Deploy agent
                    agent_actions, agent_trace, operational_summary, agent_success = await self.deploy_mitigation_agent(
                        baseline_metrics, 
                        chaos_metrics
                    )

                    # Store agent execution results
                    results["agent_execution_duration_seconds"] = time.time() - agent_execution_start_time
                    results["agent_actions"] = agent_actions
                    results["agent_trace"] = agent_trace
                    results["agent_success"] = agent_success
                    results["operational_summary"] = operational_summary
                    results["problem_location"] = operational_summary.get("problem_location", []) if operational_summary else []
                    
                except KeyboardInterrupt:
                    # User interrupted during agent execution - preserve partial trace
                    print(f"\n⚠️  Agent execution interrupted by user (Ctrl+C)")
                    results["agent_execution_duration_seconds"] = time.time() - agent_execution_start_time
                    results["interrupted"] = True
                    results["error"] = "Agent execution interrupted by user (Ctrl+C)"
                    # Note: agent_trace should already be populated if agent started
                    # Re-raise to let outer handler deal with cleanup
                    raise
                
                except Exception as e:
                    # Agent failed but experiment continues - we still want recovery metrics
                    print(f"\n❌ Agent execution failed: {e}")
                    results["agent_execution_duration_seconds"] = time.time() - agent_execution_start_time
                    results["agent_success"] = False
                    results["error"] = f"Agent execution failed: {str(e)}"
                    logger.exception("Agent execution failed, but continuing with recovery metrics")
                    # Don't raise - continue to recovery phase
                    
            else:
                print(f"\n▶ Agent execution: DISABLED (baseline-chaos-recovery mode)")
            
            # === RECOVERY METRICS ===
            print(f"\n▶ Phase 4: Recovery metrics ({self.config['recovery_duration']}s)")
            await asyncio.sleep(self.config["recovery_duration"])
            
            recovery_metrics = collect_istio_ingress_metrics(self.config["recovery_duration"])
            results["phase_metrics"]["recovery"] = recovery_metrics

            # Evaluate and report all metrics
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
            
        except KeyboardInterrupt:
            # Experiment interrupted by user - mark as interrupted and preserve all data collected so far
            results["interrupted"] = True
            if not results.get("error"):
                results["error"] = "Experiment interrupted by user (Ctrl+C)"
            print(f"\n⚠️  Experiment interrupted - saving partial results and trace")
            # Re-raise to let batch runner handle it
            raise
            
        except Exception as e:
            results["error"] = str(e)
            print(f"\nTest failed: {e}")
            logger.exception("Test execution error")            
            return results
        
        finally:
            # Always cleanup (but skip if already cleaned in success path)
            if results.get("error") or results.get("interrupted"):
                await self.cleanup_all()