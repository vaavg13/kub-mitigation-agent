"""Base Application class for microservice applications."""

from pathlib import Path
from typing import Dict, Any, Optional, Type
import yaml


class Application:
    """
    Base class for microservice applications.
    
    Encapsulates application metadata including deployment configuration,
    workload patterns, and observability settings.
    """
    
    def __init__(self, metadata_file: Path):
        """
        Initialize application from metadata file.
        
        Args:
            metadata_file: Path to YAML metadata file
        """
        self.metadata_file = metadata_file
        self.name: Optional[str] = None
        self.namespace: Optional[str] = None
        self.description: Optional[str] = None
        self.deployment_config: Dict[str, Any] = {}
        self.workload_config: Dict[str, Any] = {}
        self.observability_config: Dict[str, Any] = {}
        
        self.load_metadata()
    
    def load_metadata(self):
        """Load application metadata from YAML file."""
        if not self.metadata_file.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_file}")
        
        with open(self.metadata_file) as f:
            data = yaml.safe_load(f)
        
        self._metadata_data = data  # Store raw data for backward compat
        self.name = data.get("name")
        self.namespace = data.get("namespace")
        self.description = data.get("description", "")
        self.deployment_config = data.get("deployment", {})
        self.workload_config = data.get("workload", {})
        self.observability_config = data.get("observability", {})
    
    def get_traffic_profile_name(self) -> str:
        """
        Get the name of the traffic profile for this app.
        
        Returns:
            Profile name (e.g., 'hotel_reservation', 'simple')
        """
        return self.workload_config.get("profile", "simple")
    
    def get_workload_config(self) -> Dict[str, Any]:
        """
        Get workload configuration for this app.
        
        Returns:
            Dict containing workload parameters (users, spawn_rate, etc.)
        """
        return self.workload_config.copy()
    
    def get_manifest_dir(self) -> str:
        """
        Get the Kubernetes manifest directory for this app.
        
        Returns:
            Relative path to manifest directory
        """
        return self.deployment_config.get("manifest_dir", "kubernetes")
    
    def get_critical_services(self) -> list:
        """
        Get list of critical services to monitor.
        
        Returns:
            List of service names
        """
        # Check both top-level and observability config for backward compat
        return (self.observability_config.get("critical_services", []) or 
                self._metadata_data.get("critical_services", []))
    
    def get_summary(self) -> str:
        """
        Get human-readable summary of application.
        
        Returns:
            Multi-line string describing the application
        """
        return f"""Application: {self.name}
Namespace: {self.namespace}
Description: {self.description}

Traffic Profile: {self.get_traffic_profile_name()}
Critical Services: {', '.join(self.get_critical_services())}
"""
    
    def __repr__(self) -> str:
        return f"Application(name={self.name}, namespace={self.namespace})"
