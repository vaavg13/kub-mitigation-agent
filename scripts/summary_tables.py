#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import pandas as pd


def extract_model_and_app(filepath: Path) -> Tuple[str, str]:
	"""
	Extract model (e.g., gpt-5, gpt-5-mini) and app type (e.g., app-smart-city) from the path.
	Expected layout: DATASET_LOGS/<model>/batch_*_app-<name>/exp_*.json
	Falls back to 'unknown' if not found.
	"""
	model = "unknown"
	app_type = "unknown"

	# MODEL: first subdirectory under DATASET_LOGS
	try:
		parts = filepath.parts
		if "DATASET_LOGS" in parts:
			idx = parts.index("DATASET_LOGS")
			if idx + 1 < len(parts):
				model = parts[idx + 1]
	except Exception:
		pass

	# APP TYPE: any parent folder containing 'app-'
	for parent in filepath.parents:
		name = parent.name
		if "app-" in name:
			# pick the first 'app-*' token
			for token in name.split("_"):
				if token.startswith("app-"):
					app_type = token
					break
			if app_type != "unknown":
				break

	return model, app_type


def classify_experiment(fault_type: Optional[str], target_mode: Optional[str]) -> str:
	"""
	Map raw fault type and target mode to high-level experiment categories, mirroring the notebook.
	Only includes the categories we need for aggregation.
	"""
	fault = (fault_type or "unknown").lower()
	mode = (target_mode or "").lower()

	if fault == "baseline" or "no-failure" in fault:
		return "Baseline"
	if fault == "pod_failure":
		return "Pod Failure (All Pods)" if mode == "all_pods_app" else "Pod Failure (One Pod)"
	if fault == "cpu_stress":
		return "Pod CPU Stress (All Pods)" if mode == "all_pods_app" else "Pod CPU Stress (One Pod)"
	if fault == "memory_stress":
		return "Pod Memory Stress (All Pods)" if mode == "all_pods_app" else "Pod Memory Stress (One Pod)"
	if fault == "node_cpu_stress":
		return "Node CPU Stress"
	if fault == "node_mem_stress":
		return "Node Memory Stress"
	return f"Other: {fault}".title()


def compute_recovery_index(baseline: float, chaos: float, recovery: float, *, higher_is_better: bool) -> float:
	"""
	Recovery index as percentage of degradation regained.
	0% means no recovery, 100% means full recovery to baseline or better.
	"""
	if higher_is_better:
		# e.g., success rate: baseline >= chaos, recovery increases back toward baseline
		delta = baseline - chaos
		progress = recovery - chaos
	else:
		# e.g., latency: baseline <= chaos, recovery decreases back toward baseline
		delta = chaos - baseline
		progress = chaos - recovery
	if delta <= 0:
		return 0.0
	return max(0.0, min(100.0, (progress / delta) * 100.0))


def load_experiments(root: Path) -> pd.DataFrame:
	"""
	Scan DATASET_LOGS for experiment JSON files and build a dataframe with required fields.
	"""
	records: List[Dict[str, Any]] = []
	for file in root.rglob("exp_*.json"):
		try:
			with file.open("r") as f:
				data = json.load(f)
		except Exception:
			continue

		model, app_type = extract_model_and_app(file)

		# Metrics blocks
		baseline = data.get("baseline_metrics", {}) or {}
		chaos = data.get("chaos_metrics", {}) or {}
		recovery = data.get("recovery_metrics", {}) or {}

		# Success rate (%)
		baseline_sr = float(baseline.get("success_rate_percent") or 0.0)
		chaos_sr = float(chaos.get("success_rate_percent") or baseline_sr)
		recovery_sr = float(recovery.get("success_rate_percent") or chaos_sr)

		# Latency (seconds)
		baseline_lat = float(baseline.get("p95_latency_seconds") or 0.0)
		chaos_lat = float(chaos.get("p95_latency_seconds") or baseline_lat)
		recovery_lat = float(recovery.get("p95_latency_seconds") or chaos_lat)

		# Degradation during chaos
		lat_deg = ((chaos_lat - baseline_lat) / baseline_lat * 100.0) if baseline_lat > 0 else 0.0
		sr_deg = ((baseline_sr - chaos_sr) / baseline_sr * 100.0) if baseline_sr > 0 else 0.0

		# Recovery indices
		lat_rec = compute_recovery_index(baseline_lat, chaos_lat, recovery_lat, higher_is_better=False)
		sr_rec = compute_recovery_index(baseline_sr, chaos_sr, recovery_sr, higher_is_better=True)

		# Threshold compliance (as in notebook): latency within 20%, success rate within 1% absolute
		latency_within_20pct = (baseline_lat > 0) and (abs(recovery_lat - baseline_lat) / baseline_lat <= 0.20)
		success_within_1pct = abs(recovery_sr - baseline_sr) <= 1.0
		recovery_success = bool(latency_within_20pct and success_within_1pct)

		# Location identification flag
		location_eval = data.get("location_evaluation", {}) or {}
		location_identified = bool(location_eval.get("location_identified", False))

		# Agent effort
		agent_trace = data.get("agent_trace", []) or []
		agent_steps = len(agent_trace)
		agent_duration_seconds = float(data.get("agent_duration_seconds") or 0.0)
		total_sleep_seconds = 0.0
		for step in agent_trace:
			if step.get("action") == "sleep_seconds":
				try:
					duration = float(step.get("args", {}).get("seconds", 0.0))
				except Exception:
					duration = 0.0
				total_sleep_seconds += duration

		# Chaos classification
		chaos_config = data.get("chaos_config", {}) or {}
		fault_type = chaos_config.get("fault_type", chaos_config.get("type"))
		target_cfg = chaos_config.get("target") or {}
		target_mode = target_cfg.get("mode") or chaos_config.get("target_mode")
		category = classify_experiment(fault_type, target_mode)

		records.append(
			{
				"file": str(file),
				"model": model,
				"app_type": app_type,
				"category": category,
				"baseline_latency": baseline_lat,
				"chaos_latency": chaos_lat,
				"recovery_latency": recovery_lat,
				"baseline_success_rate": baseline_sr,
				"chaos_success_rate": chaos_sr,
				"recovery_success_rate": recovery_sr,
				"latency_degradation_pct": lat_deg,
				"success_degradation_pct": sr_deg,
				"latency_recovery_pct": lat_rec,
				"success_recovery_pct": sr_rec,
				"recovery_success": recovery_success,
				"location_identified": location_identified,
				"agent_steps": agent_steps,
				"agent_duration_minutes": agent_duration_seconds / 60.0,
				"agent_sleep_minutes": total_sleep_seconds / 60.0,
			}
		)

	df = pd.DataFrame.from_records(records)
	return df


