#!/usr/bin/env python3
import asyncio
import logging
import re
from typing import Any, Dict, Tuple

from .mcp_client import MCPClient
from ..shared.prometheus_client import (
    prometheus_get_timeseries,
    prometheus_get_node_timeseries,
    prometheus_get_service_topology,
)

logger = logging.getLogger(__name__)


def _parse_timeout_to_seconds(timeout_str: str) -> int:
    """Parse kubectl timeout string (e.g., '5m', '120s', '2h') to seconds."""
    timeout_str = timeout_str.strip().lower()
    if timeout_str == "0" or timeout_str == "0s":
        return 0
    
    # Extract number and unit
    match = re.match(r'^(\d+(?:\.\d+)?)(s|m|h)?$', timeout_str)
    if not match:
        logger.warning(f"Invalid timeout format: {timeout_str}, defaulting to 0s")
        return 0
    
    value = float(match.group(1))
    unit = match.group(2) or 's'  # Default to seconds if no unit
    
    # Convert to seconds
    if unit == 's':
        return int(value)
    elif unit == 'm':
        return int(value * 60)
    elif unit == 'h':
        return int(value * 3600)
    return 0


def _cap_kubectl_timeout(timeout_str: str, max_seconds: int) -> str:
    """Cap kubectl timeout to a maximum value. Returns timeout string in kubectl format."""
    if timeout_str == "0s" or timeout_str == "0":
        return timeout_str
    
    seconds = _parse_timeout_to_seconds(timeout_str)
    if seconds > max_seconds:
        # Return in minutes if >= 60s, otherwise in seconds
        if max_seconds >= 60:
            return f"{max_seconds // 60}m"
        return f"{max_seconds}s"
    return timeout_str


def convert_node_function_to_generic(function_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Convert node management calls (Pydantic model names) to kubectl_generic arguments."""
    if function_name == "KubectlDrain":
        node_name = args["node_name"]
        flags: Dict[str, Any] = {}
        if args.get("ignore_daemonsets", True):
            flags["ignore-daemonsets"] = True
        if args.get("delete_emptydir_data", False):
            flags["delete-emptydir-data"] = True
        if args.get("force", False):
            flags["force"] = True
        if args.get("disable_eviction", False):
            flags["disable-eviction"] = True
        grace_period = args.get("grace_period", 30)
        if grace_period != 30:
            flags["grace-period"] = grace_period
        # Cap timeout at 9 minutes (540s) to ensure it completes before MCP timeout (10 minutes)
        timeout = args.get("timeout", "0s")
        if timeout != "0s":
            timeout_capped = _cap_kubectl_timeout(timeout, max_seconds=540)
            if timeout_capped != timeout:
                logger.warning(f"Kubectl drain timeout capped from {timeout} to {timeout_capped} (max 9m)")
            flags["timeout"] = timeout_capped
        return {"command": "drain", "name": node_name, "flags": flags}
    if function_name == "KubectlCordon":
        return {"command": "cordon", "name": args["node_name"]}
    if function_name == "KubectlUncordon":
        return {"command": "uncordon", "name": args["node_name"]}
    raise ValueError(f"Unknown node function: {function_name}")


class ToolsRouter:
    """Routes structured tool calls to concrete executors (MCP, Prometheus, planning, sleep)."""

    def __init__(self, mcp_client: MCPClient):
        self.mcp_client = mcp_client

    def _cap_timeout_in_args(self, args: Dict[str, Any], function_name: str, max_seconds: int = 540) -> Dict[str, Any]:
        """Cap any timeout field in args to ensure it completes before MCP timeout."""
        if "timeout" not in args or not args["timeout"]:
            return args
        
        timeout = args["timeout"]
        if timeout in ["0", "0s"]:
            return args
        
        timeout_capped = _cap_kubectl_timeout(timeout, max_seconds=max_seconds)
        if timeout_capped != timeout:
            logger.warning(f"{function_name} timeout capped from {timeout} to {timeout_capped} (max 9m)")
            args = args.copy()  # Don't mutate original
            args["timeout"] = timeout_capped
        
        return args

    async def execute(self, function_name: str, args: Dict[str, Any], state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """
        Execute a tool call (execution tools only - reasoning tools are handled in reasoning node).

        Returns: (result, state_delta, action_record)
        """
        # MCP kubectl tools
        mcp_map = {
            "KubectlApply": "kubectl_apply",
            "KubectlGet": "kubectl_get",
            "KubectlDelete": "kubectl_delete",
            "KubectlList": "kubectl_list",
            "KubectlScale": "kubectl_scale",
            "KubectlPatch": "kubectl_patch",
            "KubectlDescribe": "kubectl_describe",
            "KubectlLogs": "kubectl_logs",
            "KubectlRollout": "kubectl_rollout",
        }
        if function_name in mcp_map:
            # Cap any timeout field to ensure kubectl completes before MCP timeout
            args = self._cap_timeout_in_args(args, function_name)
            result = await self.mcp_client.call_tool(mcp_map[function_name], args)
            # Check if the result contains an error (timeout, connection issues, etc.)
            if isinstance(result, dict) and "error" in result:
                error_info = result["error"]
                logger.warning(f"{function_name} returned an error")
                # Return a structured error response that the agent can understand
                error_result = {
                    "error": f"Tool {function_name} failed: {error_info.get('message', 'Unknown error')}",
                    "error_code": error_info.get("code", "UNKNOWN"),
                    "tool": function_name
                }
                action_record = {"type": "kubectl_call", "function": function_name, "parameters": args, "error": error_info}
                return error_result, {}, action_record
            action_record = {"type": "kubectl_call", "function": function_name, "parameters": args}
            return result, {}, action_record

        # Node management via kubectl_generic
        if function_name in ["KubectlDrain", "KubectlCordon", "KubectlUncordon"]:
            generic_args = convert_node_function_to_generic(function_name, args)
            result = await self.mcp_client.call_tool("kubectl_generic", generic_args)
            # Check if the result contains an error (timeout, connection issues, etc.)
            if isinstance(result, dict) and "error" in result:
                error_info = result["error"]
                logger.warning(f"{function_name} returned an error")
                # Return a structured error response that the agent can understand
                error_result = {
                    "error": f"Tool {function_name} failed: {error_info.get('message', 'Unknown error')}",
                    "error_code": error_info.get("code", "UNKNOWN"),
                    "tool": function_name
                }
                action_record = {"type": "kubectl_call", "function": function_name, "parameters": args, "error": error_info}
                return error_result, {}, action_record
            action_record = {"type": "kubectl_call", "function": function_name, "parameters": args}
            return result, {}, action_record

        # Prometheus tools
        if function_name == "PrometheusGetTimeseries":
            result = prometheus_get_timeseries(**args)
            action_record = {"type": "prometheus_call", "function": function_name, "parameters": args}
            return result, {}, action_record
        if function_name == "PrometheusGetNodeTimeseries":
            result = prometheus_get_node_timeseries(**args)
            action_record = {"type": "prometheus_call", "function": function_name, "parameters": args}
            return result, {}, action_record
        if function_name == "PrometheusGetServiceTopology":
            result = prometheus_get_service_topology(**args)
            action_record = {"type": "prometheus_call", "function": function_name, "parameters": args}
            return result, {}, action_record

        # Sleep
        if function_name == "SleepSeconds":
            duration = args.get("duration", 0)
            await asyncio.sleep(duration)
            result = {"duration": duration, "status": "completed"}
            action_record = {"type": "sleep", "duration": duration}
            return result, {}, action_record

        return {"error": f"Unknown function: {function_name}"}, {}, {"type": "error", "function": function_name}


