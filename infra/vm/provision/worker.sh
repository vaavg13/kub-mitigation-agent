#!/bin/bash
set -euo pipefail

NODE_NAME=${1:?"node name required"}
SERVER_IP=${2:?"server IP required"}
ZONE=${3:-default}

echo "--- System Preparation (Agent ${NODE_NAME}) ---"
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

if ! command -v sshpass >/dev/null 2>&1; then
  echo "--- Installing sshpass for token retrieval ---"
  apt-get update -y >/dev/null
  apt-get install -y sshpass >/dev/null
fi

echo "--- Joining K3s Agent: ${NODE_NAME} to server ${SERVER_IP} ---"

K3S_TOKEN=""
MAX_ATTEMPTS=30
ATTEMPT=0

until [[ -n "${K3S_TOKEN}" ]] || [[ ${ATTEMPT} -ge ${MAX_ATTEMPTS} ]]; do
  echo "Attempt $((ATTEMPT+1))/${MAX_ATTEMPTS}: Fetching K3s token from server..."

  if ping -c 1 -W 2 "${SERVER_IP}" >/dev/null 2>&1; then
    K3S_TOKEN=$(sshpass -p vagrant ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
                    vagrant@"${SERVER_IP}" \
                    "sudo cat /var/lib/rancher/k3s/server/node-token" 2>/dev/null | tr -d '\r')

    if [[ -n "${K3S_TOKEN}" ]]; then
      echo "✓ Token acquired via SSH"
      break
    fi
  fi

  ATTEMPT=$((ATTEMPT+1))
  sleep 3
done

if [[ -z "${K3S_TOKEN}" ]]; then
  echo "ERROR: Failed to acquire token after ${MAX_ATTEMPTS} attempts"
  exit 1
fi

echo "Installing K3s agent and joining cluster..."
curl -sfL https://get.k3s.io | K3S_URL=https://"${SERVER_IP}":6443 K3S_TOKEN="${K3S_TOKEN}" sh -s - agent

echo "✓ Agent installation complete for ${NODE_NAME} (zone: ${ZONE})"