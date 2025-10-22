#!/usr/bin/env python3
"""
Chaos Batch Generator
Generates randomized chaos configurations for batch experiments with reproducible seeds.
"""

import random
from typing import Dict, List, Any

# Global settings
DEFAULT_CHAOS_COUNT_PER_TYPE = 5
DEFAULT_SEED = 42

# Anomaly type definitions based on handlers
DOCKER_FAULT_TYPES = ["docker_constraints"]
CHAOS_MESH_FAULT_TYPES = ["cpu_stress", "memory_stress", "pod_failure"]  # Removed network types

# Intensity configurations
CHAOS_MESH_INTENSITIES = ["extreme"]
CHAOS_MESH_TARGET_MODES = ["one_pod", "all_pods_app", "all_pods_node"]

# Docker constraints - very low limits to simulate node malfunction
DOCKER_CPU_LIMITS = ["0.2"]  # Very low CPU to simulate malfunction
DOCKER_MEMORY_LIMITS = ["128m"]  # Very low memory to simulate malfunction

# Removed network intensities - no longer needed

class ChaosBatchGenerator:
    """Generates randomized chaos configurations for batch experiments."""
    
    def __init__(self, base_config: Dict[str, Any], seed: int = DEFAULT_SEED):
        """
        Initialize the chaos batch generator.
        
        Args:
            base_config: Base experiment configuration containing node_resources and available apps
            seed: Random seed for reproducibility
        """
        self.base_config = base_config
        self.seed = seed
        random.seed(seed)
        
        # Extract available nodes and apps from base config
        self.available_nodes = list(base_config.get("node_resources", {}).keys())
        self.available_apps = self._extract_available_apps(base_config)
        
        if not self.available_nodes:
            raise ValueError("No nodes found in base_config.node_resources")
        
        print(f"🎲 Chaos Batch Generator initialized (seed: {seed})")
        print(f"📊 Available nodes: {len(self.available_nodes)}")
        print(f"📊 Available apps: {len(self.available_apps)}")
    
    def _extract_available_apps(self, base_config: Dict[str, Any]) -> List[str]:
        """Extract available app names from the base configuration."""
        # Get available deployments from the base config
        available_deployments = base_config.get("available_deployments", [])
        
        if available_deployments:
            return available_deployments
        else:
            raise ValueError("No available deployments found in base_config.available_deployments")
        

    def generate_docker_constraints_configs(self, count: int = DEFAULT_CHAOS_COUNT_PER_TYPE) -> List[Dict[str, Any]]:
        """Generate random Docker constraints configurations."""
        configs = []
        
        for i in range(count):
            # Randomly select node, CPU limit, and memory limit
            node_name = random.choice(self.available_nodes)
            cpu_limit = random.choice(DOCKER_CPU_LIMITS)
            memory_limit = random.choice(DOCKER_MEMORY_LIMITS)
            
            config = {
                "mode": "docker_only",
                "fault_type": "docker_constraints",
                "intensity": f"cpu:{cpu_limit},mem:{memory_limit}",  # Combined intensity descriptor
                "duration": "3600s",  # Set to 1 hour, will be cleaned up manually
                "seed": self.seed,
                "node_name": node_name,
                "docker_cpu_limit": cpu_limit,
                "docker_memory_limit": memory_limit,
                "description": f"Docker constraints on {node_name}: CPU={cpu_limit}, Memory={memory_limit}"
            }
            configs.append(config)
        
        return configs
    
    def generate_comprehensive_batch(self, per_chaos_config_count: int = DEFAULT_CHAOS_COUNT_PER_TYPE) -> List[Dict[str, Any]]:
        """
        Generate a comprehensive batch of anomalies.
        
        Args:
            per_chaos_config_count: Number of configurations to generate per anomaly type
            
        Returns:
            List of chaos configurations ready for batch execution
            
        Generates:
        - cpu_stress (per_chaos_config_count configs)
        - memory_stress (per_chaos_config_count configs)  
        - pod_failure (per_chaos_config_count configs)
        - docker_constraints (per_chaos_config_count configs)
        - no_failure (per_chaos_config_count configs)
        """
        all_configs = []
        
        # 1. CPU stress chaos
        for i in range(per_chaos_config_count):
            intensity = random.choice(CHAOS_MESH_INTENSITIES)
            target_mode = random.choice(CHAOS_MESH_TARGET_MODES)
            
            config = {
                "mode": "chaos_only",
                "fault_type": "cpu_stress",
                "intensity": intensity,
                "duration": "3600s",  # Set to 1 hour, will be cleaned up manually
                "seed": self.seed,
                "target_mode": target_mode,
            }
            
            if target_mode in ["one_pod", "all_pods_app"]:
                target_app = random.choice(self.available_apps)
                config["target_app"] = target_app
                config["description"] = f"cpu_stress on {target_app} ({target_mode}, {intensity})"
            elif target_mode == "all_pods_node":
                node_name = random.choice(self.available_nodes)
                config["node_name"] = node_name
                config["target_app"] = "node-wide"
                config["description"] = f"cpu_stress on node {node_name} ({intensity})"
            
            all_configs.append(config)
        print(f"💻 Generated {per_chaos_config_count} cpu_stress configurations")
        
        # 2. Memory stress chaos  
        for i in range(per_chaos_config_count):
            intensity = random.choice(CHAOS_MESH_INTENSITIES)
            target_mode = random.choice(CHAOS_MESH_TARGET_MODES)
            
            config = {
                "mode": "chaos_only",
                "fault_type": "memory_stress",
                "intensity": intensity,
                "duration": "3600s",  # Set to 1 hour, will be cleaned up manually
                "seed": self.seed,
                "target_mode": target_mode,
            }
            
            if target_mode in ["one_pod", "all_pods_app"]:
                target_app = random.choice(self.available_apps)
                config["target_app"] = target_app
                config["description"] = f"memory_stress on {target_app} ({target_mode}, {intensity})"
            elif target_mode == "all_pods_node":
                node_name = random.choice(self.available_nodes)
                config["node_name"] = node_name
                config["target_app"] = "node-wide"
                config["description"] = f"memory_stress on node {node_name} ({intensity})"

            all_configs.append(config)
        print(f"💾 Generated {per_chaos_config_count} memory_stress configurations")
        
        # 3. Pod failure chaos
        for i in range(per_chaos_config_count):
            intensity = random.choice(CHAOS_MESH_INTENSITIES)
            target_mode = random.choice(CHAOS_MESH_TARGET_MODES)
            
            config = {
                "mode": "chaos_only",
                "fault_type": "pod_failure",
                "intensity": intensity,
                "duration": "3600s",  # Set to 1 hour, will be cleaned up manually
                "seed": self.seed,
                "target_mode": target_mode,
            }

            if target_mode in ["one_pod", "all_pods_app"]:
                target_app = random.choice(self.available_apps)
                config["target_app"] = target_app
                config["description"] = f"pod_failure on {target_app} ({target_mode}, {intensity})"
            elif target_mode == "all_pods_node":
                node_name = random.choice(self.available_nodes)
                config["node_name"] = node_name
                config["target_app"] = "node-wide"
                config["description"] = f"pod_failure on node {node_name} ({intensity})"
            
            all_configs.append(config)
        print(f"☠️ Generated {per_chaos_config_count} pod_failure configurations")
        
        # 4. Docker constraints (node failure)
        docker_configs = self.generate_docker_constraints_configs(per_chaos_config_count)
        all_configs.extend(docker_configs)
        print(f"🐳 Generated {per_chaos_config_count} docker_constraints configurations")
        
        # 5. No failure (baseline)
        for i in range(per_chaos_config_count):
            config = {
                "mode": "no_failure",
                "fault_type": "none",
                "intensity": "none",
                "duration": "3600s",  # Set to 1 hour, will be cleaned up manually
                "seed": self.seed,
                "description": f"No failure baseline experiment {i+1}"
            }
            all_configs.append(config)
        print(f"✅ Generated {per_chaos_config_count} no_failure configurations")
        
        # Shuffle for random execution order
        random.shuffle(all_configs)
        print(f"🔀 Configurations shuffled for random execution order")
        
        print(f"📦 Total configurations generated: {len(all_configs)}")

        return all_configs