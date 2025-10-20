#!/usr/bin/env python3
import os
import sys
import argparse
import json


# Ensure repository root is on sys.path to allow importing the package
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)

from kub_mitigation_agent.shared.prometheus_client import (
    get_prometheus_tool,
    prometheus_get_timeseries,
    prometheus_get_node_timeseries,
    prometheus_get_service_topology,
)


def main():
    parser = argparse.ArgumentParser(description="Quick check for Prometheus client functionality")
    parser.add_argument("--url", default="http://localhost:9090", help="Prometheus base URL")
    parser.add_argument("--namespace", default=None, help="Kubernetes namespace filter (optional)")
    parser.add_argument("--duration", default="2m", help="Timeseries duration window (e.g. 2m, 5m)")
    args = parser.parse_args()

    tool = get_prometheus_tool(prometheus_url=args.url)

    results = {}

    # "Current" metrics approximated as last-of-timeseries over 1m minimum window
    duration = "1m"
    ns = args.namespace or ""
    pod_cpu = prometheus_get_timeseries("cpu", ns, duration)
    pod_mem = prometheus_get_timeseries("memory", ns, duration)
    svc_lat = prometheus_get_timeseries("latency", ns, duration)
    node_cpu = prometheus_get_node_timeseries("cpu", duration)
    node_mem = prometheus_get_node_timeseries("memory", duration)

    def last_values(ts_result):
        if not ts_result or ts_result.get("error"):
            return {}
        out = {}
        series_map = ts_result.get("values", {})
        for k, series in series_map.items():
            if isinstance(series, list) and series:
                out[k] = series[-1]
        return out

    results["current_node_cpu"] = {"unit": node_cpu.get("unit"), "values": last_values(node_cpu)}
    results["current_node_memory"] = {"unit": node_mem.get("unit"), "values": last_values(node_mem)}
    results["current_pod_cpu"] = {"unit": pod_cpu.get("unit"), "values": last_values(pod_cpu)}
    results["current_pod_memory"] = {"unit": pod_mem.get("unit"), "values": last_values(pod_mem)}
    results["current_istio_latency"] = {"unit": svc_lat.get("unit"), "values": last_values(svc_lat)}

    # Timeseries metrics (short duration to keep output small)
    results["ts_pod_cpu"] = prometheus_get_timeseries("cpu", args.namespace or "", args.duration)
    results["ts_pod_memory"] = prometheus_get_timeseries("memory", args.namespace or "", args.duration)
    results["ts_pod_latency"] = prometheus_get_timeseries("latency", args.namespace or "", args.duration)
    results["ts_node_cpu"] = prometheus_get_node_timeseries("cpu", args.duration)
    results["ts_node_memory"] = prometheus_get_node_timeseries("memory", args.duration)

    # Service topology (short window)
    results["service_topology"] = prometheus_get_service_topology(args.namespace, time_window="2m")

    # Print RAW results for every query
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()


