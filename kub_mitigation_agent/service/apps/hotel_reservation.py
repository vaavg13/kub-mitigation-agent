"""Hotel Reservation application class with deployment logic."""

import time
from .base import Application
from ..kubectl import KubeCtl
from ..helm import Helm
from ...paths import HOTEL_RESERVATION_METADATA


class HotelReservation(Application):
    """
    Hotel Reservation application.
    
    Provides deployment, cleanup, and management for the Hotel Reservation
    microservices application from DeathStarBench.
    """
    
    def __init__(self):
        """Initialize Hotel Reservation application."""
        super().__init__(HOTEL_RESERVATION_METADATA)
        self.kubectl = KubeCtl()
        self.helm_deploy = True  # Use Helm charts by default
        
        self.load_app_json()
        self.create_namespace()
    
    def load_app_json(self):
        """Load application-specific metadata."""
        super().load_app_json()
        metadata = self.get_app_json()
        self.frontend_service = metadata.get("frontend_service", "frontend")
        self.frontend_port = metadata.get("frontend_port", 5000)
    
    def deploy(self):
        """Deploy the application (Helm or K8s based on helm_deploy flag)."""
        if self.helm_deploy:
            self.deploy_helm()
        else:
            self.deploy_k8s()
    
    def deploy_k8s(self):
        """Deploy using raw Kubernetes configurations."""
        print(f"Deploying Kubernetes configurations in namespace: {self.namespace}")
        self.kubectl.apply_configs(self.namespace, str(self.k8s_deploy_path))
        self.kubectl.wait_for_ready(self.namespace)
    
    def deploy_without_wait(self):
        """Deploy the Kubernetes configurations without waiting for ready."""
        print(f"Deploying Kubernetes configurations in namespace: {self.namespace}")
        self.kubectl.apply_configs(self.namespace, str(self.k8s_deploy_path))
        print(f"Waiting for stability...")
        time.sleep(30)
    
    def deploy_helm(self):
        """Deploy using Helm chart."""
        print(f"Deploying with Helm in namespace: {self.namespace}")
        Helm.install(**self.helm_configs)
        Helm.assert_if_deployed(self.helm_configs["namespace"])
    
    def delete(self):
        """Delete the application (Helm or K8s based on helm_deploy flag)."""
        if self.helm_deploy:
            self.delete_helm()
        else:
            self.delete_k8s()
    
    def delete_k8s(self):
        """Delete using raw Kubernetes configurations."""
        self.kubectl.delete_configs(self.namespace, str(self.k8s_deploy_path))
    
    def delete_helm(self):
        """Delete the Helm deployment."""
        Helm.uninstall(**self.helm_configs)
    
    def cleanup(self):
        """Delete the entire namespace for the hotel reservation application."""
        self.kubectl.delete_namespace(self.namespace)
        time.sleep(10)
        
        # Clean up persistent volumes
        pvs = self.kubectl.exec_command(
            f"kubectl get pv --no-headers | grep '{self.namespace}' | awk '{{print $1}}'"
        ).splitlines()

        for pv in pvs:
            if pv.strip():
                # Check if the PV is in a 'Terminating' state and remove the finalizers if necessary
                self._remove_pv_finalizers(pv)
                delete_command = f"kubectl delete pv {pv}"
                delete_result = self.kubectl.exec_command(delete_command)
                print(f"Deleted PersistentVolume {pv}: {delete_result.strip()}")
        time.sleep(5)
    
    def _remove_pv_finalizers(self, pv_name: str):
        """Remove finalizers from the PersistentVolume to prevent it from being stuck in a 'Terminating' state."""
        patch_command = (
            f'kubectl patch pv {pv_name} -p \'{{"metadata":{{"finalizers":null}}}}\''
        )
        _ = self.kubectl.exec_command(patch_command)
    
    def is_deployed(self) -> bool:
        """
        Check if the application is currently deployed.
        
        Returns:
            bool: True if deployed and running
        """
        try:
            pods = self.kubectl.list_pods(self.namespace)
            return len(pods.items) > 0
        except:
            return False
    
    def get_services(self) -> list:
        """
        Get list of services in the application.
        
        Returns:
            List of service names
        """
        try:
            services = self.kubectl.list_services(self.namespace)
            return [svc.metadata.name for svc in services.items]
        except:
            return []
    
    def get_frontend_url(self, ingress_host: str = None) -> str:
        """
        Get the frontend URL for the application.
        
        Args:
            ingress_host: Optional ingress host (e.g., "http://192.168.100.10:31596")
        
        Returns:
            Frontend URL string
        """
        if ingress_host:
            return ingress_host
        
        # Default: assume service is exposed
        return f"http://{self.frontend_service}.{self.namespace}:{self.frontend_port}"
