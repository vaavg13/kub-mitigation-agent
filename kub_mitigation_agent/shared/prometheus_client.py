from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

def format_timestamp(unix_timestamp: float) -> Dict[str, Any]:
    """Convert Unix timestamp to human-readable format for LLM consumption."""
    dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    return {
        "unix": int(unix_timestamp),
        "datetime": dt.isoformat(),
        "human_readable": dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    }

# Hardcoded node-to-cpuset mapping for k3d cluster
# Maps k3d agent index to node name and assigned CPU cores
NODE_CPUSET_MAP = {
    0: {'name': 'cloud-node-0', 'k8s_name': 'k3d-cec-emulator-agent-0', 'cpuset': '16,40,17,41', 'cpu_regex': '16|40|17|41'},
    1: {'name': 'cloud-node-1', 'k8s_name': 'k3d-cec-emulator-agent-1', 'cpuset': '18,42,19,43', 'cpu_regex': '18|42|19|43'},
    2: {'name': 'edge-node-0-site-1', 'k8s_name': 'k3d-cec-emulator-agent-2', 'cpuset': '20,44', 'cpu_regex': '20|44'},
    3: {'name': 'edge-node-1-site-1', 'k8s_name': 'k3d-cec-emulator-agent-3', 'cpuset': '21,45', 'cpu_regex': '21|45'},
    4: {'name': 'edge-node-0-site-2', 'k8s_name': 'k3d-cec-emulator-agent-4', 'cpuset': '22,46', 'cpu_regex': '22|46'},
    5: {'name': 'edge-node-1-site-2', 'k8s_name': 'k3d-cec-emulator-agent-5', 'cpuset': '23,47', 'cpu_regex': '23|47'},
}