def compute_adjusted_id_acc(group_df: pd.DataFrame) -> float:
	"""
	Adjusted location identification accuracy:
	Count only experiments with actual degradation (latency >1% OR success >1%).
	Returns percentage (0-100). If no degraded experiments, returns NaN.
	"""
	has_latency_deg = group_df["latency_degradation_pct"] > 1.0
	has_success_deg = group_df["success_degradation_pct"] > 1.0
	has_any_deg = has_latency_deg | has_success_deg

	den = int(has_any_deg.sum())
	if den == 0:
		return np.nan
	num = int((group_df["location_identified"] & has_any_deg).sum())
	return (num / den) * 100.0


def summarize_by_index_and_model(df: pd.DataFrame, index_col: str) -> pd.DataFrame:
	"""
	Produce a wide table where rows are index_col (e.g., app_type or category) and
	columns are per-model metric triplets: [ID Acc. (%), Success (%), Avg. Rounds].
	"""
	rows = []
	index_vals = sorted(df[index_col].dropna().unique().tolist())
	models = sorted(df["model"].dropna().unique().tolist())

	for idx_val in index_vals:
		row: Dict[str, Any] = {index_col: idx_val}
		sub = df[df[index_col] == idx_val]
		for m in models:
			g = sub[sub["model"] == m]
			if len(g) == 0:
				# Leave empty cells (NaN)
				row[f"{m} | ID Acc. (%)"] = np.nan
				row[f"{m} | Success (%)"] = np.nan
				row[f"{m} | Avg. Rounds"] = np.nan
				continue
			row[f"{m} | ID Acc. (%)"] = compute_adjusted_id_acc(g)
			row[f"{m} | Success (%)"] = g["recovery_success"].mean() * 100.0
			row[f"{m} | Avg. Rounds"] = g["agent_steps"].mean()
		rows.append(row)

	out = pd.DataFrame(rows)
	# Order columns: index, then models grouped by metric
	if not out.empty:
		cols = [index_col]
		models = [c for c in out.columns if c != index_col]
		# keep insertion order as created above
		out = out[ [index_col] + models ]
	return out


APP_MODEL_DF: Optional[pd.DataFrame] = None
FAULT_MODEL_DF: Optional[pd.DataFrame] = None


def main() -> None:
	root = Path(__file__).parent / "DATASET_LOGS"
	if not root.exists():
		print("DATASET_LOGS directory not found.")
		return

	df = load_experiments(root)
	if df.empty:
		print("No experiments found.")
		return

	# App × Model table
	app_table = summarize_by_index_and_model(df, index_col="app_type")
	# Fault Type × Model table (use notebook categories)
	fault_table = summarize_by_index_and_model(df, index_col="category")

	# Round for readability
	global APP_MODEL_DF, FAULT_MODEL_DF
	if not app_table.empty:
		app_rounded = app_table.copy()
		for c in app_rounded.columns:
			if c != "app_type":
				app_rounded[c] = app_rounded[c].astype(float).round(1)
		APP_MODEL_DF = app_rounded
	else:
		APP_MODEL_DF = pd.DataFrame()

	if not fault_table.empty:
		fault_rounded = fault_table.copy()
		for c in fault_rounded.columns:
			if c != "category":
				fault_rounded[c] = fault_rounded[c].astype(float).round(1)
		FAULT_MODEL_DF = fault_rounded
	else:
		FAULT_MODEL_DF = pd.DataFrame()

	with pd.option_context("display.max_columns", None, "display.width", 200):
		if APP_MODEL_DF is not None and not APP_MODEL_DF.empty:
			print("\n=== Agent Performance by Application Type × Model (DataFrame) ===")
			print(APP_MODEL_DF)
		else:
			print("\nNo data for App × Model table.")

		if FAULT_MODEL_DF is not None and not FAULT_MODEL_DF.empty:
			print("\n=== Agent Performance by Fault Type × Model (DataFrame) ===")
			print(FAULT_MODEL_DF)
		else:
			print("\nNo data for Fault Type × Model table.")


if __name__ == "__main__":
	main()


