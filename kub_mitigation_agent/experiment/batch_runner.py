import re
from datetime import datetime, timezone
from typing import Dict, Any, List
from .experiment import Experiment
from .experiment_runner import ExperimentRunner
from .experiment_logger import SimpleExperimentLogger
from .services import DefaultServices, ServiceRegistry

# Import Anomaly Config Generator
from kub_mitigation_agent.anomalies.anomaly_config_generator import AnomalyConfigGenerator, DEFAULT_SEED

class BatchExperimentRunner:
    """Coordinates multiple experiments in a batch."""
    
    def __init__(self, batch_config: Dict[str, Any], agent_config, output_base_dir: str = "DATA"):
        self.batch_config = batch_config
        self.agent_config = agent_config
        self.output_base_dir = output_base_dir
        self.batch_settings = batch_config.get("batch_settings", {})
        self.random_seed = self.batch_settings.get("random_seed", DEFAULT_SEED)
        
        # Use Default Services (or injected ones if we extended constructor)
        self.services = DefaultServices.get_registry()
        
        # Generate anomalies from spec
        generator = AnomalyConfigGenerator(batch_config, seed=self.random_seed)
        nodes_map = self.batch_config.get("nodes", {})
        chaosd_port = int(self.batch_config.get("chaosd", {}).get("port", 31767))
        
        self.anomalies = generator.generate_instances_from_spec(
            nodes_map,
            chaosd_port
        )
        
        # Setup logger
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        namespace = self.batch_config.get("namespace", "unknown-app")
        self.batch_id = f"batch_{timestamp}_{namespace}"
        
        self.logger = SimpleExperimentLogger(
            output_dir=self.output_base_dir,
            batch_id=self.batch_id,
            model_name=getattr(self.agent_config, "model", None)
        )
        self.experiments: List[Experiment] = []
    
    async def run_batch(self) -> Dict[str, Any]:
        """Run all experiments in sequence."""
        print(f"\n{'='*70}")
        print(f"🎯 BATCH: {self.batch_id}")
        print(f"📊 {len(self.anomalies)} experiments")
        print(f"🤖 Agent Model: {getattr(self.agent_config, 'model', 'unknown')}")
        print(f"{'='*70}\n")
        
        try:
            for idx, anomaly in enumerate(self.anomalies):
                # Create experiment object
                exp_id = self._generate_id(idx, anomaly)
                
                # Create clean experiment config (copy to ensure isolation)
                exp_config = self.batch_config.copy()
                
                exp = Experiment(
                    id=exp_id,
                    index=idx + 1,
                    namespace=self.batch_config.get("namespace", "default"),
                    anomaly=anomaly,
                    config=exp_config,
                    agent_config=self.agent_config
                )
                
                # Run it
                runner = ExperimentRunner(exp, self.logger, self.services)
                try:
                    exp = await runner.run()
                    self.experiments.append(exp)
                except KeyboardInterrupt:
                    print(f"\n🛑 Batch interrupted")
                    # Save what we have so far
                    self.experiments.append(exp)
                    break
        
        finally:
            # Save summary
            summary = self._build_summary()
            self.logger.save_batch_summary(summary)
            print(f"\n💾 Saved: {self.logger.output_dir}/batch_summary.json")
            return summary
    
    def _generate_id(self, idx: int, anomaly) -> str:
        """Generate readable experiment ID."""
        info = anomaly.get_info()
        
        # Fallback defaults
        mode = info.get("mode", "chaos")
        fault = info.get("fault_type") or info.get("type") or "anomaly"
        
        parts = [
            f"{idx+1:03d}",
            str(mode),
            str(fault)
        ]
        
        # Try to find a target name
        target = info.get("target", {})
        target_label = next(
            (target.get(field) for field in ("name", "app", "namespace", "node", "resource") if target.get(field)),
            None,
        )
        
        if target_label:
            parts.append(str(target_label))
        
        slug = "-".join(parts).lower().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9-]+", "-", slug)
        return f"exp_{slug}"
    
    def _build_summary(self) -> Dict[str, Any]:
        """Aggregate batch results."""
        successful = sum(1 for e in self.experiments if e.success)
        
        correct_locations = 0
        total_locations = 0
        
        for e in self.experiments:
            if e.location_evaluation and e.location_evaluation.get("location_identified") is not None:
                total_locations += 1
                if e.location_evaluation.get("location_identified"):
                    correct_locations += 1
                    
        location_accuracy = (correct_locations / total_locations * 100) if total_locations > 0 else 0
        
        # Build the experiments list for the summary
        exp_summaries = []
        for e in self.experiments:
            chaos_info = e.anomaly.get_info() if e.anomaly else {}
            exp_summaries.append({
                "id": e.id,
                "chaos": f"{chaos_info.get('mode', 'unknown')}_{chaos_info.get('fault_type', 'unknown')}",
                "success": e.success,
                "agent_trace_steps": len(e.agent_trace),
                "recovery_successful": e.recovery_evaluation.get("success", False) if e.recovery_evaluation else False,
                "location_identified": e.location_evaluation.get("location_identified") if e.location_evaluation else None
            })
            
        return {
            "batch_id": self.batch_id,
            "total_experiments": len(self.anomalies), # Total planned
            "completed": len(self.experiments),       # Total actually run
            "successful_experiments": successful,
            "failed_experiments": len(self.experiments) - successful,
            "location_identification_accuracy": location_accuracy,
            "started_at": self.experiments[0].started_at.isoformat() if self.experiments else datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "experiments": exp_summaries
        }
