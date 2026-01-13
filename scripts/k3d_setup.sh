#!/bin/bash
set -e

# Simple k3d cluster setup for testing DeathStarBench apps
# No complex VM infrastructure - just a local k3d cluster

CLUSTER_NAME="hotel-test"

echo "🚀 Setting up k3d cluster for Hotel Reservation testing..."

# Check if k3d is installed
if ! command -v k3d &> /dev/null; then
    echo "❌ k3d not found. Install with: curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash"
    exit 1
fi

# Delete existing cluster if it exists
if k3d cluster list | grep -q "$CLUSTER_NAME"; then
    echo "🧹 Removing existing cluster..."
    k3d cluster delete $CLUSTER_NAME
fi

# Create k3d cluster
# - 1 server, 3 workers (simple setup)
# - Expose port 8080 for ingress
# - Disable traefik (we'll use our own ingress if needed)
echo "📦 Creating k3d cluster..."
k3d cluster create $CLUSTER_NAME \
    --agents 3 \
    --port "8080:80@loadbalancer" \
    --k3s-arg "--disable=traefik@server:0"

# Wait for cluster to be ready
echo "⏳ Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s

# Show cluster info
echo ""
echo "✅ k3d cluster ready!"
echo ""
kubectl get nodes
echo ""

# Export kubeconfig
k3d kubeconfig get $CLUSTER_NAME > ~/.kube/k3d-$CLUSTER_NAME-config
export KUBECONFIG=$(k3d kubeconfig write $CLUSTER_NAME)

echo ""
echo "📝 To use this cluster:"
echo "   export KUBECONFIG=\$(k3d kubeconfig write $CLUSTER_NAME)"
echo ""
echo "🔥 To delete:"
echo "   k3d cluster delete $CLUSTER_NAME"
echo ""
