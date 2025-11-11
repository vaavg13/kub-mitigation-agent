# Experiment Module Refactoring Plan

**Goal**: Redesign the experiment module to be cleaner, more extensible, and more readable while reducing code complexity.

**Status**: Design proposal - Not yet implemented  
**Estimated Effort**: 2-3 days  
**Risk**: Medium (significant refactoring, but logic remains similar)

---

## Current Problems

1. **Scattered Logic**: Experiment logic split between `experiment_runner.py` (359 lines) and `experiment_batch_runner.py` (267 lines)
2. **Unclear Responsibilities**: Deployment, cleanup, and logging mixed with experiment phases
3. **Dict-Heavy**: Results passed as untyped dictionaries → hard to understand structure
4. **Duplicate Cleanup**: Cleanup happens in multiple places (pre-experiment, post-experiment, post-chaos)
5. **Hard to Extend**: Adding new phases or modifying flow requires touching multiple places

---

## Proposed Architecture

### Core Philosophy

**"Experiment as a Pipeline of Phases with Shared Context"**

```
ExperimentRunner orchestrates phases:
  1. Setup Phase (pre-cleanup, deploy app)
  2. Warmup Phase (start traffic, stabilize)
  3. Baseline Phase (measure normal performance)
  4. Chaos Phase (inject anomaly, measure impact)
  5. Mitigation Phase (run agent to fix)
  6. Recovery Phase (measure post-mitigation)
  7. Teardown Phase (cleanup, undeploy)

Each phase:
  - Reads from shared ExperimentContext
  - Updates context with its results
  - Has clear input/output contract
```

### Key Design Principles

1. **Single Responsibility**: Each file has one clear purpose
2. **Explicit State**: All shared state in `ExperimentContext` dataclass
3. **Type Safety**: Use dataclasses for results, not dicts
4. **Linear Flow**: Phases execute in order, easy to follow
5. **Easy Extension**: Add new phase = add new method/file

---

## New File Structure

```
experiment/
├── __init__.py                     # Public API exports

# Core experiment execution (ONLY 3 FILES!)
├── experiment.py                   # NEW: Experiment dataclass (~80 lines)
├── phases.py                       # NEW: Phase functions (~200 lines)
├── experiment_runner.py            # REFACTORED: Runner class (~120 lines)

# Batch coordination
├── batch_runner.py                 # REFACTORED: Batch coordinator (~80 lines)

# Supporting utilities
├── evaluators.py                   # MOVED: Recovery + location evaluation (~150 lines)
├── experiment_k8s_ops.py           # KEEP: K8s operations (deploy, cleanup)
├── experiment_logger.py            # KEEP: Logging infrastructure
├── traffic_generator.py            # KEEP: Traffic generation
└── alert_config.py                 # KEEP: Alert/snapshot builders

# Remove after refactoring
├── [OLD] experiment_runner.py      # REPLACE (same name, new design)
├── [OLD] experiment_batch_runner.py # REPLACE (rename to batch_runner.py)
└── recovery_evaluator.py           # MERGE into evaluators.py
```

**Total Lines**: ~630 lines (current: ~900 lines including helpers)  
**Main Logic**: ~400 lines (current: ~626 lines) = **36% reduction**

**Design**: Runner class orchestrates, phase functions mutate shared Experiment dataclass

---

## Implementation Details

### 1. Experiment (experiment.py) - Single Dataclass

**Purpose**: One dataclass represents both working state AND final result (no duplication!)

