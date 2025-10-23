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
        self.original_rps = None
    
    def inject_traffic_spike_only(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply traffic spike by increasing requests per second.
        
        Args:
            config: Chaos configuration with intensity ("mild", "medium", "extreme")
            
        Returns:
            Experiment record for cleanup, or None if failed
        """
        intensity = config.get("intensity", "medium")
        multiplier = self.SPIKE_MULTIPLIERS.get(intensity, 2)
        
        # Store original RPS before spike
        self.original_rps = self.traffic_generator.get_current_rate()
        
        # Calculate target RPS
        target_rps = self.original_rps * multiplier
        
        print(f"📈 === TRAFFIC SPIKE MODE: {intensity.upper()} ({multiplier}x) ===")
        print(f"   Original RPS: {self.original_rps}")
        print(f"   Target RPS: {target_rps} ({multiplier}x spike)")
        print(f"   Ramp-up: 2 users/second until target reached")
        print(f"   Duration: Traffic will be sustained at {target_rps} RPS until experiment ends")
        
        # Apply traffic spike (ramp-up happens automatically via Locust spawn_rate)
        spike_success = self.traffic_generator.adjust_traffic_rate(target_rps)
        
        if spike_success:
            print(f"✅ Traffic spike applied successfully!")
            print(f"🎯 Traffic ramping up to {target_rps} RPS at 2 users/second")
            print(f"🎯 Traffic will be sustained at peak until experiment completion")
            
            # Return experiment record for cleanup
            experiment_record = {
                "name": f"traffic-spike-{intensity}-{multiplier}x",
                "config": config,
                "traffic_spike": True,
                "original_rps": self.original_rps,
                "target_rps": target_rps,
                "multiplier": multiplier
            }
            return experiment_record
        else:
            print(f"❌ Failed to apply traffic spike")
            return None

