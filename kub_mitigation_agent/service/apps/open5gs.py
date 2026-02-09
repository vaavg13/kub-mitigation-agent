"""Open5GS 5G Core application class with deployment logic."""

import time
from .base import Application
from ..kubectl import KubeCtl
from ..helm import Helm
from ...paths import OPEN5GS_METADATA


class Open5GS(Application):
    """
    Open5GS 5G Core application.
    
    Provides deployment, cleanup, and management for the Open5GS 5G Core
    network functions including AMF, SMF, UPF, NRF, and other components.
    """
    
    def __init__(self):
        """Initialize Open5GS application."""
        super().__init__(OPEN5GS_METADATA)
        self.kubectl = KubeCtl()
        
        self.load_app_json()
        self.create_namespace()
    
    def load_app_json(self):
        """Load application-specific metadata."""
        super().load_app_json()
        metadata = self.get_app_json()
        
        # Load 5G-specific configuration
        self.fiveg_config = metadata.get("5g_config", {})
        self.mcc = self.fiveg_config.get("mcc", "999")
        self.mnc = self.fiveg_config.get("mnc", "70")
        self.sst = self.fiveg_config.get("sst", 1)
        self.sd = self.fiveg_config.get("sd", "0x111111")
        self.tac = self.fiveg_config.get("tac", "0001")
        self.amf_hostname = self.fiveg_config.get("amf_hostname", "open5gs-amf-ngap")
        
        # Load UERANSIM configuration
        self.ueransim_config = self.workload_config.get("ueransim_config", {})
        
        # Fix Helm values file paths to be absolute
        from ...paths import OPEN5GS_CORE_VALUES, OPEN5GS_UES_VALUES
        if "extra_args" in self.helm_configs:
            # Replace relative paths with absolute paths
            extra_args = []
            for arg in self.helm_configs["extra_args"]:
                if "open5gs_core_values.yaml" in arg:
                    extra_args.append(str(OPEN5GS_CORE_VALUES))
                elif "open5gs_ues_values.yaml" in arg:
                    extra_args.append(str(OPEN5GS_UES_VALUES))
                else:
                    extra_args.append(arg)
            self.helm_configs["extra_args"] = extra_args
    
    def deploy(self):
        """Deploy the Open5GS 5G Core using Helm."""
        self.deploy_helm()
    
    def deploy_helm(self):
        """Deploy using Helm chart with remote OCI registry."""
        print(f"Deploying Open5GS 5G Core with Helm in namespace: {self.namespace}")
        
        # Ensure namespace exists (without Istio injection for 5G)
        self.create_namespace()
        
        # Install Open5GS core
        Helm.install(**self.helm_configs)
        Helm.assert_if_deployed(self.helm_configs["namespace"])
        
        print("Open5GS 5G Core deployed successfully")
    
    def deploy_ueransim(self):
        """Deploy UERANSIM gNB and UEs for traffic generation."""
        if not self.ueransim_config:
            print("UERANSIM configuration not found. Skipping deployment.")
            return
        
        print(f"Deploying UERANSIM in namespace: {self.namespace}")
        
        # Add values file for UERANSIM
        from ...paths import OPEN5GS_UES_VALUES
        ueransim_config = self.ueransim_config.copy()
        ueransim_config["extra_args"] = ["--values", str(OPEN5GS_UES_VALUES)]
        
        # Install UERANSIM
        Helm.install(**ueransim_config)
        
        print("UERANSIM deployed successfully")
    
    def delete(self):
        """Delete the Open5GS application (Helm)."""
        self.delete_helm()
    
    def delete_helm(self):
        """Delete the Helm deployment."""
        # Uninstall UERANSIM if it exists
        if self.ueransim_config:
            try:
                print("Uninstalling UERANSIM...")
                Helm.uninstall(**self.ueransim_config)
            except Exception as e:
                print(f"UERANSIM uninstall warning: {e}")
        
        # Uninstall Open5GS core
        Helm.uninstall(**self.helm_configs)
    
    def cleanup(self):
        """Delete the entire namespace for the Open5GS application."""
        print(f"Cleaning up Open5GS namespace: {self.namespace}")
        
        self.kubectl.delete_namespace(self.namespace)
        time.sleep(10)
        
        # Clean up persistent volumes
        pvs = self.kubectl.exec_command(
            f"kubectl get pv --no-headers | grep '{self.namespace}' | awk '{{print $1}}'"
        ).splitlines()

        for pv in pvs:
            if pv.strip():
                # Remove finalizers if PV is stuck in Terminating state
                self._remove_pv_finalizers(pv)
                delete_command = f"kubectl delete pv {pv}"
                delete_result = self.kubectl.exec_command(delete_command)
                print(f"Deleted PersistentVolume {pv}: {delete_result.strip()}")
        
        time.sleep(5)
        print("Open5GS cleanup completed")
    
    def _remove_pv_finalizers(self, pv_name: str):
        """Remove finalizers from PersistentVolume to prevent stuck Terminating state."""
        patch_command = (
            f'kubectl patch pv {pv_name} -p \'{{"metadata":{{"finalizers":null}}}}\''
        )
        _ = self.kubectl.exec_command(patch_command)
    
    def is_deployed(self) -> bool:
        """
        Check if the Open5GS application is currently deployed.
        
        Returns:
            bool: True if deployed and running
        """
        try:
            pods = self.kubectl.list_pods(self.namespace)
            return len(pods.items) > 0
        except:
            return False
    
    def get_services(self) -> list:
        """
        Get list of services in the Open5GS application.
        
        Returns:
            List of service names
        """
        try:
            services = self.kubectl.list_services(self.namespace)
            return [svc.metadata.name for svc in services.items]
        except:
            return []
    
    def get_core_functions(self) -> list:
        """
        Get list of 5G Core Network Functions.
        
        Returns:
            List of core network function names (AMF, SMF, UPF, etc.)
        """
        app_json = self.get_app_json()
        return app_json.get("Critical Services", [])
    
    def execute_ueransim_command(self, command: str) -> str:
        """
        Execute a command in the UERANSIM pod using nr-cli.
        
        Args:
            command: Command to execute (e.g., "nr-cli -d")
        
        Returns:
            Command output
        """
        # Find UERANSIM pod
        pods = self.kubectl.list_pods(self.namespace)
        ueransim_pod = None
        
        for pod in pods.items:
            if "ueransim" in pod.metadata.name.lower():
                ueransim_pod = pod.metadata.name
                break
        
        if not ueransim_pod:
            return "UERANSIM pod not found"
        
        # Execute command
        exec_command = f"kubectl exec -n {self.namespace} {ueransim_pod} -- {command}"
        result = self.kubectl.exec_command(exec_command)
        
        return result
    
    def list_ues(self) -> str:
        """
        List all UEs currently running in UERANSIM.
        
        Returns:
            Output from nr-cli -d command
        """
        return self.execute_ueransim_command("nr-cli -d")
    
    def establish_pdu_session(self, imsi: str, sst: int = 1, sd: str = "1", dnn: str = "internet") -> str:
        """
        Establish a PDU session for a specific UE.
        
        Args:
            imsi: UE IMSI (e.g., "imsi-999700000000001")
            sst: Slice Service Type (default: 1)
            sd: Slice Differentiator (default: "1")
            dnn: Data Network Name (default: "internet")
        
        Returns:
            Command output
        """
        command = f'nr-cli {imsi} -e "ps-establish IPv4 --sst {sst} --sd {sd} --dnn {dnn}"'
        return self.execute_ueransim_command(command)
    
    def release_pdu_session(self, imsi: str, session_id: int = 1) -> str:
        """
        Release a PDU session for a specific UE.
        
        Args:
            imsi: UE IMSI (e.g., "imsi-999700000000001")
            session_id: PDU session ID (default: 1)
        
        Returns:
            Command output
        """
        command = f'nr-cli {imsi} -e "ps-release {session_id}"'
        return self.execute_ueransim_command(command)
    
    def __repr__(self) -> str:
        return f"Open5GS(namespace={self.namespace}, mcc={self.mcc}, mnc={self.mnc})"