```python
# experiment/experiment.py
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

@dataclass
class Experiment:
    """
    A single chaos experiment.
    
    This object IS both:
    - The working state (mutated by phase functions)
    - The final result (serialized via to_dict())
    
    Lifecycle: create with config → phases mutate it → save to disk
    """
    
    # === CONFIGURATION (immutable, set at creation) ===
    namespace: str
    anomaly: Any  # Anomaly instance
    config: Dict[str, Any]  # Full experiment config
    agent_config: Optional[Any] = None
    
    # === IDENTITY (set by batch runner) ===
    id: str = ""  # Generated experiment ID
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    
    # === RESOURCES (managed by phases, cleaned up) ===
    traffic_generator: Optional[Any] = None
    anomaly_handle: Optional[Any] = None
    
    # === COLLECTED METRICS (populated during measurement phases) ===
    baseline_metrics: Optional[Dict[str, Any]] = None
    chaos_metrics: Optional[Dict[str, Any]] = None
    recovery_metrics: Optional[Dict[str, Any]] = None
    
    # === AGENT RESULTS (from mitigation phase) ===
    agent_trace: List[Dict[str, Any]] = field(default_factory=list)
    operational_summary: Optional[Dict[str, Any]] = None
    agent_success: bool = False
    
    # === EVALUATIONS (computed after phases complete) ===
    recovery_evaluation: Optional[Dict[str, Any]] = None
    location_evaluation: Optional[Dict[str, Any]] = None
    
    # === STATUS (updated throughout execution) ===
    success: bool = False
    interrupted: bool = False
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging (matches current log format)."""
        return {
            "experiment_id": self.id,
            "namespace": self.namespace,
            "chaos_config": self.anomaly.get_info(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "baseline_metrics": self.baseline_metrics,
            "chaos_metrics": self.chaos_metrics,
            "recovery_metrics": self.recovery_metrics,
            "agent_trace": self.agent_trace,
            "operational_summary": self.operational_summary,
            "agent_success": self.agent_success,
            "recovery_evaluation": self.recovery_evaluation,
            "location_evaluation": self.location_evaluation,
            "success": self.success,
            "interrupted": self.interrupted,
            "error": self.error,
        }
```

**Benefits**:
- ✅ **No duplication** - Single object for everything (no separate context+result)
- ✅ **Clear lifecycle** - Empty → running → complete
- ✅ **Natural** - "Experiment accumulates data over time"
- ✅ **Type-safe** - All fields are documented with type hints
- ✅ **Serializable** - to_dict() produces current log format

---

### 2. Phase Functions (phases.py) - Pure Functions

**Purpose**: Each phase is a simple function that mutates the experiment

