import asyncio
import time
import logging
import statistics
from typing import Dict, List
from locust import HttpUser, task, between, events
from locust.env import Environment
from locust.stats import stats_printer, stats_history
import gevent

logger = logging.getLogger(__name__)

class SimpleLoadUser(HttpUser):
    """Simple Locust user for testing specific endpoints."""
    wait_time = between(1, 3)  # Realistic wait between requests (1-3 seconds)
    connection_timeout = 10.0
    network_timeout = 10.0
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.endpoints = getattr(self.environment, 'target_endpoints', ['/'])
    
    @task
    def test_endpoint_1(self):
        """Test first endpoint."""
        if len(self.endpoints) >= 1:
            try:
                response = self.client.get(self.endpoints[0], timeout=10)
            except Exception as e:
                # Locust will handle the exception stats
                pass
    
    @task            
    def test_endpoint_2(self):
        """Test second endpoint."""
        if len(self.endpoints) >= 2:
            try:
                response = self.client.get(self.endpoints[1], timeout=10)
            except Exception as e:
                # Locust will handle the exception stats
                pass

class LocustTrafficGenerator:
    """Locust-based traffic generator for reproducible load testing."""
    
    def __init__(self, config: Dict):
        self.config = config
        self.environment = None
        self.runner = None
        self.stats_greenlet = None
        self.is_running = False
        self.phase_start_time = None
        self.actual_users = 0  # Track actual user count for realistic calculations
        
        # Suppress Locust's verbose logging using standard Python logging
        logging.getLogger("locust").setLevel(logging.WARNING)
        
    def _extract_endpoints_paths(self) -> List[str]:
        """Extract just the paths from full endpoint URLs."""
        paths = []
        for endpoint in self.config["endpoints"]:
            # Extract path from URL like "http://172.23.0.5:31115/s0-edge-site-1" -> "/s0-edge-site-1"
            if "//" in endpoint:
                path = "/" + endpoint.split("//")[1].split("/", 1)[1] if "/" in endpoint.split("//")[1] else "/"
            else:
                path = endpoint
            paths.append(path)
        return paths
    
    def _get_host_from_endpoints(self) -> str:
        """Extract host from the first endpoint."""
        first_endpoint = self.config["endpoints"][0]
        if "//" in first_endpoint:
            # Extract "http://172.23.0.5:31115" from "http://172.23.0.5:31115/s0-edge-site-1"
            return first_endpoint.split("//")[0] + "//" + first_endpoint.split("//")[1].split("/")[0]
        return "http://localhost"
    
    def _calculate_realistic_expected_requests(self, phase_duration_seconds: float) -> int:
        """Calculate realistic expected requests based on actual Locust behavior."""
        if not self.actual_users or phase_duration_seconds <= 0:
            return 0
        
        # Realistic calculation:
        # - Each user has wait_time between(1, 3) → average 2s wait between requests
        # - Each user cycles through 2 tasks (endpoints) equally
        # - So each user makes ~1 request every 2s across both endpoints = 0.5 req/s per user
        # - Total rate = users × 0.5 req/s
        realistic_rps_per_user = 0.5  # Conservative estimate based on wait times and task distribution
        estimated_total_rps = self.actual_users * realistic_rps_per_user
        estimated_requests = int(estimated_total_rps * phase_duration_seconds)
        
        return estimated_requests

    def _start_traffic_sync(self):
        """Synchronous traffic start - runs in gevent context."""
        if self.is_running:
            return
            
        self.is_running = True
        
        # Calculate users and spawn rate - conservative for service stability
        total_rps = self.config["requests_per_second"] * len(self.config["endpoints"])
        # Use fewer users with longer wait times to achieve target RPS
        users = min(max(total_rps // 2, 2), 10)  # Much fewer users, minimum 2, max 10
        spawn_rate = min(users, 2)  # Slow spawn rate to avoid overwhelming services
        self.actual_users = users  # Store for realistic calculations
        
        # Extract host and endpoint paths
        host = self._get_host_from_endpoints()
        endpoint_paths = self._extract_endpoints_paths()
        
        print(f"🚀 Starting Locust traffic: {users} users, {spawn_rate} spawn rate")
        print(f"   Host: {host}")
        print(f"   Endpoints: {endpoint_paths}")
        
        # Create Locust environment
        self.environment = Environment(user_classes=[SimpleLoadUser])
        self.environment.target_endpoints = endpoint_paths
        self.environment.host = host
        
        # Create runner
        self.runner = self.environment.create_local_runner()
        
        # Start users
        self.runner.start(user_count=users, spawn_rate=spawn_rate)
        
        # Start stats printer (but suppress it by not starting it)
        # self.stats_greenlet = gevent.spawn(stats_printer, self.environment.stats)
    
    async def start_traffic(self):
        """Start Locust-based traffic generation (async wrapper)."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._start_traffic_sync)
        
    def _stop_traffic_sync(self):
        """Synchronous traffic stop - runs in gevent context."""
        if not self.is_running:
            return
            
        self.is_running = False
        
        if self.runner:
            self.runner.stop()
            
        # if self.stats_greenlet:
        #     self.stats_greenlet.kill()
            
        print("🛑 Locust traffic stopped")
    
    async def stop_traffic(self):
        """Stop Locust traffic generation (async wrapper)."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._stop_traffic_sync)
    
    def reset_phase_metrics(self):
        """Reset metrics for a new measurement phase."""
        if self.environment and self.environment.stats:
            self.environment.stats.reset_all()
        self.phase_start_time = time.time()
        
    def get_phase_metrics(self, phase_duration_seconds: float = None) -> Dict:
        """Get metrics for the current phase."""
        if not self.environment or not self.environment.stats:
            return self._empty_metrics(phase_duration_seconds)
        
        stats = self.environment.stats.total
        
        # Calculate actual phase duration
        actual_duration = 0
        if self.phase_start_time:
            actual_duration = time.time() - self.phase_start_time
        
        # Calculate realistic expected requests based on actual Locust behavior
        expected_requests = 0
        if phase_duration_seconds:
            expected_requests = self._calculate_realistic_expected_requests(phase_duration_seconds)
        
        # Get metrics from Locust stats
        total_requests = stats.num_requests
        failed_requests = stats.num_failures
        successful_requests = total_requests - failed_requests
        
        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
        
        # Locust provides percentiles directly
        p95_latency = stats.get_response_time_percentile(0.95) / 1000.0  # Convert ms to seconds
        max_latency = stats.max_response_time / 1000.0 if stats.max_response_time else 0
        
        metrics = {
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "failed_requests": failed_requests,
            "success_rate_percent": round(success_rate, 2),
            "p95_latency_seconds": round(p95_latency, 3),
            "max_latency_seconds": round(max_latency, 3),
            "actual_duration_seconds": round(actual_duration, 1),
            "expected_requests": expected_requests,
            "current_rps": round(stats.current_rps, 1)
        }
        
        return metrics
    
    def _empty_metrics(self, phase_duration_seconds: float = None) -> Dict:
        """Return empty metrics when no stats available."""
        expected_requests = 0
        if phase_duration_seconds:
            expected_requests = self._calculate_realistic_expected_requests(phase_duration_seconds)
            
        return {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "success_rate_percent": 0,
            "p95_latency_seconds": 0,
            "max_latency_seconds": 0,
            "actual_duration_seconds": 0,
            "expected_requests": expected_requests,
            "current_rps": 0
        }
    
    def adjust_traffic_rate(self, new_rps: int) -> bool:
        """Dynamically adjust traffic rate during execution.
        
        Args:
            new_rps: New target requests per second
            
        Returns:
            True if adjustment succeeded, False otherwise
        """
        if not self.is_running or not self.runner:
            logger.warning("Cannot adjust traffic rate: traffic generator not running")
            return False
        
        # Calculate new user count and spawn rate
        total_rps = new_rps * len(self.config["endpoints"])
        new_users = min(max(total_rps // 2, 2), 30)  # Cap at 30 users for safety
        spawn_rate = 2  # Fixed spawn rate: 2 users/second for deterministic behavior
        
        logger.info(f"Adjusting traffic rate from {self.config['requests_per_second']} RPS to {new_rps} RPS")
        logger.info(f"  Users: {self.actual_users} -> {new_users}, spawn rate: {spawn_rate} users/s")
        
        # Update actual users tracking
        self.actual_users = new_users
        
        # Update config for future reference
        self.config["requests_per_second"] = new_rps
        
        # Restart runner with new user count
        self.runner.start(user_count=new_users, spawn_rate=spawn_rate)
        
        return True
    
    def get_current_rate(self) -> int:
        """Return current configured requests per second."""
        return self.config.get("requests_per_second", 0)

# Keep the old class name for backward compatibility
TrafficGenerator = LocustTrafficGenerator 