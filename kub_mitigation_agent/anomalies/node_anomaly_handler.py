#!/usr/bin/env python3
"""
Node anomaly handler (Chaosd): CPU / Memory stress on a node via Chaosd HTTP API.
"""

from typing import Dict, Tuple
import time

import requests

from .anomaly_base import Anomaly


class NodeAnomalyHandler(Anomaly):
    """Node-level stress anomaly using Chaosd service mode.

    Supported types:
        - "cpu": requires load (0-100) and workers (int >= 1)
        - "mem": requires size (e.g., "512MB" or "1GB"); optional workers
    """

    def __init__(
        self,
        node_name: str,
        node_host: str,
        chaosd_port: int,
        stress_type: str,
        params: Dict,
        request_timeout_seconds: int = 10,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        super().__init__()
        self.node_name = node_name
        self.node_host = node_host
        self.chaosd_port = chaosd_port
        self.stress_type = stress_type  # "cpu" or "mem"
        self.params = params
        self.request_timeout_seconds = request_timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

        self._validate()

    def _validate(self) -> None:
        if self.stress_type not in {"cpu", "mem"}:
            raise ValueError(f"Unsupported stress_type: {self.stress_type}")

        if self.stress_type == "cpu":
            if "load" not in self.params or "workers" not in self.params:
                raise ValueError("CPU stress requires 'load' (0-100) and 'workers' (>=1)")
            load = self.params["load"]
            workers = self.params["workers"]
            if not isinstance(load, int) or load < 0 or load > 100:
                raise ValueError("'load' must be an integer between 0 and 100")
            if not isinstance(workers, int) or workers < 1:
                raise ValueError("'workers' must be an integer >= 1")

        if self.stress_type == "mem":
            if "size" not in self.params:
                raise ValueError("Memory stress requires 'size' (e.g., '512MB', '1GB')")
            size = self.params["size"]
            if not isinstance(size, str) or not size:
                raise ValueError("'size' must be a non-empty string, e.g., '512MB'")
            if "workers" in self.params:
                workers = self.params["workers"]
                if not isinstance(workers, int) or workers < 1:
                    raise ValueError("'workers' must be an integer >= 1 if provided")

    def _base_url(self) -> str:
        return f"http://{self.node_host}:{self.chaosd_port}"

    def _build_payload(self) -> Dict:
        if self.stress_type == "cpu":
            return {
                "action": "cpu",
                "load": int(self.params["load"]),
                "workers": int(self.params["workers"]),
            }
        # mem
        payload: Dict = {"action": "mem", "size": str(self.params["size"]) }
        if "workers" in self.params:
            payload["workers"] = int(self.params["workers"])
        return payload

    def get_info(self) -> Dict:
        fault_type = f"node_{self.stress_type}_stress"
        return {
            "mode": "chaos",
            "provider": "chaosd",
            "type": self.stress_type,
            "fault_type": fault_type,
            "target": {
                "name": self.node_name,
                "host": self.node_host,
                "port": self.chaosd_port,
            },
            "endpoint": f"{self._base_url()}/api/attack/stress",
            "payload": self._build_payload(),
        }

    def start(self) -> Dict:
        if self._handle is not None:
            return self._handle

        url = f"{self._base_url()}/api/attack/stress"
        payload = self._build_payload()
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(url, json=payload, timeout=self.request_timeout_seconds)
                if 500 <= response.status_code < 600:
                    raise RuntimeError(f"Server error {response.status_code}: {response.text}")
                response.raise_for_status()
                data = response.json()
                uid = data.get("uid") or data.get("Uid") or data.get("UID")
                if not uid:
                    raise RuntimeError("Chaosd did not return a uid for the stress attack")
                break
            except Exception as e:
                last_err = e
                if attempt == self.max_retries:
                    raise
                time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))

        self._handle = {
            "provider": "chaosd",
            "type": self.stress_type,
            "id": str(uid),
            "metadata": {
                "node_name": self.node_name,
                "host": self.node_host,
                "port": self.chaosd_port,
            },
        }
        return self._handle

    def stop(self) -> bool:
        if self._handle is None:
            return True

        uid = self._handle.get("id")
        url = f"{self._base_url()}/api/attack/{uid}"
        try:
            last_err = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = requests.delete(url, timeout=self.request_timeout_seconds)
                    if response.status_code == 404:
                        break
                    if 500 <= response.status_code < 600:
                        raise RuntimeError(f"Server error {response.status_code}: {response.text}")
                    response.raise_for_status()
                    break
                except Exception as e:
                    last_err = e
                    if attempt == self.max_retries:
                        raise
                    time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        finally:
            self._handle = None
        return True

    @staticmethod
    def cleanup_all(nodes: Dict[str, str], chaosd_port: int, request_timeout_seconds: int = 10, max_retries: int = 3, backoff_seconds: float = 1.0) -> Dict[str, Dict[str, int]]:
        """Recover all Chaosd experiments across all provided nodes.

        For each node host:
          - GET /api/experiments/
          - For each entry with a uid, DELETE /api/attack/{uid}

        Returns summary per node: {host: {"listed": n, "deleted": m, "errors": e}}

        Reference: https://chaos-mesh.org/docs/chaosd-search-recover/
        """
        import requests  # local import to avoid hard dependency at import time

        summary: Dict[str, Dict[str, int]] = {}
        for host in nodes.values():
            node_sum = {"listed": 0, "deleted": 0, "errors": 0}
            base = f"http://{host}:{chaosd_port}"
            try:
                resp = requests.get(f"{base}/api/experiments/", timeout=request_timeout_seconds)
                if not resp.ok:
                    node_sum["errors"] += 1
                    summary[host] = node_sum
                    continue
                experiments = resp.json() if resp.content else []
                if isinstance(experiments, dict):
                    experiments = [experiments]
                for exp in experiments or []:
                    uid = exp.get("uid") or exp.get("Uid") or exp.get("UID")
                    if not uid:
                        continue
                    node_sum["listed"] += 1
                    # retry delete per UID
                    deleted = False
                    for attempt in range(1, max_retries + 1):
                        try:
                            del_resp = requests.delete(f"{base}/api/attack/{uid}", timeout=request_timeout_seconds)
                            if del_resp.status_code in (200, 204, 404):
                                deleted = True
                                break
                            if 500 <= del_resp.status_code < 600:
                                raise RuntimeError(f"Server error {del_resp.status_code}")
                            del_resp.raise_for_status()
                            deleted = True
                            break
                        except Exception:
                            if attempt == max_retries:
                                break
                            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
                    if deleted:
                        node_sum["deleted"] += 1
                    else:
                        node_sum["errors"] += 1
            except Exception:
                node_sum["errors"] += 1
            summary[host] = node_sum
        return summary