```python
# experiment/phases.py
import asyncio
from datetime import datetime, timezone
from .experiment import Experiment

# ========== PHASE 1: SETUP ==========

async def phase_setup(exp: Experiment):
    """Pre-cleanup + deploy application."""
    print(f"\n▶ Setup")
    
    from .experiment_k8s_ops import complete_pre_experiment_cleanup, deploy_fresh_app_sync
    
    # Pre-cleanup: stop anomalies, uncordon nodes, delete namespace
    complete_pre_experiment_cleanup(
        exp.namespace,
        exp.config.get("nodes", {}),
        exp.config.get("chaosd_port", 31767)
    )
    
    # Deploy fresh app
    success, _ = deploy_fresh_app_sync(exp.config)
    if not success:
        raise Exception("Failed to deploy application")
    
    print(f"  ✅ Complete")


# ========== PHASE 2: WARMUP ==========

async def phase_warmup(exp: Experiment):
    """Start traffic and stabilize system."""
    duration = exp.config.get("warmup_duration", 0)
    if duration == 0:
        return
    
    print(f"\n▶ Warmup ({duration}s)")
    
    from .traffic_generator import LocustTrafficGenerator
    exp.traffic_generator = LocustTrafficGenerator(exp.config["traffic_config"])
    await exp.traffic_generator.start_traffic()
    await asyncio.sleep(duration)
    
    print(f"  ✅ Complete")


# ========== PHASE 3: BASELINE ==========

async def phase_baseline(exp: Experiment):
    """Measure normal system performance."""
    duration = exp.config["baseline_duration"]
    print(f"\n▶ Baseline ({duration}s)")
    
    # Start traffic if not running
    if not exp.traffic_generator:
        from .traffic_generator import LocustTrafficGenerator
        exp.traffic_generator = LocustTrafficGenerator(exp.config["traffic_config"])
        await exp.traffic_generator.start_traffic()
    
    await asyncio.sleep(duration)
    
    from .experiment_k8s_ops import collect_istio_ingress_metrics
    exp.baseline_metrics = collect_istio_ingress_metrics(duration)
    
    print(f"  ✅ {exp.baseline_metrics['success_rate_percent']:.1f}% success, "
          f"P95: {exp.baseline_metrics['p95_latency_seconds']:.3f}s")


# ========== PHASE 4: CHAOS ==========

async def phase_chaos(exp: Experiment):
    """Inject anomaly and measure impact."""
    print(f"\n▶ Chaos")
    
    # Inject anomaly
    print(f"  Injecting...", end="")
    exp.anomaly_handle = exp.anomaly.start()
    print(" ✅")
    
    # Warmup + measure
    warmup = exp.config["chaos_warmup_duration"]
    await asyncio.sleep(warmup)
    
    from .experiment_k8s_ops import collect_istio_ingress_metrics
    exp.chaos_metrics = collect_istio_ingress_metrics(warmup)
    
    print(f"  ⚠️  {exp.chaos_metrics['success_rate_percent']:.1f}% success, "
          f"P95: {exp.chaos_metrics['p95_latency_seconds']:.3f}s")


# ========== PHASE 5: MITIGATION ==========

async def phase_mitigation(exp: Experiment):
    """Run agent to diagnose and fix problem."""
    if not exp.agent_config or not exp.agent_config.enabled:
        print(f"\n▶ Mitigation: DISABLED")
        return
    
    print(f"\n▶ Mitigation")
    
    from kub_mitigation_agent.agent.agent import KubernetesAgent
    from .alert_config import build_intent, build_snapshot
    
    agent = KubernetesAgent(exp.agent_config)
    await agent.initialize()
    
    # Prepare agent inputs
    intent = build_intent()
    snapshot = build_snapshot(
        namespace=exp.namespace,
        baseline_latency_p95=exp.baseline_metrics['p95_latency_seconds'],
        baseline_success_rate=exp.baseline_metrics['success_rate_percent'],
        current_latency_p95=exp.chaos_metrics['p95_latency_seconds'],
        current_success_rate=exp.chaos_metrics['success_rate_percent'],
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    try:
        actions, trace, summary = await agent.agent_loop(intent, snapshot)
        exp.agent_trace = trace
        exp.operational_summary = summary
        exp.agent_success = True
        print(f"  ✅ {len(trace)} steps")
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        exp.agent_success = False
    finally:
        await agent.cleanup()


# ========== PHASE 6: RECOVERY ==========

async def phase_recovery(exp: Experiment):
    """Measure post-mitigation performance."""
    duration = exp.config["recovery_duration"]
    print(f"\n▶ Recovery ({duration}s)")
    
    await asyncio.sleep(duration)
    
    from .experiment_k8s_ops import collect_istio_ingress_metrics
    exp.recovery_metrics = collect_istio_ingress_metrics(duration)
    
    print(f"  ✅ {exp.recovery_metrics['success_rate_percent']:.1f}% success, "
          f"P95: {exp.recovery_metrics['p95_latency_seconds']:.3f}s")


# ========== PHASE 7: TEARDOWN ==========

async def phase_teardown(exp: Experiment):
    """Cleanup all experiment resources."""
    print(f"\n▶ Teardown")
    
    # Stop traffic
    if exp.traffic_generator:
        try:
            await exp.traffic_generator.stop_traffic()
        except Exception as e:
            print(f"  ⚠️  Traffic: {e}")
    
    # Stop anomaly
    if exp.anomaly_handle:
        try:
            exp.anomaly.stop()
        except Exception as e:
            print(f"  ⚠️  Anomaly: {e}")
    
    # Comprehensive cleanup
    try:
        from kub_mitigation_agent.anomalies import cleanup_all_anomalies
        cleanup_all_anomalies(
            namespaces=[exp.namespace],
            nodes=exp.config.get("nodes", {}),
            chaosd_port=exp.config.get("chaosd_port", 31767)
        )
    except Exception as e:
        print(f"  ⚠️  Cleanup: {e}")
    
    # Undeploy app
    try:
        from .experiment_k8s_ops import undeploy_app_sync
        undeploy_app_sync(exp.config)
    except Exception as e:
        print(f"  ⚠️  Undeploy: {e}")
    
    print(f"  ✅ Complete")
```

