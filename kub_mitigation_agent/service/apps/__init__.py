"""
Application management package.

Provides application definitions, metadata, and traffic profiles for
microservices under test.

Structure:
- base.py: Base Application class
- hotel_reservation.py: HotelReservation app class (with deploy/undeploy)
- metadata/: App configuration YAML files (minimal)
- profiles/: Traffic patterns (Locust HttpUser classes)
- registry.py: App discovery and factory
"""

from .base import Application
from .hotel_reservation import HotelReservation
from .registry import get_app, register_app, list_apps

__all__ = [
    "Application",
    "HotelReservation",
    "get_app",
    "register_app",
    "list_apps",
]
