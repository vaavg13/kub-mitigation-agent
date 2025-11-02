#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from kub_mitigation_agent.clients.prometheus_client import get_prometheus_tool


def compute_step(duration: str) -> str:
    """Compute a reasonable Prometheus step for a given duration.

    Uses ~10 points over the window and snaps to a "nice" step size.
    """
    tool = get_prometheus_tool()
    total_seconds = tool._parse_duration_to_seconds(duration)
    target = max(total_seconds // 10, 1)
    nice_steps = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800, 3600]
    chosen = next((s for s in nice_steps if s >= target), nice_steps[-1])
    return f"{chosen}s"


def format_timeseries_output(result: Dict[str, Any], metric_type: str, duration: str) -> Dict[str, Any]:
    if result.get("error"):
        return result
    unit_map = {"cpu": "millicores", "memory": "MiB", "latency": "ms"}
    metric_type_map = {"cpu": "pod_cpu", "memory": "pod_memory", "latency": "service_latency"}
    if not result.get("data"):
        return {
            "status": "success",
            "metric_type": metric_type_map.get(metric_type, metric_type),
            "unit": result.get("unit", unit_map.get(metric_type, "unknown")),
            "duration": duration,
            "step": "5s",
            "values": {},
            "summary": "No data available",
        }
    try:
        step = result.get("query_info", {}).get("step", "5s")
        pod_data: Dict[str, Any] = {}
        for item in result["data"]:
            pod_name = item.get("pod") or item.get("service", "unknown")
            values = item.get("values", [])
            if not values:
                continue
            try:
                metric_values = [round(v.get("value", 0), 1) for v in values]
                pod_data[pod_name] = metric_values
            except Exception:
                continue
        unit = result.get("unit", unit_map.get(metric_type, "unknown"))
        return {
            "status": "success",
            "metric_type": metric_type_map.get(metric_type, metric_type),
            "unit": unit,
            "duration": duration,
            "step": step,
            "values": pod_data,
        }
    except Exception as e:
        return {"error": f"Failed to format {metric_type} output: {str(e)}", "raw_result": result}


def format_node_timeseries_output(result: Dict[str, Any], metric_type: str, duration: str) -> Dict[str, Any]:
    if result.get("error"):
        return result
    unit_map = {"cpu": "millicores", "memory": "MiB"}
    metric_type_map = {"cpu": "node_cpu", "memory": "node_memory"}
    actual_metric_type = result.get("metric_type", metric_type_map.get(metric_type, f"node_{metric_type}"))
    if not result.get("data"):
        return {
            "status": "success",
            "metric_type": actual_metric_type,
            "unit": result.get("unit", unit_map.get(metric_type, "unknown")),
            "duration": duration,
            "step": "5s",
            "values": {},
            "summary": "No data available",
        }
    try:
        step = result.get("query_info", {}).get("step", "5s")
        unit = result.get("unit", unit_map.get(metric_type, "unknown"))
        node_data: Dict[str, Any] = {}
        for item in result["data"]:
            node_name = item.get("node", "unknown")
            values = item.get("values", [])
            if not values:
                continue
            try:
                metric_values = [round(v.get("value", 0), 1) for v in values]
                node_data[node_name] = metric_values
            except Exception:
                continue
        output = {
            "status": "success",
            "metric_type": actual_metric_type,
            "unit": unit,
            "duration": duration,
            "step": step,
            "values": node_data,
        }
        if "description" in result:
            output["description"] = result["description"]
        return output
    except Exception as e:
        return {"error": f"Failed to format node {metric_type} output: {str(e)}", "raw_result": result}


def clamp_duration(duration: str, min_s: int = 60, max_s: int = 600) -> str:
    """Clamp duration between [min_s, max_s] using the Prom tool's parser."""
    tool = get_prometheus_tool()
    try:
        duration_seconds = tool._parse_duration_to_seconds(duration)
        if duration_seconds < min_s:
            return f"{min_s // 60}m" if min_s % 60 == 0 else f"{min_s}s"
        if duration_seconds > max_s:
            return f"{max_s // 60}m" if max_s % 60 == 0 else f"{max_s}s"
        return duration
    except Exception:
        return f"{min_s // 60}m" if min_s % 60 == 0 else f"{min_s}s"


def window_bounds(duration: str) -> tuple[str, str]:
    """Return (start_iso, end_iso) for now with the given duration window."""
    tool = get_prometheus_tool()
    end_dt = datetime.now(timezone.utc)
    duration_seconds = tool._parse_duration_to_seconds(duration)
    start_dt = end_dt - timedelta(seconds=duration_seconds)
    return start_dt.isoformat(), end_dt.isoformat()