**Benefits**:
- ✅ **Simple functions** - Not classes, not methods, just functions
- ✅ **Clear contract** - Take experiment, mutate it, return nothing
- ✅ **Easy to test** - `await phase_baseline(mock_exp)`
- ✅ **Easy to extend** - Add a new function, call it from runner
- ✅ **Reusable** - Can be called from anywhere, not tied to a class

**Lines**: ~200 lines (all 7 phases)

---

### 3. ExperimentRunner (experiment_runner.py) - Orchestration Class

**Purpose**: Orchestrate phases, handle errors, save results

```python
# experiment/experiment_runner.py
from datetime import datetime, timezone
from .experiment import Experiment
from . import phases
from .evaluators import evaluate_recovery, evaluate_location

class ExperimentRunner:
    """Orchestrates a single chaos experiment."""
    
    def __init__(self, experiment: Experiment, logger=None):
        self.exp = experiment
        self.logger = logger
    
    async def run(self) -> Experiment:
        """
        Execute experiment phases in order.
        
        Returns the same experiment object (now complete).
        """
        print(f"\n{'='*70}")
        print(f"🧪 EXPERIMENT: {self.exp.id}")
        print(f"{'='*70}")
        
        try:
            # Run phases in order (phase functions mutate self.exp)
            await phases.phase_setup(self.exp)
            await phases.phase_warmup(self.exp)
            await phases.phase_baseline(self.exp)
            await phases.phase_chaos(self.exp)
            await phases.phase_mitigation(self.exp)
            await phases.phase_recovery(self.exp)
            
            # Evaluate results
            self.exp.recovery_evaluation = evaluate_recovery(self.exp)
            self.exp.location_evaluation = evaluate_location(self.exp)
            
            # Print summary
            self._print_summary()
            
            # Mark success
            self.exp.success = self.exp.recovery_evaluation.get("success", False)
            
        except KeyboardInterrupt:
            self.exp.interrupted = True
            print("\n⚠️  Interrupted")
            raise
            
        except Exception as e:
            self.exp.error = str(e)
            print(f"\n❌ Failed: {e}")
            
        finally:
            # Always teardown and save
            await phases.phase_teardown(self.exp)
            self.exp.completed_at = datetime.now(timezone.utc)
            
            if self.logger:
                self.logger.log_experiment(self.exp)  # Logger calls exp.to_dict() internally
        
        return self.exp
    
    def _print_summary(self):
        """Print experiment summary."""
        if not self.exp.recovery_evaluation:
            return
        
        r = self.exp.recovery_evaluation
        print(f"\n📊 Results:")
        print(f"  Recovery: {'✅' if r['success'] else '❌'} {r['reason']}")
        
        if self.exp.location_evaluation:
            l = self.exp.location_evaluation
            print(f"  Location: {'✅' if l['location_identified'] else '❌'} "
                  f"Expected: {l['expected_target']}, Found: {l['reported_locations']}")
```

**Key Changes from Current**:
- ❌ Remove: Separate context/result objects and conversion logic
- ❌ Remove: Phase class wrapper
- ✅ Add: Direct calls to phase functions
- ✅ Add: Experiment object passed through, mutated, returned
- ✅ Add: Clean error handling that preserves partial results

**Lines**: ~120 lines (vs current 359 lines)

---

### 4. BatchExperimentRunner (batch_runner.py) - Coordination

**Purpose**: create experiments, aggregate results

