import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Callable
from langchain.tools import tool

from kub_mitigation_agent.clients.prometheus import get_prometheus_client, parse_duration

logger = logging.getLogger(__name__)

# Global state for warmup cutoff
_WARMUP_END_TS_UTC: Optional[datetime] = None

def set_warmup_end_timestamp(timestamp_iso: Optional[str]) -> None:
    """Set or clear the warmup end timestamp (UTC) used by metrics tools."""
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
        pass

# --- Shared Helpers ---

def _parse_duration_safe(duration: str) -> int:
    try:
        return parse_duration(duration)
    except Exception:
        return 300

def _compute_step(duration_str: str) -> str:
    """Compute a reasonable Prometheus step for a given duration."""
    total_seconds = _parse_duration_safe(duration_str)
    target = max(total_seconds // 10, 1)
    nice_steps = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800, 3600]
    chosen = next((s for s in nice_steps if s >= target), nice_steps[-1])
    return f"{chosen}s"

def _prepare_query_context(duration: str, min_s: int = 60, max_s: int = 600) -> Tuple[str, str, float, float, str, str]:
    """
    Prepare query parameters including duration clamping, warmup handling, and timestamps.
    Returns: (effective_duration, step, start_ts, end_ts, start_iso, end_iso)
    """
    # 1. Clamp duration
    try:
        secs = parse_duration(duration)
        if secs < min_s: secs = min_s
        if secs > max_s: secs = max_s
    except Exception:
        secs = 300
    
    effective_duration_str = f"{secs}s"
    
    # 2. Apply warmup cutoff
    now = datetime.now(timezone.utc)
    if _WARMUP_END_TS_UTC and _WARMUP_END_TS_UTC <= now:
        window_start_ts = now.timestamp() - secs
        cutoff_ts = _WARMUP_END_TS_UTC.timestamp()
        effective_start_ts = max(window_start_ts, cutoff_ts)
        effective_secs = int(now.timestamp() - effective_start_ts)
        if effective_secs >= 60:
            secs = effective_secs
            effective_duration_str = f"{secs}s"

    # 3. Calculate bounds
    step = _compute_step(effective_duration_str)
    end_dt = now
    start_dt = end_dt - timedelta(seconds=secs)
    
    return (
        effective_duration_str,
        step,
        start_dt.timestamp(),
        end_dt.timestamp(),
        start_dt.isoformat(),
        end_dt.isoformat()
    )

def _run_prom_query_range(query: str, start_ts: float, end_ts: float, step: str) -> List[Dict[str, Any]]:
    """Execute a generic Prometheus range query."""
    client = get_prometheus_client()
    data = client.query_range(query, start_ts, end_ts, step)
    if not data or data.get('status') != 'success':
        return []
    return data.get('data', {}).get('result', [])

def _extract_series_values(
    series_list: List[Dict[str, Any]], 
    label_key: str, 
    value_map: Callable[[float], float],
    label_fallback_key: Optional[str] = None
) -> Dict[str, List[float]]:
    """Parse Prometheus result list into a simple dict of {label: [values]}."""
    output = {}
    for item in series_list:
        metric = item.get('metric', {})
        label = metric.get(label_key)
        if not label and label_fallback_key:
            label = metric.get(label_fallback_key)
        if not label:
            # Try specific node fallbacks or generic unknown
            label = metric.get('instance', 'unknown').split(':')[0]
            
        values = []
        for _, val in item.get('values', []):
            try:
                values.append(value_map(float(val)))
            except (ValueError, TypeError):
                pass
        if values:
            output[label] = values
    return output

