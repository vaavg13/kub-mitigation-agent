from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional


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
    
    def get_node_cpu_timeseries(self, duration: str = "10m", step: str = "1m") -> Dict[str, Any]:
        """CPU used by containers on each node (sum of containers), in cores."""
        base_selector = 'image!="", container!="POD"'
        query = (
            f'sum by (node) (\n\n  rate(container_cpu_usage_seconds_total{{{base_selector}}}[2m])\n\n)'
        )
        data = self._query_prometheus_range(query, duration, step)

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
    
    def get_node_memory_timeseries(self, duration: str = "10m", step: str = "1m") -> Dict[str, Any]:
        """Node memory used (bytes), joined to nodename via node_uname_info."""
        query = (
            '(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)\n\n* on (instance) group_left (nodename)\n\nnode_uname_info'
        )
        data = self._query_prometheus_range(query, duration, step)
        
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
    
    def get_node_core_cpu_timeseries(self, duration: str = "10m", step: str = "1m") -> Dict[str, Any]:
        """Total node CPU usage (non-idle) in cores, joined to node names via kube_node_info."""
        query = (
            'label_replace(\n\n  sum by (instance) (irate(node_cpu_seconds_total{mode!="idle"}[1m])),\n\n  "internal_ip", "$1", "instance", "^([^:]+):.*$"\n\n)\n\n* on (internal_ip) group_left (node)\n\nkube_node_info'
        )
        data = self._query_prometheus_range(query, duration, step)

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
    
    def get_pod_cpu_timeseries(self, duration: str = "10m", step: str = "1m", namespace: Optional[str] = None, rate_window: str = "1m") -> Dict[str, Any]:
        """Get historical CPU usage time series for pods."""
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
    
    def get_istio_ingress_metrics(self, duration_seconds: float) -> Dict[str, Any]:
        """Get Istio ingress gateway metrics for the specified duration.
        
        Queries metrics from istio-ingressgateway in istio-system namespace.
        Returns P95 latency and success rate from server-side perspective.
        
        Args:
            duration_seconds: Time window to query (e.g., 60 for last 60 seconds)
        
        Returns:
            Dict with p95_latency_seconds, success_rate_percent, total_requests
        """
        import math
        
        duration_str = f"{int(duration_seconds)}s"
        
        latency_query = f'''histogram_quantile(0.95,
            sum(rate(istio_request_duration_milliseconds_bucket{{
                reporter="source",
                source_workload="istio-ingressgateway",
                source_workload_namespace="istio-system"
            }}[{duration_str}]))
            by (le)
        )'''
        
        total_requests_query = f'''sum(increase(istio_requests_total{{
            reporter="source",
            source_workload="istio-ingressgateway",
            source_workload_namespace="istio-system"
        }}[{duration_str}]))'''
        
        success_requests_query = f'''sum(increase(istio_requests_total{{
            reporter="source",
            source_workload="istio-ingressgateway",
            source_workload_namespace="istio-system",
            response_code=~"[23].*"
        }}[{duration_str}]))'''
        
        latency_data = self._query_prometheus(latency_query)
        total_data = self._query_prometheus(total_requests_query)
        success_data = self._query_prometheus(success_requests_query)
        
        p95_latency_ms = 0
        total_requests = 0
        successful_requests = 0
        
        if latency_data and latency_data.get('status') == 'success' and latency_data['data']['result']:
            value = latency_data['data']['result'][0]['value'][1]
            p95_latency_ms = float(value)
            if math.isnan(p95_latency_ms) or p95_latency_ms == float('inf'):
                p95_latency_ms = 0
        
        if total_data and total_data.get('status') == 'success' and total_data['data']['result']:
            value = total_data['data']['result'][0]['value'][1]
            total_requests = int(float(value))
        
        if success_data and success_data.get('status') == 'success' and success_data['data']['result']:
            value = success_data['data']['result'][0]['value'][1]
            successful_requests = int(float(value))
        
        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "p95_latency_seconds": round(p95_latency_ms / 1000.0, 3),
            "success_rate_percent": round(success_rate, 2),
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "failed_requests": total_requests - successful_requests
        }
    
    def get_service_topology(self, namespace: Optional[str] = None, time_window: str = "5m") -> Dict[str, Any]:
        """Get service topology and communication patterns from Istio metrics."""
        if namespace:
            selector = f'reporter="destination", destination_workload_namespace="{namespace}"'
        else:
            selector = 'reporter="destination"'

        query = f'sum by (source_workload, destination_workload, source_workload_namespace, destination_workload_namespace) (rate(istio_requests_total{{{selector}}}[{time_window}]))'
        data = self._query_prometheus(query)
        
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
            data2 = self._query_prometheus(query2)
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

# Global instance to be used by agent
_prometheus_tool = None


def get_prometheus_tool(prometheus_url="http://localhost:9090") -> PrometheusMetricsTool:
    """Get or create global PrometheusMetricsTool instance."""
    global _prometheus_tool
    if _prometheus_tool is None:
        _prometheus_tool = PrometheusMetricsTool(prometheus_url)
    return _prometheus_tool


