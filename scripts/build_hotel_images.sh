#!/bin/bash
# Build Hotel Reservation Docker images and load into k3d cluster

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOTEL_DIR="$PROJECT_ROOT/DeathStarBench/hotelReservation"
CLUSTER_NAME="hotel-cluster"

echo "=========================================="
echo "Building Hotel Reservation Docker Images"
echo "=========================================="
echo ""

cd "$HOTEL_DIR"

# Check if Dockerfile exists
if [ ! -f "Dockerfile" ]; then
    echo "❌ Dockerfile not found in $HOTEL_DIR"
    exit 1
fi

echo "📦 Building hotel-reservation image..."
docker build -t deathstarbench/hotel-reservation:latest .

if [ $? -eq 0 ]; then
    echo "✅ Image built successfully"
else
    echo "❌ Failed to build image"
    exit 1
fi

echo ""
echo "📥 Loading image into k3d cluster '$CLUSTER_NAME'..."
k3d image import deathstarbench/hotel-reservation:latest -c $CLUSTER_NAME

if [ $? -eq 0 ]; then
    echo "✅ Image loaded into cluster"
else
    echo "❌ Failed to load image into cluster"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ Complete! Image ready in cluster"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Delete the failing pods: kubectl delete pods --all -n hotel-reservation"
echo "  2. New pods will be created and use the local image"
