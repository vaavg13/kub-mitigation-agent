#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Absolute path to the script's directory
SCRIPT_ABSOLUTE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to check if a command exists
check_command() {
    if ! command -v $1 &> /dev/null; then
        print_error "$1 is not installed. Please install it first."
        exit 1
    fi
}

# Function to get config value from YAML
get_config() {
    yq eval ".$1" "$SCRIPT_ABSOLUTE_DIR/default.yaml"
}

# Function to install required dependencies
install_dependencies() {
    print_status "Installing required dependencies..."
    
    # Check and install Python dependencies
    # pip3 install -q -r requirements.txt
    
    # Install yq if not available
    if ! command -v yq &> /dev/null; then
        print_status "Installing yq..."
        wget -qO /tmp/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
        chmod +x /tmp/yq
        sudo mv /tmp/yq /usr/local/bin/
    fi

    # Install jq if not available
    if ! command -v jq &> /dev/null; then
        print_status "Installing jq..."
        if command -v apt-get &> /dev/null; then
            sudo apt-get update -y && sudo apt-get install -y jq
        elif command -v yum &> /dev/null; then
            sudo yum install -y jq
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y jq
        else
            print_error "Could not find apt-get, yum, or dnf to install jq. Please install jq manually."
            exit 1
        fi
    fi
    
    # Ensure wget and curl are available (used by installers)
    if ! command -v wget &> /dev/null; then
        print_status "Installing wget..."
        if command -v apt-get &> /dev/null; then
            sudo apt-get update -y && sudo apt-get install -y wget
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y wget
        elif command -v yum &> /dev/null; then
            sudo yum install -y wget
        fi
    fi
    if ! command -v curl &> /dev/null; then
        print_status "Installing curl..."
        if command -v apt-get &> /dev/null; then
            sudo apt-get update -y && sudo apt-get install -y curl ca-certificates gnupg
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y curl ca-certificates gnupg2
        elif command -v yum &> /dev/null; then
            sudo yum install -y curl ca-certificates gnupg2
        fi
    fi
    
    print_status "Dependencies installed successfully"
}

# Install Helm v3
install_helm() {
    if command -v helm &> /dev/null; then
        print_status "Helm is already installed"
        return 0
    fi
    print_status "Installing Helm..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    print_status "Helm installed"
}
# Function to install K3D
install_k3d() {
    print_status "Installing K3D..."
    
    if ! command -v k3d &> /dev/null; then
        # Get K3D install script from config
        K3D_INSTALL_SCRIPT=$(get_config 'k3d.install_script')
        
        # Install K3D
        wget -q -O - $K3D_INSTALL_SCRIPT | bash
    else
        print_status "K3D is already installed"
    fi
    
    print_status "K3D installed successfully"
}

# Function to create K3D cluster with specified number of agents
create_k3d_cluster() {
    print_status "Creating K3D cluster..."

    # Get cluster name from config
    CLUSTER_NAME=$(get_config 'k3d.cluster_name')
    TOTAL_AGENTS=$(jq '. | length' "$SCRIPT_ABSOLUTE_DIR/nodes.json")

    # Check if cluster already exists
    if k3d cluster list | grep -q "^$CLUSTER_NAME"; then
        print_warning "Cluster '$CLUSTER_NAME' already exists"
        read -p "Do you want to delete the existing cluster and create a new one? (y/n): " confirm
        if [[ $confirm == [yY] ]]; then
            print_status "Deleting existing cluster..."
            k3d cluster delete "$CLUSTER_NAME"
        else
            print_status "Using existing cluster"
            return 0
        fi
    fi
    
    # Create the cluster with specified number of agents
    # Read host port configuration from config
    PROMETHEUS_HOST_PORT=$(get_config 'k3d.host_ports.prometheus')
    GRAFANA_HOST_PORT=$(get_config 'k3d.host_ports.grafana')
    MUBENCH_SERVICE_PORT=$(get_config 'k3d.host_ports.mubench_service')
    KIALI_HOST_PORT=$(get_config 'k3d.host_ports.kiali')
    
    k3d cluster create "$CLUSTER_NAME" \
        --agents "$TOTAL_AGENTS" \
        --k3s-arg "--disable=traefik@server:*" \
        --k3s-arg "--disable=metrics-server@server:*" \
        -p "${PROMETHEUS_HOST_PORT}:30000@loadbalancer" \
        -p "${GRAFANA_HOST_PORT}:30001@loadbalancer" \
        -p "${MUBENCH_SERVICE_PORT}:31113@loadbalancer" \
        -p "${KIALI_HOST_PORT}:30003@loadbalancer" \
        --runtime-label "com.docker.compose.project=cec_emulator@all"

    if [ $? -ne 0 ]; then
        print_error "Failed to create K3D cluster"
        exit 1
    fi

    print_status "K3D cluster created successfully with $TOTAL_AGENTS agents"
}

