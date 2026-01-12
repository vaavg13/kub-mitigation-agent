import json
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
import glob
import os

# Suppress warnings
warnings.filterwarnings('ignore')

# Setup directories
INPUT_DIR = 'DATASET_LOGS/gpt-5'
OUTPUT_DIR = 'PLOTS/all_experiments'
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# Style settings
sns.set_style("whitegrid")
sns.set_context("paper", font_scale=1.5)
plt.rcParams['figure.figsize'] = (14, 10)
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['DejaVu Serif', 'Liberation Serif', 'Times New Roman', 'Times']

def get_affected_component(chaos_config):
    chaos_type = chaos_config.get('type', 'unknown')
    
    if chaos_type == 'baseline' or chaos_type == 'unknown':
        return 'Baseline'
    
    target = chaos_config.get('target', {})
    
    if 'name' in target:
        return target['name']
    elif 'app' in target:
        return target['app']
    
    # Fallback to parsing from chaos name or just return 'Unknown'
    name = chaos_config.get('name', '')
    if name:
        return name
    
    return 'Unknown Component'

def format_title(namespace, chaos_type, component):
    # Clean up strings
    chaos_type_formatted = chaos_type.replace('_', ' ').title()
    return f"{namespace} - {chaos_type_formatted} - {component}"

def process_experiment(file_path):
    print(f"Processing {file_path}...")
    
    try:
        with open(file_path, 'r') as f:
            exp_data = json.load(f)
            
        # Basic Info
        namespace = exp_data.get('namespace', 'unknown-app')
        chaos_config = exp_data.get('chaos_config', {})
        chaos_type = chaos_config.get('type', 'baseline')
        affected_component = get_affected_component(chaos_config)
        
        title = format_title(namespace, chaos_type, affected_component)
        
        # Timeseries Data
        if 'prometheus_timeseries' not in exp_data:
            print(f"Skipping {file_path}: No prometheus_timeseries found.")
            return

        ts_data = exp_data['prometheus_timeseries']
        if 'ingress_gateway' not in ts_data:
            print(f"Skipping {file_path}: No ingress_gateway data found.")
            return
            
        latency_data = ts_data['ingress_gateway']['latency_p95_seconds']
        success_data = ts_data['ingress_gateway']['success_rate_percent']
        
        # Convert to DataFrames
        df_latency = pd.DataFrame(latency_data)
        if df_latency.empty:
            print(f"Skipping {file_path}: Empty latency data.")
            return
            
        df_latency['time'] = pd.to_datetime(df_latency['timestamp'], unit='s')
        df_latency['seconds_elapsed'] = (df_latency['timestamp'] - df_latency['timestamp'].min())

        df_success = pd.DataFrame(success_data)
        if df_success.empty:
            print(f"Skipping {file_path}: Empty success data.")
            return
            
        df_success['time'] = pd.to_datetime(df_success['timestamp'], unit='s')
        df_success['seconds_elapsed'] = (df_success['timestamp'] - df_success['timestamp'].min())

        # Metrics
        baseline_metrics = exp_data.get('baseline_metrics', {'p95_latency_seconds': 0, 'success_rate_percent': 100})
        
        # Durations
        duration = exp_data.get('duration_seconds', 600)
        agent_duration = exp_data.get('agent_duration_seconds', 0)
        
        # Phase Boundaries (Standardized)
        warmup_duration = 60
        baseline_duration = 60
        chaos_warmup_duration = 60
        
        phase_warmup_end = warmup_duration
        phase_baseline_end = phase_warmup_end + baseline_duration
        phase_chaos_end = phase_baseline_end + chaos_warmup_duration
        phase_agent_end = phase_chaos_end + agent_duration
        phase_recovery_end = duration

        # Create Figure
        fig, axes = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

        # Plot 1: Latency
        ax1 = axes[0]
        ax1.plot(df_latency['seconds_elapsed'], df_latency['value'], 
                 linewidth=2.5, color='#2E86AB', marker='o', markersize=5, label='P95 Latency', zorder=5)

        # Baseline Reference
        ax1.axhline(y=baseline_metrics['p95_latency_seconds'], 
                    color='#A23B72', linestyle='--', linewidth=2, alpha=0.7, label='Baseline Reference')

        # Phase Backgrounds
        ax1.axvspan(0, phase_warmup_end, alpha=0.08, color='gray', label='Warmup')
        ax1.axvspan(phase_warmup_end, phase_baseline_end, alpha=0.12, color='green', label='Baseline')
        ax1.axvspan(phase_baseline_end, phase_chaos_end, alpha=0.12, color='red', label='Chaos')
        ax1.axvspan(phase_chaos_end, phase_agent_end, alpha=0.12, color='orange', label=f'Agent ({agent_duration:.0f}s)')
        ax1.axvspan(phase_agent_end, phase_recovery_end, alpha=0.12, color='blue', label='Recovery')

        # Vertical Lines
        for phase_time in [phase_warmup_end, phase_baseline_end, phase_chaos_end, phase_agent_end]:
            ax1.axvline(x=phase_time, color='black', linestyle=':', linewidth=1, alpha=0.5)

        ax1.set_ylabel('P95 Latency (seconds)', fontsize=14, fontweight='bold')
        ax1.set_title(title, fontsize=16, fontweight='bold', pad=20)
        ax1.legend(loc='upper right', frameon=True, shadow=True, ncol=2, fontsize=10)
        ax1.grid(True, alpha=0.3)

        # Plot 2: Success Rate
        ax2 = axes[1]
        ax2.plot(df_success['seconds_elapsed'], df_success['value'], 
                 linewidth=2.5, color='#F18F01', marker='s', markersize=5, label='Success Rate', zorder=5)

        # Baseline Reference
        ax2.axhline(y=baseline_metrics['success_rate_percent'], 
                    color='#A23B72', linestyle='--', linewidth=2, alpha=0.7, label='Baseline Reference')

        # Phase Backgrounds
        ax2.axvspan(0, phase_warmup_end, alpha=0.08, color='gray')
        ax2.axvspan(phase_warmup_end, phase_baseline_end, alpha=0.12, color='green')
        ax2.axvspan(phase_baseline_end, phase_chaos_end, alpha=0.12, color='red')
        ax2.axvspan(phase_chaos_end, phase_agent_end, alpha=0.12, color='orange')
        ax2.axvspan(phase_agent_end, phase_recovery_end, alpha=0.12, color='blue')

        # Vertical Lines
        for phase_time in [phase_warmup_end, phase_baseline_end, phase_chaos_end, phase_agent_end]:
            ax2.axvline(x=phase_time, color='black', linestyle=':', linewidth=1, alpha=0.5)

        ax2.set_xlabel('Time Elapsed (seconds)', fontsize=14, fontweight='bold')
        ax2.set_ylabel('Success Rate (%)', fontsize=14, fontweight='bold')
        # Adjust ylim slightly to show 100 clearly, but handle 0 cases too
        if df_success['value'].min() < 99:
            ax2.set_ylim([min(0, df_success['value'].min() - 5), 105])
        else:
            ax2.set_ylim([99, 100.5])
            
        ax2.legend(loc='lower right', frameon=True, shadow=True)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        
        # Save
        filename = Path(file_path).stem
        output_path = Path(OUTPUT_DIR) / f"{filename}.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"Saved {output_path}")
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def main():
    # Find all json files recursively
    files = glob.glob(f"{INPUT_DIR}/**/*.json", recursive=True)
    print(f"Found {len(files)} experiment files.")
    
    for f in files:
        process_experiment(f)

if __name__ == "__main__":
    main()


