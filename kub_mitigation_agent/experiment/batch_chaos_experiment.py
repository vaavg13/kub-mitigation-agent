#!/usr/bin/env python3
"""
Batch Chaos Experiment Orchestrator
Runs multiple chaos experiments with complete isolation between each experiment.
"""

import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, Any, List
from .chaos_mitigation_experiment import ChaosAndMitigationExperiment
from .experiment_utils import deploy_fresh_app_sync, undeploy_app_sync
from .simple_experiment_logger import SimpleExperimentLogger
from ..anomalies.docker_constraints_handler import DockerConstraintsHandler
from ..anomalies.chaos_mesh_handler import ChaosMeshHandler

logger = logging.getLogger(__name__)

class BatchChaosExperiment:
    """Orchestrates multiple chaos experiments with complete isolation."""
    
    def __init__(self, batch_config: Dict[str, Any], output_base_dir: str = "DATA"):
        """
        Initialize batch experiment.
        
        Args:
            batch_config: Complete batch configuration from batch_config.py
            output_base_dir: Base directory for dataset logs
        """
        self.batch_config = batch_config
        self.chaos_configs = batch_config.get("chaos_configurations", [])
        self.batch_settings = batch_config.get("batch_settings", {})
        self.output_base_dir = output_base_dir
        
        # Extract namespace/application name from config
        namespace = self.batch_config.get("namespace", "unknown-app")
        
        # Results storage with enhanced batch ID including date and namespace
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.batch_results = {
            "batch_id": f"batch_{timestamp}_{namespace}",
            "started_at": datetime.now().isoformat(),
            "total_experiments": len(self.chaos_configs),
            "successful_experiments": 0,
            "failed_experiments": 0,
            "experiments": []
        }
        
        # Initialize simple logger
        self.simple_logger = SimpleExperimentLogger(self.output_base_dir, self.batch_results["batch_id"])
        print(f"📊 Experiment logging initialized for batch: {self.batch_results['batch_id']}")
        print(f"💾 Logs will be saved to: {self.simple_logger.output_dir}")
        
        # Initialize handlers with base config
        self.docker_handler = DockerConstraintsHandler(self.batch_config)
        self.chaos_mesh_handler = None  # Keep this lazy since it's rarely used directly
    
    def _create_experiment_config(self, chaos_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create complete experiment config by adding chaos config to batch config."""
        experiment_config = self.batch_config.copy()
        experiment_config["chaos_config"] = chaos_config
        return experiment_config
    
    def _create_experiment_id(self, index: int, chaos_config: Dict[str, Any]) -> str:
        """Create unique experiment ID."""
        mode = chaos_config.get("mode", "unknown")
        fault_type = chaos_config.get("fault_type", "unknown")
        return f"exp_{index+1:03d}_{mode}_{fault_type}"
    
    def reset_scheduling_policies(self) -> bool:
        """Reset all scheduling policies and node constraints to clean state between experiments."""
        print(f"🔄 Resetting scheduling policies...", end="")
        
        try:
            # 1. Reset Docker node constraints to proper specifications
            docker_reset_success = self.docker_handler.reset_all_node_docker_constraints()
            
            # 2. Clean up any remaining Chaos Mesh experiments
            chaos_cleanup_success = True
            try:
                # Direct kubectl cleanup without needing ChaosMeshHandler
                cleanup_cmd = "kubectl delete stresschaos,podchaos,networkchaos --all --all-namespaces --ignore-not-found=true"
                import subprocess
                result = subprocess.run(cleanup_cmd.split(), capture_output=True, text=True, timeout=30)
                if result.returncode != 0:
                    chaos_cleanup_success = False
            except Exception as e:
                chaos_cleanup_success = False
            
            overall_success = docker_reset_success and chaos_cleanup_success
            
            if overall_success:
                print(" ✅ Done")
            else:
                print(" ⚠️  Some issues occurred")
                
            return overall_success
            
        except Exception as e:
            print(f" ❌ Error: {e}")
            return False
    
    async def run_single_experiment(self, 
                                  experiment_config: Dict[str, Any], 
                                  alert_config: Dict[str, Any],
                                  experiment_id: str,
                                  index: int) -> Dict[str, Any]:
        """Run a single isolated experiment with complete deployment cycle."""
        print(f"\n{'='*70}")
        print(f"🧪 EXPERIMENT {index + 1}/{len(self.chaos_configs)}: {experiment_id}")
        print(f"   Mode: {experiment_config['chaos_config']['mode']} | Type: {experiment_config['chaos_config']['fault_type']} | Intensity: {experiment_config['chaos_config']['intensity']}")
        print(f"{'='*70}")
        
        # Start logging this experiment
        self.simple_logger.start_experiment(
            experiment_id=experiment_id,
            batch_id=self.batch_results["batch_id"],
            experiment_index=index + 1,
            chaos_config=experiment_config["chaos_config"],
            namespace=experiment_config["namespace"]
        )
        
        experiment_result = {
            "experiment_id": experiment_id,
            "index": index + 1,
            "chaos_config": experiment_config["chaos_config"].copy(),
            "started_at": datetime.now().isoformat(),
            "success": False,
            "error": None,
            "results": None,
            "completed_at": None,
            "dataset_record_saved": False
        }
        
        try:
            # Step 1: Deploy fresh application
            print(f"\n▶ Step 1: Deploying fresh application...", end="")
            deployment_success, namespace = deploy_fresh_app_sync(experiment_config)
            
            if not deployment_success:
                print(" ❌ Failed")
                raise Exception("Failed to deploy application")
            
            print(f" ✅ Done (namespace: {namespace})")
            experiment_result["namespace"] = namespace
            
            # Step 2: Run the chaos experiment with logging
            print(f"\n▶ Step 2: Running chaos experiment")
            print(f"  ├─ Chaos injection type: {experiment_config['chaos_config']['mode']} - {experiment_config['chaos_config']['fault_type']}")
            experiment = ChaosAndMitigationExperiment(
                experiment_config, 
                alert_config,
                simple_logger=self.simple_logger
            )
            
            # Run the experiment with already deployed app
            results = await experiment.run_full_experiment(
                deployment_already_done=True,
                deployment_namespace=namespace
            )
            
            experiment_result["results"] = results
            experiment_result["success"] = results.get("success", False)
            
            # Extract key metrics from results
            if results.get("dataset_logged", False):
                experiment_result["agent_actions"] = results.get("agent_actions", [])
                experiment_result["recovery_successful"] = results.get("recovery_successful", False)
                experiment_result["recovery_reason"] = results.get("recovery_reason", "")
                experiment_result["operational_summary"] = results.get("operational_summary", {})
                experiment_result["problem_location"] = results.get("problem_location", {})
            
            experiment_result["completed_at"] = datetime.now().isoformat()
            
            # Save the experiment log
            try:
                saved_file = self.simple_logger.complete_experiment(
                    success=experiment_result["success"],
                    recovery_successful=results.get("recovery_successful", False),
                    recovery_reason=results.get("recovery_reason", ""),
                    error=None
                )
                experiment_result["dataset_record_saved"] = True
                experiment_result["dataset_file"] = str(saved_file)
                print(f"\n💾 Experiment log saved: {saved_file.name}")
            except Exception as save_error:
                logger.warning(f"Failed to save experiment log: {save_error}")
                experiment_result["dataset_record_saved"] = False
            
            if experiment_result["success"]:
                print(f"✅ Experiment {experiment_id} completed successfully")
                self.batch_results["successful_experiments"] += 1
            else:
                print(f"❌ Experiment {experiment_id} failed")
                self.batch_results["failed_experiments"] += 1
            
            return experiment_result
            
        except KeyboardInterrupt:
            experiment_result["error"] = "Interrupted by user (Ctrl+C)"
            experiment_result["completed_at"] = datetime.now().isoformat()
            print(f"\n🛑 Experiment {experiment_id} interrupted by user")
            
            # Save interrupted experiment log
            try:
                saved_file = self.simple_logger.complete_experiment(
                    success=False,
                    recovery_successful=False,
                    recovery_reason="Interrupted",
                    error=experiment_result["error"]
                )
                experiment_result["dataset_record_saved"] = True
                experiment_result["dataset_file"] = str(saved_file)
            except Exception as save_error:
                logger.warning(f"Failed to save interrupted experiment log: {save_error}")
            
            # Emergency cleanup
            try:
                print(f"🧹 Emergency cleanup for {experiment_id}...")
                undeploy_app_sync(experiment_config)
            except Exception as cleanup_error:
                print(f"⚠️  Emergency cleanup warning: {cleanup_error}")
            
            raise  # Re-raise to stop batch
            
        except Exception as e:
            experiment_result["error"] = str(e)
            experiment_result["completed_at"] = datetime.now().isoformat()
            print(f"❌ Experiment {experiment_id} failed: {e}")
            self.batch_results["failed_experiments"] += 1
            
            # Save failed experiment log
            try:
                saved_file = self.simple_logger.complete_experiment(
                    success=False,
                    recovery_successful=False,
                    recovery_reason="Failed",
                    error=experiment_result["error"]
                )
                experiment_result["dataset_record_saved"] = True
                experiment_result["dataset_file"] = str(saved_file)
            except Exception as save_error:
                logger.warning(f"Failed to save failed experiment log: {save_error}")
            
            # Cleanup after failure
            try:
                print(f"🧹 Cleanup after failure for {experiment_id}...")
                undeploy_app_sync(experiment_config)
            except Exception as cleanup_error:
                print(f"⚠️  Cleanup warning: {cleanup_error}")
            
            return experiment_result
    
    async def run_batch(self, alert_config: Dict[str, Any]) -> Dict[str, Any]:
        """Run the complete batch of experiments."""
        print(f"\n{'='*70}")
        print(f"🎯 STARTING BATCH EXPERIMENT: {self.batch_results['batch_id']}")
        print(f"{'='*70}")
        print(f"📊 Total experiments: {len(self.chaos_configs)}")
        print(f"⏰ Estimated duration: ~{len(self.chaos_configs) * 10} minutes")
        print(f"💾 Output directory: {self.simple_logger.output_dir}")
        print(f"{'─'*70}")
        
        # Initial policy reset before starting batch
        print(f"\n▶ Initial setup: ", end="")
        initial_reset_success = self.reset_scheduling_policies()
        if not initial_reset_success:
            print(f"  ⚠️  Some issues during initial setup, continuing...")
        
        try:
            for index, chaos_config in enumerate(self.chaos_configs):
                # Create experiment config and ID
                experiment_config = self._create_experiment_config(chaos_config)
                experiment_id = self._create_experiment_id(index, chaos_config)
                
                # Run the experiment
                experiment_result = await self.run_single_experiment(
                    experiment_config, 
                    alert_config, 
                    experiment_id, 
                    index
                )
                
                # Store results
                self.batch_results["experiments"].append(experiment_result)
                
                # Reset scheduling policies between experiments (if not the last one)
                if index < len(self.chaos_configs) - 1:
                    print(f"\n▶ Between-experiment reset: ", end="")
                    reset_success = self.reset_scheduling_policies()
                    if not reset_success:
                        print(f"  ⚠️  Some issues during reset, continuing...")
                    
                    # Delay between experiments (if specified)
                    delay = self.batch_settings.get("delay_between_experiments", 30)
                    if delay > 0:
                        print(f"⏸️  Waiting {delay}s before next experiment...")
                        await asyncio.sleep(delay)
            
            # Mark batch as completed
            self.batch_results["completed_at"] = datetime.now().isoformat()
            
            # Save batch summary with dataset statistics
            try:
                batch_summary_file = self.simple_logger.save_batch_summary(self.batch_results)
                print(f"\n💾 Batch summary saved: {batch_summary_file}")
                self.batch_results["batch_summary_saved"] = True
                self.batch_results["batch_summary_file"] = str(batch_summary_file)
            except Exception as summary_error:
                logger.warning(f"Failed to save batch summary: {summary_error}")
                self.batch_results["batch_summary_saved"] = False
            
            # Print batch summary
            self._print_batch_summary()
            
            return self.batch_results
            
        except KeyboardInterrupt:
            self.batch_results["completed_at"] = datetime.now().isoformat()
            self.batch_results["error"] = "Batch interrupted by user (Ctrl+C)"
            print(f"\n🛑 BATCH INTERRUPTED BY USER")
            
            # Try to save what we have
            try:
                batch_summary_file = self.simple_logger.save_batch_summary(self.batch_results)
                print(f"💾 Partial batch summary saved: {batch_summary_file}")
            except Exception as summary_error:
                logger.warning(f"Failed to save interrupted batch summary: {summary_error}")
            
            self._print_batch_summary()
            return self.batch_results
            
        except Exception as e:
            self.batch_results["completed_at"] = datetime.now().isoformat()
            self.batch_results["error"] = str(e)
            print(f"\n❌ BATCH FAILED: {e}")
            logger.exception("Batch execution error")
            
            # Try to save what we have
            try:
                batch_summary_file = self.simple_logger.save_batch_summary(self.batch_results)
                print(f"💾 Error batch summary saved: {batch_summary_file}")
            except Exception as summary_error:
                logger.warning(f"Failed to save error batch summary: {summary_error}")
            
            self._print_batch_summary()
            return self.batch_results
    
    def _print_batch_summary(self):
        """Print final batch summary."""
        print(f"\n{'='*70}")
        print(f"📊 BATCH EXPERIMENT SUMMARY")
        print(f"{'='*70}")
        print(f"Batch ID: {self.batch_results['batch_id']}")
        print(f"Duration: {self.batch_results['started_at']} → {self.batch_results.get('completed_at', 'Not completed')}")
        print(f"\nResults:")
        print(f"  ✅ Successful: {self.batch_results['successful_experiments']}/{self.batch_results['total_experiments']}")
        print(f"  ❌ Failed: {self.batch_results['failed_experiments']}/{self.batch_results['total_experiments']}")
        
        if self.batch_results.get("error"):
            print(f"  🚨 Batch Error: {self.batch_results['error']}")
        
        # Dataset statistics
        dataset_saved_count = sum(1 for exp in self.batch_results["experiments"] if exp.get("dataset_record_saved", False))
        agent_actions_total = sum(len(exp.get("agent_actions", [])) for exp in self.batch_results["experiments"])
        recovery_successful_count = sum(1 for exp in self.batch_results["experiments"] if exp.get("recovery_successful", False))
        
        print(f"\nDataset Statistics:")
        print(f"  📁 Output directory: {self.simple_logger.output_dir}")
        print(f"  💾 Logs saved: {dataset_saved_count}/{len(self.batch_results['experiments'])}")
        print(f"  🤖 Total agent actions: {agent_actions_total}")
        print(f"  🩹 Recovery successful: {recovery_successful_count}/{len(self.batch_results['experiments'])}")
        
        print(f"\n{'─'*70}")
        print(f"EXPERIMENT DETAILS:")
        print(f"{'─'*70}")
        
        for exp in self.batch_results["experiments"]:
            status = "✅" if exp["success"] else "❌"
            chaos_mode = exp['chaos_config']['mode']
            chaos_type = exp['chaos_config']['fault_type']
            dataset_status = "💾" if exp.get("dataset_record_saved", False) else "⚠️"
            agent_actions = len(exp.get("agent_actions", []))
            
            print(f"{status} {dataset_status} {exp['experiment_id']}")
            print(f"    Chaos: {chaos_mode} - {chaos_type} | Actions: {agent_actions}")
            if exp.get("error"):
                print(f"    Error: {exp['error']}")
        
        print(f"{'='*70}") 