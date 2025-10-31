#!/usr/bin/env python3
"""Node-Level Stress Handler
Applies host-level CPU stress pinned to individual k3d node cpusets using stress utility."""

import subprocess
import signal
from typing import Dict, Any, List, Optional

from ..shared.prometheus_client import NODE_CPUSET_MAP


class NodeStressHandler:
    """Handles node-level CPU stress using host taskset + stress."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.active_stress_processes: Dict[str, subprocess.Popen] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_node_cpuset(self, node_name: str) -> Optional[str]:
        """Return cpuset mask for a k3d node container."""
        try:
            inspect_cmd = [
                "docker",
                "inspect",
                node_name,
                "--format",
                "{{.HostConfig.CpusetCpus}}",
            ]
            result = subprocess.run(inspect_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                cpuset = result.stdout.strip()
                if cpuset:
                    return cpuset
        except Exception as exc:
            print(f"⚠️  Failed to inspect cpuset for {node_name}: {exc}")

        # Fallback to static mapping
        for node_info in NODE_CPUSET_MAP.values():
            if node_info.get("k8s_name") == node_name:
                return node_info.get("cpuset")
        return None

    @staticmethod
    def _expand_cpuset(cpuset: str) -> List[int]:
        """Expand a cpuset string (e.g. "0-2,8") into CPU index list."""
        cpus: List[int] = []
        for part in cpuset.split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                start_s, end_s = part.split('-', 1)
                try:
                    start = int(start_s)
                    end = int(end_s)
                except ValueError:
                    continue
                cpus.extend(range(start, end + 1))
            else:
                try:
                    cpus.append(int(part))
                except ValueError:
                    continue
        return cpus

    # ------------------------------------------------------------------
    # Stress lifecycle
    # ------------------------------------------------------------------
    def start_cpuset_stress(self, node_name: str, duration: str) -> Optional[Dict[str, Any]]:
        """Launch stress pinned to the node's cpuset."""
        cpuset = self._get_node_cpuset(node_name)
        if not cpuset:
            print(f"⚠️  Unable to determine cpuset for {node_name}; skipping node stress")
            return None

        cpu_list = self._expand_cpuset(cpuset)
        cpu_workers = max(len(cpu_list), 1)

        # Ensure no duplicate stress running
        if node_name in self.active_stress_processes:
            self.stop_cpuset_stress(node_name)

        # Convert duration from stress-ng format (e.g., "900s") to stress format (just the number)
        duration_seconds = duration.rstrip('s')

        cmd = [
            "taskset",
            "-c",
            cpuset,
            "stress",
            "--cpu",
            str(cpu_workers),
            "--timeout",
            duration_seconds,
            "--quiet",
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.active_stress_processes[node_name] = proc
            print(
                f"🔥 Started node stress for {node_name}: cpuset={cpuset}, "
                f"workers={cpu_workers}, pid={proc.pid}, duration={duration}"
            )
            return {
                "cpuset": cpuset,
                "cpu_workers": cpu_workers,
                "pid": proc.pid,
                "duration": duration,
            }
        except FileNotFoundError as exc:
            print(f"⚠️  taskset or stress not available on host: {exc}")
        except Exception as exc:
            print(f"⚠️  Failed to start stress for {node_name}: {exc}")

        return None

    def stop_cpuset_stress(self, node_name: str) -> None:
        """Stop active node stress for a specific node."""
        proc = self.active_stress_processes.pop(node_name, None)
        if not proc:
            return

        if proc.poll() is not None:
            return

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception as exc:
            print(f"⚠️  Error stopping stress process for {node_name}: {exc}")

    def stop_all_cpuset_stress(self) -> None:
        """Stop stress workloads for all nodes."""
        nodes = list(self.active_stress_processes.keys())
        for node in nodes:
            self.stop_cpuset_stress(node)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def inject_node_stress_only(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Apply host-level CPU stress to a specific node.

        Expected config keys:
            node_name: k3d node container name (required)
            stress_duration: duration string in seconds (e.g., '3600s', optional, defaults to '3600s')
        """

        node_name = config.get("node_name")
        if not node_name:
            print("❌ node_name is required for node-level stress")
            return None

        duration = config.get("stress_duration") or config.get("duration") or "3600s"

        stress_info = self.start_cpuset_stress(node_name, duration)
        if not stress_info:
            print("❌ Failed to start node stress workload")
            return None

        experiment_record = {
            "name": f"node-stress-{node_name}-{config.get('intensity', 'default')}",
            "config": config,
            "node_stress_only": True,
            "stress": stress_info,
        }
        return experiment_record

    def reset_all_node_stress(self) -> bool:
        """Stop all host-level stress workloads."""
        self.stop_all_cpuset_stress()
        return True
    
    @staticmethod
    def cleanup_orphaned_stress_processes() -> int:
        """Find and kill all orphaned stress processes on the host.
        
        Returns:
            Number of processes killed
        """
        try:
            # Find all stress processes
            result = subprocess.run(
                ['pgrep', '-f', '^stress'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0 or not result.stdout.strip():
                # No stress processes found
                return 0
            
            pids = [pid.strip() for pid in result.stdout.strip().split('\n') if pid.strip()]
            
            if not pids:
                return 0
            
            print(f"🧹 Found {len(pids)} orphaned stress process(es), terminating...")
            
            # Try graceful termination first
            for pid in pids:
                try:
                    subprocess.run(['kill', '-TERM', pid], timeout=2, check=False)
                except Exception:
                    pass
            
            # Wait a bit for graceful shutdown
            subprocess.run(['sleep', '1'], timeout=2, check=False)
            
            # Force kill any remaining processes
            result = subprocess.run(
                ['pgrep', '-f', '^stress'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip():
                remaining_pids = [pid.strip() for pid in result.stdout.strip().split('\n') if pid.strip()]
                for pid in remaining_pids:
                    try:
                        subprocess.run(['kill', '-KILL', pid], timeout=2, check=False)
                    except Exception:
                        pass
                print(f"  ⚠️  Force killed {len(remaining_pids)} stubborn process(es)")
            
            print(f"  ✅ Cleaned up {len(pids)} stress process(es)")
            return len(pids)
            
        except subprocess.TimeoutExpired:
            print("⚠️  Timeout while cleaning up stress processes")
            return 0
        except Exception as exc:
            print(f"⚠️  Error cleaning up stress processes: {exc}")
            return 0

