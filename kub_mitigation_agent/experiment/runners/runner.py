import asyncio
import time
from typing import Optional, Any, Callable
from datetime import datetime, timezone
from ..core.experiment import Experiment
import kub_mitigation_agent.service.k8s as k8s_module
from kub_mitigation_agent.generators.workload import LocustTrafficGenerator
from kub_mitigation_agent.paths import HOTEL_RESERVATION_METADATA
import json
from kub_mitigation_agent.generators.fault import cleanup_all_anomalies
from kub_mitigation_agent.agent.react_agent import ReactAgent
import kub_mitigation_agent.generators.fault as anomaly_pkg
from kub_mitigation_agent.service.telemetry.metrics import ExperimentMetrics
from kub_mitigation_agent.service.telemetry.prometheus import get_prometheus_client
from ..evaluators import evaluate_metrics_recovery, evaluate_problem_location_match
from kub_mitigation_agent.agent.config import KubernetesAgentConfig

# Optional UI event emission
try:
    from kub_mitigation_agent.ui.events import (
        emit_experiment_start, emit_phase, emit_agent_step, emit_experiment_end
    )
    UI_EVENTS_AVAILABLE = True
except ImportError:
    UI_EVENTS_AVAILABLE = False

class ExperimentRunner:
    """Orchestrates a single chaos experiment with dependency injection."""
    
    def __init__(
        self,
        experiment: Experiment,
        logger=None,
        metrics: Optional[ExperimentMetrics] = None,
        k8s_ops: Optional[Any] = None,
        traffic_generator_factory: Optional[type] = None,
        anomaly_manager: Optional[Any] = None,
        agent_class: Optional[type] = None,
        emit_ui_events: bool = False
    ):
        """
        Initialize experiment runner with injected dependencies.
        
        Args:
            experiment: The experiment to run
            logger: Optional logger instance
            metrics: Metrics service (defaults to ExperimentMetrics with Prometheus client)
            k8s_ops: K8s operations module (defaults to k8s_module)
            traffic_generator_factory: Traffic generator class (defaults to LocustTrafficGenerator)
            anomaly_manager: Anomaly management module (defaults to anomaly_pkg)
            agent_class: Agent class (defaults to ReactAgent)
            emit_ui_events: Whether to emit events for the UI server
        """
        self.exp = experiment
        self.logger = logger
        self.emit_ui_events = emit_ui_events and UI_EVENTS_AVAILABLE
        
        # Dependency injection with defaults
        if metrics is None:
            prom_client = get_prometheus_client()
            metrics = ExperimentMetrics(prom_client)
        
        self.metrics = metrics
        self.k8s_ops = k8s_ops if k8s_ops is not None else k8s_module
        self.traffic_generator_factory = traffic_generator_factory if traffic_generator_factory is not None else LocustTrafficGenerator
        self.anomaly_manager = anomaly_manager if anomaly_manager is not None else anomaly_pkg
        self.agent_class = agent_class if agent_class is not None else ReactAgent

        self._ensure_traffic_config()
    
    def _emit_phase(self, phase_name: str, status: str, metrics: Optional[dict] = None):
        """Emit phase event to UI if enabled."""
        if self.emit_ui_events:
            emit_phase(self.exp.id, phase_name, status, metrics)
    
    async def run(self) -> Experiment:
        """
        Execute experiment phases in order.
        
        Returns the same experiment object (now complete).
        """
        print(f"\n{'='*70}")
        print(f"🧪 EXPERIMENT: {self.exp.id}")
        print(f"{'='*70}")
        
        # Emit experiment start event
        if self.emit_ui_events:
            chaos_config = self.exp.anomaly.get_info() if self.exp.anomaly else {}
            emit_experiment_start(self.exp.id, {
                "namespace": self.exp.namespace,
                "chaos_config": chaos_config,
                "index": self.exp.index
            })
        
        try:
            # Run phases in order (phase functions mutate self.exp)
            await self.phase_setup()
            await self.phase_warmup()
            await self.phase_baseline()
            await self.phase_chaos()
            await self.phase_mitigation()
            await self.phase_recovery()
            
            # Evaluate results
            self.exp.recovery_evaluation = evaluate_metrics_recovery({
                "baseline": self.exp.baseline_metrics,
                "chaos": self.exp.chaos_metrics,
                "recovery": self.exp.recovery_metrics
            })
            
            chaos_config = self.exp.anomaly.get_info() if self.exp.anomaly else {}
            self.exp.location_evaluation = evaluate_problem_location_match(
                chaos_config, 
                self.exp.operational_summary.get("problem_location") if self.exp.operational_summary else None
            )
            
            # Print summary
            self._print_summary()
            
            # Mark success
            self.exp.success = self.exp.recovery_evaluation.get("success", False)
            
        except KeyboardInterrupt:
            self.exp.interrupted = True
            print("\n⚠️  Interrupted")
            raise
            
        except Exception as e:
            self.exp.error = str(e)
            print(f"\n❌ Failed: {e}")
            # We log the exception but allow the runner to return the partial experiment
            
        finally:
            # Always teardown and save
            try:
                await self.phase_teardown()
            except Exception as e:
                print(f"Error during teardown: {e}")
                
            self.exp.completed_at = datetime.now(timezone.utc)
            
            if self.logger:
                self.logger.log_experiment(self.exp)  # Logger calls exp.to_dict() internally
            
            # Emit experiment end event
            if self.emit_ui_events:
                status = "success" if self.exp.success else ("interrupted" if self.exp.interrupted else "failed")
                emit_experiment_end(self.exp.id, status, self.exp.operational_summary)
        
        return self.exp

    # ========== PHASE 1: SETUP ==========

    async def phase_setup(self):
        """Pre-cleanup + deploy application."""
        print(f"\n▶ Setup")
        self._emit_phase("setup", "started")
        
        # Stop anomalies (now handled explicitly here, not in k8s_ops)
        try:
            print(f"   • Stopping anomalies...", end="")
            anomaly_results = self.anomaly_manager.cleanup_all_anomalies(
                namespaces=[self.exp.namespace],
                nodes=self.exp.config.get("nodes", {}),
                chaosd_port=self.exp.config.get("chaosd_port", 31767)
            )
            summary = anomaly_results.get("summary", {})
            total_cleaned = summary.get("total_cleaned", 0)
            if total_cleaned > 0:
                print(f" ✅ Stopped {total_cleaned} experiments")
            else:
                print(f" ✅ None running")
        except Exception as e:
            print(f" ⚠️  Error: {e}")
        
        # Pre-cleanup: uncordon nodes, delete namespace (K8s operations only)
        self.k8s_ops.complete_pre_experiment_cleanup(
            self.exp.namespace,
            self.exp.config.get("nodes", {}),
            self.exp.config.get("chaosd_port", 31767)
        )
        
        # Deploy fresh app
        success, _ = self.k8s_ops.deploy_fresh_app_sync(self.exp.config)
        if not success:
            raise Exception("Failed to deploy application")
        
        print(f"  ✅ Complete")
        self._emit_phase("setup", "completed")


    # ========== PHASE 2: WARMUP ==========

    async def phase_warmup(self):
        """Start traffic and stabilize system."""
        duration = self.exp.config.get("warmup_duration", 0)
        if duration == 0:
            return
        
        print(f"\n▶ Warmup ({duration}s)")
        self._emit_phase("warmup", "started")
        
        # Instantiate traffic generator using the factory
        self.exp.traffic_generator = self.traffic_generator_factory(self.exp.config["traffic_config"])
        await self.exp.traffic_generator.start_traffic()
        await asyncio.sleep(duration)
        
        print(f"  ✅ Complete")
        self._emit_phase("warmup", "completed")


    # ========== PHASE 3: BASELINE ==========

    async def phase_baseline(self):
        """Measure normal system performance."""
        duration = self.exp.config["baseline_duration"]
        print(f"\n▶ Baseline ({duration}s)")
        self._emit_phase("baseline", "started")
        
        # Start traffic if not running
        if not self.exp.traffic_generator:
            self.exp.traffic_generator = self.traffic_generator_factory(self.exp.config["traffic_config"])
            await self.exp.traffic_generator.start_traffic()
        
        await asyncio.sleep(duration)
        
        self.exp.baseline_metrics = self.metrics.get_istio_ingress_metrics(duration)
        
        print(f"  ✅ {self.exp.baseline_metrics['success_rate_percent']:.1f}% success, "
            f"P95: {self.exp.baseline_metrics['p95_latency_seconds']:.3f}s, "
            f"Requests: {self.exp.baseline_metrics.get('total_requests', 0)}")
        self._emit_phase("baseline", "completed", self.exp.baseline_metrics)


    # ========== PHASE 4: CHAOS ==========

    async def phase_chaos(self):
        """Inject anomaly and measure impact."""
        print(f"\n▶ Chaos")
        self._emit_phase("chaos", "started")
        
        # Inject anomaly
        print(f"  Injecting...", end="")
        self.exp.anomaly_handle = self.exp.anomaly.start()
        print(" ✅")
        
        # Warmup + measure
        warmup = self.exp.config["chaos_warmup_duration"]
        await asyncio.sleep(warmup)
        
        self.exp.chaos_metrics = self.metrics.get_istio_ingress_metrics(warmup)
        
        print(f"  ⚠️  {self.exp.chaos_metrics['success_rate_percent']:.1f}% success, "
            f"P95: {self.exp.chaos_metrics['p95_latency_seconds']:.3f}s, "
            f"Requests: {self.exp.chaos_metrics.get('total_requests', 0)}")
        self._emit_phase("chaos", "completed", self.exp.chaos_metrics)


    # ========== PHASE 5: MITIGATION ==========

    async def phase_mitigation(self):
        """Run agent to diagnose and fix problem."""
        if not self.exp.agent_config or not self.exp.agent_config.enabled:
            print(f"\n▶ Mitigation: DISABLED")
            return
        
        print(f"\n▶ Mitigation")
        self._emit_phase("mitigation", "started")
        
        # Initialize agent using the injected class
        agent = self.agent_class(self.exp.agent_config)
        
        # Set up step callback for UI events if enabled
        if self.emit_ui_events:
            agent.on_step_callback = self._create_step_callback()
        
        await agent.initialize()
        
        # Prepare agent inputs (Snapshot)
        snapshot = {
            "namespace": self.exp.namespace,
            "alert_type": "performance_degradation",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "baseline_latency_p95": self.exp.baseline_metrics['p95_latency_seconds'],
            "baseline_success_rate": self.exp.baseline_metrics['success_rate_percent'],
            "current_latency_p95": self.exp.chaos_metrics['p95_latency_seconds'],
            "current_success_rate": self.exp.chaos_metrics['success_rate_percent']
        }
        
        start_time = time.time()
        try:
            # Agent uses default intent if not provided
            trace, summary = await agent.agent_loop(snapshot=snapshot)
            self.exp.agent_trace = trace
            self.exp.operational_summary = summary
            self.exp.agent_success = True
            print(f"  ✅ {len(trace)} steps")
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            self.exp.agent_success = False
            # We don't re-raise here because we want to proceed to recovery measurement
        finally:
            end_time = time.time()
            self.exp.agent_duration_seconds = end_time - start_time
            await agent.cleanup()
            self._emit_phase("mitigation", "completed", {"steps": len(self.exp.agent_trace)})
    
    def _create_step_callback(self) -> Callable:
        """Create a callback function for emitting agent step events."""
        def callback(step_number: int, thought: str, actions: list, observations: list):
            emit_agent_step(self.exp.id, step_number, thought, actions, observations)
        return callback


    # ========== PHASE 6: RECOVERY ==========

    async def phase_recovery(self):
        """Measure post-mitigation performance."""
        duration = self.exp.config["recovery_duration"]
        print(f"\n▶ Recovery ({duration}s)")
        self._emit_phase("recovery", "started")
        
        await asyncio.sleep(duration)
        
        self.exp.recovery_metrics = self.metrics.get_istio_ingress_metrics(duration)
        
        print(f"  ✅ {self.exp.recovery_metrics['success_rate_percent']:.1f}% success, "
            f"P95: {self.exp.recovery_metrics['p95_latency_seconds']:.3f}s, "
            f"Requests: {self.exp.recovery_metrics.get('total_requests', 0)}")
        self._emit_phase("recovery", "completed", self.exp.recovery_metrics)


    # ========== PHASE 7: TEARDOWN ==========

    async def phase_teardown(self):
        """Cleanup all experiment resources."""
        print(f"\n▶ Teardown")
        
        # Stop traffic
        if self.exp.traffic_generator:
            try:
                await self.exp.traffic_generator.stop_traffic()
            except Exception as e:
                print(f"  ⚠️  Traffic: {e}")
        
        # Stop anomaly
        if self.exp.anomaly_handle:
            try:
                self.exp.anomaly.stop()
            except Exception as e:
                print(f"  ⚠️  Anomaly: {e}")
        
        # Comprehensive cleanup
        try:
            self.anomaly_manager.cleanup_all_anomalies(
                namespaces=[self.exp.namespace],
                nodes=self.exp.config.get("nodes", {}),
                chaosd_port=self.exp.config.get("chaosd_port", 31767)
            )
        except Exception as e:
            print(f"  ⚠️  Cleanup: {e}")
        
        # Undeploy app
        try:
            self.k8s_ops.undeploy_app_sync(self.exp.config)
        except Exception as e:
            print(f"  ⚠️  Undeploy: {e}")
        
        print(f"  ✅ Complete")

    def _ensure_traffic_config(self) -> None:
        """Populate traffic_config from app metadata when missing."""
        traffic_config = self.exp.config.get("traffic_config", {})
        if traffic_config.get("host"):
            return

        # Default to Hotel Reservation metadata for now (avoid app init side effects)
        with open(HOTEL_RESERVATION_METADATA, "r") as file:
            metadata = json.load(file)
        workload = metadata.get("Workload", {})

        self.exp.config["traffic_config"] = {
            "workload_pattern": workload.get("profile", "hotel_reservation"),
            "host": workload.get("host", "http://localhost:8080"),
            "num_users": workload.get("default_users", 10),
            "spawn_rate": workload.get("spawn_rate", 2),
            "wait_time_min": workload.get("wait_time_min", 1),
            "wait_time_max": workload.get("wait_time_max", 3),
        }
    
    def _print_summary(self):
        """Print experiment summary."""
        if not self.exp.recovery_evaluation:
            return
        
        r = self.exp.recovery_evaluation
        print(f"\n📊 Results:")
        print(f"  Recovery: {'✅' if r['success'] else '❌'}")
        
        # Print metrics comparison
        cmp = r.get("metrics_comparison", {})
        if cmp:
            print(f"  Baseline: P95: {cmp.get('baseline_latency_p95', 0):.3f}s, Success: {cmp.get('baseline_success_rate', 0):.1f}%, Requests: {cmp.get('baseline_request_count', 0)}")
            print(f"  Chaos:    P95: {cmp.get('chaos_latency_p95', 0):.3f}s, Success: {cmp.get('chaos_success_rate', 0):.1f}%, Requests: {cmp.get('chaos_request_count', 0)}")
            print(f"  Recovery: P95: {cmp.get('recovery_latency_p95', 0):.3f}s, Success: {cmp.get('recovery_success_rate', 0):.1f}%, Requests: {cmp.get('recovery_request_count', 0)}")
            
            # Latency stats
            base_p95 = cmp.get('baseline_latency_p95', 0)
            rec_p95 = cmp.get('recovery_latency_p95', 0)
            chaos_p95 = cmp.get('chaos_latency_p95', 0)
            
            if base_p95 > 0:
                diff_pct = ((rec_p95 - base_p95) / base_p95) * 100
                diff_str = f"{abs(diff_pct):.1f}% {'slower' if diff_pct > 0 else 'faster'} than baseline"
            else:
                diff_str = "N/A"
            
            if chaos_p95 > 0 and rec_p95 < chaos_p95:
                 imp_pct = ((chaos_p95 - rec_p95) / chaos_p95) * 100
                 imp_str = f"{imp_pct:.1f}% improvement from chaos"
            else:
                 imp_str = "No improvement"

            print(f"  Stats:    {diff_str} | {imp_str}")
        
        if self.exp.location_evaluation:
            l = self.exp.location_evaluation
            print(f"  Location: {'✅' if l['location_identified'] else '❌'} "
                  f"Expected: {l['expected_target']}, Found: {l['reported_locations']}")
