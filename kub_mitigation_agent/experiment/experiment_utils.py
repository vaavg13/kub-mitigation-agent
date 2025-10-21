#!/usr/bin/env python3
"""
Experiment Utilities
Helper functions for experiment configuration and validation.
"""

import asyncio
import time
import subprocess
from typing import Dict, Any
from kubernetes import client, config
from mu_bench.deployers.manager import K8sDeploymentManager

def validate_config(config):
    """Validate that all required configuration is present.

    Agent config is now loaded from YAML separately; do not require it here.
    """
    required_fields = [
        "namespace", "traffic_config"
    ]
    
    missing_fields = []
    
    for field in required_fields:
        if field not in config:
            missing_fields.append(field)
    
    # Validate chaos config based on mode
    chaos_config = config.get("chaos_config", {})
    mode = chaos_config.get("mode")
    
    if mode == "chaos_only":
        # For chaos_only mode, target_app is required
        if "target_app" not in chaos_config:
            missing_fields.append("chaos_config.target_app")
    
    if missing_fields:
        raise ValueError(f"Missing required configuration fields: {missing_fields}")
    
    # Validate traffic config
    traffic_required = ["endpoints", "requests_per_second", "request_timeout"]
    for field in traffic_required:
        if field not in config["traffic_config"]:
            missing_fields.append(f"traffic_config.{field}")
    
    if missing_fields:
        raise ValueError(f"Missing required configuration fields: {missing_fields}")
    
    return True 

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
        
    print(f"\nDeploying fresh application...")
    
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

def extract_prometheus_latency(prometheus_metrics: Dict[str, Any], namespace: str) -> str:
    """Extract average P95 latency value as simple number."""
    if not prometheus_metrics or not prometheus_metrics.get("metrics", {}).get("istio_latency"):
        return "unknown"
    
    istio_data = prometheus_metrics["metrics"]["istio_latency"].get("data", [])
    if not istio_data:
        return "unknown"
    
    # Filter for target namespace
    target_services = [s for s in istio_data if s.get("namespace") == namespace]
    if not target_services:
        return "unknown"
    
    # Return average latency as a simple number
    avg_latency = sum(s.get("p95_latency_ms", 0) for s in target_services) / len(target_services)
    return f"{avg_latency:.1f}" 