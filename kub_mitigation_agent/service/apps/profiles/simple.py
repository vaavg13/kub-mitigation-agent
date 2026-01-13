"""
Simple traffic profile for basic endpoint testing.

This is a generic profile that tests 1-2 configurable endpoints with
equal probability. Useful for quick tests or applications without
specific traffic patterns defined.
"""

import random
import logging
from locust import HttpUser, task

logger = logging.getLogger(__name__)


class SimpleLoadUser(HttpUser):
    """
    Simple load user for basic endpoint testing.
    
    Tests up to 2 configurable endpoints from the environment's
    target_endpoints list. This is the fallback pattern for apps
    without specific traffic profiles.
    """
    
    connection_timeout = 10.0
    network_timeout = 10.0
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get endpoints from environment (set by traffic generator)
        self.endpoints = getattr(self.environment, 'target_endpoints', ['/'])
    
    def wait_time(self):
        """
        Dynamically get wait time from environment config.
        
        Returns:
            Float: Random wait time between min and max seconds
        """
        wait_min = getattr(self.environment, 'wait_time_min', 1)
        wait_max = getattr(self.environment, 'wait_time_max', 3)
        return random.uniform(wait_min, wait_max)
    
    @task
    def test_endpoint_1(self):
        """Test first endpoint."""
        if len(self.endpoints) >= 1:
            try:
                self.client.get(self.endpoints[0], timeout=10)
            except Exception as e:
                logger.debug(f"Endpoint 1 request failed: {e}")
    
    @task
    def test_endpoint_2(self):
        """Test second endpoint (if configured)."""
        if len(self.endpoints) >= 2:
            try:
                self.client.get(self.endpoints[1], timeout=10)
            except Exception as e:
                logger.debug(f"Endpoint 2 request failed: {e}")
