import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from langchain.tools import tool

from kub_mitigation_agent.clients.prometheus import get_prometheus_client, parse_duration

logger = logging.getLogger(__name__)

# Global state for warmup cutoff
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

# --- Helpers (formerly in tools_utils.py) ---

def _compute_step(duration: str) -> str:
    """Compute a reasonable Prometheus step for a given duration."""
    total_seconds = parse_duration(duration)
    target = max(total_seconds // 10, 1)
    nice_steps = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800, 3600]
    chosen = next((s for s in nice_steps if s >= target), nice_steps[-1])
    return f"{chosen}s"

def _clamp_duration(duration: str, min_s: int = 60, max_s: int = 600) -> str:
    """Clamp duration between [min_s, max_s]."""
    try:
        duration_seconds = parse_duration(duration)
        if duration_seconds < min_s:
            return f"{min_s // 60}m" if min_s % 60 == 0 else f"{min_s}s"
        if duration_seconds > max_s:
            return f"{max_s // 60}m" if max_s % 60 == 0 else f"{max_s}s"
        return duration
    except Exception:
        return f"{min_s // 60}m" if min_s % 60 == 0 else f"{min_s}s"

def _window_bounds(duration: str) -> Tuple[str, str]:
    """Return (start_iso, end_iso) for now with the given duration window."""
    end_dt = datetime.now(timezone.utc)
    duration_seconds = parse_duration(duration)
    start_dt = end_dt - timedelta(seconds=duration_seconds)
    return start_dt.isoformat(), end_dt.isoformat()

def _format_timeseries_output(result: Dict[str, Any], metric_type: str, duration: str) -> Dict[str, Any]:
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

def _format_node_timeseries_output(result: Dict[str, Any], metric_type: str, duration: str) -> Dict[str, Any]:
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

# --- Query Implementation Helpers ---

def _get_pod_cpu_timeseries(duration: str, step: str, namespace: Optional[str] = None, rate_window: str = "1m") -> Dict[str, Any]:
    client = get_prometheus_client()
    now = datetime.now(timezone.utc)
    duration_seconds = parse_duration(duration)
    start_ts = (now - timedelta(seconds=duration_seconds)).timestamp()
    end_ts = now.timestamp()

    base_selector = 'image!="", container!="POD"'
    if namespace:
        namespace_filter = f'namespace="{namespace}"'
        full_selector = f'{base_selector}, {namespace_filter}'
    else:
        full_selector = base_selector
    
    query = f'sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{{{full_selector}}}[{rate_window}]))'
    data = client.query_range(query, start_ts, end_ts, step)
    
    if not data or data.get('status') != 'success':
        return {"error": "Failed to query pod CPU time series", "data": []}
    
    results = []
    for series in data['data']['result']:
        namespace_val = series['metric'].get('namespace', 'unknown_namespace')
        pod_val = series['metric'].get('pod', 'unknown_pod')
        values = []
        for timestamp, value in series['values']:
            cpu_millicores = round(float(value) * 1000, 1)
            values.append({
                "value": cpu_millicores
            })
        
        results.append({
            "namespace": namespace_val,
            "pod": pod_val,
            "values": values
        })
    
    return {
        "status": "success",
        "metric_type": "pod_cpu",
        "unit": "millicores",
        "query_info": {"duration": duration, "step": step, "rate_window": rate_window, "namespace_filter": namespace or "all_namespaces"},
        "data": results
    }

