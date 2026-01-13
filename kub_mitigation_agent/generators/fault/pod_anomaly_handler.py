#!/usr/bin/env python3
"""
Pod anomaly handler (Chaos Mesh): CPU/Memory stress and Pod failure on pods.
"""

import os
import subprocess
import tempfile
from typing import Dict, Any, Optional

import yaml

from .anomaly_base import Anomaly


class PodAnomalyHandler(Anomaly):
    def __init__(
        self,
        namespace: str,
        fault_type: str,
        target_mode: str,
        app: str,
        params: Optional[Dict[str, Any]] = None,
        experiment_name: Optional[str] = None,
    ):
        super().__init__()
        self.namespace = namespace
        self.fault_type = fault_type  # "cpu_stress" | "memory_stress" | "pod_failure"
        self.target_mode = target_mode  # "one_pod" | "all_pods_app"
        self.app = app
        self.params = params or {}
        self.experiment_name = experiment_name

        self._validate()

    def _validate(self) -> None:
        if self.fault_type not in {"cpu_stress", "memory_stress", "pod_failure"}:
            raise ValueError(f"Unsupported fault_type: {self.fault_type}")
        if self.target_mode not in {"one_pod", "all_pods_app"}:
            raise ValueError(f"Unsupported target_mode: {self.target_mode}")
        if not self.app:
            raise ValueError("'app' label is required for pod-level chaos")
        if self.fault_type == "cpu_stress":
            if "workers" not in self.params or "load" not in self.params:
                raise ValueError("cpu_stress requires 'workers' and 'load'")
        if self.fault_type == "memory_stress":
            if "size" not in self.params:
                raise ValueError("memory_stress requires 'size'")

    def _generate_name(self) -> str:
        raw = f"{self.fault_type}-{self.target_mode}-{self.app}".replace("_", "-").lower()
        sanitized = "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in raw)
        trimmed = sanitized[:60].strip("-")
        if not trimmed:
            trimmed = "chaos"
        return trimmed

    def _build_template(self) -> Dict[str, Any]:
        name = self._generate_name()
        base_template: Dict[str, Any] = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
            },
            "spec": {},
        }

        selector = {
            "namespaces": [self.namespace],
            "labelSelectors": {"app": self.app},
        }
        base_template["spec"]["selector"] = selector
        base_template["spec"]["mode"] = "one" if self.target_mode == "one_pod" else "all"

        if self.fault_type in {"cpu_stress", "memory_stress"}:
            base_template["kind"] = "StressChaos"
            stressors: Dict[str, Any] = {}
            if self.fault_type == "cpu_stress":
                stressors["cpu"] = {
                    "workers": int(self.params["workers"]),
                    "load": int(self.params["load"]),
                }
            else:
                mem_stressor: Dict[str, Any] = {"size": str(self.params["size"]) }
                if "workers" in self.params:
                    mem_stressor["workers"] = int(self.params["workers"])
                stressors["memory"] = mem_stressor
            base_template["spec"]["stressors"] = stressors

        elif self.fault_type == "pod_failure":
            base_template["kind"] = "PodChaos"
            base_template["spec"]["action"] = "pod-failure"

        return base_template

    def get_info(self) -> Dict:
        info: Dict[str, Any] = {
            "mode": "chaos",
            "provider": "chaosmesh",
            "type": self.fault_type,
            "fault_type": self.fault_type,
            "target": {
                "namespace": self.namespace,
                "mode": self.target_mode,
                "app": self.app,
            },
            "parameters": dict(self.params),
        }
        if self.experiment_name:
            info["name"] = self.experiment_name
        return info

    def start(self) -> Dict:
        if self._handle is not None:
            return self._handle

        template = self._build_template()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
            yaml.dump(template, tmp, default_flow_style=False, sort_keys=False)
            path = tmp.name
        try:
            result = subprocess.run(["kubectl", "apply", "-f", path], capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"kubectl apply failed: {result.stderr}")
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

        name = template["metadata"]["name"]
        self._handle = {
            "provider": "chaosmesh",
            "type": self.fault_type,
            "id": name,
            "metadata": {
                "namespace": self.namespace,
                "kind": "stresschaos" if self.fault_type in {"cpu_stress", "memory_stress"} else "podchaos",
            },
        }
        return self._handle

    def stop(self) -> bool:
        if self._handle is None:
            return True
        name = self._handle.get("id")
        kind = self._handle.get("metadata", {}).get("kind", "chaos")
        try:
            subprocess.run(
                [
                    "kubectl",
                    "delete",
                    kind,
                    name,
                    "-n",
                    self.namespace,
                    "--ignore-not-found=true",
                ],
                capture_output=True,
                text=True,
            )
        finally:
            self._handle = None
        return True

    @staticmethod
    def cleanup_all(namespaces: list[str]) -> Dict[str, bool]:
        """Delete all StressChaos and PodChaos in the given namespaces.

        Returns a dict {namespace: success_bool} summarizing delete calls.
        """
        results: Dict[str, bool] = {}
        for ns in namespaces:
            ok = True
            try:
                r1 = subprocess.run([
                    "kubectl", "delete", "stresschaos", "--all", "-n", ns, "--ignore-not-found=true"
                ], capture_output=True, text=True)
                if r1.returncode not in (0,):
                    ok = False
                r2 = subprocess.run([
                    "kubectl", "delete", "podchaos", "--all", "-n", ns, "--ignore-not-found=true"
                ], capture_output=True, text=True)
                if r2.returncode not in (0,):
                    ok = False
            except Exception:
                ok = False
            results[ns] = ok
        return results


