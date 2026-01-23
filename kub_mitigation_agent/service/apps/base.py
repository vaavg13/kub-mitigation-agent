"""Base Application class for microservice applications (Helm-only)."""

import json
from typing import Dict, Any, Optional
from kub_mitigation_agent.paths import TARGET_MICROSERVICES


class Application:
    """
    Base class for microservice applications.
    
    Follows AIOpsLab's pattern for application management.
    """
    
    def __init__(self, config_file: str):
        """
        Initialize application from config file.
        
        Args:
            config_file: Path to JSON metadata file
        """
        self.config_file = config_file
        self.name: Optional[str] = None
        self.namespace: Optional[str] = None
        self.helm_configs: Dict[str, Any] = {}
        
        # Additional attributes
        self.description: Optional[str] = None
        self.workload_config: Dict[str, Any] = {}
        self.observability_config: Dict[str, Any] = {}
        self.istio_injection_enabled: bool = False
    
    def load_app_json(self):
        """
        Load application metadata from JSON file.
        
        Override this method in subclasses to load additional attributes.
        """
        with open(self.config_file, "r") as file:
            metadata = json.load(file)

        self.name = metadata["Name"]
        self.namespace = metadata["Namespace"]
        self.description = metadata.get("Desc", "")
        self.istio_injection_enabled = bool(metadata.get("Istio Injection", False))
        
        if "Helm Config" in metadata:
            self.helm_configs = metadata["Helm Config"]
            chart_path = self.helm_configs.get("chart_path")
            
            if chart_path and not self.helm_configs.get("remote_chart", False):
                self.helm_configs["chart_path"] = str(TARGET_MICROSERVICES / chart_path)
        
        # Load workload and observability configs if present
        if "Workload" in metadata:
            self.workload_config = metadata["Workload"]
        
        if "Observability" in metadata:
            self.observability_config = metadata["Observability"]

    def get_app_json(self) -> dict:
        """
        Get application metadata in JSON format.
        
        Returns:
            dict: application metadata
        """
        with open(self.config_file, "r") as file:
            app_json = json.load(file)
        return app_json

    def get_app_summary(self) -> str:
        """
        Get a summary of the application metadata in string format.
        
        Returns:
            str: application metadata
        """
        app_json = self.get_app_json()
        app_name = app_json.get("Name", "")
        namespace = app_json.get("Namespace", "")
        desc = app_json.get("Desc", "")
        supported_operations = app_json.get("Supported Operations", [])
        operations_str = "\n".join([f"  - {op}" for op in supported_operations])

        description = f"Service Name: {app_name}\nNamespace: {namespace}\nDescription: {desc}\nSupported Operations:\n{operations_str}"

        return description
    
    def get_summary(self) -> str:
        """Alias for get_app_summary for backward compatibility."""
        return self.get_app_summary()

    def create_namespace(self):
        """Create the namespace for the application if it doesn't exist."""
        result = self.kubectl.exec_command(f"kubectl get namespace {self.namespace}")
        if "notfound" in result.lower():
            print(f"Namespace {self.namespace} not found. Creating namespace.")
            create_namespace_command = f"kubectl create namespace {self.namespace}"
            create_result = self.kubectl.exec_command(create_namespace_command)
            print(f"Namespace {self.namespace} created successfully: {create_result}")
        else:
            print(f"Namespace {self.namespace} already exists.")

        # Always apply Istio injection label if enabled (even for existing namespaces)
        if self.istio_injection_enabled:
            label_cmd = f"kubectl label namespace {self.namespace} istio-injection=enabled --overwrite"
            result = self.kubectl.exec_command(label_cmd)
            print(f"Istio injection enabled for namespace {self.namespace}")

    def cleanup(self):
        """Delete the entire namespace for the application."""
        self.kubectl.delete_namespace(self.namespace)
    
    # Helper methods for backward compatibility
    def get_traffic_profile_name(self) -> str:
        """Get the traffic profile name."""
        return self.workload_config.get("profile", "simple")
    
    def get_workload_config(self) -> Dict[str, Any]:
        """Get workload configuration."""
        return self.workload_config.copy()
    
    def get_critical_services(self) -> list:
        """Get list of critical services."""
        app_json = self.get_app_json()
        return (self.observability_config.get("critical_services", []) or 
                app_json.get("Critical Services", []))
    
    def __repr__(self) -> str:
        return f"Application(name={self.name}, namespace={self.namespace})"
