## Fast Reset Strategy (No Namespace Deletion)

### Investigation Findings

**Confirmed Leakage Point:** ChaosMesh CRDs live in the application namespace
- Active example: `stresschaos/cpu-stress-node-k3d-cec-emulator-agent-5-extreme` in `app-iot-gateway` namespace
- Current cleanup (`cleanup_chaos_experiment`) deletes by name, but can fail silently or be skipped on crashes
- If chaos CRDs persist between experiments, they continue affecting pods

**Environment Characteristics:**
- Stateless microservices (no PVCs, no persistent data)
- Deployments with HPA autoscalers
- Istio sidecars injected
- No StatefulSets, Jobs, or DaemonSets in typical apps

**Confidence Level: 95%** for fast reset success

### Implementation Plan

**Fast Reset Steps (alternative to namespace deletion):**
1. **Delete ALL ChaosMesh CRDs** in namespace (guaranteed chaos cleanup):
   ```bash
   kubectl delete stresschaos,podchaos,networkchaos,iochaos,httpchaos --all -n {namespace} --ignore-not-found=true
   ```
2. **Reset Docker constraints** on all nodes:
   ```python
   reset_scheduling_policies(docker_handler)
   ```
3. **Re-apply application YAMLs**:
   ```python
   K8sDeploymentManager.from_deployment_dir(app_dir).deploy()
   ```
4. **Restart all deployments** (fresh pods):
   ```bash
   kubectl rollout restart deployment --all -n {namespace}
   ```
5. **Wait for pod readiness**:
   ```python
   wait_for_pods_ready_sync(namespace, timeout)
   ```

**Ownership:** `BatchChaosExperiment.run_single_experiment` - add branch before Step 1 (deployment)

**Benefits:**
- Saves ~15-30 seconds per experiment (namespace deletion + wait time)
- Guaranteed chaos cleanup even if previous experiment failed
- Keeps namespace and reduces API server load
- Works with existing app architecture

**Critical Addition vs Original Todo:**
- Step 1 must delete ALL chaos CRDs (wildcard) instead of relying on experiment-level cleanup
- This handles the case where cleanup_chaos_experiment() failed or was skipped

---


## Deployment Misconfiguration Chaos Injection Family

### Investigation Findings

**Current Deployment Management:**
- **Deployment Source:** YAML files in `APPS/{app-name}/yamls/` directory
  - Example: `mubench-00030-Deployment-iot-device-gateway-edge-site-1.yaml`
  - Contains: replicas, resources (cpu/memory), affinity, volumes, env vars
  - These represent **ideal configuration for normal traffic**
  - Managed by external `mu_bench.deployers.manager.K8sDeploymentManager`
- **Available kubectl Tools:** Already available via MCP server
  - `kubectl_patch`: Modify deployment specs in-place (strategic/merge/json patch)
  - `kubectl_get`: Retrieve current deployment specs (ideal state)
  - `kubectl_scale`: Change replica count
- **Current Resources:** Example deployment has `requests: {cpu: 30m, memory: 128Mi}` (ideal baseline)
- **HPA Integration:** Apps have HorizontalPodAutoscalers (HPA) that respond to misconfigurations

**Key Discovery:** Deployed YAMLs represent the **ideal configuration**. Using `kubectl get` to capture current state, then `kubectl patch` to reduce/misconfigure from that ideal baseline. Cleanup patches back to original ideal values.

**Key Insight:** No hardcoded misconfiguration values needed - just apply **percentage-based reductions** from whatever the ideal configuration is (e.g., reduce CPU by 80%, reduce replicas to 0).

**Confidence Level: 98%** - Simpler than anticipated, leverages ideal baseline already deployed

### Implementation Plan

**New Chaos Family: Deployment Misconfiguration Injections**

