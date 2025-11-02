#!/usr/bin/env python3
"""
Unified tool definitions using LangChain's @tool decorator.

Each tool contains its own execution logic. Input schemas are defined by
type hints and docstrings (no Pydantic models), and shared dependencies
are accessed via ToolRuntime when needed.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from typing import Literal

from langchain.tools import tool

from kub_mitigation_agent.clients.prometheus_client import get_prometheus_tool
from .tools_utils import (
    compute_step,
    clamp_duration,
    window_bounds,
    format_timeseries_output,
    format_node_timeseries_output,
)


logger = logging.getLogger(__name__)


# Shared MCP handle (set by agent at init time)
_MCP_CLIENT = None

def set_mcp_client(mcp_client: Any) -> None:
    global _MCP_CLIENT
    _MCP_CLIENT = mcp_client

"""
Warmup cutoff timestamp (UTC).

If set, timeseries queries will only look back to this point by reducing the
Prometheus query duration (server-side). If unset, queries are not constrained
by warmup and behave as before.
"""
_WARMUP_END_TS_UTC: Optional[datetime] = None

def set_warmup_end_timestamp(timestamp_iso: Optional[str]) -> None:
    """Set or clear the warmup end timestamp (UTC) used by metrics tools.

    Args:
        timestamp_iso: ISO-8601 timestamp string. If None/empty, clears cutoff.
    """
    global _WARMUP_END_TS_UTC
    if not timestamp_iso:
        _WARMUP_END_TS_UTC = None
        return
    try:
        dt = datetime.fromisoformat(timestamp_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        _WARMUP_END_TS_UTC = dt
    except Exception:
        # Leave as-is on parse failure
        return

"""
Tools: planning, metrics, kubectl, and utility.
All tool names are snake_case and match their function names.
"""


@tool(description="Create an actionable, concrete plan of tool calls before taking action.")
def generate_action_plan(objective: str, situation: str, steps: List[str], expected_outcomes: List[str]) -> Dict[str, Any]:
    """Create an action plan.

    Args:
        objective: Clear objective for this incident or mitigation effort
        situation: Current evidence or context motivating this plan
        steps: Ordered list of concrete tool calls or operational steps
        expected_outcomes: Signals or metrics that will confirm success
    """
    return {
        "objective": objective,
        "situation": situation,
        "steps": steps,
        "expected_outcomes": expected_outcomes,
    }


@tool(description="Emit the final operational summary and stop the operation.")
def generate_operational_summary(
    objective: str,
    actions_completed: List[str],
    results_achieved: List[str],
    status: str,
    problem_location: Optional[List[Dict[str, str]]] = None,
    success: bool = False,
) -> Dict[str, Any]:
    """Generate final operational summary for the run."""
    return {
        "objective": objective,
        "actions_completed": actions_completed,
        "results_achieved": results_achieved,
        "status": status,
        "problem_location": problem_location or [],
        "success": success,
    }


@tool(description="Sleep for a number of seconds.")
async def sleep_seconds(duration: float) -> Dict[str, Any]:
    """Sleep for a given duration in seconds."""
    await asyncio.sleep(duration)
    return {"duration": duration, "status": "completed"}


@tool(description="Get pod/service timeseries metrics from Prometheus.")
def prometheus_get_timeseries(metric_type: Literal["cpu", "memory", "latency"], namespace: str, duration: str = "5m") -> Dict[str, Any]:
    """Query Prometheus for pod/service timeseries (cpu|memory|latency)."""
    tool = get_prometheus_tool()
    requested_duration = clamp_duration(duration, min_s=60, max_s=600)
    # Apply warmup cutoff by shortening query duration only when valid
    now = datetime.now(timezone.utc)
    effective_duration = requested_duration
    try:
        total_seconds = tool._parse_duration_to_seconds(requested_duration)
        if _WARMUP_END_TS_UTC is not None and _WARMUP_END_TS_UTC <= now:
            window_start_ts = now.timestamp() - total_seconds
            cutoff_ts = _WARMUP_END_TS_UTC.timestamp()
            effective_start_ts = max(window_start_ts, cutoff_ts)
            effective_seconds = int(now.timestamp() - effective_start_ts)
            if effective_seconds >= 60:
                effective_duration = f"{effective_seconds}s"
    except Exception:
        effective_duration = requested_duration
    step = compute_step(effective_duration)
    rate_window = "30s"
    try:
        start_iso, end_iso = window_bounds(effective_duration)
        if metric_type == "cpu":
            result = tool.get_pod_cpu_timeseries(effective_duration, step, namespace, rate_window=rate_window)
        elif metric_type == "memory":
            result = tool.get_pod_memory_timeseries(effective_duration, step, namespace)
        elif metric_type == "latency":
            result = tool.get_istio_latency_timeseries(effective_duration, step, namespace, percentile="0.95", rate_window=rate_window)
        else:
            return {"error": f"Unsupported metric type: {metric_type}. Use 'cpu', 'memory', or 'latency'"}
        if result.get("error"):
            return result
        base = format_timeseries_output(result, metric_type, effective_duration)
        output = {
            "start": start_iso,
            "end": end_iso,
            "status": base.get("status"),
            "metric_type": base.get("metric_type"),
            "unit": base.get("unit"),
            "duration": base.get("duration"),
            "step": base.get("step"),
            "values": base.get("values", {}),
        }
        if "summary" in base:
            output["summary"] = base["summary"]
        return output
    except Exception as e:
        return {"error": f"Failed to get {metric_type} timeseries: {str(e)}"}


@tool(description="Get node-level timeseries metrics from Prometheus.")
def prometheus_get_node_timeseries(metric_type: Literal["cpu", "memory"], duration: str = "5m") -> Dict[str, Any]:
    """Query Prometheus for node-level timeseries (cpu|memory)."""
    tool = get_prometheus_tool()
    requested_duration = clamp_duration(duration, min_s=60, max_s=600)
    now = datetime.now(timezone.utc)
    effective_duration = requested_duration
    try:
        total_seconds = tool._parse_duration_to_seconds(requested_duration)
        if _WARMUP_END_TS_UTC is not None and _WARMUP_END_TS_UTC <= now:
            window_start_ts = now.timestamp() - total_seconds
            cutoff_ts = _WARMUP_END_TS_UTC.timestamp()
            effective_start_ts = max(window_start_ts, cutoff_ts)
            effective_seconds = int(now.timestamp() - effective_start_ts)
            if effective_seconds >= 60:
                effective_duration = f"{effective_seconds}s"
    except Exception:
        effective_duration = requested_duration
    step = compute_step(effective_duration)
    try:
        start_iso, end_iso = window_bounds(effective_duration)
        if metric_type == "cpu":
            container_result = tool.get_node_cpu_timeseries(effective_duration, step)
            node_result = tool.get_node_core_cpu_timeseries(effective_duration, step)
            if container_result.get("error") and node_result.get("error"):
                return {"error": "Failed to get both container and node CPU metrics"}
            container_formatted = format_node_timeseries_output(container_result, metric_type, effective_duration) if not container_result.get("error") else {}
            node_formatted = format_node_timeseries_output(node_result, metric_type, effective_duration) if not node_result.get("error") else {}
            return {
                "start": start_iso,
                "end": end_iso,
                "status": "success",
                "metric_type": "node_cpu",
                "unit": "cores",
                "duration": effective_duration,
                "step": step,
                "metrics": {
                    "pod_cpu": {
                        "description": "CPU consumed by pods running on each node (in cores)",
                        "values": container_formatted.get("values", {}),
                    },
                    "node_cpu": {
                        "description": "Total node CPU usage from host metrics (in cores)",
                        "values": node_formatted.get("values", {}),
                    },
                },
            }
        elif metric_type == "memory":
            result = tool.get_node_memory_timeseries(effective_duration, step)
            if result.get("error"):
                return result
            base = format_node_timeseries_output(result, metric_type, effective_duration)
            output = {
                "start": start_iso,
                "end": end_iso,
                "status": base.get("status"),
                "metric_type": base.get("metric_type"),
                "unit": base.get("unit"),
                "duration": base.get("duration"),
                "step": base.get("step"),
                "values": base.get("values", {}),
            }
            if "summary" in base:
                output["summary"] = base["summary"]
            return output
        else:
            return {"error": f"Unsupported node metric type: {metric_type}. Use 'cpu' or 'memory'"}
    except Exception as e:
        return {"error": f"Failed to get node {metric_type} timeseries: {str(e)}"}


@tool(description="Get a service call topology snapshot from Prometheus.")
def prometheus_get_service_topology(namespace: Optional[str] = None, time_window: str = "5m") -> Dict[str, Any]:
    """Get a recent service-to-service call topology."""
    tool = get_prometheus_tool()
    return tool.get_service_topology(namespace, time_window)


@tool(description="Apply a Kubernetes manifest via MCP kubectl.")
async def kubectl_apply(manifest: str, namespace: Optional[str] = None, dryRun: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl apply -f manifest [--namespace] [--dry-run]."""
    args: Dict[str, Any] = {"manifest": manifest, "namespace": namespace, "dryRun": dryRun}
    return await _MCP_CLIENT.call_tool("kubectl_apply", args)


