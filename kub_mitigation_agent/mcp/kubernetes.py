#!/usr/bin/env python3
"""
Kubernetes MCP Server Configuration (Node.js based)

Provides configuration for connecting to mcp-server-kubernetes.
This is a Node.js/TypeScript based server that's more mature and actively maintained.

Installation:
    npx -y mcp-server-kubernetes  (no install needed!)

For more information, see: https://github.com/Flux159/mcp-server-kubernetes

Features:
    - Unified kubectl API (get, describe, apply, delete, create, logs, etc.)
    - Helm operations (install, upgrade, uninstall charts)
    - Port forwarding to pods and services
    - Node management (cordon, drain, uncordon)
    - Pod cleanup for problematic pods
    - Non-destructive mode for read-only access
    - Troubleshooting prompt (k8s-diagnose)
    
Advantages over kubectl-mcp-tool:
    - No stdout logging issues (works without wrapper)
    - More features (Helm, exec, port-forward)
    - Better maintained (1.3k stars, v3.1.1)
    - No Python dependency conflicts
"""

import subprocess
from typing import Dict, Any, Optional


def get_kubernetes_config(
    transport: str = "stdio",
    non_destructive: bool = False,
    custom_command: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get configuration for mcp-server-kubernetes (Node.js).
    
    Args:
        transport: Transport mechanism ("stdio" only for now)
        non_destructive: Run in read-only mode (disables destructive operations)
        custom_command: Custom command override (default: npx -y mcp-server-kubernetes)
        
    Returns:
        Configuration dictionary for mcp-server-kubernetes
        
    Example:
        >>> config = get_kubernetes_config()
        >>> # Returns: {"kubernetes": {"transport": "stdio", ...}}
        
        >>> config = get_kubernetes_config(non_destructive=True)
        >>> # Read-only mode - no delete, no drain, etc.
    
    Note:
        This server uses npx and doesn't require installation.
        Much better than kubectl-mcp-tool - no logging issues!
    """
    if transport == "stdio":
        config = {
            "kubernetes": {
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "mcp-server-kubernetes"],
            }
        }
        
        # Add environment for non-destructive mode
        if non_destructive:
            config["kubernetes"]["env"] = {
                "ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS": "true"
            }
        
        # Override command if custom one provided
        if custom_command:
            parts = custom_command.split()
            config["kubernetes"]["command"] = parts[0]
            config["kubernetes"]["args"] = parts[1:]
        
        return config
    else:
        raise ValueError(f"Unsupported transport: {transport}")


def kubernetes_ready(timeout: int = 10) -> bool:
    """
    Check if kubectl can reach the cluster and list nodes.
    
    This verifies Kubernetes connectivity before starting the MCP server.
    
    Args:
        timeout: Maximum time to wait for kubectl command
        
    Returns:
        True if kubectl can successfully reach the cluster, False otherwise
    """
    try:
        result = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "name", "--request-timeout=5s"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False
