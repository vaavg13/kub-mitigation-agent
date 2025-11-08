#!/usr/bin/env python3
"""
No-failure anomaly: baseline experiment with no chaos injection.
"""

from typing import Dict
from .anomaly_base import Anomaly


class NoFailureAnomaly(Anomaly):
    """Represents a baseline experiment with no chaos injection."""

    def get_info(self) -> Dict:
        """Return baseline experiment configuration."""
        return {
            "mode": "no_failure",
            "provider": "none",
            "type": "baseline",
        }

    def start(self) -> Dict:
        """No-op for baseline experiments."""
        self._handle = {
            "mode": "no_failure",
            "provider": "none",
            "id": "baseline",
        }
        return self._handle

    def stop(self) -> bool:
        """No-op cleanup for baseline experiments."""
        self._handle = None
        return True
    
    @staticmethod
    def cleanup_all(**kwargs):
        """No-op cleanup (no actual chaos to clean up)."""
        return {"success": True, "message": "No cleanup needed for no-failure anomaly"}

