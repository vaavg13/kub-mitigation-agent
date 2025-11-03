#!/usr/bin/env python3
"""
Anomaly generator that converts a spec into concrete Anomaly instances.
Randomness is only applied to target selection (nodes, apps).
"""

import random
from typing import Dict, List, Any

from .anomaly_base import Anomaly
from .node_anomaly_handler import NodeAnomalyHandler
from .pod_anomaly_handler import PodAnomalyHandler

DEFAULT_SEED = 42


class AnomalyConfigGenerator:
    """Converts chaos_experiments spec to concrete anomaly instances."""
    
    def __init__(self, base_config: Dict[str, Any], seed: int = DEFAULT_SEED):
        """
        Initialize the anomaly config generator.
        
        Args:
            base_config: Base experiment configuration containing chaos_experiments spec
            seed: Random seed for reproducibility (used only for target selection)
        """
        self.base_config = base_config
        self.seed = seed
        random.seed(seed)
        
        # Extract available apps and namespace
        self.available_apps = base_config.get("available_deployments", [])
        self.namespace = base_config.get("namespace", "default")
        
        # Parse chaos experiments specification
        self.chaos_experiments_spec = base_config.get("chaos_experiments", {})
        
        # Printing is handled by the batch runner
    
    # Old dict-creating methods removed; this generator now only returns instances.

    def generate_instances_from_spec(self, nodes: Dict[str, str], chaosd_port: int) -> List[Anomaly]:
        """
        Generate fully configured anomaly instances from explicit specification.

        Structure expected under self.chaos_experiments_spec:

        chaos_experiments:
          pod_level:
            cpu_stress:
              count: <int>
              target_mode: "one_pod"|"all_pods_app"
              workers: <int>
              load: <0-100>
            memory_stress:
              count: <int>
              target_mode: "one_pod"|"all_pods_app"
              size: "<e.g., 512MB>"
              workers: <int?>
            pod_failure:
              count: <int>
              target_mode: "one_pod"|"all_pods_app"
          node_level:
            node_cpu_stress:
              count: <int>
              load: <0-100>
              workers: <int>
            node_memory_stress:
              count: <int>
              size: "<e.g., 512MB>"
              workers: <int?>

        Args:
            nodes: Mapping of node name -> host/IP. The selection will be random.
            chaosd_port: Global Chaosd port used for all nodes.

        Returns:
            List of configured Anomaly instances.
        """
        if not self.chaos_experiments_spec:
            raise ValueError("No chaos_experiments specification found in config")

        node_items = list(nodes.items()) if nodes else []
        all_instances: List[Anomaly] = []

        # --- Pod-level anomalies (Chaos Mesh) ---
        pod_spec = self.chaos_experiments_spec.get("pod_level", {})
        if not isinstance(pod_spec, dict):
            pod_spec = {}

        # cpu_stress
        pod_cpu = pod_spec.get("cpu_stress", {})
        try:
            cnt = int(pod_cpu.get("count", 0))
        except Exception:
            cnt = 0
        if cnt > 0:
            target_mode = pod_cpu.get("target_mode", "one_pod")
            workers = pod_cpu.get("workers")
            load = pod_cpu.get("load")
            if workers is None or load is None:
                raise ValueError("pod_level.cpu_stress requires 'workers' and 'load'")
            if not self.available_apps:
                raise ValueError("available_deployments is required for pod-level anomalies")
            for _ in range(cnt):
                app = random.choice(self.available_apps)
                inst = PodAnomalyHandler(
                    namespace=self.namespace,
                    fault_type="cpu_stress",
                    target_mode=target_mode,
                    app=app,
                    params={"workers": int(workers), "load": int(load)},
                )
                all_instances.append(inst)

        # memory_stress
        pod_mem = pod_spec.get("memory_stress", {})
        try:
            cnt = int(pod_mem.get("count", 0))
        except Exception:
            cnt = 0
        if cnt > 0:
            target_mode = pod_mem.get("target_mode", "one_pod")
            size = pod_mem.get("size")
            if size is None:
                raise ValueError("pod_level.memory_stress requires 'size'")
            workers_opt = pod_mem.get("workers")
            if not self.available_apps:
                raise ValueError("available_deployments is required for pod-level anomalies")
            for _ in range(cnt):
                app = random.choice(self.available_apps)
                params: Dict[str, Any] = {"size": str(size)}
                if workers_opt is not None:
                    params["workers"] = int(workers_opt)
                inst = PodAnomalyHandler(
                    namespace=self.namespace,
                    fault_type="memory_stress",
                    target_mode=target_mode,
                    app=app,
                    params=params,
                )
                all_instances.append(inst)

        # pod_failure
        pod_fail = pod_spec.get("pod_failure", {})
        try:
            cnt = int(pod_fail.get("count", 0))
        except Exception:
            cnt = 0
        if cnt > 0:
            target_mode = pod_fail.get("target_mode", "one_pod")
            if not self.available_apps:
                raise ValueError("available_deployments is required for pod-level anomalies")
            for _ in range(cnt):
                app = random.choice(self.available_apps)
                inst = PodAnomalyHandler(
                    namespace=self.namespace,
                    fault_type="pod_failure",
                    target_mode=target_mode,
                    app=app,
                )
                all_instances.append(inst)

        # --- Node-level anomalies (Chaosd) ---
        node_level_spec = self.chaos_experiments_spec.get("node_level", {})
        if not isinstance(node_level_spec, dict):
            node_level_spec = {}

        # CPU stress (node-level)
        cpu_spec = node_level_spec.get("node_cpu_stress", {})
        try:
            cpu_count = int(cpu_spec.get("count", 0))
        except Exception:
            cpu_count = 0
        if cpu_count > 0:
            load = cpu_spec.get("load")
            workers = cpu_spec.get("workers")
            if load is None or workers is None:
                raise ValueError("node_cpu_stress requires 'load' and 'workers'")
            if not node_items:
                raise ValueError("nodes mapping is required for node-level anomalies")
            for _ in range(cpu_count):
                node_name, node_host = random.choice(node_items)
                inst = NodeAnomalyHandler(
                    node_name=node_name,
                    node_host=node_host,
                    chaosd_port=chaosd_port,
                    stress_type="cpu",
                    params={"load": int(load), "workers": int(workers)},
                )
                all_instances.append(inst)

        # Memory stress (node-level)
        mem_spec = node_level_spec.get("node_memory_stress", {})
        try:
            mem_count = int(mem_spec.get("count", 0))
        except Exception:
            mem_count = 0
        if mem_count > 0:
            size = mem_spec.get("size")
            if size is None:
                raise ValueError("node_memory_stress requires 'size' (e.g., '512MB')")
            workers_opt = mem_spec.get("workers")
            mem_params: Dict[str, Any] = {"size": str(size)}
            if workers_opt is not None:
                mem_params["workers"] = int(workers_opt)
            if not node_items:
                raise ValueError("nodes mapping is required for node-level anomalies")
            for _ in range(mem_count):
                node_name, node_host = random.choice(node_items)
                inst = NodeAnomalyHandler(
                    node_name=node_name,
                    node_host=node_host,
                    chaosd_port=chaosd_port,
                    stress_type="mem",
                    params=mem_params,
                )
                all_instances.append(inst)

        # Shuffle to randomize execution order
        random.shuffle(all_instances)
        return all_instances


