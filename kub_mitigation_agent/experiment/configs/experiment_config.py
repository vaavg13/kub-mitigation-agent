# Main test configuration
EXPERIMENT_CONFIG = {
    # Target application settings
    "namespace": "app-iot-gateway",
    "app_directory": "./APPS",
    
    # Test timing configuration - simplified phases with longer warmup
    "pod_warmup_duration": 100,     # Extended warmup with smart monitoring for service stabilization  
    "baseline_duration": 60,        # Record baseline metrics
    "chaos_warmup_duration": 60,    # Chaos impact + warmup before agent (record metrics during chaos)
    "recovery_duration": 60,        # Recovery after agent execution (record metrics)
    
    # Chaos configuration - Choose ONE testing mode:
    
    # # === MODE 1: DOCKER CONSTRAINTS ONLY ===
    # "chaos_config": {
    #     "mode": "docker_only",              # Testing mode
    #     "fault_type": "docker_constraints", # Docker-level resource limits
    #     "intensity": "high",                # Used for logging/naming
    #     "duration": "600s",                 # How long to keep constraints active
    #     "seed": 42,
    #     "node_name": "k3d-cec-emulator-agent-2",
    #     "docker_cpu_limit": "0.3",          # CPU cores limit
    #     "docker_memory_limit": "512m",      # Memory limit
    # },
    
    # === MODE 2: CHAOS MESH ONLY ===
    "chaos_config": {
        "mode": "chaos_only",               # Testing mode
        "target_app": "cloud-analytics-engine-cloud",  # App to target for chaos
        "fault_type": "cpu_stress",         # cpu_stress, memory_stress, pod_failure
        "intensity": "extreme",                # low, medium, high, extreme
        "duration": "600s",            
        "seed": 42,
        "target_mode": "one_pod", # one_pod, all_pods_app, all_pods_node
        # "node_name": "k3d-cec-emulator-agent-2",  # Only needed for all_pods_node
    },
    
    # Agent configuration
    "agent_config": {
        "max_rounds": 50,
        "agent_timeout": 90,
        "openai_model": "gpt-4.1",
        "show_reasoning": True,  # Enable reasoning summaries for better explainability
        "reasoning_in_context": False
    },
    
    # Maps k3d node names to their proper resource limits
    "node_resources": {
        # Cloud nodes (4 CPU cores, 4GB memory)
        "k3d-cec-emulator-agent-0": {"cpus": "4", "memory": "4g"},
        "k3d-cec-emulator-agent-1": {"cpus": "4", "memory": "4g"},
        
        # Edge nodes (2 CPU cores, 2GB memory) 
        "k3d-cec-emulator-agent-2": {"cpus": "2", "memory": "2g"},
        "k3d-cec-emulator-agent-3": {"cpus": "2", "memory": "2g"},
        "k3d-cec-emulator-agent-4": {"cpus": "2", "memory": "2g"},
        "k3d-cec-emulator-agent-5": {"cpus": "2", "memory": "2g"}
    },
    
    # Traffic generation configuration
    "traffic_config": {
        "endpoints": [
            "http://172.23.0.5:31115/iot-device-gateway-edge-site-1",
            "http://172.23.0.5:31115/iot-device-gateway-edge-site-2"
        ],
        "requests_per_second": 5,  # 2 req/s per endpoint = 4 req/s total = 240 req per 60s phase (conservative)
        "request_timeout": 10,
        "collect_metrics": True
    },
    
    # Test behavior settings
    "test_settings": {
        "deploy_fresh_app": True,      # Deploy fresh app instances
        "cleanup_after_test": True,    # Clean up test resources
        "pod_ready_timeout": 300,      # Timeout for pod readiness in seconds
        "skip_warmup_baseline": False, # Skip warmup and baseline phases for faster testing
    }
}

# Alert configuration - what the agent receives
ALERT_CONFIG = {
    "alert_template": "🚨 CRITICAL INCIDENT: Performance degradation detected in namespace '{namespace}' at {timestamp}. ALERT TRIGGERS: Service latency degraded from {baseline_latency_p95} to {current_latency_p95} (degradation threshold exceeded), Success rate dropped from {baseline_success_rate}% to {current_success_rate}% (availability threshold exceeded). IMMEDIATE INVESTIGATION AND CORRECTIVE ACTION REQUIRED. You must: 1) Investigate and identify which specific services/deployments are affected and causing this degradation, 2) Determine root cause of the performance issues, 3) Implement appropriate remediation actions, 4) Validate that service performance is restored to acceptable levels. Use Prometheus metrics and Kubernetes tools to diagnose the situation systematically.",
    "context_fields": [
        "namespace",
        "alert_type", 
        "timestamp",
        "baseline_latency_p95",
        "baseline_success_rate", 
        "current_latency_p95",
        "current_success_rate"
    ]
}

# Logging configuration
LOGGING_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "suppress_libs": [
        "httpx",
        "httpcore"
    ]
}
