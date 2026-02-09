"""
Service module.

Provides Kubernetes service management, application deployment,
and telemetry/observability capabilities.

Structure:
- apps/: Application classes with deploy/undeploy logic
- kubectl.py: Kubectl wrapper for K8s operations
- helm.py: Helm wrapper for Helm operations
- k8s.py: Experiment utilities (deployment helpers)
- telemetry/: Prometheus, metrics, observability
"""

# Re-export commonly used items
from .apps import Open5GS, Application
from .kubectl import KubeCtl
from .helm import Helm

__all__ = [
    "Open5GS",
    "Application",
    "KubeCtl",
    "Helm",
]
