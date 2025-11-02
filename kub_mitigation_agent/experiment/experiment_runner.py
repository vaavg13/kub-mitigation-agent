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

# CRITICAL: Import TrafficGenerator FIRST (contains Locust) before Kubernetes
# This ensures proper SSL monkey-patching order to prevent recursion errors
from .traffic_generator import LocustTrafficGenerator

# Import other project modules
from ..anomalies.chaos_mesh_handler import ChaosMeshHandler
from kub_mitigation_agent.agent.agent import KubernetesAgent
from kub_mitigation_agent.agent.config import KubernetesAgentConfig
from kub_mitigation_agent.clients.prometheus_client import get_prometheus_tool
from .alert_config import build_intent, build_snapshot
from .recovery_evaluator import evaluate_metrics_recovery, evaluate_problem_location_match
from .experiment_k8s_ops import collect_istio_ingress_metrics

logger = logging.getLogger(__name__)

class MitigationExperimentRunner:
    """Orchestrates chaos injection and agent mitigation testing."""
    
    def __init__(self, 
        experiment_config: Dict[str, Any],
        experiment_id: Optional[str] = None,
        agent_config: Optional[KubernetesAgentConfig] = None
    ):
        self.config = experiment_config
        self.experiment_id = experiment_id
        self.agent_config = agent_config or KubernetesAgentConfig()
        
        # Initialize components
        self.chaos_mesh_handler = None
        self.agent = None
        self.traffic_generator = None
        self.chaos_experiment = None
        
        # Initialize Prometheus metrics tool using singleton
        self.prometheus_tool = get_prometheus_tool()
        
        # No longer storing metrics in class attributes - passed as parameters for traceability
        
    async def setup(self):
        # Initialize Anomalie Handlers and Traffic Generator
        self.chaos_mesh_handler = ChaosMeshHandler(self.config)        
        self.traffic_generator = LocustTrafficGenerator(self.config["traffic_config"])
        
        if self.agent_config.enabled:
            self.agent = KubernetesAgent(self.agent_config)
 
    async def inject_chaos(self) -> bool:
        """Inject chaos into the target application based on configuration mode."""
        config = self.config['chaos_config']
        mode = config['mode']

        if mode == "no_failure":
            # No chaos experiment to track
            self.chaos_experiment = None
            return True
        elif mode == "chaos_only":
            exp = self.chaos_mesh_handler.inject_chaos_mesh_only(config)
            if exp:
                self.chaos_experiment = exp
                return True
            return False
        else:
            print(f"  ❌ Unknown chaos mode: {mode}")
            return False
    
    def _prepare_agent_inputs(
        self, 
        baseline_metrics: Dict[str, Any],
        current_metrics: Dict[str, Any]
    ) -> tuple[str, Dict[str, Any]]:
        """Prepare intent and snapshot for agent execution.
        
        Args:
            baseline_metrics: Traffic generator metrics from baseline phase
            current_metrics: Traffic generator metrics from chaos phase
            
        Returns:
            (intent, snapshot) tuple for agent execution
        """
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
        """Execute mitigation agent.
        
        Args:
            baseline_metrics: Traffic generator metrics from baseline phase
            current_metrics: Traffic generator metrics from chaos phase
            
        Returns:
            (actions, summary, success) tuple
        """
        # Initialize agent if needed
        if not self.agent.is_initialized:
            await self.agent.initialize()
        
        # Build intent and snapshot from traffic generator metrics
        intent, snapshot = self._prepare_agent_inputs(baseline_metrics, current_metrics)
        
        # Run agent - let exceptions propagate
        actions, summary = await self.agent.agent_loop(intent, snapshot)
        return actions, summary, True


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
                if mode != "no_failure":
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
        
        # 3. Clean up agent (if enabled)
        if self.agent_config.enabled and self.agent and self.config.get("test_settings", {}).get("cleanup_after_test", True):
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
            


    async def run_full_experiment(self) -> Dict[str, Any]:
        """Run the simplified chaos injection and mitigation experiment."""
        results = {
            "success": False,
            "phases_completed": [],
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
            # Setup
            await self.setup()
            
            # === WARMUP PHASE (for all experiments) ===
            warmup_duration = self.config.get("warmup_duration", 0)
            if warmup_duration > 0:
                print(f"\n▶ Phase 1: Warmup ({warmup_duration}s)")
                await self.traffic_generator.start_traffic()
                await asyncio.sleep(warmup_duration)
                print(f"  ✅ Warmup complete (pods, Istio, connection pools stabilized)")
                results["phases_completed"].append("warmup")
            
            # === BASELINE METRICS ===
            phase_label = "Phase 2" if warmup_duration > 0 else "Phase 1"
            print(f"\n▶ {phase_label}: Baseline metrics ({self.config['baseline_duration']}s)")
            if warmup_duration == 0:
                await self.traffic_generator.start_traffic()
            await asyncio.sleep(self.config["baseline_duration"])
            baseline_metrics = collect_istio_ingress_metrics(self.config["baseline_duration"])
            results["phase_metrics"]["baseline"] = baseline_metrics
            metrics_source = baseline_metrics.get("source", "unknown")
            print(f"  ✅ Measured ({metrics_source}): {baseline_metrics['success_rate_percent']:.1f}% success, P95: {baseline_metrics['p95_latency_seconds']:.3f}s")
            
            results["phases_completed"].append("baseline")
            
            print(f"\n▶ Chaos injection: ", end="")
            if await self.inject_chaos():
                print("✅ Active")
                results["phases_completed"].append("chaos_injection")
            else:
                print("❌ Failed")
                raise Exception("Failed to inject chaos")
            
            # === CHAOS WARMUP (record metrics during active chaos) ===
            phase_num = 3 if warmup_duration > 0 else 2
            print(f"\n▶ Phase {phase_num}: Chaos metrics ({self.config['chaos_warmup_duration']}s)")
            await asyncio.sleep(self.config["chaos_warmup_duration"])
            
            chaos_metrics = collect_istio_ingress_metrics(self.config["chaos_warmup_duration"])
            results["phase_metrics"]["chaos"] = chaos_metrics
            metrics_source = chaos_metrics.get("source", "unknown")
            print(f"  ⚠️  Chaos ({metrics_source}): {chaos_metrics['success_rate_percent']:.1f}% success, P95: {chaos_metrics['p95_latency_seconds']:.3f}s")
            
            results["phases_completed"].append("chaos_warmup")
            
            # === AGENT EXECUTION (during active chaos) ===
            if self.agent_config.enabled:
                print(f"\n▶ Agent execution (chaos active)")
                agent_execution_start_time = time.time()
                agent_actions, operational_summary, agent_success = await self.deploy_mitigation_agent(
                    baseline_metrics, 
                    chaos_metrics
                )
                results["agent_execution_duration_seconds"] = time.time() - agent_execution_start_time
                results["agent_actions"] = agent_actions
                results["agent_success"] = agent_success
                results["operational_summary"] = operational_summary
                results["problem_location"] = operational_summary.get("problem_location", []) if operational_summary else []
                results["phases_completed"].append("agent_execution")
                
                # Print operational summary
                if operational_summary:
                    print(f"\n📋 Operational Summary:")
                    print(f"  • Objective: {operational_summary.get('objective', 'N/A')}")
                    print(f"  • Status: {operational_summary.get('status', 'N/A')}")
                    print(f"  • Success: {'✅' if operational_summary.get('success') else '❌'}")
                    # Always show Problem Location (even if none)
                    problem_location_list = operational_summary.get('problem_location') or []
                    if problem_location_list:
                        print(f"  • Problem Location:")
                        for loc in problem_location_list:
                            print(f"    - {loc.get('type', 'unknown')}: {loc.get('name', 'N/A')}")
                    else:
                        print(f"  • Problem Location: none")
                    if operational_summary.get('actions_completed'):
                        print(f"  • Actions: {', '.join(operational_summary['actions_completed'])}")
                    if operational_summary.get('results_achieved'):
                        print(f"  • Results:")
                        for result in operational_summary['results_achieved']:
                            print(f"    - {result}")
                else:
                    print(f"\n⚠️  No operational summary generated")
            else:
                print(f"\n▶ Agent execution: DISABLED (baseline-chaos-recovery mode)")
                results["phases_completed"].append("agent_execution_skipped")
            
            # === RECOVERY METRICS ===
            phase_num = 4 if warmup_duration > 0 else 3
            print(f"\n▶ Phase {phase_num}: Recovery metrics ({self.config['recovery_duration']}s)")
            await asyncio.sleep(self.config["recovery_duration"])
            
            recovery_metrics = collect_istio_ingress_metrics(self.config["recovery_duration"])
            results["phase_metrics"]["recovery"] = recovery_metrics
            metrics_source = recovery_metrics.get("source", "unknown")
            print(f"  🩹 Recovery ({metrics_source}): {recovery_metrics['success_rate_percent']:.1f}% success, P95: {recovery_metrics['p95_latency_seconds']:.3f}s")
            # Explicit recovery evaluation against baseline
            recovery_eval_preview = evaluate_metrics_recovery(results["phase_metrics"])  # uses baseline vs recovery
            cmp = recovery_eval_preview.get("metrics_comparison", {})
            lr = cmp.get("latency_ratio")
            sd = cmp.get("success_rate_diff")
            ok = recovery_eval_preview.get("success", False)
            status_label = "within baseline range" if ok else "outside baseline range"
            emoji = "✅" if ok else "❌"
            # Show baseline vs recovery details
            baseline_m = results["phase_metrics"].get("baseline", {})
            chaos_m = results["phase_metrics"].get("chaos", {})
            b_sr = baseline_m.get("success_rate_percent")
            b_p95 = baseline_m.get("p95_latency_seconds")
            c_sr = chaos_m.get("success_rate_percent")
            c_p95 = chaos_m.get("p95_latency_seconds")
            r_sr = recovery_metrics.get("success_rate_percent")
            r_p95 = recovery_metrics.get("p95_latency_seconds")
            if c_sr is not None and c_p95 is not None:
                print(f"  📊 Chaos: {c_sr:.1f}% success, P95: {c_p95:.3f}s")
            print(f"  📊 Baseline: {b_sr:.1f}% success, P95: {b_p95:.3f}s")
            print(f"  📊 Recovery: {r_sr:.1f}% success, P95: {r_p95:.3f}s")
            if isinstance(lr, (int, float)) and isinstance(sd, (int, float)):
                print(f"  📈 Recovery evaluation: {emoji} {status_label} (latency {lr:.2f}x baseline, success ±{sd:.1f}% vs baseline)")
            else:
                print(f"  📈 Recovery evaluation: {emoji} {status_label}")
            
            # Evaluate problem location identification
            problem_location = results.get("operational_summary", {}).get("problem_location") if results.get("operational_summary") else None
            location_evaluation = evaluate_problem_location_match(
                self.config.get("chaos_config", {}),
                problem_location
            )
            results["location_evaluation"] = location_evaluation
            
            # Print standardized problem location identification results
            expected_target = location_evaluation.get('expected_target')
            expected_label = expected_target if expected_target is not None else "none"
            reported_locations = location_evaluation.get('reported_locations') or []
            if isinstance(reported_locations, list):
                reported_label = ", ".join([str(x) for x in reported_locations]) if reported_locations else "none"
            else:
                reported_label = str(reported_locations)
            result_emoji = "✅" if location_evaluation.get("location_identified") else "❌"
            print(f"  🎯 Problem location: expected={expected_label}; agent={reported_label}; result={result_emoji}")
            
            results["phases_completed"].append("recovery")
            
            # === CLEANUP AND FINAL METRICS ===
            print(f"\n▶ Cleanup: ", end="")
            await self.cleanup_all()
            print("✅ Complete")
            
            # Evaluate metrics recovery
            recovery_evaluation = evaluate_metrics_recovery(results["phase_metrics"])
            results["recovery_evaluation"] = recovery_evaluation
            
            # Set overall experiment success based on recovery evaluation
            results["success"] = recovery_evaluation["success"]
            results["recovery_successful"] = recovery_evaluation["success"]
            results["recovery_reason"] = recovery_evaluation["reason"]
            
            return results
            
        except Exception as e:
            results["error"] = str(e)
            print(f"\nTest failed: {e}")
            logger.exception("Test execution error")            
            return results
        
        finally:
            # Always cleanup (but skip if already cleaned in success path)
            if results.get("error"):
                await self.cleanup_all(emergency=False)