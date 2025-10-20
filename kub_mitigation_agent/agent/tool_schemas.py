#!/usr/bin/env python3
"""
Tool Schemas for OpenAI Function Calling
Defines all available operations that an AI agent can perform through MCP and other utilities.
"""

from typing import List, Dict, Any
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

# ----- REASONING TOOLS (inform/analyze) -----
class CreateReasoningPlan(BaseModel):
    objective: str = Field(..., description="Clear goal to accomplish")
    steps: List[str] = Field(
        ..., 
        description="Ordered list of CONCRETE ACTION STEPS (specific tool calls). NOT analytical tasks like 'compare X and Y' - you do that in EvaluateStep. Example: 'Get CPU metrics for namespace X (10m)', 'Scale deployment Y to 3 replicas'"
    )
    rationale: str = Field(..., description="Why this plan will resolve the issue based on your analysis")


class EvaluateStep(BaseModel):
    step_completed: str = Field(..., description="Description of the step that was just executed")
    observations: List[str] = Field(..., description="Key observations from the action result")
    analysis: str = Field(..., description="Your analysis of the data: comparisons, patterns, calculations, and conclusions drawn from the observations")
    success: bool = Field(..., description="Did the step achieve its intended outcome?")
    plan_action: Literal["proceed_to_next_step", "retry_current_step", "create_new_plan", "completed"] = Field(..., description="What to do next")
    rationale: str = Field(..., description="Why this decision based on the evidence")


class ProblemLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str = Field(..., description="Name of the problem location (e.g., pod name, node name)")
    type: str = Field(..., description="Type of the problem location (e.g., 'pod', 'node', 'deployment')")


class GenerateOperationalSummary(BaseModel):
    objective: str = Field(..., description="Objective of the operation")
    actions_completed: List[str] = Field(..., description="List of actions completed")
    results_achieved: List[str] = Field(..., description="List of results achieved")
    status: str = Field(..., description="Final status of the operation")
    problem_location: Optional[List[ProblemLocation]] = Field(None, description="List of problem locations with name and type")
    success: bool = Field(..., description="Whether the problem was resolved")


class SleepSeconds(BaseModel):
    duration: float = Field(..., description="Number of seconds to sleep")


class PrometheusGetTimeseries(BaseModel):
    metric_type: Literal["cpu", "memory", "latency"] = Field(..., description="Type of metric to retrieve")
    namespace: str = Field(..., description="Target namespace to filter metrics")
    duration: str = Field("5m", description="Time range backwards from now (<=2m)")


class PrometheusGetNodeTimeseries(BaseModel):
    metric_type: Literal["cpu", "memory"] = Field(..., description="Type of node metric to retrieve")
    duration: str = Field("5m", description="Time range backwards from now (<=2m)")


class PrometheusGetServiceTopology(BaseModel):
    namespace: Optional[str] = Field(None, description="Namespace to analyze topology for (optional)")
    time_window: str = Field("5m", description="Time window for analyzing request patterns")


class KubectlApply(BaseModel):
    manifest: str = Field(..., description="The YAML manifest content to apply")
    namespace: Optional[str] = Field(None, description="Target namespace (optional)")
    dryRun: Optional[bool] = Field(None, description="If true, only validate without applying")


class KubectlGet(BaseModel):
    resourceType: str = Field(..., description="Resource type (e.g., 'pod', 'deployment')")
    name: Optional[str] = Field(None, description="Name of the resource (optional)")
    namespace: Optional[str] = Field(None, description="Namespace (optional)")
    output: Optional[Literal["json", "yaml", "wide", "name"]] = Field(None, description="Output format")


class KubectlDelete(BaseModel):
    resourceType: str = Field(..., description="Type of resource to delete")
    name: str = Field(..., description="Name of the resource")
    namespace: Optional[str] = Field(None, description="Namespace (optional for cluster-scoped)")
    force: Optional[bool] = Field(None, description="Force immediate deletion")


class KubectlList(BaseModel):
    resourceType: str = Field(..., description="Type of resource to list")
    namespace: Optional[str] = Field(None, description="Specific namespace (optional)")
    allNamespaces: Optional[bool] = Field(None, description="List across all namespaces")


