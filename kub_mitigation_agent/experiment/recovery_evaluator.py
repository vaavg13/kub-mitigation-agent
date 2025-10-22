#!/usr/bin/env python3
"""
Recovery Evaluator
Evaluates both metrics recovery and problem location identification accuracy.
"""

from typing import Dict, Any, List, Optional


def evaluate_metrics_recovery(phase_metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate if the agent successfully recovered the system to near baseline levels.
    
    Args:
        phase_metrics: Dict with keys "baseline", "chaos", "recovery" containing metrics
        
    Returns:
        Dict with success, reason, and metrics_comparison
    """
    if "baseline" not in phase_metrics or "recovery" not in phase_metrics:
        return {
            "success": False,
            "reason": "Missing baseline or recovery metrics for comparison",
            "metrics_comparison": {}
        }
    
    baseline = phase_metrics["baseline"]
    recovery = phase_metrics["recovery"]
    
    # Define success thresholds (configurable)
    latency_threshold = 1.3  # Recovery latency should be within 30% of baseline
    success_rate_threshold = 5.0  # Recovery success rate should be within 5% of baseline
    
    metrics_comparison = {
        "baseline_latency_p95": baseline["p95_latency_seconds"],
        "recovery_latency_p95": recovery["p95_latency_seconds"],
        "baseline_success_rate": baseline["success_rate_percent"],
        "recovery_success_rate": recovery["success_rate_percent"],
    }
    
    # Normal mode: compare recovery with baseline
    latency_ratio = recovery["p95_latency_seconds"] / baseline["p95_latency_seconds"] if baseline["p95_latency_seconds"] > 0 else float('inf')
    success_rate_diff = abs(recovery["success_rate_percent"] - baseline["success_rate_percent"])
    
    latency_acceptable = latency_ratio <= latency_threshold
    success_rate_acceptable = success_rate_diff <= success_rate_threshold
    
    success = latency_acceptable and success_rate_acceptable
    
    if success:
        reason = f"Recovery within acceptable thresholds: latency {latency_ratio:.2f}x baseline, success rate ±{success_rate_diff:.1f}%"
    else:
        issues = []
        if not latency_acceptable:
            issues.append(f"latency {latency_ratio:.2f}x baseline (threshold: {latency_threshold}x)")
        if not success_rate_acceptable:
            issues.append(f"success rate ±{success_rate_diff:.1f}% (threshold: ±{success_rate_threshold}%)")
        reason = f"Recovery exceeded thresholds: {', '.join(issues)}"
    
    metrics_comparison.update({
        "latency_ratio": latency_ratio,
        "success_rate_diff": success_rate_diff,
        "latency_acceptable": latency_acceptable,
        "success_rate_acceptable": success_rate_acceptable
    })
    
    return {
        "success": success,
        "reason": reason,
        "metrics_comparison": metrics_comparison
    }


def _fuzzy_match(expected: str, reported: str) -> bool:
    """Case-insensitive partial match.
    
    Args:
        expected: Expected target name from chaos config
        reported: Reported location name from agent
        
    Returns:
        True if there's a fuzzy match
    """
    expected_lower = expected.lower()
    reported_lower = reported.lower()
    return expected_lower in reported_lower or reported_lower in expected_lower


def evaluate_problem_location_match(
    chaos_config: Dict[str, Any],
    problem_location: Optional[List[Dict[str, str]]]
) -> Dict[str, Any]:
    """Evaluate if agent correctly identified the problem location.
    
    Args:
        chaos_config: Chaos configuration with mode, fault_type, target info
        problem_location: List of dicts with 'name' and 'type' from agent's operational summary
        
    Returns:
        Dict with:
        - location_identified: bool (True if agent correctly identified location)
        - expected_target: str (the expected target from chaos_config)
        - reported_locations: list of strings (names from problem_location)
        - match_details: str (explanation of match/mismatch)
    """
    mode = chaos_config.get("mode", "unknown")
    
    # Handle no_failure mode - no problem to identify
    if mode == "no_failure":
        return {
            "location_identified": None,  # N/A for no_failure
            "expected_target": "none (baseline)",
            "reported_locations": [loc.get("name", "") for loc in (problem_location or [])],
            "match_details": "No failure injected - location identification not applicable"
        }
    
    # Extract expected target based on mode
    expected_target = None
    
    if mode == "chaos_only":
        target_mode = chaos_config.get("target_mode", "")
        if target_mode in ["one_pod", "all_pods_app"]:
            expected_target = chaos_config.get("target_app")
        elif target_mode == "all_pods_node":
            expected_target = chaos_config.get("node_name")
    elif mode == "docker_only":
        expected_target = chaos_config.get("node_name")
    
    # Handle case where we couldn't extract expected target
    if not expected_target:
        return {
            "location_identified": False,
            "expected_target": "unknown",
            "reported_locations": [loc.get("name", "") for loc in (problem_location or [])],
            "match_details": f"Could not determine expected target from chaos config (mode: {mode})"
        }
    
    # Extract reported locations from agent
    reported_names = [loc.get("name", "") for loc in (problem_location or [])]
    
    # Handle case where agent didn't report any locations
    if not reported_names or not any(reported_names):
        return {
            "location_identified": False,
            "expected_target": expected_target,
            "reported_locations": [],
            "match_details": f"Agent did not identify any problem locations (expected: {expected_target})"
        }
    
    # Perform fuzzy matching
    match_found = False
    matched_name = None
    
    for reported_name in reported_names:
        if _fuzzy_match(expected_target, reported_name):
            match_found = True
            matched_name = reported_name
            break
    
    # Build result
    if match_found:
        match_details = f"Agent correctly identified location: '{matched_name}' matches expected '{expected_target}'"
    else:
        match_details = f"Agent identified: {reported_names}, but expected: '{expected_target}'"
    
    return {
        "location_identified": match_found,
        "expected_target": expected_target,
        "reported_locations": reported_names,
        "match_details": match_details
    }

