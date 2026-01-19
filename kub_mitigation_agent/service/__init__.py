"""
Service module.

Provides Kubernetes service management, application deployment,
and telemetry/observability capabilities.

Structure (matches AIOpsLab):
- apps/: Application classes with deploy/undeploy logic
- kubectl.py: Kubectl wrapper for K8s operations
- helm.py: Helm wrapper for Helm operations
- k8s.py: Experiment utilities (deployment helpers)
- telemetry/: Prometheus, metrics, observability
- deployment.py: DEPRECATED - use Application classes instead
"""

# Re-export commonly used items
from .apps import HotelReservation, Application, get_app
from .kubectl import KubeCtl
from .helm import Helm

# DEPRECATED - kept for backward compatibility
from .deployment import SimpleK8sDeploymentManager

__all__ = [
    "HotelReservation",
    "Application",
    "get_app",
    "KubeCtl",
    "Helm",
    "SimpleK8sDeploymentManager",  # DEPRECATED
]
