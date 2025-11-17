#!/usr/bin/env python3
"""
Ad-hoc test runner for anomaly handlers.

Runs each anomaly type for a fixed duration and then stops it.
Targets the currently running app/namespace as specified by the batch config.
"""

import argparse
import random
import time
from pathlib import Path
from typing import Dict, Any, List

import yaml

from kub_mitigation_agent.anomalies import (
    NodeAnomalyHandler,
    PodAnomalyHandler,
)


def load_batch_config(path: Path) -> Dict[str, Any]:
    with path.open("r") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "BATCH_CONFIG" not in data:
        raise ValueError("Invalid batch config file; expected top-level BATCH_CONFIG")
    return data["BATCH_CONFIG"]


def build_anomalies(batch_cfg: Dict[str, Any]) -> List:
    namespace = batch_cfg.get("namespace", "default")
    apps: List[str] = batch_cfg.get("available_deployments", [])
    if not apps:
        raise ValueError("available_deployments is empty in batch config")
    app = random.choice(apps)

    # Node targets
    chaosd_cfg = batch_cfg.get("chaosd", {})
    chaosd_port = int(chaosd_cfg.get("port", 31767))
    nodes: Dict[str, str] = batch_cfg.get("nodes", {})
    if not nodes:
        raise ValueError("nodes mapping is empty in batch config")
    node_name, node_host = random.choice(list(nodes.items()))

    anomalies: List = []

    # Pod-level: cpu_stress
    anomalies.append(
        PodAnomalyHandler(
            namespace=namespace,
            fault_type="cpu_stress",
            target_mode="one_pod",
            app=app,
            params={"workers": 2, "load": 80},
        )
    )

    # Pod-level: memory_stress
    anomalies.append(
        PodAnomalyHandler(
            namespace=namespace,
            fault_type="memory_stress",
            target_mode="one_pod",
            app=app,
            params={"size": "1GB", "workers": 1},
        )
    )

    # Pod-level: pod_failure
    anomalies.append(
        PodAnomalyHandler(
            namespace=namespace,
            fault_type="pod_failure",
            target_mode="one_pod",
            app=app,
        )
    )

    # Node-level: cpu
    anomalies.append(
        NodeAnomalyHandler(
            node_name=node_name,
            node_host=node_host,
            chaosd_port=chaosd_port,
            stress_type="cpu",
            params={"load": 80, "workers": 2},
        )
    )

    # Node-level: memory
    anomalies.append(
        NodeAnomalyHandler(
            node_name=node_name,
            node_host=node_host,
            chaosd_port=chaosd_port,
            stress_type="mem",
            params={"size": "512MB", "workers": 1},
        )
    )

    return anomalies


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batch-config",
        default=str(Path("experiment_configs") / "batch_config_iot_gateway_app.yaml"),
        help="Path to batch config YAML",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Per-anomaly run duration in seconds",
    )
    args = parser.parse_args()

    batch_cfg = load_batch_config(Path(args.batch_config))
    # Best-effort pre-cleanup
    try:
        ns = batch_cfg.get("namespace", "default")
        PodAnomalyHandler.cleanup_all([ns])
    except Exception as e:
        print(f"Warning: pod cleanup failed pre-run: {e}")
    try:
        chaosd_cfg = batch_cfg.get("chaosd", {})
        port = int(chaosd_cfg.get("port", 31767))
        nodes = batch_cfg.get("nodes", {})
        if nodes:
            NodeAnomalyHandler.cleanup_all(nodes, port)
    except Exception as e:
        print(f"Warning: node cleanup failed pre-run: {e}")

    anomalies = build_anomalies(batch_cfg)

    for idx, anomaly in enumerate(anomalies, start=1):
        print(f"\n=== Anomaly {idx}/{len(anomalies)} ===")
        info = anomaly.get_info()
        print("Info:", yaml.safe_dump(info, sort_keys=False))

        handle = None
        try:
            print("Starting...")
            handle = anomaly.start()
            print("Handle:")
            print(yaml.safe_dump(handle, sort_keys=False))

            print(f"Running for {args.duration}s...")
            time.sleep(args.duration)
        except KeyboardInterrupt:
            print("Interrupted by user; stopping...")
        except Exception as e:
            print(f"Error during anomaly run: {e}")
        finally:
            try:
                print("Stopping...")
                ok = anomaly.stop()
                print(f"Stopped: {ok}")
            except Exception as e:
                print(f"Error during stop: {e}")

    # Best-effort post-cleanup
    try:
        ns = batch_cfg.get("namespace", "default")
        PodAnomalyHandler.cleanup_all([ns])
    except Exception as e:
        print(f"Warning: pod cleanup failed post-run: {e}")
    try:
        chaosd_cfg = batch_cfg.get("chaosd", {})
        port = int(chaosd_cfg.get("port", 31767))
        nodes = batch_cfg.get("nodes", {})
        if nodes:
            NodeAnomalyHandler.cleanup_all(nodes, port)
    except Exception as e:
        print(f"Warning: node cleanup failed post-run: {e}")


if __name__ == "__main__":
    main()


