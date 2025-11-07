#!/bin/bash
set -euo pipefail

SERVER_IP=${1:?"server IP required"}

echo "--- System Preparation (Server) ---"
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

echo "--- Installing K3s Server (Control Plane) ---"
curl -sfL https://get.k3s.io | sh -s - server \
  --cluster-init \
  --disable traefik \
  --write-kubeconfig-mode "644" \
  --tls-san "${SERVER_IP}"

echo "--- Waiting for K3s Server to be ready..."
timeout 300 bash -c 'until sudo kubectl get nodes 2>/dev/null; do sleep 1; done'
echo "K3s Server is READY."

chmod 644 /etc/rancher/k3s/k3s.yaml

