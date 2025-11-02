import asyncio
import logging
from typing import Dict
from locust import HttpUser, task
from locust.env import Environment

logger = logging.getLogger(__name__)

class SimpleLoadUser(HttpUser):
    """Simple Locust user for testing specific endpoints."""
    connection_timeout = 10.0
    network_timeout = 10.0
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.endpoints = getattr(self.environment, 'target_endpoints', ['/'])
    
    def wait_time(self):
        """Dynamically get wait time from environment config."""
        wait_min = getattr(self.environment, 'wait_time_min', 1)
        wait_max = getattr(self.environment, 'wait_time_max', 3)
        # Return a random value between min and max
        import random
        return random.uniform(wait_min, wait_max)
    
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
    """Locust-based traffic generator for reproducible load testing.
    
    This class ONLY handles starting and stopping traffic generation.
    Metrics collection is done separately by the experiment orchestrator
    using Istio/Prometheus metrics from the ingress gateway.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.environment = None
        self.runner = None
        self.is_running = False
        
        # Suppress Locust's verbose logging using standard Python logging
        logging.getLogger("locust").setLevel(logging.WARNING)

    def _start_traffic_sync(self):
        """Synchronous traffic start - runs in gevent context."""
        if self.is_running:
            return
            
        self.is_running = True
        
        # Get configuration
        users = self.config.get("num_users", 10)
        spawn_rate = self.config.get("spawn_rate", 2)
        wait_min = self.config.get("wait_time_min", 1)
        wait_max = self.config.get("wait_time_max", 3)
        host = self.config.get("host", "http://localhost")
        endpoints = self.config.get("endpoints", ["/"])
        
        # Calculate approximate RPS for display
        avg_wait = (wait_min + wait_max) / 2.0
        approx_rps = users / avg_wait
        
        print(f"🚀 Starting Locust traffic:")
        print(f"   Users: {users}")
        print(f"   Spawn rate: {spawn_rate} users/second")
        print(f"   Wait time: {wait_min}-{wait_max} seconds between requests")
        print(f"   Approximate RPS: {approx_rps:.1f}")
        print(f"   Host: {host}")
        print(f"   Endpoints: {endpoints}")
        
        # Create Locust environment
        self.environment = Environment(user_classes=[SimpleLoadUser])
        self.environment.target_endpoints = endpoints
        self.environment.host = host
        self.environment.wait_time_min = wait_min
        self.environment.wait_time_max = wait_max
        
        # Create runner
        self.runner = self.environment.create_local_runner()
        
        # Start users
        self.runner.start(user_count=users, spawn_rate=spawn_rate)
    
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
        
        print("🛑 Locust traffic stopped")
    
    async def stop_traffic(self):
        """Stop Locust traffic generation (async wrapper)."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._stop_traffic_sync)
    
    def adjust_traffic_rate(self, new_num_users: int, new_spawn_rate: int = None) -> bool:
        """Dynamically adjust traffic rate during execution by changing number of users.
        
        Args:
            new_num_users: New number of users to spawn
            new_spawn_rate: Optional new spawn rate (defaults to config spawn_rate)
            
        Returns:
            True if adjustment succeeded, False otherwise
        """
        if not self.is_running or not self.runner:
            logger.warning("Cannot adjust traffic rate: traffic generator not running")
            return False
        
        if new_spawn_rate is None:
            new_spawn_rate = self.config.get("spawn_rate", 2)
        
        old_users = self.config.get("num_users", 0)
        
        # Calculate approximate RPS for logging
        wait_min = self.config.get("wait_time_min", 1)
        wait_max = self.config.get("wait_time_max", 3)
        avg_wait = (wait_min + wait_max) / 2.0
        old_approx_rps = old_users / avg_wait if avg_wait > 0 else 0
        new_approx_rps = new_num_users / avg_wait if avg_wait > 0 else 0
        
        logger.info(f"Adjusting traffic rate:")
        logger.info(f"  Users: {old_users} -> {new_num_users}")
        logger.info(f"  Approximate RPS: {old_approx_rps:.1f} -> {new_approx_rps:.1f}")
        logger.info(f"  Spawn rate: {new_spawn_rate} users/s")
        
        # Update config for future reference
        self.config["num_users"] = new_num_users
        
        # Restart runner with new user count
        self.runner.start(user_count=new_num_users, spawn_rate=new_spawn_rate)
        
        return True

# Keep the old class name for backward compatibility
TrafficGenerator = LocustTrafficGenerator 