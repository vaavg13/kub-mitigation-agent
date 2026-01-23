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
import json

# Update import to new location
from kub_mitigation_agent.experiment.runners.batch import BatchExperimentRunner
from kub_mitigation_agent.agent.config import KubernetesAgentConfig
from kub_mitigation_agent.logging_config import setup_logging
from kub_mitigation_agent.paths import (
    HOTEL_RESERVATION_METADATA,
    HOTEL_RESERVATION_EXPERIMENTS,
    EXPERIMENT_SETTINGS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=REPO_ROOT / ".env")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Batch Chaos Experiment Runner")
    parser.add_argument(
        "--metadata", "-m",
        type=Path,
        default=HOTEL_RESERVATION_METADATA,
        help="Path to app metadata JSON"
    )
    parser.add_argument(
        "--experiments", "-e",
        type=Path,
        default=HOTEL_RESERVATION_EXPERIMENTS,
        help="Path to chaos experiments YAML"
    )
    parser.add_argument(
        "--settings", "-s",
        type=Path,
        default=EXPERIMENT_SETTINGS,
        help="Path to experiment settings YAML"
    )

    return parser.parse_args()


def load_configs(metadata_path: Path, experiments_path: Path, settings_path: Path):
    """Load batch and agent configurations."""
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    workload = metadata.get("Workload", {})
    experiment_defaults = metadata.get("Experiment", {})

    if not experiments_path.exists():
        raise FileNotFoundError(f"Chaos experiments file not found: {experiments_path}")

    chaos_spec = yaml.safe_load(experiments_path.read_text(encoding="utf-8")) or {}
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}

    batch_config = {
        "namespace": metadata.get("Namespace", "default"),
        "available_deployments": metadata.get("Critical Services", []),
        "traffic_config": {
            "workload_pattern": workload.get("profile", "simple"),
            "host": workload.get("host", "http://localhost:8080"),
            "num_users": workload.get("default_users", 10),
            "spawn_rate": workload.get("spawn_rate", 2),
            "wait_time_min": workload.get("wait_time_min", 1),
            "wait_time_max": workload.get("wait_time_max", 3),
        },
        "test_settings": experiment_defaults.get("test_settings", {"deploy_fresh_app": True}),
        "warmup_duration": experiment_defaults.get("warmup_duration", 0),
        "baseline_duration": experiment_defaults.get("baseline_duration", 30),
        "chaos_warmup_duration": experiment_defaults.get("chaos_warmup_duration", 30),
        "recovery_duration": experiment_defaults.get("recovery_duration", 30),
        "batch_settings": experiment_defaults.get("batch_settings", {"random_seed": 420}),
        "chaosd": experiment_defaults.get(
            "chaosd",
            {"port": settings.get("chaosd_port", 31767)}
        ),
        "nodes": settings.get("nodes", {}),
        "prometheus_url": settings.get("prometheus_url", "http://localhost:9090"),
        "istio_ingress_workload": settings.get("istio_ingress_workload", "istio-ingress"),
        "istio_ingress_namespace": settings.get("istio_ingress_namespace", "istio-system"),
        "chaos_experiments": chaos_spec.get("chaos_experiments", {}),
    }
    
    agent_config_path = REPO_ROOT / "kub_mitigation_agent" / "agent" / "configs" / "agent.config.yaml"
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
    batch_config, agent_config = load_configs(args.metadata, args.experiments, args.settings)
    
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
