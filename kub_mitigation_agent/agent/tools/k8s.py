import logging
from typing import Any, Dict, Literal, Optional
from langchain.tools import tool

logger = logging.getLogger(__name__)

# Shared MCP handle (set by agent at init time)
_MCP_CLIENT = None

def set_mcp_client(mcp_client: Any) -> None:
    global _MCP_CLIENT
    _MCP_CLIENT = mcp_client

@tool(description="Apply a Kubernetes manifest via MCP kubectl.")
async def kubectl_apply(manifest: str, namespace: Optional[str] = None, dryRun: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl apply -f manifest [--namespace] [--dry-run]."""
    args: Dict[str, Any] = {"manifest": manifest, "namespace": namespace, "dryRun": dryRun}
    return await _MCP_CLIENT.call_tool("kubectl_apply", args)


@tool(description="Get Kubernetes resources via MCP kubectl.")
async def kubectl_get(resourceType: str, name: Optional[str] = None, namespace: Optional[str] = None, output: Optional[Literal["json", "yaml", "wide", "name"]] = None) -> Dict[str, Any]:
    """kubectl get <type> [name] [-n namespace] [-o json|yaml|wide|name]."""
    args: Dict[str, Any] = {"resourceType": resourceType, "name": name, "namespace": namespace, "output": output}
    return await _MCP_CLIENT.call_tool("kubectl_get", args)


@tool(description="Delete a Kubernetes resource via MCP kubectl.")
async def kubectl_delete(resourceType: str, name: str, namespace: Optional[str] = None, force: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl delete <type> <name> [-n namespace] [--force]."""
    args: Dict[str, Any] = {"resourceType": resourceType, "name": name, "namespace": namespace, "force": force}
    return await _MCP_CLIENT.call_tool("kubectl_delete", args)


@tool(description="List Kubernetes resources via MCP kubectl.")
async def kubectl_list(resourceType: str, namespace: Optional[str] = None, allNamespaces: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl get <type> [-n namespace] [--all-namespaces]."""
    args: Dict[str, Any] = {"resourceType": resourceType, "namespace": namespace, "allNamespaces": allNamespaces}
    return await _MCP_CLIENT.call_tool("kubectl_list", args)


@tool(description="Scale a workload via MCP kubectl.")
async def kubectl_scale(name: str, namespace: Optional[str] = None, replicas: int = 1, resourceType: Optional[Literal["deployment", "replicaset", "statefulset"]] = None) -> Dict[str, Any]:
    """kubectl scale <resourceType>/<name> --replicas=N [-n namespace]."""
    args: Dict[str, Any] = {"name": name, "namespace": namespace, "replicas": replicas, "resourceType": resourceType}
    return await _MCP_CLIENT.call_tool("kubectl_scale", args)


@tool(description="Patch a Kubernetes resource via MCP kubectl.")
async def kubectl_patch(resourceType: str, name: str, patchData: Dict[str, Any], namespace: Optional[str] = None, patchType: Optional[Literal["strategic", "merge", "json"]] = None, dryRun: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl patch <type> <name> [-n ns] --type <t> -p <json>."""
    args: Dict[str, Any] = {
        "resourceType": resourceType,
        "name": name,
        "namespace": namespace,
        "patchType": patchType,
        "patchData": patchData,
        "dryRun": dryRun,
    }
    return await _MCP_CLIENT.call_tool("kubectl_patch", args)


@tool(description="Describe a Kubernetes resource via MCP kubectl.")
async def kubectl_describe(resourceType: str, name: str, namespace: Optional[str] = None, allNamespaces: Optional[bool] = None) -> Dict[str, Any]:
    """kubectl describe <type> <name> [-n namespace] [--all-namespaces]."""
    args: Dict[str, Any] = {"resourceType": resourceType, "name": name, "namespace": namespace, "allNamespaces": allNamespaces}
    return await _MCP_CLIENT.call_tool("kubectl_describe", args)


@tool(description="Fetch logs via MCP kubectl.")
async def kubectl_logs(
    resourceType: Literal["pod", "deployment", "job", "cronjob"],
    name: str,
    namespace: str,
    container: Optional[str] = None,
    tail: Optional[int] = None,
    since: Optional[str] = None,
    sinceTime: Optional[str] = None,
    timestamps: Optional[bool] = None,
    previous: Optional[bool] = None,
    follow: Optional[bool] = None,
    labelSelector: Optional[str] = None,
) -> Dict[str, Any]:
    """kubectl logs for pod/deployment/job/cronjob."""
    args: Dict[str, Any] = {
        "resourceType": resourceType,
        "name": name,
        "namespace": namespace,
        "container": container,
        "tail": tail,
        "since": since,
        "sinceTime": sinceTime,
        "timestamps": timestamps,
        "previous": previous,
        "follow": follow,
        "labelSelector": labelSelector,
    }
    return await _MCP_CLIENT.call_tool("kubectl_logs", args)


@tool(description="Rollout operations via MCP kubectl.")
async def kubectl_rollout(
    subCommand: Literal["history", "pause", "restart", "resume", "status", "undo"],
    resourceType: Literal["deployment", "daemonset", "statefulset"],
    name: str,
    namespace: Optional[str] = None,
    revision: Optional[int] = None,
    toRevision: Optional[int] = None,
    timeout: Optional[str] = None,
    watch: Optional[bool] = None,
) -> Dict[str, Any]:
    """kubectl rollout <subCommand> <resourceType>/<name>."""
    # Inline tiny guardrail for timeout: cap to 9m if provided and longer
    def _cap_timeout(t: Optional[str]) -> Optional[str]:
        if not t or t in ("0", "0s"):
            return t
        # crude cap without parsing complexity
        return "9m" if t.endswith("m") or t.endswith("s") else t

    args: Dict[str, Any] = {
        "subCommand": subCommand,
        "resourceType": resourceType,
        "name": name,
        "namespace": namespace,
        "revision": revision,
        "toRevision": toRevision,
        "timeout": _cap_timeout(timeout),
        "watch": watch,
    }
    return await _MCP_CLIENT.call_tool("kubectl_rollout", args)


@tool(description="Drain a node via MCP kubectl (uses kubectl_generic).")
async def kubectl_drain(
    node_name: str,
    ignore_daemonsets: bool = True,
    delete_emptydir_data: bool = False,
    force: bool = False,
    grace_period: int = 30,
    timeout: str = "0s",
    disable_eviction: bool = False,
) -> Dict[str, Any]:
    """kubectl drain <node> with safe defaults (timeouts capped at 9m)."""
    flags: Dict[str, Any] = {}
    if ignore_daemonsets:
        flags["ignore-daemonsets"] = True
    if delete_emptydir_data:
        flags["delete-emptydir-data"] = True
    if force:
        flags["force"] = True
    if disable_eviction:
        flags["disable-eviction"] = True
    if grace_period != 30:
        flags["grace-period"] = grace_period
    # crude cap to 9m if provided and nonzero
    if timeout and timeout not in ("0", "0s"):
        flags["timeout"] = "9m"
    generic_args = {"command": "drain", "name": node_name, "flags": flags}
    return await _MCP_CLIENT.call_tool("kubectl_generic", generic_args)


@tool(description="Cordon a node via MCP kubectl (uses kubectl_generic).")
async def kubectl_cordon(node_name: str) -> Dict[str, Any]:
    """kubectl cordon <node>."""
    generic_args = {"command": "cordon", "name": node_name}
    return await _MCP_CLIENT.call_tool("kubectl_generic", generic_args)


@tool(description="Uncordon a node via MCP kubectl (uses kubectl_generic).")
async def kubectl_uncordon(node_name: str) -> Dict[str, Any]:
    """kubectl uncordon <node>."""
    generic_args = {"command": "uncordon", "name": node_name}
    return await _MCP_CLIENT.call_tool("kubectl_generic", generic_args)

