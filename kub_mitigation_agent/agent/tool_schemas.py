#!/usr/bin/env python3
"""
Tool Schemas for OpenAI Function Calling
Defines all available operations that an AI agent can perform through MCP and other utilities.
"""

from typing import List, Dict, Any
from typing import Literal, Optional
from pydantic import BaseModel, Field

# ----- Tool-call Pydantic models (for with_structured_output) -----
class CreateActionPlanCall(BaseModel):
    tool: Literal["create_action_plan"] = Field("create_action_plan", description="Exact tool to call")
    objective: str = Field(..., description="Clear description of what to accomplish")
    current_situation: str = Field(..., description="Current state/context for the plan")
    steps: List[str] = Field(..., description="Ordered list of specific steps")
    expected_outcome: Optional[str] = Field(None, description="Expected outcome after completing steps")
    risks_considerations: Optional[List[str]] = Field(None, description="Potential risks or considerations")


class GenerateOperationalSummaryCall(BaseModel):
    tool: Literal["generate_operational_summary"] = Field("generate_operational_summary", description="Exact tool to call")
    objective: str = Field(..., description="Objective of the operation")
    actions_completed: List[str] = Field(..., description="List of actions completed")
    results_achieved: List[str] = Field(..., description="List of results achieved")
    status: str = Field(..., description="Status of the operation")
    problem_location: Optional[List[Dict[str, Any]]] = Field(None, description="List of problem locations with name and type")
    success: bool = Field(..., description="Whether the problem was resolved")


class SleepSecondsCall(BaseModel):
    tool: Literal["sleep_seconds"] = Field("sleep_seconds", description="Exact tool to call")
    duration: float = Field(..., description="Number of seconds to sleep")


class PrometheusGetTimeseriesCall(BaseModel):
    tool: Literal["prometheus_get_timeseries"] = Field("prometheus_get_timeseries", description="Exact tool to call")
    metric_type: Literal["cpu", "memory", "latency"] = Field(..., description="Type of metric to retrieve")
    namespace: str = Field(..., description="Target namespace to filter metrics")
    duration: str = Field("2m", description="Time range backwards from now (<=2m)")


class PrometheusGetNodeTimeseriesCall(BaseModel):
    tool: Literal["prometheus_get_node_timeseries"] = Field("prometheus_get_node_timeseries", description="Exact tool to call")
    metric_type: Literal["cpu", "memory"] = Field(..., description="Type of node metric to retrieve")
    duration: str = Field("2m", description="Time range backwards from now (<=2m)")


class PrometheusGetServiceTopologyCall(BaseModel):
    tool: Literal["prometheus_get_service_topology"] = Field("prometheus_get_service_topology", description="Exact tool to call")
    namespace: Optional[str] = Field(None, description="Namespace to analyze topology for (optional)")
    time_window: str = Field("5m", description="Time window for analyzing request patterns")


class KubectlApplyCall(BaseModel):
    tool: Literal["kubectl_apply"] = Field("kubectl_apply", description="Exact tool to call")
    manifest: str = Field(..., description="The YAML manifest content to apply")
    namespace: Optional[str] = Field(None, description="Target namespace (optional)")
    dryRun: Optional[bool] = Field(None, description="If true, only validate without applying")


class KubectlGetCall(BaseModel):
    tool: Literal["kubectl_get"] = Field("kubectl_get", description="Exact tool to call")
    resourceType: str = Field(..., description="Resource type (e.g., 'pod', 'deployment')")
    name: Optional[str] = Field(None, description="Name of the resource (optional)")
    namespace: Optional[str] = Field(None, description="Namespace (optional)")
    output: Optional[Literal["json", "yaml", "wide", "name"]] = Field(None, description="Output format")


class KubectlDeleteCall(BaseModel):
    tool: Literal["kubectl_delete"] = Field("kubectl_delete", description="Exact tool to call")
    resourceType: str = Field(..., description="Type of resource to delete")
    name: str = Field(..., description="Name of the resource")
    namespace: Optional[str] = Field(None, description="Namespace (optional for cluster-scoped)")
    force: Optional[bool] = Field(None, description="Force immediate deletion")


class KubectlListCall(BaseModel):
    tool: Literal["kubectl_list"] = Field("kubectl_list", description="Exact tool to call")
    resourceType: str = Field(..., description="Type of resource to list")
    namespace: Optional[str] = Field(None, description="Specific namespace (optional)")
    allNamespaces: Optional[bool] = Field(None, description="List across all namespaces")


class KubectlScaleCall(BaseModel):
    tool: Literal["kubectl_scale"] = Field("kubectl_scale", description="Exact tool to call")
    name: str = Field(..., description="Name of the deployment to scale")
    namespace: Optional[str] = Field(None, description="Namespace of the deployment")
    replicas: int = Field(..., description="Number of replicas to scale to")
    resourceType: Optional[Literal["deployment", "replicaset", "statefulset"]] = Field(
        None, description="Resource type to scale"
    )


class KubectlPatchCall(BaseModel):
    tool: Literal["kubectl_patch"] = Field("kubectl_patch", description="Exact tool to call")
    resourceType: str = Field(..., description="Type of resource to patch")
    name: str = Field(..., description="Name of the resource to patch")
    namespace: Optional[str] = Field(None, description="Namespace of the resource")
    patchType: Optional[Literal["strategic", "merge", "json"]] = Field(None, description="Patch type")
    patchData: Dict[str, Any] = Field(..., description="JSON object with patch payload")
    dryRun: Optional[bool] = Field(None, description="Validate only without applying")


