#!/bin/bash

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_DIR="${SCRIPT_DIR}/manifests"
NODEPORT_DIR="${MANIFEST_DIR}/nodeports"
GRAFANA_DIR="${SCRIPT_DIR}/grafana"

print_status() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }

ensure_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        print_error "Required command '$1' not found in PATH"
        exit 1
    fi
}

ensure_host_kubeconfig() {
    local cfg
    cfg="${KUBECONFIG:-$HOME/.kube/config}"
    if [[ ! -f "$cfg" ]]; then
        print_error "Kubeconfig not found at '$cfg'. Please acquire kubeconfig on the host and set KUBECONFIG or place it at ~/.kube/config."
        exit 1
    fi
}

ensure_helm_repo() {
    local name="$1" url="$2"
    if ! helm repo list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$name"; then
        helm repo add "$name" "$url"
    fi
}

main() {
    ensure_command kubectl; ensure_command helm
    ensure_host_kubeconfig

    for d in "$MANIFEST_DIR" "$NODEPORT_DIR" "$GRAFANA_DIR"; do
        [[ -d "$d" ]] || { print_error "Missing directory: $d"; exit 1; }
    done

    ensure_helm_repo prometheus-community https://prometheus-community.github.io/helm-charts
    ensure_helm_repo istio https://istio-release.storage.googleapis.com/charts
    helm repo update

    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

    print_status "Deploying Prometheus and Grafana"
    helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
        --namespace monitoring \
        --set prometheus.prometheusSpec.nodeSelector."topology\\.kubernetes\\.io/zone"=cloud \
        --set alertmanager.alertmanagerSpec.nodeSelector."topology\\.kubernetes\\.io/zone"=cloud \
        --set grafana.nodeSelector."topology\\.kubernetes\\.io/zone"=cloud \
        --set prometheusOperator.nodeSelector."topology\\.kubernetes\\.io/zone"=cloud \
        --set kubeStateMetrics.nodeSelector."topology\\.kubernetes\\.io/zone"=cloud \
        --set grafana.sidecar.dashboards.enabled=true \
        --set grafana.sidecar.dashboards.label=grafana_dashboard

    kubectl apply -n monitoring -f "${NODEPORT_DIR}/prometheus-nodeport.yaml"
    kubectl apply -n monitoring -f "${NODEPORT_DIR}/grafana-nodeport.yaml"

    print_status "Configuring Grafana dashboard"
    kubectl create configmap grafana-dashboard-kub-agent-observability-v2 \
        --from-file=kub-agent-observability-v2.json="${GRAFANA_DIR}/kub-agent-observatility_v2.json" \
        -n monitoring --dry-run=client -o yaml | kubectl apply -f -
    kubectl label configmap grafana-dashboard-kub-agent-observability-v2 -n monitoring grafana_dashboard=1 --overwrite

    kubectl create namespace istio-system --dry-run=client -o yaml | kubectl apply -f -

    print_status "Deploying Istio"
    helm upgrade --install istio-base istio/base -n istio-system
    helm upgrade --install istiod istio/istiod -n istio-system \
        --set pilot.nodeSelector."topology\\.kubernetes\\.io/zone"=cloud \
        --set global.proxy.tracer=zipkin \
        --wait
    helm upgrade --install istio-ingressgateway istio/gateway -n istio-system \
        --set nodeSelector."topology\\.kubernetes\\.io/zone"=cloud

    kubectl label namespace default istio-injection=enabled --overwrite
    kubectl apply -f "${MANIFEST_DIR}/istio-envoy-podmonitor.yaml"

    # Jaeger disabled per request

    # Kiali disabled per request

    if [[ -f "${MANIFEST_DIR}/mub-monitor.yaml" ]]; then
        kubectl apply -f "${MANIFEST_DIR}/mub-monitor.yaml"
    fi

    print_status "Monitoring setup completed successfully!"
}

main "$@"


