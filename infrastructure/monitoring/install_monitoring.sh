#!/bin/bash

set -e

MANIFEST_DIR="$(dirname "$0")/manifests"
NODEPORT_DIR="$MANIFEST_DIR/nodeports"
GRAFANA_DIR="$(dirname "$0")/grafana"

# Helper to apply YAML
apply_yaml() {
    local filename=$1
    local namespace=$2
    local nodeport=$3
    local path
    if [[ "$nodeport" == "true" ]]; then
        path="$NODEPORT_DIR/$filename"
    else
        path="$MANIFEST_DIR/$filename"
    fi
    echo "→ Applying $filename"
    if [[ -n "$namespace" ]]; then
        kubectl apply -f "$path" -n "$namespace"
    else
        kubectl apply -f "$path"
    fi
}

# Secure kubeconfig file
secure_kubeconfig() {
    local kubeconfig="$HOME/.kube/config"
    if [[ -f "$kubeconfig" ]]; then
        echo "→ Securing kubeconfig file"
        chmod go-r "$kubeconfig" || echo "Warning: Could not modify kubeconfig permissions (not critical)"
    fi
}

# Install monitoring stack
install_monitoring_stack() {
    secure_kubeconfig

    # --- Metrics Server (install clean one since k3d's is disabled) ---
    if ! helm repo list | grep -q "^metrics-server"; then
        echo "→ Adding metrics-server Helm repository"
        helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
    fi
    helm repo update
    helm install metrics-server metrics-server/metrics-server -n kube-system \
      --set args="{--cert-dir=/tmp,--secure-port=10250,--kubelet-preferred-address-types=InternalIP\,ExternalIP\,Hostname,--kubelet-use-node-status-port,--metric-resolution=15s,--kubelet-insecure-tls}" \
      --set nodeSelector."topology\.kubernetes\.io/zone"=cloud

    # --- Prometheus & Grafana ---
    kubectl create namespace monitoring || true
    if ! helm repo list | grep -q "^prometheus-community"; then
        echo "→ Adding prometheus-community Helm repository"
        helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    fi
    helm repo update
    helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring \
      --set prometheus.prometheusSpec.nodeSelector."topology\.kubernetes\.io/zone"=cloud \
      --set alertmanager.alertmanagerSpec.nodeSelector."topology\.kubernetes\.io/zone"=cloud \
      --set grafana.nodeSelector."topology\.kubernetes\.io/zone"=cloud \
      --set prometheusOperator.nodeSelector."topology\.kubernetes\.io/zone"=cloud \
      --set kubeStateMetrics.nodeSelector."topology\.kubernetes\.io/zone"=cloud \
      --set grafana.sidecar.dashboards.enabled=true \
      --set grafana.sidecar.dashboards.label=grafana_dashboard

    apply_yaml "prometheus-nodeport.yaml" "monitoring" true
    apply_yaml "grafana-nodeport.yaml" "monitoring" true

    # --- Grafana Dashboard (always apply) ---
    if [[ -f "$GRAFANA_DIR/kub-agent-observatility_v2.json" ]]; then
        echo "→ Applying Grafana dashboard ConfigMap"
        kubectl create configmap grafana-dashboard-kub-agent-observability-v2 \
          --from-file=kub-agent-observability-v2.json="$GRAFANA_DIR/kub-agent-observatility_v2.json" \
          -n monitoring --dry-run=client -o yaml | kubectl apply -f -
        kubectl label configmap grafana-dashboard-kub-agent-observability-v2 -n monitoring grafana_dashboard=1 --overwrite
    else
        echo "Warning: Grafana dashboard JSON not found at $GRAFANA_DIR/kub-agent-observatility_v2.json"
    fi

    # --- Istio ---
    kubectl create namespace istio-system || true
    if ! helm repo list | grep -q "^istio"; then
        echo "→ Adding istio Helm repository"
        helm repo add istio https://istio-release.storage.googleapis.com/charts
    fi
    helm repo update
    helm install istio-base istio/base -n istio-system
    helm install istiod istio/istiod -n istio-system \
      --set pilot.nodeSelector."topology\.kubernetes\.io/zone"=cloud \
      --set global.proxy.tracer=zipkin --wait
    helm install istio-ingressgateway istio/gateway -n istio-system \
      --set nodeSelector."topology\.kubernetes\.io/zone"=cloud

    kubectl label namespace default istio-injection=enabled --overwrite

    # Istio/Envoy scraping (simple PodMonitor) and app metrics
    apply_yaml "istio-envoy-podmonitor.yaml"

    # --- Jaeger ---
    apply_yaml "jaeger.yaml"
    apply_yaml "jaeger-nodeport.yaml" "" true

    # --- Kiali ---
    if ! helm repo list | grep -q "^kiali"; then
        echo "→ Adding kiali Helm repository"
        helm repo add kiali https://kiali.org/helm-charts
    fi
    helm repo update
    helm install -n istio-system -f "$MANIFEST_DIR/kiali-values.yaml" kiali-server kiali/kiali-server

    apply_yaml "kiali-nodeport.yaml" "" true
}

# Main
if [[ ! -d "$MANIFEST_DIR" ]]; then
    echo "Error: Manifests directory not found at $MANIFEST_DIR"
    echo "Please ensure all YAML files are in the manifests directory"
    exit 1
fi
if [[ ! -d "$NODEPORT_DIR" ]]; then
    echo "Error: Nodeports directory not found at $NODEPORT_DIR"
    echo "Please ensure all nodeport YAML files are in the manifests/nodeports directory"
    exit 1
fi

install_monitoring_stack

echo "Monitoring setup completed successfully!" 