class KubectlDescribeCall(BaseModel):
    tool: Literal["kubectl_describe"] = Field("kubectl_describe", description="Exact tool to call")
    resourceType: str = Field(..., description="Type of resource to describe")
    name: str = Field(..., description="Name of the resource")
    namespace: Optional[str] = Field(None, description="Namespace (optional)")
    allNamespaces: Optional[bool] = Field(None, description="Describe across all namespaces")


class KubectlLogsCall(BaseModel):
    tool: Literal["kubectl_logs"] = Field("kubectl_logs", description="Exact tool to call")
    resourceType: Literal["pod", "deployment", "job", "cronjob"] = Field(..., description="Resource type")
    name: str = Field(..., description="Name of the resource")
    namespace: str = Field(..., description="Namespace of the resource")
    container: Optional[str] = Field(None, description="Container name if multiple")
    tail: Optional[int] = Field(None, description="Lines from end of logs")
    since: Optional[str] = Field(None, description="Relative time (e.g., '2m')")
    sinceTime: Optional[str] = Field(None, description="Absolute time (RFC3339)")
    timestamps: Optional[bool] = Field(None, description="Include timestamps")
    previous: Optional[bool] = Field(None, description="Include logs from terminated containers")
    follow: Optional[bool] = Field(None, description="Follow logs output")
    labelSelector: Optional[str] = Field(None, description="Filter by label selector")


class KubectlRolloutCall(BaseModel):
    tool: Literal["kubectl_rollout"] = Field("kubectl_rollout", description="Exact tool to call")
    subCommand: Literal["history", "pause", "restart", "resume", "status", "undo"] = Field(..., description="Subcommand")
    resourceType: Literal["deployment", "daemonset", "statefulset"] = Field(..., description="Resource type")
    name: str = Field(..., description="Name of the resource")
    namespace: Optional[str] = Field(None, description="Namespace of the resource")
    revision: Optional[int] = Field(None, description="Revision to rollback to (undo)")
    toRevision: Optional[int] = Field(None, description="Revision to roll back to (history)")
    timeout: Optional[str] = Field(None, description="Wait time (e.g., '30s')")
    watch: Optional[bool] = Field(None, description="Watch status until completion")


class KubectlDrainCall(BaseModel):
    tool: Literal["kubectl_drain"] = Field("kubectl_drain", description="Exact tool to call")
    node_name: str = Field(..., description="Name of the node to drain")
    ignore_daemonsets: bool = Field(True, description="Ignore DaemonSet-managed pods")
    delete_emptydir_data: bool = Field(False, description="Continue if pods use emptyDir volumes")
    force: bool = Field(False, description="Continue if pods not managed by a controller")
    grace_period: int = Field(30, description="Seconds for graceful termination")
    timeout: str = Field("0s", description="Timeout before giving up (e.g., '5m')")
    disable_eviction: bool = Field(False, description="Use delete instead of evict API")


class KubectlCordonCall(BaseModel):
    tool: Literal["kubectl_cordon"] = Field("kubectl_cordon", description="Exact tool to call")
    node_name: str = Field(..., description="Name of the node to cordon")


class KubectlUncordonCall(BaseModel):
    tool: Literal["kubectl_uncordon"] = Field("kubectl_uncordon", description="Exact tool to call")
    node_name: str = Field(..., description="Name of the node to uncordon")


# ---------- Aggregation helpers for tool registration ----------
def get_all_tool_call_models() -> List[type[BaseModel]]:
    """Return all Pydantic call models used for structured tool-calling across providers."""
    return [
        # Planning / summaries / sleep
        CreateActionPlanCall,
        GenerateOperationalSummaryCall,
        SleepSecondsCall,
        # Prometheus
        PrometheusGetTimeseriesCall,
        PrometheusGetNodeTimeseriesCall,
        PrometheusGetServiceTopologyCall,
        # MCP kubectl
        KubectlApplyCall,
        KubectlGetCall,
        KubectlDeleteCall,
        KubectlListCall,
        KubectlScaleCall,
        KubectlPatchCall,
        KubectlDescribeCall,
        KubectlLogsCall,
        KubectlRolloutCall,
        KubectlDrainCall,
        KubectlCordonCall,
        KubectlUncordonCall,
    ]

def get_tool_name_to_model_map() -> Dict[str, type[BaseModel]]:
    """Map tool name strings to their Pydantic call model class."""
    return {
        # Planning / summaries / sleep
        "create_action_plan": CreateActionPlanCall,
        "generate_operational_summary": GenerateOperationalSummaryCall,
        "sleep_seconds": SleepSecondsCall,
        # Prometheus
        "prometheus_get_timeseries": PrometheusGetTimeseriesCall,
        "prometheus_get_node_timeseries": PrometheusGetNodeTimeseriesCall,
        "prometheus_get_service_topology": PrometheusGetServiceTopologyCall,
        # MCP kubectl
        "kubectl_apply": KubectlApplyCall,
        "kubectl_get": KubectlGetCall,
        "kubectl_delete": KubectlDeleteCall,
        "kubectl_list": KubectlListCall,
        "kubectl_scale": KubectlScaleCall,
        "kubectl_patch": KubectlPatchCall,
        "kubectl_describe": KubectlDescribeCall,
        "kubectl_logs": KubectlLogsCall,
        "kubectl_rollout": KubectlRolloutCall,
        "kubectl_drain": KubectlDrainCall,
        "kubectl_cordon": KubectlCordonCall,
        "kubectl_uncordon": KubectlUncordonCall,
    }