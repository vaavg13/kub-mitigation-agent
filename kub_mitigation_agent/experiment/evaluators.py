"""
Recovery Evaluator
Evaluates both metrics recovery and problem location identification accuracy.
"""

from typing import Dict, Any, List, Optional


def evaluate_metrics_recovery(phase_metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate if the agent successfully recovered the system to near baseline levels.
    
    Args:
        phase_metrics: Dict with keys "baseline", optional "chaos", and "recovery" containing metrics
        
    Returns:
        Dict with:
        - success: bool
        - metrics_comparison: dict of numeric comparisons (includes baseline/chaos/recovery values and ratios)
        - recovery_index_latency: float (0-1 scale, 1=full recovery)
        - recovery_index_success: float (0-1 scale, 1=full recovery)
        - composite_recovery_score: float (0-1 scale, 1=full recovery)
        - within_20pct_baseline: bool (True if within 20% of baseline)
    """
    if "baseline" not in phase_metrics or "recovery" not in phase_metrics:
        return {
            "success": False,
            "metrics_comparison": {},
            "recovery_index_latency": None,
            "recovery_index_success": None,
            "composite_recovery_score": None,
            "within_20pct_baseline": False
        }
    
    baseline = phase_metrics["baseline"]
    recovery = phase_metrics["recovery"]
    chaos = phase_metrics.get("chaos")
    
    # Define success thresholds (configurable)
    latency_threshold = 1.3  # Recovery latency should be within 30% of baseline
    success_rate_threshold = 5.0  # Recovery success rate should be within 5% of baseline
    
    metrics_comparison = {
        "baseline_latency_p95": baseline["p95_latency_seconds"],
        "recovery_latency_p95": recovery["p95_latency_seconds"],
        "baseline_success_rate": baseline["success_rate_percent"],
        "recovery_success_rate": recovery["success_rate_percent"],
    }
    
    # Calculate recovery indices if chaos metrics available
    recovery_index_latency = None
    recovery_index_success = None
    composite_recovery_score = None
    
    if chaos and "p95_latency_seconds" in chaos and "success_rate_percent" in chaos:
        metrics_comparison.update({
            "chaos_latency_p95": chaos["p95_latency_seconds"],
            "chaos_success_rate": chaos["success_rate_percent"],
        })
        
        # Recovery Index: R = (chaos - recovery) / (chaos - baseline)
        # R=1 → fully restored, R=0 → no improvement, R<0 → worsened
        
        # Latency recovery index
        chaos_lat = chaos["p95_latency_seconds"]
        recovery_lat = recovery["p95_latency_seconds"]
        baseline_lat = baseline["p95_latency_seconds"]
        
        if chaos_lat != baseline_lat and baseline_lat > 0:
            recovery_index_latency = (chaos_lat - recovery_lat) / (chaos_lat - baseline_lat)
            # If recovery exceeds baseline (better than baseline), cap at 1.0 or allow > 1.0
            # Recovery better than baseline means full recovery achieved
            if recovery_lat < baseline_lat:
                recovery_index_latency = max(1.0, recovery_index_latency)
        elif recovery_lat <= baseline_lat * 1.1:  # Within 10% of baseline
            recovery_index_latency = 1.0
        else:
            recovery_index_latency = 0.0
        
        # Success rate recovery index (normalized to 0-100 scale)
        chaos_sr = chaos["success_rate_percent"]
        recovery_sr = recovery["success_rate_percent"]
        baseline_sr = baseline["success_rate_percent"]
        
        if chaos_sr != baseline_sr:
            # For success rate, lower is worse, so we need to handle direction
            recovery_index_success = (recovery_sr - chaos_sr) / (baseline_sr - chaos_sr)
            # If recovery exceeds baseline (better than baseline), cap at 1.0 or allow > 1.0
            if recovery_sr > baseline_sr:
                recovery_index_success = max(1.0, recovery_index_success)
        elif abs(recovery_sr - baseline_sr) <= 1.0:  # Within 1% of baseline
            recovery_index_success = 1.0
        else:
            recovery_index_success = 0.0
        
        # Composite recovery score (weighted average: 70% latency, 30% success rate)
        composite_recovery_score = 0.7 * recovery_index_latency + 0.3 * recovery_index_success
    
    # Normal mode: compare recovery with baseline
    latency_ratio = recovery["p95_latency_seconds"] / baseline["p95_latency_seconds"] if baseline["p95_latency_seconds"] > 0 else float('inf')
    success_rate_diff = abs(recovery["success_rate_percent"] - baseline["success_rate_percent"])
    
    # Check if within 20% of baseline
    within_20pct_latency = latency_ratio <= 1.20
    within_20pct_success = success_rate_diff <= 1.0  # Within 1% for success rate (already percentage)
    within_20pct_baseline = within_20pct_latency and within_20pct_success
    
    latency_acceptable = latency_ratio <= latency_threshold
    success_rate_acceptable = success_rate_diff <= success_rate_threshold
    
    success = latency_acceptable and success_rate_acceptable
    
    metrics_comparison.update({
        "latency_ratio": latency_ratio,
        "success_rate_diff": success_rate_diff,
        "latency_acceptable": latency_acceptable,
        "success_rate_acceptable": success_rate_acceptable
    })
    
    return {
        "success": success,
        "metrics_comparison": metrics_comparison,
        "recovery_index_latency": recovery_index_latency,
        "recovery_index_success": recovery_index_success,
        "composite_recovery_score": composite_recovery_score,
        "within_20pct_baseline": within_20pct_baseline
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
        chaos_config: Anomaly info from anomaly.get_info() with mode, provider, type, target
        problem_location: List of dicts with 'name' and 'type' from agent's operational summary
        
    Returns:
        Dict with:
        - location_identified: bool (True if agent correctly identified location)
        - expected_target: str (the expected target from chaos_config)
        - reported_locations: list of strings (names from problem_location)
    """
    mode = chaos_config.get("mode", "unknown")
    
    # Handle no_failure mode - no problem to identify
    if mode == "no_failure":
        reported_names = [loc.get("name", "") for loc in (problem_location or [])]
        correctly_identified = len(reported_names) == 0 or not any(reported_names)
        
        return {
            "location_identified": correctly_identified,
            "expected_target": None,
            "reported_locations": reported_names
        }
    
    # Extract expected target from the unified anomaly format
    # Pod-level anomalies: target = {namespace, mode, app}
    # Node-level anomalies: target = {name, host, port}
    expected_target = None
    target = chaos_config.get("target", {})
    
    if "app" in target:
        # Pod-level chaos (Chaos Mesh)
        expected_target = target.get("app")
    elif "name" in target:
        # Node-level chaos (Chaosd)
        expected_target = target.get("name")
    
    # Handle case where we couldn't extract expected target
    if not expected_target:
        return {
            "location_identified": False,
            "expected_target": "unknown",
            "reported_locations": [loc.get("name", "") for loc in (problem_location or [])]
        }
    
    # Extract reported locations from agent
    reported_names = [loc.get("name", "") for loc in (problem_location or [])]
    
    # Handle case where agent didn't report any locations
    if not reported_names or not any(reported_names):
        return {
            "location_identified": False,
            "expected_target": expected_target,
            "reported_locations": []
        }
    
    # Perform fuzzy matching
    match_found = False
    
    for reported_name in reported_names:
        if _fuzzy_match(expected_target, reported_name):
            match_found = True
            break
    
    return {
        "location_identified": match_found,
        "expected_target": expected_target,
        "reported_locations": reported_names
    }