def _get_node_ip_mapping():
    """Get mapping of node IPs to friendly node names from Kubernetes."""
    try:
        import subprocess
        result = subprocess.run(
            ['kubectl', 'get', 'nodes', '-o', 'jsonpath={range .items[*]}{.metadata.name}{"\\t"}{.status.addresses[?(@.type=="InternalIP")].address}{"\\n"}{end}'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            ip_map = {}
            for line in result.stdout.strip().split('\n'):
                if '\t' in line:
                    k8s_name, ip = line.strip().split('\t')
                    # Find corresponding friendly name
                    for node_info in NODE_CPUSET_MAP.values():
                        if node_info['k8s_name'] == k8s_name:
                            ip_map[ip] = node_info['name']
                            break
            return ip_map
    except Exception:
        pass
    return {}

class PrometheusMetricsTool:
    """
    Tool for getting current Prometheus metrics.
    """
    
    def __init__(self, prometheus_url="http://localhost:9090"):
        """Initialize the Prometheus metrics tool."""
        # Minimal internal Prometheus client (no CSV/export functionality)
        self.prometheus_url = prometheus_url
        if not self.prometheus_url.startswith(("http://", "https://")):
            self.prometheus_url = "http://" + self.prometheus_url

    def _query_prometheus(self, query: str):
        """Execute an instant Prometheus query and return JSON or None on error."""
        try:
            import requests
            full_url = f"{self.prometheus_url}/api/v1/query"
            response = requests.get(full_url, params={"query": query}, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None
    
    def _parse_duration_to_seconds(self, duration: str) -> int:
        """Parse duration string (e.g., '1h', '30m', '5s') to seconds."""
        duration = duration.lower().strip()
        
        if duration.endswith('s'):
            return int(duration[:-1])
        elif duration.endswith('m'):
            return int(duration[:-1]) * 60
        elif duration.endswith('h'):
            return int(duration[:-1]) * 3600
        elif duration.endswith('d'):
            return int(duration[:-1]) * 86400
        else:
            # Assume seconds if no unit
            return int(duration)
    
    def _query_prometheus_range(self, query: str, duration: str, step: str) -> Dict[str, Any]:
        """Query Prometheus for range data over a time period."""
        import requests
        
        now = datetime.now(timezone.utc)
        duration_seconds = self._parse_duration_to_seconds(duration)
        start_time = now - timedelta(seconds=duration_seconds)
        
        params = {
            'query': query,
            'start': start_time.timestamp(),
            'end': now.timestamp(),
            'step': step
        }
        
        try:
            response = requests.get(f"{self.prometheus_url}/api/v1/query_range", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def get_node_cpu_timeseries(self, duration: str = "10m", step: str = "1m", rate_window: str = "1m") -> Dict[str, Any]:
        """Get historical CPU usage time series for all nodes."""
        base_selector = 'image!="", container!="POD"'
        query = f'sum by (instance) (rate(container_cpu_usage_seconds_total{{{base_selector}}}[{rate_window}]))'
        data = self._query_prometheus_range(query, duration, step)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query node CPU time series", "data": []}
        
        results = []
        for series in data['data']['result']:
            node_id = series['metric'].get('instance', 'unknown_instance').split(':')[0]
            values = []
            for timestamp, value in series['values']:
                values.append({
                    "value": round(float(value) * 1000, 1)
                })
            
            results.append({
                "node": node_id,
                "values": values
            })
        
        return {
            "status": "success",
            "metric_type": "node_cpu",
            "unit": "millicores",
            "query_info": {"duration": duration, "step": step, "rate_window": rate_window},
            "data": results
        }
    
    def get_node_memory_timeseries(self, duration: str = "10m", step: str = "1m") -> Dict[str, Any]:
        """Get historical memory usage time series for all nodes."""
        base_selector = 'image!="", container!="POD"'
        query = f'sum by (instance) (container_memory_working_set_bytes{{{base_selector}}})'
        data = self._query_prometheus_range(query, duration, step)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query node memory time series", "data": []}
        
        results = []
        for series in data['data']['result']:
            node_id = series['metric'].get('instance', 'unknown_instance').split(':')[0]
            values = []
            for timestamp, value in series['values']:
                memory_bytes = int(float(value))
                memory_mib = round(memory_bytes / (1024 * 1024), 1)
                values.append({
                    "value": memory_mib
                })
            
            results.append({
                "node": node_id,
                "values": values
            })
        
        return {
            "status": "success",
            "metric_type": "node_memory",
            "unit": "MiB",
            "query_info": {"duration": duration, "step": step},
            "data": results
        }
    
    def get_node_core_cpu_timeseries(self, duration: str = "10m", step: str = "1m", rate_window: str = "1m") -> Dict[str, Any]:
        """Get per-node CPU usage based on assigned CPU cores (represents physical node CPU)."""
        # Ensure rate_window is at least 1m for range queries to work properly
        try:
            rate_seconds = self._parse_duration_to_seconds(rate_window)
            if rate_seconds < 60:
                rate_window = "1m"
        except Exception:
            rate_window = "1m"
        
        results = []
        ip_map = _get_node_ip_mapping()
        friendly_to_ip = {friendly: ip for ip, friendly in ip_map.items()}
        
        # Query each node's CPU cores separately
        for agent_idx, node_info in NODE_CPUSET_MAP.items():
            cpu_regex = node_info['cpu_regex']
            node_name = node_info['name']
            node_ip = friendly_to_ip.get(node_name)
            if not node_ip:
                # Fallback to k8s node name (may still be useful for consumers)
                node_ip = node_info.get('k8s_name', node_name)
            
            # Query: 1 - avg(rate(node_cpu_seconds_total{mode="idle",cpu=~"16|17|40|41"}[1m]))
            query = f'1 - avg(rate(node_cpu_seconds_total{{mode="idle",cpu=~"{cpu_regex}"}}[{rate_window}]))'
            data = self._query_prometheus_range(query, duration, step)
            
            if not data or data.get('status') != 'success':
                continue
            
            # Extract time series values
            if data['data']['result']:
                series = data['data']['result'][0]  # Should be single result (avg across cores)
                values = []
                for timestamp, value in series['values']:
                    # Convert to millicores (1 core = 1000 millicores)
                    # Value is 0-1 representing utilization, multiply by number of cores
                    num_cores = len(node_info['cpuset'].split(','))
                    millicores = round(float(value) * num_cores * 1000, 1)
                    values.append({
                        "value": millicores
                    })
                
                results.append({
                    "node": node_ip,
                    "values": values
                })
        
        return {
            "status": "success",
            "metric_type": "node_cpu",
            "unit": "millicores",
            "query_info": {"duration": duration, "step": step, "rate_window": rate_window},
            "data": results
        }
    
    def get_pod_cpu_timeseries(self, duration: str = "10m", step: str = "1m", namespace: Optional[str] = None, rate_window: str = "1m") -> Dict[str, Any]:
        """Get historical CPU usage time series for pods."""
        # Build namespace filter
        base_selector = 'image!="", container!="POD"'
        if namespace:
            namespace_filter = f'namespace="{namespace}"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = base_selector
        
        query = f'sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{{{full_selector}}}[{rate_window}]))'
        data = self._query_prometheus_range(query, duration, step)
        
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
    
    def get_pod_memory_timeseries(self, duration: str = "10m", step: str = "1m", namespace: Optional[str] = None) -> Dict[str, Any]:
        """Get historical memory usage time series for pods."""
        # Build namespace filter
        base_selector = 'image!="", container!="POD"'
        if namespace:
            namespace_filter = f'namespace="{namespace}"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = base_selector
        
        query = f'sum by (namespace, pod) (container_memory_working_set_bytes{{{full_selector}}})'
        data = self._query_prometheus_range(query, duration, step)
        
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
    
    def get_istio_latency_timeseries(self, duration: str = "10m", step: str = "1m", namespace: Optional[str] = None, percentile: str = "0.95", rate_window: str = "2m") -> Dict[str, Any]:
        """Get historical Istio latency time series for services."""
        import math

        if namespace:
            selector = f'reporter="destination", destination_workload_namespace="{namespace}"'
        else:
            selector = 'reporter="destination"'

        query = f'''histogram_quantile({percentile},
            sum(rate(istio_request_duration_milliseconds_bucket{{{selector}}}[{rate_window}]))
            by (le, destination_workload, destination_workload_namespace)
        )'''
        data = self._query_prometheus_range(query, duration, step)

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
    
    def get_service_topology(self, namespace: Optional[str] = None, time_window: str = "5m") -> Dict[str, Any]:
        """Get service topology and communication patterns from Istio metrics."""
        if namespace:
            selector = f'reporter="destination", destination_workload_namespace="{namespace}"'
        else:
            selector = 'reporter="destination"'

        # Prefer workload-level topology
        query = f'sum by (source_workload, destination_workload, source_workload_namespace, destination_workload_namespace) (rate(istio_requests_total{{{selector}}}[{time_window}]))'
        data = self._query_prometheus(query)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query service topology", "data": {}}
        
        # Extract topology information
        services = set()
        relationships = []
        
        if data and data.get('status') == 'success' and data['data']['result']:
            for item in data['data']['result']:
                source = item['metric'].get('source_workload', 'unknown')
                dest = item['metric'].get('destination_workload', 'unknown')
                source_ns = item['metric'].get('source_workload_namespace', 'unknown')
                dest_ns = item['metric'].get('destination_workload_namespace', 'unknown')
                request_rate = round(float(item['value'][1]), 1)

                # Skip unknown endpoints (typically external HTTP traffic)
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
            # Fallback to canonical services
            query2 = f'sum by (source_canonical_service, destination_canonical_service, source_workload_namespace, destination_workload_namespace) (rate(istio_requests_total{{{selector}}}[{time_window}]))'
            data2 = self._query_prometheus(query2)
            if data2 and data2.get('status') == 'success' and data2['data']['result']:
                for item in data2['data']['result']:
                    source = item['metric'].get('source_canonical_service', 'unknown')
                    dest = item['metric'].get('destination_canonical_service', 'unknown')
                    source_ns = item['metric'].get('source_workload_namespace', 'unknown')
                    dest_ns = item['metric'].get('destination_workload_namespace', 'unknown')
                    request_rate = round(float(item['value'][1]), 1)

                    # Skip unknown endpoints
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

                    
        
        # Analyze service criticality (services with most incoming connections)
        incoming_connections = {}
        outgoing_connections = {}
        
        for rel in relationships:
            dest = rel["destination"]
            source = rel["source"]
            
            if dest not in incoming_connections:
                incoming_connections[dest] = []
            incoming_connections[dest].append({
                "from": source,
                "rate": rel["request_rate_per_second"]
            })
            
            if source not in outgoing_connections:
                outgoing_connections[source] = []
            outgoing_connections[source].append({
                "to": dest,
                "rate": rel["request_rate_per_second"]
            })
        
        # Identify critical services (high fan-in = many services depend on them)
        critical_services = []
        for service, connections in incoming_connections.items():
            if len(connections) > 1:  # Multiple services depend on this one
                total_rate = sum(conn["rate"] for conn in connections)
                critical_services.append({
                    "service": service,
                    "dependent_services": [conn["from"] for conn in connections],
                    "total_incoming_rate": total_rate,
                    "criticality_score": len(connections) * total_rate
                })
        
        # Sort by criticality
        critical_services.sort(key=lambda x: x["criticality_score"], reverse=True)
        
        # Ensure 'unknown' isn't included in services set in any case
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

# Global instance to be used by agent
_prometheus_tool = None

def get_prometheus_tool(prometheus_url="http://localhost:9090") -> PrometheusMetricsTool:
    """Get or create global PrometheusMetricsTool instance."""
    global _prometheus_tool
    if _prometheus_tool is None:
        _prometheus_tool = PrometheusMetricsTool(prometheus_url)
    return _prometheus_tool

def prometheus_get_timeseries(metric_type: str, namespace: str, duration: str = "10m") -> Dict[str, Any]:
    """
    Get historical time series for pods/services with optimized settings.
    Fixed 5s intervals, 10m max duration, concise output format.
    
    Args:
        metric_type: Type of metric ("cpu", "memory", "latency")
        namespace: Target namespace to filter metrics
        duration: Time range (max 10m)
    """
    tool = get_prometheus_tool()
    
    # Normalize duration: enforce minimum 1m and maximum 10m
    try:
        duration_seconds = tool._parse_duration_to_seconds(duration)
        if duration_seconds < 60:
            duration = "1m"
        elif duration_seconds > 600:
            duration = "10m"
    except Exception:
        duration = "1m"

    # Compute dynamic step targeting ~10 samples
    def _compute_step(dur: str) -> str:
        tool_local = get_prometheus_tool()
        total_seconds = tool_local._parse_duration_to_seconds(dur)
        target = max(total_seconds // 10, 1)
        nice_steps = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800, 3600]
        chosen = next((s for s in nice_steps if s >= target), nice_steps[-1])
        return f"{chosen}s"

    step = _compute_step(duration)
    rate_window = "30s"  # Consistent aggregation window for pod-level CPU and latency
    
    try:
        # Compute window timestamps for comparability
        end_dt = datetime.now(timezone.utc)
        duration_seconds_norm = tool._parse_duration_to_seconds(duration)
        start_dt = end_dt - timedelta(seconds=duration_seconds_norm)
        if metric_type == "cpu":
            result = tool.get_pod_cpu_timeseries(duration, step, namespace, rate_window=rate_window)
        elif metric_type == "memory":
            result = tool.get_pod_memory_timeseries(duration, step, namespace)
        elif metric_type == "latency":
            result = tool.get_istio_latency_timeseries(duration, step, namespace, percentile="0.95", rate_window=rate_window)
        else:
            return {"error": f"Unsupported metric type: {metric_type}. Use 'cpu', 'memory', or 'latency'"}
        
        # Check if there's an error in the result first
        if result.get("error"):
            return result
        
        # Format for minimal token usage
        base = _format_timeseries_output(result, metric_type, duration)
        # Reconstruct to ensure ordering and ISO-only timestamps
        output = {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "status": base.get("status"),
            "metric_type": base.get("metric_type"),
            "unit": base.get("unit"),
            "duration": base.get("duration"),
            "step": base.get("step"),
            "values": base.get("values", {})
        }
        if "summary" in base:
            output["summary"] = base["summary"]
        return output
        
    except Exception as e:
        return {"error": f"Failed to get {metric_type} timeseries: {str(e)}"}

def prometheus_get_node_timeseries(metric_type: str, duration: str = "10m") -> Dict[str, Any]:
    """
    Get historical node-level metrics with optimized settings.
    Returns both container-level and node-level CPU metrics for complete visibility.
    
    Args:
        metric_type: Type of metric ("cpu", "memory")
        duration: Time range (max 10m)
    
    Returns:
        For CPU: Both pod-level and node-level metrics
        For memory: Node-level metrics only
    """
    tool = get_prometheus_tool()
    
    # Normalize duration: enforce minimum 1m and maximum 10m
    try:
        duration_seconds = tool._parse_duration_to_seconds(duration)
        if duration_seconds < 60:
            duration = "1m"
        elif duration_seconds > 600:
            duration = "10m"
    except Exception:
        duration = "1m"

    # Compute dynamic step targeting ~10 samples
    def _compute_step(dur: str) -> str:
        tool_local = get_prometheus_tool()
        total_seconds = tool_local._parse_duration_to_seconds(dur)
        target = max(total_seconds // 10, 1)
        nice_steps = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800, 3600]
        chosen = next((s for s in nice_steps if s >= target), nice_steps[-1])
        return f"{chosen}s"

    step = _compute_step(duration)
    
    try:
        # Compute window timestamps for comparability
        end_dt = datetime.now(timezone.utc)
        duration_seconds_norm = tool._parse_duration_to_seconds(duration)
        start_dt = end_dt - timedelta(seconds=duration_seconds_norm)
        
        if metric_type == "cpu":
            # Get both metrics for CPU
            # 1. Container metrics (pod CPU usage)
            container_result = tool.get_node_cpu_timeseries(duration, step, rate_window="30s")
            # 2. Node-level metrics (physical node CPU from per-core measurements)
            node_result = tool.get_node_core_cpu_timeseries(duration, step, rate_window="1m")
            
            # Check for errors
            if container_result.get("error") and node_result.get("error"):
                return {"error": "Failed to get both container and node CPU metrics"}
            
            # Format both results
            container_formatted = _format_node_timeseries_output(container_result, metric_type, duration) if not container_result.get("error") else {}
            node_formatted = _format_node_timeseries_output(node_result, metric_type, duration) if not node_result.get("error") else {}
            
            output = {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "status": "success",
                "metric_type": "node_cpu",
                "unit": "millicores",
                "duration": duration,
                "step": step,
                "metrics": {
                    "pod_cpu": {
                        "description": "CPU consumed by pods running on each node (workload only)",
                        "values": container_formatted.get("values", {})
                    },
                    "node_cpu": {
                        "description": "Total node CPU usage (represents physical machine CPU utilization)",
                        "values": node_formatted.get("values", {})
                    }
                }
            }
            return output
            
        elif metric_type == "memory":
            result = tool.get_node_memory_timeseries(duration, step)
            
            # Check if there's an error in the result first
            if result.get("error"):
                return result
            
            # Format for minimal token usage
            base = _format_node_timeseries_output(result, metric_type, duration)
            output = {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "status": base.get("status"),
                "metric_type": base.get("metric_type"),
                "unit": base.get("unit"),
                "duration": base.get("duration"),
                "step": base.get("step"),
                "values": base.get("values", {})
            }
            if "summary" in base:
                output["summary"] = base["summary"]
            return output
        else:
            return {"error": f"Unsupported node metric type: {metric_type}. Use 'cpu' or 'memory'"}
        
    except Exception as e:
        return {"error": f"Failed to get node {metric_type} timeseries: {str(e)}"}

def _format_timeseries_output(result: Dict[str, Any], metric_type: str, duration: str) -> Dict[str, Any]:
    """Format timeseries output to show actual values for each pod."""
    # Handle errors first
    if result.get("error"):
        return result
    
    # Check if we have data
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
            "summary": "No data available"
        }
    
    try:
        # Get step from query_info if available
        step = result.get("query_info", {}).get("step", "5s")
        
        # Create pod timeseries data
        pod_data = {}
        
        for item in result["data"]:
            pod_name = item.get("pod") or item.get("service", "unknown")
            values = item.get("values", [])
            
            if not values:
                continue
                
            # Extract the actual metric values (now all use "value" field)
            try:
                metric_values = [round(v.get("value", 0), 1) for v in values]
                pod_data[pod_name] = metric_values
                
            except Exception as e:
                # Skip this pod/service if there's an error processing it
                continue
        
        # Get unit from original result
        unit = result.get("unit", unit_map.get(metric_type, "unknown"))
        
        return {
            "status": "success",
            "metric_type": metric_type_map.get(metric_type, metric_type),
            "unit": unit,
            "duration": duration,
            "step": step,
            "values": pod_data
        }
        
    except Exception as e:
        return {
            "error": f"Failed to format {metric_type} output: {str(e)}",
            "raw_result": result
        }

def _format_node_timeseries_output(result: Dict[str, Any], metric_type: str, duration: str) -> Dict[str, Any]:
    """Format node timeseries output to show actual values for each node."""
    # Handle errors first
    if result.get("error"):
        return result
    
    # Check if we have data
    unit_map = {"cpu": "millicores", "memory": "MiB"}
    metric_type_map = {"cpu": "node_cpu", "memory": "node_memory"}
    
    # Handle special case for node_core_cpu metric type
    actual_metric_type = result.get("metric_type", metric_type_map.get(metric_type, f"node_{metric_type}"))
    
    if not result.get("data"):
        return {
            "status": "success",
            "metric_type": actual_metric_type,
            "unit": result.get("unit", unit_map.get(metric_type, "unknown")),
            "duration": duration,
            "step": "5s",
            "values": {},
            "summary": "No data available"
        }
    
    try:
        # Get step from query_info if available
        step = result.get("query_info", {}).get("step", "5s")
        unit = result.get("unit", unit_map.get(metric_type, "unknown"))
        
        # Create node timeseries data
        node_data = {}
        
        for item in result["data"]:
            node_name = item.get("node", "unknown")
            values = item.get("values", [])
            
            if not values:
                continue
                
            # Extract the actual metric values (now all use "value" field)
            try:
                metric_values = [round(v.get("value", 0), 1) for v in values]
                node_data[node_name] = metric_values
                
            except Exception as e:
                # Skip this node if there's an error processing it
                continue
        
        output = {
            "status": "success",
            "metric_type": actual_metric_type,
            "unit": unit,
            "duration": duration,
            "step": step,
            "values": node_data
        }
        
        # Include description if present (for core metrics)
        if "description" in result:
            output["description"] = result["description"]
        
        return output
        
    except Exception as e:
        return {
            "error": f"Failed to format node {metric_type} output: {str(e)}",
            "raw_result": result
        }

def prometheus_get_service_topology(namespace: Optional[str] = None, time_window: str = "5m") -> Dict[str, Any]:
    """Get service topology information showing communication patterns and critical services."""
    tool = get_prometheus_tool()
    return tool.get_service_topology(namespace, time_window) 