```python
# experiment/batch_runner.py
import re
from datetime import datetime, timezone
from .experiment import Experiment
from .experiment_runner import ExperimentRunner
from .experiment_logger import SimpleExperimentLogger

class BatchExperimentRunner:
    """Coordinates multiple experiments in a batch."""
    
    def __init__(self, batch_config: Dict[str, Any], agent_config):
        self.batch_config = batch_config
        self.agent_config = agent_config
        
        # Generate anomalies from spec
        from kub_mitigation_agent.anomalies.anomaly_config_generator import AnomalyConfigGenerator
        generator = AnomalyConfigGenerator(batch_config)
        self.anomalies = generator.generate_instances_from_spec(
            batch_config.get("nodes", {}),
            batch_config.get("chaosd", {}).get("port", 31767)
        )
        
        # Setup logger
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        self.batch_id = f"batch_{timestamp}_{batch_config['namespace']}"
        self.logger = SimpleExperimentLogger("DATASET_LOGS", self.batch_id)
        self.experiments = []
    
    async def run_batch(self) -> Dict[str, Any]:
        """Run all experiments in sequence."""
        print(f"\n{'='*70}")
        print(f"🎯 BATCH: {self.batch_id}")
        print(f"📊 {len(self.anomalies)} experiments")
        print(f"{'='*70}\n")
        
        try:
            for idx, anomaly in enumerate(self.anomalies):
                # Create experiment object
                exp = Experiment(
                    id=self._generate_id(idx, anomaly),
                    namespace=self.batch_config["namespace"],
                    anomaly=anomaly,
                    config=self.batch_config,
                    agent_config=self.agent_config
                )
                
                # Run it
                runner = ExperimentRunner(exp, self.logger)
                try:
                    exp = await runner.run()
                    self.experiments.append(exp)
                except KeyboardInterrupt:
                    print(f"\n🛑 Batch interrupted")
                    break
        
        finally:
            # Save summary
            summary = self._build_summary()
            self.logger.save_batch_summary(summary)
            print(f"\n💾 Saved: {self.logger.output_dir}/batch_summary.json")
            return summary
    
    def _generate_id(self, idx: int, anomaly) -> str:
        """Generate readable experiment ID."""
        info = anomaly.get_info()
        parts = [
            f"{idx+1:03d}",
            info.get("mode", "chaos"),
            info.get("fault_type", "unknown")
        ]
        
        target = info.get("target", {})
        if name := (target.get("name") or target.get("app")):
            parts.append(name)
        
        slug = "-".join(parts).lower().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9-]+", "-", slug)
        return f"exp_{slug}"
    
    def _build_summary(self) -> Dict[str, Any]:
        """Aggregate batch results."""
        successful = sum(1 for e in self.experiments if e.success)
        location_ok = sum(
            1 for e in self.experiments 
            if e.location_evaluation and e.location_evaluation.get("location_identified")
        )
        
        return {
            "batch_id": self.batch_id,
            "total": len(self.anomalies),
            "completed": len(self.experiments),
            "successful": successful,
            "failed": len(self.experiments) - successful,
            "location_accuracy": location_ok / len(self.experiments) * 100 if self.experiments else 0,
            "experiments": [
                {
                    "id": e.id,
                    "success": e.success,
                    "recovery_ok": e.recovery_evaluation.get("success") if e.recovery_evaluation else False
                }
                for e in self.experiments
            ]
        }
```

**Key Changes from Current**:
- ❌ Remove: All phase execution logic (delegated to ExperimentRunner)
- ❌ Remove: Deployment/cleanup logic (delegated to phase functions)
- ✅ Add: Simple experiment object creation
- ✅ Keep: ID generation (batch-level concern)
- ✅ Keep: Summary aggregation (batch-level concern)
- ✅ Simplify: Just coordinates, doesn't execute

**Lines**: ~80 lines (vs current 267 lines)

---

### 5. Evaluators (evaluators.py) - Evaluation Logic

**Purpose**: Compute recovery and location evaluations