# Function to apply resource limits to nodes
apply_node_resource_limits() {
    print_status "Applying resource limits to nodes..."

    CLUSTER_NAME=$(get_config 'k3d.cluster_name')
    TOTAL_AGENTS=$(jq '. | length' "$SCRIPT_ABSOLUTE_DIR/nodes.json")

    # Apply limits to each node based on the configuration list
    for i in $(seq 0 $((TOTAL_AGENTS-1))); do
        NODE_MEM_GB_RAW=$(jq -r ".[${i}].memory_capacity_gb" "$SCRIPT_ABSOLUTE_DIR/nodes.json")
        NODE_CPUSET=$(jq -r ".[${i}].cpuset_cpus // empty" "$SCRIPT_ABSOLUTE_DIR/nodes.json")
        
        # Ensure NODE_MEM_GB_RAW is treated as a number for arithmetic
        NODE_MEM_GB=$(echo "$NODE_MEM_GB_RAW" | awk '{print int($1)}')
        NODE_MEM_MB=$((NODE_MEM_GB * 1024))

        CONTAINER_NAME="k3d-${CLUSTER_NAME}-agent-$i"
        if [ -n "$NODE_CPUSET" ]; then
            print_status "Applying resource limits to node $i (container: ${CONTAINER_NAME}): cpuset [$NODE_CPUSET], ${NODE_MEM_MB}MB memory..."
            
            # Set memory and memory-swap together to avoid the error
            docker update --cpuset-cpus "$NODE_CPUSET" \
                         --memory="${NODE_MEM_MB}m" \
                         --memory-swap="${NODE_MEM_MB}m" \
                         "$CONTAINER_NAME"
        else
            print_status "Applying resource limits to node $i (container: ${CONTAINER_NAME}): ${NODE_MEM_MB}MB memory..."
            
            # Set memory and memory-swap together to avoid the error
            docker update --memory="${NODE_MEM_MB}m" \
                         --memory-swap="${NODE_MEM_MB}m" \
                         "$CONTAINER_NAME"
        fi
    done

    print_status "Resource limits applied successfully"
}

# Function to apply labels to nodes
apply_node_labels() {
    print_status "Applying labels to nodes..."

    CLUSTER_NAME=$(get_config 'k3d.cluster_name')
    TOTAL_AGENTS=$(jq '. | length' "$SCRIPT_ABSOLUTE_DIR/nodes.json")

    # Apply labels to each node based on the configuration list
    for i in $(seq 0 $((TOTAL_AGENTS-1))); do
        NODE_K8S_NAME="k3d-${CLUSTER_NAME}-agent-$i"
        NODE_ZONE=$(jq -r ".[${i}].zone" "$SCRIPT_ABSOLUTE_DIR/nodes.json")
        
        print_status "Applying label topology.kubernetes.io/zone=${NODE_ZONE} to node $i (k8s_name: $NODE_K8S_NAME)..."
        kubectl label node "$NODE_K8S_NAME" "topology.kubernetes.io/zone=${NODE_ZONE}" --overwrite
    done

    print_status "Labels applied successfully"
}

# Function to apply taint to the control-plane node
apply_control_plane_taint() {
    # print_status "Applying taint to control-plane node..." # Reduced verbosity
    CLUSTER_NAME=$(get_config 'k3d.cluster_name')
    CONTROL_PLANE_NODE_NAME="k3d-${CLUSTER_NAME}-server-0" # Standard k3d naming
    
    # print_status "Waiting for control-plane node '$CONTROL_PLANE_NODE_NAME' to be ready..." # Reduced verbosity
    if ! kubectl wait --for=condition=Ready node/"$CONTROL_PLANE_NODE_NAME" --timeout=120s > /dev/null 2>&1; then # Silenced kubectl wait output
        print_error "Control-plane node '$CONTROL_PLANE_NODE_NAME' did not become ready in time or was not found."
        print_error "Skipping control-plane taint application."
        return 1
    fi

    # print_status "Tainting node '$CONTROL_PLANE_NODE_NAME' with 'node-role.kubernetes.io/control-plane=true:NoSchedule'..." # Reduced verbosity
    if kubectl taint node "$CONTROL_PLANE_NODE_NAME" node-role.kubernetes.io/control-plane=true:NoSchedule --overwrite > /dev/null 2>&1; then # Silenced kubectl taint output
        print_status "Taint applied successfully to $CONTROL_PLANE_NODE_NAME."
    else
        print_error "Failed to apply taint to $CONTROL_PLANE_NODE_NAME."
        return 1
    fi
    return 0
}

