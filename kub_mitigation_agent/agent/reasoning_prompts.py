#!/usr/bin/env python3
"""
Reasoning prompts for the Kubernetes Agent.
"""

# Template string with placeholders for reflective reasoning
REASONING_SUMMARY_PROMPT = """Based on your recent action and its result, provide a critical reflection and analysis.

Recent context:
{context_text}

Last action: {last_function}
Result: {last_result_preview}

Provide a reflective analysis covering:
1. PATTERN RECOGNITION: What specific patterns do you observe in the data? Look for anomalies, correlations, or unexpected behaviors.
2. EVIDENCE ASSESSMENT: What does this evidence tell you about the root cause? Be specific about metrics, resource usage, or failure indicators.
3. CRITICAL EVALUATION: Does this result contradict or confirm your hypothesis? Are there red flags or concerning patterns?
4. NEXT STEPS: Based on this evidence, what is the most logical next action? Should you investigate deeper or take immediate corrective action?

Focus on actionable insights and avoid repeating obvious information. If you see resource exhaustion, pod failures, or performance degradation, explicitly call it out."""

def get_reasoning_summary_prompt(context_text: str, last_function: str, last_result_preview: str) -> str:
    return REASONING_SUMMARY_PROMPT.format(
        context_text=context_text,
        last_function=last_function,
        last_result_preview=last_result_preview
    ) 