```python
# experiment/evaluators.py
from typing import Dict, Any
from .experiment import Experiment

def evaluate_recovery(exp: Experiment) -> Dict[str, Any]:
    """Evaluate if system recovered to baseline levels."""
    # Current logic from recovery_evaluator.py
    # Access exp.baseline_metrics, exp.recovery_metrics, exp.chaos_metrics
    phase_metrics = {
        "baseline": exp.baseline_metrics,
        "chaos": exp.chaos_metrics,
        "recovery": exp.recovery_metrics
    }
    
    # ... existing evaluation logic ...
    return {
        "success": bool,
        "reason": str,
        "metrics_comparison": dict,
        "recovery_index_latency": float,
        "recovery_index_success": float,
        "composite_recovery_score": float,
        "within_20pct_baseline": bool
    }

def evaluate_location(exp: Experiment) -> Dict[str, Any]:
    """Evaluate if agent correctly identified problem location."""
    # Current logic from recovery_evaluator.py
    # Access exp.anomaly.get_info(), exp.operational_summary
    chaos_config = exp.anomaly.get_info()
    problem_location = exp.operational_summary.get("problem_location") if exp.operational_summary else None
    
    # ... existing location matching logic ...
    return {
        "location_identified": bool,
        "expected_target": str,
        "reported_locations": list,
        "match_details": str
    }
```

**Changes**:
- ❌ Remove: `recovery_evaluator.py` (merge into this file)
- ✅ Simplify: Functions take Experiment instead of multiple parameters
- ✅ Keep: All existing evaluation logic intact

**Lines**: ~150 lines

---

### 6. Logger Update (experiment_logger.py)

**Purpose**: Simplify logger to accept Experiment dataclass directly

**Current**:
```python
logger.log_experiment(experiment_result.to_dict(), batch_id)
```

**New**:
```python
# experiment/experiment_logger.py
class SimpleExperimentLogger:
    def log_experiment(self, experiment: Experiment) -> Path:
        """Log experiment by accepting Experiment dataclass."""
        # Logger handles serialization internally
        log_data = experiment.to_dict()
        
        # Add Prometheus snapshot
        log_data["prometheus_timeseries"] = self.snapshot_prometheus_metrics(
            experiment.started_at.isoformat(),
            (experiment.completed_at - experiment.started_at).total_seconds(),
            experiment.namespace
        )
        
        # Save to file
        log_file = self.output_dir / f"{experiment.id}.json"
        with open(log_file, 'w') as f:
            json.dump(log_data, f, indent=2)
        
        return log_file
```

**Benefits**:
- ✅ Simpler API: `logger.log_experiment(exp)` vs `logger.log_experiment(exp.to_dict(), batch_id)`
- ✅ Logger owns serialization logic
- ✅ Type-safe: logger expects Experiment, not dict

---

### 7. Traffic Generator: Simplify or Drop?

**Current**: `LocustTrafficGenerator` wrapper class

**Question**: Does the wrapper add value, or can phases use Locust directly?

**Option A: Keep Simplified Wrapper** (if it provides useful abstraction)
```python
# experiment/traffic.py
class TrafficGenerator:
    """Thin wrapper around Locust for traffic generation."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._process = None
    
    async def start(self):
        """Start Locust traffic generation."""
        # Locust subprocess management
        self._process = subprocess.Popen([...])
    
    async def stop(self):
        """Stop traffic generation."""
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=10)
```

**Use in phases**:
```python
async def phase_warmup(exp: Experiment):
    from .traffic import TrafficGenerator
    exp.traffic_generator = TrafficGenerator(exp.config["traffic_config"])
    await exp.traffic_generator.start()
```

**Keep wrapper if**:
- Manages Locust subprocess lifecycle
- Handles config translation
- Provides cleanup guarantees
- Used in multiple places

---

