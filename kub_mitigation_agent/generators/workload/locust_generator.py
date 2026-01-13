"""Locust-based traffic generator using app-specific profiles."""

import asyncio
import logging
from typing import Dict, Any
from locust import HttpUser
from locust.env import Environment

from kub_mitigation_agent.service.apps.profiles import get_profile
from .base import WorkloadGenerator

logger = logging.getLogger(__name__)


class LocustTrafficGenerator(WorkloadGenerator):
    """
    Locust-based traffic generator for reproducible load testing.
    
    This generator uses app-specific traffic profiles from the apps.profiles
    package to generate realistic workload patterns. It handles starting and
    stopping traffic generation, while metrics collection is done separately
    by the experiment orchestrator using Istio/Prometheus.
    
    Usage:
        config = {
            "workload_pattern": "hotel_reservation",  # or "simple"
            "host": "http://ingress-gateway:80",
            "num_users": 10,
            "spawn_rate": 2,
            "wait_time_min": 1,
            "wait_time_max": 3,
        }
        generator = LocustTrafficGenerator(config)
        await generator.start_traffic()
        # ... traffic runs continuously ...
        await generator.stop_traffic()
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Locust traffic generator.
        
        Args:
            config: Workload configuration dict with keys:
                - workload_pattern: Name of traffic profile (default: "simple")
                - host: Target host URL (required)
                - num_users: Number of concurrent users (default: 10)
                - spawn_rate: Users spawned per second (default: 2)
                - wait_time_min: Minimum wait between requests (default: 1)
                - wait_time_max: Maximum wait between requests (default: 3)
                - endpoints: List of endpoints for simple pattern (optional)
        """
        super().__init__(config)
        self.environment = None
        self.runner = None
        
        # Get app-specific traffic profile
        pattern = config.get("workload_pattern", "simple")
        try:
            self.user_class = get_profile(pattern)
            logger.info(f"Loaded traffic profile: {pattern} ({self.user_class.__name__})")
        except ValueError as e:
            logger.error(f"Failed to load traffic profile: {e}")
            raise
        
        # Suppress Locust's verbose logging
        logging.getLogger("locust").setLevel(logging.WARNING)
    
    def _start_traffic_sync(self):
        """
        Synchronous traffic start - runs in gevent context.
        
        This method runs in a separate thread to avoid blocking the
        async event loop while gevent is active.
        """
        if self.is_running:
            logger.warning("Traffic generator is already running")
            return
        
        self.is_running = True
        
        # Get configuration parameters
        users = self.config.get("num_users", 10)
        spawn_rate = self.config.get("spawn_rate", 2)
        wait_min = self.config.get("wait_time_min", 1)
        wait_max = self.config.get("wait_time_max", 3)
        host = self.config.get("host", "http://localhost")
        endpoints = self.config.get("endpoints", ["/"])
        
        # Calculate approximate RPS for informational purposes
        avg_wait = (wait_min + wait_max) / 2.0
        approx_rps = users / avg_wait
        
        logger.info(f"🚀 Starting Locust traffic:")
        logger.info(f"   Profile: {self.user_class.__name__}")
        logger.info(f"   Users: {users}")
        logger.info(f"   Spawn rate: {spawn_rate} users/second")
        logger.info(f"   Wait time: {wait_min}-{wait_max} seconds between requests")
        logger.info(f"   Approximate RPS: {approx_rps:.1f}")
        logger.info(f"   Host: {host}")
        if self.user_class.__name__ == "SimpleLoadUser":
            logger.info(f"   Endpoints: {endpoints}")
        
        # Create Locust environment with selected user class
        self.environment = Environment(user_classes=[self.user_class])
        self.environment.host = host
        self.environment.wait_time_min = wait_min
        self.environment.wait_time_max = wait_max
        
        # For SimpleLoadUser, set endpoints on environment
        if self.user_class.__name__ == "SimpleLoadUser":
            self.environment.target_endpoints = endpoints
        
        # Create runner and start users
        self.runner = self.environment.create_local_runner()
        self.runner.start(user_count=users, spawn_rate=spawn_rate)
        
        logger.info("✅ Traffic generation started")
    
    async def start_traffic(self):
        """
        Start Locust-based traffic generation (async wrapper).
        
        Traffic will run continuously until stop_traffic() is called.
        This method returns immediately after starting the traffic.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._start_traffic_sync)
    
    def _stop_traffic_sync(self):
        """
        Synchronous traffic stop - runs in gevent context.
        
        Stops all users and cleans up Locust environment.
        """
        if not self.is_running:
            logger.warning("Traffic generator is not running")
            return
        
        self.is_running = False
        
        if self.runner:
            self.runner.stop()
            logger.info("🛑 Locust traffic stopped")
    
    async def stop_traffic(self):
        """
        Stop Locust traffic generation (async wrapper).
        
        Stops all virtual users and cleans up resources.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._stop_traffic_sync)
