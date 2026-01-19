"""Helm wrapper for Helm operations."""

import subprocess
from typing import Optional, List, Dict
from .kubectl import KubeCtl


class Helm:
    """Wrapper for Helm operations."""

    @staticmethod
    def install(**args):
        """
        Install a Helm chart.
        
        Args:
            release_name (str): Name of the release
            chart_path (str): Path to the helm chart
            namespace (str): Namespace to install the chart
            version (str): Optional version of the chart
            extra_args (List[str]): Extra arguments for the helm install command
            remote_chart (bool): Whether the chart is remote (from a Helm repo)
        """
        print("== Helm Install ==")
        release_name = args.get("release_name")
        chart_path = args.get("chart_path")
        namespace = args.get("namespace")
        version = args.get("version")
        extra_args = args.get("extra_args", [])
        remote_chart = args.get("remote_chart", False)

        if not remote_chart:
            # Install dependencies for chart before installation
            dependency_command = f"helm dependency update {chart_path}"
            print(f"Updating dependencies: {dependency_command}")
            dependency_process = subprocess.Popen(
                dependency_command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            dependency_output, dependency_error = dependency_process.communicate()
            if dependency_error:
                print(f"Dependency update stderr: {dependency_error.decode('utf-8')}")

        command = f"helm install {release_name} {chart_path} -n {namespace} --create-namespace"

        if version:
            command += f" --version {version}"

        if extra_args:
            command += " " + " ".join(extra_args)

        print(f"Running: {command}")
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()

        if error:
            print(error.decode("utf-8"))
        if output:
            print(output.decode("utf-8"))

    @staticmethod
    def uninstall(**args):
        """
        Uninstall a Helm chart.
        
        Args:
            release_name (str): Name of the release
            namespace (str): Namespace to uninstall the chart
        """
        print("== Helm Uninstall ==")
        release_name = args.get("release_name")
        namespace = args.get("namespace")

        if not Helm.exists_release(release_name, namespace):
            print(f"Release {release_name} does not exist. Skipping uninstall.")
            return

        command = f"helm uninstall {release_name} -n {namespace}"
        print(f"Running: {command}")
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()

        if error:
            print(error.decode("utf-8"))
        if output:
            print(output.decode("utf-8"))

    @staticmethod
    def exists_release(release_name: str, namespace: str) -> bool:
        """
        Check if a Helm release exists.
        
        Args:
            release_name (str): Name of the release
            namespace (str): Namespace to check
            
        Returns:
            bool: True if release exists
        """
        command = f"helm list -n {namespace}"
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()

        if error:
            print(error.decode("utf-8"))
            return False
        else:
            return release_name in output.decode("utf-8")

    @staticmethod
    def add_repo(repo_name: str, repo_url: str):
        """
        Add a Helm repository.
        
        Args:
            repo_name (str): Name of the repository
            repo_url (str): URL of the repository
        """
        command = f"helm repo add {repo_name} {repo_url}"
        print(f"Running: {command}")
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = process.communicate()

        if error:
            print(error.decode("utf-8"))
        if output:
            print(output.decode("utf-8"))

        # Update repos after adding
        update_command = "helm repo update"
        subprocess.run(update_command, shell=True, capture_output=True)

    @staticmethod
    def assert_if_deployed(namespace: str):
        """
        Assert if all services in the application are deployed.
        
        Args:
            namespace (str): Namespace to check
            
        Returns:
            bool: True if deployed
            
        Raises:
            Exception: If not deployed
        """
        kubectl = KubeCtl()
        try:
            kubectl.wait_for_ready(namespace)
        except Exception as e:
            raise e

        return True
