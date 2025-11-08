def build_intent() -> str:
    # return (
    #     "Performance degradation detected in the system. "
    #     "Investigate the issue and take corrective action to restore service quality."
    # )
    return (
        "Cloud-worker-1 has cpu stress after you drain and cordon the node latency will fall near baseline but not all the way."
        "This prompt is a test to see if you can handle the node level cpu stress and latency will fall near baseline but not all the way."
        "You should investigate how you can drop the last 100ms of latency aprox."
        "In a previous test run you scaled deployments both for cloud-analytics engine and iog-gateway for both sites."
        "Try to see if relaxing the limits or the requests will help or any other action you can think of."
        "Again this is a test and would serve to see if our benchmark is working as expected."
        "Or cpu stress is too high to be mitigated in general."
        "Try 2-3 ideas before you produce the operational summary."
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

