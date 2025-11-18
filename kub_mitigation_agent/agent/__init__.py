# Agent module
from .react_agent import ReactAgent

# Alias for backward compatibility (and since we merged the wrapper)
KubernetesAgent = ReactAgent

__all__ = ["KubernetesAgent", "ReactAgent"]
