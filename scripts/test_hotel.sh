#!/bin/bash
# Simple test script for Hotel Reservation
# Tests basic connectivity to services

NAMESPACE="hotel-reservation"

echo "🧪 Testing Hotel Reservation deployment..."
echo ""

# Check if namespace exists
if ! kubectl get namespace $NAMESPACE &> /dev/null; then
    echo "❌ Namespace $NAMESPACE not found. Deploy first with: ./scripts/deploy_hotel_simple.sh"
    exit 1
fi

# Show pod status
echo "📊 Pod Status:"
kubectl get pods -n $NAMESPACE
echo ""

# Check for running pods
RUNNING=$(kubectl get pods -n $NAMESPACE --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
TOTAL=$(kubectl get pods -n $NAMESPACE --no-headers 2>/dev/null | wc -l)
echo "Running: $RUNNING / $TOTAL"
echo ""

if [ "$RUNNING" -eq "0" ]; then
    echo "❌ No pods running. Check deployment."
    exit 1
fi

# Find frontend service
FRONTEND_SVC=$(kubectl get svc -n $NAMESPACE | grep frontend | awk '{print $1}')
if [ -z "$FRONTEND_SVC" ]; then
    echo "⚠️  Frontend service not found"
    exit 1
fi

echo "🎯 Found frontend service: $FRONTEND_SVC"
echo ""

# Port forward in background
echo "🔌 Setting up port-forward..."
kubectl port-forward -n $NAMESPACE svc/$FRONTEND_SVC 5000:5000 &
PF_PID=$!
sleep 3

# Test endpoints
echo "🌐 Testing endpoints..."
echo ""

# Test 1: Search hotels
echo "1. Testing /hotels endpoint..."
if curl -s -f "http://localhost:5000/hotels?inDate=2015-04-09&outDate=2015-04-10" > /tmp/hotel_test.json; then
    echo "   ✅ /hotels responds"
    cat /tmp/hotel_test.json | head -c 200
    echo ""
else
    echo "   ❌ /hotels failed"
fi
echo ""

# Test 2: Recommendations
echo "2. Testing /recommendations endpoint..."
if curl -s -f "http://localhost:5000/recommendations?require=dis&lat=37.7&lon=-122.4" > /tmp/hotel_rec.json; then
    echo "   ✅ /recommendations responds"
    cat /tmp/hotel_rec.json | head -c 200
    echo ""
else
    echo "   ❌ /recommendations failed"
fi
echo ""

# Cleanup
kill $PF_PID 2>/dev/null || true

echo "✅ Basic tests complete!"
echo ""
echo "To interact manually:"
echo "   kubectl port-forward -n $NAMESPACE svc/$FRONTEND_SVC 5000:5000"
echo "   curl http://localhost:5000/hotels?inDate=2015-04-09&outDate=2015-04-10"
echo ""