class KubectlScale(BaseModel):
    name: str = Field(..., description="Name of the deployment to scale")
    namespace: Optional[str] = Field(None, description="Namespace of the deployment")
    replicas: int = Field(..., description="Number of replicas to scale to")
    resourceType: Optional[Literal["deployment", "replicaset", "statefulset"]] = Field(
        None, description="Resource type to scale"
    )


class KubectlPatch(BaseModel):
    resourceType: str = Field(..., description="Type of resource to patch")
    name: str = Field(..., description="Name of the resource to patch")
    namespace: Optional[str] = Field(None, description="Namespace of the resource")
    patchType: Optional[Literal["strategic", "merge", "json"]] = Field(None, description="Patch type")
    patchData: Dict[str, Any] = Field(..., description="JSON object with patch payload")
    dryRun: Optional[bool] = Field(None, description="Validate only without applying")


class KubectlDescribe(BaseModel):
    resourceType: str = Field(..., description="Type of resource to describe")
    name: str = Field(..., description="Name of the resource")
    namespace: Optional[str] = Field(None, description="Namespace (optional)")
    allNamespaces: Optional[bool] = Field(None, description="Describe across all namespaces")


class KubectlLogs(BaseModel):
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


class KubectlRollout(BaseModel):
    subCommand: Literal["history", "pause", "restart", "resume", "status", "undo"] = Field(..., description="Subcommand")
    resourceType: Literal["deployment", "daemonset", "statefulset"] = Field(..., description="Resource type")
    name: str = Field(..., description="Name of the resource")
    namespace: Optional[str] = Field(None, description="Namespace of the resource")
    revision: Optional[int] = Field(None, description="Revision to rollback to (undo)")
    toRevision: Optional[int] = Field(None, description="Revision to roll back to (history)")
    timeout: Optional[str] = Field(None, description="Wait time (e.g., '30s')")
    watch: Optional[bool] = Field(None, description="Watch status until completion")


class KubectlDrain(BaseModel):
    node_name: str = Field(..., description="Name of the node to drain")
    ignore_daemonsets: bool = Field(True, description="Ignore DaemonSet-managed pods")
    delete_emptydir_data: bool = Field(False, description="Continue if pods use emptyDir volumes")
    force: bool = Field(False, description="Continue if pods not managed by a controller")
    grace_period: int = Field(30, description="Seconds for graceful termination")
    timeout: str = Field("0s", description="Timeout before giving up (e.g., '5m')")
    disable_eviction: bool = Field(False, description="Use delete instead of evict API")


class KubectlCordon(BaseModel):
    node_name: str = Field(..., description="Name of the node to cordon")


class KubectlUncordon(BaseModel):
    node_name: str = Field(..., description="Name of the node to uncordon")


# ---------- Aggregation helpers for tool registration ----------
def get_reasoning_tool_models() -> List[type[BaseModel]]:
    """Return tool models for reasoning/analysis (inform, don't execute)."""
    return [
        CreateReasoningPlan,
        EvaluateStep,
    ]


def get_execution_tool_models() -> List[type[BaseModel]]:
    """Return tool models for execution (take action)."""
    return [
        # Utility
        SleepSeconds,
        # Prometheus
        PrometheusGetTimeseries,
        PrometheusGetNodeTimeseries,
        PrometheusGetServiceTopology,
        # MCP kubectl
        KubectlApply,
        KubectlGet,
        KubectlDelete,
        KubectlList,
        KubectlScale,
        KubectlPatch,
        KubectlDescribe,
        KubectlLogs,
        KubectlRollout,
        KubectlDrain,
        KubectlCordon,
        KubectlUncordon,
    ]


def get_all_tool_models() -> List[type[BaseModel]]:
    """Return all tool models for ReAct agent (no separation between reasoning/execution)."""
    return [
        # Summary tool (signals completion)
        GenerateOperationalSummary,
        # Utility
        SleepSeconds,
        # Prometheus
        PrometheusGetTimeseries,
        PrometheusGetNodeTimeseries,
        PrometheusGetServiceTopology,
        # MCP kubectl
        KubectlApply,
        KubectlGet,
        KubectlDelete,
        KubectlList,
        KubectlScale,
        KubectlPatch,
        KubectlDescribe,
        KubectlLogs,
        KubectlRollout,
        KubectlDrain,
        KubectlCordon,
        KubectlUncordon,
    ]