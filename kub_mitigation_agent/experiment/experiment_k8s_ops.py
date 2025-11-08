#!/usr/bin/env python3
"""
Experiment Utilities
Helper functions for experiment deployment, cleanup, and metrics collection.
"""

import time
import subprocess
import logging
from typing import Dict, Any
from kubernetes import client, config
from mu_bench.deployers.manager import K8sDeploymentManager

logger = logging.getLogger(__name__)

def wait_for_pods_ready_sync(namespace: str, timeout: int = 300) -> bool:
    """Wait for all pods in namespace to be ready (synchronous version)."""
    config.load_kube_config()
    k8s_core_api = client.CoreV1Api()
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            pods = k8s_core_api.list_namespaced_pod(namespace=namespace)
            if not pods.items:
                time.sleep(5)
                continue
                
            ready_count = 0
            for pod in pods.items:
                if pod.status.conditions:
                    for condition in pod.status.conditions:
                        if condition.type == 'Ready' and condition.status == 'True':
                            ready_count += 1
                            break
            
            if ready_count == len(pods.items):
                print(f"✅ All {ready_count} pods ready in {namespace}")
                return True
                
            print(f"⏳ Waiting... {ready_count}/{len(pods.items)} pods ready")
            time.sleep(5)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
    
    print(f"❌ Timeout waiting for pods in {namespace}")
    return False

def deploy_fresh_app_sync(experiment_config):
    """
    Deploy fresh application.
    """
    if not experiment_config["test_settings"]["deploy_fresh_app"]:
        print("Skipping fresh app deployment (disabled in config)")
        return True, ""
    
    # Use namespace from config to determine app name
    app_name = experiment_config["namespace"]
    app_dir = f"{experiment_config['app_directory']}/{app_name}"
    
    try:
        print(f"Deploying {app_name}...")
        mgr = K8sDeploymentManager.from_deployment_dir(app_dir)
        mgr.deploy()
        
        print(f"Waiting for pods to be ready...")
        if not wait_for_pods_ready_sync(mgr.namespace, timeout=300):
            print(f"❌ Pods failed to become ready")
            return False, ""
        
        print(f"✅ Application deployed successfully")
        return True, mgr.namespace
        
    except Exception as e:
        print(f"❌ Deployment error: {e}")
        logger.error(f"Deployment failed: {e}")
        return False, ""

def undeploy_app_sync(experiment_config):
    """
    Undeploy application (minimal cleanup).
    """
    app_name = experiment_config["namespace"]
    app_dir = f"{experiment_config['app_directory']}/{app_name}"
    
    try:
        print(f"Undeploying {app_name}...")
        mgr = K8sDeploymentManager.from_deployment_dir(app_dir)
        mgr.undeploy()
        
        print(f"✅ Application undeployed")
        return True
        
    except Exception as e:
        print(f"⚠️  Undeployment error (non-critical): {e}")
        logger.warning(f"Undeploy failed: {e}")
        # Return True anyway - cleanup will happen next iteration
        return True

