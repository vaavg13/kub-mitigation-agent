"""Application registry for managing known applications."""

from pathlib import Path
from typing import Dict, Optional
from .base import Application


class ApplicationRegistry:
    """Registry of known applications and their metadata."""
    
    def __init__(self, metadata_dir: Optional[Path] = None):
        """
        Initialize registry.
        
        Args:
            metadata_dir: Directory containing metadata YAML files.
                         Defaults to apps/metadata/ in package.
        """
        if metadata_dir is None:
            metadata_dir = Path(__file__).parent / "metadata"
        
        self.metadata_dir = metadata_dir
        self._apps: Dict[str, Application] = {}
        self._discover_apps()
    
    def _discover_apps(self):
        """Discover and load all app metadata files."""
        if not self.metadata_dir.exists():
            return
        
        for metadata_file in self.metadata_dir.glob("*.yaml"):
            app_id = metadata_file.stem
            try:
                app = Application(metadata_file)
                self._apps[app_id] = app
            except Exception as e:
                print(f"Warning: Failed to load app metadata {metadata_file}: {e}")
    
    def get(self, app_id: str) -> Optional[Application]:
        """
        Get application by ID.
        
        Args:
            app_id: Application identifier (e.g., 'hotel_reservation')
        
        Returns:
            Application instance or None if not found
        """
        return self._apps.get(app_id)
    
    def get_by_namespace(self, namespace: str) -> Optional[Application]:
        """
        Get application by namespace.
        
        Args:
            namespace: Kubernetes namespace (e.g., 'hotel-reservation')
        
        Returns:
            Application instance or None if not found
        """
        for app in self._apps.values():
            if app.namespace == namespace:
                return app
        return None
    
    def list_apps(self) -> Dict[str, Application]:
        """
        Get all registered applications.
        
        Returns:
            Dict mapping app_id to Application instance
        """
        return self._apps.copy()
    
    def register(self, app_id: str, app: Application):
        """
        Register a new application.
        
        Args:
            app_id: Application identifier
            app: Application instance
        """
        self._apps[app_id] = app


# Global registry instance
_registry = ApplicationRegistry()


def get_app(identifier: str) -> Optional[Application]:
    """
    Get application by ID or namespace.
    
    Tries to match identifier as:
    1. App ID (e.g., 'hotel_reservation')
    2. Namespace (e.g., 'hotel-reservation')
    
    Args:
        identifier: App ID or namespace
    
    Returns:
        Application instance or None if not found
    """
    # Try as app ID first
    app = _registry.get(identifier)
    if app:
        return app
    
    # Try as namespace
    return _registry.get_by_namespace(identifier)


def register_app(app_id: str, app: Application):
    """
    Register a custom application.
    
    Args:
        app_id: Application identifier
        app: Application instance
    """
    _registry.register(app_id, app)


def list_apps() -> Dict[str, Application]:
    """
    List all registered applications.
    
    Returns:
        Dict mapping app_id to Application instance
    """
    return _registry.list_apps()
