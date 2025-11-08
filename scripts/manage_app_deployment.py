import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from kub_mitigation_agent.clients.mcp_client import kubectl_ready
from kub_mitigation_agent.experiment.experiment_k8s_ops import (
    deploy_fresh_app_sync,
    undeploy_app_sync,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=REPO_ROOT / ".env")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Deploy or undeploy an application defined in a batch config",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=REPO_ROOT / "experiment_configs" / "batch_config_iot_gateway_app.yaml",
        help="Path to the batch configuration YAML file",
    )
    parser.add_argument(
        "--action",
        "-a",
        choices=["deploy", "undeploy"],
        default="deploy",
        help="Action to perform",
    )

    return parser.parse_args()


def load_batch_config(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw_config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    batch_config = raw_config.get("BATCH_CONFIG", raw_config.get("batch_config"))

    if not batch_config:
        raise ValueError("batch_config missing from YAML file")

    app_dir = batch_config.get("app_directory")
    if not app_dir:
        raise ValueError("app_directory missing in batch configuration")

    # Normalize paths relative to repository root
    batch_config["app_directory"] = str((REPO_ROOT / Path(app_dir)).resolve())

    test_settings = batch_config.setdefault("test_settings", {})
    test_settings.setdefault("deploy_fresh_app", True)

    return batch_config


def main():
    args = parse_args()
    config_path = args.config if args.config.is_absolute() else (REPO_ROOT / args.config).resolve()

    try:
        batch_config = load_batch_config(config_path)
    except Exception as exc:
        print(f"❌ Failed to load configuration: {exc}")
        return 1

    if not kubectl_ready():
        print("❌ kubectl is not reachable. Check your kubeconfig and cluster access.")
        return 1

    namespace = batch_config.get("namespace", "unknown-namespace")

    if args.action == "deploy":
        print(f"▶ Deploying application for namespace '{namespace}'")
        success, _ = deploy_fresh_app_sync(batch_config)
        return 0 if success else 1

    print(f"🧹 Undeploying application for namespace '{namespace}'")
    success = undeploy_app_sync(batch_config)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())





