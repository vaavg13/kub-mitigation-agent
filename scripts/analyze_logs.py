import os
import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter

def get_tool_name(step):
    action = step.get('action')
    if not action:
        return None
    
    args = step.get('action_args', {})
    
    # Special handling for prometheus tools
    if action in ['prometheus_get_timeseries', 'prometheus_get_node_timeseries']:
        metric_type = args.get('metric_type')
        if metric_type:
            return f"{action} ({metric_type})"
    
    return action

def process_directory(directory):
    tool_counts = Counter()
    total_actions = 0
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.json'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                        trace = data.get('agent_trace', [])
                        for step in trace:
                            tool_name = get_tool_name(step)
                            if tool_name:
                                tool_counts[tool_name] += 1
                                total_actions += 1
                except Exception as e:
                    print(f"Error processing {filepath}: {e}")
                    
    return tool_counts, total_actions

def generate_tikz(df, order, filename='tool_usage.tex'):
    # Clean tool names for LaTeX (escape underscores)
    clean_order = [t.replace('_', r'\_') for t in order]
    symbolic_coords = ",".join(clean_order)
    
    models = df['Model'].unique()
    
    # Construct the TikZ content using f-strings carefully
    # Note: We use {{ and }} to escape curly braces for f-strings
    
    header = r"""\documentclass{standalone}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}

\begin{document}

\begin{tikzpicture}
    \begin{axis}[
        xbar,
        width=12cm,
        height=8cm,
        xlabel={Usage Percentage (\%%)},
        symbolic y coords={%s},
        ytick=data,
        nodes near coords,
        nodes near coords align={horizontal},
        yticklabel style={text width=6cm, align=right, font=\small},
        legend style={at={(0.5,-0.2)},
            anchor=north,legend columns=-1},
        xmin=0,
        xmax=25, 
        enlarge y limits=0.15,
        reverse legend,
        y dir=reverse, 
        bar width=10pt,
    ]
""" % (symbolic_coords)

    body = ""
    for model in models:
        model_df = df[df['Model'] == model]
        coords = []
        for tool in order:
            row = model_df[model_df['Tool'] == tool]
            if not row.empty:
                val = row.iloc[0]['Percentage']
                clean_tool = tool.replace('_', r'\_')
                coords.append(f"({val:.2f},{clean_tool})")
            else:
                clean_tool = tool.replace('_', r'\_')
                coords.append(f"(0,{clean_tool})")
        
        body += f"    \\addplot coordinates {{ {' '.join(coords)} }};\n"
        body += f"    \\addlegendentry{{{model}}}\n"

    footer = r"""
    \end{axis}
\end{tikzpicture}

\end{document}
"""
    
    with open(filename, 'w') as f:
        f.write(header + body + footer)
    print(f"\nTikZ figure saved to '{filename}'")

def main():
    base_dir = 'DATASET_LOGS'
    models = ['gpt-5', 'gpt-5-mini']
    
    print("Analyzing logs...")
    
    model_counts = {}
    model_totals = {}
    global_counts = Counter()

    # 1. Collect Data
    for model in models:
        model_dir = os.path.join(base_dir, model)
        if not os.path.exists(model_dir):
            print(f"Warning: Directory {model_dir} not found.")
            continue
            
        counts, total = process_directory(model_dir)
        model_counts[model] = counts
        model_totals[model] = total
        global_counts.update(counts)

    # Remove "generate_operational_summary" from consideration
    if 'generate_operational_summary' in global_counts:
        del global_counts['generate_operational_summary']

    # 2. Identify Top 8 Tools Globally
    top_8_tools = [tool for tool, count in global_counts.most_common(8)]
    
    # 3. Prepare Data for Visualization
    plot_data = []
    
    for model in models:
        if model not in model_counts:
            continue
            
        total = model_totals[model]
        counts = model_counts[model]
        
        # Add data for Top 8
        for tool in top_8_tools:
            count = counts.get(tool, 0)
            pct = (count / total) * 100 if total > 0 else 0
            plot_data.append({
                'Tool': tool,
                'Percentage': pct,
                'Model': model
            })
        
    df = pd.DataFrame(plot_data)
    
    # Define order: Top 8 tools
    order = top_8_tools

    # 4. Generate TikZ (Publication Quality Vector Graphic)
    generate_tikz(df, order, filename='tool_usage.tex')

    # 5. Generate Matplotlib Plot (Clean, Publication Style)
    sns.set_theme(style="whitegrid", font_scale=1.2)
    plt.figure(figsize=(12, 7))
    
    # Use a high-contrast palette suitable for papers
    # 'Paired' or 'Set2' are good. 'viridis' is also fine but let's try distinct.
    palette = sns.color_palette("Paired") 
    
    ax = sns.barplot(
        data=df, 
        y='Tool', 
        x='Percentage', 
        hue='Model', 
        order=order, 
        palette='viridis', # Staying with viridis as it's often safe, but styling is cleaner now
        edgecolor='black', # Add border to bars for definition
        linewidth=0.5
    )
    
    # Clean up labels
    ax.set_ylabel('')
    ax.set_xlabel('Usage Percentage (%)')
    ax.set_title('') # No title for paper figures typically
    
    # Move legend to a good spot or outside
    plt.legend(title='Model', loc='lower right', frameon=True)
    
    # Remove top and right spines
    sns.despine()
    
    # Save as PDF (vector) and PNG (high dpi)
    plt.tight_layout()
    plt.savefig('tool_usage_comparison.pdf', format='pdf', bbox_inches='tight')
    plt.savefig('tool_usage_comparison.png', dpi=300, bbox_inches='tight')
    print("\nMatplotlib visualization saved to 'tool_usage_comparison.pdf' and 'tool_usage_comparison.png'")

    # Print Data for verification
    for model in models:
        print(f"\nStats for {model}:")
        model_df = df[df['Model'] == model]
        for _, row in model_df.iterrows():
            print(f"  {row['Tool']}: {row['Percentage']:.2f}%")

if __name__ == "__main__":
    main()
