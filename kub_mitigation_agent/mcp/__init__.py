"""
MCP (Model Context Protocol) Integration

This module provides integration with MCP servers using LangChain's MCP adapters.
MCP servers expose tools for interacting with external systems (Kubernetes, Prometheus, etc.)
through a standardized protocol.

The module uses langchain-mcp-adapters for robust MCP protocol support:
- https://docs.langchain.com/oss/python/langchain/mcp

Currently supported MCP servers:
- **mcp-server-kubernetes** (Node.js)
  https://github.com/Flux159/mcp-server-kubernetes
  - Mature and actively maintained (1.3k stars)
  - No logging issues, works perfectly out of the box
  - Rich features: kubectl, Helm, port-forward, node management, exec
  - Use: get_kubernetes_config()

Future MCP servers:
- prometheus: Metrics queries (planned)
- other tools as needed
"""

from .manager import MCPManager
from .kubernetes import get_kubernetes_config, kubernetes_ready

__all__ = [
    "MCPManager",
    "get_kubernetes_config",
    "kubernetes_ready",
]
