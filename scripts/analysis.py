import pandas as pd
import json
import os
from typing import List, Dict, Any

# Hardcoded paths to the experiment logs directories
LOG_DIRECTORIES = [
    "DATASET_LOGS/batch_20250711_093622_app-smart-manufacturing",
    "DATASET_LOGS/batch_20250710_234233_app-smart-manufacturing",
    "DATASET_LOGS/batch_20250710_230217_app-smart-manufacturing",
    "DATASET_LOGS/batch_20250710_213510_app-iot-gateway",
    "DATASET_LOGS/batch_20250712_193327_app-smart-city",
    "DATASET_LOGS/batch_20250712_213934_app-smart-city"
]

# Hardcoded paths for directories to be included ONLY in success rate analysis
SUCCESS_ONLY_LOG_DIRECTORIES = [
    "DATASET_LOGS/batch_20250710_150954_app-iot-gateway"
]

def agent_took_no_system_changing_actions(actions: List[Dict[str, Any]]) -> bool:
    """
    Checks if the agent performed any actions that change the system state.
    Returns True if no changing actions were taken, False otherwise.
    """
    # Define functions and subcommands that are considered system-changing.
    # For kubectl_rollout, only 'restart' is changing. 'status' is safe.
    # For others, any use of the function is considered changing.
    CHANGING_ACTIONS = {
        "kubectl_rollout": ["restart"],
        "kubectl_delete": None,  # None means any use is changing
        "kubectl_apply": None,
        "kubectl_scale": None,
        "kubectl_cordon": None,
        "kubectl_drain": None,
    }

    for action in actions:
        if action.get('type') == 'mcp_call':
            function_name = action.get('function')
            if function_name in CHANGING_ACTIONS:
                changing_subcommands = CHANGING_ACTIONS[function_name]
                if changing_subcommands is None:
                    return False  # Any use of this function is a changing action

                parameters = action.get('parameters', {})
                subcommand = parameters.get('subCommand')
                if subcommand in changing_subcommands:
                    return False  # This specific subcommand is a changing action
    
    return True  # No system-changing actions found


