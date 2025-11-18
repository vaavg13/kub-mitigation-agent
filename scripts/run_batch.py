# Standard library imports first, BUT...
# We need to monkey patch immediately if we are using gevent/locust
import gevent.monkey
gevent.monkey.patch_all()

import asyncio
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv
import yaml

# Update import to new location
from kub_mitigation_agent.experiment.runners.batch import BatchExperimentRunner
from kub_mitigation_agent.agent.config import KubernetesAgentConfig
from kub_mitigation_agent.logging_config import setup_logging

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=REPO_ROOT / ".env")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Batch Chaos Experiment Runner")
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=REPO_ROOT / "experiment_configs" / "batch_config_smart_city_app.yaml",
        help="Path to YAML batch config"
    )

    return parser.parse_args()


def load_configs(batch_config_path: Path):
    """Load batch and agent configurations."""
    batch_config = yaml.safe_load(batch_config_path.read_text(encoding="utf-8"))
    batch_config = batch_config.get("BATCH_CONFIG", batch_config.get("batch_config", {}))
    
    # Load chaos experiments from external file if specified
    chaos_experiments_file = batch_config.get("batch_settings", {}).get("chaos_experiments_file")
    if chaos_experiments_file:
        chaos_exp_path = REPO_ROOT / chaos_experiments_file
        if chaos_exp_path.exists():
            chaos_spec = yaml.safe_load(chaos_exp_path.read_text(encoding="utf-8"))
            batch_config["chaos_experiments"] = chaos_spec.get("chaos_experiments", {})
            print(f"📋 Loaded chaos experiments spec from: {chaos_experiments_file}")
        else:
            raise FileNotFoundError(f"Chaos experiments file not found: {chaos_exp_path}")
    
    agent_config_path = REPO_ROOT / "experiment_configs" / "agent.config.yaml"
    if agent_config_path.exists():
        agent_cfg = yaml.safe_load(agent_config_path.read_text(encoding="utf-8"))
        agent_config = KubernetesAgentConfig.from_yaml_dict(agent_cfg)
    else:
        agent_config = KubernetesAgentConfig()
    
    return batch_config, agent_config


async def main():
    """Run batch chaos experiments."""
    setup_logging()
    args = parse_arguments()
    batch_config, agent_config = load_configs(args.config)
    
    batch_experiment = BatchExperimentRunner(
        batch_config,
        output_base_dir="DATASET_LOGS",
        agent_config=agent_config
    )
    
    await batch_experiment.run_batch()

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n🛑 Batch execution interrupted by user")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"\n❌ Batch execution failed with error: {e}")
        sys.exit(1)
