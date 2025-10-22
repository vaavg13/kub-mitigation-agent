## Experiment runtime optimization plan

### Objectives
- Reduce per-experiment time by avoiding namespace deletion and full redeploy.
- Allow skipping live baseline collection using prerecorded metrics.
- Keep implementation simple; no new helpers; minimal edits at clear ownership points.

### Config changes (experiment_configs/*.yaml)
- Add under `BATCH_CONFIG.test_settings`:
  - `reset_strategy: clean | fast` (default: clean)
  - `baseline_source: measure | prerecorded` (default: measure)
- Add at `BATCH_CONFIG.baseline_metrics` for prerecorded mode:
  - `success_rate_percent: <float>`
  - `p95_latency_seconds: <float>`

Example:
```yaml
BATCH_CONFIG:
  namespace: "app-smart-manufacturing"
  app_directory: "./APPS"

  baseline_metrics:
    success_rate_percent: 99.5
    p95_latency_seconds: 0.250

  test_settings:
    deploy_fresh_app: true
    cleanup_after_test: true
    pod_ready_timeout: 300
    reset_strategy: fast
    baseline_source: prerecorded
```

### CLI changes (scripts/run_batch_chaos_test.py)
- Add optional flags; override YAML when provided:
  - `--reset-strategy {clean,fast}`
  - `--baseline-source {measure,prerecorded}`
- Merge into `batch_config["test_settings"]` before constructing `BatchChaosExperiment`.

### Fast reset strategy (no namespace deletion)
- Ownership: `BatchChaosExperiment.run_single_experiment` step 1.
- If `reset_strategy == "fast"`:
  1) `reset_scheduling_policies(self.docker_handler)` to uncordon nodes and clear chaos.
  2) Re-apply YAMLs via `K8sDeploymentManager.from_deployment_dir(app_dir).deploy()`.
  3) `kubectl rollout restart deployment --all -n <namespace>` to restart pods.
  4) Wait readiness via `wait_for_pods_ready_sync(namespace, timeout)`.
- Else (clean): keep existing fresh deploy path.

### Baseline strategy (ChaosAndMitigationExperiment.run_full_experiment)
- If `baseline_source == "prerecorded"`:
  - Use `config["baseline_metrics"]` to set phase metrics and append "baseline" to phases.
  - Start traffic prior to chaos; skip the 60s baseline sleep.
- Else (measure): keep current baseline collection.

### Optional improvement (clean path)
- In `deploy_fresh_app_sync`:
  - After `kubectl delete namespace`, poll for ns deletion instead of fixed `time.sleep(15)`.
  - Remove redundant `mgr.undeploy()` and extra `time.sleep(10)`.

### Minimal code touchpoints
- `scripts/run_batch_chaos_test.py`
  - Add CLI args and merge into `batch_config["test_settings"]`.
- `kub_mitigation_agent/experiment/batch_chaos_experiment.py`
  - In `run_single_experiment`: branch on `reset_strategy` for fast reset vs clean deploy.
- `kub_mitigation_agent/experiment/chaos_mitigation_experiment.py`
  - In `run_full_experiment`: branch baseline phase by `baseline_source`.
- `kub_mitigation_agent/experiment/experiment_utils.py` (optional)
  - Tweak waits in `deploy_fresh_app_sync` for clean mode.

### Rollout checklist
- [ ] Add `reset_strategy` and `baseline_source` keys to batch YAMLs (with defaults).
- [ ] Add `baseline_metrics` to YAMLs where used.
- [ ] Add CLI flags and config override in `run_batch_chaos_test.py`.
- [ ] Implement fast reset branch in `BatchChaosExperiment.run_single_experiment`.
- [ ] Implement prerecorded baseline branch in `ChaosAndMitigationExperiment.run_full_experiment`.
- [ ] (Optional) Replace sleeps in `deploy_fresh_app_sync` clean path with polling; remove redundant undeploy.
- [ ] Smoke test: run one clean experiment, then two fast-reset experiments; verify readiness and timing.
- [ ] Validate agent still receives baseline/current metrics and generates summary.

### Usage examples
- Fast reset with prerecorded baseline (CLI overrides YAML):
```bash
python scripts/run_batch_chaos_test.py \
  --config experiment_configs/batch_config_manufacturing_app.yaml \
  --reset-strategy fast \
  --baseline-source prerecorded
```
- Default clean mode with measured baseline:
```bash
python scripts/run_batch_chaos_test.py --config experiment_configs/batch_config_manufacturing_app.yaml
```


