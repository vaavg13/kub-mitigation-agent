"""
Agent Tools

This module provides tools for the agent to interact with various systems.

Tools are divided into:
- NON_MCP_TOOLS: Core tools and prometheus tools (not from MCP servers)
- MCP tools: kubectl operations from MCP server (loaded dynamically via MCPManager)

Note: Kubectl tools are now provided by the kubectl MCP server via LangChain adapters,
so they are no longer defined here as custom wrappers.
"""

from .core import generate_action_plan, generate_operational_summary, sleep_seconds
from .metrics import (
    prometheus_get_pod_cpu_timeseries,
    prometheus_get_pod_memory_timeseries,
    prometheus_get_service_latency_timeseries,
    prometheus_get_node_cpu_timeseries,
    prometheus_get_node_memory_timeseries,
    prometheus_get_service_topology,
    prometheus_get_ingress_stats,
    set_warmup_end_timestamp
)

# Non-MCP tools (core utilities + prometheus queries)
# These are combined with MCP tools (kubectl) at agent initialization
NON_MCP_TOOLS = [
    # Core agent tools
    generate_action_plan,
    generate_operational_summary,
    sleep_seconds,
    
    # Prometheus monitoring tools
    prometheus_get_pod_cpu_timeseries,
    prometheus_get_pod_memory_timeseries,
    prometheus_get_service_latency_timeseries,
    prometheus_get_node_cpu_timeseries,
    prometheus_get_node_memory_timeseries,
    prometheus_get_service_topology,
    prometheus_get_ingress_stats,
]

# Backward compatibility: ALL_TOOLS now just refers to NON_MCP_TOOLS
# MCP tools are added dynamically by the agent
ALL_TOOLS = NON_MCP_TOOLS
