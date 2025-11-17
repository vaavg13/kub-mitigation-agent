#!/usr/bin/env python3
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _describe_action(action: Any) -> str:
    if isinstance(action, str):
        return action
    if isinstance(action, dict):
        return action.get("function", action.get("tool", "unknown"))
    return str(action)


def build_emergency_summary(actions: List[Any], status: str, results: List[str], error: Optional[str] = None) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "objective": "Agent execution incomplete",
        "actions_completed": [_describe_action(a) for a in (actions or [])],
        "results_achieved": results,
        "status": status,
        "problem_location": [],
        "success": False,
    }
    if error:
        summary["error"] = error
    return summary


def log_thought_action_observation(thought: Optional[str], action_name: str, action_args: Dict[str, Any], observation: Any) -> None:
    if thought:
        logger.info(f"THOUGHT: {thought}")
    logger.info(f"ACTION: {action_name}({json.dumps(action_args, separators=(',', ':'))})")
    try:
        logger.info(f"OBSERVATION: {json.dumps(observation)}")
    except Exception:
        logger.info(f"OBSERVATION: {observation}")