def uncordon_all_nodes() -> bool:
    """Uncordon all cordoned nodes in the cluster.
    
    Returns:
        True if successful or no nodes needed uncordoning, False on error
    """
    try:
        # Get all nodes with unschedulable=true
        get_cmd = "kubectl get nodes -o json"
        result = subprocess.run(get_cmd.split(), capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return False
        
        import json
        nodes_data = json.loads(result.stdout)
        cordoned_nodes = []
        
        for node in nodes_data.get("items", []):
            node_name = node.get("metadata", {}).get("name", "")
            # Skip infrastructure nodes
            if node_name in ["k3s-server", "system-services"]:
                continue
            unschedulable = node.get("spec", {}).get("unschedulable", False)
            if unschedulable:
                cordoned_nodes.append(node_name)
        
        if not cordoned_nodes:
            return True  # Nothing to uncordon
        
        # Uncordon each node
        for node_name in cordoned_nodes:
            uncordon_cmd = f"kubectl uncordon {node_name}"
            subprocess.run(uncordon_cmd.split(), capture_output=True, text=True, timeout=10)
        
        return True
        
    except Exception as e:
        logger.warning(f"Error uncordoning nodes: {e}")
        return False


def complete_pre_experiment_cleanup(
    namespace: str,
    nodes: dict,
    chaosd_port: int
) -> dict:
    """
    THE SINGLE SOURCE OF TRUTH for cleanup.
    
    Performs comprehensive cleanup BEFORE each experiment to guarantee clean state:
    1. Stop all anomalies (chaosd + chaosmesh) - stops resource waste immediately
    2. Uncordon all nodes - reset infrastructure state from agent actions
    3. Delete namespace - nuclear option that removes all app + chaos resources
    
    This is the ONLY place that should do comprehensive cleanup.
    Deploy/undeploy functions should only handle their specific tasks.
    
    Args:
        namespace: Target namespace for the experiment
        nodes: Dict of node names to IP addresses  
        chaosd_port: Port for chaosd API
        
    Returns:
        Dict with cleanup results for each component
    """
    from kub_mitigation_agent.anomalies import cleanup_all_anomalies
    
    print(f"\n🧹 Pre-experiment cleanup (ensuring clean state)")
    cleanup_results = {
        "anomaly_cleanup": {},
        "node_uncordon": {"success": False},
        "namespace_deletion": {"success": False}
    }
    
    # 1. Stop ALL anomalies using unified cleanup function
    # This stops resource waste immediately
    try:
        print(f"   • Stopping all anomalies...", end="")
        anomaly_results = cleanup_all_anomalies(
            namespaces=[namespace],
            nodes=nodes,
            chaosd_port=chaosd_port
        )
        cleanup_results["anomaly_cleanup"] = anomaly_results
        
        # Report results
        summary = anomaly_results.get("summary", {})
        total_cleaned = summary.get("total_cleaned", 0)
        all_successful = summary.get("all_successful", False)
        
        if total_cleaned > 0:
            print(f" ✅ Stopped {total_cleaned} experiments")
        else:
            print(f" ✅ None running")
            
        if not all_successful:
            # Only report REAL problems, not phantom errors from already-cleaned resources
            failed_ns = summary.get("failed_namespaces", [])
            node_anomalies = anomaly_results.get("node_anomalies", {})
            
            details = []
            # Check node anomaly errors - but only if we actually failed to clean something
            # Errors on phantom/stale entries don't count if all listed experiments were deleted
            if isinstance(node_anomalies, dict):
                for host, stats in node_anomalies.items():
                    if isinstance(stats, dict):
                        listed = stats.get("listed", 0)
                        deleted = stats.get("deleted", 0)
                        errors = stats.get("errors", 0)
                        
                        # Only warn if we failed to delete experiments that actually exist
                        # (listed > 0 but deleted < listed means we found some but couldn't clean them)
                        if listed > 0 and deleted < listed:
                            failed_count = listed - deleted
                            details.append(f"node {host}: failed to clean {failed_count}/{listed} experiments")
            
            # Check pod anomaly failures
            if failed_ns:
                details.append(f"namespaces {', '.join(failed_ns)}: cleanup failed")
            
            # Only print warning if there are ACTUAL problems
            if details:
                print(f"   ⚠️  Issues: {'; '.join(details)}")
            
    except Exception as e:
        print(f" ⚠️  Error: {e}")
        logger.warning(f"Anomaly cleanup failed: {e}")
        cleanup_results["anomaly_cleanup"] = {"error": str(e)}
    
    # 2. Uncordon all nodes (reset infrastructure state from agent)
    try:
        print(f"   • Uncordoning nodes...", end="")
        success = uncordon_all_nodes()
        cleanup_results["node_uncordon"]["success"] = success
        if success:
            print(f" ✅ Done")
        else:
            print(f" ⚠️  Some issues")
    except Exception as e:
        print(f" ⚠️  Error: {e}")
        logger.warning(f"Node uncordon failed: {e}")
    
    # 3. Delete namespace (comprehensive cleanup of all app resources)
    # This removes: pods, services, deployments, HPA, and any remaining ChaosMesh CRDs
    try:
        print(f"   • Deleting namespace {namespace}...", end="")
        delete_cmd = f"kubectl delete namespace {namespace} --ignore-not-found=true"
        result = subprocess.run(delete_cmd.split(), capture_output=True, text=True, timeout=30)
        cleanup_results["namespace_deletion"]["success"] = result.returncode == 0
        
        if result.returncode == 0:
            print(f" ✅ Done")
            # Wait for namespace deletion to fully complete
            print(f"   • Waiting for namespace deletion...", end="")
            time.sleep(15)  # Namespace deletion takes time
            print(f" ✅ Complete")
        else:
            print(f" ⚠️  Error: {result.stderr}")
    except Exception as e:
        print(f" ⚠️  Error: {e}")
        logger.warning(f"Namespace deletion failed: {e}")
    
    print(f"   ✓ Cleanup complete - clean state guaranteed\n")
    return cleanup_results


def collect_istio_ingress_metrics(duration_seconds: float) -> Dict[str, Any]:
    """Collect metrics from Istio ingress gateway for the specified time window.
    
    Queries Prometheus for server-side metrics from istio-ingressgateway.
    Returns P95 latency, success rate, and request counts.
    
    Args:
        duration_seconds: Time window to measure (e.g., 60 for last 60 seconds)
        
    Returns:
        Dict with keys:
            - p95_latency_seconds: P95 latency in seconds
            - success_rate_percent: Success rate percentage
            - total_requests: Total requests in window
            - successful_requests: Successful requests (2xx, 3xx)
            - failed_requests: Failed requests (4xx, 5xx)
            - source: "istio-ingress" or "unavailable"
    """
    try:
        from ..clients.prometheus_client import get_prometheus_tool
        prometheus_tool = get_prometheus_tool()
        
        metrics = prometheus_tool.get_istio_ingress_metrics(duration_seconds)
        metrics["source"] = "istio-ingress"
        return metrics
        
    except Exception as e:
        logger.warning(f"Failed to collect Istio ingress metrics: {e}")
        return {
            "p95_latency_seconds": 0,
            "success_rate_percent": 0,
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "source": "unavailable"
        }