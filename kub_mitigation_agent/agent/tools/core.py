import asyncio
import logging
from typing import Any, Dict, List, Optional
from langchain.tools import tool

logger = logging.getLogger(__name__)

@tool(description="Create an actionable, concrete plan of tool calls before taking action.")
def generate_action_plan(objective: str, situation: str, steps: List[str], expected_outcomes: List[str]) -> Dict[str, Any]:
    """Create an action plan.

    Args:
        objective: Clear objective for this incident or mitigation effort
        situation: Current evidence or context motivating this plan
        steps: Ordered list of concrete tool calls or operational steps
        expected_outcomes: Signals or metrics that will confirm success
    """
    return {
        "objective": objective,
        "situation": situation,
        "steps": steps,
        "expected_outcomes": expected_outcomes,
    }


@tool(description="Emit the final operational summary and stop the operation. CRITICAL: You MUST explicitly populate the problem_location parameter with identified problem resources (pods, nodes, deployments, etc.) as a list of dicts with 'name' and 'type' keys. DO NOT describe problem locations only in text fields - they MUST be in the problem_location parameter.")
def generate_operational_summary(
    objective: str,
    actions_completed: List[str],
    results_achieved: List[str],
    status: str,
    problem_location: Optional[List[Dict[str, str]]] = None,
    success: bool = False,
) -> Dict[str, Any]:
    """Generate final operational summary for the run.
    
    CRITICAL REQUIREMENT: The problem_location parameter is MANDATORY when any problem is identified.
    You MUST explicitly return problem locations in this parameter, NOT just describe them in status/actions_completed text.
    
    Args:
        objective: Clear objective for this operation
        actions_completed: List of actions taken during the operation
        results_achieved: List of results or outcomes achieved
        status: Final status message
        problem_location: **REQUIRED** - List of dictionaries identifying problem resources. Each dict must have:
            - "name": The exact resource name (e.g., "pod-name", "node-name", "deployment-name")
            - "type": The resource type (e.g., "pod", "node", "deployment", "hpa")
            Example: [{"name": "edge-service-xyz", "type": "pod"}, {"name": "worker-node-1", "type": "node"}]
            MUST be populated if any problem was identified. Only leave empty ([]) if definitively no problem exists.
        success: Whether the operation was successful
    """
    return {
        "objective": objective,
        "actions_completed": actions_completed,
        "results_achieved": results_achieved,
        "status": status,
        "problem_location": problem_location or [],
        "success": success,
    }


@tool(description="Sleep for a number of seconds.")
async def sleep_seconds(duration: float) -> Dict[str, Any]:
    """Sleep for a given duration in seconds."""
    await asyncio.sleep(duration)
    return {"duration": duration, "status": "completed"}

