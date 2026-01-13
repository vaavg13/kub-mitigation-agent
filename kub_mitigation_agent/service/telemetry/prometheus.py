import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

class PrometheusClient:
    """
    Dumb transport client for Prometheus.
    """
    
    def __init__(self, prometheus_url="http://localhost:9090"):
        self.prometheus_url = prometheus_url
        if not self.prometheus_url.startswith(("http://", "https://")):
            self.prometheus_url = "http://" + self.prometheus_url

    def query(self, query: str) -> Dict[str, Any]:
        """Execute an instant Prometheus query."""
        try:
            full_url = f"{self.prometheus_url}/api/v1/query"
            response = requests.get(full_url, params={"query": query}, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def query_range(self, query: str, start: float, end: float, step: str) -> Dict[str, Any]:
        """Execute a range query."""
        try:
            params = {
                'query': query,
                'start': start,
                'end': end,
                'step': step
            }
            response = requests.get(f"{self.prometheus_url}/api/v1/query_range", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def is_ready(self, timeout: int = 3) -> bool:
        """Check if Prometheus is ready."""
        try:
            resp = requests.get(f"{self.prometheus_url}/-/ready", timeout=timeout)
            if resp.status_code == 200:
                return True
            # Fallback to checking 'up' query
            q = requests.get(f"{self.prometheus_url}/api/v1/query", params={"query": "up"}, timeout=timeout)
            if not q.ok:
                return False
            data = q.json()
            return isinstance(data, dict) and data.get("status") == "success"
        except Exception:
            return False

def parse_duration(duration: str) -> int:
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

# Global instance management
_client = None

def get_prometheus_client(url: str = "http://localhost:9090") -> PrometheusClient:
    global _client
    if _client is None:
        _client = PrometheusClient(url)
    return _client

