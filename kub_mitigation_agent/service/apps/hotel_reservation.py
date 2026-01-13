"""Hotel Reservation application class with deployment logic."""

from pathlib import Path
from .base import Application
from ...paths import APPS_DIR, APP_METADATA_DIR


class HotelReservation(Application):
    """
    Hotel Reservation application.
    
    Provides deployment, cleanup, and management for the Hotel Reservation
    microservices application from DeathStarBench.
    """
    
    def __init__(self, app_dir: str = None):
        """
        Initialize Hotel Reservation application.
        
        Args:
            app_dir: Optional path to app directory.
                    Defaults to APPS/real-apps/hotel-reservation
        """
        # Load metadata
        metadata_file = APP_METADATA_DIR / "hotel_reservation.yaml"
        super().__init__(metadata_file)
        
        # Set app directory
        if app_dir is None:
            app_dir = APPS_DIR / "hotel-reservation"
        self.app_dir = Path(app_dir)
        
        # Deployment manager will be initialized lazily to avoid circular imports
        self._deployment_manager = None
    
    @property
    def deployment_manager(self):
        """Lazy initialization of deployment manager to avoid circular imports."""
        if self._deployment_manager is None:
            from ..deployment import SimpleK8sDeploymentManager
            self._deployment_manager = SimpleK8sDeploymentManager(
                str(self.app_dir),
                self.namespace
            )
        return self._deployment_manager
    
    def deploy(self, wait_for_ready: bool = True) -> bool:
        """
        Deploy the Hotel Reservation application.
        
        Args:
            wait_for_ready: Whether to wait for pods to be ready
        
        Returns:
            bool: True if deployment succeeded
        """
        print(f"📦 Deploying {self.name}...")
        print(f"   Namespace: {self.namespace}")
        print(f"   App directory: {self.app_dir}")
        
        success = self.deployment_manager.deploy()
        
        if success and wait_for_ready:
            print("⏳ Waiting for pods to be ready...")
            # Wait logic handled by deployment_manager
        
        if success:
            print(f"✅ {self.name} deployed successfully")
        else:
            print(f"❌ {self.name} deployment failed")
        
        return success
    
    def undeploy(self) -> bool:
        """
        Undeploy the Hotel Reservation application.
        
        Deletes the namespace and all resources.
        
        Returns:
            bool: True if undeployment succeeded
        """
        print(f"🗑️  Undeploying {self.name}...")
        success = self.deployment_manager.undeploy()
        
        if success:
            print(f"✅ {self.name} undeployed successfully")
        else:
            print(f"❌ {self.name} undeployment failed")
        
        return success
    
    def is_deployed(self) -> bool:
        """
        Check if the application is currently deployed.
        
        Returns:
            bool: True if deployed and running
        """
        return self.deployment_manager.is_deployed()
    
    def get_services(self) -> list:
        """
        Get list of services in the application.
        
        Returns:
            List of service names
        """
        return self.deployment_manager.get_services()
    
    def get_deployments(self) -> list:
        """
        Get list of deployments in the application.
        
        Returns:
            List of deployment names
        """
        return self.deployment_manager.get_deployments()
    
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
        return f"http://frontend.{self.namespace}:5000"
