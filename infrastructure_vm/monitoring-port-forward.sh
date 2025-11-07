#!/bin/bash
set -euo pipefail

# Grafana
nohup kubectl -n monitoring port-forward svc/prometheus-grafana 3001:80 --address 127.0.0.1 \
  >/dev/null 2>&1 & echo $! > /tmp/grafana-port-forward.pid
echo "Grafana available at http://localhost:3001 (PID $(cat /tmp/grafana-port-forward.pid))"

# Prometheus
nohup kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090 --address 127.0.0.1 \
  >/dev/null 2>&1 & echo $! > /tmp/prometheus-port-forward.pid
echo "Prometheus available at http://localhost:9090 (PID $(cat /tmp/prometheus-port-forward.pid))"



