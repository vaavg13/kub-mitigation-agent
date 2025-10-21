import asyncio
import logging
import argparse
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# CRITICAL: Import Locust FIRST to do SSL monkey-patching before Kubernetes client
try:
    import locust  # Import Locust first to ensure proper SSL monkey-patching
except ImportError:
    pass  # If Locust not available, continue without it

# Import modules
from kub_mitigation_agent.experiment.batch_chaos_experiment import BatchChaosExperiment
from kub_mitigation_agent.experiment.chaos_batch_generator import ChaosBatchGenerator, DEFAULT_CHAOS_COUNT_PER_TYPE
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=REPO_ROOT / ".env")

START_AT_EXPERIMENT = 5

def setup_logging(log_config):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO")),
        format=log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    for lib in log_config.get("suppress_libs", []):
        logging.getLogger(lib).setLevel(logging.WARNING)

def create_batch_config(base_config, experiment_count_per_type: int = DEFAULT_CHAOS_COUNT_PER_TYPE, 
                       random_seed: int = 42):
    """Create batch configuration with generated chaos experiments."""
    batch_config = base_config.copy()
    generator = ChaosBatchGenerator(base_config, seed=random_seed)
    chaos_configs = generator.generate_comprehensive_batch(experiment_count_per_type)
    batch_config["chaos_configurations"] = chaos_configs
    return batch_config

def load_yaml_config(config_path: Path):
    """Load YAML file and return (BATCH_CONFIG, BATCH_ALERT_CONFIG, LOGGING_CONFIG)."""
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    batch_cfg = cfg.get("BATCH_CONFIG") or cfg.get("batch_config") or {}
    alert_cfg = cfg.get("BATCH_ALERT_CONFIG") or cfg.get("batch_alert_config") or {}
    logging_cfg = cfg.get("LOGGING_CONFIG") or cfg.get("logging_config") or {}
    return batch_cfg, alert_cfg, logging_cfg

async def main():
    """Main async function to run batch chaos experiments."""
    print("🎯 Batch Chaos Experiment Runner")
    print("=" * 50)
    
    # Parse args
    parser = argparse.ArgumentParser(description="Batch Chaos Experiment Runner")
    repo_root = Path(__file__).resolve().parent.parent
    default_cfg = repo_root / "experiment_configs" / "batch_config_iot_gateway_app.yaml"
    parser.add_argument("--config", "-c", type=str, default=str(default_cfg), help="Path to YAML batch config")
    args = parser.parse_args()

    # Load YAML config
    batch_cfg_loaded, alert_cfg_loaded, logging_cfg_loaded = load_yaml_config(Path(args.config))

    # Setup logging
    setup_logging(logging_cfg_loaded)

    start_at_experiment = START_AT_EXPERIMENT
    
    # Configuration from BATCH_CONFIG
    batch_settings = batch_cfg_loaded.get("batch_settings", {})
    experiment_count_per_type = batch_settings.get("experiments_count_per_type", 2)
    random_seed = batch_settings.get("random_seed", 42)
    dataset_output_dir = "DATASET_LOGS"  # Directory for comprehensive dataset logs
    
    print(f"Configuration: {experiment_count_per_type} experiments per type, seed={random_seed}")
    
    # Create batch configuration
    batch_config = create_batch_config(batch_cfg_loaded, experiment_count_per_type, random_seed)
    
    # --- Slicing for Resuming ---
    all_chaos_configs = batch_config.get("chaos_configurations", [])
    total_experiments = len(all_chaos_configs)
    
    print(f"Generated {total_experiments} chaos experiments in total.")

    if start_at_experiment > 1:
        start_index = start_at_experiment - 1
        if start_index < total_experiments:
            print(f"▶️ Resuming from experiment {start_at_experiment}...")
            batch_config["chaos_configurations"] = all_chaos_configs[start_index:]
        else:
            print(f"⚠️ Start number {start_at_experiment} is beyond the total number of experiments ({total_experiments}). Nothing to run.")
            batch_config["chaos_configurations"] = []
    
    experiments_to_run = batch_config.get("chaos_configurations", [])
    if not experiments_to_run:
        print("No experiments to run. Exiting.")
        return 0
        
    print(f"Executing {len(experiments_to_run)} experiments:")
    for i, config in enumerate(experiments_to_run, start_at_experiment):
        print(f"  {i:2d}. {config['mode']} - {config['fault_type']} ({config.get('intensity', 'default')})")
    
    # Create batch experiment with dataset logging
    print(f"\nInitializing batch experiment...")
    batch_experiment = BatchChaosExperiment(batch_config, output_base_dir=dataset_output_dir)
    
    # Use the batch-specific alert configuration
    alert_config = alert_cfg_loaded
    
    # Run the batch experiment
    print(f"Starting batch execution...")
    results = await batch_experiment.run_batch(alert_config)
    
    # Print final summary
    print(f"\n" + "=" * 60)
    print(f"🏁 BATCH EXECUTION COMPLETE")
    print(f"=" * 60)
    
    if results.get("error"):
        print(f"❌ Batch failed: {results['error']}")
        return 1
    else:
        success_rate = (results['successful_experiments'] / results['total_experiments']) * 100
        print(f"✅ Batch completed successfully")
        print(f"📊 Success rate: {success_rate:.1f}% ({results['successful_experiments']}/{results['total_experiments']})")
        
        # Dataset logging summary
        if results.get("batch_summary_saved", False):
            print(f"💾 Complete dataset saved to: {dataset_output_dir}")
        
        return 0

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n🛑 Batch execution interrupted by user")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"\n❌ Batch execution failed with error: {e}")
        logging.exception("Batch execution error")
        sys.exit(1) 