def _build_response(
    metric_type: str,
    unit: str,
    duration: str,
    step: str,
    start_iso: str,
    end_iso: str,
    values: Dict[str, Any],
    extra_fields: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Standardize tool output."""
    res = {
        "status": "success",
        "metric_type": metric_type,
        "unit": unit,
        "duration": duration,
        "step": step,
        "start": start_iso,
        "end": end_iso,
        "values": values,
    }
    if not values:
        res["summary"] = "No data available"
    if extra_fields:
        res.update(extra_fields)
    return res

# --- Tools ---

@tool(description="Get pod CPU usage timeseries (millicores).")
def prometheus_get_pod_cpu_timeseries(namespace: str, duration: str = "5m") -> Dict[str, Any]:
    """Query Prometheus for pod CPU usage in millicores."""
    try:
        dur_str, step, start_ts, end_ts, start_iso, end_iso = _prepare_query_context(duration)
        
        selector = f'image!="", container!="POD", namespace="{namespace}"'
        query = f'sum by (pod) (rate(container_cpu_usage_seconds_total{{{selector}}}[1m]))'
        
        results = _run_prom_query_range(query, start_ts, end_ts, step)
        values = _extract_series_values(results, 'pod', lambda v: round(v * 1000, 1))
        
        return _build_response("pod_cpu", "millicores", dur_str, step, start_iso, end_iso, values)
    except Exception as e:
        return {"error": f"Failed to get pod CPU: {str(e)}"}

@tool(description="Get pod memory usage timeseries (MiB).")
def prometheus_get_pod_memory_timeseries(namespace: str, duration: str = "5m") -> Dict[str, Any]:
    """Query Prometheus for pod memory working set in MiB."""
    try:
        dur_str, step, start_ts, end_ts, start_iso, end_iso = _prepare_query_context(duration)
        
        selector = f'image!="", container!="POD", namespace="{namespace}"'
        query = f'sum by (pod) (container_memory_working_set_bytes{{{selector}}})'
        
        results = _run_prom_query_range(query, start_ts, end_ts, step)
        values = _extract_series_values(results, 'pod', lambda v: round(v / 1048576, 1))
        
        return _build_response("pod_memory", "MiB", dur_str, step, start_iso, end_iso, values)
    except Exception as e:
        return {"error": f"Failed to get pod memory: {str(e)}"}

@tool(description="Get service latency timeseries (ms).")
def prometheus_get_service_latency_timeseries(namespace: str, duration: str = "5m", percentile: str = "0.95") -> Dict[str, Any]:
    """Query Istio request duration (latency) in milliseconds."""
    try:
        dur_str, step, start_ts, end_ts, start_iso, end_iso = _prepare_query_context(duration)
        
        # Use destination_workload for service grouping
        selector = f'reporter="destination", destination_workload_namespace="{namespace}"'
        # Guard against injection in percentile, though unlikely given type
        p = percentile if percentile.replace('.', '', 1).isdigit() else "0.95"
        
        query = (
            f'histogram_quantile({p}, '
            f'sum(rate(istio_request_duration_milliseconds_bucket{{{selector}}}[2m])) '
            f'by (le, destination_workload)'
            f')'
        )
        
        results = _run_prom_query_range(query, start_ts, end_ts, step)
        # Filter out NaNs and Infs
        def clean_latency(v):
            if math.isnan(v) or math.isinf(v): raise ValueError
            return round(v, 1)
            
        values = _extract_series_values(results, 'destination_workload', clean_latency)
        
        return _build_response("service_latency", "ms", dur_str, step, start_iso, end_iso, values, 
                             extra_fields={"percentile": p})
    except Exception as e:
        return {"error": f"Failed to get service latency: {str(e)}"}

@tool(description="Get node CPU timeseries (pod vs node total).")
def prometheus_get_node_cpu_timeseries(duration: str = "5m") -> Dict[str, Any]:
    """
    Returns two CPU metrics per node:
    1. pod_cpu: Aggregate usage of all pods (millicores)
    2. node_cpu: Total host CPU usage (millicores/cores)
    """
    try:
        dur_str, step, start_ts, end_ts, start_iso, end_iso = _prepare_query_context(duration)
        
        # 1. Pod CPU (sum of containers)
        query_pod = 'sum by (node) (rate(container_cpu_usage_seconds_total{image!="", container!="POD"}[2m]))'
        pod_res = _run_prom_query_range(query_pod, start_ts, end_ts, step)
        pod_values = _extract_series_values(pod_res, 'node', lambda v: round(v, 3)) # Cores
        
        # 2. Node Total CPU (host level)
        # Complex query matching internal_ip to join with kube_node_info to get node name
        query_node = (
            'label_replace(sum by (instance) (irate(node_cpu_seconds_total{mode!="idle"}[1m])), '
            '"internal_ip", "$1", "instance", "^([^:]+):.*$") '
            '* on (internal_ip) group_left (node) kube_node_info'
        )
        node_res = _run_prom_query_range(query_node, start_ts, end_ts, step)
        node_values = _extract_series_values(node_res, 'node', lambda v: round(v, 3)) # Cores
        
        if not pod_values and not node_values:
            return {"status": "success", "summary": "No data available", "duration": dur_str}

        return {
            "status": "success",
            "metric_type": "node_cpu",
            "unit": "cores",
            "duration": dur_str,
            "step": step,
            "start": start_iso,
            "end": end_iso,
            "metrics": {
                "pod_cpu": {
                    "description": "CPU consumed by pods (cores)",
                    "values": pod_values
                },
                "node_cpu": {
                    "description": "Total node CPU usage (cores)",
                    "values": node_values
                }
            }
        }
    except Exception as e:
        return {"error": f"Failed to get node CPU metrics: {str(e)}"}

@tool(description="Get node memory timeseries (pod vs node total).")
def prometheus_get_node_memory_timeseries(duration: str = "5m") -> Dict[str, Any]:
    """
    Returns two Memory metrics per node (in MiB):
    1. pod_memory: Aggregate working set of all pods
    2. node_memory: Total node memory usage (Total - Available)
    """
    try:
        dur_str, step, start_ts, end_ts, start_iso, end_iso = _prepare_query_context(duration)
        
        # 1. Pod Memory (sum of containers)
        # Summing working set bytes for all non-POD containers
        query_pod = 'sum by (node) (container_memory_working_set_bytes{image!="", container!="POD"})'
        pod_res = _run_prom_query_range(query_pod, start_ts, end_ts, step)
        pod_values = _extract_series_values(pod_res, 'node', lambda v: round(v / 1048576, 1)) # MiB
        
        # 2. Node Total Memory (host level)
        query_node = (
            '(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) '
            '* on (instance) group_left (nodename) node_uname_info'
        )
        node_res = _run_prom_query_range(query_node, start_ts, end_ts, step)
        # Prefer 'nodename', fallback to 'node' or 'instance'
        node_values = _extract_series_values(node_res, 'nodename', lambda v: round(v / 1048576, 1), label_fallback_key='node') # MiB
        
        if not pod_values and not node_values:
            return {"status": "success", "summary": "No data available", "duration": dur_str}
        
        return {
            "status": "success",
            "metric_type": "node_memory",
            "unit": "MiB",
            "duration": dur_str,
            "step": step,
            "start": start_iso,
            "end": end_iso,
            "metrics": {
                "pod_memory": {
                    "description": "Memory consumed by pods (MiB)",
                    "values": pod_values
                },
                "node_memory": {
                    "description": "Total node memory usage (MiB)",
                    "values": node_values
                }
            }
        }
    except Exception as e:
        return {"error": f"Failed to get node memory: {str(e)}"}

@tool(description="Get a service call topology snapshot from Prometheus.")
def prometheus_get_service_topology(namespace: Optional[str] = None, time_window: str = "5m") -> Dict[str, Any]:
    """Get a recent service-to-service call topology."""
    try:
        client = get_prometheus_client()
        selector = f'reporter="destination", destination_workload_namespace="{namespace}"' if namespace else 'reporter="destination"'
        
        # Try workload-level first
        query = f'sum by (source_workload, destination_workload, source_workload_namespace, destination_workload_namespace) (rate(istio_requests_total{{{selector}}}[{time_window}]))'
        data = client.query(query)
        
        # Fallback to canonical service
        if not data or data.get('status') != 'success' or not data.get('data', {}).get('result'):
             query = f'sum by (source_canonical_service, destination_canonical_service, source_workload_namespace, destination_workload_namespace) (rate(istio_requests_total{{{selector}}}[{time_window}]))'
             data = client.query(query)

        if not data or data.get('status') != 'success':
            return {"error": "Failed to query service topology", "data": {}}

        relationships = []
        
        for item in data.get('data', {}).get('result', []):
            metric = item.get('metric', {})
            src = metric.get('source_workload') or metric.get('source_canonical_service')
            dst = metric.get('destination_workload') or metric.get('destination_canonical_service')
            
            if not src or not dst or src == 'unknown' or dst == 'unknown':
                continue

            try:
                val = float(item['value'][1])
                if val > 0:
                    relationships.append({
                        "source": src,
                        "destination": dst,
                        "rate": round(val, 2)
                    })
            except (IndexError, ValueError):
                continue

        return {
            "status": "success",
            "metric_type": "service_topology",
            "query_info": {"time_window": time_window, "namespace": namespace or "all"},
            "relationships": relationships
        }
    except Exception as e:
        return {"error": f"Failed to get topology: {str(e)}"}

@tool(description="Get Istio Ingress Gateway metrics timeseries (success rate, latency, rps).")
def prometheus_get_ingress_stats(duration: str = "5m") -> Dict[str, Any]:
    """
    Get global ingress gateway statistics as timeseries:
    - Success Rate (%)
    - P95 Latency (seconds)
    - Requests Per Second (RPS)
    """
    try:
        dur_str, step, start_ts, end_ts, start_iso, end_iso = _prepare_query_context(duration)
        
        # 1. Latency P95 Timeseries
        latency_query = f'''histogram_quantile(0.95,
            sum(rate(istio_request_duration_milliseconds_bucket{{
                reporter="source",
                source_workload="istio-ingressgateway",
                source_workload_namespace="istio-system"
            }}[1m]))
            by (le)
        )'''
        
        # 2. Total Requests Rate (RPS)
        rps_query = f'''sum(rate(istio_requests_total{{
            reporter="source",
            source_workload="istio-ingressgateway",
            source_workload_namespace="istio-system"
        }}[1m]))'''
        
        # 3. Success Requests Rate (2xx/3xx)
        success_rps_query = f'''sum(rate(istio_requests_total{{
            reporter="source",
            source_workload="istio-ingressgateway",
            source_workload_namespace="istio-system",
            response_code=~"[23].*"
        }}[1m]))'''
        
        # Execute range queries
        latency_res = _run_prom_query_range(latency_query, start_ts, end_ts, step)
        rps_res = _run_prom_query_range(rps_query, start_ts, end_ts, step)
        success_res = _run_prom_query_range(success_rps_query, start_ts, end_ts, step)
        
        # Helper to extract simple [ts, val] list from single result series
        def extract_single_series(res, scale=1.0):
            if not res: return []
            values = []
            for ts, val in res[0].get('values', []):
                try:
                    v = float(val)
                    if not (math.isnan(v) or math.isinf(v)):
                        values.append(round(v * scale, 3))
                except (ValueError, TypeError):
                    pass
            return values

        # Extract raw series
        latency_values = extract_single_series(latency_res, scale=0.001) # ms -> s
        rps_values = extract_single_series(rps_res)
        success_values = extract_single_series(success_res)
        
        # Calculate Success Rate Timeseries
        # We need to align timestamps, but since they come from same step query, we can zip comfortably if lengths match.
        # If lengths differ slightly due to prom glitches, we'll truncate to shortest.
        success_rate_values = []
        min_len = min(len(rps_values), len(success_values))
        
        for i in range(min_len):
            total = rps_values[i]
            succ = success_values[i]
            rate = (succ / total * 100.0) if total > 0 else 100.0
            success_rate_values.append(round(rate, 1))

        return {
            "status": "success",
            "metric_type": "ingress_stats",
            "duration": dur_str,
            "step": step,
            "start": start_iso,
            "end": end_iso,
            "metrics": {
                "p95_latency_seconds": latency_values,
                "requests_per_second": rps_values,
                "success_rate_percent": success_rate_values
            }
        }

    except Exception as e:
        return {"error": f"Failed to get ingress stats: {str(e)}"}
