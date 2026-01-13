"""Base interface for workload generators."""

from abc import ABC, abstractmethod
from typing import Dict, Any


class WorkloadGenerator(ABC):
    """
    Abstract base class for workload generators.
    
    All workload generators must implement start_traffic() and stop_traffic()
    to provide consistent interface for experiment orchestration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize workload generator.
        
        Args:
            config: Workload configuration dictionary
        """
        self.config = config
        self.is_running = False
    
    @abstractmethod
    async def start_traffic(self):
        """
        Start generating traffic.
        
        Should be idempotent - multiple calls should not cause issues.
        """
        pass
    
    @abstractmethod
    async def stop_traffic(self):
        """
        Stop generating traffic.
        
        Should be idempotent - multiple calls should not cause issues.
        Should clean up all resources.
        """
        pass
