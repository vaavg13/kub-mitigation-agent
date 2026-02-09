# Refactoring Summary: Open5GS 5G Core Integration

## Overview
Refactored the kub-mitigation-agent codebase to focus on 5G Core network (Open5GS) instead of microservices (Hotel Reservation). Removed Locust-based HTTP traffic generation and replaced it with UERANSIM-based 5G traffic simulation.

## What Was Added

### 1. Open5GS Application Class
**File**: `kub_mitigation_agent/service/apps/open5gs.py`
- Full-featured Open5GS 5G Core application class
- Deploy/undeploy methods using Helm with remote OCI charts
- UERANSIM integration for UE simulation
- Helper methods for PDU session management:
  - `establish_pdu_session(imsi, sst, sd, dnn)`
  - `release_pdu_session(imsi, session_id)`
  - `list_ues()`
  - `execute_ueransim_command(command)`

### 2. Open5GS Metadata
**Files**:
- `kub_mitigation_agent/service/apps/metadata/open5gs.json` - Application metadata with Helm config
- `kub_mitigation_agent/service/apps/metadata/open5gs_core_values.yaml` - Core network values (from `core.yaml`)
- `kub_mitigation_agent/service/apps/metadata/open5gs_ues_values.yaml` - UE simulator values (from `ues.yaml`)
- `kub_mitigation_agent/service/apps/metadata/open5gs_experiments.yaml` - Chaos experiment configurations

### 3. UERANSIM Traffic Generator
**File**: `kub_mitigation_agent/generators/workload/ueransim_generator.py`
- 5G-specific traffic generator replacing Locust
- Supports continuous and bursty traffic patterns
- Automatic PDU session lifecycle management
- Async/await interface for experiment orchestration

### 4. Test Script
**File**: `scripts/test_open5gs_deployment.py`
- Quick test script for Open5GS deployment
- Shows basic usage patterns
- Demonstrates UERANSIM integration

## What Was Removed

### Files Deleted
- `kub_mitigation_agent/service/apps/hotel_reservation.py`
- `kub_mitigation_agent/service/apps/metadata/hotel_reservation.json`
- `kub_mitigation_agent/service/apps/metadata/hotel_reservation_experiments.yaml`
- `kub_mitigation_agent/service/apps/profiles/hotel_reservation.py`
- `kub_mitigation_agent/service/apps/profiles/simple.py`
- `scripts/test_hotel_deployment.py`
- `scripts/test_traffic.py`

### References Updated
Updated all imports and references from `HotelReservation` to `Open5GS` in:
- `kub_mitigation_agent/service/__init__.py`
- `kub_mitigation_agent/service/k8s.py`
- `kub_mitigation_agent/experiment/runners/runner.py`
- `scripts/run_batch.py`

## Updated Paths

**File**: `kub_mitigation_agent/paths.py`

```python
# Old (removed):
HOTEL_RESERVATION_METADATA
HOTEL_RESERVATION_EXPERIMENTS

# New (added):
OPEN5GS_METADATA
OPEN5GS_EXPERIMENTS
OPEN5GS_CORE_VALUES
OPEN5GS_UES_VALUES
```

## Helm Configuration

### Open5GS Core
- **Chart**: `oci://registry-1.docker.io/gradiantcharts/open5gs`
- **Release Name**: `open5gs`
- **Namespace**: `open5gs`
- **Values Files**: `open5gs_core_values.yaml`, `open5gs_ues_values.yaml`

### UERANSIM
- **Chart**: `oci://registry-1.docker.io/gradiant/ueransim-gnb`
- **Release Name**: `ueransim`
- **Namespace**: `open5gs` (same as core)
- **Values File**: `open5gs_ues_values.yaml`

## 5G Network Configuration

From `open5gs.json`:
- **MCC**: 999
- **MNC**: 70
- **SST**: 1 (Slice Service Type)
- **SD**: 0x111111 (Slice Differentiator)
- **TAC**: 0001 (Tracking Area Code)
- **AMF Hostname**: open5gs-amf-ngap
- **Number of UEs**: 11 (IMSI: 999700000000001 - 999700000000011)

## Usage Examples

### Deploy Open5GS Core

```python
from kub_mitigation_agent.service.apps import Open5GS

# Initialize and deploy
app = Open5GS()
app.deploy()

# Deploy UERANSIM for traffic generation
app.deploy_ueransim()
```

### Generate 5G Traffic

```python
# List available UEs
ues = app.list_ues()

# Establish PDU session
app.establish_pdu_session(
    imsi="imsi-999700000000001",
    sst=1,
    sd="1",
    dnn="internet"
)

# Release PDU session
app.release_pdu_session(
    imsi="imsi-999700000000001",
    session_id=1
)
```

### Using UERANSIM Traffic Generator

```python
from kub_mitigation_agent.generators.workload import UERANSIMTrafficGenerator

config = {
    "namespace": "open5gs",
    "num_ues": 11,
    "traffic_type": "continuous",
    "pdu_sessions_per_ue": 1,
}

generator = UERANSIMTrafficGenerator(config)
await generator.start_traffic()
# ... traffic runs ...
await generator.stop_traffic()
```

### Cleanup

```python
# Undeploy (removes Helm releases)
app.delete()

# Full cleanup (removes namespace and PVs)
app.cleanup()
```

## Testing

Run the test script to verify deployment:

```bash
python scripts/test_open5gs_deployment.py
```

## Chaos Experiments

Chaos experiments are configured in `open5gs_experiments.yaml`:
- AMF pod failure (active)
- SMF, UPF, NRF pod failures (commented out, ready to enable)
- CPU stress tests (commented out)
- Network delay tests (commented out)

Enable additional experiments by uncommenting sections in the YAML file.

## Next Steps

1. **Test Deployment**: Run `scripts/test_open5gs_deployment.py` to verify
2. **Verify UERANSIM**: Check that UEs register with the core
3. **Test PDU Sessions**: Establish and release sessions manually
4. **Enable Traffic Generation**: Integrate UERANSIM generator with experiments
5. **Run Chaos Experiments**: Test with AMF pod failure
6. **Expand Coverage**: Enable additional chaos experiments (SMF, UPF, etc.)

## Notes

- Istio injection is **disabled** for Open5GS (5G protocols don't work well with service mesh)
- Locust-based generators are kept for backward compatibility but are not used for 5G
- UERANSIM traffic generation uses 5G protocols (NGAP, NAS, GTP) instead of HTTP
- All paths use absolute references to avoid Helm path resolution issues

## Architecture Comparison

### Before (Hotel Reservation)
- HTTP/REST microservices
- Locust traffic generator
- Istio service mesh
- Prometheus metrics via Envoy

### After (Open5GS)
- 5G Core Network Functions (AMF, SMF, UPF, etc.)
- UERANSIM traffic generator (5G protocols)
- No service mesh (incompatible with 5G)
- Direct Prometheus metrics from 5G components
