#!/bin/bash
set -e

# Simple deployment of Hotel Reservation
# No agent, no traffic generation - just deploy and test connectivity

NAMESPACE="hotel-reservation"
SRC_DIR="APPS/real-apps/hotel-reservation/src"
MANIFESTS_DIR="$SRC_DIR/kubernetes"

echo "🏨 Deploying Hotel Reservation (simple mode)..."
echo ""

# Step 1: Check if source exists
if [ ! -d "$SRC_DIR" ]; then
    echo "❌ Source directory not found: $SRC_DIR"
    echo "   Run: cp -r /tmp/DeathStarBench/hotelReservation $SRC_DIR"
    exit 1
fi

echo "✓ Using manifests from: $MANIFESTS_DIR"

# Step 3: Create namespace
echo "📦 Creating namespace..."
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Step 4: Deploy all manifests
echo "🚀 Deploying services..."
kubectl apply -f $MANIFESTS_DIR/ -n $NAMESPACE

# Step 5: Wait for pods
echo ""
echo "⏳ Waiting for pods to be ready (this may take 2-3 minutes)..."
kubectl wait --for=condition=ready pod --all -n $NAMESPACE --timeout=300s || {
    echo "⚠️  Some pods not ready yet. Checking status..."
    kubectl get pods -n $NAMESPACE
}

# Show deployment status
echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 Pod Status:"
kubectl get pods -n $NAMESPACE
echo ""
echo "🌐 Services:"
kubectl get svc -n $NAMESPACE
echo ""

# Get frontend service details
FRONTEND_SVC=$(kubectl get svc -n $NAMESPACE -l app=frontend -o name 2>/dev/null | head -1)
if [ -n "$FRONTEND_SVC" ]; then
    echo "🎯 Frontend service found: $FRONTEND_SVC"
    echo ""
    echo "To access frontend:"
    echo "   kubectl port-forward -n $NAMESPACE svc/frontend 5000:5000"
    echo "   curl http://localhost:5000/hotels?inDate=2015-04-09&outDate=2015-04-10"
else
    echo "⚠️  Frontend service not found. Check manifests."
fi

echo ""
echo "📝 Useful commands:"
echo "   kubectl get all -n $NAMESPACE"
echo "   kubectl logs -n $NAMESPACE <pod-name>"
echo "   kubectl describe pod -n $NAMESPACE <pod-name>"
echo ""
