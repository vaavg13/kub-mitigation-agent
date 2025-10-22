#!/usr/bin/env python3
"""
Batch Chaos Experiment Orchestrator
Runs multiple chaos experiments with complete isolation between each experiment.
"""

import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, Any
from .chaos_mitigation_experiment import ChaosAndMitigationExperiment
from .experiment_utils import deploy_fresh_app_sync, undeploy_app_sync, reset_scheduling_policies
from .simple_experiment_logger import SimpleExperimentLogger
from .chaos_batch_generator import ChaosBatchGenerator, DEFAULT_CHAOS_COUNT_PER_TYPE, DEFAULT_SEED
from ..anomalies.docker_constraints_handler import DockerConstraintsHandler
from ..agent.config import KubernetesAgentConfig

logger = logging.getLogger(__name__)

class BatchChaosExperiment:
    """Orchestrates multiple chaos experiments with complete isolation."""
    
    def __init__(self, batch_config: Dict[str, Any], output_base_dir: str = "DATA", agent_config: KubernetesAgentConfig = None):
        """
        Initialize batch experiment.
        
        Args:
            batch_config: Complete batch configuration (required)
            output_base_dir: Base directory for dataset logs
            agent_config: Agent configuration for all experiments (required)
        """
        # Validate required configurations
        assert batch_config is not None, "batch_config is required - cannot run batch experiments without configuration"
        assert agent_config is not None, "agent_config is required - cannot run experiments without agent configuration"
        
        self.batch_config = batch_config
        self.batch_settings = batch_config.get("batch_settings", {})
        self.output_base_dir = output_base_dir
        self.agent_config = agent_config
        
        # Generate chaos configurations internally using ChaosBatchGenerator
        experiment_count_per_type = self.batch_settings.get("experiments_count_per_type", DEFAULT_CHAOS_COUNT_PER_TYPE)
        random_seed = self.batch_settings.get("random_seed", DEFAULT_SEED)
        
        print(f"🎲 Generating chaos configurations (seed: {random_seed}, {experiment_count_per_type} per type)")
        generator = ChaosBatchGenerator(batch_config, seed=random_seed)
        self.chaos_configs = generator.generate_comprehensive_batch(experiment_count_per_type)
        
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
        self.chaos_mesh_handler = None
    
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
    
    async def run_single_experiment(
        self, 
        experiment_config: Dict[str, Any],
        experiment_id: str,
        index: int
    ) -> Dict[str, Any]:
        """Run a single isolated experiment with complete deployment cycle."""
        print(f"\n{'='*70}")
        print(f"🧪 EXPERIMENT {index + 1}/{len(self.chaos_configs)}: {experiment_id}")
        print(f"   Mode: {experiment_config['chaos_config']['mode']} | Type: {experiment_config['chaos_config']['fault_type']} | Intensity: {experiment_config['chaos_config']['intensity']}")
        print(f"{'='*70}")
        
        # Track experiment execution time
        experiment_start_time = time.time()
        
        # Initialize result structure with defaults
        experiment_result = {
            "experiment_id": experiment_id,
            "index": index + 1,
            "chaos_config": experiment_config["chaos_config"].copy(),
            "namespace": experiment_config["namespace"],
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "experiment_duration_seconds": 0,
            "success": False,
            "error": None,
            "agent_actions": [],
            "recovery_successful": False,
            "recovery_reason": "",
            "phase_metrics": {},
            "agent_success": False,
            "agent_execution_duration_seconds": 0,
            "operational_summary": None,
            "location_evaluation": None
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
            
            # Step 2: Run the chaos experiment
            print(f"\n▶ Step 2: Running chaos experiment")
            print(f"  ├─ Chaos injection type: {experiment_config['chaos_config']['mode']} - {experiment_config['chaos_config']['fault_type']}")
            experiment = ChaosAndMitigationExperiment(
                experiment_config,
                experiment_id=experiment_id,
                agent_config=self.agent_config
            )
            
            results = await experiment.run_full_experiment()
            
            # Update experiment result with data from experiment
            experiment_result["success"] = results.get("success", False)
            experiment_result["recovery_successful"] = results.get("recovery_successful", False)
            experiment_result["recovery_reason"] = results.get("recovery_reason", "")
            experiment_result["agent_actions"] = results.get("agent_actions", [])
            experiment_result["phase_metrics"] = results.get("phase_metrics", {})
            experiment_result["agent_success"] = results.get("agent_success", False)
            experiment_result["agent_execution_duration_seconds"] = results.get("agent_execution_duration_seconds", 0)
            experiment_result["operational_summary"] = results.get("operational_summary")
            experiment_result["location_evaluation"] = results.get("location_evaluation")
            
            # Update batch statistics
            if results.get("success"):
                print(f"✅ Experiment {experiment_id} completed successfully")
                self.batch_results["successful_experiments"] += 1
            else:
                print(f"❌ Experiment {experiment_id} failed")
                self.batch_results["failed_experiments"] += 1
            
        except Exception as e:
            # Update result with error info
            experiment_result["error"] = str(e)
            experiment_result["recovery_reason"] = "Exception during execution"
            print(f"❌ Experiment {experiment_id} failed: {e}")
            self.batch_results["failed_experiments"] += 1
            
            # Cleanup after failure
            try:
                print(f"🧹 Cleanup after failure for {experiment_id}...")
                undeploy_app_sync(experiment_config)
            except Exception as cleanup_error:
                print(f"⚠️  Cleanup warning: {cleanup_error}")
        
        finally:
            # Calculate experiment execution time
            experiment_result["completed_at"] = datetime.now().isoformat()
            experiment_result["experiment_duration_seconds"] = time.time() - experiment_start_time
            
            try:
                log_file = self.simple_logger.log_experiment(
                    experiment_id=experiment_id,
                    batch_id=self.batch_results["batch_id"],
                    experiment_index=index + 1,
                    namespace=experiment_result["namespace"],
                    chaos_config=experiment_config["chaos_config"],
                    started_at=experiment_result["started_at"],
                    completed_at=experiment_result["completed_at"],
                    duration_seconds=experiment_result["experiment_duration_seconds"],
                    phase_metrics=experiment_result["phase_metrics"],
                    agent_actions=experiment_result["agent_actions"],
                    agent_success=experiment_result["agent_success"],
                    agent_duration_seconds=experiment_result["agent_execution_duration_seconds"],
                    operational_summary=experiment_result["operational_summary"],
                    location_evaluation=experiment_result["location_evaluation"],
                    experiment_success=experiment_result["success"],
                    recovery_successful=experiment_result["recovery_successful"],
                    recovery_reason=experiment_result["recovery_reason"],
                    error=experiment_result["error"]
                )
                print(f"💾 Experiment log saved: {log_file.name}")
            except Exception as log_error:
                logger.warning(f"Failed to save experiment log: {log_error}")
            
            return experiment_result
    
    async def run_batch(self) -> Dict[str, Any]:
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
        initial_reset_success = reset_scheduling_policies(self.docker_handler)
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
                    experiment_id, 
                    index
                )
                
                # Store results
                self.batch_results["experiments"].append(experiment_result)
                
                # Reset scheduling policies after each experiment (cleanup step)
                print(f"\n▶ Post-experiment cleanup: ", end="")
                reset_success = reset_scheduling_policies(self.docker_handler)
                if not reset_success:
                    print(f"  ⚠️  Some issues during reset, continuing...")
                
                # Delay between experiments (if not the last one)
                if index < len(self.chaos_configs) - 1:
                    delay = self.batch_settings.get("delay_between_experiments", 30)
                    if delay > 0:
                        print(f"⏸️  Waiting {delay}s before next experiment...")
                        await asyncio.sleep(delay)
            
            # Mark batch as completed
            self.batch_results["completed_at"] = datetime.now().isoformat()
            
        except KeyboardInterrupt:
            self.batch_results["completed_at"] = datetime.now().isoformat()
            self.batch_results["error"] = "Batch interrupted by user (Ctrl+C)"
            print(f"\n🛑 BATCH INTERRUPTED BY USER")
            
        except Exception as e:
            self.batch_results["completed_at"] = datetime.now().isoformat()
            self.batch_results["error"] = str(e)
            print(f"\n❌ BATCH FAILED: {e}")
            logger.exception("Batch execution error")
        
        finally:
            # Always save batch summary (success, interrupted, or failed)
            try:
                batch_summary_file = self.simple_logger.save_batch_summary(self.batch_results)
                print(f"\n💾 Batch summary saved: {batch_summary_file}")
                self.batch_results["batch_summary_saved"] = True
                self.batch_results["batch_summary_file"] = str(batch_summary_file)
            except Exception as summary_error:
                logger.warning(f"Failed to save batch summary: {summary_error}")
                self.batch_results["batch_summary_saved"] = False
            
            return self.batch_results