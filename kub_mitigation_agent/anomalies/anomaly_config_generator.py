#!/usr/bin/env python3
"""Anomaly generator that converts a deterministic spec into concrete Anomaly instances."""

from typing import Dict, List, Any

from .anomaly_base import Anomaly
from .node_anomaly_handler import NodeAnomalyHandler
from .pod_anomaly_handler import PodAnomalyHandler
from .no_failure_anomaly import NoFailureAnomaly

DEFAULT_SEED = 420


class AnomalyConfigGenerator:
    """Converts chaos_experiments spec to concrete anomaly instances."""
    
    def __init__(self, base_config: Dict[str, Any], seed: int = DEFAULT_SEED):
        """Initialize the anomaly config generator (seed retained for compatibility)."""
        self.base_config = base_config
        self.seed = seed
        
        self.available_apps = base_config.get("available_deployments", [])
        self.namespace = base_config.get("namespace", "default")
        
        self.chaos_experiments_spec = base_config.get("chaos_experiments", {})
        if not isinstance(self.chaos_experiments_spec, dict):
            raise ValueError("chaos_experiments must be a mapping")
    
    def _require_apps_defined(self):
        if not self.available_apps:
            raise ValueError("available_deployments is required for pod-level anomalies")

    @staticmethod
    def _require_nodes_defined(nodes: Dict[str, str]):
        if not nodes:
            raise ValueError("nodes mapping is required for node-level anomalies")

    def generate_instances_from_spec(self, nodes: Dict[str, str], chaosd_port: int) -> List[Anomaly]:
        """
        Generate fully configured anomaly instances from explicit specification.

        Expected structure:

        chaos_experiments:
          baseline:
            - name: "steady-state-1"
            - {}
          pod_level:
            cpu_stress:
              - app: "iot-gateway-edge-site-1"
                target_mode: "one_pod"
                workers: 2
                load: 90
            memory_stress:
              - app: "iot-gateway-edge-site-1"
                target_mode: "all_pods_app"
                size: "1GB"
                workers: 1
            pod_failure:
              - app: "iot-gateway-edge-site-1"
                target_mode: "one_pod"
          node_level:
            node_cpu_stress:
              - node: "edge-site-1-worker-1"
                load: 90
                workers: 4
            node_memory_stress:
              - node: "edge-site-1-worker-1"
                size: "3GB"
                workers: 1

        Args:
            nodes: Mapping of node name -> host/IP. Values must cover referenced targets.
            chaosd_port: Global Chaosd port used for all nodes.

        Returns:
            List of configured Anomaly instances.
        """
        if not self.chaos_experiments_spec:
            raise ValueError("No chaos_experiments specification found in config")

        all_instances: List[Anomaly] = []

        # --- Baseline (no-failure) experiments ---
        baseline_entries = self.chaos_experiments_spec.get("baseline", [])
        if baseline_entries:
            if not isinstance(baseline_entries, list):
                raise ValueError("baseline must be a list when provided")
            for _ in baseline_entries:
                all_instances.append(NoFailureAnomaly())

        # --- Pod-level anomalies (Chaos Mesh) ---
        pod_spec = self.chaos_experiments_spec.get("pod_level", {})
        if pod_spec and not isinstance(pod_spec, dict):
            raise ValueError("pod_level must be a mapping")

        if pod_spec:
            self._require_apps_defined()

            # cpu_stress
            pod_cpu = pod_spec.get("cpu_stress", {})
            if pod_cpu:
                entries = pod_cpu if isinstance(pod_cpu, list) else pod_cpu.get("experiments", [])
                if not isinstance(entries, list):
                    raise ValueError("pod_level.cpu_stress must be a list or contain an experiments list")
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("pod cpu entries must be mappings")
                    app_name = entry.get("app")
                    target_mode = entry.get("target_mode", "one_pod")
                    workers = entry.get("workers")
                    load = entry.get("load")
                    if not app_name or workers is None or load is None:
                        raise ValueError("pod_level.cpu_stress entries require 'app', 'workers', and 'load'")
                    if app_name not in self.available_apps:
                        raise ValueError(f"cpu_stress references unknown app '{app_name}'")
                    inst = PodAnomalyHandler(
                        namespace=self.namespace,
                        fault_type="cpu_stress",
                        target_mode=target_mode,
                        app=app_name,
                        params={"workers": int(workers), "load": int(load)},
                    )
                    all_instances.append(inst)

            # memory_stress
            pod_mem = pod_spec.get("memory_stress", {})
            if pod_mem:
                entries = pod_mem if isinstance(pod_mem, list) else pod_mem.get("experiments", [])
                if not isinstance(entries, list):
                    raise ValueError("pod_level.memory_stress must be a list or contain an experiments list")
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("pod memory entries must be mappings")
                    app_name = entry.get("app")
                    target_mode = entry.get("target_mode", "one_pod")
                    size = entry.get("size")
                    workers_opt = entry.get("workers")
                    if not app_name or size is None:
                        raise ValueError("pod_level.memory_stress entries require 'app' and 'size'")
                    if app_name not in self.available_apps:
                        raise ValueError(f"memory_stress references unknown app '{app_name}'")
                    params: Dict[str, Any] = {"size": str(size)}
                    if workers_opt is not None:
                        params["workers"] = int(workers_opt)
                    inst = PodAnomalyHandler(
                        namespace=self.namespace,
                        fault_type="memory_stress",
                        target_mode=target_mode,
                        app=app_name,
                        params=params,
                    )
                    all_instances.append(inst)

            # pod_failure
            pod_fail = pod_spec.get("pod_failure", {})
            if pod_fail:
                entries = pod_fail if isinstance(pod_fail, list) else pod_fail.get("experiments", [])
                if not isinstance(entries, list):
                    raise ValueError("pod_level.pod_failure must be a list or contain an experiments list")
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("pod failure entries must be mappings")
                    app_name = entry.get("app")
                    target_mode = entry.get("target_mode", "one_pod")
                    if not app_name:
                        raise ValueError("pod_level.pod_failure entries require 'app'")
                    if app_name not in self.available_apps:
                        raise ValueError(f"pod_failure references unknown app '{app_name}'")
                    inst = PodAnomalyHandler(
                        namespace=self.namespace,
                        fault_type="pod_failure",
                        target_mode=target_mode,
                        app=app_name,
                    )
                    all_instances.append(inst)

        # --- Node-level anomalies (Chaosd) ---
        node_level_spec = self.chaos_experiments_spec.get("node_level", {})
        if node_level_spec and not isinstance(node_level_spec, dict):
            raise ValueError("node_level must be a mapping")

        if node_level_spec:
            self._require_nodes_defined(nodes)

            # CPU stress (node-level)
            cpu_spec = node_level_spec.get("node_cpu_stress", {})
            if cpu_spec:
                entries = cpu_spec if isinstance(cpu_spec, list) else cpu_spec.get("experiments", [])
                if not isinstance(entries, list):
                    raise ValueError("node_level.node_cpu_stress must be a list or contain an experiments list")
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("node cpu entries must be mappings")
                    node_name = entry.get("node")
                    load = entry.get("load")
                    workers = entry.get("workers")
                    if not node_name or load is None or workers is None:
                        raise ValueError("node_cpu_stress entries require 'node', 'load', and 'workers'")
                    if node_name not in nodes:
                        raise ValueError(f"node_cpu_stress references unknown node '{node_name}'")
                    node_host = entry.get("host", nodes[node_name])
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
            if mem_spec:
                entries = mem_spec if isinstance(mem_spec, list) else mem_spec.get("experiments", [])
                if not isinstance(entries, list):
                    raise ValueError("node_level.node_memory_stress must be a list or contain an experiments list")
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("node memory entries must be mappings")
                    node_name = entry.get("node")
                    size = entry.get("size")
                    workers_opt = entry.get("workers")
                    if not node_name or size is None:
                        raise ValueError("node_memory_stress entries require 'node' and 'size'")
                    if node_name not in nodes:
                        raise ValueError(f"node_memory_stress references unknown node '{node_name}'")
                    node_host = entry.get("host", nodes[node_name])
                    params: Dict[str, Any] = {"size": str(size)}
                    if workers_opt is not None:
                        params["workers"] = int(workers_opt)
                    inst = NodeAnomalyHandler(
                        node_name=node_name,
                        node_host=node_host,
                        chaosd_port=chaosd_port,
                        stress_type="mem",
                        params=params,
                    )
                    all_instances.append(inst)

        return all_instances


