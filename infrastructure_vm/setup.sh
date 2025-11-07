#!/bin/bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Absolute script directory
SCRIPT_ABSOLUTE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration sources
CLUSTER_CONFIG_FILE="${SCRIPT_ABSOLUTE_DIR}/config/cluster.json"
CONFIG_CLI="${SCRIPT_ABSOLUTE_DIR}/config/cluster_config_cli.py"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "Python interpreter '${PYTHON_BIN}' not found. Set PYTHON_BIN to a valid python3 binary." >&2
    exit 1
fi

read_config_value() {
    local query="$1"
    "${PYTHON_BIN}" "${CONFIG_CLI}" value "${CLUSTER_CONFIG_FILE}" "${query}"
}

NETWORK_NAME=$(read_config_value "network.name")
BRIDGE_NAME=$(read_config_value "network.bridge")
NETWORK_IP=$(read_config_value "network.gateway")
NETWORK_MASK=$(read_config_value "network.mask")
DHCP_START=$(read_config_value "network.dhcp_start")
DHCP_END=$(read_config_value "network.dhcp_end")
IP_BASE=$(read_config_value "network.ip_base")

KUBECONFIG_RELATIVE=$(read_config_value "kubeconfig.path")
KUBECONFIG_PATH="${SCRIPT_ABSOLUTE_DIR}/${KUBECONFIG_RELATIVE}"
KUBECONFIG_DIR="$(dirname "${KUBECONFIG_PATH}")"

HOST_KUBECONFIG_DIR="${HOME}/.kube"
HOST_KUBECONFIG_PATH="${HOST_KUBECONFIG_DIR}/config"

CHAOSD_VERSION=$(read_config_value "chaosd.version")
CHAOSD_PORT=$(read_config_value "chaosd.port")

# Function to print colored output
print_status() { echo -e "${GREEN}[✓]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
print_info() { echo -e "${BLUE}[ℹ]${NC} $1"; }

ensure_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        print_error "Required command '$1' not found in PATH"
        exit 1
    fi
}

mapfile -t ALL_NODE_NAMES < <("${PYTHON_BIN}" "${CONFIG_CLI}" node-names "${CLUSTER_CONFIG_FILE}")

if ! SERVER_NODE_NAME=$("${PYTHON_BIN}" "${CONFIG_CLI}" server-field "${CLUSTER_CONFIG_FILE}" name); then
    print_error "No server node defined in ${CLUSTER_CONFIG_FILE}"
    exit 1
fi

if [[ -z "${SERVER_NODE_NAME}" ]]; then
    print_error "No server node defined in ${CLUSTER_CONFIG_FILE}"
    exit 1
fi

if ! SERVER_IP_SUFFIX=$("${PYTHON_BIN}" "${CONFIG_CLI}" server-field "${CLUSTER_CONFIG_FILE}" ip_suffix); then
    print_error "Server node in ${CLUSTER_CONFIG_FILE} is missing ip_suffix"
    exit 1
fi

SERVER_IP="${IP_BASE}${SERVER_IP_SUFFIX}"

mapfile -t WORKER_VMS < <("${PYTHON_BIN}" "${CONFIG_CLI}" worker-names "${CLUSTER_CONFIG_FILE}")

mapfile -t CHAOSD_TARGET_NODES < <("${PYTHON_BIN}" "${CONFIG_CLI}" chaosd-targets "${CLUSTER_CONFIG_FILE}")