def analyze_experiment(experiment_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyzes a single experiment log to determine if the agent correctly
    identified the problem location.
    """
    chaos_config = experiment_data.get('chaos_config', {})
    agent_actions = experiment_data.get('agent_actions', [])
    problem_location_data = experiment_data.get('problem_location')
    mode = chaos_config.get('mode')
    experiment_success = experiment_data.get('experiment_success', False)
    namespace = experiment_data.get('namespace', 'N/A')
    num_rounds = len(agent_actions)

    agent_locations = []
    if isinstance(problem_location_data, list):
        agent_locations = [loc.get('name') for loc in problem_location_data if loc.get('name')]

    ground_truth_target = None
    if mode == 'chaos_only':
        app = chaos_config.get('target_app')
        ground_truth_target = None if app == 'all_pods_node' else app
    

    is_node_wise_chaos = (mode == 'chaos_only' and chaos_config.get('target_app') == 'all_pods_node')

    correctness = False
    if is_node_wise_chaos:
        correctness = experiment_success
    elif mode == "no_failure":
        correctness = agent_took_no_system_changing_actions(agent_actions)
    elif ground_truth_target:
        correctness = any(ground_truth_target in loc for loc in agent_locations)

    # Extract latency metrics
    baseline_latency = experiment_data.get('baseline_metrics', {}).get('p95_latency_seconds', 'N/A')
    chaos_latency = experiment_data.get('chaos_metrics', {}).get('p95_latency_seconds', 'N/A')
    recovery_latency = experiment_data.get('recovery_metrics', {}).get('p95_latency_seconds', 'N/A')
    
    fault_type = chaos_config.get('fault_type', 'none')
    if fault_type == 'none':
        fault_type = 'no_fault'

    return {
        'experiment_id': experiment_data.get('experiment_id', 'N/A'),
        'fault_type': fault_type,
        'ground_truth': ground_truth_target or 'None',
        'agent_locations': agent_locations if agent_locations else 'None',
        'correct_identification': correctness,
        'baseline_latency_p95': baseline_latency,
        'chaos_latency_p95': chaos_latency,
        'recovery_latency_p95': recovery_latency,
        'experiment_success': experiment_success,
        'namespace': namespace,
        'num_rounds': num_rounds,
    }

def main():
    """
    Loads all experiment logs from multiple directories, analyzes them, and reports
    on the agent's problem identification accuracy and experiment success rates.
    """
    # --- Part 1: Identification Analysis ---
    identification_results = []
    for logs_directory in LOG_DIRECTORIES:
        if not os.path.isdir(logs_directory):
            print(f"Warning: Directory not found at '{logs_directory}', skipping.")
            continue

        for filename in sorted(os.listdir(logs_directory)):
            if filename.endswith('.json'):
                filepath = os.path.join(logs_directory, filename)
                with open(filepath, 'r') as f:
                    try:
                        data = json.load(f)
                        identification_results.append(analyze_experiment(data))
                    except json.JSONDecodeError:
                        print(f"Warning: Could not decode JSON from {filepath}")
                    except Exception as e:
                        print(f"Warning: Error processing {filepath}: {e}")

    if not identification_results:
        print("No valid experiment logs found for identification analysis.")
    
    identification_df = pd.DataFrame(identification_results)

    if not identification_df.empty:
        # Display detailed results for each experiment in a clear, formatted way
        print("--- Detailed Identification Results ---")
        for _, row in identification_df.iterrows():
            print("-" * 50)
            print(f"Experiment ID:          {row['experiment_id']}")
            print(f"Fault Type:             {row['fault_type']}")
            print(f"Ground Truth:           {row['ground_truth']}")
            
            agent_locs = row['agent_locations']
            # Format the list of locations for clear, multi-line display
            if isinstance(agent_locs, list):
                locations_str = "\n  - " + "\n  - ".join(agent_locs)
            else:
                locations_str = f" {agent_locs}"
                
            print(f"Agent Locations Found: {locations_str}")
            print(f"Correct Identification: {row['correct_identification']}")
            
            baseline_lat = row['baseline_latency_p95']
            chaos_lat = row['chaos_latency_p95']
            recovery_lat = row['recovery_latency_p95']
            print(f"P95 Latency (s):        Baseline={baseline_lat}, Chaos={chaos_lat}, Recovery={recovery_lat}")
        print("-" * 50)
        
        print("\n" + "="*50 + "\n")

        # Calculate and display aggregate accuracy
        accuracy_by_chaos = identification_df.groupby('fault_type').agg(
            Total_Experiments=('correct_identification', 'count'),
            Correct_Identifications=('correct_identification', 'sum'),
            Average_Rounds=('num_rounds', 'mean')
        ).astype({
            'Total_Experiments': int,
            'Correct_Identifications': int
        })

        if 'Total_Experiments' in accuracy_by_chaos.columns and not accuracy_by_chaos.empty:
            accuracy_by_chaos['Accuracy_Percentage'] = (
                (accuracy_by_chaos['Correct_Identifications'] / accuracy_by_chaos['Total_Experiments']) * 100
            ).round(1)
            accuracy_by_chaos['Average_Rounds'] = accuracy_by_chaos['Average_Rounds'].round(1)

        print("Problem Location Identification Accuracy by Chaos Type:")
        print(accuracy_by_chaos)

        # Calculate and display overall accuracy
        total_experiments = accuracy_by_chaos['Total_Experiments'].sum()
        total_correct = accuracy_by_chaos['Correct_Identifications'].sum()

        if total_experiments > 0:
            overall_accuracy_percentage = (total_correct / total_experiments) * 100
            print("\n" + "="*50)
            print(f"Overall Identification Accuracy: {total_correct}/{total_experiments} ({overall_accuracy_percentage:.1f}%)")
            print("="*50)

    # --- Part 2: Experiment Success Rate Analysis (for ALL batches) ---
    all_experiments_for_success = []
    if not identification_df.empty:
        all_experiments_for_success.extend(identification_df[['experiment_success', 'fault_type', 'namespace', 'num_rounds']].to_dict('records'))

    for logs_directory in SUCCESS_ONLY_LOG_DIRECTORIES:
        if not os.path.isdir(logs_directory):
            print(f"Warning: Success-only directory not found at '{logs_directory}', skipping.")
            continue

        for filename in sorted(os.listdir(logs_directory)):
            if filename.endswith('.json'):
                filepath = os.path.join(logs_directory, filename)
                with open(filepath, 'r') as f:
                    try:
                        data = json.load(f)
                        fault_type = data.get('chaos_config', {}).get('fault_type', 'none')
                        if fault_type == 'none':
                            fault_type = 'no_fault'
                        
                        all_experiments_for_success.append({
                            'experiment_success': data.get('experiment_success', False),
                            'fault_type': fault_type,
                            'namespace': data.get('namespace', 'N/A'),
                            'num_rounds': len(data.get('agent_actions', [])),
                        })
                    except json.JSONDecodeError:
                        print(f"Warning: Could not decode JSON from {filepath}")
                    except Exception as e:
                        print(f"Warning: Error processing {filepath}: {e}")
                        
    if not all_experiments_for_success:
        print("\nNo data available for success rate analysis.")
        return

    success_df = pd.DataFrame(all_experiments_for_success)

    print("\n\n" + "="*50)
    print("--- Experiment Success Rate Analysis (All Batches) ---")
    print("="*50)

    # 1. By Fault Type
    success_by_fault = success_df.groupby('fault_type').agg(
        Total_Experiments=('experiment_success', 'count'),
        Successful_Experiments=('experiment_success', lambda x: x.sum()),
        Average_Rounds=('num_rounds', 'mean')
    ).astype(int)
    success_by_fault['Success_Rate_%'] = (
        (success_by_fault['Successful_Experiments'] / success_by_fault['Total_Experiments']) * 100
    ).round(1)
    success_by_fault['Average_Rounds'] = success_df.groupby('fault_type')['num_rounds'].mean().round(1)
    print("\n--- Success Rate by Fault Type ---")
    print(success_by_fault)

    # 2. By Namespace
    success_by_namespace = success_df.groupby('namespace').agg(
        Total_Experiments=('experiment_success', 'count'),
        Successful_Experiments=('experiment_success', lambda x: x.sum()),
        Average_Rounds=('num_rounds', 'mean')
    ).astype(int)
    success_by_namespace['Success_Rate_%'] = (
        (success_by_namespace['Successful_Experiments'] / success_by_namespace['Total_Experiments']) * 100
    ).round(1)
    success_by_namespace['Average_Rounds'] = success_df.groupby('namespace')['num_rounds'].mean().round(1)
    print("\n--- Success Rate by Namespace ---")
    print(success_by_namespace)

    # 3. Overall
    total_successful_experiments = success_df['experiment_success'].sum()
    total_experiments = len(success_df)
    overall_success_rate = (total_successful_experiments / total_experiments * 100) if total_experiments > 0 else 0
    overall_average_rounds = success_df['num_rounds'].mean()
    print("\n" + "="*50)
    print(f"Overall Experiment Success Rate: {total_successful_experiments}/{total_experiments} ({overall_success_rate:.1f}%)")
    print(f"Overall Average Rounds:          {overall_average_rounds:.1f}")
    print("="*50)

    # --- Combined Summary Tables ---
    print("\n\n" + "="*50)
    print("--- Combined Metrics by Fault Type ---")
    print("="*50)

    # Combined by Fault Type
    if not success_df.empty:
        success_by_fault = success_df.groupby('fault_type').agg(
            Success_Rate_Percent=('experiment_success', lambda x: (x.mean() * 100).round(1)),
            Average_Rounds=('num_rounds', lambda x: x.mean().round(1))
        )
    else:
        success_by_fault = pd.DataFrame()

    if not identification_df.empty:
        accuracy_by_fault = identification_df.groupby('fault_type').agg(
            Accuracy_Percent=('correct_identification', lambda x: (x.mean() * 100).round(1))
        )
        combined_by_fault = success_by_fault.join(accuracy_by_fault, how='outer').fillna('N/A')
    else:
        combined_by_fault = success_by_fault
        combined_by_fault['Accuracy_Percent'] = 'N/A'

    # Reorder columns
    combined_by_fault = combined_by_fault[['Accuracy_Percent', 'Success_Rate_Percent', 'Average_Rounds']]
    print(combined_by_fault)

    print("\n" + "="*50)
    print("--- Combined Metrics by Namespace ---")
    print("="*50)

    # Combined by Namespace
    if not success_df.empty:
        success_by_namespace = success_df.groupby('namespace').agg(
            Success_Rate_Percent=('experiment_success', lambda x: (x.mean() * 100).round(1)),
            Average_Rounds=('num_rounds', lambda x: x.mean().round(1))
        )
    else:
        success_by_namespace = pd.DataFrame()

    if not identification_df.empty:
        accuracy_by_namespace = identification_df.groupby('namespace').agg(
            Accuracy_Percent=('correct_identification', lambda x: (x.mean() * 100).round(1))
        )
        combined_by_namespace = success_by_namespace.join(accuracy_by_namespace, how='outer').fillna('N/A')
    else:
        combined_by_namespace = success_by_namespace
        combined_by_namespace['Accuracy_Percent'] = 'N/A'

    # Reorder columns
    combined_by_namespace = combined_by_namespace[['Accuracy_Percent', 'Success_Rate_Percent', 'Average_Rounds']]
    print(combined_by_namespace)

    # Overall Combined Summary
    print("\n" + "="*50)
    overall_identification_experiments = len(identification_df) if not identification_df.empty else 0
    overall_identification_correct = identification_df['correct_identification'].sum() if not identification_df.empty else 0
    overall_accuracy_percent = (overall_identification_correct / overall_identification_experiments * 100) if overall_identification_experiments > 0 else 'N/A'
    overall_success_rate_percent = overall_success_rate
    overall_avg_rounds = overall_average_rounds.round(1)
    print("--- Overall Combined Metrics ---")
    print(f"Accuracy Percentage:    {overall_accuracy_percent:.1f}%" if isinstance(overall_accuracy_percent, float) else f"Accuracy Percentage:    {overall_accuracy_percent}")
    print(f"Success Rate Percentage:{overall_success_rate_percent:.1f}%")
    print(f"Average Rounds:         {overall_avg_rounds}")
    print("="*50)


if __name__ == '__main__':
    main() 