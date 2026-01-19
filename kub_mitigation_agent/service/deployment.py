"""
DEPRECATED: Simple Kubernetes Deployment Manager

This module is deprecated and will be removed in a future version.
Use the new Application classes (e.g., HotelReservation) with kubectl/helm wrappers instead.

Legacy code for deploying real microservice applications.
"""

import warnings
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

import yaml
from kubernetes import client, config

logger = logging.getLogger(__name__)

warnings.warn(
    "deployment.py (SimpleK8sDeploymentManager) is deprecated. "
    "Use Application classes (e.g., HotelReservation) with kubectl/helm wrappers instead.",
    DeprecationWarning,
    stacklevel=2
)


class SimpleK8sDeploymentManager:
    """
    Simple deployment manager for real microservices applications.
    
    Reads K8s manifests from a directory and applies them using kubectl.
    No synthetic workload generation - just deploys real apps.
    """
    
    def __init__(self, app_dir: str, namespace: str, app_config: Optional[Dict[str, Any]] = None):
        """
        Initialize deployment manager.
        
        Args:
            app_dir: Path to application directory
            namespace: Kubernetes namespace
            app_config: Optional app configuration dict (from app-config.yaml)
        """
        self.app_dir = Path(app_dir)
        self.namespace = namespace
        self.app_config = app_config or {}
        
        # Determine manifests directory
        manifests_dir_name = self.app_config.get('manifests_dir', 'manifests')
        self.manifests_dir = self.app_dir / manifests_dir_name
        
        # Load Kubernetes config
        try:
            config.load_kube_config()
            self.core_api = client.CoreV1Api()
            self.apps_api = client.AppsV1Api()
        except Exception as e:
            logger.warning(f"Failed to load kubeconfig: {e}")
            self.core_api = None
            self.apps_api = None
    
    @classmethod
    def from_deployment_dir(cls, app_dir: str) -> "SimpleK8sDeploymentManager":
        """
        Create deployment manager from app directory.
        
        Reads app-config.yaml if it exists to determine namespace and settings.
        
        Args:
            app_dir: Path to application directory
            
        Returns:
            SimpleK8sDeploymentManager instance
        """
        app_dir_path = Path(app_dir)
        config_path = app_dir_path / "app-config.yaml"
        
        # Load app config if it exists
        app_config = {}
        namespace = app_dir_path.name  # Default: use directory name as namespace
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    app_config = yaml.safe_load(f) or {}
                namespace = app_config.get('namespace', namespace)
                logger.info(f"Loaded app config from {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load app config: {e}, using defaults")
        
        return cls(str(app_dir_path), namespace, app_config)
    
    def deploy(self) -> bool:
        """
        Deploy application to Kubernetes.
        
        Steps:
        1. Create namespace if it doesn't exist
        2. Apply all manifests in the manifests directory
        3. Wait for resources to be created
        
        Returns:
            bool: True if deployment succeeded, False otherwise
        """
        try:
            logger.info(f"Deploying application from {self.app_dir}")
            logger.info(f"Namespace: {self.namespace}")
            logger.info(f"Manifests directory: {self.manifests_dir}")
            
            # Check if manifests directory exists
            if not self.manifests_dir.exists():
                logger.error(f"Manifests directory not found: {self.manifests_dir}")
                return False
            
            # Get all YAML files
            manifest_files = sorted(self.manifests_dir.glob("*.yaml")) + \
                           sorted(self.manifests_dir.glob("*.yml"))
            
            if not manifest_files:
                logger.error(f"No manifest files found in {self.manifests_dir}")
                return False
            
            logger.info(f"Found {len(manifest_files)} manifest files")
            
            # Create namespace first
            if not self._create_namespace():
                logger.warning("Namespace creation failed, may already exist")
            
            # Apply each manifest
            failed_manifests = []
            for manifest_file in manifest_files:
                if not self._apply_manifest(manifest_file):
                    failed_manifests.append(manifest_file.name)
            
            if failed_manifests:
                logger.error(f"Failed to apply manifests: {', '.join(failed_manifests)}")
                return False
            
            logger.info(f"✅ Successfully deployed {len(manifest_files)} manifests")
            return True
            
        except Exception as e:
            logger.error(f"Deployment failed: {e}", exc_info=True)
            return False
    
    def undeploy(self) -> bool:
        """
        Undeploy application from Kubernetes.
        
        Simply deletes the namespace, which removes all resources.
        
        Returns:
            bool: True if undeployment succeeded, False otherwise
        """
        try:
            logger.info(f"Undeploying application: deleting namespace {self.namespace}")
            
            cmd = ["kubectl", "delete", "namespace", self.namespace, "--ignore-not-found=true"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info(f"✅ Successfully deleted namespace {self.namespace}")
                # Wait a bit for namespace deletion to propagate
                time.sleep(5)
                return True
            else:
                logger.error(f"Failed to delete namespace: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Undeployment failed: {e}", exc_info=True)
            return False
    
    def _create_namespace(self) -> bool:
        """Create Kubernetes namespace if it doesn't exist."""
        try:
            cmd = ["kubectl", "create", "namespace", self.namespace]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                logger.info(f"Created namespace: {self.namespace}")
                return True
            elif "AlreadyExists" in result.stderr:
                logger.info(f"Namespace already exists: {self.namespace}")
                return True
            else:
                logger.warning(f"Namespace creation issue: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to create namespace: {e}")
            return False
    
    def _apply_manifest(self, manifest_file: Path) -> bool:
        """
        Apply a single manifest file using kubectl.
        
        Args:
            manifest_file: Path to manifest file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            cmd = [
                "kubectl", "apply",
                "-f", str(manifest_file),
                "-n", self.namespace
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.debug(f"Applied: {manifest_file.name}")
                return True
            else:
                logger.error(f"Failed to apply {manifest_file.name}: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error applying manifest {manifest_file.name}: {e}")
            return False
    
    def get_deployments(self) -> List[str]:
        """
        Get list of deployment names in the namespace.
        
        Returns:
            List of deployment names
        """
        try:
            if not self.apps_api:
                # Fallback to kubectl
                return self._get_deployments_kubectl()
            
            deployments = self.apps_api.list_namespaced_deployment(namespace=self.namespace)
            return [dep.metadata.name for dep in deployments.items]
            
        except Exception as e:
            logger.error(f"Failed to get deployments: {e}")
            return []
    
    def _get_deployments_kubectl(self) -> List[str]:
        """Get deployments using kubectl."""
        try:
            cmd = ["kubectl", "get", "deployments", "-n", self.namespace, "-o", "name"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                # Output format: "deployment/name", extract just the name
                return [line.split('/')[-1] for line in result.stdout.strip().split('\n') if line]
            return []
            
        except Exception as e:
            logger.error(f"Failed to get deployments via kubectl: {e}")
            return []
    
    def get_services(self) -> List[str]:
        """
        Get list of service names in the namespace.
        
        Returns:
            List of service names
        """
        try:
            if not self.core_api:
                return self._get_services_kubectl()
            
            services = self.core_api.list_namespaced_service(namespace=self.namespace)
            return [svc.metadata.name for svc in services.items]
            
        except Exception as e:
            logger.error(f"Failed to get services: {e}")
            return []
    
    def _get_services_kubectl(self) -> List[str]:
        """Get services using kubectl."""
        try:
            cmd = ["kubectl", "get", "services", "-n", self.namespace, "-o", "name"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                return [line.split('/')[-1] for line in result.stdout.strip().split('\n') if line]
            return []
            
        except Exception as e:
            logger.error(f"Failed to get services via kubectl: {e}")
            return []
    
    def is_deployed(self) -> bool:
        """
        Check if application is deployed (namespace exists with resources).
        
        Returns:
            bool: True if deployed, False otherwise
        """
        try:
            cmd = ["kubectl", "get", "namespace", self.namespace]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                return False
            
            # Check if there are any pods
            cmd = ["kubectl", "get", "pods", "-n", self.namespace, "--no-headers"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            return result.returncode == 0 and result.stdout.strip() != ""
            
        except Exception as e:
            logger.error(f"Failed to check deployment status: {e}")
            return False
