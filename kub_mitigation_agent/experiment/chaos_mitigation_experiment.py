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
from ..anomalies.docker_constraints_handler import DockerConstraintsHandler
from ..anomalies.chaos_mesh_handler import ChaosMeshHandler
from ..anomalies.traffic_spike_handler import TrafficSpikeHandler
from kub_mitigation_agent.agent.agent import KubernetesAgent
from kub_mitigation_agent.agent.config import KubernetesAgentConfig
from kub_mitigation_agent.shared.prometheus_client import get_prometheus_tool
from .alert_config import build_intent, build_snapshot
from .recovery_evaluator import evaluate_metrics_recovery, evaluate_problem_location_match

logger = logging.getLogger(__name__)

class ChaosAndMitigationExperiment:
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
        self.docker_handler = None
        self.chaos_mesh_handler = None
        self.traffic_spike_handler = None
        self.agent = None
        self.traffic_generator = None
        self.chaos_experiment = None
        
        # Initialize Prometheus metrics tool using singleton
        self.prometheus_tool = get_prometheus_tool()
        
        # No longer storing metrics in class attributes - passed as parameters for traceability
        
    async def setup(self):
        # Initialize Anomalie Handlers and Traffic Generator
        self.docker_handler = DockerConstraintsHandler(self.config)
        self.chaos_mesh_handler = ChaosMeshHandler(self.config)        
        self.traffic_generator = LocustTrafficGenerator(self.config["traffic_config"])
        self.traffic_spike_handler = TrafficSpikeHandler(self.config, self.traffic_generator)
        
        self.agent = KubernetesAgent(self.agent_config)
 
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
        elif mode == "traffic_spike_only":
            exp = self.traffic_spike_handler.inject_traffic_spike_only(config)
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
                if mode == "docker_only":
                    if emergency:
                        print("Docker-only experiment: No Chaos Mesh cleanup required")
                elif mode == "traffic_spike_only":
                    # No cleanup needed - traffic is already stopped, and each experiment
                    # creates a fresh traffic generator from config with original RPS
                    if emergency:
                        print("Traffic spike experiment: No cleanup needed (traffic already stopped)")
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
            
            # === BASELINE METRICS ===
            prerecorded_baseline = self.config.get("prerecorded_baseline")
            
            if prerecorded_baseline:
                # Use prerecorded baseline from first experiment
                print(f"\n▶ Phase 1: Baseline metrics (prerecorded)")
                baseline_metrics = prerecorded_baseline
                results["phase_metrics"]["baseline"] = baseline_metrics
                print(f"  ♻️  Reused: {baseline_metrics['success_rate_percent']:.1f}% success, P95: {baseline_metrics['p95_latency_seconds']:.3f}s")
            else:
                # Measure baseline normally
                print(f"\n▶ Phase 1: Baseline metrics ({self.config['baseline_duration']}s)")
                await self.traffic_generator.start_traffic()
                self.traffic_generator.reset_phase_metrics()
                await asyncio.sleep(self.config["baseline_duration"])
                baseline_metrics = self.traffic_generator.get_phase_metrics(self.config["baseline_duration"])
                results["phase_metrics"]["baseline"] = baseline_metrics
                print(f"  ✅ Measured: {baseline_metrics['success_rate_percent']:.1f}% success, P95: {baseline_metrics['p95_latency_seconds']:.3f}s")
            
            results["phases_completed"].append("baseline")
            
            # === CHAOS INJECTION ===
            if prerecorded_baseline:
                await self.traffic_generator.start_traffic()
            
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
            
            results["phases_completed"].append("chaos_warmup")
            
            # === AGENT EXECUTION (during active chaos) ===
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
                if operational_summary.get('problem_location'):
                    print(f"  • Problem Location:")
                    for loc in operational_summary['problem_location']:
                        print(f"    - {loc.get('type', 'unknown')}: {loc.get('name', 'N/A')}")
                if operational_summary.get('actions_completed'):
                    print(f"  • Actions: {', '.join(operational_summary['actions_completed'])}")
                if operational_summary.get('results_achieved'):
                    print(f"  • Results:")
                    for result in operational_summary['results_achieved']:
                        print(f"    - {result}")
            else:
                print(f"\n⚠️  No operational summary generated")
            
            # === PHASE 4: RECOVERY METRICS ===
            print(f"\n▶ Phase 4: Recovery metrics ({self.config['recovery_duration']}s)")
            # Reset metrics at START of recovery measurement phase (after agent execution)
            self.traffic_generator.reset_phase_metrics()
            await asyncio.sleep(self.config["recovery_duration"])
            
            recovery_metrics = self.traffic_generator.get_phase_metrics(self.config["recovery_duration"])
            results["phase_metrics"]["recovery"] = recovery_metrics
            print(f"  🩹 Recovery: {recovery_metrics['success_rate_percent']:.1f}% success, P95: {recovery_metrics['p95_latency_seconds']:.3f}s")
            
            # Evaluate problem location identification
            problem_location = results.get("operational_summary", {}).get("problem_location") if results.get("operational_summary") else None
            location_evaluation = evaluate_problem_location_match(
                self.config.get("chaos_config", {}),
                problem_location
            )
            results["location_evaluation"] = location_evaluation
            
            # Print location identification results
            if location_evaluation["location_identified"]:
                # Correctly identified (including empty list for baseline)
                if location_evaluation['expected_target'] is None:
                    print(f"  ✅ Baseline: Agent correctly reported no problem location")
                else:
                    print(f"  ✅ Problem location correctly identified: {location_evaluation['expected_target']}")
            else:
                print(f"  ❌ Problem location mismatch:")
                expected = location_evaluation['expected_target'] or "none (baseline)"
                print(f"     Expected: {expected}")
                print(f"     Reported: {location_evaluation['reported_locations']}")
            
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