TOTAL_NODES=${#ALL_NODE_NAMES[@]}
FIRST_WORKER="${WORKER_VMS[0]:-}"

# Function to check if running with proper permissions
check_permissions() {
    # Check if we can run virsh commands (with or without sudo)
    if ! sudo virsh net-list >/dev/null 2>&1; then
        print_error "Cannot access libvirt. Please ensure libvirt is installed and running."
        exit 1
    fi
    
    # Check if vagrant is available
    if ! command -v vagrant >/dev/null 2>&1; then
        print_error "Vagrant is not installed. Please install it first."
        exit 1
    fi
}

# Helper to ensure Vagrant exists without verifying libvirt (used for ad-hoc helpers)
ensure_vagrant_available() {
    if ! command -v vagrant >/dev/null 2>&1; then
        print_error "Vagrant is not installed. Please install it first."
        exit 1
    fi
}

# Wrapper around vagrant to filter libvirt warnings
vagrant_run() {
    ensure_vagrant_available

    local output
    if output=$(vagrant "$@" 2>&1); then
        printf '%s\n' "$output"
        return 0
    else
        local status=$?
        printf '%s\n' "$output"
        return $status
    fi
}

# Return a list of VMs that are currently running
list_running_vms() {
    ensure_vagrant_available
    vagrant_run status --machine-readable \
        | awk -F, '$3 == "state" && $4 == "running" {print $2}'
}

# Function to create libvirt network
create_network() {
    print_info "Checking libvirt network: ${NETWORK_NAME}..."
    
    if sudo virsh net-list --all | grep -q "${NETWORK_NAME}"; then
        print_status "Network '${NETWORK_NAME}' already exists"
        
        # Check if it's active
        if ! sudo virsh net-list | grep -q "${NETWORK_NAME}"; then
            print_info "Starting network '${NETWORK_NAME}'..."
            sudo virsh net-start "${NETWORK_NAME}"
            print_status "Network started"
        fi
    else
        print_info "Creating libvirt network '${NETWORK_NAME}'..."
        
        # Create network XML definition
        cat <<EOF | sudo virsh net-define /dev/stdin
<network>
  <name>${NETWORK_NAME}</name>
  <forward mode='nat'/>
  <bridge name='${BRIDGE_NAME}' stp='on' delay='0'/>
  <ip address='${NETWORK_IP}' netmask='${NETWORK_MASK}'>
    <dhcp>
      <range start='${DHCP_START}' end='${DHCP_END}'/>
    </dhcp>
  </ip>
</network>
EOF
        
        # Start the network
        sudo virsh net-start "${NETWORK_NAME}"
        print_status "Network created and started"
        
        # Make it autostart on host boot
        sudo virsh net-autostart "${NETWORK_NAME}"
        print_status "Network set to autostart"
    fi
}

# Function to bring up k3s server
start_server() {
    print_info "Bringing up ${SERVER_NODE_NAME} (control plane)..."
    
    if vagrant_run status "${SERVER_NODE_NAME}" | grep -q "running"; then
        print_status "${SERVER_NODE_NAME} is already running"
    else
        vagrant_run up "${SERVER_NODE_NAME}"
        print_status "${SERVER_NODE_NAME} is ready"
    fi
    
    # Wait for server to be fully ready
    print_info "Waiting for k3s server to be fully ready..."
    sleep 10
}

# Function to bring up worker nodes
start_workers() {
    if [[ ${#WORKER_VMS[@]} -eq 0 ]]; then
        print_warning "No worker nodes defined in ${CLUSTER_CONFIG_FILE}"
        return 0
    fi

    print_info "Bringing up worker nodes (${#WORKER_VMS[@]} total)..."

    # Start workers serially to avoid apt/dpkg lock contention during provisioning
    for vm in "${WORKER_VMS[@]}"; do
        print_info "Starting ${vm}..."
        vagrant_run up "${vm}"
    done

    print_status "All worker nodes are ready"
}

install_chaosd_on_node() {
    local node="$1"
    local script_path="${SCRIPT_ABSOLUTE_DIR}/provision/install_chaosd.sh"

    print_info "Installing chaosd on ${node}..."

    if [[ ! -f "${script_path}" ]]; then
        print_error "Chaosd installer script missing at ${script_path}"
        return 1
    fi

    if vagrant_run ssh "${node}" -- -T "sudo env CHAOSD_VERSION=${CHAOSD_VERSION} CHAOSD_PORT=${CHAOSD_PORT} bash -s" < "${script_path}"; then
        print_status "Chaosd installed on ${node}"
        return 0
    else
        print_error "Chaosd installation failed on ${node}"
        return 1
    fi
}

install_chaosd_targets() {
    if [[ ${#CHAOSD_TARGET_NODES[@]} -eq 0 ]]; then
        print_warning "No chaosd target nodes defined"
        return 0
    fi

    local failures=0
    for node in "${CHAOSD_TARGET_NODES[@]}"; do
        if [[ -z "${node}" ]]; then
            continue
        fi
        install_chaosd_on_node "${node}" || failures=1
    done

    if [[ ${failures} -ne 0 ]]; then
        print_error "Chaosd installation encountered errors"
        exit 1
    fi

    print_status "Chaosd installed on all target nodes"
}

ensure_host_tools() {
    ensure_command kubectl
}

download_kubeconfig_to() {
    local destination=${1:?'destination path required'}
    local raw_file tmp_config

    ensure_vagrant_available

    raw_file=$(mktemp)
    tmp_config=$(mktemp)

    if ! vagrant ssh-config "${SERVER_NODE_NAME}" >"${tmp_config}" 2>/dev/null; then
        rm -f "${raw_file}" "${tmp_config}"
        return 1
    fi

    if ! ssh -F "${tmp_config}" "${SERVER_NODE_NAME}" "sudo cat /etc/rancher/k3s/k3s.yaml" >"${raw_file}" 2>/dev/null; then
        rm -f "${raw_file}" "${tmp_config}"
        return 1
    fi

    if ! "${PYTHON_BIN}" "${CONFIG_CLI}" rewrite-kubeconfig "${raw_file}" "${SERVER_IP}" "${destination}"; then
        rm -f "${raw_file}" "${tmp_config}"
        return 1
    fi

    rm -f "${raw_file}" "${tmp_config}"
    return 0
}

ensure_kubeconfig_local() {
    mkdir -p "${KUBECONFIG_DIR}"

    if [[ ! -f "${KUBECONFIG_PATH}" ]]; then
        print_info "Fetching kubeconfig from ${SERVER_NODE_NAME}"
        if download_kubeconfig_to "${KUBECONFIG_PATH}"; then
            print_status "Kubeconfig written to ${KUBECONFIG_PATH}"
        else
            print_error "Failed to retrieve kubeconfig from ${SERVER_NODE_NAME}"
            exit 1
        fi
    fi

    export KUBECONFIG="${KUBECONFIG_PATH}"
}

prepare_cluster_context() {
    ensure_kubeconfig_local
    ensure_host_tools
}

copy_kubeconfig_to_home() {
    local tmp
    tmp=$(mktemp)

    if download_kubeconfig_to "${tmp}"; then
        cat "${tmp}"
        rm -f "${tmp}"
    else
        rm -f "${tmp}"
        print_error "Failed to retrieve kubeconfig from ${SERVER_NODE_NAME}"
        exit 1
    fi
}

# Function to apply zone labels to nodes
apply_node_metadata() {
    print_info "Applying node labels and taints..."

    local count output
    for attempt in $(seq 1 120); do
        if output=$(kubectl get nodes --no-headers 2>/dev/null); then
            count=$(printf '%s\n' "$output" | awk 'NF{c++} END{print c+0}')
        else
            count=0
        fi
        if [[ "$count" -ge "$TOTAL_NODES" ]]; then
            print_status "Detected ${count} registered nodes"
            break
        fi
        print_info "Waiting for nodes to register (${count}/${TOTAL_NODES})"
        sleep 2
    done

    mapfile -t NODE_LABELS < <("${PYTHON_BIN}" "${CONFIG_CLI}" node-labels "${CLUSTER_CONFIG_FILE}")

    mapfile -t NODE_TAINTS < <("${PYTHON_BIN}" "${CONFIG_CLI}" node-taints "${CLUSTER_CONFIG_FILE}")

    for entry in "${NODE_LABELS[@]}"; do
        [[ -z "$entry" ]] && continue
        IFS='|' read -r node key value <<<"$entry"
        kubectl label node "$node" "$key=$value" --overwrite >/dev/null || print_warning "Failed to label $node with $key=$value"
    done

    for entry in "${NODE_TAINTS[@]}"; do
        [[ -z "$entry" ]] && continue
        IFS='|' read -r node key value effect <<<"$entry"
        if [[ -n "$value" ]]; then
            kubectl taint node "$node" "$key=$value:$effect" --overwrite >/dev/null || print_warning "Failed to taint $node with $key=$value:$effect"
        else
            kubectl taint node "$node" "$key:$effect" --overwrite >/dev/null || print_warning "Failed to taint $node with $key:$effect"
        fi
    done

    print_status "Node metadata applied"
    kubectl get nodes --show-labels
}

# Function to verify cluster status
verify_cluster() {
    print_info "Verifying cluster status..."
    echo ''
    echo '=== K3s Cluster Status ==='
    kubectl get nodes -o wide
    echo ''
    echo '=== Node Labels ==='
    kubectl get nodes --show-labels
    echo ''
    echo '=== Cluster Info ==='
    kubectl cluster-info
    print_status "Cluster verification complete"
}

install_monitoring_stack_host() {
    print_info "Installing monitoring stack on k3s cluster..."
    if KUBECONFIG="${KUBECONFIG_PATH}" bash "${SCRIPT_ABSOLUTE_DIR}/addons/install_monitoring.sh"; then
        print_status "Monitoring stack installed"
    else
        print_error "Monitoring stack installation failed"
        exit 1
    fi
}

install_chaos_mesh_host() {
    print_info "Installing Chaos Mesh on k3s cluster..."
    if KUBECONFIG="${KUBECONFIG_PATH}" bash "${SCRIPT_ABSOLUTE_DIR}/addons/install_chaos_mesh.sh" "$@"; then
        print_status "Chaos Mesh installed"
    else
        print_error "Chaos Mesh installation failed"
        exit 1
    fi
}

# Function to show cluster access info
show_access_info() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║           K3s Cluster Setup Complete! 🎉                    ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Access your cluster:"
    echo "  1. SSH into server:    vagrant ssh ${SERVER_NODE_NAME}"
    echo "  2. Run kubectl:        vagrant ssh ${SERVER_NODE_NAME} -c 'sudo kubectl get nodes'"
    echo ""
    echo "Copy kubeconfig to host:"
    echo "  ./setup.sh kubeconfig-copy > ~/.kube/config"
    echo "  export KUBECONFIG=~/.kube/config"
    echo ""
    echo "Management commands:"
    echo "  • Stop cluster:        vagrant halt"
    echo "  • Start cluster:       vagrant up"
    echo "  • Destroy cluster:     vagrant destroy -f"
    if [[ -n "${FIRST_WORKER}" ]]; then
        echo "  • SSH to worker:       vagrant ssh ${FIRST_WORKER}"
    fi
    echo ""
}

# Function to show help
show_help() {
    cat <<EOF
K3s Vagrant Cluster Setup Script

USAGE:
    $0 [COMMAND]

COMMANDS:
    setup               Setup complete cluster (network + server + workers + labels)
    network             Create/start libvirt network only
    server              Start ${SERVER_NODE_NAME} only
    workers             Start worker nodes only
    labels              Apply node labels/taints from config
    verify              Verify cluster status
    monitoring-install  Install monitoring/observability stack on the cluster
    chaos-mesh-install [args]  Install Chaos Mesh (arguments are forwarded to installer)
    chaosd-install       Install or update chaosd on target nodes
    kubeconfig-copy      Print kubeconfig contents to stdout
    clean               Destroy all VMs and remove network
    help                Show this help message

EXAMPLES:
    $0              # Full setup (equivalent to 'setup')
    $0 setup        # Full setup
    $0 network      # Just create the network
    $0 clean        # Clean up everything

EOF
}

# Function to clean up everything
clean_all() {
    print_warning "This will destroy all VMs and remove the libvirt network"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Cancelled"
        exit 0
    fi
    
    print_info "Destroying all VMs..."
    vagrant_run destroy -f || true
    
    print_info "Removing libvirt network..."
    if sudo virsh net-list --all | grep -q "${NETWORK_NAME}"; then
        sudo virsh net-destroy "${NETWORK_NAME}" 2>/dev/null || true
        sudo virsh net-undefine "${NETWORK_NAME}" 2>/dev/null || true
        print_status "Network removed"
    fi
    
    print_status "Cleanup complete"
}

# Function to run full setup
full_setup() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║        K3s Vagrant Cluster Setup with CPU Pinning            ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    check_permissions
    create_network
    start_server
    start_workers
    install_chaosd_targets
    prepare_cluster_context
    apply_node_metadata
    verify_cluster
    install_monitoring_stack_host
    install_chaos_mesh_host
    show_access_info
}

# Main execution
main() {
    # Change to script directory
    cd "$(dirname "${BASH_SOURCE[0]}")"
    
    case "${1:-setup}" in
        setup)
            full_setup
            ;;
        network)
            check_permissions
            create_network
            ;;
        server)
            start_server
            ;;
        workers)
            start_workers
            ;;
        labels)
            prepare_cluster_context
            apply_node_metadata
            ;;
        verify)
            prepare_cluster_context
            verify_cluster
            ;;
        monitoring-install)
            prepare_cluster_context
            install_monitoring_stack_host
            ;;
        chaos-mesh-install)
            shift || true
            prepare_cluster_context
            install_chaos_mesh_host "$@"
            ;;
        chaosd-install)
            install_chaosd_targets
            ;;
        kubeconfig-copy)
            copy_kubeconfig_to_home
            ;;
        clean)
            clean_all
            ;;
        help|-h|--help)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# Execute main function
main "$@"

