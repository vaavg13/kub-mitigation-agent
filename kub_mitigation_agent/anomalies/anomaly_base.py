
from typing import Dict, Optional, Any


class Anomaly:
    """Base anomaly interface for unified lifecycle management.

    Subclasses must implement get_info, start, stop, and cleanup_all.
    
    Lifecycle:
    - get_info(): Returns metadata about this anomaly instance
    - start(): Starts this specific anomaly instance
    - stop(): Stops this specific anomaly instance
    - cleanup_all(): Static method to stop ALL anomalies of this type system-wide
    """

    def __init__(self):
        self._handle: Optional[Dict] = None

    def get_info(self) -> Dict:
        """Return a preview of what will be deployed.

        This should include provider, type, target, and payload summary.
        """
        raise NotImplementedError

    def start(self) -> Dict:
        """Start the anomaly and return a handle.

        The handle should be stored internally and returned so that
        orchestration layers can log or persist it if needed.
        """
        raise NotImplementedError

    def stop(self) -> bool:
        """Stop the anomaly using the internal handle. Idempotent."""
        raise NotImplementedError
    
    @staticmethod
    def cleanup_all(**kwargs) -> Dict[str, Any]:
        """
        Stop ALL anomalies of this type across the entire system.
        
        This is the nuclear option used for pre-experiment cleanup to ensure
        no residual anomalies are running from previous experiments.
        
        Subclasses must implement this to provide system-wide cleanup.
        
        Args:
            **kwargs: Implementation-specific parameters
                     (e.g., namespaces for pod anomalies, nodes for node anomalies)
            
        Returns:
            Dict with cleanup results/statistics
        """
        raise NotImplementedError


