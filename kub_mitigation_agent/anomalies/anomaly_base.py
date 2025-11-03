
from typing import Dict, Optional


class Anomaly:
    """Base anomaly interface for unified lifecycle management.

    Subclasses must implement get_info, start, and stop. Instances are
    expected to hold all configuration parameters at construction time,
    so callers do not pass parameters when calling start/stop.
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


