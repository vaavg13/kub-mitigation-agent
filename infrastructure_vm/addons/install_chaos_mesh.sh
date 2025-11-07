#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

DEFAULT_NAMESPACE="chaos-mesh"
DEFAULT_RELEASE="chaos-mesh"
DEFAULT_CHART_VERSION="2.8.0"

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
    if ! helm repo list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$name"; then
        helm repo add "$name" "$url"
    fi
}

parse_args() {
    CHAOS_NAMESPACE="$DEFAULT_NAMESPACE"
    CHAOS_RELEASE="$DEFAULT_RELEASE"
    CHAOS_CHART_VERSION="$DEFAULT_CHART_VERSION"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --namespace)
                CHAOS_NAMESPACE="$2"
                shift 2
                ;;
            --release-name)
                CHAOS_RELEASE="$2"
                shift 2
                ;;
            -h|--help)
                cat <<EOF
Usage: $0 [--namespace NAMESPACE] [--release-name NAME]
EOF
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
}

main() {
    parse_args "$@"
    ensure_command kubectl
    ensure_command helm
    ensure_kubeconfig

    ensure_helm_repo chaos-mesh https://charts.chaos-mesh.org
    helm repo update chaos-mesh >/dev/null

    kubectl create namespace "$CHAOS_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

    print_status "Installing Chaos Mesh (release: ${CHAOS_RELEASE}, namespace: ${CHAOS_NAMESPACE})"
    helm upgrade --install "$CHAOS_RELEASE" chaos-mesh/chaos-mesh \
        --namespace "$CHAOS_NAMESPACE" \
        --set chaosDaemon.runtime=containerd \
        --set chaosDaemon.socketPath=/run/k3s/containerd/containerd.sock \
        --version "$CHAOS_CHART_VERSION" >/dev/null

    print_status "Waiting for Chaos Mesh pods"
    if ! kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance="$CHAOS_RELEASE" -n "$CHAOS_NAMESPACE" --timeout=300s; then
        print_warning "Timed out waiting for Chaos Mesh pods; continuing"
    fi

    kubectl get pods -n "$CHAOS_NAMESPACE" -l app.kubernetes.io/instance="$CHAOS_RELEASE"
    kubectl get services -n "$CHAOS_NAMESPACE"

    if kubectl get service chaos-dashboard -n "$CHAOS_NAMESPACE" >/dev/null 2>&1; then
        local port
        port=$(kubectl get svc chaos-dashboard -n "$CHAOS_NAMESPACE" -o jsonpath='{.spec.ports[0].port}')
        print_status "Chaos Dashboard exposed on port ${port}"
    fi

    print_status "Chaos Mesh installation completed"
}

main "$@"

