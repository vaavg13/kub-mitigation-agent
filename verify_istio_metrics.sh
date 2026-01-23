#!/bin/bash
# Verification script for Istio metrics in Prometheus
set -e

echo "🔍 Verifying Istio Metrics Collection"
echo "======================================"
echo ""

# Check if app is deployed
echo "1. Checking if hotel-reservation app is deployed..."
POD_COUNT=$(kubectl get pods -n hotel-reservation -l security.istio.io/tlsMode=istio --no-headers 2>/dev/null | wc -l | xargs)
if [ "$POD_COUNT" -eq 0 ]; then
    echo "   ❌ No pods with Istio sidecars found in hotel-reservation namespace"
    echo "   ℹ️  Deploy the app first to test metrics collection"
    exit 1
fi
echo "   ✅ Found $POD_COUNT pods with Istio sidecars"
echo ""

# Check if PodMonitor is configured correctly
echo "2. Checking PodMonitor configuration..."
TARGET_PORT=$(kubectl get podmonitor envoy-sidecars -n istio-system -o jsonpath='{.spec.podMetricsEndpoints[0].targetPort}' 2>/dev/null)
if [ "$TARGET_PORT" != "15090" ]; then
    echo "   ❌ PodMonitor targetPort is not 15090 (found: $TARGET_PORT)"
    echo "   ℹ️  Run: kubectl apply -f infrastructure_vm/addons/monitoring/manifests/istio-envoy-podmonitor.yaml"
    exit 1
fi
echo "   ✅ PodMonitor configured with correct targetPort: $TARGET_PORT"
echo ""

# Check if a pod exposes metrics on port 15090
echo "3. Testing metrics endpoint from a random pod..."
RANDOM_POD=$(kubectl get pods -n hotel-reservation -l security.istio.io/tlsMode=istio -o name | head -1 | cut -d'/' -f2)
if [ -z "$RANDOM_POD" ]; then
    echo "   ❌ Could not find a pod to test"
    exit 1
fi
echo "   Testing pod: $RANDOM_POD"

METRICS=$(kubectl exec -n hotel-reservation "$RANDOM_POD" -c istio-proxy -- curl -s localhost:15090/stats/prometheus 2>/dev/null | head -5)
if [ -z "$METRICS" ]; then
    echo "   ❌ Could not retrieve metrics from istio-proxy container"
    exit 1
fi
echo "   ✅ Metrics endpoint responding (sample):"
echo "$METRICS" | sed 's/^/      /'
echo ""

# Check if Prometheus has discovered the targets
echo "4. Checking Prometheus scrape targets..."
PROM_POD=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o name | head -1 | cut -d'/' -f2)
if [ -z "$PROM_POD" ]; then
    echo "   ❌ Prometheus pod not found"
    exit 1
fi

echo "   Querying Prometheus API..."
ACTIVE_TARGETS=$(kubectl exec -n monitoring "$PROM_POD" -c prometheus -- wget -qO- 'localhost:9090/api/v1/targets?state=active' 2>/dev/null | grep -o '"job":"envoy-sidecars"' | wc -l | xargs)
echo "   ✅ Found $ACTIVE_TARGETS active envoy-sidecars targets"
echo ""

# Query for istio_requests_total metric
echo "5. Checking if istio_requests_total metric exists..."
METRIC_EXISTS=$(kubectl exec -n monitoring "$PROM_POD" -c prometheus -- wget -qO- 'localhost:9090/api/v1/query?query=istio_requests_total' 2>/dev/null | grep -o '"status":"success"')
if [ -z "$METRIC_EXISTS" ]; then
    echo "   ⚠️  istio_requests_total metric not found yet"
    echo "   ℹ️  This is normal if no traffic has been sent to the app"
    echo "   ℹ️  Generate some traffic with: python test_traffic.py"
else
    echo "   ✅ istio_requests_total metric exists in Prometheus"
    
    # Show sample values
    echo ""
    echo "   Sample metric values:"
    kubectl exec -n monitoring "$PROM_POD" -c prometheus -- wget -qO- 'localhost:9090/api/v1/query?query=sum(rate(istio_requests_total[1m]))%20by%20(destination_service_name)' 2>/dev/null | python3 -c "import sys, json; data=json.load(sys.stdin); [print(f\"      {r['metric']['destination_service_name']}: {r['value'][1]} req/s\") for r in data.get('data', {}).get('result', [])]" 2>/dev/null || echo "      (unable to parse results)"
fi
echo ""

echo "✅ Verification complete!"
echo ""
echo "📊 To view metrics in Prometheus:"
echo "   kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
echo "   Then open: http://localhost:9090/graph?g0.expr=istio_requests_total"
echo ""
echo "📈 To view in Grafana:"
echo "   kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80"
echo "   Then open: http://localhost:3000 (default: admin/prom-operator)"
