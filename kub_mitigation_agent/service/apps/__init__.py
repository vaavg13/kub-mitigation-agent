"""
Application management package.

Provides application definitions, metadata, and deployment management
for applications under test.

Structure:
- base.py: Base Application class
- open5gs.py: Open5GS 5G Core app class (with deploy/undeploy)
- metadata/: App configuration JSON and YAML files
- profiles/: Traffic patterns (UERANSIM for 5G)
"""

from .base import Application
from .open5gs import Open5GS

__all__ = [
    "Application",
    "Open5GS",
]
