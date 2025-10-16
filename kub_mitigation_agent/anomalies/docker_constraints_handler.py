#!/usr/bin/env python3
"""
Docker Constraints Handler
Handles Docker-level resource constraints for k3d nodes.
"""

import subprocess
from typing import Dict, List, Any


class DockerConstraintsHandler:
    """Handles Docker-level resource constraints for k3d nodes."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    def get_node_docker_resources(self, node_name: str) -> Dict[str, str]:
        """Get current Docker resource limits for a k3d node."""
        try:
            # Get current container resources
            inspect_cmd = f"docker inspect {node_name} --format='{{{{.HostConfig.Memory}}}},{{{{.HostConfig.NanoCpus}}}}'"
            result = subprocess.run(inspect_cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"⚠️  Failed to inspect node {node_name}: {result.stderr}")
                return {}
            
            memory_bytes, nano_cpus = result.stdout.strip().split(',')
            
            # Convert to human-readable format
            resources = {}
            if memory_bytes != "0":
                memory_mb = int(memory_bytes) // (1024 * 1024)
                resources["memory"] = f"{memory_mb}m"
            else:
                resources["memory"] = "unlimited"
                
            if nano_cpus != "0":
                cpus = int(nano_cpus) / 1_000_000_000
                resources["cpus"] = str(cpus)
            else:
                resources["cpus"] = "unlimited"
                
            return resources
            
        except Exception as e:
            print(f"⚠️  Error getting node resources: {e}")
            return {}

    def apply_node_docker_constraints(self, node_name: str, cpu_limit: str = "0.3", memory_limit: str = "512m") -> bool:
        """Apply restrictive Docker-level constraints to a k3d node."""
        try:
            print(f"🔒 Applying Docker-level resource constraints to {node_name}...")
            
            # Apply the constraints (don't quote numeric values)
            docker_cmd = f"docker update --cpus={cpu_limit} --memory={memory_limit} {node_name}"
            result = subprocess.run(docker_cmd.split(), capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ Node {node_name} constrained: CPU={cpu_limit} cores, Memory={memory_limit}")
                print(f"🎯 This makes node-level stress persistent - pod deletion won't help!")
                return True
            else:
                print(f"❌ Failed to constrain node: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error applying node constraints: {e}")
            return False

    def get_all_k3d_nodes(self) -> List[str]:
        """Get list of all k3d node container names."""
        try:
            # Get all containers with k3d labels
            cmd = "docker ps --filter label=app=k3d --format {{.Names}}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                nodes = [line.strip() for line in result.stdout.split('\n') if line.strip() and 'agent' in line]
                return nodes
            else:
                print(f"⚠️  Could not list k3d nodes: {result.stderr}")
                return []
                
        except Exception as e:
            print(f"❌ Error listing k3d nodes: {e}")
            return []

    def get_kubernetes_node_status(self) -> Dict[str, Dict[str, Any]]:
        """Get Kubernetes node status and scheduling information."""
        try:
            # Get node status with custom columns for schedulability
            cmd = "kubectl get nodes -o custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type=='Ready')].status,SCHEDULABLE:.spec.unschedulable --no-headers"
            result = subprocess.run(cmd.split(), capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"⚠️  Could not get Kubernetes node status: {result.stderr}")
                return {}
            
            node_status = {}
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        node_name = parts[0]
                        ready_status = parts[1]
                        unschedulable = parts[2] if parts[2] != '<none>' else 'false'
                        
                        node_status[node_name] = {
                            'ready': ready_status.lower() == 'true',
                            'schedulable': unschedulable.lower() != 'true'
                        }
            
            return node_status
            
        except Exception as e:
            print(f"❌ Error getting Kubernetes node status: {e}")
            return {}

    def ensure_nodes_schedulable(self) -> bool:
        """Ensure all k3d nodes are schedulable by uncordoning any cordoned nodes."""
        try:
            # Get current node status
            node_status = self.get_kubernetes_node_status()
            if not node_status:
                return False
            
            uncordon_count = 0
            total_nodes = 0
            
            for node_name, status in node_status.items():
                # Only process k3d agent nodes
                if 'k3d-cec-emulator-agent-' not in node_name:
                    continue
                    
                total_nodes += 1
                
                if not status['schedulable']:
                    uncordon_cmd = f"kubectl uncordon {node_name}"
                    result = subprocess.run(uncordon_cmd.split(), capture_output=True, text=True)
                    
                    if result.returncode == 0:
                        uncordon_count += 1
                    else:
                        print(f"   ❌ Failed to uncordon {node_name}: {result.stderr}")
            
            if uncordon_count > 0:
                print(f"   ✅ Uncordoned {uncordon_count} nodes to ensure schedulability")
            
            return True
            
        except Exception as e:
            print(f"❌ Error ensuring nodes are schedulable: {e}")
            return False

    def reset_all_node_docker_constraints(self) -> bool:
        """Reset Docker constraints for all k3d nodes to their proper resource specifications and ensure they are schedulable."""
        try:
            nodes = self.get_all_k3d_nodes()
            if not nodes:
                return True
            
            # First, ensure all nodes are schedulable (uncordon any cordoned nodes)
            schedulable_success = self.ensure_nodes_schedulable()
            
            # Get node resource specifications from config
            node_resources = self.config.get("node_resources", {})
            if not node_resources:
                return schedulable_success
            
            success_count = 0
            updates_made = 0
            for node_name in nodes:
                try:
                    # Get the proper resource specification for this node
                    target_resources = node_resources.get(node_name)
                    if not target_resources:
                        continue
                    
                    target_cpus = target_resources["cpus"]
                    target_memory = target_resources["memory"]
                    
                    # Check current resources
                    current_resources = self.get_node_docker_resources(node_name)
                    if current_resources:
                        current_cpus = current_resources.get("cpus", "unknown")
                        current_memory = current_resources.get("memory", "unknown")
                        
                        # Check if resources need updating
                        needs_update = (current_cpus != target_cpus or current_memory != target_memory)
                        
                        if needs_update:
                            # Set to proper resource limits
                            update_cmd = f"docker update --cpus={target_cpus} --memory={target_memory} {node_name}"
                            result = subprocess.run(update_cmd.split(), capture_output=True, text=True)
                            
                            if result.returncode == 0:
                                success_count += 1
                                updates_made += 1
                            else:
                                print(f"   ❌ Failed to set limits on {node_name}: {result.stderr}")
                        else:
                            success_count += 1
                        
                except Exception as e:
                    print(f"   ❌ Error processing {node_name}: {e}")
            
            # Single summary line
            total_nodes = len([n for n in nodes if n in node_resources])
            if updates_made > 0:
                print(f"   ✅ Reset {updates_made} nodes to proper resource limits ({success_count}/{total_nodes} successful)")
            else:
                print(f"   ✅ All {total_nodes} nodes already have proper resource limits")
            
            return success_count > 0 and schedulable_success
            
        except Exception as e:
            print(f"❌ Error in Docker resource setup: {e}")
            return False

    def inject_docker_constraints_only(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply Docker-level node constraints without Chaos Mesh."""
        print(f"🐳 === DOCKER-ONLY MODE: Applying node constraints ===")
        
        node_name = config["node_name"]
        cpu_limit = config["docker_cpu_limit"]
        memory_limit = config["docker_memory_limit"]
        
        constraint_success = self.apply_node_docker_constraints(node_name, cpu_limit, memory_limit)
        if constraint_success:
            print(f"✅ Docker-only node constraints applied successfully!")
            print(f"🎯 Node {node_name} limited to CPU={cpu_limit}, Memory={memory_limit}")
            print(f"🎯 This creates persistent resource pressure - scaling/deleting pods won't help!")
            
            # Return experiment record for cleanup purposes
            experiment_record = {
                "name": f"docker-constraints-{node_name}-{config['intensity']}",
                "config": config,
                "docker_only": True  # Flag to skip Chaos Mesh cleanup
            }
            return experiment_record
        else:
            print(f"❌ Failed to apply Docker constraints")
            return None 