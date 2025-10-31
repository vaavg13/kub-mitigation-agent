#!/usr/bin/env python3
"""
Traffic Spike Handler
Handles dynamic traffic rate adjustments to simulate load spikes.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class TrafficSpikeHandler:
    """Handles traffic spike injections by dynamically adjusting traffic generator load."""
    
    SPIKE_MULTIPLIERS = {
        "mild": 2,
        "medium": 3,
        "extreme": 5
    }
    
    def __init__(self, config: Dict[str, Any], traffic_generator):
        """Initialize traffic spike handler.
        
        Args:
            config: Experiment configuration
            traffic_generator: Reference to LocustTrafficGenerator instance
        """
        self.config = config
        self.traffic_generator = traffic_generator
        self.original_users = None
    
    def inject_traffic_spike_only(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply traffic spike by increasing number of users.
        
        Args:
            config: Chaos configuration with intensity ("mild", "medium", "extreme")
            
        Returns:
            Experiment record for cleanup, or None if failed
        """
        intensity = config.get("intensity", "medium")
        multiplier = self.SPIKE_MULTIPLIERS.get(intensity, 2)
        
        # Store original users before spike
        self.original_users = self.traffic_generator.get_current_users()
        original_approx_rps = self.traffic_generator.get_current_approx_rps()
        
        # Calculate target users (multiply by intensity)
        target_users = int(self.original_users * multiplier)
        target_approx_rps = original_approx_rps * multiplier
        
        print(f"📈 === TRAFFIC SPIKE MODE: {intensity.upper()} ({multiplier}x) ===")
        print(f"   Original users: {self.original_users} (~{original_approx_rps:.1f} RPS)")
        print(f"   Target users: {target_users} (~{target_approx_rps:.1f} RPS)")
        print(f"   Ramp-up: 2 users/second until target reached")
        print(f"   Duration: Traffic will be sustained at {target_users} users until experiment ends")
        
        # Apply traffic spike (ramp-up happens automatically via Locust spawn_rate)
        spike_success = self.traffic_generator.adjust_traffic_rate(target_users, new_spawn_rate=2)
        
        if spike_success:
            print(f"✅ Traffic spike applied successfully!")
            print(f"🎯 Traffic ramping up to {target_users} users at 2 users/second")
            print(f"🎯 Traffic will be sustained at peak until experiment completion")
            
            # Return experiment record for cleanup
            experiment_record = {
                "name": f"traffic-spike-{intensity}-{multiplier}x",
                "config": config,
                "traffic_spike": True,
                "original_users": self.original_users,
                "target_users": target_users,
                "multiplier": multiplier
            }
            return experiment_record
        else:
            print(f"❌ Failed to apply traffic spike")
            return None

