"""
Workload generation package.

Provides generic workload generators that use app-specific traffic profiles.
"""

from .locust_generator import LocustTrafficGenerator

__all__ = [
    "LocustTrafficGenerator",
]
