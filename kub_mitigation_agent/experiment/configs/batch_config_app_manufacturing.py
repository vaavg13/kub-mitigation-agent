BATCH_CONFIG = {
    # Target application settings
    "namespace": "app-smart-manufacturing",
    "app_directory": "./APPS",
    
    # Test timing configuration - simplified phases with longer warmup
    "pod_warmup_duration": 60,     # Extended warmup with smart monitoring for service stabilization  
    "baseline_duration": 60,        # Record baseline metrics
    "chaos_warmup_duration": 60,    # Chaos impact + warmup before agent (record metrics during chaos)
    "recovery_duration": 60,        # Recovery after agent execution (record metrics)
    
    # Agent configuration
    "agent_config": {
        "max_rounds": 50,
        "agent_timeout": 120,
        "openai_model": "gpt-4.1",
        "show_reasoning": True,   # Enable reasoning summaries for better explainability  
        "reasoning_in_context": True  # Enable reasoning in context for better reflection
    },
    
    # Batch experiment settings
    "batch_settings": {
        "experiments_count_per_type": 5,  # Number of experiments per chaos type
        "random_seed": 42,                # Random seed for reproducibility
        "delay_between_experiments": 0    # No delay between experiments
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
    
    # Available deployment/app names for chaos targeting
    "available_deployments": [
        "sensor-data-ingestion-edge-site-1",
        "sensor-data-ingestion-edge-site-2",
        "edge-data-preprocessing-edge-site-1",
        "edge-data-preprocessing-edge-site-2",
        "real-time-anomaly-detection-edge-site-1",
        "real-time-anomaly-detection-edge-site-2",
        "local-control-actuation-edge-site-1",
        "local-control-actuation-edge-site-2",
        "predictive-maintenance-analytics-cloud",
        "production-optimization-engine-cloud",
        "inventory-supply-chain-mgmt-cloud",
        "centralized-data-lake-cloud",
        "reporting-dashboarding-cloud"
    ],
    
    # Traffic generation configuration
    "traffic_config": {
        "endpoints": [
            "http://172.23.0.5:31119/sensor-data-ingestion-edge-site-1",
            "http://172.23.0.5:31119/sensor-data-ingestion-edge-site-2"
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

# Alert configuration - what the agent receives (matches single experiment setup)
BATCH_ALERT_CONFIG = {
    "alert_template": "🚨 CRITICAL INCIDENT: Performance degradation detected in namespace '{namespace}' at {timestamp}. ALERT TRIGGERS: Service latency degraded from {baseline_latency_p95} to {current_latency_p95} (degradation threshold exceeded), Success rate dropped from {baseline_success_rate}% to {current_success_rate}% (availability threshold exceeded). IMMEDIATE INVESTIGATION AND CORRECTIVE ACTION REQUIRED.",
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