#!/bin/bash

# Chaos Mesh Installation Script for k3s
# Based on: https://chaos-mesh.org/docs/production-installation-using-helm/

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration for k3s
NAMESPACE="chaos-mesh"
RELEASE_NAME="chaos-mesh"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        print_error "$1 is not installed or not in PATH"
        return 1
    fi
    return 0
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    # Check if kubectl is available
    if ! check_command "kubectl"; then
        print_error "kubectl is required but not found"
        exit 1
    fi
    
    # Check if helm is available
    if ! check_command "helm"; then
        print_error "helm is required but not found"
        exit 1
    fi
    
    # Check helm version
    print_status "Checking Helm version..."
    helm version
    
    # Check kubectl connection to cluster
    print_status "Checking Kubernetes cluster connection..."
    if ! kubectl cluster-info &> /dev/null; then
        print_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    print_success "Prerequisites check passed"
}

# Function to add Chaos Mesh repository
add_chaos_mesh_repo() {
    print_status "Adding Chaos Mesh repository..."
    
    if helm repo list | grep -q "chaos-mesh"; then
        print_warning "Chaos Mesh repository already exists, updating..."
        helm repo update chaos-mesh
    else
        helm repo add chaos-mesh https://charts.chaos-mesh.org
        helm repo update
    fi
    
    print_success "Chaos Mesh repository added successfully"
}

# Function to create namespace
create_namespace() {
    print_status "Creating namespace: $NAMESPACE"
    
    if kubectl get namespace "$NAMESPACE" &> /dev/null; then
        print_warning "Namespace $NAMESPACE already exists"
    else
        kubectl create namespace "$NAMESPACE"
        print_success "Namespace $NAMESPACE created successfully"
    fi
}

# Function to install Chaos Mesh for k3s
install_chaos_mesh() {
    print_status "Installing Chaos Mesh for k3s..."
    
    helm install $RELEASE_NAME chaos-mesh/chaos-mesh -n=$NAMESPACE \
        --set chaosDaemon.runtime=containerd \
        --set chaosDaemon.socketPath=/run/k3s/containerd/containerd.sock \
        --set controllerManager.replicaCount=1 \
        --set controllerManager.tolerations[0].key=node-role.kubernetes.io/control-plane \
        --set controllerManager.tolerations[0].operator=Exists \
        --set controllerManager.tolerations[0].effect=NoSchedule
    
    print_success "Chaos Mesh installation completed"
}

# Function to verify installation
verify_installation() {
    print_status "Verifying Chaos Mesh installation..."
    
    # Wait for pods to be ready (max 5 minutes)
    print_status "Waiting for Chaos Mesh pods to be ready (timeout: 5 minutes)..."
    if kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance=chaos-mesh -n $NAMESPACE --timeout=300s; then
        print_success "All Chaos Mesh pods are ready"
    else
        print_warning "Some pods may not be ready yet, continuing with verification..."
    fi
    
    # Check pod status
    print_status "Chaos Mesh pod status:"
    kubectl get pods -n $NAMESPACE -l app.kubernetes.io/instance=chaos-mesh
    
    # Check services
    print_status "Chaos Mesh services:"
    kubectl get services -n $NAMESPACE
    
    # Check if dashboard is accessible
    print_status "Checking dashboard service..."
    if kubectl get service chaos-dashboard -n $NAMESPACE &> /dev/null; then
        DASHBOARD_PORT=$(kubectl get service chaos-dashboard -n $NAMESPACE -o jsonpath='{.spec.ports[0].port}')
        print_success "Chaos Dashboard is available on port $DASHBOARD_PORT"
        print_status "To access dashboard locally, run:"
        print_status "kubectl port-forward -n $NAMESPACE service/chaos-dashboard $DASHBOARD_PORT:$DASHBOARD_PORT"
    fi
}

# Function to run basic chaos experiment test
run_basic_test() {
    print_status "Creating a basic pod-kill chaos experiment for testing..."
    
    # Create a test deployment first
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: chaos-test-app
  namespace: default
spec:
  replicas: 3
  selector:
    matchLabels:
      app: chaos-test
  template:
    metadata:
      labels:
        app: chaos-test
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
EOF

    # Wait for test deployment to be ready
    print_status "Waiting for test deployment to be ready..."
    kubectl wait --for=condition=available deployment/chaos-test-app --timeout=120s
    
    # Create chaos experiment
    cat <<EOF | kubectl apply -f -
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: test-pod-kill
  namespace: default
spec:
  action: pod-kill
  mode: one
  selector:
    labelSelectors:
      app: chaos-test
  duration: "30s"
EOF

    print_success "Basic chaos experiment created: test-pod-kill"
    print_status "Monitoring experiment for 45 seconds..."
    
    # Wait and show experiment status
    sleep 10
    kubectl get podchaos test-pod-kill -n default
    
    # Clean up
    sleep 35
    print_status "Cleaning up test resources..."
    kubectl delete podchaos test-pod-kill -n default --ignore-not-found=true
    kubectl delete deployment chaos-test-app -n default --ignore-not-found=true
    
    print_success "Basic test completed successfully"
}

# Function to show useful commands
show_useful_commands() {
    print_status "Useful Chaos Mesh commands:"
    echo "  # View chaos experiments:"
    echo "  kubectl get podchaos,networkchaos,stresschaos --all-namespaces"
    echo ""
    echo "  # Access dashboard:"
    echo "  kubectl port-forward -n $NAMESPACE service/chaos-dashboard 2333:2333"
    echo "  # Then open: http://localhost:2333"
    echo ""
    echo "  # Uninstall:"
    echo "  helm uninstall $RELEASE_NAME -n $NAMESPACE"
}

# Main installation function
main() {
    print_status "Starting Chaos Mesh installation for k3s..."
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --namespace)
                NAMESPACE="$2"
                shift 2
                ;;
            --skip-test)
                SKIP_TEST=true
                shift
                ;;
            --help)
                echo "Usage: $0 [options]"
                echo "Options:"
                echo "  --namespace NAME     Kubernetes namespace (default: chaos-mesh)"
                echo "  --skip-test          Skip running the basic chaos experiment test"
                echo "  --help               Show this help message"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done
    
    check_prerequisites
    add_chaos_mesh_repo
    create_namespace
    install_chaos_mesh
    verify_installation
    
    if [[ "$SKIP_TEST" != true ]]; then
        run_basic_test
    fi
    
    show_useful_commands
    
    print_success "Chaos Mesh installation completed successfully!"
    print_status "Dashboard URL: http://localhost:2333 (after port-forward)"
}

# Run main function
main "$@" 