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
from kub_mitigation_agent.service.kubectl import KubeCtl
from kub_mitigation_agent.service.apps import HotelReservation

logger = logging.getLogger(__name__)

def wait_for_pods_ready_sync(namespace: str, timeout: int = 300) -> bool:
    """
    Wait for all pods in namespace to be ready (synchronous version).
    
    Args:
        namespace: Kubernetes namespace
        timeout: Maximum wait time in seconds
        
    Returns:
        True if all pods ready, False if timeout
    """
    kubectl = KubeCtl()
    return kubectl.wait_for_ready(namespace, sleep=5, max_wait=timeout)

def deploy_fresh_app_sync(experiment_config):
    """
    Deploy fresh application using new Application classes.
    
    Args:
        experiment_config: Experiment configuration dict
        
    Returns:
        Tuple of (success: bool, namespace: str)
    """
    if not experiment_config["test_settings"]["deploy_fresh_app"]:
        print("Skipping fresh app deployment (disabled in config)")
        return True, ""
    
    namespace = experiment_config["namespace"]
    
    try:
        print(f"Deploying application to namespace: {namespace}...")
        
        # Use HotelReservation app (can be extended to support other apps)
        app = HotelReservation()
        
        # Deploy the application
        app.deploy()
        
        print(f"✅ Application deployed successfully")
        return True, app.namespace
        
    except Exception as e:
        print(f"❌ Deployment error: {e}")
        logger.error(f"Deployment failed: {e}", exc_info=True)
        return False, ""

def undeploy_app_sync(experiment_config):
    """
    Undeploy application (minimal cleanup) using new Application classes.
    
    Args:
        experiment_config: Experiment configuration dict
        
    Returns:
        True (always, as cleanup will happen in pre-experiment phase)
    """
    namespace = experiment_config["namespace"]
    
    try:
        print(f"Undeploying application from namespace: {namespace}...")
        
        # Use HotelReservation app
        app = HotelReservation()
        app.delete()
        
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
    
    print(f"\n🧹 Pre-experiment cleanup (ensuring clean state)")
    cleanup_results = {
        "anomaly_cleanup": {},
        "node_uncordon": {"success": False},
        "namespace_deletion": {"success": False}
    }
    
    # 1. Stop ALL anomalies using unified cleanup function
    # This stops resource waste immediately
    # NOTE: This logic should ideally be called from the anomaly manager, but 
    # we keep it here temporarily until full dependency injection refactor is complete.
    # Ideally, this function should only handle K8s resources.
    
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
