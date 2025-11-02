import asyncio
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv
import yaml

try:
    import locust
except ImportError:
    pass

from kub_mitigation_agent.experiment.experiment_batch_runner import BatchExperimentRunner
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
        default=REPO_ROOT / "experiment_configs" / "batch_config_iot_gateway_app.yaml",
        help="Path to YAML batch config"
    )
    parser.add_argument(
        "--resume-from",
        type=int,
        default=None,
        help="Resume batch from specified experiment number (1-indexed, e.g., 5 to start from experiment 5)"
    )
    return parser.parse_args()


def load_configs(batch_config_path: Path):
    """Load batch and agent configurations."""
    batch_config = yaml.safe_load(batch_config_path.read_text(encoding="utf-8"))
    batch_config = batch_config.get("BATCH_CONFIG") or batch_config.get("batch_config") or {}
    
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
        agent_config=agent_config,
        resume_from=args.resume_from
    )
    
    results = await batch_experiment.run_batch()
    
    if results.get("error"):
        print(f"\n❌ Batch failed: {results['error']}")
        return 1
    
    success_rate = (results['successful_experiments'] / results['total_experiments']) * 100
    print(f"\n✅ Batch complete: {success_rate:.1f}% success ({results['successful_experiments']}/{results['total_experiments']})")
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
        sys.exit(1) 