import time
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any
from .experiment_runner import MitigationExperimentRunner
from .experiment_k8s_ops import deploy_fresh_app_sync, undeploy_app_sync, complete_pre_experiment_cleanup
from kub_mitigation_agent.clients.mcp_client import kubectl_ready
from kub_mitigation_agent.clients.prometheus_client import prometheus_ready
from .experiment_logger import SimpleExperimentLogger
from kub_mitigation_agent.anomalies.anomaly_config_generator import AnomalyConfigGenerator, DEFAULT_SEED
from ..agent.config import KubernetesAgentConfig

logger = logging.getLogger(__name__)

class BatchExperimentRunner:    
    def __init__(
        self, 
        batch_config: Dict[str, Any], 
        output_base_dir: str = "DATA", 
        agent_config: KubernetesAgentConfig = None
    ):
        # Preflight checks
        assert batch_config is not None, "batch_config is required - cannot run batch experiments without configuration"
        assert agent_config is not None, "agent_config is required - cannot run experiments without agent configuration"
        assert kubectl_ready(), "kubectl is not reachable. Ensure KUBECONFIG is set and cluster is accessible."
        assert prometheus_ready(), "Prometheus is not reachable at http://localhost:9090."

        self.batch_config = batch_config
        self.batch_settings = batch_config.get("batch_settings", {})
        self.output_base_dir = output_base_dir
        self.agent_config = agent_config
        
        # Generate chaos configurations from explicit specification in config
        self.random_seed = self.batch_settings.get("random_seed", DEFAULT_SEED)
        
        # Show available resources
        self.available_nodes_count = len(self.batch_config.get("nodes", {}))
        self.available_apps_count = len(self.batch_config.get("available_deployments", []))

        # Generate concrete anomaly instances from spec
        generator = AnomalyConfigGenerator(batch_config, seed=self.random_seed)
        nodes_map = self.batch_config.get("nodes", {})
        chaosd_port = int(self.batch_config.get("chaosd", {}).get("port", 31767))
        self.anomalies = generator.generate_instances_from_spec(nodes_map, chaosd_port)

        # Extract namespace/application name from config
        namespace = self.batch_config.get("namespace", "unknown-app")
        
        # Results storage with enhanced batch ID including date and namespace
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        self.batch_results = {
            "batch_id": f"batch_{timestamp}_{namespace}",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total_experiments": len(self.anomalies),
            "successful_experiments": 0,
            "failed_experiments": 0,
            "experiments": []
        }
        
        # Initialize simple logger
        self.simple_logger = SimpleExperimentLogger(
            output_dir=self.output_base_dir,
            batch_id=self.batch_results["batch_id"],
            model_name=getattr(self.agent_config, "model", None),
        )


    def _create_experiment_config(self) -> Dict[str, Any]:
        """Create complete experiment config (no anomaly-specific data)."""
        return self.batch_config.copy()
    
    def _build_experiment_id(self, index: int, chaos_info: Dict[str, Any]) -> str:
        """Create a readable experiment ID based on anomaly metadata."""
        fault_label = chaos_info.get("fault_type") or chaos_info.get("type") or "anomaly"
        mode_label = chaos_info.get("mode") or "chaos"

        target = chaos_info.get("target") or {}
        target_label = next(
            (target.get(field) for field in ("name", "app", "namespace", "node", "resource") if target.get(field)),
            None,
        )

        slug_parts = [f"{index + 1:03d}", mode_label, fault_label]
        if target_label:
            slug_parts.append(str(target_label))

        raw_slug = "-".join(slug_parts)
        normalized_slug = re.sub(r"[^a-zA-Z0-9-]+", "-", raw_slug).strip("-").lower()
        return f"exp_{normalized_slug}"
    
    async def run_single_experiment(
        self, 
        experiment_config: Dict[str, Any],
        experiment_id: str,
        index: int,
        anomaly_instance,
    ) -> Dict[str, Any]:

        ai = anomaly_instance.get_info()

        print(f"\n{'='*70}")
        print(f"🧪 EXPERIMENT {index + 1}/{len(self.anomalies)}: {experiment_id}")
        print(f"   Anomaly: {ai}")
        print(f"{'='*70}")
        

        # Initialize result structure with metadata only
        experiment_result = {
            "experiment_id": experiment_id,
            "index": index + 1,
            "namespace": experiment_config["namespace"],
            "chaos_config": ai,
        }
        
        try:
            # Step 0: Complete pre-experiment cleanup
            # Clean up any residual chaos state from previous experiments
            nodes = self.batch_config.get("nodes", {})
            chaosd_port = int(self.batch_config.get("chaosd", {}).get("port", 31767))
            cleanup_results = complete_pre_experiment_cleanup(
                namespace=experiment_config["namespace"],
                nodes=nodes,
                chaosd_port=chaosd_port
            )
            experiment_result["pre_cleanup_results"] = cleanup_results
            
            # Step 1: Deploy fresh application
            print(f"\n▶ Deploying fresh application...", end="")
            deployment_success, _ns = deploy_fresh_app_sync(experiment_config)
            
            if not deployment_success:
                print(" ❌ Failed")
                raise Exception("Failed to deploy application")
            
            print(f" ✅ Done (namespace: {experiment_config['namespace']})")
            
            experiment = MitigationExperimentRunner(
                experiment_config,
                experiment_id=experiment_id,
                agent_config=self.agent_config,
                anomaly=anomaly_instance,
            )

            experiment_result["started_at"] = datetime.now(timezone.utc).isoformat()
            experiment_start_time = time.time()
            results = await experiment.run_full_experiment()
            experiment_result["completed_at"] = datetime.now(timezone.utc).isoformat()
            experiment_result["experiment_duration_seconds"] = time.time() - experiment_start_time
            
            # Merge experiment results directly (structured dict)
            experiment_result.update(results)
            if results.get("success"):
                self.batch_results["successful_experiments"] += 1
                      
        except KeyboardInterrupt:
            # Experiment interrupted - mark it and save partial results including trace
            experiment_result["interrupted"] = True
            experiment_result["error"] = "Experiment interrupted by user (Ctrl+C)"
            experiment_result.setdefault("completed_at", datetime.now(timezone.utc).isoformat())
            if not experiment_result.get("experiment_duration_seconds"):
                experiment_result["experiment_duration_seconds"] = time.time() - experiment_start_time
            self.batch_results["failed_experiments"] += 1
            print(f"\n⚠️  Experiment {experiment_id} interrupted - saving partial results and trace")
            # Re-raise to let batch runner handle the interruption
            raise
            
        except Exception as e:
            # Update result with error info
            experiment_result["error"] = str(e)
            experiment_result.setdefault("completed_at", datetime.now(timezone.utc).isoformat())
            if not experiment_result.get("experiment_duration_seconds"):
                experiment_result["experiment_duration_seconds"] = time.time() - experiment_start_time
            self.batch_results["failed_experiments"] += 1
            print(f"❌ Experiment {experiment_id} failed: {e}")
                    
        finally:       
            # Always cleanup app to ensure isolation
            try:
                print(f"🧹 Cleanup for {experiment_id}...")
                undeploy_app_sync(experiment_config)
            except Exception as cleanup_error:
                print(f"⚠️  Cleanup warning: {cleanup_error}")

            # Save experiment log (ALWAYS, even on interrupt or failure)
            try:
                log_file = self.simple_logger.log_experiment(
                    experiment_result,
                    batch_id=self.batch_results["batch_id"],
                )
                if experiment_result.get("interrupted"):
                    print(f"💾 Partial experiment log saved (interrupted): {log_file.name}")
                    if experiment_result.get("agent_trace"):
                        print(f"   ✓ Saved {len(experiment_result['agent_trace'])} agent trace steps")
                else:
                    print(f"💾 Experiment log saved: {log_file.name}")
            except Exception as log_error:
                logger.warning(f"Failed to save experiment log: {log_error}")
            
            return experiment_result
    
    async def run_batch(self) -> Dict[str, Any]:
        """Run the complete batch of experiments."""

        # Print batch summary
        print(f"📋 Loading chaos configurations from spec (seed retained for record: {self.random_seed})")
        print(f"📊 Experiment logging initialized for batch: {self.batch_results['batch_id']}")
        print(f"💾 Logs will be saved to: {self.simple_logger.output_dir}")
        print(f"🎯 Instances execute exactly in the configured order")
        print(f"📦 Total anomalies generated: {len(self.anomalies)}")
        print(f"📊 Available nodes: {self.available_nodes_count}")
        print(f"📊 Available apps: {self.available_apps_count}")


        print(f"🤖 Agent LLM: {self.agent_config.provider}/{self.agent_config.model}")
        print(f"\n{'='*70}")
        print(f"🎯 STARTING BATCH EXPERIMENT: {self.batch_results['batch_id']}")
        print(f"{'='*70}")
        print(f"📊 Total experiments: {len(self.anomalies)}")
        print(f"⏰ Estimated duration: ~{len(self.anomalies) * 10} minutes")
        
        print(f"💾 Output directory: {self.simple_logger.output_dir}")
        print(f"{'─'*70}")
        
        try:
            for index, anomaly in enumerate(self.anomalies):
                # Create experiment config and ID
                chaos_info = anomaly.get_info()
                experiment_config = self._create_experiment_config()

                experiment_id = self._build_experiment_id(index, chaos_info)
                
                # Run the experiment
                experiment_result = await self.run_single_experiment(
                    experiment_config,
                    experiment_id, 
                    index,
                    anomaly_instance=anomaly,
                )
                
                # Store results (also attach chaos info for logging/viewing)
                experiment_result["chaos_config"] = chaos_info.copy()
                self.batch_results["experiments"].append(experiment_result)
                        
        except KeyboardInterrupt:
            self.batch_results["error"] = "Batch interrupted by user (Ctrl+C)"
            print(f"\n🛑 BATCH INTERRUPTED BY USER")
            
        except Exception as e:
            self.batch_results["error"] = str(e)
            print(f"\n❌ BATCH FAILED: {e}")
            logger.exception("Batch execution error")
        
        finally:
            # Always save batch summary (success, interrupted, or failed)
            try:
                print(f"\n{'-'*70}")
                print(f"📦 Batch summary")
                batch_summary_file = self.simple_logger.save_batch_summary(self.batch_results)
                print(f"💾 Batch summary saved: {batch_summary_file}")
                print(f"{'-'*70}")
                self.batch_results["batch_summary_saved"] = True
                self.batch_results["batch_summary_file"] = str(batch_summary_file)
            except Exception as summary_error:
                logger.warning(f"Failed to save batch summary: {summary_error}")
                self.batch_results["batch_summary_saved"] = False
            
            return self.batch_results