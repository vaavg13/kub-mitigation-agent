import json
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import textwrap
import re

def simplify_text(text, max_len=80):
    # Remove common prefixes/suffixes for brevity
    text = re.sub(r'Phase \d+ [–-] ', '', text)
    text = re.sub(r'Thought: ', '', text)
    text = re.sub(r'Action: ', '', text)
    
    # Specific simplifications for this log pattern
    text = text.replace("Investigate and remediate performance degradation in namespace app-smart-manufacturing to restore latency and success rate to baseline.", "Investigate & remediate perf degradation in app-smart-manufacturing.")
    text = text.replace("Resolve performance degradation in namespace app-smart-manufacturing by mitigating CPU saturation and restoring latency toward baseline.", "Resolve perf degradation (CPU saturation) & restore latency.")
    
    # NO HARD TRUNCATION to avoid cutting off mid-sentence
    # We rely on wrapping for layout
    
    return text

def wrap_text(text, width=60):
    return textwrap.fill(text, width=width)

def render_pdf(data, output_file='action_summary_view.pdf'):
    # Extract Data
    action_plan_step = next((s for s in data['agent_trace'] if s['action'] == 'generate_action_plan'), None)
    op_summary_step = next((s for s in reversed(data['agent_trace']) if s['action'] == 'generate_operational_summary'), None)
    
    if not action_plan_step or not op_summary_step:
        print("Could not find both Action Plan and Operational Summary.")
        return

    ap_args = action_plan_step['action_args']
    os_args = op_summary_step['action_args']

    # Prepare Content
    
    # LEFT COLUMN: Action Plan
    ap_content = []
    ap_content.append(r"$\bf{Objective}$" + ": " + simplify_text(ap_args.get('objective', '')))
    ap_content.append(r"$\bf{Situation}$" + ": " + simplify_text(ap_args.get('situation', '')))
    
    ap_content.append(r"$\bf{Planned\ Steps}$:")
    for step in ap_args.get('steps', []):
        clean_step = simplify_text(step)
        # Handle sub-bullets (Decision Branch items often start with "- ")
        if clean_step.strip().startswith("- "):
             # It's a sub-bullet, indent it
             ap_content.append("    " + clean_step)
        else:
             # Regular step, add bullet
             ap_content.append("- " + clean_step)

    # Add Expected Outcomes to Left Column (Missing in previous version)
    ap_content.append(r"$\bf{Expected\ Outcomes}$:")
    for outcome in ap_args.get('expected_outcomes', []):
        clean_outcome = simplify_text(outcome)
        ap_content.append("- " + clean_outcome)
        
    # RIGHT COLUMN: Operational Summary
    os_content = []
    os_content.append(r"$\bf{Status}$" + ": " + os_args.get('status', ''))
    
    os_content.append(r"$\bf{Actions\ Executed}$:")
    for action in os_args.get('actions_completed', []):
        os_content.append("- " + simplify_text(action))
    
    os_content.append(r"$\bf{Results}$:")
    for res in os_args.get('results_achieved', []):
        os_content.append("- " + simplify_text(res))

    os_content.append(r"$\bf{Root\ Cause\ Locations}$:")
    locations = [f"{loc['name']} ({loc['type']})" for loc in os_args.get('problem_location', [])]
    # Join with newlines if too many, or comma
    os_content.append(", ".join(locations))

    # Plotting
    fig = plt.figure(figsize=(12, 12)) # Increased height slightly to accommodate more text
    
    # Remove axes
    plt.axis('off')
    
    # Title
    # plt.suptitle("Experiment Operational Trace: Action Plan vs Execution Summary", fontsize=16, y=0.98)
    
    # Define Layout columns
    left_x = 0.02
    right_x = 0.52
    top_y = 0.92 # Lowered to avoid title overlap
    line_height = 0.018 # Slightly smaller line height to fit more
    col_width = 70 # characters for wrapping

    # Draw Left Column
    y = top_y
    plt.text(left_x, y, "Initial Action Plan", fontsize=14, fontweight='bold', transform=fig.transFigure)
    y -= line_height * 2.5
    
    for line in ap_content:
        wrapped = wrap_text(line, width=col_width).split('\n')
        for subline in wrapped:
            # Check if it's a header (bold math)
            is_header = r"$\bf" in subline
            font_weight = 'bold' if is_header else 'normal'
            # Indent handling for sub-bullets
            x_offset = left_x
            if line.startswith("    "):
                x_offset += 0.02
            
            plt.text(x_offset, y, subline, fontsize=9, transform=fig.transFigure, va='top', fontfamily='sans-serif')
            y -= line_height
        y -= line_height * 0.5 # Gap between items

    # Draw Right Column
    y = top_y
    plt.text(right_x, y, "Operational Summary (Post-Execution)", fontsize=14, fontweight='bold', transform=fig.transFigure)
    y -= line_height * 2.5

    for line in os_content:
        wrapped = wrap_text(line, width=col_width).split('\n')
        for subline in wrapped:
            is_header = r"$\bf" in subline
            plt.text(right_x, y, subline, fontsize=9, transform=fig.transFigure, va='top', fontfamily='sans-serif')
            y -= line_height
        y -= line_height * 0.5

    # Draw separator line
    line = plt.Line2D([0.5, 0.5], [0.02, 0.95], transform=fig.transFigure, color="black", linewidth=0.5)
    fig.add_artist(line)

    plt.savefig(output_file, format='pdf', bbox_inches='tight')
    print(f"PDF generated: {output_file}")

if __name__ == "__main__":
    filepath = 'DATASET_LOGS/gpt-5/batch_20251113_090217_app-smart-manufacturing/exp_003-chaos-cpu-stress-predictive-maintenance-analytics-cloud.json'
    with open(filepath, 'r') as f:
        data = json.load(f)
    render_pdf(data)
