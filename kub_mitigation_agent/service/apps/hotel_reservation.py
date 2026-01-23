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
        
        self.load_app_json()
        self.create_namespace()
    
    def load_app_json(self):
        """Load application-specific metadata."""
        super().load_app_json()
        metadata = self.get_app_json()
        self.frontend_service = metadata.get("frontend_service", "frontend")
        self.frontend_port = metadata.get("frontend_port", 5000)
    
    def deploy(self):
        """Deploy the application using Helm."""
        self.deploy_helm()
    
    def deploy_helm(self):
        """Deploy using Helm chart."""
        print(f"Deploying with Helm in namespace: {self.namespace}")
        
        # Ensure namespace exists with proper labels before Helm install
        self.create_namespace()
        
        # Apply Istio injection label if enabled (ensure it's set every time)
        if self.istio_injection_enabled:
            print(f"Applying istio-injection label to namespace {self.namespace}")
            label_cmd = f"kubectl label namespace {self.namespace} istio-injection=enabled --overwrite"
            result = self.kubectl.exec_command(label_cmd)
            print(f"Istio injection label applied: {result.strip()}")
        
        Helm.install(**self.helm_configs)
        Helm.assert_if_deployed(self.helm_configs["namespace"])
    
    def delete(self):
        """Delete the application (Helm)."""
        self.delete_helm()
    
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