# Function to install monitoring if enabled in config
install_monitoring_if_enabled() {
    MONITORING_ENABLED=$(get_config 'monitoring.install')
    if [[ "$MONITORING_ENABLED" == "true" ]]; then
        print_status "Monitoring installation enabled in config. Installing monitoring..."
        bash "$SCRIPT_ABSOLUTE_DIR/monitoring/install_monitoring.sh"
        if [ $? -ne 0 ]; then
            print_error "Failed to install monitoring."
            exit 1
        fi
        print_status "Monitoring installed successfully."
    else
        print_status "Monitoring installation is disabled in config. Skipping monitoring setup."
    fi
}

# Function to clean existing environment (migrated from clean_install.sh)
clean_environment() {
    print_status "Cleaning existing environment..."
    CLUSTER_NAME=$(get_config 'k3d.cluster_name')
    # Delete K3D cluster if it exists
    if k3d cluster list | grep -q "^$CLUSTER_NAME"; then
        print_status "Deleting existing K3D cluster..."
        k3d cluster delete "$CLUSTER_NAME"
    fi
    print_status "Environment cleaned successfully"
}

# Function to setup the environment
setup() {  
    # Ask if user wants to clean existing environment if cluster exists
    CLUSTER_NAME=$(get_config 'k3d.cluster_name')
    if k3d cluster list | grep -q "^$CLUSTER_NAME"; then
        print_warning "Cluster '$CLUSTER_NAME' already exists."
        read -p "Do you want to clean the existing environment before setup? (y/n): " clean_confirm
        if [[ $clean_confirm == [yY] ]]; then
            clean_environment
        else
            print_status "Skipping environment cleaning. Proceeding with setup."
        fi
    fi

    print_status "Starting environment setup..."
    print_status "The following steps will be performed:"
    print_status "1. Clean existing environment (if requested)"
    print_status "2. Install base tools (yq, jq, curl, wget)"
    print_status "3. Verify prerequisites (Docker, kubectl)"
    print_status "4. Install Helm (if missing)"
    print_status "5. Install K3D (if missing)"
    print_status "6. Create K3D cluster with specified number of agents"
    print_status "7. Apply resource limits to nodes"
    print_status "8. Apply labels to nodes"
    
    read -p "Do you want to proceed with the setup? (y/n): " confirm
    if [[ $confirm != [yY] ]]; then
        print_status "Setup cancelled."
        exit 0
    fi
    
    # Install base dependencies and runtime tooling
    install_dependencies

    # Verify prerequisites
    print_status "Verifying prerequisites (Docker, kubectl)..."
    check_command "docker"
    # Ensure current user can access Docker daemon (k3d requires non-sudo Docker access)
    if ! docker info > /dev/null 2>&1; then
        if sudo -n docker info > /dev/null 2>&1; then
            print_error "Docker works only with sudo for this user. k3d needs Docker access without sudo. Add your user to the 'docker' group and re-login: sudo usermod -aG docker $USER"
        else
            print_error "Docker daemon not reachable. Ensure the Docker service is running."
        fi
        exit 1
    fi
    check_command "kubectl"

    # Install Helm if missing and verify tools
    install_helm
    check_command "helm"
    check_command "yq"
    
    # Install K3D
    install_k3d
    
    # Create K3D cluster
    create_k3d_cluster
    
    # Apply resource limits to nodes
    apply_node_resource_limits
    
    # Apply labels to nodes
    apply_node_labels
    
    # Apply taint to control-plane node
    apply_control_plane_taint
    
    # Install monitoring if enabled
    install_monitoring_if_enabled
    
    print_status "Environment setup completed successfully"
    # print_status "To set up MuBench, run: ./workloads/setup_mubench.sh"
}

# Main execution
main() {
    if [ $# -eq 0 ]; then
        setup
        exit 0
    fi
    
    case "$1" in
        "clean")
            clean_environment
            ;;
        "help"|"-h"|"--help")
            echo "Usage: $0 [command]"
            echo "Commands:"
            echo "  (no arguments)  - Run complete setup with confirmation (asks before cleaning if infra exists)"
            echo "  clean           - Clean existing environment (delete cluster)"
            echo "  help            - Show this help message"
            ;;
        *)
            print_error "Unknown command: $1"
            echo "Usage: $0 [command]"
            echo "Use '$0 help' for more information"
            exit 1
            ;;
    esac
}

# Execute main function with all arguments
main "$@" 