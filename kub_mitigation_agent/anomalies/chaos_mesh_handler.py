#!/usr/bin/env python3
"""
Chaos Mesh Handler
Handles Chaos Mesh experiment deployment and management.
Combines template generation, deployment, and cleanup functionality.
"""

import os
import yaml
import random
import subprocess
import tempfile
from typing import Dict, Any, List


INTENSITY_PARAMS = {
    "cpu_stress": {
        "low": {"workers": 1, "load": 50},
        "medium": {"workers": 2, "load": 80},
        "high": {"workers": 4, "load": 95},
        "extreme": {"workers": 16, "load": 100}
    },
    "memory_stress": {
        "low": {"workers": 1, "size": "256MB", "time": "10s"},
        "medium": {"workers": 2, "size": "512MB", "time": "10s"},
        "high": {"workers": 4, "size": "1GB", "time": "10s"},
        "extreme": {"workers": 8, "size": "100%"}
    }
}

FAULT_TYPES = ["cpu_stress", "memory_stress", "pod_failure"]
INTENSITIES = ["low", "medium", "high", "extreme"]
TARGET_MODES = ["one_pod", "all_pods_app", "all_pods_node"]


class ChaosMeshHandler:
    """Handles Chaos Mesh experiment deployment and management."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.namespace = config["namespace"]
        # Get target_app from chaos_config if available (chaos_only mode)
        chaos_config = config.get("chaos_config", {})
        target_app = chaos_config.get("target_app")
        self.app_list = [target_app] if target_app else []
        self.seed = config["chaos_config"]["seed"]
        random.seed(self.seed)
    
    def create_experiment_template(self, fault_type: str, target_mode: str, app: str = None, 
                                 node_name: str = None, intensity: str = "medium", 
                                 duration: str = "60s") -> Dict[str, Any]:
        """Create a chaos experiment template with specified targeting mode"""
        
        # Generate appropriate name based on targeting mode
        if target_mode == "one_pod":
            name = f"{fault_type}-one-{app}-{intensity}".replace("_", "-")
        elif target_mode == "all_pods_app":
            name = f"{fault_type}-all-{app}-{intensity}".replace("_", "-")
        elif target_mode == "all_pods_node":
            name = f"{fault_type}-node-{node_name}-{intensity}".replace("_", "-")
        else:
            raise ValueError(f"Unknown target mode: {target_mode}")
        
        base_template = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "metadata": {
                "name": name,
                "namespace": self.namespace
            },
            "spec": {
                "duration": duration
            }
        }
        
        # Configure targeting mode and selector
        if target_mode == "one_pod":
            base_template["spec"]["mode"] = "one"
            base_template["spec"]["selector"] = {
                "namespaces": [self.namespace],
                "labelSelectors": {"app": app}
            }
        elif target_mode == "all_pods_app":
            base_template["spec"]["mode"] = "all"
            base_template["spec"]["selector"] = {
                "namespaces": [self.namespace],
                "labelSelectors": {"app": app}
            }
        elif target_mode == "all_pods_node":
            base_template["spec"]["mode"] = "all"
            base_template["spec"]["selector"] = {
                "fieldSelectors": {"spec.nodeName": node_name}
            }
        
        # Configure chaos type and parameters
        if fault_type in ["cpu_stress", "memory_stress"]:
            base_template["kind"] = "StressChaos"
            
            stressor_type = "cpu" if fault_type == "cpu_stress" else "memory"
            base_template["spec"]["stressors"] = {
                stressor_type: INTENSITY_PARAMS[fault_type][intensity]
            }
        
        elif fault_type == "pod_failure":
            base_template["kind"] = "PodChaos"
            base_template["spec"]["action"] = "pod-failure"
        
        elif fault_type == "docker_constraints_only":
            # This is a special fault type that only applies Docker constraints
            # Return None to signal that no Chaos Mesh template should be created
            return None
        
        return base_template
    
    def deploy_experiment(self, experiment_config: Dict[str, Any]) -> bool:
        """Deploy a single chaos experiment"""
        try:
            template = experiment_config["template"]
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                yaml.dump(template, temp_file, default_flow_style=False, sort_keys=False)
                temp_file_path = temp_file.name
            
            # Apply to cluster  
            cmd = f"kubectl apply -f {temp_file_path}"
            result = subprocess.run(cmd.split(), capture_output=True, text=True)
            
            # Clean up temp file
            os.unlink(temp_file_path)
            
            if result.returncode == 0:
                self._verify_chaos_deployment(experiment_config)
                return True
            else:
                print(f"❌ Failed to deploy chaos experiment: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error deploying chaos experiment: {e}")
            return False
    
    def _verify_chaos_deployment(self, experiment_config: Dict[str, Any]):
        """Verify that chaos experiment was deployed and check targets"""
        try:
            name = experiment_config["name"]
            fault_type = experiment_config["fault_type"]
            target_mode = experiment_config["target_mode"]
            
            # Determine chaos type for verification
            if fault_type in ["cpu_stress", "memory_stress"]:
                chaos_type = "stresschaos"
            elif fault_type == "pod_failure":
                chaos_type = "podchaos"
            else:
                chaos_type = "chaos"  # fallback
            
            # Check if chaos resource exists
            cmd = f"kubectl get {chaos_type} {name} -n {self.namespace} -o yaml"
            result = subprocess.run(cmd.split(), capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ Chaos experiment {name} deployed successfully")
                
                # Verify targets based on mode
                if target_mode in ["one_pod", "all_pods_app"]:
                    target_app = experiment_config.get("app")
                    if target_app:
                        pod_cmd = f"kubectl get pods -n {self.namespace} -l app={target_app}"
                        pod_result = subprocess.run(pod_cmd.split(), capture_output=True, text=True)
                        
                        if pod_result.returncode == 0:
                            pod_lines = [line for line in pod_result.stdout.split('\n') 
                                       if line.strip() and not line.startswith('NAME')]
                            pod_count = len(pod_lines)
                            print(f"📊 Found {pod_count} target pods for app '{target_app}'")
                
                elif target_mode == "all_pods_node":
                    node_name = experiment_config.get("node_name")
                    if node_name:
                        # Check if node exists
                        node_cmd = f"kubectl get node {node_name}"
                        node_result = subprocess.run(node_cmd.split(), capture_output=True, text=True)
                        
                        if node_result.returncode == 0:
                            print(f"✅ Target node '{node_name}' is available")
                            
                            # Check pods on the node
                            pod_cmd = f"kubectl get pods --all-namespaces --field-selector=spec.nodeName={node_name}"
                            pod_result = subprocess.run(pod_cmd.split(), capture_output=True, text=True)
                            if pod_result.returncode == 0:
                                pod_lines = [line for line in pod_result.stdout.split('\n') 
                                           if line.strip() and not line.startswith('NAMESPACE')]
                                pod_count = len(pod_lines)
                                print(f"📊 Found {pod_count} pods running on node '{node_name}'")
                        else:
                            print(f"⚠️  Target node '{node_name}' not found")
            else:
                print(f"⚠️  Could not verify chaos experiment {name}")
                
        except Exception as e:
            print(f"⚠️  Error verifying deployment: {e}")
    
    def undeploy_experiment(self, experiment_config: Dict[str, Any]) -> bool:
        """Undeploy/clean up a chaos experiment"""
        try:
            name = experiment_config["name"]
            fault_type = experiment_config["fault_type"]
            
            # Determine chaos type
            if fault_type in ["cpu_stress", "memory_stress"]:
                chaos_type = "stresschaos"
            elif fault_type == "pod_failure":
                chaos_type = "podchaos"
            else:
                chaos_type = "chaos"  # fallback
            
            # Delete experiment
            cmd = f"kubectl delete {chaos_type} {name} -n {self.namespace} --ignore-not-found=true"
            result = subprocess.run(cmd.split(), capture_output=True, text=True)
            
            print(f"🧹 Cleaned up: {name}")
            return True
            
        except Exception as e:
            print(f"❌ Error cleaning up {experiment_config['name']}: {e}")
            return False

    def inject_chaos_mesh_only(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Deploy Chaos Mesh experiments without Docker constraints."""
        print(f"⚡ === CHAOS MESH ONLY MODE: Deploying pod-level stress ===")
        
        fault_type = config['fault_type']
        target_mode = config['target_mode']
        target_app = config.get('target_app')
        
        print(f"🎯 Fault type: {fault_type} | Target mode: {target_mode}")

        # Generate template first to get the canonical experiment name
        if target_mode in ["one_pod", "all_pods_app"]:
            if not target_app:
                raise ValueError("target_app is required for app-level chaos")
            print(f"🎯 Target app: {target_app}")
            template = self.create_experiment_template(
                fault_type=fault_type,
                target_mode=target_mode,
                app=target_app,
                intensity=config["intensity"],
                duration=config["duration"]
            )
        elif target_mode == "all_pods_node":
            node_name = config.get("node_name")
            if not node_name:
                raise ValueError("node_name is required for node-level chaos")
            print(f"🎯 Target node: {node_name}")
            template = self.create_experiment_template(
                fault_type=fault_type,
                target_mode=target_mode,
                node_name=node_name,
                intensity=config["intensity"],
                duration=config["duration"]
            )
        else:
            raise ValueError(f"Unknown target_mode: {target_mode}")

        # Get name from template's metadata
        experiment_name = template["metadata"]["name"]
        print(f"📖 Generated experiment name: {experiment_name}")

        # Create chaos experiment record using the canonical name
        experiment_record = {
            "name": experiment_name,
            "fault_type": fault_type,  # Add fault_type for cleanup
            "app": target_app,  # Can be None for node-level chaos
            "config": config,
            "docker_only": False
        }

        # Set experiment duration to 1 hour (will be cleaned up by stop_chaos)
        if template and "spec" in template:
            template["spec"]["duration"] = "3600s"
        
        # Create experiment config for deployment
        experiment_config = {
            "name": experiment_record["name"],
            "template": template,
            "fault_type": fault_type,
            "target_mode": target_mode,
            "intensity": config["intensity"]
        }
        
        # Add target-specific fields for verification/logging
        if target_mode in ["one_pod", "all_pods_app"]:
            experiment_config["app"] = experiment_record["app"]
        elif target_mode == "all_pods_node":
            experiment_config["node_name"] = config["node_name"]
            
        deployment_success = self.deploy_experiment(experiment_config)
        
        if deployment_success:
            print(f"✅ Chaos Mesh experiment deployed successfully")
            return experiment_record
        else:
            print(f"❌ Failed to deploy Chaos Mesh experiment")
            return None
    
    def cleanup_chaos_experiment(self, experiment_config: Dict[str, Any]) -> bool:
        """Clean up a chaos experiment."""
        if experiment_config and not experiment_config.get("docker_only", False):
            return self.undeploy_experiment(experiment_config)
        return True 