**Option B: Drop Wrapper** (if it's just a thin pass-through)
```python
# phases.py - direct Locust usage
import subprocess

async def phase_warmup(exp: Experiment):
    """Start traffic directly with Locust."""
    traffic_cfg = exp.config["traffic_config"]
    
    # Start Locust directly
    cmd = [
        "locust",
        "-f", traffic_cfg["locustfile"],
        "--host", traffic_cfg["host"],
        "--users", str(traffic_cfg["users"]),
        "--spawn-rate", str(traffic_cfg["spawn_rate"]),
        "--headless",
        "--run-time", str(traffic_cfg.get("run_time", "999h"))
    ]
    
    exp._locust_process = subprocess.Popen(cmd)
    await asyncio.sleep(2)  # Let it start


async def phase_teardown(exp: Experiment):
    """Stop traffic."""
    if hasattr(exp, '_locust_process') and exp._locust_process:
        exp._locust_process.terminate()
        exp._locust_process.wait(timeout=10)
```

**Drop wrapper if**:
- It's just translating config to subprocess args
- No complex lifecycle management
- Only used in 2-3 places (phases only)
- Phases can handle subprocess directly

---

**Recommendation** (After Analysis):

✅ **KEEP the wrapper** - It provides significant value:

Current `LocustTrafficGenerator` (~165 lines) does:
- ✅ Manages Locust Environment + Runner lifecycle
- ✅ Bridges async (asyncio) ↔ sync (gevent) contexts
- ✅ Config abstraction (dict → Locust API)
- ✅ Logging suppression for Locust
- ✅ Dynamic traffic adjustment (`adjust_traffic_rate()`)
- ✅ RPS calculation for display
- ✅ Custom `SimpleLoadUser` class

**This is NOT a thin wrapper** - it handles async/gevent integration, which would be messy to inline in phases.

**Keep as-is** or **minor simplification**:
```python
# Just update phases to use it cleanly
async def phase_warmup(exp: Experiment):
    from .traffic_generator import LocustTrafficGenerator
    exp.traffic_generator = LocustTrafficGenerator(exp.config["traffic_config"])
    await exp.traffic_generator.start_traffic()
```

**No changes needed** - the wrapper earns its place!

---

## Summary

### Code Reduction
- **experiment.py**: 80 lines (new)
- **phases.py**: 200 lines (all phases)
- **experiment_runner.py**: 120 lines (vs current 359) = **-239 lines**
- **batch_runner.py**: 80 lines (vs current 267) = **-187 lines**
- **evaluators.py**: 150 lines (merged from recovery_evaluator.py)
- **experiment_logger.py**: Minor update (accept Experiment directly)
- **traffic_generator.py**: Keep as-is (provides value)

**Total Main Logic**: ~630 lines (current: ~900) = **30% reduction**

### Key Benefits

1. **No Duplication** - Single Experiment dataclass (not context + result)
2. **Simple Phases** - Functions (not class methods)
3. **Clean Runner** - Class for orchestration
4. **Easy Extension** - Add phase = add function
5. **Easy Testing** - `await phase_baseline(mock_exp)`
6. **Simpler Logger** - Accepts Experiment directly: `logger.log_experiment(exp)`
7. **Keep Good Abstractions** - Traffic generator wrapper provides real value (async/gevent bridging)

---

## Migration Strategy

1. ✅ Create `experiment.py` with Experiment dataclass
2. ✅ Create `phases.py` with 7 phase functions (using LocustTrafficGenerator wrapper)
3. ✅ Rewrite `experiment_runner.py` (keep same filename)
4. ✅ Rename `experiment_batch_runner.py` → `batch_runner.py`
5. ✅ Merge `recovery_evaluator.py` → `evaluators.py`
6. ✅ Update `experiment_logger.py` to accept Experiment dataclass
7. ✅ Test with one experiment
8. ✅ Test with full batch
9. ✅ Delete old `experiment_batch_runner.py` and `recovery_evaluator.py`

**Estimated Time**: 1-2 days

**Traffic Generator**: No changes needed - keep `traffic_generator.py` as-is

---

**Document Version**: 2.0 (Final)  
**Last Updated**: 2025-11-11  
**Status**: Ready to implement
