#!/usr/bin/env python3
"""
Main Execution Script for Chaos Injection and Mitigation Test
Orchestrates the complete test workflow using modular components.
"""

import asyncio
import logging
import sys
import os
import time
from pathlib import Path
import subprocess

# Add project root to path for imports
project_root = Path(__file__).parent
sys.path.append(str(project_root))

# CRITICAL: Import Locust FIRST to do SSL monkey-patching before Kubernetes client
# This prevents SSL recursion errors
try:
    import locust  # Import Locust first to ensure proper SSL monkey-patching
except ImportError:
    pass  # If Locust not available, continue without it

# Import configuration and test modules
from nl_interface.experiment.experiment_utils import (
    validate_config,
    deploy_fresh_app_sync,
    wait_for_pods_ready_sync
)
from nl_interface.experiment.chaos_mitigation_experiment import ChaosAndMitigationExperiment
from nl_interface.experiment.configs.experiment_config import EXPERIMENT_CONFIG, ALERT_CONFIG, LOGGING_CONFIG


def setup_logging():
    """Setup logging configuration."""
    log_config = LOGGING_CONFIG.copy()
    
    # Configure basic logging
    logging.basicConfig(
        level=getattr(logging, log_config["level"]),
        format=log_config["format"]
    )

    # Suppress verbose logs from specified libraries
    for lib in log_config["suppress_libs"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

def check_prerequisites():
    """Check that all prerequisites are met."""
    print("Checking prerequisites...")
    
    # Check OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable must be set")
        return False
    
    # Validate configuration
    try:
        validate_config()
        print("Configuration validated")
    except ValueError as e:
        print(f"Configuration validation failed: {e}")
        return False
    
    return True

def print_experiment_info():
    """Print information about the experiment to be run."""
    config = EXPERIMENT_CONFIG.copy()
    
    print("CHAOS EXPERIMENT CONFIGURATION")
    print("=" * 40)
    print(f"Namespace: {config['namespace']}")
    print(f"Chaos: {config['chaos_config']['fault_type']} ({config['chaos_config']['intensity']})")
    print(f"Agent: {config['agent_config']['openai_model']} (max {config['agent_config']['max_rounds']} rounds)")
    print("=" * 40)

async def run_experiment(deployment_success=True, namespace=""):
    """Run the complete chaos injection and mitigation experiment."""
    # Get configurations
    experiment_config = EXPERIMENT_CONFIG.copy()
    alert_config = ALERT_CONFIG.copy()
    
    # Create test instance
    test = ChaosAndMitigationExperiment(experiment_config, alert_config)
    
    try:
        # Run the experiment, indicating deployment was already done
        results = await test.run_full_experiment(
            deployment_already_done=deployment_success,
            deployment_namespace=namespace
        )
        return results
    except KeyboardInterrupt:
        print(f"\nExperiment interrupted! Performing emergency cleanup...")
        await test.emergency_cleanup()
        raise

def print_experiment_summary(results):
    """Print experiment summary without status information."""
    # Show phase metrics summary
    if results.get('phase_metrics'):
        print(f"\nPhase metrics collected:")
        for phase, metrics in results['phase_metrics'].items():
            print(f"  {phase}: {metrics['total_requests']} requests, {metrics['success_rate_percent']}% success")
    
    if results.get('agent_actions'):
        print(f"\nAgent took {len(results['agent_actions'])} action(s)")

async def main_async(deployment_success, namespace):
    """Async part of main execution function."""
    try:
        # Run the experiment
        print(f"\nStarting experiment...")
        results = await run_experiment(deployment_success, namespace)
        
        # Print experiment summary
        print_experiment_summary(results)
        
        # Return appropriate exit code
        return 0 if results["success"] else 1
        
    except KeyboardInterrupt:
        print(f"\nExperiment interrupted (Ctrl+C)")
        print(f"Emergency cleanup completed")
        return 130  # Standard exit code for Ctrl+C
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        logging.exception("Unexpected error in main execution")
        return 1

def main():
    """Main execution function."""
    try:
        # Setup logging
        setup_logging()
        
        # Check prerequisites
        if not check_prerequisites():
            return 1
        
        # Print experiment information
        print_experiment_info()
        
        # Ask for confirmation
        config = EXPERIMENT_CONFIG.copy()
        print(f"\nThis experiment will deploy fresh apps, inject chaos, generate traffic,")
        print(f"and run AI agent mitigation.")
        
        try:
            confirmation = input(f"\nProceed? (y/N): ").strip().lower()
            if confirmation not in ['y', 'yes']:
                print("Experiment cancelled")
                return 0
        except KeyboardInterrupt:
            print("\nExperiment cancelled")
            return 0
        
        # Deploy application synchronously BEFORE async context
        print(f"\nDeploying application (before async context)...")
        deployment_success, namespace = deploy_fresh_app_sync(config)
        
        if not deployment_success:
            print("Failed to deploy application")
            return 1
        
        # Now run the async part of the experiment
        return asyncio.run(main_async(deployment_success, namespace))
        
    except KeyboardInterrupt:
        print(f"\nExperiment cancelled (Ctrl+C)")
        return 130  # Standard exit code for Ctrl+C
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        logging.exception("Unexpected error in main execution")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code) 