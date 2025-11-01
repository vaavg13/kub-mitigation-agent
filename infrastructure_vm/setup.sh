#!/bin/bash
set -euo pipefail

# Suppress fog-libvirt warnings about unrecognized arguments
unset VAGRANT_NO_PARALLEL
export FOG_LOG_LEVEL=ERROR

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Absolute script directory
SCRIPT_ABSOLUTE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
NETWORK_NAME="k3s-net"
BRIDGE_NAME="virbr-k3s"
NETWORK_IP="192.168.100.1"
NETWORK_MASK="255.255.255.0"
# DHCP range avoids our static IPs (.10-.30 reserved for VMs)
DHCP_START="192.168.100.100"
DHCP_END="192.168.100.254"

# Chaosd configuration (mirror currently provides v1.4.x only)
CHAOSD_VERSION="${CHAOSD_VERSION:-v1.4.0}"
CHAOSD_PORT="${CHAOSD_PORT:-31767}"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[⚠]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[ℹ]${NC} $1"
}

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
        printf '%s\n' "$output" | sed '/^\[fog\]\[WARNING\]/d'
        return 0
    else
        local status=$?
        printf '%s\n' "$output" | sed '/^\[fog\]\[WARNING\]/d'
        return $status
    fi
}

# Return a list of VMs that are currently running
list_running_vms() {
    ensure_vagrant_available
    vagrant_run status --machine-readable \
        | awk -F, '$3 == "state" && $4 == "running" {print $2}'
}

# Execute a bash script on a VM as root via base64 transport
run_remote_root_script() {
    local vm="$1"
    local script="$2"

    ensure_vagrant_available

    if [[ -z "$vm" ]]; then
        print_error "No VM name provided for remote execution"
        return 1
    fi

    local encoded_script
    encoded_script=$(printf '%s' "$script" | base64 | tr -d '\n')

    vagrant_run ssh "$vm" -c "echo '$encoded_script' | base64 -d | sudo bash"
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
    print_info "Bringing up k3s-server (control plane)..."
    
    if vagrant_run status k3s-server | grep -q "running"; then
        print_status "k3s-server is already running"
    else
        vagrant_run up k3s-server
        print_status "k3s-server is ready"
    fi
    
    # Wait for server to be fully ready
    print_info "Waiting for k3s server to be fully ready..."
    sleep 10
}

# Function to bring up worker nodes
start_workers() {
    print_info "Bringing up worker nodes..."
    
    # Explicitly list all worker nodes (required because they have autostart: false)
    # Start workers in parallel for faster provisioning
    vagrant_run up cloud-worker-1 cloud-worker-2 \
               edge-worker-1 edge-worker-2 \
               edge-worker-3 edge-worker-4 \
               --parallel
    
    print_status "All worker nodes are ready"
}

# Function to apply zone labels to nodes
apply_labels() {
    print_info "Applying zone labels to nodes..."
    
    # Wait for all nodes to register in k3s and become ready
    print_info "Waiting for worker nodes to register..."
    sleep 30
    
    # Apply labels via kubectl from the server
    vagrant_run ssh k3s-server -c "
        # Wait for all 7 nodes (1 server + 6 workers)
        echo 'Waiting for all nodes to be ready...'
        for i in {1..60}; do
            NODE_COUNT=\$(sudo kubectl get nodes --no-headers 2>/dev/null | wc -l)
            if [ \$NODE_COUNT -eq 7 ]; then
                echo 'All 7 nodes are registered!'
                break
            fi
            echo \"Attempt \$i/60: Found \$NODE_COUNT/7 nodes\"
            sleep 2
        done
        
        echo ''
        echo 'Labeling cloud workers...'
        sudo kubectl label node cloud-worker-1 topology.kubernetes.io/zone=cloud --overwrite || true
        sudo kubectl label node cloud-worker-2 topology.kubernetes.io/zone=cloud --overwrite || true
        
        echo 'Labeling edge workers (site 1)...'
        sudo kubectl label node edge-worker-1 topology.kubernetes.io/zone=edge-site-1 --overwrite || true
        sudo kubectl label node edge-worker-2 topology.kubernetes.io/zone=edge-site-1 --overwrite || true
        
        echo 'Labeling edge workers (site 2)...'
        sudo kubectl label node edge-worker-3 topology.kubernetes.io/zone=edge-site-2 --overwrite || true
        sudo kubectl label node edge-worker-4 topology.kubernetes.io/zone=edge-site-2 --overwrite || true
        
        echo ''
        echo 'Node labels summary:'
        sudo kubectl get nodes -L topology.kubernetes.io/zone
    " 2>/dev/null
    
    print_status "Zone labels applied"
}

