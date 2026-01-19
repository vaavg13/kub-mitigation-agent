"""Kubectl wrapper for Kubernetes operations."""

import json
import time
import subprocess
from typing import Optional, Dict, Any
from kubernetes import client, config
from kubernetes.client.rest import ApiException


class KubeCtl:
    """Wrapper for kubectl and Kubernetes API operations."""

    def __init__(self, context: Optional[str] = None):
        """
        Initialize KubeCtl.
        
        Args:
            context: Optional Kubernetes context to use
        """
        if context:
            config.load_kube_config(context=context)
        else:
            try:
                config.load_kube_config()
            except:
                config.load_incluster_config()
        
        self.core_v1_api = client.CoreV1Api()
        self.apps_v1_api = client.AppsV1Api()

    def exec_command(self, command: str) -> str:
        """
        Execute a shell command and return the output.
        
        Args:
            command: Shell command to execute
            
        Returns:
            Command output as string
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"Error executing command: {e}"

    def list_namespaces(self):
        """Return a list of all namespaces in the cluster."""
        return self.core_v1_api.list_namespace()

    def list_pods(self, namespace: str):
        """Return a list of all pods within a specified namespace."""
        return self.core_v1_api.list_namespaced_pod(namespace)

    def list_services(self, namespace: str):
        """Return a list of all services within a specified namespace."""
        return self.core_v1_api.list_namespaced_service(namespace)

    def create_namespace(self, namespace: str):
        """Create a namespace."""
        try:
            body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
            self.core_v1_api.create_namespace(body)
            print(f"Namespace {namespace} created successfully")
        except ApiException as e:
            if e.status == 409:
                print(f"Namespace {namespace} already exists")
            else:
                raise

    def create_namespace_if_not_exist(self, namespace: str):
        """Create namespace if it doesn't exist."""
        result = self.exec_command(f"kubectl get namespace {namespace}")
        if "NotFound" in result or "not found" in result.lower():
            self.create_namespace(namespace)
        else:
            print(f"Namespace {namespace} already exists")

    def delete_namespace(self, namespace: str):
        """Delete a namespace and all its resources."""
        try:
            print(f"Deleting namespace {namespace}...")
            self.core_v1_api.delete_namespace(namespace)
            print(f"Namespace {namespace} deleted successfully")
        except ApiException as e:
            if e.status == 404:
                print(f"Namespace {namespace} not found")
            else:
                print(f"Error deleting namespace: {e}")

    def apply_configs(self, namespace: str, config_path: str):
        """
        Apply Kubernetes configurations from a directory (recursively).
        
        Args:
            namespace: Target namespace
            config_path: Path to configuration files or directory
        """
        command = f"kubectl apply -f {config_path} -n {namespace} --recursive"
        result = self.exec_command(command)
        print(result)
        return result

    def delete_configs(self, namespace: str, config_path: str):
        """
        Delete Kubernetes configurations from a directory (recursively).
        
        Args:
            namespace: Target namespace
            config_path: Path to configuration files or directory
        """
        command = f"kubectl delete -f {config_path} -n {namespace} --recursive --ignore-not-found=true"
        result = self.exec_command(command)
        print(result)
        return result

    def wait_for_ready(self, namespace: str, sleep: int = 5, max_wait: int = 300):
        """
        Wait for all pods in a namespace to be ready.
        
        Args:
            namespace: Target namespace
            sleep: Sleep interval between checks
            max_wait: Maximum wait time in seconds
        """
        print(f"Waiting for all pods in namespace '{namespace}' to be ready...")
        
        wait = 0
        while wait < max_wait:
            try:
                pod_list = self.list_pods(namespace)
                
                if not pod_list.items:
                    print(f"No pods found yet in {namespace}. Waiting...")
                    time.sleep(sleep)
                    wait += sleep
                    continue
                
                ready_pods = [
                    pod for pod in pod_list.items
                    if pod.status.container_statuses and
                    all(cs.ready for cs in pod.status.container_statuses)
                ]
                
                total_pods = len(pod_list.items)
                ready_count = len(ready_pods)
                
                print(f"Pods ready: {ready_count}/{total_pods}")
                
                if ready_count == total_pods:
                    print(f"All pods in namespace '{namespace}' are ready!")
                    return True
                
                time.sleep(sleep)
                wait += sleep
                
            except Exception as e:
                print(f"Error checking pod status: {e}")
                time.sleep(sleep)
                wait += sleep
        
        print(f"Timeout waiting for pods in namespace '{namespace}'")
        return False

    def create_or_update_configmap(
        self,
        name: str,
        namespace: str,
        data: Dict[str, str]
    ):
        """
        Create or update a ConfigMap.
        
        Args:
            name: ConfigMap name
            namespace: Target namespace
            data: Dictionary of key-value pairs for the ConfigMap
        """
        body = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=name),
            data=data
        )
        
        try:
            self.core_v1_api.replace_namespaced_config_map(name, namespace, body)
            print(f"ConfigMap {name} updated in namespace {namespace}")
        except ApiException as e:
            if e.status == 404:
                self.core_v1_api.create_namespaced_config_map(namespace, body)
                print(f"ConfigMap {name} created in namespace {namespace}")
            else:
                raise

    def get_node_architectures(self):
        """Get the architectures of all nodes in the cluster."""
        nodes = self.core_v1_api.list_node()
        architectures = set()
        for node in nodes.items:
            arch = node.status.node_info.architecture
            architectures.add(arch)
        return list(architectures)

    def get_deployment(self, name: str, namespace: str):
        """Fetch the deployment configuration."""
        return self.apps_v1_api.read_namespaced_deployment(name, namespace)
