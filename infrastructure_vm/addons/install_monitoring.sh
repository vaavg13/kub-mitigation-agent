#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_status() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }

ensure_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        print_error "Required command '$1' not found in PATH"
        exit 1
    fi
}

ensure_kubeconfig() {
    local cfg="${KUBECONFIG:-}"
    if [[ -z "$cfg" || ! -f "$cfg" ]]; then
        print_error "KUBECONFIG must point to a valid kubeconfig file before running this script"
        exit 1
    fi
}

ensure_helm_repo() {
    local name="$1" url="$2"
    if ! helm repo list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$name"; then
        helm repo add "$name" "$url"
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="${SCRIPT_DIR}/monitoring"
MANIFEST_DIR="${ASSETS_DIR}/manifests"
NODEPORT_DIR="${MANIFEST_DIR}/nodeports"
GRAFANA_DIR="${ASSETS_DIR}/grafana"
VALUES_FILE="${ASSETS_DIR}/values.yaml"

SYSTEM_LABEL_KEY="kub-mitigation/system-services"
SYSTEM_LABEL_VALUE="true"
SYSTEM_TAINT_EFFECT="NoSchedule"

main() {
    ensure_command kubectl
    ensure_command helm
    ensure_kubeconfig

    for d in "$MANIFEST_DIR" "$NODEPORT_DIR" "$GRAFANA_DIR"; do
        [[ -d "$d" ]] || { print_error "Missing directory: $d"; exit 1; }
    done

    [[ -f "$VALUES_FILE" ]] || { print_error "Missing Helm values file: $VALUES_FILE"; exit 1; }

    ensure_helm_repo prometheus-community https://prometheus-community.github.io/helm-charts
    ensure_helm_repo istio https://istio-release.storage.googleapis.com/charts
    helm repo update >/dev/null

    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

    print_status "Deploying kube-prometheus-stack"
    helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
        --namespace monitoring \
        -f "$VALUES_FILE" >/dev/null

    kubectl apply -n monitoring -f "${NODEPORT_DIR}/prometheus-nodeport.yaml"
    kubectl apply -n monitoring -f "${NODEPORT_DIR}/grafana-nodeport.yaml"

    print_status "Configuring Grafana dashboards"
    kubectl create configmap grafana-dashboard-kub-agent-observability-v2 \
        --from-file=kub-agent-observability-v2.json="${GRAFANA_DIR}/kub-agent-observatility_v2.json" \
        -n monitoring --dry-run=client -o yaml | kubectl apply -f -
    kubectl label configmap grafana-dashboard-kub-agent-observability-v2 -n monitoring grafana_dashboard=1 --overwrite

    kubectl create namespace istio-system --dry-run=client -o yaml | kubectl apply -f -

    print_status "Deploying Istio components"
    helm upgrade --install istio-base istio/base -n istio-system >/dev/null

    helm upgrade --install istiod istio/istiod -n istio-system \
        --set-string pilot.nodeSelector."${SYSTEM_LABEL_KEY}"="${SYSTEM_LABEL_VALUE}" \
        --set pilot.tolerations[0].key="${SYSTEM_LABEL_KEY}" \
        --set pilot.tolerations[0].operator=Equal \
        --set-string pilot.tolerations[0].value="${SYSTEM_LABEL_VALUE}" \
        --set pilot.tolerations[0].effect="${SYSTEM_TAINT_EFFECT}" \
        --set global.proxy.tracer=zipkin \
        --wait >/dev/null

    helm upgrade --install istio-ingressgateway istio/gateway -n istio-system \
        --set-string nodeSelector."${SYSTEM_LABEL_KEY}"="${SYSTEM_LABEL_VALUE}" \
        --set tolerations[0].key="${SYSTEM_LABEL_KEY}" \
        --set tolerations[0].operator=Equal \
        --set-string tolerations[0].value="${SYSTEM_LABEL_VALUE}" \
        --set tolerations[0].effect="${SYSTEM_TAINT_EFFECT}" >/dev/null

    kubectl label namespace default istio-injection=enabled --overwrite
    kubectl apply -f "${MANIFEST_DIR}/istio-envoy-podmonitor.yaml"

    if [[ -f "${MANIFEST_DIR}/mub-monitor.yaml" ]]; then
        kubectl apply -f "${MANIFEST_DIR}/mub-monitor.yaml"
    fi

    print_status "Monitoring stack ready"
}

main "$@"