**1. Create Deployment Misconfiguration Handler** (~120 lines, NEW FILE)
   - **File:** `kub_mitigation_agent/anomalies/deployment_misconfig_handler.py`
   - **Pattern:** Similar to `DockerConstraintsHandler` but uses kubectl instead of docker commands
   - **Key Concept:** Reduce from ideal configuration (not hardcoded values)
   - **Key methods:**
     ```python
     class DeploymentMisconfigHandler:
         def __init__(self, config: Dict[str, Any]):
             self.namespace = config["namespace"]
             self.original_specs = {}  # Store ideal state backups
         
         def _get_current_spec(self, deployment_name: str) -> Dict[str, Any]:
             # kubectl get deployment {name} -n {namespace} -o json
             # Returns current ideal configuration
         
         def _generate_reduction_patch(self, current_spec: Dict, fault_type: str, intensity: str) -> List[Dict]:
             # Extract current ideal values (e.g., cpu: 30m, memory: 128Mi, replicas: 1)
             # Generate patch that reduces from these values based on fault_type and intensity
             # Example: cpu_underprovision extreme = reduce to 5m (83% reduction from 30m)
         
         def inject_deployment_misconfig_only(self, config: Dict[str, Any]) -> Dict[str, Any]:
             # 1. Select target deployment (from available_deployments or random)
             # 2. Get current ideal spec and backup
             # 3. Generate reduction patch based on fault_type and intensity
             # 4. Apply patch via kubectl
             # 5. Return experiment record with "deployment_misconfig": True flag
         
         def cleanup_deployment_misconfig(self, experiment_config: Dict[str, Any]) -> bool:
             # Extract original ideal values from backup
             # Generate restore patch (patch back to original values)
             # Apply restore patch
     ```

**2. Deployment Misconfiguration Fault Types** (6 fault types)
   - **Resource Underprovisioning:**
     - `cpu_underprovision`: Reduce CPU requests (e.g., 30m → 5m = 83% reduction)
     - `memory_underprovision`: Reduce memory requests (e.g., 128Mi → 16Mi = 87% reduction, causes OOMKills)
   - **Resource Overprovisioning:**
     - `cpu_overprovision`: Increase CPU requests dramatically (e.g., 30m → 8000m, unschedulable)
     - `memory_overprovision`: Increase memory requests dramatically (e.g., 128Mi → 16Gi, unschedulable)
   - **Replica Misconfiguration:**
     - `replica_reduction`: Reduce replicas (e.g., 3 → 0 or 1, no redundancy)
     - `replica_excess`: Increase replicas excessively (e.g., 2 → 20, resource exhaustion)
   
   **Reduction Logic Examples:**
   ```python
   # CPU Underprovisioning (reduce from ideal)
   # Ideal: cpu: 30m
   # Extreme intensity: 83% reduction → 5m
   patch = [{
       "op": "replace",
       "path": "/spec/template/spec/containers/0/resources/requests/cpu",
       "value": "5m"  # Calculated from current ideal value
   }]
   
   # Replica Reduction (reduce from ideal)
   # Ideal: replicas: 3
   # Extreme intensity: reduce to 0
   patch = [{
       "op": "replace",
       "path": "/spec/replicas",
       "value": 0  # Calculated from current ideal value
   }]
   ```

**3. Intensities for Misconfiguration Faults**
   - **Reduction percentages applied to ideal configuration:**
   - **medium:** Noticeable misconfiguration (degraded)
     - CPU: 50% reduction, Memory: 50% reduction, Replicas: max(1, current-1)
   - **high:** Severe misconfiguration (critical)
     - CPU: 70% reduction, Memory: 75% reduction, Replicas: 1
   - **extreme:** Maximum misconfiguration (failure)
     - CPU: 83% reduction, Memory: 87% reduction, Replicas: 0
     - OR for overprovisioning: CPU × 200, Memory × 100 (unschedulable)
   
   **Example with ideal: cpu=30m, memory=128Mi, replicas=3:**
   - Medium: cpu=15m, memory=64Mi, replicas=2
   - High: cpu=9m, memory=32Mi, replicas=1
   - Extreme: cpu=5m, memory=16Mi, replicas=0

**4. Integrate into Experiment Orchestrator** (~15 lines)
   - **File:** `kub_mitigation_agent/experiment/chaos_mitigation_experiment.py`
   - **Changes:**
     - `setup()`: Initialize `self.deployment_misconfig_handler = DeploymentMisconfigHandler(config)`
     - `inject_chaos()`: Add `elif mode == "deployment_misconfig_only":` branch
     - `cleanup_all()`: Check for `chaos_experiment.get("deployment_misconfig")` and call cleanup

