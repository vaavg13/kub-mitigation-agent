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
    """Deploy fresh application synchronously BEFORE async context starts."""
    if not experiment_config["test_settings"]["deploy_fresh_app"]:
        print("Skipping fresh app deployment (disabled in config)")
        return True, ""
    
    # Use namespace from config to determine app name (e.g., "app-smart-manufacturing")
    app_name = experiment_config["namespace"]
    app_dir = f"{experiment_config['app_directory']}/{app_name}"
    
    try:
        # Delete the namespace first to ensure completely clean state
        print(f"Deleting namespace to ensure clean state...")
        delete_cmd = f"kubectl delete namespace {experiment_config['namespace']} --ignore-not-found=true"
        subprocess.run(delete_cmd.split(), capture_output=True, text=True)
        
        # Wait for namespace deletion to complete
        print(f"Waiting for namespace deletion to complete...")
        time.sleep(15)
        
        print(f"Undeploying existing {app_name}...")
        try:
            mgr = K8sDeploymentManager.from_deployment_dir(app_dir)
            mgr.undeploy()
            print(f"Undeployment completed")
        except Exception as e:
            print(f"Undeploy warning (may not exist): {e}")
        
        # Wait a bit for cleanup
        time.sleep(10)
        
        print(f"Deploying fresh {app_name}...")
        mgr = K8sDeploymentManager.from_deployment_dir(app_dir)
        mgr.deploy()
        
        print(f"Waiting for pods to be ready...")
        if not wait_for_pods_ready_sync(mgr.namespace):
            print(f"Failed to wait for pods to be ready")
            return False, ""
        
        print(f"Fresh application deployed successfully")
        return True, mgr.namespace
        
    except Exception as e:
        print(f"Deployment error: {e}")
        return False, ""

def undeploy_app_sync(experiment_config):
    """Undeploy application and clean up namespace."""
    # Use namespace from config to determine app name
    app_name = experiment_config["namespace"]
    app_dir = f"{experiment_config['app_directory']}/{app_name}"
    
    try:
        print(f"Undeploying {app_name}...")
        mgr = K8sDeploymentManager.from_deployment_dir(app_dir)
        mgr.undeploy()
        
        # Delete the namespace to ensure complete cleanup
        print(f"Deleting namespace {experiment_config['namespace']}...")
        delete_cmd = f"kubectl delete namespace {experiment_config['namespace']} --ignore-not-found=true"
        subprocess.run(delete_cmd.split(), capture_output=True, text=True)
        
        # Wait for namespace deletion to complete
        print(f"Waiting for namespace deletion to complete...")
        time.sleep(15)
        
        print(f"Application undeployed successfully")
        return True
        
    except Exception as e:
        print(f"Undeployment error: {e}")
        return False

def reset_scheduling_policies() -> bool:
    """Clean residual chaos objects from the cluster.
    
    Returns:
        True if cleanup was successful, False otherwise
    """
    print(f"🔄 Resetting scheduling policies...", end="")
    
    try:
        # Clean up any remaining Chaos Mesh experiments
        cleanup_cmd = "kubectl delete stresschaos,podchaos,networkchaos --all --all-namespaces --ignore-not-found=true"
        result = subprocess.run(cleanup_cmd.split(), capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(" ✅ Done")
            return True
        else:
            print(" ⚠️  Some issues occurred")
            return False
    except Exception as e:
        print(f" ❌ Error: {e}")
        return False


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