#!/usr/bin/env python3
import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from .mcp_client import MCPClient
from ..shared.prometheus_client import (
    prometheus_get_timeseries,
    prometheus_get_node_timeseries,
    prometheus_get_service_topology,
)
# The agent expects tool function_name to be the Pydantic model class name

logger = logging.getLogger(__name__)


def _convert_problem_location_to_list(problem_location_param: Any) -> list[dict[str, Any]]:
    """Maintain backward compatibility for problem_location param shapes."""
    if isinstance(problem_location_param, list):
        return problem_location_param
    result: list[dict[str, Any]] = []
    if isinstance(problem_location_param, dict):
        for resource_type in ["deployment", "pod", "node", "service"]:
            plural_key = f"{resource_type}s"
            if plural_key in problem_location_param:
                resources = problem_location_param[plural_key]
                if isinstance(resources, list):
                    for name in resources:
                        result.append({"name": name, "type": resource_type})
                elif isinstance(resources, str):
                    result.append({"name": resources, "type": resource_type})
    return result


def convert_node_function_to_generic(function_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Convert node management calls (Pydantic model names) to kubectl_generic arguments."""
    if function_name == "KubectlDrainCall":
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
        timeout = args.get("timeout", "0s")
        if timeout != "0s":
            flags["timeout"] = timeout
        return {"command": "drain", "name": node_name, "flags": flags}
    if function_name == "KubectlCordonCall":
        return {"command": "cordon", "name": args["node_name"]}
    if function_name == "KubectlUncordonCall":
        return {"command": "uncordon", "name": args["node_name"]}
    raise ValueError(f"Unknown node function: {function_name}")


class ToolsRouter:
    """Routes structured tool calls to concrete executors (MCP, Prometheus, planning, sleep)."""

    def __init__(self, mcp_client: MCPClient):
        self.mcp_client = mcp_client

    async def execute(self, function_name: str, args: Dict[str, Any], state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """
        Execute a tool call.

        Returns: (result, state_delta, action_record)
        """
        # Planning tools (update state) - expect model class names
        if function_name == "CreateActionPlanCall":
            plan = {
                "objective": args.get("objective"),
                "current_situation": args.get("current_situation"),
                "steps": args.get("steps", []),
                "expected_outcome": args.get("expected_outcome"),
                "risks_considerations": args.get("risks_considerations", []),
                "created_at": time.time(),
                "status": "active",
            }
            state_delta = {"plan": plan, "current_step_index": 0}
            result = {"status": "success", "message": "Action plan created successfully", "plan": plan}
            action_record = {"type": "planning", "function": function_name, "parameters": args}
            return result, state_delta, action_record

        if function_name == "GenerateOperationalSummaryCall":
            problem_location_param = args.get("problem_location", [])
            problem_location_list = _convert_problem_location_to_list(problem_location_param)
            summary = {
                "objective": args.get("objective"),
                "actions_completed": args.get("actions_completed", []),
                "results_achieved": args.get("results_achieved", []),
                "status": args.get("status"),
                "problem_location": problem_location_list,
                "success": args.get("success", False),
                "timestamp": time.time(),
                "plan_info": {
                    "plans_created": len(state.get("plan_history", [])),
                    "final_plan_status": (state.get("plan") or {}).get("status", "none"),
                },
            }
            state_delta = {"final_summary": {"status": "success", "summary": summary, "operation_complete": True}}
            # Mark plan status if present
            if state.get("plan"):
                updated_plan = dict(state["plan"])  # shallow copy
                updated_plan["status"] = "completed_with_summary"
                state_delta["plan"] = updated_plan
            result = {"status": "success", "message": "Operational summary generated", "summary": summary, "operation_complete": True}
            action_record = {"type": "planning", "function": function_name, "parameters": args}
            return result, state_delta, action_record

        # MCP kubectl tools
        mcp_map = {
            "KubectlApplyCall": "kubectl_apply",
            "KubectlGetCall": "kubectl_get",
            "KubectlDeleteCall": "kubectl_delete",
            "KubectlListCall": "kubectl_list",
            "KubectlScaleCall": "kubectl_scale",
            "KubectlPatchCall": "kubectl_patch",
            "KubectlDescribeCall": "kubectl_describe",
            "KubectlLogsCall": "kubectl_logs",
            "KubectlRolloutCall": "kubectl_rollout",
        }
        if function_name in mcp_map:
            result = await self.mcp_client.call_tool(mcp_map[function_name], args)
            action_record = {"type": "mcp_call", "function": function_name, "parameters": args}
            return result, {}, action_record

        # Node management via kubectl_generic
        if function_name in ["KubectlDrainCall", "KubectlCordonCall", "KubectlUncordonCall"]:
            generic_args = convert_node_function_to_generic(function_name, args)
            result = await self.mcp_client.call_tool("kubectl_generic", generic_args)
            action_record = {"type": "mcp_call", "function": function_name, "parameters": args}
            return result, {}, action_record

        # Prometheus tools
        if function_name == "PrometheusGetTimeseriesCall":
            result = prometheus_get_timeseries(**args)
            action_record = {"type": "prometheus_call", "function": function_name, "parameters": args}
            return result, {}, action_record
        if function_name == "PrometheusGetNodeTimeseriesCall":
            result = prometheus_get_node_timeseries(**args)
            action_record = {"type": "prometheus_call", "function": function_name, "parameters": args}
            return result, {}, action_record
        if function_name == "PrometheusGetServiceTopologyCall":
            result = prometheus_get_service_topology(**args)
            action_record = {"type": "prometheus_call", "function": function_name, "parameters": args}
            return result, {}, action_record

        # Sleep
        if function_name == "SleepSecondsCall":
            duration = args.get("duration", 0)
            await asyncio.sleep(duration)
            result = {"duration": duration, "status": "completed"}
            action_record = {"type": "sleep", "duration": duration}
            return result, {}, action_record

        return {"error": f"Unknown function: {function_name}"}, {}, {"type": "error", "function": function_name}