**5. Extend Batch Generator** (~60 lines)
   - **File:** `kub_mitigation_agent/experiment/chaos_batch_generator.py`
   - **Add constants:**
     ```python
     DEPLOYMENT_MISCONFIG_FAULT_TYPES = [
         "cpu_underprovision",
         "memory_underprovision", 
         "cpu_overprovision",
         "memory_overprovision",
         "replica_reduction",
         "replica_excess"
     ]
     DEPLOYMENT_MISCONFIG_INTENSITIES = ["medium", "high", "extreme"]
     ```
   - **Add method:** `generate_deployment_misconfig_configs(count)`
     - Randomly select fault type, intensity, and target deployment
     - Generate config with appropriate patch values
   - **Integrate:** Call from `generate_comprehensive_batch()` like other chaos types

**Total Code Addition: ~195 lines**

### Design Decisions

1. **kubectl-based approach:** Uses existing kubectl commands instead of K8s API directly (simpler, matches project pattern)
2. **Reduction from ideal:** No hardcoded values - always reduce/increase from current ideal configuration (flexible, works for any app)
3. **Percentage-based reductions:** Apply reduction percentages (e.g., 83% reduction for extreme) rather than absolute values
4. **JSON Patch format:** Precise surgical changes to deployment specs without full replacement
5. **Backup/restore mechanism:** Store original ideal specs in memory, patch back to exact values during cleanup
6. **Target selection:** Can target specific deployments from `available_deployments` config list
7. **Rollout verification:** Wait for `kubectl rollout status` to ensure patches are applied
8. **HPA interaction:** Resource changes will trigger HPA responses (realistic scenario testing)
9. **No YAML file modification:** Only runtime kubectl patches, preserves original YAML files in APPS/

### Benefits

- **Realistic production scenarios:** Misconfigurations are common root causes
- **Agent validation:** Tests if agent can identify configuration issues vs runtime failures
- **Orthogonal to resource chaos:** Tests configuration layer independently
- **Clean separation:** Doesn't interfere with ChaosMesh or Docker handlers
- **HPA testing:** Validates how agent handles autoscaler responses to misconfigurations
- **Multiple failure modes:** Tests scheduling failures (overprovision), runtime failures (underprovision), availability issues (replica reduction)

### Implementation Details

**Target Deployment Selection:**
```python
def _select_target_deployment(self, config: Dict[str, Any]) -> str:
    """Select target deployment from config or randomly."""
    if "target_deployment" in config:
        return config["target_deployment"]
    
    # Get available deployments from config
    available = self.config.get("available_deployments", [])
    if not available:
        raise ValueError("No available deployments found")
    
    return random.choice(available)
```

**Reduction Patch Generation:**
```python
def _generate_reduction_patch(self, current_spec: Dict, fault_type: str, intensity: str) -> List[Dict]:
    """Generate patch that reduces from current ideal values."""
    container_path = "/spec/template/spec/containers/0"
    current_resources = current_spec["spec"]["template"]["spec"]["containers"][0].get("resources", {})
    
    # Extract current ideal values
    current_cpu = current_resources.get("requests", {}).get("cpu", "30m")  # e.g., "30m"
    current_memory = current_resources.get("requests", {}).get("memory", "128Mi")  # e.g., "128Mi"
    current_replicas = current_spec["spec"].get("replicas", 1)
    
    # Parse values and apply reduction percentages based on intensity
    if fault_type == "cpu_underprovision":
        if intensity == "extreme":
            new_cpu = "5m"  # 83% reduction from typical 30m
        elif intensity == "high":
            new_cpu = "9m"  # 70% reduction
        else:  # medium
            new_cpu = "15m"  # 50% reduction
        
        return [{
            "op": "replace",
            "path": f"{container_path}/resources/requests/cpu",
            "value": new_cpu
        }]
    
    # ... similar logic for other fault types
```

**Rollout Wait Logic:**
```python
def _wait_for_rollout(self, deployment_name: str, timeout: int = 120) -> bool:
    """Wait for deployment rollout to complete."""
    cmd = f"kubectl rollout status deployment/{deployment_name} -n {self.namespace} --timeout={timeout}s"
    result = subprocess.run(cmd.split(), capture_output=True, text=True)
    return result.returncode == 0
```

### Challenges & Solutions

**Challenge 1:** Different deployments have different resource specs
- **Solution:** ✅ SOLVED - Always get current ideal values first, then apply percentage reductions

**Challenge 2:** HPA may immediately counteract replica changes
- **Solution:** Patch HPA minReplicas/maxReplicas first, then deployment replicas (or accept HPA response as part of chaos)

**Challenge 3:** Overprovision may make pods unschedulable
- **Solution:** This is intentional - tests agent's ability to detect scheduling issues

