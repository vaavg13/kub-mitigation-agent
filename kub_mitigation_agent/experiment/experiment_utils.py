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

async def smart_warmup_with_monitoring(config, traffic_generator):
    """Smart warmup that monitors latency until it stabilizes.
    
    Args:
        config: Experiment configuration containing pod_warmup_duration
        traffic_generator: Traffic generator instance with reset_phase_metrics() and get_phase_metrics() methods
    """
    max_warmup_time = config["pod_warmup_duration"]  # Safety limit
    check_interval = 30  # Check every 30 seconds
    stability_window = 3  # Need 3 stable measurements
    stability_threshold = 0.3  # Latency variation < 30% to consider stable
    min_success_rate = 70  # Minimum success rate to consider healthy
    
    latency_history = []
    elapsed_time = 0
    stable_count = 0
    
    print(
        f"🔄 Monitoring warmup (max {max_warmup_time}s, "
        f"checking every {check_interval}s)"
    )
    print(
        f"📊 Looking for latency stabilization: <{stability_threshold * 100}% "
        f"variation for {stability_window} measurements"
    )
    
    # Reset metrics at start of warmup
    traffic_generator.reset_phase_metrics()
    
    while elapsed_time < max_warmup_time:
        await asyncio.sleep(check_interval)
        elapsed_time += check_interval
        
        # Get current metrics for this check interval
        metrics = traffic_generator.get_phase_metrics(check_interval)
        
        # Reset metrics after reading (so next measurement is clean)
        traffic_generator.reset_phase_metrics()
        
        if not metrics or metrics.get('total_requests', 0) == 0:
            print(f"⏳ {elapsed_time}s: No requests yet, continuing warmup...")
            continue
            
        current_latency = metrics.get('p95_latency_seconds', 0)
        success_rate = metrics.get('success_rate_percent', 0)
        
        print(
            f"📈 {elapsed_time}s: P95={current_latency:.3f}s, "
            f"Success={success_rate:.1f}%, Req={metrics.get('total_requests', 0)}"
        )
        
        # Check if service is healthy enough to measure
        if success_rate < min_success_rate:
            print(
                f"⚠️  Success rate too low ({success_rate:.1f}% < {min_success_rate}%), "
                f"continuing warmup..."
            )
            latency_history.clear()  # Reset history due to unhealthy state
            stable_count = 0
            continue
        
        # Add to latency history
        latency_history.append(current_latency)
        
        # Only start checking stability after we have enough history
        if len(latency_history) < stability_window:
            continue
            
        # Keep only recent history
        if len(latency_history) > stability_window:
            latency_history.pop(0)
        
        # Check if latency is stable (low variation)
        if len(latency_history) == stability_window:
            min_latency = min(latency_history)
            max_latency = max(latency_history)
            
            # Avoid division by zero
            if min_latency > 0:
                variation = (max_latency - min_latency) / min_latency
                
                if variation <= stability_threshold:
                    stable_count += 1
                    print(f"✅ Stable measurement {stable_count}: variation {variation:.2%} (threshold: {stability_threshold:.0%})")
                    
                    # Consider stable if we have enough consecutive stable measurements
                    if stable_count >= 2:  # At least 2 consecutive stable intervals
                        print(f"🎯 Latency stabilized at ~{current_latency:.3f}s after {elapsed_time}s")
                        print(f"✅ Warmup complete - services ready for baseline measurement")
                        return
                else:
                    stable_count = 0
                    print(f"📊 Variation {variation:.2%} > {stability_threshold:.0%}, waiting for stability...")
    
    # If we exit the loop, we hit max time
    if latency_history:
        avg_latency = sum(latency_history) / len(latency_history)
        print(f"⏰ Max warmup time reached ({max_warmup_time}s)")
        print(f"📊 Final average latency: {avg_latency:.3f}s")
    else:
        print(f"⚠️  Warmup completed without stable measurements")
    
    print(f"✅ Proceeding to baseline measurement")

def validate_config(config):
    """Validate that all required configuration is present."""
    required_fields = [
        "namespace", "agent_config", "traffic_config"
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
    
    # Validate agent config
    agent_required = ["max_rounds", "agent_timeout", "openai_model"]
    for field in agent_required:
        if field not in config["agent_config"]:
            missing_fields.append(f"agent_config.{field}")
    
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