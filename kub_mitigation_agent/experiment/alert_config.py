def build_intent() -> str:
    return (
        "Performance degradation detected in the system. "
        "Investigate the issue and take corrective action to restore service quality."
    )


def build_snapshot(namespace: str, baseline_latency_p95: float, baseline_success_rate: float,
                   current_latency_p95: float, current_success_rate: float, timestamp: str) -> dict:
    return {
        "namespace": namespace,
        "alert_type": "performance_degradation",
        "timestamp": timestamp,
        "baseline_latency_p95": baseline_latency_p95,
        "baseline_success_rate": baseline_success_rate,
        "current_latency_p95": current_latency_p95,
        "current_success_rate": current_success_rate
    }