def _get_pod_memory_timeseries(duration: str, step: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    client = get_prometheus_client()
    now = datetime.now(timezone.utc)
    duration_seconds = parse_duration(duration)
    start_ts = (now - timedelta(seconds=duration_seconds)).timestamp()
    end_ts = now.timestamp()

    base_selector = 'image!="", container!="POD"'
    if namespace:
        namespace_filter = f'namespace="{namespace}"'
        full_selector = f'{base_selector}, {namespace_filter}'
    else:
        full_selector = base_selector
    
    query = f'sum by (namespace, pod) (container_memory_working_set_bytes{{{full_selector}}})'
    data = client.query_range(query, start_ts, end_ts, step)
    
    if not data or data.get('status') != 'success':
        return {"error": "Failed to query pod memory time series", "data": []}
    
    results = []
    for series in data['data']['result']:
        namespace_val = series['metric'].get('namespace', 'unknown_namespace')
        pod_val = series['metric'].get('pod', 'unknown_pod')
        values = []
        for timestamp, value in series['values']:
            memory_bytes = int(float(value))
            memory_mib = round(memory_bytes / (1024 * 1024), 1)
            values.append({
                "value": memory_mib
            })
        
        results.append({
            "namespace": namespace_val,
            "pod": pod_val,
            "values": values
        })
    
    return {
        "status": "success",
        "metric_type": "pod_memory",
        "unit": "MiB",
        "query_info": {"duration": duration, "step": step, "namespace_filter": namespace or "all_namespaces"},
        "data": results
    }

def _get_istio_latency_timeseries(duration: str, step: str, namespace: Optional[str] = None, percentile: str = "0.95", rate_window: str = "2m") -> Dict[str, Any]:
    client = get_prometheus_client()
    now = datetime.now(timezone.utc)
    duration_seconds = parse_duration(duration)
    start_ts = (now - timedelta(seconds=duration_seconds)).timestamp()
    end_ts = now.timestamp()

    if namespace:
        selector = f'reporter="destination", destination_workload_namespace="{namespace}"'
    else:
        selector = 'reporter="destination"'

    query = f'''histogram_quantile({percentile},
        sum(rate(istio_request_duration_milliseconds_bucket{{{selector}}}[{rate_window}]))
        by (le, destination_workload, destination_workload_namespace)
    )'''
    data = client.query_range(query, start_ts, end_ts, step)

    if not data or data.get('status') != 'success':
        return {"error": "Failed to query Istio latency time series", "data": []}

    results = []
    for series in data['data']['result']:
        svc = series['metric'].get('destination_workload', 'unknown')
        namespace_val = series['metric'].get('destination_workload_namespace', 'unknown_namespace')
        values = []

        for timestamp, value in series['values']:
            latency_ms = float(value)
            if not (math.isnan(latency_ms) or latency_ms == float('inf')):
                values.append({
                    "value": round(latency_ms, 1)
                })

        if values:
            results.append({
                "namespace": namespace_val,
                "service": svc,
                "values": values
            })

    return {
        "status": "success",
        "metric_type": "service_latency",
        "unit": "ms",
        "query_info": {"duration": duration, "step": step, "percentile": percentile, "rate_window": rate_window, "namespace_filter": namespace or "all_namespaces"},
        "data": results
    }

def _get_node_cpu_timeseries(duration: str, step: str) -> Dict[str, Any]:
    """CPU used by containers on each node (sum of containers), in cores."""
    client = get_prometheus_client()
    now = datetime.now(timezone.utc)
    duration_seconds = parse_duration(duration)
    start_ts = (now - timedelta(seconds=duration_seconds)).timestamp()
    end_ts = now.timestamp()

    base_selector = 'image!="", container!="POD"'
    query = (
        f'sum by (node) (\n\n  rate(container_cpu_usage_seconds_total{{{base_selector}}}[2m])\n\n)'
    )
    data = client.query_range(query, start_ts, end_ts, step)

    if not data or data.get('status') != 'success':
        return {"error": "Failed to query node CPU time series", "data": []}

    results = []
    for series in data['data']['result']:
        node_label = series['metric'].get('node') or series['metric'].get('instance', 'unknown_instance').split(':')[0]
        values = []
        for timestamp, value in series['values']:
            values.append({
                "value": round(float(value), 3)
            })

        results.append({
            "node": node_label,
            "values": values
        })

    return {
        "status": "success",
        "metric_type": "node_cpu",
        "unit": "cores",
        "query_info": {"duration": duration, "step": step, "rate_window": "2m"},
        "data": results
    }

def _get_node_core_cpu_timeseries(duration: str, step: str) -> Dict[str, Any]:
    """Total node CPU usage (non-idle) in cores."""
    client = get_prometheus_client()
    now = datetime.now(timezone.utc)
    duration_seconds = parse_duration(duration)
    start_ts = (now - timedelta(seconds=duration_seconds)).timestamp()
    end_ts = now.timestamp()

    query = (
        'label_replace(\n\n  sum by (instance) (irate(node_cpu_seconds_total{mode!="idle"}[1m])),\n\n  "internal_ip", "$1", "instance", "^([^:]+):.*$"\n\n)\n\n* on (internal_ip) group_left (node)\n\nkube_node_info'
    )
    data = client.query_range(query, start_ts, end_ts, step)

    if not data or data.get('status') != 'success':
        return {"error": "Failed to query total node CPU time series", "data": []}

    results = []
    for series in data['data']['result']:
        node_label = series['metric'].get('node') or series['metric'].get('instance', 'unknown_instance').split(':')[0]
        values = []
        for timestamp, value in series['values']:
            values.append({
                "value": round(float(value), 3)
            })

        results.append({
            "node": node_label,
            "values": values
        })

    return {
        "status": "success",
        "metric_type": "node_cpu",
        "unit": "cores",
        "query_info": {"duration": duration, "step": step, "rate_window": "1m"},
        "data": results
    }

def _get_node_memory_timeseries(duration: str, step: str) -> Dict[str, Any]:
    """Node memory used (bytes)."""
    client = get_prometheus_client()
    now = datetime.now(timezone.utc)
    duration_seconds = parse_duration(duration)
    start_ts = (now - timedelta(seconds=duration_seconds)).timestamp()
    end_ts = now.timestamp()

    query = (
        '(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)\n\n* on (instance) group_left (nodename)\n\nnode_uname_info'
    )
    data = client.query_range(query, start_ts, end_ts, step)
    
    if not data or data.get('status') != 'success':
        return {"error": "Failed to query node memory time series", "data": []}
    
    results = []
    for series in data['data']['result']:
        node_label = series['metric'].get('nodename') or series['metric'].get('node') or series['metric'].get('instance', 'unknown_instance').split(':')[0]
        values = []
        for timestamp, value in series['values']:
            memory_bytes = float(value)
            values.append({
                "value": round(memory_bytes, 1)
            })
        
        results.append({
            "node": node_label,
            "values": values
        })
    
    return {
        "status": "success",
        "metric_type": "node_memory",
        "unit": "bytes",
        "query_info": {"duration": duration, "step": step},
        "data": results
    }

# --- Tools Definition ---

@tool(description="Get pod/service timeseries metrics from Prometheus.")
def prometheus_get_timeseries(metric_type: Literal["cpu", "memory", "latency"], namespace: str, duration: str = "5m") -> Dict[str, Any]:
    """Query Prometheus for pod/service timeseries (cpu|memory|latency)."""
    requested_duration = _clamp_duration(duration, min_s=60, max_s=600)
    
    # Apply warmup cutoff by shortening query duration only when valid
    now = datetime.now(timezone.utc)
    effective_duration = requested_duration
    try:
        total_seconds = parse_duration(requested_duration)
        if _WARMUP_END_TS_UTC is not None and _WARMUP_END_TS_UTC <= now:
            window_start_ts = now.timestamp() - total_seconds
            cutoff_ts = _WARMUP_END_TS_UTC.timestamp()
            effective_start_ts = max(window_start_ts, cutoff_ts)
            effective_seconds = int(now.timestamp() - effective_start_ts)
            if effective_seconds >= 60:
                effective_duration = f"{effective_seconds}s"
    except Exception:
        effective_duration = requested_duration
        
    step = _compute_step(effective_duration)
    rate_window = "30s"
    
    try:
        start_iso, end_iso = _window_bounds(effective_duration)
        if metric_type == "cpu":
            result = _get_pod_cpu_timeseries(effective_duration, step, namespace, rate_window=rate_window)
        elif metric_type == "memory":
            result = _get_pod_memory_timeseries(effective_duration, step, namespace)
        elif metric_type == "latency":
            result = _get_istio_latency_timeseries(effective_duration, step, namespace, percentile="0.95", rate_window=rate_window)
        else:
            return {"error": f"Unsupported metric type: {metric_type}. Use 'cpu', 'memory', or 'latency'"}
        
        if result.get("error"):
            return result
        
        base = _format_timeseries_output(result, metric_type, effective_duration)
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
    requested_duration = _clamp_duration(duration, min_s=60, max_s=600)
    now = datetime.now(timezone.utc)
    effective_duration = requested_duration
    try:
        total_seconds = parse_duration(requested_duration)
        if _WARMUP_END_TS_UTC is not None and _WARMUP_END_TS_UTC <= now:
            window_start_ts = now.timestamp() - total_seconds
            cutoff_ts = _WARMUP_END_TS_UTC.timestamp()
            effective_start_ts = max(window_start_ts, cutoff_ts)
            effective_seconds = int(now.timestamp() - effective_start_ts)
            if effective_seconds >= 60:
                effective_duration = f"{effective_seconds}s"
    except Exception:
        effective_duration = requested_duration
    step = _compute_step(effective_duration)
    try:
        start_iso, end_iso = _window_bounds(effective_duration)
        if metric_type == "cpu":
            container_result = _get_node_cpu_timeseries(effective_duration, step)
            node_result = _get_node_core_cpu_timeseries(effective_duration, step)
            if container_result.get("error") and node_result.get("error"):
                return {"error": "Failed to get both container and node CPU metrics"}
            container_formatted = _format_node_timeseries_output(container_result, metric_type, effective_duration) if not container_result.get("error") else {}
            node_formatted = _format_node_timeseries_output(node_result, metric_type, effective_duration) if not node_result.get("error") else {}
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
            result = _get_node_memory_timeseries(effective_duration, step)
            if result.get("error"):
                return result
            base = _format_node_timeseries_output(result, metric_type, effective_duration)
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
    client = get_prometheus_client()
    
    if namespace:
        selector = f'reporter="destination", destination_workload_namespace="{namespace}"'
    else:
        selector = 'reporter="destination"'

    query = f'sum by (source_workload, destination_workload, source_workload_namespace, destination_workload_namespace) (rate(istio_requests_total{{{selector}}}[{time_window}]))'
    data = client.query(query)
    
    if not data or data.get('status') != 'success':
        return {"error": "Failed to query service topology", "data": {}}
    
    services = set()
    relationships = []
    
    if data and data.get('status') == 'success' and data['data']['result']:
        for item in data['data']['result']:
            source = item['metric'].get('source_workload', 'unknown')
            dest = item['metric'].get('destination_workload', 'unknown')
            source_ns = item['metric'].get('source_workload_namespace', 'unknown')
            dest_ns = item['metric'].get('destination_workload_namespace', 'unknown')
            request_rate = round(float(item['value'][1]), 1)

            if source == 'unknown' or dest == 'unknown' or not source or not dest:
                continue

            services.add(source)
            services.add(dest)

            relationships.append({
                "source": source,
                "destination": dest,
                "source_namespace": source_ns,
                "destination_namespace": dest_ns,
                "request_rate_per_second": request_rate
            })
    else:
        query2 = f'sum by (source_canonical_service, destination_canonical_service, source_workload_namespace, destination_workload_namespace) (rate(istio_requests_total{{{selector}}}[{time_window}]))'
        data2 = client.query(query2)
        if data2 and data2.get('status') == 'success' and data2['data']['result']:
            for item in data2['data']['result']:
                source = item['metric'].get('source_canonical_service', 'unknown')
                dest = item['metric'].get('destination_canonical_service', 'unknown')
                source_ns = item['metric'].get('source_workload_namespace', 'unknown')
                dest_ns = item['metric'].get('destination_workload_namespace', 'unknown')
                request_rate = round(float(item['value'][1]), 1)

                if source == 'unknown' or dest == 'unknown' or not source or not dest:
                    continue

                services.add(source)
                services.add(dest)

                relationships.append({
                    "source": source,
                    "destination": dest,
                    "source_namespace": source_ns,
                    "destination_namespace": dest_ns,
                    "request_rate_per_second": request_rate
                })
    
    incoming_connections: Dict[str, Any] = {}
    outgoing_connections: Dict[str, Any] = {}
    
    for rel in relationships:
        dest = rel["destination"]
        source = rel["source"]
        if dest not in incoming_connections:
            incoming_connections[dest] = []
        incoming_connections[dest].append({"from": source, "rate": rel["request_rate_per_second"]})
        if source not in outgoing_connections:
            outgoing_connections[source] = []
        outgoing_connections[source].append({"to": dest, "rate": rel["request_rate_per_second"]})
    
    critical_services = []
    for service, connections in incoming_connections.items():
        if len(connections) > 1:
            total_rate = sum(conn["rate"] for conn in connections)
            critical_services.append({
                "service": service,
                "dependent_services": [conn["from"] for conn in connections],
                "total_incoming_rate": total_rate,
                "criticality_score": len(connections) * total_rate
            })
    critical_services.sort(key=lambda x: x["criticality_score"], reverse=True)
    services.discard('unknown')

    return {
        "status": "success",
        "metric_type": "service_topology",
        "unit": "requests_per_second",
        "query_info": {"time_window": time_window, "namespace_filter": namespace or "all_namespaces"},
        "topology": {
            "services": sorted(list(services)),
            "relationships": relationships,
            "critical_services": critical_services[:5],
            "incoming_connections": incoming_connections,
            "outgoing_connections": outgoing_connections
        }
    }