**Challenge 4:** Cleanup during failures
- **Solution:** Store backups immediately after retrieval, cleanup restores from backup even if injection failed partially

**Challenge 5:** Parsing resource values (30m, 128Mi) to apply percentages
- **Solution:** Use fixed reduction values per intensity level (simple, predictable, sufficient for chaos testing)

### Future Enhancements (Not in Initial Plan)

1. **Probe misconfiguration:** Modify liveness/readiness probe settings
2. **Image pull policy:** Change to `Always` to cause rate limiting
3. **Volume mount issues:** Remove or misconfigure volume mounts
4. **Service selector mismatch:** Break service-to-pod routing
5. **Combined misconfigurations:** Multiple issues simultaneously (e.g., low resources + low replicas)
6. **Gradual degradation:** Slowly reduce resources over time

### Testing Strategy

1. Unit test: Backup/restore deployment specs
2. Handler test: Apply and revert each fault type
3. Patch validation: Verify patches are correctly formatted and applied
4. Single experiment: Run one deployment misconfiguration chaos experiment
5. Rollout verification: Ensure rollout completes or fails appropriately
6. Batch test: Include deployment misconfigs in comprehensive batch
7. Agent validation: Verify agent detects configuration issues vs infrastructure issues

### Integration Notes

**Available Deployments (from config):**
```yaml
available_deployments:
  - "cloud-analytics-engine-cloud"
  - "edge-data-processor-edge-site-1"
  - "iot-gateway-edge-site-1"
  - "iot-gateway-edge-site-2"
```

**Experiment Config Structure:**
```python
{
    "mode": "deployment_misconfig_only",
    "fault_type": "cpu_underprovision",
    "intensity": "high",
    "target_deployment": "iot-gateway-edge-site-1",  # or None for random
    "duration": "3600s",
    "seed": 42,
    "description": "CPU underprovisioning on iot-gateway-edge-site-1 (high)"
}
```

---

## Infrastructure VM Streamlining (K3s Cluster)

### Objectives
- Limit Vagrant usage to VM lifecycle (up/halt/destroy/status) and rely on host `kubectl`/`bash` for cluster management.
- Speed up provisioning by caching k3s installer artifacts and parallelizing worker start-up.
- Provide a reproducible host kubeconfig and centralized node inventory for easier resource management.

### Plan of Action
1. **Artifact Caching**
   - Add `infrastructure_vm/cache/install-k3s.sh` (ignored by git) downloaded once via `curl`.
   - Provision cached installer into all VMs (server/workers) through Vagrant file provisioner or synced folder.
   - Update provisioning scripts to execute the cached installer instead of fetching from the internet each time.
2. **Host-Facing kubeconfig**
   - After `k3s-server` is up, copy `/etc/rancher/k3s/k3s.yaml` via `scp` using the Vagrant insecure key.
   - Replace `127.0.0.1` with `https://192.168.100.10:6443` and persist to `~/.kube/config` (with backup if needed).
   - Export `KUBECONFIG` for subsequent script steps so all `kubectl` commands run on the host.
3. **Script Refactors (`setup.sh`)**
   - Drop `vagrant ssh` wrappers; add generic `ssh_vm`, `scp_vm` helpers using static IPs.
   - Require `kubectl` on host; run labeling, monitoring install, chaos-mesh install, and verification locally.
   - Remove output suppression (`2>/dev/null`) to keep logs complete.
   - Keep Chaosd management using SSH (exception per requirements).
4. **Parallel Worker Start**
   - Call `vagrant up --parallel` for the worker pool once the server is ready.
   - Ensure worker provisioning uses the cached installer and waits on the server token via shared/synced path.
5. **Node Inventory File**
   - Create `infrastructure_vm/nodes.yml` describing each VM (name, role, IP, CPUs, memory, optional CPU pinning).
   - Use this manifest in both `setup.sh` (dynamic lists) and `Vagrantfile` (looped VM definitions, libvirt CPU pin directives if supported).
6. **Prerequisite Checks**
   - Add validation for required host binaries (`kubectl`, `ssh`, `scp`, `curl`, `virsh`, `vagrant`).
   - Fail fast with descriptive messages if any are missing.

### Open Decisions
- Confirm final kubeconfig destination (`~/.kube/config` vs `kube/config`).
- Decide whether CPU pinning should be actively applied or just documented in `nodes.yml`.
- Determine if additional installer assets (agent binaries, token files) should be cached alongside `install-k3s.sh`.
