#!/bin/bash
set -euo pipefail

# Assumes kubectl is configured on host
nohup kubectl -n monitoring port-forward svc/prometheus-grafana 3001:80 --address 127.0.0.1 \
  >/dev/null 2>&1 & echo $! > /tmp/grafana-port-forward.pid
echo "Grafana available at http://localhost:3001 (PID $(cat /tmp/grafana-port-forward.pid))"