@tool(description="Get Kubernetes resources via MCP kubectl.")
async def kubectl_get(resourceType: str, name: Optional[str] = None, namespace: Optional[str] = None, output: Optional[Literal["json", "yaml", "wide", "name"]] = None) -> Dict[str, Any]:
    """kubectl get <type> [name] [-n namespace] [-o json|yaml|wide|name]."""
    args: Dict[str, Any] = {"resourceType": resourceType, "name": name, "namespace": namespace, "output": output}
    return await _MCP_CLIENT.call_tool("kubectl_get", args)


@tool(description="Delete a Kubernetes resource via MCP kubectl.")
async def kubectl_delete(resourceType: str, name: str, namespace: Optional[str] = None, force: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl delete <type> <name> [-n namespace] [--force]."""
    args: Dict[str, Any] = {"resourceType": resourceType, "name": name, "namespace": namespace, "force": force}
    return await _MCP_CLIENT.call_tool("kubectl_delete", args)


@tool(description="List Kubernetes resources via MCP kubectl.")
async def kubectl_list(resourceType: str, namespace: Optional[str] = None, allNamespaces: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl get <type> [-n namespace] [--all-namespaces]."""
    args: Dict[str, Any] = {"resourceType": resourceType, "namespace": namespace, "allNamespaces": allNamespaces}
    return await _MCP_CLIENT.call_tool("kubectl_list", args)


@tool(description="Scale a workload via MCP kubectl.")
async def kubectl_scale(name: str, namespace: Optional[str] = None, replicas: int = 1, resourceType: Optional[Literal["deployment", "replicaset", "statefulset"]] = None) -> Dict[str, Any]:
    """kubectl scale <resourceType>/<name> --replicas=N [-n namespace]."""
    args: Dict[str, Any] = {"name": name, "namespace": namespace, "replicas": replicas, "resourceType": resourceType}
    return await _MCP_CLIENT.call_tool("kubectl_scale", args)


@tool(description="Patch a Kubernetes resource via MCP kubectl.")
async def kubectl_patch(resourceType: str, name: str, patchData: Dict[str, Any], namespace: Optional[str] = None, patchType: Optional[Literal["strategic", "merge", "json"]] = None, dryRun: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl patch <type> <name> [-n ns] --type <t> -p <json>."""
    args: Dict[str, Any] = {
        "resourceType": resourceType,
        "name": name,
        "namespace": namespace,
        "patchType": patchType,
        "patchData": patchData,
        "dryRun": dryRun,
    }
    return await _MCP_CLIENT.call_tool("kubectl_patch", args)


@tool(description="Describe a Kubernetes resource via MCP kubectl.")
async def kubectl_describe(resourceType: str, name: str, namespace: Optional[str] = None, allNamespaces: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl describe <type> <name> [-n namespace] [--all-namespaces]."""
    args: Dict[str, Any] = {"resourceType": resourceType, "name": name, "namespace": namespace, "allNamespaces": allNamespaces}
    return await _MCP_CLIENT.call_tool("kubectl_describe", args)


@tool(description="Fetch logs via MCP kubectl.")
async def kubectl_logs(
    resourceType: Literal["pod", "deployment", "job", "cronjob"],
    name: str,
    namespace: str,
    container: Optional[str] = None,
    tail: Optional[int] = None,
    since: Optional[str] = None,
    sinceTime: Optional[str] = None,
    timestamps: Optional[bool] = None,
    previous: Optional[bool] = None,
    follow: Optional[bool] = None,
    labelSelector: Optional[str] = None,
) -> Dict[str, Any]:
    """kubectl logs for pod/deployment/job/cronjob."""
    args: Dict[str, Any] = {
        "resourceType": resourceType,
        "name": name,
        "namespace": namespace,
        "container": container,
        "tail": tail,
        "since": since,
        "sinceTime": sinceTime,
        "timestamps": timestamps,
        "previous": previous,
        "follow": follow,
        "labelSelector": labelSelector,
    }
    return await _MCP_CLIENT.call_tool("kubectl_logs", args)


@tool(description="Rollout operations via MCP kubectl.")
async def kubectl_rollout(
    subCommand: Literal["history", "pause", "restart", "resume", "status", "undo"],
    resourceType: Literal["deployment", "daemonset", "statefulset"],
    name: str,
    namespace: Optional[str] = None,
    revision: Optional[int] = None,
    toRevision: Optional[int] = None,
    timeout: Optional[str] = None,
    watch: Optional[bool] = None,
) -> Dict[str, Any]:
    """kubectl rollout <subCommand> <resourceType>/<name>."""
    # Inline tiny guardrail for timeout: cap to 9m if provided and longer
    def _cap_timeout(t: Optional[str]) -> Optional[str]:
        if not t or t in ("0", "0s"):
            return t
        # crude cap without parsing complexity
        return "9m" if t.endswith("m") or t.endswith("s") else t

    args: Dict[str, Any] = {
        "subCommand": subCommand,
        "resourceType": resourceType,
        "name": name,
        "namespace": namespace,
        "revision": revision,
        "toRevision": toRevision,
        "timeout": _cap_timeout(timeout),
        "watch": watch,
    }
    return await _MCP_CLIENT.call_tool("kubectl_rollout", args)


@tool(description="Drain a node via MCP kubectl (uses kubectl_generic).")
async def kubectl_drain(
    node_name: str,
    ignore_daemonsets: bool = True,
    delete_emptydir_data: bool = False,
    force: bool = False,
    grace_period: int = 30,
    timeout: str = "0s",
    disable_eviction: bool = False,
) -> Dict[str, Any]:
    """kubectl drain <node> with safe defaults (timeouts capped at 9m)."""
    flags: Dict[str, Any] = {}
    if ignore_daemonsets:
        flags["ignore-daemonsets"] = True
    if delete_emptydir_data:
        flags["delete-emptydir-data"] = True
    if force:
        flags["force"] = True
    if disable_eviction:
        flags["disable-eviction"] = True
    if grace_period != 30:
        flags["grace-period"] = grace_period
    # crude cap to 9m if provided and nonzero
    if timeout and timeout not in ("0", "0s"):
        flags["timeout"] = "9m"
    generic_args = {"command": "drain", "name": node_name, "flags": flags}
    return await _MCP_CLIENT.call_tool("kubectl_generic", generic_args)


@tool(description="Cordon a node via MCP kubectl (uses kubectl_generic).")
async def kubectl_cordon(node_name: str) -> Dict[str, Any]:
    """kubectl cordon <node>."""
    generic_args = {"command": "cordon", "name": node_name}
    return await _MCP_CLIENT.call_tool("kubectl_generic", generic_args)


@tool(description="Uncordon a node via MCP kubectl (uses kubectl_generic).")
async def kubectl_uncordon(node_name: str) -> Dict[str, Any]:
    """kubectl uncordon <node>."""
    generic_args = {"command": "uncordon", "name": node_name}
    return await _MCP_CLIENT.call_tool("kubectl_generic", generic_args)


# Public registry of tool runnables
ALL_TOOLS = [
    generate_action_plan,
    generate_operational_summary,
    sleep_seconds,
    prometheus_get_timeseries,
    prometheus_get_node_timeseries,
    prometheus_get_service_topology,
    kubectl_apply,
    kubectl_get,
    kubectl_delete,
    kubectl_list,
    kubectl_scale,
    kubectl_patch,
    kubectl_describe,
    kubectl_logs,
    kubectl_rollout,
    kubectl_drain,
    kubectl_cordon,
    kubectl_uncordon,
]