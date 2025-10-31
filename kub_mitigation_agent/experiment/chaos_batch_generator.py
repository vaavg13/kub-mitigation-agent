#!/usr/bin/env python3
"""
Chaos Batch Generator
Generates chaos configurations based on explicit counts from config.
Randomness is only applied to target selection (nodes, apps, pods).
"""

import random
from typing import Dict, List, Any

# Node stress durations (in stress-ng timeout format)
NODE_STRESS_DURATIONS = ["900s", "1200s", "1800s"]
DEFAULT_SEED = 42


class ChaosBatchGenerator:
    """Generates chaos configurations based on explicit experiment specifications."""
    
    def __init__(self, base_config: Dict[str, Any], seed: int = DEFAULT_SEED):
        """
        Initialize the chaos batch generator.
        
        Args:
            base_config: Base experiment configuration containing chaos_experiments spec
            seed: Random seed for reproducibility (used only for target selection)
        """
        self.base_config = base_config
        self.seed = seed
        random.seed(seed)
        
        # Extract available nodes and apps from base config
        self.available_nodes = list(base_config.get("node_resources", {}).keys())
        self.available_apps = base_config.get("available_deployments", [])
        
        if not self.available_nodes:
            raise ValueError("No nodes found in base_config.node_resources")
        if not self.available_apps:
            raise ValueError("No available deployments found in base_config.available_deployments")
        
        # Parse chaos experiments specification
        self.chaos_experiments_spec = base_config.get("chaos_experiments", {})
        
        print(f"🎲 Chaos Batch Generator initialized (seed: {seed})")
        print(f"📊 Available nodes: {len(self.available_nodes)}")
        print(f"📊 Available apps: {len(self.available_apps)}")
    
    def _generate_pod_level_chaos(self, fault_type: str, intensity: str, target_mode: str, count: int) -> List[Dict[str, Any]]:
        """Generate pod-level chaos configurations (cpu_stress, memory_stress, pod_failure)."""
        configs = []
        
        for i in range(count):
            config = {
                "mode": "chaos_only",
                "fault_type": fault_type,
                "intensity": intensity,
                "duration": "3600s",
                "seed": self.seed,
                "target_mode": target_mode,
            }
            
            # Randomly select target based on mode
            if target_mode in ["one_pod", "all_pods_app"]:
                target_app = random.choice(self.available_apps)
                config["target_app"] = target_app
                config["description"] = f"{fault_type} on {target_app} ({target_mode}, {intensity})"
            elif target_mode == "all_pods_node":
                node_name = random.choice(self.available_nodes)
                config["node_name"] = node_name
                config["target_app"] = "node-wide"
                config["description"] = f"{fault_type} on node {node_name} ({intensity})"
            
            configs.append(config)
        
        return configs
    
    def _generate_node_stress(self, count: int) -> List[Dict[str, Any]]:
        """Generate node-level stress configurations."""
        configs = []
        
        for i in range(count):
            # Randomly select node and stress duration
            node_name = random.choice(self.available_nodes)
            stress_duration = random.choice(NODE_STRESS_DURATIONS)
            
            config = {
                "mode": "node_stress_only",
                "fault_type": "node_stress",
                "intensity": f"duration:{stress_duration}",
                "duration": "3600s",
                "seed": self.seed,
                "node_name": node_name,
                "stress_duration": stress_duration,
                "description": f"Node stress on {node_name}: CPU stress for {stress_duration}"
            }
            configs.append(config)
        
        return configs
    
    def _generate_traffic_spikes(self, intensity: str, count: int) -> List[Dict[str, Any]]:
        """Generate traffic spike configurations."""
        configs = []
        
        for i in range(count):
            config = {
                "mode": "traffic_spike_only",
                "fault_type": "traffic_spike",
                "intensity": intensity,
                "duration": "3600s",
                "seed": self.seed,
                "description": f"Traffic spike: {intensity} intensity"
            }
            configs.append(config)
        
        return configs
    
    def _generate_no_failure(self, count: int) -> List[Dict[str, Any]]:
        """Generate no-failure baseline configurations."""
        configs = []
        
        for i in range(count):
            config = {
                "mode": "no_failure",
                "fault_type": "none",
                "intensity": "none",
                "duration": "3600s",
                "seed": self.seed,
                "description": f"No failure baseline experiment {i+1}"
            }
            configs.append(config)
        
        return configs
    
    def generate_from_spec(self) -> List[Dict[str, Any]]:
        """
        Generate chaos configurations based on explicit specification in config.
        
        Returns:
            List of chaos configurations ready for batch execution
        """
        if not self.chaos_experiments_spec:
            raise ValueError("No chaos_experiments specification found in config")
        
        all_configs = []
        
        # 1. Pod-level chaos
        pod_level_spec = self.chaos_experiments_spec.get("pod_level", {})
        for fault_type, intensities in pod_level_spec.items():
            for intensity, target_modes in intensities.items():
                for target_mode, count in target_modes.items():
                    configs = self._generate_pod_level_chaos(fault_type, intensity, target_mode, count)
                    all_configs.extend(configs)
                    print(f"💻 Generated {count} {fault_type} configs ({intensity}, {target_mode})")
        
        # 2. Node-level chaos (host CPU stress)
        node_level_spec = self.chaos_experiments_spec.get("node_level", {})
        node_stress_count = node_level_spec.get("node_stress", 0)
        if node_stress_count > 0:
            configs = self._generate_node_stress(node_stress_count)
            all_configs.extend(configs)
            print(f"🔥 Generated {node_stress_count} node_stress configs")
        
        # 3. Traffic spikes
        traffic_spike_spec = self.chaos_experiments_spec.get("traffic_spike", {})
        for intensity, count in traffic_spike_spec.items():
            if count > 0:
                configs = self._generate_traffic_spikes(intensity, count)
                all_configs.extend(configs)
                print(f"📈 Generated {count} traffic_spike configs ({intensity})")
        
        # 4. No failure baselines
        no_failure_count = self.chaos_experiments_spec.get("no_failure", 0)
        if no_failure_count > 0:
            configs = self._generate_no_failure(no_failure_count)
            all_configs.extend(configs)
            print(f"✅ Generated {no_failure_count} no_failure configs")
        
        # Shuffle for random execution order
        random.shuffle(all_configs)
        print(f"🔀 Configurations shuffled for random execution order")
        
        print(f"📦 Total configurations generated: {len(all_configs)}")
        
        return all_configs
