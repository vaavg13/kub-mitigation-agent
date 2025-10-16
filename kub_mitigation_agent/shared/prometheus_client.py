import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from mu_bench.metrics_exporter.prometheus_exporter import PrometheusExporter
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import json

def format_timestamp(unix_timestamp: float) -> Dict[str, Any]:
    """Convert Unix timestamp to human-readable format for LLM consumption."""
    dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    return {
        "unix": int(unix_timestamp),
        "datetime": dt.isoformat(),
        "human_readable": dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    }

class PrometheusMetricsTool:
    """
    Tool for getting current Prometheus metrics.
    """
    
    def __init__(self, prometheus_url="http://localhost:9090"):
        """Initialize the Prometheus metrics tool."""
        # Create exporter but don't initialize CSV files
        self.exporter = PrometheusExporter(
            prometheus_url=prometheus_url,
            create_output_dir=False,
            verbose=False
        )
    
    def get_current_node_cpu(self, rate_window="1m") -> Dict[str, Any]:
        """Get current CPU usage for all nodes."""
        query = f'sum by (instance) (rate(container_cpu_usage_seconds_total{{image!="", container!="POD"}}[{rate_window}]))'
        data = self.exporter._query_prometheus(query)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query node CPU metrics", "data": []}
        
        results = []
        for item in data['data']['result']:
            node_id = item['metric'].get('instance', 'unknown_instance').split(':')[0]
            cpu_cores = round(float(item['value'][1]), 3)
            results.append({
                "node": node_id,
                "cpu_cores_used": cpu_cores,
                "timestamp": format_timestamp(float(item['value'][0]))
            })
        
        return {"status": "success", "data": results}
    
    def get_current_node_memory(self) -> Dict[str, Any]:
        """Get current memory usage for all nodes (using working set like kubectl top)."""
        query = 'sum by (instance) (container_memory_working_set_bytes{image!="", container!="POD"})'
        data = self.exporter._query_prometheus(query)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query node memory metrics", "data": []}
        
        results = []
        for item in data['data']['result']:
            node_id = item['metric'].get('instance', 'unknown_instance').split(':')[0]
            memory_bytes = int(float(item['value'][1]))
            memory_mb = round(memory_bytes / (1024 * 1024), 2)
            memory_gb = round(memory_bytes / (1024 * 1024 * 1024), 2)
            results.append({
                "node": node_id,
                "memory_working_set_bytes": memory_bytes,
                "memory_working_set_mb": memory_mb,
                "memory_working_set_gb": memory_gb,
                "timestamp": format_timestamp(float(item['value'][0]))
            })
        
        return {"status": "success", "data": results}
    
    def get_current_pod_cpu(self, namespace: Optional[str] = None, rate_window="1m") -> Dict[str, Any]:
        """Get current CPU usage for pods."""
        # Build namespace filter
        if namespace:
            namespace_filter = f'namespace="{namespace}"'
            base_selector = 'image!="", container!="POD"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = 'image!="", container!="POD"'
        
        query = f'sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{{{full_selector}}}[{rate_window}]))'
        data = self.exporter._query_prometheus(query)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query pod CPU metrics", "data": []}
        
        results = []
        for item in data['data']['result']:
            namespace_val = item['metric'].get('namespace', 'unknown_namespace')
            pod_val = item['metric'].get('pod', 'unknown_pod')
            cpu_cores = round(float(item['value'][1]), 3)
            cpu_millicores = round(cpu_cores * 1000, 0)  # Convert to millicores like kubectl top
            results.append({
                "namespace": namespace_val,
                "pod": pod_val,
                "cpu_millicores": f"{int(cpu_millicores)}m",  # Format like kubectl top (e.g., "5m")
                "timestamp": format_timestamp(float(item['value'][0]))
            })
        
        return {"status": "success", "data": results}
    
    def get_current_pod_memory(self, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Get current memory usage for pods (using working set like kubectl top pod)."""
        # Build namespace filter
        if namespace:
            namespace_filter = f'namespace="{namespace}"'
            base_selector = 'image!="", container!="POD"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = 'image!="", container!="POD"'
        
        # Use container_memory_working_set_bytes to match kubectl top pod behavior
        query = f'sum by (namespace, pod) (container_memory_working_set_bytes{{{full_selector}}})'
        data = self.exporter._query_prometheus(query)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query pod memory metrics", "data": []}
        
        results = []
        for item in data['data']['result']:
            namespace_val = item['metric'].get('namespace', 'unknown_namespace')
            pod_val = item['metric'].get('pod', 'unknown_pod')
            memory_bytes = int(float(item['value'][1]))
            memory_mib = round(memory_bytes / (1024 * 1024), 0)  # Mebibytes like kubectl top
            results.append({
                "namespace": namespace_val,
                "pod": pod_val,
                "memory_working_set_mib": f"{int(memory_mib)}Mi",
                "timestamp": format_timestamp(float(item['value'][0]))
            })
        
        return {"status": "success", "data": results}
    
    def get_current_istio_latency(self, namespace: Optional[str] = None, percentile="0.95", rate_window="2m") -> Dict[str, Any]:
        """Get current Istio latency metrics for services."""
        import math
        
        # Build namespace filter
        if namespace:
            namespace_filter = f'destination_workload_namespace="{namespace}"'
            base_selector = 'reporter="destination"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = 'reporter="destination"'
        
        # Use histogram quantile for P95 latency with pod-level granularity (not deployment aggregation)
        query = f'''histogram_quantile({percentile},
            sum(rate(istio_request_duration_milliseconds_bucket{{{full_selector}}}[{rate_window}]))
            by (le, pod_name, destination_workload_namespace)
        )'''
        data = self.exporter._query_prometheus(query)
        
        results = []
        
        if data and data.get('status') == 'success':
            for item in data['data']['result']:
                pod_name_val = item['metric'].get('pod_name', 'unknown_pod')
                namespace_val = item['metric'].get('destination_workload_namespace', 'unknown_namespace')
                latency_ms = float(item['value'][1])
                
                # If histogram quantile gives valid result, use it
                if not (math.isnan(latency_ms) or latency_ms == float('inf')):
                    results.append({
                        "namespace": namespace_val,
                        "workload": pod_name_val,  # This is now a pod name, not workload name
                        "p95_latency_ms": round(latency_ms, 2),
                        "timestamp": format_timestamp(float(item['value'][0]))
                    })
                else:
                    # Fall back to average latency if histogram quantile fails
                    avg_query = f'''rate(istio_request_duration_milliseconds_sum{{
                        {full_selector}, pod_name="{pod_name_val}"
                    }}[{rate_window}]) / rate(istio_requests_total{{
                        {full_selector}, pod_name="{pod_name_val}"
                    }}[{rate_window}])'''
                    
                    avg_data = self.exporter._query_prometheus(avg_query)
                    if avg_data and avg_data.get('status') == 'success' and avg_data['data']['result']:
                        avg_latency = float(avg_data['data']['result'][0]['value'][1])
                        if not (math.isnan(avg_latency) or avg_latency == float('inf')):
                            results.append({
                                "namespace": namespace_val,
                                "workload": pod_name_val,  # This is now a pod name, not workload name
                                "p95_latency_ms": round(avg_latency, 2),  # Using average as fallback
                                "timestamp": format_timestamp(float(item['value'][0]))
                            })
        
        if not results:
            return {"error": "Failed to query Istio P95 latency metrics", "data": []}
        
        return {"status": "success", "data": results}
    
    def get_metrics_summary(self, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Get a summary of all current metrics for a namespace or all namespaces."""
        now = datetime.now(timezone.utc)
        summary = {
            "namespace_filter": namespace or "all_namespaces",
            "summary_generated_at": {
                "unix": int(now.timestamp()),
                "datetime": now.isoformat(),
                "human_readable": now.strftime("%Y-%m-%d %H:%M:%S UTC")
            },
            "metrics": {}
        }
        
        # Get all metrics
        summary["metrics"]["node_cpu"] = self.get_current_node_cpu()
        summary["metrics"]["node_memory"] = self.get_current_node_memory()
        summary["metrics"]["pod_cpu"] = self.get_current_pod_cpu(namespace)
        summary["metrics"]["pod_memory"] = self.get_current_pod_memory(namespace)
        summary["metrics"]["istio_latency"] = self.get_current_istio_latency(namespace)
        
        return summary
    
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
            response = requests.get(f"{self.exporter.prometheus_url}/api/v1/query_range", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def get_node_cpu_timeseries(self, duration: str = "10m", step: str = "1m", rate_window: str = "1m") -> Dict[str, Any]:
        """Get historical CPU usage time series for all nodes."""
        query = f'sum by (instance) (rate(container_cpu_usage_seconds_total{{image!="", container!="POD"}}[{rate_window}]))'
        data = self._query_prometheus_range(query, duration, step)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query node CPU time series", "data": []}
        
        results = []
        for series in data['data']['result']:
            node_id = series['metric'].get('instance', 'unknown_instance').split(':')[0]
            values = []
            for timestamp, value in series['values']:
                values.append({
                    "timestamp": format_timestamp(float(timestamp)),
                    "cpu_cores_used": round(float(value), 3)
                })
            
            results.append({
                "node": node_id,
                "values": values
            })
        
        return {
            "status": "success", 
            "query_info": {"duration": duration, "step": step, "rate_window": rate_window},
            "data": results
        }
    
    def get_node_memory_timeseries(self, duration: str = "10m", step: str = "1m") -> Dict[str, Any]:
        """Get historical memory usage time series for all nodes."""
        query = 'sum by (instance) (container_memory_working_set_bytes{image!="", container!="POD"})'
        data = self._query_prometheus_range(query, duration, step)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query node memory time series", "data": []}
        
        results = []
        for series in data['data']['result']:
            node_id = series['metric'].get('instance', 'unknown_instance').split(':')[0]
            values = []
            for timestamp, value in series['values']:
                memory_bytes = int(float(value))
                values.append({
                    "timestamp": format_timestamp(float(timestamp)),
                    "memory_working_set_bytes": memory_bytes,
                    "memory_working_set_gb": round(memory_bytes / (1024 * 1024 * 1024), 2)
                })
            
            results.append({
                "node": node_id,
                "values": values
            })
        
        return {
            "status": "success",
            "query_info": {"duration": duration, "step": step},
            "data": results
        }
    
    def get_pod_cpu_timeseries(self, duration: str = "10m", step: str = "1m", namespace: Optional[str] = None, rate_window: str = "1m") -> Dict[str, Any]:
        """Get historical CPU usage time series for pods."""
        # Build namespace filter
        if namespace:
            namespace_filter = f'namespace="{namespace}"'
            base_selector = 'image!="", container!="POD"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = 'image!="", container!="POD"'
        
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
                cpu_cores = round(float(value), 3)
                cpu_millicores = round(cpu_cores * 1000, 0)
                values.append({
                    "timestamp": format_timestamp(float(timestamp)),
                    "cpu_millicores": f"{int(cpu_millicores)}m"
                })
            
            results.append({
                "namespace": namespace_val,
                "pod": pod_val,
                "values": values
            })
        
        return {
            "status": "success",
            "query_info": {"duration": duration, "step": step, "rate_window": rate_window, "namespace_filter": namespace or "all_namespaces"},
            "data": results
        }
    
    def get_pod_memory_timeseries(self, duration: str = "10m", step: str = "1m", namespace: Optional[str] = None) -> Dict[str, Any]:
        """Get historical memory usage time series for pods."""
        # Build namespace filter
        if namespace:
            namespace_filter = f'namespace="{namespace}"'
            base_selector = 'image!="", container!="POD"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = 'image!="", container!="POD"'
        
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
                memory_mib = round(memory_bytes / (1024 * 1024), 0)
                values.append({
                    "timestamp": format_timestamp(float(timestamp)),
                    "memory_working_set_mib": f"{int(memory_mib)}Mi"
                })
            
            results.append({
                "namespace": namespace_val,
                "pod": pod_val,
                "values": values
            })
        
        return {
            "status": "success",
            "query_info": {"duration": duration, "step": step, "namespace_filter": namespace or "all_namespaces"},
            "data": results
        }
    
    def get_istio_latency_timeseries(self, duration: str = "10m", step: str = "1m", namespace: Optional[str] = None, percentile: str = "0.95", rate_window: str = "2m") -> Dict[str, Any]:
        """Get historical Istio latency time series for services."""
        import math
        
        # Build namespace filter
        if namespace:
            namespace_filter = f'destination_workload_namespace="{namespace}"'
            base_selector = 'reporter="destination"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = 'reporter="destination"'
        
        query = f'''histogram_quantile({percentile},
            sum(rate(istio_request_duration_milliseconds_bucket{{{full_selector}}}[{rate_window}]))
            by (le, pod_name, destination_workload_namespace)
        )'''
        data = self._query_prometheus_range(query, duration, step)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query Istio latency time series", "data": []}
        
        results = []
        for series in data['data']['result']:
            pod_name_val = series['metric'].get('pod_name', 'unknown_pod')
            namespace_val = series['metric'].get('destination_workload_namespace', 'unknown_namespace')
            values = []
            
            for timestamp, value in series['values']:
                latency_ms = float(value)
                if not (math.isnan(latency_ms) or latency_ms == float('inf')):
                    values.append({
                        "timestamp": format_timestamp(float(timestamp)),
                        "p95_latency_ms": round(latency_ms, 2)
                    })
            
            if values:  # Only include series with valid data
                results.append({
                    "namespace": namespace_val,
                    "workload": pod_name_val,  # This is now a pod name, not workload name
                    "values": values
                })
        
        return {
            "status": "success",
            "query_info": {"duration": duration, "step": step, "percentile": percentile, "rate_window": rate_window, "namespace_filter": namespace or "all_namespaces"},
            "data": results
        }
    
    def get_custom_timeseries(self, query: str, duration: str = "10m", step: str = "1m") -> Dict[str, Any]:
        """Execute custom Prometheus range query for time series data."""
        data = self._query_prometheus_range(query, duration, step)
        
        if not data or data.get('status') != 'success':
            return {"error": f"Failed to execute custom query: {query}", "data": []}
        
        results = []
        for series in data['data']['result']:
            values = []
            for timestamp, value in series['values']:
                values.append({
                    "timestamp": format_timestamp(float(timestamp)),
                    "value": float(value)
                })
            
            results.append({
                "metric": series['metric'],
                "values": values
            })
        
        return {
            "status": "success",
            "query_info": {"query": query, "duration": duration, "step": step},
            "data": results
        }

    def get_service_topology(self, namespace: Optional[str] = None, time_window: str = "5m") -> Dict[str, Any]:
        """Get service topology and communication patterns from Istio metrics."""
        # Build namespace filter for destination services
        if namespace:
            namespace_filter = f'destination_service_namespace="{namespace}"'
            base_selector = 'reporter="destination"'
            full_selector = f'{base_selector}, {namespace_filter}'
        else:
            full_selector = 'reporter="destination"'
        
        # Query for service-to-service communication with request volumes
        query = f'sum by (source_app, destination_app, source_workload_namespace, destination_workload_namespace) (rate(istio_requests_total{{{full_selector}}}[{time_window}]))'
        data = self.exporter._query_prometheus(query)
        
        if not data or data.get('status') != 'success':
            return {"error": "Failed to query service topology", "data": {}}
        
        # Extract topology information
        services = set()
        relationships = []
        service_details = {}
        
        for item in data['data']['result']:
            source_app = item['metric'].get('source_app', 'unknown')
            dest_app = item['metric'].get('destination_app', 'unknown')
            source_ns = item['metric'].get('source_workload_namespace', 'unknown')
            dest_ns = item['metric'].get('destination_workload_namespace', 'unknown')
            request_rate = round(float(item['value'][1]), 3)
            
            # Skip very low-volume connections (likely health checks)
            if request_rate < 0.001:
                continue
                
            services.add(source_app)
            services.add(dest_app)
            
            relationships.append({
                "source": source_app,
                "destination": dest_app, 
                "source_namespace": source_ns,
                "destination_namespace": dest_ns,
                "request_rate_per_second": request_rate
            })
            
            # Track service details
            service_details[source_app] = {"namespace": source_ns, "type": "client"}
            service_details[dest_app] = {"namespace": dest_ns, "type": "server"}
        
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
        
        return {
            "status": "success",
            "query_info": {"time_window": time_window, "namespace_filter": namespace or "all_namespaces"},
            "topology": {
                "services": sorted(list(services)),
                "relationships": relationships,
                "service_details": service_details,
                "critical_services": critical_services[:5],  # Top 5 most critical
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

def prometheus_get_node_cpu(rate_window: str = "1m") -> Dict[str, Any]:
    """Get current CPU usage for all nodes."""
    tool = get_prometheus_tool()
    return tool.get_current_node_cpu(rate_window)

def prometheus_get_node_memory() -> Dict[str, Any]:
    """Get current memory usage for all nodes."""
    tool = get_prometheus_tool()
    return tool.get_current_node_memory()

def prometheus_get_pod_cpu(namespace: Optional[str] = None, rate_window: str = "1m") -> Dict[str, Any]:
    """Get current CPU usage for pods in specified namespace or all namespaces."""
    tool = get_prometheus_tool()
    return tool.get_current_pod_cpu(namespace, rate_window)

def prometheus_get_pod_memory(namespace: Optional[str] = None) -> Dict[str, Any]:
    """Get current memory usage for pods in specified namespace or all namespaces."""
    tool = get_prometheus_tool()
    return tool.get_current_pod_memory(namespace)

def prometheus_get_istio_latency(namespace: Optional[str] = None, percentile: str = "0.95", rate_window: str = "2m") -> Dict[str, Any]:
    """Get current Istio latency metrics for services in specified namespace or all namespaces."""
    tool = get_prometheus_tool()
    return tool.get_current_istio_latency(namespace, percentile, rate_window)

def prometheus_get_metrics_summary(namespace: Optional[str] = None) -> Dict[str, Any]:
    """Get a summary of all current metrics for a namespace or all namespaces."""
    tool = get_prometheus_tool()
    return tool.get_metrics_summary(namespace)

# New Simplified Time Series Functions (Optimized for Agent Use)

def prometheus_get_timeseries(metric_type: str, namespace: str, duration: str = "2m") -> Dict[str, Any]:
    """
    Get historical time series for pods/services with optimized settings.
    Fixed 5s intervals, 2m max duration, concise output format.
    
    Args:
        metric_type: Type of metric ("cpu", "memory", "latency")
        namespace: Target namespace to filter metrics
        duration: Time range (max 2m)
    """
    tool = get_prometheus_tool()
    step = "5s"  # Fixed 5s intervals
    
    # Enforce 2m maximum
    try:
        duration_seconds = tool._parse_duration_to_seconds(duration)
        if duration_seconds > 120:  # 2 minutes
            duration = "2m"
    except Exception:
        duration = "2m"  # Default fallback
    
    try:
        if metric_type == "cpu":
            result = tool.get_pod_cpu_timeseries(duration, step, namespace, rate_window="30s")
        elif metric_type == "memory":
            result = tool.get_pod_memory_timeseries(duration, step, namespace)
        elif metric_type == "latency":
            result = tool.get_istio_latency_timeseries(duration, step, namespace, percentile="0.95", rate_window="30s")
        else:
            return {"error": f"Unsupported metric type: {metric_type}. Use 'cpu', 'memory', or 'latency'"}
        
        # Check if there's an error in the result first
        if result.get("error"):
            return result
        
        # Format for minimal token usage
        return _format_timeseries_output(result, metric_type, duration)
        
    except Exception as e:
        return {"error": f"Failed to get {metric_type} timeseries: {str(e)}"}

def prometheus_get_node_timeseries(metric_type: str, duration: str = "2m") -> Dict[str, Any]:
    """
    Get historical node-level metrics with optimized settings.
    Fixed 5s intervals, 2m max duration, concise output format.
    
    Args:
        metric_type: Type of metric ("cpu", "memory")
        duration: Time range (max 2m)
    """
    tool = get_prometheus_tool()
    step = "5s"  # Fixed 5s intervals
    
    # Enforce 2m maximum
    try:
        duration_seconds = tool._parse_duration_to_seconds(duration)
        if duration_seconds > 120:  # 2 minutes
            duration = "2m"
    except Exception:
        duration = "2m"  # Default fallback
    
    try:
        if metric_type == "cpu":
            result = tool.get_node_cpu_timeseries(duration, step, rate_window="30s")
        elif metric_type == "memory":
            result = tool.get_node_memory_timeseries(duration, step)
        else:
            return {"error": f"Unsupported node metric type: {metric_type}. Use 'cpu' or 'memory'"}
        
        # Check if there's an error in the result first
        if result.get("error"):
            return result
        
        # Format for minimal token usage
        return _format_node_timeseries_output(result, metric_type, duration)
        
    except Exception as e:
        return {"error": f"Failed to get node {metric_type} timeseries: {str(e)}"}

def _format_timeseries_output(result: Dict[str, Any], metric_type: str, duration: str) -> Dict[str, Any]:
    """Format timeseries output to show actual values for each pod."""
    # Handle errors first
    if result.get("error"):
        return result
    
    # Check if we have data
    if not result.get("data"):
        return {
            "status": "success",
            "metric": metric_type,
            "duration": duration,
            "step": "5s",
            "summary": "No data available"
        }
    
    try:
        # Get step from query_info if available
        step = result.get("query_info", {}).get("step", "5s")
        
        # Create pod timeseries data
        pod_data = {}
        
        for item in result["data"]:
            pod_name = item.get("pod") or item.get("workload", "unknown")
            values = item.get("values", [])
            
            if not values:
                continue
                
            # Extract the actual metric values
            try:
                if metric_type == "cpu":
                    # Extract numeric values from cpu_millicores format (remove 'm' suffix)
                    metric_values = [float(v.get("cpu_millicores", "0m").replace("m", "")) for v in values]
                elif metric_type == "memory":
                    # Extract numeric values from memory format (remove 'Mi' suffix)  
                    metric_values = [float(v.get("memory_working_set_mib", "0Mi").replace("Mi", "")) for v in values]
                elif metric_type == "latency":
                    # Extract latency values (already numeric)
                    metric_values = [v.get("p95_latency_ms", 0) for v in values]
                else:
                    continue
                
                pod_data[pod_name] = metric_values
                
            except Exception as e:
                # Skip this pod if there's an error processing it
                continue
        
        return {
            "status": "success",
            "metric": metric_type,
            "duration": duration,
            "step": step,
            **pod_data  # Spread the pod data directly into the result
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
    if not result.get("data"):
        return {
            "status": "success",
            "metric": metric_type,
            "duration": duration,
            "step": "5s",
            "summary": "No data available"
        }
    
    try:
        # Get step from query_info if available
        step = result.get("query_info", {}).get("step", "5s")
        
        # Create node timeseries data
        node_data = {}
        
        for item in result["data"]:
            node_name = item.get("node", "unknown")
            values = item.get("values", [])
            
            if not values:
                continue
                
            # Extract the actual metric values
            try:
                if metric_type == "cpu":
                    metric_values = [v.get("cpu_cores_used", 0) for v in values]
                elif metric_type == "memory":
                    metric_values = [v.get("memory_working_set_gb", 0) for v in values]
                else:
                    continue
                
                node_data[node_name] = metric_values
                
            except Exception as e:
                # Skip this node if there's an error processing it
                continue
        
        return {
            "status": "success",
            "metric": metric_type,
            "duration": duration,
            "step": step,
            **node_data  # Spread the node data directly into the result
        }
        
    except Exception as e:
        return {
            "error": f"Failed to format node {metric_type} output: {str(e)}",
            "raw_result": result
        }

def prometheus_get_service_topology(namespace: Optional[str] = None, time_window: str = "5m") -> Dict[str, Any]:
    """Get service topology information showing communication patterns and critical services."""
    tool = get_prometheus_tool()
    return tool.get_service_topology(namespace, time_window) 