import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from kub_mitigation_agent.service.telemetry.prometheus import PrometheusClient, parse_duration

class ExperimentMetrics:
    """
    Experiment-specific metrics collection.
    """
    
    def __init__(self, client: PrometheusClient):
        self.client = client

    def get_istio_ingress_metrics(self, duration_seconds: float) -> Dict[str, Any]:
        """Get Istio ingress gateway metrics for the specified duration."""
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
        
        latency_data = self.client.query(latency_query)
        total_data = self.client.query(total_requests_query)
        success_data = self.client.query(success_requests_query)
        
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
            "failed_requests": total_requests - successful_requests,
            "source": "istio-ingress"
        }

    def get_experiment_snapshot(self, started_at: str, duration_seconds: float, namespace: str) -> Dict[str, Any]:
        """Capture Prometheus timeseries for the full experiment duration."""
        
        step = "15s"
        
        # Calculate time range
        start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
        end_time = start_time + timedelta(seconds=duration_seconds)
        
        start_ts = start_time.timestamp()
        end_ts = end_time.timestamp()
        
        # === INGRESS GATEWAY METRICS ===
        
        # 1. Latency P95
        latency_query = '''histogram_quantile(0.95,
            sum(rate(istio_request_duration_milliseconds_bucket{
                reporter="source",
                source_workload="istio-ingressgateway",
                source_workload_namespace="istio-system"
            }[1m]))
            by (le)
        )'''
        latency_data = self.client.query_range(latency_query, start_ts, end_ts, step)
        
        # 2. Total Requests
        total_query = '''sum(rate(istio_requests_total{
            reporter="source",
            source_workload="istio-ingressgateway",
            source_workload_namespace="istio-system"
        }[1m]))'''
        total_data = self.client.query_range(total_query, start_ts, end_ts, step)
        
        # 3. Success Requests (2xx/3xx)
        success_query = '''sum(rate(istio_requests_total{
            reporter="source",
            source_workload="istio-ingressgateway",
            source_workload_namespace="istio-system",
            response_code=~"[23].*"
        }[1m]))'''
        success_data = self.client.query_range(success_query, start_ts, end_ts, step)

        # Process Ingress Data
        ingress_latency = self._format_timeseries(latency_data, scale=0.001) # ms -> s
        
        # Calculate success rate timeseries
        ingress_success_rate = []
        total_vals = {point['timestamp']: point['value'] for point in self._format_timeseries(total_data)}
        success_vals = {point['timestamp']: point['value'] for point in self._format_timeseries(success_data)}
        
        for ts in total_vals:
            tot = total_vals[ts]
            suc = success_vals.get(ts, 0)
            rate = (suc / tot * 100) if tot > 0 else 0
            ingress_success_rate.append({'timestamp': ts, 'value': round(rate, 2)})
            
        # === NODE METRICS ===
        # Node CPU (Pod aggregate)
        node_pod_cpu_query = 'sum by (node) (rate(container_cpu_usage_seconds_total{image!="", container!="POD"}[2m]))'
        node_pod_cpu_data = self.client.query_range(node_pod_cpu_query, start_ts, end_ts, step)
        
        # Node CPU (Total non-idle)
        node_core_cpu_query = 'label_replace(sum by (instance) (irate(node_cpu_seconds_total{mode!="idle"}[1m])), "internal_ip", "$1", "instance", "^([^:]+):.*$") * on (internal_ip) group_left (node) kube_node_info'
        node_core_cpu_data = self.client.query_range(node_core_cpu_query, start_ts, end_ts, step)
        
        # Node Memory
        node_mem_query = '(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) * on (instance) group_left (nodename) node_uname_info'
        node_mem_data = self.client.query_range(node_mem_query, start_ts, end_ts, step)

        return {
            'ingress_gateway': {
                'latency_p95_seconds': ingress_latency,
                'success_rate_percent': ingress_success_rate
            },
            'node_resources': {
                'pod_cpu_per_node': self._format_multi_timeseries(node_pod_cpu_data, label_key='node'),
                'node_cpu_cores_non_idle': self._format_multi_timeseries(node_core_cpu_data, label_key='node'),
                'node_memory_bytes': self._format_multi_timeseries(node_mem_data, label_key='nodename')
            },
            'metadata': {
                'start_time': started_at,
                'end_time': end_time.isoformat(),
                'duration_seconds': duration_seconds,
                'step': step,
                'namespace': namespace
            }
        }

    def _format_timeseries(self, response_json: Dict, scale: float = 1.0) -> List[Dict]:
        """Format single series response."""
        results = []
        if response_json and response_json.get('status') == 'success' and response_json['data']['result']:
            for ts, val in response_json['data']['result'][0]['values']:
                results.append({'timestamp': ts, 'value': float(val) * scale})
        return results

    def _format_multi_timeseries(self, response_json: Dict, label_key: str) -> List[Dict]:
        """Format multi-series response (e.g. one per node)."""
        results = []
        if response_json and response_json.get('status') == 'success' and response_json['data']['result']:
            for series in response_json['data']['result']:
                lbl = series['metric'].get(label_key) or series['metric'].get('instance', 'unknown').split(':')[0]
                vals = [{'value': float(v)} for _, v in series['values']] # simplified structure for log
                results.append({'node': lbl, 'values': vals})
        return results

