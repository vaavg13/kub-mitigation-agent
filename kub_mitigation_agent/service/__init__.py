"""
Service module.

Provides Kubernetes service management, application deployment,
and telemetry/observability capabilities.

Structure (matches AIOpsLab):
- apps/: Application classes with deploy/undeploy logic
- telemetry/: Prometheus, metrics, observability
- k8s.py: Kubernetes utilities
- deployment.py: Deployment management
"""

# Re-export commonly used items
from .apps import HotelReservation, Application, get_app
from .deployment import SimpleK8sDeploymentManager

__all__ = [
    "HotelReservation",
    "Application",
    "get_app",
    "SimpleK8sDeploymentManager",
]
