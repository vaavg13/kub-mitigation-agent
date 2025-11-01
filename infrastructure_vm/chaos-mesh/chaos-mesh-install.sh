#!/bin/bash

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

DEFAULT_NAMESPACE="chaos-mesh"
DEFAULT_RELEASE="chaos-mesh"

print_status() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }

ensure_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        print_error "Required command '$1' not found in PATH"; exit 1; fi
}

parse_args() {
    CHAOS_NAMESPACE="$DEFAULT_NAMESPACE"
    CHAOS_RELEASE="$DEFAULT_RELEASE"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --namespace) CHAOS_NAMESPACE="$2"; shift 2;;
            --release-name) CHAOS_RELEASE="$2"; shift 2;;
            -h|--help)
                echo "Usage: $0 [--namespace NAMESPACE] [--release-name NAME]"; exit 0;;
            *) print_error "Unknown option: $1"; exit 1;;
        esac
    done
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
    local name="$1" url="$2"; helm repo list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$name" || helm repo add "$name" "$url"
}

main() {
    parse_args "$@"
    ensure_command kubectl; ensure_command helm
    ensure_host_kubeconfig

    ensure_helm_repo chaos-mesh https://charts.chaos-mesh.org
    helm repo update chaos-mesh >/dev/null

    kubectl create namespace "$CHAOS_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

    print_status "Installing Chaos Mesh (release: ${CHAOS_RELEASE}, ns: ${CHAOS_NAMESPACE})"
    helm upgrade --install "$CHAOS_RELEASE" chaos-mesh/chaos-mesh \
        --namespace "$CHAOS_NAMESPACE" \
        --set chaosDaemon.runtime=containerd \
        --set chaosDaemon.socketPath=/run/k3s/containerd/containerd.sock \
        --set controllerManager.replicaCount=1 \
        --set controllerManager.tolerations[0].key=node-role.kubernetes.io/control-plane \
        --set controllerManager.tolerations[0].operator=Exists \
        --set controllerManager.tolerations[0].effect=NoSchedule >/dev/null

    print_status "Waiting for Chaos Mesh pods"
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance="$CHAOS_RELEASE" -n "$CHAOS_NAMESPACE" --timeout=300s || \
        print_warning "Timed out waiting for pods; continuing"

    kubectl get pods -n "$CHAOS_NAMESPACE" -l app.kubernetes.io/instance="$CHAOS_RELEASE"
    kubectl get services -n "$CHAOS_NAMESPACE"

    if kubectl get service chaos-dashboard -n "$CHAOS_NAMESPACE" >/dev/null 2>&1; then
        local p; p=$(kubectl get svc chaos-dashboard -n "$CHAOS_NAMESPACE" -o jsonpath='{.spec.ports[0].port}')
        print_status "Chaos Dashboard port: ${p} (use kubectl port-forward if needed)"
    fi

    print_status "Chaos Mesh installation completed"
}

main "$@"