# Function to verify cluster status
verify_cluster() {
    print_info "Verifying cluster status..."
    
    vagrant_run ssh k3s-server -c "
        echo ''
        echo '=== K3s Cluster Status ==='
        sudo kubectl get nodes -o wide
        echo ''
        echo '=== Node Labels ==='
        sudo kubectl get nodes --show-labels
        echo ''
        echo '=== Cluster Info ==='
        sudo kubectl cluster-info
    " 2>/dev/null
    
    print_status "Cluster verification complete"
}

# Install Chaosd on a single VM
install_chaosd_on_vm() {
    local vm="$1"

    print_info "Installing Chaosd (${CHAOSD_VERSION}) on ${vm}..."

    if ! vagrant_run status "$vm" --machine-readable \
        | awk -F, '$3 == "state" {print $4; exit}' \
        | grep -qx "running"; then
        print_warning "Skipping ${vm}: VM is not running"
        return 0
    fi

    local remote_script
    remote_script=$(cat <<'EOF'
set -euo pipefail

CHAOSD_VERSION="__CHAOSD_VERSION__"
CHAOSD_PORT="__CHAOSD_PORT__"
ARCHIVE="chaosd-${CHAOSD_VERSION}-linux-amd64.tar.gz"
INSTALL_ROOT="/usr/local"
TARGET_DIR="${INSTALL_ROOT}/chaosd-${CHAOSD_VERSION}-linux-amd64"

if [ "${CHAOSD_VERSION}" = "latest" ]; then
    DOWNLOAD_URL="https://mirrors.chaos-mesh.org/chaosd-latest-linux-amd64.tar.gz"
else
    DOWNLOAD_URL="https://mirrors.chaos-mesh.org/${ARCHIVE}"
fi
SYMLINK_PATH="/usr/local/bin/chaosd"

printf '[chaosd] Target version: %s\n' "$CHAOSD_VERSION"

missing_pkgs=()
command -v curl >/dev/null 2>&1 || missing_pkgs+=("curl")
command -v tar >/dev/null 2>&1 || missing_pkgs+=("tar")

if [ ${#missing_pkgs[@]} -gt 0 ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y "${missing_pkgs[@]}"
fi

if [ ! -d "$TARGET_DIR" ]; then
    tmp_dir=$(mktemp -d)
    trap 'rm -rf "$tmp_dir"' EXIT
    curl -fsSL "$DOWNLOAD_URL" -o "$tmp_dir/$ARCHIVE"
    tar -xzf "$tmp_dir/$ARCHIVE" -C "$tmp_dir"
    mv "$tmp_dir/chaosd-$CHAOSD_VERSION-linux-amd64" "$TARGET_DIR"
else
    printf '[chaosd] Directory %s already exists, skipping download.\n' "$TARGET_DIR"
fi

ln -snf "$TARGET_DIR/chaosd" "$SYMLINK_PATH"
chmod 755 "$SYMLINK_PATH" 2>/dev/null || true
mkdir -p /var/lib/chaosd
mkdir -p /var/log/chaosd

cat >/etc/systemd/system/chaosd.service <<SERVICE
[Unit]
Description=Chaosd chaos engineering service
Documentation=https://chaos-mesh.org/docs/chaosd-overview/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${SYMLINK_PATH} server --host 0.0.0.0 --port ${CHAOSD_PORT}
Restart=on-failure
RestartSec=5
User=root
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable chaosd.service >/dev/null 2>&1 || true
systemctl restart chaosd.service

if systemctl is-active --quiet chaosd.service; then
    printf '[chaosd] Service is active on port %s.\n' "$CHAOSD_PORT"
else
    echo "[chaosd] Warning: chaosd service failed to start" >&2
    systemctl status chaosd.service --no-pager || true
    exit 1
fi
EOF
)

    remote_script=${remote_script//__CHAOSD_VERSION__/$CHAOSD_VERSION}
    remote_script=${remote_script//__CHAOSD_PORT__/$CHAOSD_PORT}

    if run_remote_root_script "$vm" "$remote_script"; then
        print_status "Chaosd installed on ${vm}"
    else
        print_error "Failed to install Chaosd on ${vm}"
        return 1
    fi
}

# Install Chaosd on all running VMs or a provided subset
chaosd_install() {
    local targets=("$@")

    if [ ${#targets[@]} -eq 0 ]; then
        while IFS= read -r vm; do
            if [[ -n "$vm" ]]; then
                targets+=("$vm")
            fi
        done < <(list_running_vms)
    fi

    if [ ${#targets[@]} -eq 0 ]; then
        print_warning "No running VMs found. Start the VMs first or pass VM names explicitly."
        return 0
    fi

    for vm in "${targets[@]}"; do
        install_chaosd_on_vm "$vm" || return 1
    done
}

# Check Chaosd service status across VMs
chaosd_status() {
    local targets=("$@")

    if [ ${#targets[@]} -eq 0 ]; then
        while IFS= read -r vm; do
            if [[ -n "$vm" ]]; then
                targets+=("$vm")
            fi
        done < <(list_running_vms)
    fi

    if [ ${#targets[@]} -eq 0 ]; then
        print_warning "No running VMs found."
        return 0
    fi

    for vm in "${targets[@]}"; do
        print_info "Checking Chaosd on ${vm}..."
        if ! vagrant_run status "$vm" --machine-readable \
            | awk -F, '$3 == "state" {print $4; exit}' \
            | grep -qx "running"; then
            print_warning "${vm} is not running; skipping"
            continue
        fi
        if vagrant_run ssh "$vm" -c "sudo systemctl is-active --quiet chaosd.service" >/dev/null 2>&1; then
            print_status "Chaosd service running on ${vm} (port ${CHAOSD_PORT})"
        else
            print_warning "Chaosd service not active on ${vm}"
        fi
    done
}

install_monitoring_stack_host() {
    print_info "Installing monitoring stack on k3s cluster..."
    if bash "${SCRIPT_ABSOLUTE_DIR}/monitoring/install.sh"; then
        print_status "Monitoring stack installed"
    else
        print_error "Monitoring stack installation failed"
        exit 1
    fi
}

install_chaos_mesh_host() {
    print_info "Installing Chaos Mesh on k3s cluster..."
    if bash "${SCRIPT_ABSOLUTE_DIR}/chaos-mesh/chaos-mesh-install" "$@"; then
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
    echo "  1. SSH into server:    vagrant ssh k3s-server"
    echo "  2. Run kubectl:        vagrant ssh k3s-server -c 'sudo kubectl get nodes'"
    echo ""
    echo "Copy kubeconfig to host:"
    echo "  vagrant ssh k3s-server -c 'sudo cat /etc/rancher/k3s/k3s.yaml' > ~/.kube/k3s-vm-config"
    echo "  # Then edit the file and change 'server: https://127.0.0.1:6443' to 'server: https://192.168.100.10:6443'"
    echo "  export KUBECONFIG=~/.kube/k3s-vm-config"
    echo ""
    echo "Management commands:"
    echo "  • Stop cluster:        vagrant halt"
    echo "  • Start cluster:       vagrant up"
    echo "  • Destroy cluster:     vagrant destroy -f"
    echo "  • SSH to worker:       vagrant ssh cloud-worker-1"
    echo ""
}

# Function to show help
show_help() {
    cat <<EOF
K3s Vagrant Cluster Setup Script

USAGE:
    $0 [COMMAND]

COMMANDS:
    setup       Setup complete cluster (network + server + workers + labels)
    network     Create/start libvirt network only
    server      Start k3s-server only
    workers     Start worker nodes only
    labels      Apply zone labels to nodes
    verify      Verify cluster status
    chaosd-install [VM...]  Install Chaosd service on all running VMs or the specified subset
    chaosd-status [VM...]   Check Chaosd service status on all running VMs or the specified subset
    monitoring-install      Install monitoring/observability stack on the cluster
    chaos-mesh-install [args]  Install Chaos Mesh (arguments are forwarded to installer)
    clean       Destroy all VMs and remove network
    help        Show this help message

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
    apply_labels
    verify_cluster
    install_monitoring_stack_host
    install_chaos_mesh_host --skip-test
    chaosd_install
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
            apply_labels
            ;;
        verify)
            verify_cluster
            ;;
        chaosd-install)
            shift || true
            bash "${SCRIPT_ABSOLUTE_DIR}/chaos-mesh/chaosd-install.sh" "$@"
            ;;
        chaosd-status)
            shift || true
            bash "${SCRIPT_ABSOLUTE_DIR}/chaos-mesh/chaosd-status.sh" "$@"
            ;;
        monitoring-install)
            install_monitoring_stack_host
            ;;
        chaos-mesh-install)
            shift || true
            install_chaos_mesh_host "$@"
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

