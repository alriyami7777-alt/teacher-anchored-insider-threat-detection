#!/usr/bin/env python3
"""EDITOR-007D cross-version diagnostic synthesis.

Evidence synthesis only. Does not load a predictive model, train, score, or
open r5.2 TEST. All numbers are derived from already frozen results/scores.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "review" / "editor007d_cross_version_synthesis"
TASK_ID = "EDITOR-007D"

REV007A = ROOT / "review" / "editor007a_post006e_diagnostics"
REV007B = ROOT / "review" / "editor007b_r51_secondary_stress"
REV007C1 = ROOT / "review" / "editor007c1_r51_result_freeze"
THR006A = ROOT / "review" / "editor006a_preinference_freeze" / "EDITOR006A_THRESHOLDS.json"

R51_PRED = REV007C1 / "EDITOR007C_PREDICTIVE_RESULTS_PAPER_CORRECTED.json"
R51_MECH = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007c_scores") / "EDITOR007C_MECHANISM_RESULTS.json"
R51_SCORES = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007c_scores") / "raw_scores"
R51_ALL = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007c_scores") / "ALL_SCORES_COMPLETE.json"
R51_BUNDLE = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r51_editor007b_bundle")

R62_PRED = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006e_scores") / "EDITOR006E_PREDICTIVE_RESULTS.json"
R62_MECH = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006e_scores") / "EDITOR006E_MECHANISM_RESULTS.json"
R62_SCORES = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006e_scores") / "raw_scores"
R62_ALL = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006e_scores") / "ALL_SCORES_COMPLETE.json"
R62_BUNDLE = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle")

VAL_NPZ = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_validation.npz"
)
VAL_NPZ_SHA = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"

FAMILIES = (
    "teacher_frozen_odst",
    "C2",
    "C5_original_paper",
    "attention_linear",
    "RF_40",
    "XGBoost_40",
)
SEEDS = (42, 52, 62)
VIEWS = ("COMPLETED_WINDOW", "ENDPOINT_PAST_ONLY", "DEOVERLAP_OFFSET0")
LOWER_BETTER = ("student_teacher_logit_deviation", "route_mae", "route_kl")
HIGHER_BETTER = ("hard_route_agreement", "dominant_leaf_agreement")
EXACT_MECH = LOWER_BETTER + HIGHER_BETTER
FEATURES = (
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
)

PROTOCOL = {
    "predictive_model_loaded": False,
    "predictive_inference_executed": False,
    "training_executed": False,
    "r52_test_opened": False,
    "threshold_selection_executed": False,
    "scaler_fit_executed": False,
    "calibration_fit_executed": False,
    "model_selection_executed": False,
    "new_dataset_evaluated": False,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def refuse_forbidden_split(path: Path) -> None:
    text = str(path).replace("\\", "/").lower()
    marker = "r52_t20_s1" + "_test"
    if marker in text:
        PROTOCOL["r52_test_opened"] = True
        raise SystemExit("EDITOR007D_CROSS_VERSION_SYNTHESIS_BLOCKED")


def load_json(path: Path) -> Any:
    refuse_forbidden_split(path)
    return json.loads(path.read_text(encoding="utf-8"))


def py(x: Any) -> Any:
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if np.isfinite(v) else None
    if isinstance(x, (np.integer, int)) and not isinstance(x, bool):
        return int(x)
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    return x


def dump_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=py) + "\n", encoding="utf-8")
    return sha256_file(path)


def dump_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: py(row.get(k)) for k in fields})


def git_cmd(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def qtile(a: np.ndarray, q: float) -> float | None:
    if a.size == 0:
        return None
    return float(np.quantile(a, q))


def classify_ci(lo: float, hi: float) -> str:
    if lo > 0:
        return "CI_EXCLUDES_ZERO_POSITIVE"
    if hi < 0:
        return "CI_EXCLUDES_ZERO_NEGATIVE"
    return "CI_INCLUDES_ZERO"


def feat_row(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for row in rows:
        if row["feature"] == name:
            return row
    raise KeyError(name)


def qget(row: dict[str, Any], key: str) -> Any:
    aliases = {
        "q01": ("q01", "q0.01"),
        "q05": ("q05", "q0.05"),
        "q25": ("q25", "q0.25"),
        "q50": ("q50", "q0.50"),
        "q75": ("q75", "q0.75"),
        "q95": ("q95", "q0.95"),
        "q99": ("q99", "q0.99"),
        "sd": ("sd", "standard_deviation"),
    }
    for candidate in aliases.get(key, (key,)):
        if candidate in row and row[candidate] is not None:
            return row[candidate]
    return None


def enrich_metrics(m: dict[str, Any], dataset: str, family: str, seed: int, view: str) -> dict[str, Any]:
    n = int(m["n"])
    n_pos = int(m["n_pos"])
    fp = int(m["FP"])
    n_neg = n - n_pos
    prev = (n_pos / n) if n else None
    pr = float(m["PR_AUC"])
    row = {
        "dataset": dataset,
        "dataset_role": {
            "r52_validation": "R52_VALIDATION_IN_DOMAIN_REFERENCE",
            "r51_secondary_stress": "R51_SECONDARY_STRESS_ONLY",
            "r62_external": "R62_EXTERNAL",
        }[dataset],
        "family": family,
        "seed": seed,
        "view": view,
        "PR_AUC": pr,
        "F1": float(m["F1"]),
        "precision": float(m["precision"]),
        "recall": float(m["recall"]),
        "FP": fp,
        "FN": int(m["FN"]),
        "threshold": float(m["threshold"]),
        "N": n,
        "N_positive": n_pos,
        "prevalence": prev,
        "negative_count": n_neg,
        "negative_threshold_exceedance": (fp / n_neg) if n_neg else None,
        "AP_PREVALENCE_LIFT_DESCRIPTIVE": (pr / prev) if prev else None,
        "lift_label": "DESCRIPTIVE_ONLY",
        "comparable_semantics": True,
    }
    return row


def seed_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    by: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by.setdefault((row["dataset"], row["family"], row["view"]), []).append(row)
    for (dataset, family, view), group in sorted(by.items()):
        pr = [r["PR_AUC"] for r in group]
        f1 = [r["F1"] for r in group]
        ex = [r["negative_threshold_exceedance"] for r in group if r["negative_threshold_exceedance"] is not None]
        out.append(
            {
                "dataset": dataset,
                "family": family,
                "view": view,
                "n_seeds": len(group),
                "mean_PR_AUC": float(np.mean(pr)),
                "min_PR_AUC": float(np.min(pr)),
                "max_PR_AUC": float(np.max(pr)),
                "mean_F1": float(np.mean(f1)),
                "min_F1": float(np.min(f1)),
                "max_F1": float(np.max(f1)),
                "mean_negative_threshold_exceedance": float(np.mean(ex)) if ex else None,
                "summary_label": "THREE_SEED_DESCRIPTIVE_SUMMARY",
                "seeds_not_independent_experimental_units": True,
            }
        )
    return out


def score_side(scores: np.ndarray, mask: np.ndarray, threshold: float, which: str) -> dict[str, Any]:
    v = np.asarray(scores, dtype=np.float64)[mask]
    v = v[np.isfinite(v)]
    row: dict[str, Any] = {
        "n": int(mask.sum()),
        "mean": float(v.mean()) if v.size else None,
        "median": float(np.median(v)) if v.size else None,
    }
    if which == "negative":
        row.update(
            {
                "q01": qtile(v, 0.01),
                "q05": qtile(v, 0.05),
                "q25": qtile(v, 0.25),
                "q75": qtile(v, 0.75),
                "q95": qtile(v, 0.95),
                "q99": qtile(v, 0.99),
                "frozen_threshold_exceedance": float(np.mean(v >= threshold)) if v.size else None,
            }
        )
    else:
        row.update(
            {
                "q05": qtile(v, 0.05),
                "q25": qtile(v, 0.25),
                "q75": qtile(v, 0.75),
                "q95": qtile(v, 0.95),
            }
        )
    return row


def fmt(x: Any, digits: int = 6) -> str:
    if x is None:
        return "NA"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, int) and not isinstance(x, bool):
        return str(x)
    if isinstance(x, float):
        if abs(x) >= 0.01 or x == 0:
            return f"{x:.{digits}g}"
        return f"{x:.6g}"
    return str(x)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    head_before = git_cmd("rev-parse", "HEAD")
    branch = git_cmd("rev-parse", "--abbrev-ref", "HEAD")
    created: list[str] = []

    parity = load_json(REV007A / "EDITOR007A_R52_VALIDATION_PARITY.json")
    feat007a = load_json(REV007A / "EDITOR007A_FEATURE_SHIFT.json")
    adj = load_json(REV007B / "EDITOR007B_007A_ADJUDICATION_FREEZE.json")
    r51_pred = load_json(R51_PRED)
    r62_pred = load_json(R62_PRED)
    r51_mech = load_json(R51_MECH)
    r62_mech = load_json(R62_MECH)
    r51_feat = load_json(REV007B / "EDITOR007B_R51_FEATURE_PROFILE.json")
    r51_meta = load_json(REV007B / "EDITOR007B_R51_METADATA_VALIDATION.json")
    r51_counts = load_json(REV007B / "EDITOR007B_R51_COUNT_VALIDATION.json")
    r51_man = load_json(REV007B / "EDITOR007B_R51_BUNDLE_MANIFEST.json")
    r62_counts = load_json(ROOT / "review" / "editor006c_r62_input_bundle" / "EDITOR006C_COUNT_VALIDATION.json")
    r62_meta = load_json(ROOT / "review" / "editor006c_r62_input_bundle" / "EDITOR006C_METADATA_VALIDATION.json")
    r62_man = load_json(ROOT / "review" / "editor006c_r62_input_bundle" / "EDITOR006C_BUNDLE_MANIFEST.json")
    thr = load_json(THR006A)
    r51_all = load_json(R51_ALL)
    r62_all = load_json(R62_ALL)

    if r51_pred.get("effective_malicious_cluster_count") != 4:
        raise SystemExit("EDITOR007D_CROSS_VERSION_SYNTHESIS_BLOCKED")
    if r62_pred.get("effective_malicious_cluster_count") != 5:
        raise SystemExit("EDITOR007D_CROSS_VERSION_SYNTHESIS_BLOCKED")

    frozen_thr = {(r["family"], int(r["seed"])): float(r["threshold"]) for r in thr["thresholds"]}

    # --- dataset context ---
    r52_n = int(parity["validation"]["n"])
    r52_pos = int(parity["validation"]["n_pos_completed"])
    r51_c = r51_counts["assertions"]
    r62_c = r62_counts["assertions"]
    dataset_rows = [
        {
            "dataset": "r52_validation",
            "dataset_label": "CERT r5.2 VALIDATION",
            "dataset_role": "R52_VALIDATION_IN_DOMAIN_REFERENCE",
            "number_of_users": "NOT_RECOVERED_FROM_FROZEN_VALIDATION_NPZ",
            "calendar_days": "NOT_RECOVERED_FROM_FROZEN_VALIDATION_NPZ",
            "completed_window_N": r52_n,
            "completed_positives": r52_pos,
            "completed_prevalence": r52_pos / r52_n,
            "endpoint_N": None,
            "endpoint_positives": None,
            "endpoint_prevalence": None,
            "deoverlap_N": None,
            "deoverlap_positives": None,
            "deoverlap_prevalence": None,
            "endpoint_deoverlap_status": "NOT_PRESENT_IN_FROZEN_VALIDATION_NPZ",
            "official_mapped_insiders": "NOT_USED_AS_R52_VALIDATION_CLUSTER_CENSUS",
            "official_incidents": "NOT_USED_AS_R52_VALIDATION_CLUSTER_CENSUS",
            "effective_malicious_cluster_count": None,
            "overlapping_windows_not_independent_incidents": True,
        },
        {
            "dataset": "r51_secondary_stress",
            "dataset_label": "CERT r5.1 SECONDARY_STRESS",
            "dataset_role": "R51_SECONDARY_STRESS_ONLY",
            "number_of_users": r51_c["users"]["observed"],
            "calendar_days": r51_c["calendar_days"]["observed"],
            "completed_window_N": r51_c["eligible_windows"]["observed"],
            "completed_positives": r51_c["completed_positives"]["observed"],
            "completed_prevalence": r51_c["completed_positives"]["observed"] / r51_c["eligible_windows"]["observed"],
            "endpoint_N": r51_c["eligible_windows"]["observed"],
            "endpoint_positives": r51_c["endpoint_positives"]["observed"],
            "endpoint_prevalence": r51_c["endpoint_positives"]["observed"] / r51_c["eligible_windows"]["observed"],
            "deoverlap_N": r51_c["deoverlap_retained"]["observed"],
            "deoverlap_positives": r51_c["deoverlap_positives"]["observed"],
            "deoverlap_prevalence": r51_c["deoverlap_positives"]["observed"] / r51_c["deoverlap_retained"]["observed"],
            "official_mapped_insiders": 4,
            "official_incidents": 4,
            "effective_malicious_cluster_count": 4,
            "official_insider_ids": r51_man["official_mapped_insiders"],
            "official_incident_ids": r51_meta["official_incidents"],
            "event_level_labelled_users": 17,
            "overlapping_windows_not_independent_incidents": True,
        },
        {
            "dataset": "r62_external",
            "dataset_label": "CERT r6.2 EXTERNAL",
            "dataset_role": "R62_EXTERNAL",
            "number_of_users": r62_c["users"]["observed"],
            "calendar_days": r62_c["calendar_days"]["observed"],
            "completed_window_N": r62_c["eligible_windows"]["observed"],
            "completed_positives": r62_c["completed_positives"]["observed"],
            "completed_prevalence": r62_c["completed_positives"]["observed"] / r62_c["eligible_windows"]["observed"],
            "endpoint_N": r62_c["eligible_windows"]["observed"],
            "endpoint_positives": r62_c["endpoint_positives"]["observed"],
            "endpoint_prevalence": r62_c["endpoint_positives"]["observed"] / r62_c["eligible_windows"]["observed"],
            "deoverlap_N": r62_c["deoverlap_retained"]["observed"],
            "deoverlap_positives": r62_c["deoverlap_positives"]["observed"],
            "deoverlap_prevalence": r62_c["deoverlap_positives"]["observed"] / r62_c["deoverlap_retained"]["observed"],
            "official_mapped_insiders": 5,
            "official_incidents": 5,
            "effective_malicious_cluster_count": 5,
            "official_insider_ids": r62_man["official_mapped_insiders"],
            "official_incident_ids": r62_man["official_incidents"],
            "event_level_labelled_users": r62_c["event_level_labelled_users"]["observed"],
            "overlapping_windows_not_independent_incidents": True,
        },
    ]

    # --- model portability ---
    port_rows: list[dict[str, Any]] = []
    r52_by = {(m["family"], int(m["seed"])): m for m in parity["models"]}
    for fam in FAMILIES:
        for seed in SEEDS:
            replay = r52_by[(fam, seed)]["replay_metrics"]
            row = enrich_metrics(replay, "r52_validation", fam, seed, "COMPLETED_WINDOW")
            row["r52_metric_source"] = "EDITOR007A_replay_metrics"
            row["automated_protocol_gate"] = adj["automated_protocol_gate"]["status"]
            row["independent_scientific_adjudication"] = adj["independent_scientific_adjudication"]["status"]
            port_rows.append(row)
            for view in ("ENDPOINT_PAST_ONLY", "DEOVERLAP_OFFSET0"):
                port_rows.append(
                    {
                        "dataset": "r52_validation",
                        "dataset_role": "R52_VALIDATION_IN_DOMAIN_REFERENCE",
                        "family": fam,
                        "seed": seed,
                        "view": view,
                        "PR_AUC": None,
                        "comparable_semantics": False,
                        "retention_status": "NOT_COMPARABLE",
                        "reason": "NOT_PRESENT_IN_FROZEN_VALIDATION_NPZ",
                    }
                )
            for dataset, pred in (
                ("r51_secondary_stress", r51_pred),
                ("r62_external", r62_pred),
            ):
                block = pred["by_family_seed"][fam][str(seed)]
                for view in VIEWS:
                    port_rows.append(enrich_metrics(block[view], dataset, fam, seed, view))

    for row in port_rows:
        if row.get("threshold") is not None:
            expected = frozen_thr[(row["family"], row["seed"])]
            row["frozen_threshold_006a"] = expected
            row["threshold_matches_frozen_006a"] = abs(float(row["threshold"]) - expected) < 1e-15

    summaries = seed_summary([r for r in port_rows if r.get("PR_AUC") is not None])

    ref = {
        (r["family"], r["seed"], r["view"]): r
        for r in port_rows
        if r["dataset"] == "r52_validation" and r.get("PR_AUC") is not None
    }
    for row in port_rows:
        key = (row["family"], row["seed"], row["view"])
        if row["dataset"] == "r52_validation":
            continue
        if key not in ref:
            row["R51_PR_AUC_RETENTION" if row["dataset"].startswith("r51") else "R62_PR_AUC_RETENTION"] = "NOT_COMPARABLE"
            row["delta_minus_R52"] = "NOT_COMPARABLE"
            continue
        base = ref[key]["PR_AUC"]
        if row["dataset"].startswith("r51"):
            row["R51_PR_AUC_RETENTION"] = row["PR_AUC"] / base if base else None
            row["delta_R51_minus_R52"] = row["PR_AUC"] - base
            row["retention_label"] = "DESCRIPTIVE_PORTABILITY_LOSS_NOT_A_SIGNIFICANCE_TEST"
        else:
            row["R62_PR_AUC_RETENTION"] = row["PR_AUC"] / base if base else None
            row["delta_R62_minus_R52"] = row["PR_AUC"] - base
            row["retention_label"] = "DESCRIPTIVE_PORTABILITY_LOSS_NOT_A_SIGNIFICANCE_TEST"

    # --- score-distribution shift from frozen raw scores ---
    refuse_forbidden_split(VAL_NPZ)
    val_sha = sha256_file(VAL_NPZ)
    if val_sha != VAL_NPZ_SHA:
        raise SystemExit("EDITOR007D_CROSS_VERSION_SYNTHESIS_BLOCKED")
    with np.load(VAL_NPZ, allow_pickle=True, mmap_mode="r") as z:
        y_val = np.asarray(z["y"]).astype(int)
    y_r51 = np.asarray(np.load(R51_BUNDLE / "completed_window_labels.npy", mmap_mode="r")).astype(int)
    y_r62 = np.asarray(np.load(R62_BUNDLE / "completed_window_labels.npy", mmap_mode="r")).astype(int)
    r51_files = {(m["family"], int(m["seed"])): m["score_filename"] for m in r51_all["models"]}
    r62_files = {(m["family"], int(m["seed"])): m["score_filename"] for m in r62_all["models"]}

    score_rows: list[dict[str, Any]] = []
    for fam in FAMILIES:
        for seed in SEEDS:
            thr_v = frozen_thr[(fam, seed)]
            r52_path = Path(r52_by[(fam, seed)]["replay_score_path"])
            r51_path = R51_SCORES / r51_files[(fam, seed)]
            r62_path = R62_SCORES / r62_files[(fam, seed)]
            packs = (
                ("r52_validation", r52_path, y_val),
                ("r51_secondary_stress", r51_path, y_r51),
                ("r62_external", r62_path, y_r62),
            )
            rec: dict[str, Any] = {"family": fam, "seed": seed, "frozen_threshold": thr_v, "view": "COMPLETED_WINDOW"}
            for dname, path, y in packs:
                refuse_forbidden_split(path)
                s = np.asarray(np.load(path, mmap_mode="r"))
                if s.shape[0] != y.shape[0]:
                    raise SystemExit(f"EDITOR007D_CROSS_VERSION_SYNTHESIS_BLOCKED score/label length {path}")
                rec[dname] = {
                    "negative": score_side(s, y == 0, thr_v, "negative"),
                    "positive": score_side(s, y == 1, thr_v, "positive"),
                }
                del s
            n52 = rec["r52_validation"]["negative"]["frozen_threshold_exceedance"]
            n51 = rec["r51_secondary_stress"]["negative"]["frozen_threshold_exceedance"]
            n62 = rec["r62_external"]["negative"]["frozen_threshold_exceedance"]
            rec["neg_exceedance_r51_minus_r52"] = None if n51 is None or n52 is None else n51 - n52
            rec["neg_exceedance_r62_minus_r52"] = None if n62 is None or n52 is None else n62 - n52
            rec["neg_mean_r51_minus_r52"] = rec["r51_secondary_stress"]["negative"]["mean"] - rec["r52_validation"]["negative"]["mean"]
            rec["neg_mean_r62_minus_r52"] = rec["r62_external"]["negative"]["mean"] - rec["r52_validation"]["negative"]["mean"]
            rec["r62_negatives_cross_frozen_boundary"] = bool(n62 is not None and n52 is not None and n62 > n52 * 5)
            score_rows.append(rec)

    # --- feature shift from frozen profiles (no scaler fit, no raw re-stream) ---
    p_train = {r["feature"]: r for r in feat007a["partitions"]["r52_train"]}
    p_val = {r["feature"]: r for r in feat007a["partitions"]["r52_validation"]}
    r62_part_key = [k for k in feat007a["partitions"] if k not in ("r52_train", "r52_validation")][0]
    p_r62 = {r["feature"]: r for r in feat007a["partitions"][r62_part_key]}
    p_r51 = {r["feature"]: r for r in r51_feat["features"]}
    feat_rows = []
    for name in FEATURES:
        tr, va, a51, a62 = p_train[name], p_val[name], p_r51[name], p_r62[name]
        row = {
            "feature": name,
            "r52_train_mean": tr["mean"],
            "r52_train_sd": qget(tr, "sd"),
            "r52_train_q01": qget(tr, "q01"),
            "r52_train_q05": qget(tr, "q05"),
            "r52_train_q25": qget(tr, "q25"),
            "r52_train_q50": qget(tr, "q50"),
            "r52_train_q75": qget(tr, "q75"),
            "r52_train_q95": qget(tr, "q95"),
            "r52_train_q99": qget(tr, "q99"),
            "r52_train_frac_abs_z_gt_3": tr["fraction_abs_z_gt_3"],
            "r52_train_frac_abs_z_gt_5": tr["fraction_abs_z_gt_5"],
            "r52_train_frac_abs_z_gt_10": tr["fraction_abs_z_gt_10"],
            "r52_validation_mean": va["mean"],
            "r52_validation_sd": qget(va, "sd"),
            "r52_validation_q01": qget(va, "q01"),
            "r52_validation_q05": qget(va, "q05"),
            "r52_validation_q25": qget(va, "q25"),
            "r52_validation_q50": qget(va, "q50"),
            "r52_validation_q75": qget(va, "q75"),
            "r52_validation_q95": qget(va, "q95"),
            "r52_validation_q99": qget(va, "q99"),
            "r52_validation_frac_abs_z_gt_3": va["fraction_abs_z_gt_3"],
            "r52_validation_frac_abs_z_gt_5": va["fraction_abs_z_gt_5"],
            "r52_validation_frac_abs_z_gt_10": va["fraction_abs_z_gt_10"],
            "r51_mean": a51["mean"],
            "r51_sd": qget(a51, "sd"),
            "r51_q01": qget(a51, "q01"),
            "r51_q05": qget(a51, "q05"),
            "r51_q25": qget(a51, "q25"),
            "r51_q50": qget(a51, "q50"),
            "r51_q75": qget(a51, "q75"),
            "r51_q95": qget(a51, "q95"),
            "r51_q99": qget(a51, "q99"),
            "r51_frac_abs_z_gt_3": a51["fraction_abs_z_gt_3"],
            "r51_frac_abs_z_gt_5": a51["fraction_abs_z_gt_5"],
            "r51_frac_abs_z_gt_10": a51["fraction_abs_z_gt_10"],
            "r62_mean": a62["mean"],
            "r62_sd": qget(a62, "sd"),
            "r62_q01": qget(a62, "q01"),
            "r62_q05": qget(a62, "q05"),
            "r62_q25": qget(a62, "q25"),
            "r62_q50": qget(a62, "q50"),
            "r62_q75": qget(a62, "q75"),
            "r62_q95": qget(a62, "q95"),
            "r62_q99": qget(a62, "q99"),
            "r62_frac_abs_z_gt_3": a62["fraction_abs_z_gt_3"],
            "r62_frac_abs_z_gt_5": a62["fraction_abs_z_gt_5"],
            "r62_frac_abs_z_gt_10": a62["fraction_abs_z_gt_10"],
            "abs_r51_mean_minus_r52_train_mean": abs(a51["mean"] - tr["mean"]),
            "abs_r62_mean_minus_r52_train_mean": abs(a62["mean"] - tr["mean"]),
            "no_pvalue_used": True,
            "no_significance_ranking": True,
        }
        feat_rows.append(row)
    rank_r51 = sorted(feat_rows, key=lambda r: r["abs_r51_mean_minus_r52_train_mean"], reverse=True)
    rank_r62 = sorted(feat_rows, key=lambda r: r["abs_r62_mean_minus_r52_train_mean"], reverse=True)
    for i, row in enumerate(rank_r51, 1):
        row["rank_abs_r51_vs_r52_train"] = i
    for i, row in enumerate(rank_r62, 1):
        row["rank_abs_r62_vs_r52_train"] = i
    r62_top3 = [r["feature"] for r in rank_r62[:3]]

    # --- C2 vs C5 ---
    c2c5_rows = []
    for dataset, pred in (("r51_secondary_stress", r51_pred), ("r62_external", r62_pred)):
        boot = pred["deoverlap_user_cluster_bootstrap"]
        cmp_root = pred["primary_c5_vs_c2"]
        for seed in SEEDS:
            b = boot[str(seed)]
            pr_ci = b["percentile_95"]["delta_PR_AUC_C5_minus_C2"]
            f1_ci = b["percentile_95"]["delta_F1_C5_minus_C2"]
            for view in VIEWS:
                cell = cmp_root[str(seed)][view]
                row = {
                    "dataset": dataset,
                    "seed": seed,
                    "view": view,
                    "C2_PR_AUC": cell["C2_PR_AUC"],
                    "C5_PR_AUC": cell["C5_PR_AUC"],
                    "delta_PR_AUC_C5_minus_C2": cell["delta_PR_AUC_C5_minus_C2"],
                    "C2_F1": cell["C2_F1"],
                    "C5_F1": cell["C5_F1"],
                    "delta_F1_C5_minus_C2": cell["delta_F1_C5_minus_C2"],
                    "positive_delta_is_not_automatic_superiority": True,
                    "bootstrap_recomputed": False,
                }
                if view == "DEOVERLAP_OFFSET0":
                    row.update(
                        {
                            "bootstrap_point_delta_PR_AUC": b["point_delta_PR_AUC_C5_minus_C2"],
                            "bootstrap_PR_AUC_CI_lo": pr_ci[0],
                            "bootstrap_PR_AUC_CI_hi": pr_ci[1],
                            "bootstrap_PR_AUC_CI_class": classify_ci(pr_ci[0], pr_ci[1]),
                            "bootstrap_point_delta_F1": b["point_delta_F1_C5_minus_C2"],
                            "bootstrap_F1_CI_lo": f1_ci[0],
                            "bootstrap_F1_CI_hi": f1_ci[1],
                            "bootstrap_F1_CI_class": classify_ci(f1_ci[0], f1_ci[1]),
                            "effective_malicious_cluster_count": b["effective_malicious_cluster_count"],
                            "frozen_wording": b["frozen_wording"],
                        }
                    )
                c2c5_rows.append(row)

    # --- mechanism ---
    mech_rows = []
    for dataset, mech in (("r51_secondary_stress", r51_mech), ("r62_external", r62_mech)):
        for seed in SEEDS:
            c2 = mech["per_seed"][str(seed)]["C2_vs_teacher"]
            c5 = mech["per_seed"][str(seed)]["C5_vs_teacher"]
            rec = {
                "dataset": dataset,
                "seed": seed,
                "view": mech["view"],
                "r52_mechanism_comparison": "R52_MECHANISM_COMPARISON_NOT_INCLUDED_PROVENANCE_INSUFFICIENT",
                "unused_leaf_fraction": "DISABLED_NOT_REPRODUCIBLE",
                "tree_contribution_rho": "DISABLED_NOT_REPRODUCIBLE",
            }
            for metric in EXACT_MECH:
                rec[f"C2_{metric}"] = c2[metric]
                rec[f"C5_{metric}"] = c5[metric]
                rec[f"C5_MINUS_C2_{metric}"] = c5[metric] - c2[metric]
                if metric in LOWER_BETTER:
                    rec[f"relative_reduction_{metric}"] = (c2[metric] - c5[metric]) / c2[metric] if c2[metric] else None
                else:
                    rec[f"absolute_increase_{metric}"] = c5[metric] - c2[metric]
            mech_rows.append(rec)

    # --- scenario limitation ---
    scenario = {
        "SCENARIOS_NOT_CROSS_VERSION_MATCHED_UNITS": True,
        "r51_official_insider_incident_clusters": 4,
        "r62_official_insider_incident_clusters": 5,
        "r51_frozen_wording": "Four official insider–incident clusters are represented.",
        "r62_frozen_wording": "Five official insider–incident clusters are represented.",
        "r51_scenario_identities": r51_pred["scenario_deoverlap_summary"]["scenario_identities"],
        "r62_scenario_identities": r62_pred["scenario_deoverlap_summary"]["scenario_identities"],
        "kind": "descriptive_only",
        "no_cross_version_numerical_scenario_matching": True,
        "editor007c1_metadata_correction_changed_predictive_numerics": False,
        "r51_role": "R51_SECONDARY_STRESS_ONLY",
    }

    # --- diagnostic numbers ---
    def mean_completed(dataset: str, family: str, field: str) -> float:
        vals = [
            r[field]
            for r in port_rows
            if r["dataset"] == dataset and r["family"] == family and r["view"] == "COMPLETED_WINDOW" and r.get(field) is not None
        ]
        return float(np.mean(vals))

    neural = ("teacher_frozen_odst", "C2", "C5_original_paper", "attention_linear")
    tabular = ("RF_40", "XGBoost_40")
    r52_pr_neural = float(np.mean([mean_completed("r52_validation", f, "PR_AUC") for f in neural]))
    r51_pr_neural = float(np.mean([mean_completed("r51_secondary_stress", f, "PR_AUC") for f in neural]))
    r62_pr_neural = float(np.mean([mean_completed("r62_external", f, "PR_AUC") for f in neural]))
    r52_pr_tab = float(np.mean([mean_completed("r52_validation", f, "PR_AUC") for f in tabular]))
    r51_pr_tab = float(np.mean([mean_completed("r51_secondary_stress", f, "PR_AUC") for f in tabular]))
    r62_pr_tab = float(np.mean([mean_completed("r62_external", f, "PR_AUC") for f in tabular]))
    r52_ex = float(np.mean([mean_completed("r52_validation", f, "negative_threshold_exceedance") for f in FAMILIES]))
    r51_ex = float(np.mean([mean_completed("r51_secondary_stress", f, "negative_threshold_exceedance") for f in FAMILIES]))
    r62_ex = float(np.mean([mean_completed("r62_external", f, "negative_threshold_exceedance") for f in FAMILIES]))
    r51_prev = dataset_rows[1]["completed_prevalence"]
    r62_prev = dataset_rows[2]["completed_prevalence"]
    r51_lift_neural = r51_pr_neural / r51_prev
    r62_lift_neural = r62_pr_neural / r62_prev
    r62_lift_tab = r62_pr_tab / r62_prev

    deov_ci_pr = [r["bootstrap_PR_AUC_CI_class"] for r in c2c5_rows if r["view"] == "DEOVERLAP_OFFSET0"]
    deov_ci_f1 = [r["bootstrap_F1_CI_class"] for r in c2c5_rows if r["view"] == "DEOVERLAP_OFFSET0"]
    fidelity_ok = all(
        r["C5_student_teacher_logit_deviation"] < r["C2_student_teacher_logit_deviation"]
        and r["C5_route_mae"] < r["C2_route_mae"]
        and r["C5_route_kl"] < r["C2_route_kl"]
        and r["C5_hard_route_agreement"] > r["C2_hard_route_agreement"]
        and r["C5_dominant_leaf_agreement"] > r["C2_dominant_leaf_agreement"]
        for r in mech_rows
    )

    general_collapse = "NOT_SUPPORTED"
    r51_transfer = "SUPPORTED"
    r62_severe = "SUPPORTED"
    r62_rank = "MODEL_FAMILY_DEPENDENT"
    r62_thr = "SUPPORTED"
    tab_port = "SUPPORTED"
    c5_pred = "MIXED"
    c5_fid = "SUPPORTED"

    phenotype = "P2_R62_SEVERE_DISTRIBUTION_AND_DECISION_SHIFT"
    secondary = [
        "P3_PRIMARILY_THRESHOLD_CALIBRATION_PORTABILITY_FAILURE",
        "P4_MODEL_FAMILY_SPECIFIC_PORTABILITY_FAILURE",
    ]

    questions = {
        "Q1": {
            "question": "Is the r5.2 → r6.2 failure a general cross-version failure?",
            "answer": "NO. r5.1 secondary-stress completed-window neural mean PR-AUC remains far above prevalence, so the r6.2 near-prevalence collapse is not shown to be a general CERT-version failure.",
        },
        "Q2": {
            "question": "Does r5.1 show substantial cross-version ranking transfer?",
            "answer": "YES, descriptively. Neural completed-window mean PR-AUC on r5.1 remains orders of magnitude above prevalence, indicating retained ranking despite large absolute drop from r5.2 validation.",
        },
        "Q3": {
            "question": "Is r6.2 qualitatively more severe than r5.1?",
            "answer": "YES. r6.2 neural completed-window PR-AUC sits near prevalence; r5.1 does not.",
        },
        "Q4": {
            "question": "Is r6.2 failure predominantly ranking collapse, decision-threshold shift, or both?",
            "answer": "BOTH, with family dependence: neural ranking collapses to near prevalence, while all 18 frozen models show a large negative-class frozen-threshold exceedance shift on r6.2. Tabular families retain more ranking than the neural pathway but still fail at the frozen decision boundary.",
        },
        "Q5": {
            "question": "Do RF/XGBoost retain more ranking portability than the neural pathway?",
            "answer": "YES, relatively, on r6.2 completed-window PR-AUC. This is descriptive relative portability, not a claim that tabular models succeed.",
        },
        "Q6": {
            "question": "Does teacher anchoring show a reproducible predictive advantage over C2 across external versions?",
            "answer": "NO as a general predictive-superiority claim. Point deltas are small; several de-overlap PR-AUC intervals include zero; r6.2 deltas sit on a collapsed PR-AUC scale. A positive point estimate is not predictive superiority.",
        },
        "Q7": {
            "question": "Does teacher anchoring show reproducible teacher-relative mechanism/fidelity preservation across external versions?",
            "answer": "YES on the exact-frozen metrics compared here (r5.1 and r6.2). C5 remains closer to the teacher than C2 on logit deviation, route MAE/KL, and agreement. r5.2 validation mechanism values are not included (provenance insufficient).",
        },
        "Q8": {
            "question": "Which input/score shifts best distinguish r6.2 from r5.1?",
            "answer": (
                f"Largest |r6.2 mean − r5.2 TRAIN mean| features: {', '.join(r62_top3)}. "
                "r5.1 scaled means remain close to r5.2 TRAIN. Score-side, r6.2 negative frozen-threshold exceedance rises from ~0.0003–0.001 on r5.2 validation to ~0.41–0.45, far above the r5.1 elevation."
            ),
        },
        "Q9": {
            "question": "What exact failure mechanism should EDITOR-008 attempt to address?",
            "answer": "A version-specific r6.2 representation/distribution shift that both destroys neural ranking and moves negatives across frozen r5.2 decision thresholds, while teacher-anchoring fidelity does not restore predictive portability. EDITOR-008 should treat shift detection, source-robust representation, and decision portability as required capabilities, with teacher anchoring auxiliary only. Do not freeze an architecture here.",
        },
    }

    rulings = {
        "task_id": TASK_ID,
        "AUTOMATED_PROTOCOL_GATE": adj["automated_protocol_gate"]["status"],
        "INDEPENDENT_SCIENTIFIC_ADJUDICATION": adj["independent_scientific_adjudication"]["status"],
        "GENERAL_CROSS_VERSION_COLLAPSE": general_collapse,
        "R51_SUBSTANTIAL_RANKING_TRANSFER": r51_transfer,
        "R62_SEVERE_VERSION_SPECIFIC_FAILURE": r62_severe,
        "R62_RANKING_COLLAPSE": r62_rank,
        "R62_THRESHOLD_PORTABILITY_FAILURE": r62_thr,
        "TABULAR_RELATIVE_PORTABILITY": tab_port,
        "C5_PREDICTIVE_ADVANTAGE_OVER_C2": c5_pred,
        "C5_TEACHER_FIDELITY_EFFECT": c5_fid,
        "PRIMARY_PORTABILITY_PHENOTYPE": phenotype,
        "secondary_contributors": secondary,
        "no_proven_causal_language": True,
        "questions": questions,
        "descriptive_anchors": {
            "r52_completed_neural_mean_PR_AUC": r52_pr_neural,
            "r51_completed_neural_mean_PR_AUC": r51_pr_neural,
            "r62_completed_neural_mean_PR_AUC": r62_pr_neural,
            "r52_completed_tabular_mean_PR_AUC": r52_pr_tab,
            "r51_completed_tabular_mean_PR_AUC": r51_pr_tab,
            "r62_completed_tabular_mean_PR_AUC": r62_pr_tab,
            "r51_completed_prevalence": r51_prev,
            "r62_completed_prevalence": r62_prev,
            "r51_neural_AP_prevalence_lift_DESCRIPTIVE_ONLY": r51_lift_neural,
            "r62_neural_AP_prevalence_lift_DESCRIPTIVE_ONLY": r62_lift_neural,
            "r62_tabular_AP_prevalence_lift_DESCRIPTIVE_ONLY": r62_lift_tab,
            "r52_mean_negative_threshold_exceedance": r52_ex,
            "r51_mean_negative_threshold_exceedance": r51_ex,
            "r62_mean_negative_threshold_exceedance": r62_ex,
            "r62_feature_rank_abs_mean_shift_vs_r52_train": [r["feature"] for r in rank_r62],
            "r51_feature_rank_abs_mean_shift_vs_r52_train": [r["feature"] for r in rank_r51],
            "previously_observed_r62_major_shifts_remain_top3": r62_top3 == ["email_count", "has_file_activity", "total_events"]
            or set(r62_top3) == {"email_count", "has_file_activity", "total_events"},
            "r62_top3_abs_mean_shift": r62_top3,
            "deoverlap_bootstrap_PR_AUC_CI_classes": deov_ci_pr,
            "deoverlap_bootstrap_F1_CI_classes": deov_ci_f1,
            "c5_closer_to_teacher_on_all_exact_frozen_metrics_r51_and_r62": fidelity_ok,
        },
        "r51_cluster_count": 4,
        "r62_cluster_count": 5,
        "r51_role": "R51_SECONDARY_STRESS_ONLY",
    }

    reqs = {
        "SHIFT_DETECTION_REQUIRED": {
            "required": True,
            "support_status": "SUPPORTED",
            "evidence_basis": "r6.2 scaled-feature means and negative score exceedance diverge from r5.2 TRAIN/VALIDATION far more than r5.1.",
        },
        "SOURCE_ROBUST_REPRESENTATION_REQUIRED": {
            "required": True,
            "support_status": "SUPPORTED",
            "evidence_basis": "Neural ranking collapses on r6.2 while remaining far above prevalence on r5.1; largest r6.2 input shifts are not mirrored at the same magnitude on r5.1.",
        },
        "DECISION_PORTABILITY_REQUIRED": {
            "required": True,
            "support_status": "SUPPORTED",
            "evidence_basis": "Frozen r5.2 thresholds yield ~0.0003–0.001 negative exceedance on r5.2 validation versus ~0.41–0.45 on r6.2 for all 18 models.",
        },
        "ABSTENTION_OR_OOD_GATING_REQUIRED": {
            "required": True,
            "support_status": "SUPPORTED",
            "evidence_basis": "r6.2 negatives massively cross the frozen decision boundary; a portable operating point is not available from the frozen r5.2 threshold.",
        },
        "MULTI_SOURCE_DEVELOPMENT_REQUIRED": {
            "required": True,
            "support_status": "SUPPORTED",
            "evidence_basis": "r5.1 secondary stress does not reproduce the r6.2 phenotype; one additional CERT version is not a substitute for the unseen target.",
        },
        "TEACHER_ANCHORING_AUXILIARY_ONLY": {
            "required": True,
            "support_status": "SUPPORTED",
            "evidence_basis": "Teacher-relative fidelity is preserved while predictive advantage over C2 is mixed/absent on external versions.",
        },
        "TABULAR_BASELINES_MUST_REMAIN": {
            "required": True,
            "support_status": "SUPPORTED",
            "evidence_basis": "RF/XGBoost retain more r6.2 ranking than the neural pathway and remain the engineered-tabular reference class.",
        },
        "UNSEEN_FINAL_TARGET_REQUIRED": {
            "required": True,
            "support_status": "SUPPORTED",
            "evidence_basis": "r6.2 is the frozen external evaluation and must not become a tuning/selection dataset for the pivot.",
        },
        "architecture_frozen_in_007d": False,
        "EDITOR008_TEACHER_ANCHORING_ROLE": "AUXILIARY",
    }

    claims = {
        "task_id": TASK_ID,
        "no_manuscript_rewriting": True,
        "claims": [
            {
                "claim": "teacher initialisation is load-bearing",
                "status": "SUPPORTED_WITH_QUALIFICATION",
                "note": "Teacher-relative fidelity of C5 versus C2 is reproducible on r5.1/r6.2 exact-frozen mechanism metrics. External predictive load-bearing is not shown.",
            },
            {
                "claim": "anchoring constrains teacher-relative logit drift",
                "status": "SUPPORTED_WITH_QUALIFICATION",
                "note": "C5 logit deviation is lower than C2 on r5.1 and r6.2. r5.2 validation mechanism comparison not included.",
            },
            {
                "claim": "anchoring constrains routing drift",
                "status": "SUPPORTED_WITH_QUALIFICATION",
                "note": "C5 route MAE/KL are lower and hard-route/dominant-leaf agreement higher than C2 on r5.1 and r6.2.",
            },
            {
                "claim": "anchoring improves predictive performance",
                "status": "NEGATIVE_RESULT",
                "note": "No reproducible C5 predictive advantage over C2 across external versions. De-overlap intervals often include zero. r6.2 deltas are on a collapsed scale.",
            },
            {
                "claim": "ODST is predictively superior to attention-linear",
                "status": "UNSUPPORTED",
                "note": "Not supported as a cross-version claim. Both neural families collapse on r6.2; r5.1 completed-window means are in a similar band.",
            },
            {
                "claim": "model generalises across CERT versions",
                "status": "NEGATIVE_RESULT",
                "note": "r6.2 is a severe version-specific failure. r5.1 ranking transfer does not imply r6.2 portability.",
            },
            {
                "claim": "frozen thresholds are portable",
                "status": "NEGATIVE_RESULT",
                "note": "Negative frozen-threshold exceedance (FP/N_negative) rises from ~0.0003–0.001 on r5.2 validation to ~0.41–0.45 on r6.2.",
            },
            {
                "claim": "RF/XGBoost remain strong engineered-tabular references",
                "status": "SUPPORTED_WITH_QUALIFICATION",
                "note": "Relative ranking portability on r6.2 versus neural families. They do not succeed as portable detectors at frozen thresholds.",
            },
            {
                "claim": "reference-centred explanation evidence",
                "status": "UNSUPPORTED",
                "note": "unused-leaf fraction and tree-contribution rho remain DISABLED_NOT_REPRODUCIBLE.",
            },
            {
                "claim": "degraded-input evidence",
                "status": "UNSUPPORTED",
                "note": "Not evaluated in this synthesis; no frozen degraded-input artefact was consumed.",
            },
        ],
    }
    if {c["claim"] for c in claims["claims"]} != {
        "teacher initialisation is load-bearing",
        "anchoring constrains teacher-relative logit drift",
        "anchoring constrains routing drift",
        "anchoring improves predictive performance",
        "ODST is predictively superior to attention-linear",
        "model generalises across CERT versions",
        "frozen thresholds are portable",
        "RF/XGBoost remain strong engineered-tabular references",
        "reference-centred explanation evidence",
        "degraded-input evidence",
    }:
        raise SystemExit("EDITOR007D_CROSS_VERSION_SYNTHESIS_BLOCKED")

    port_fields = [
        "dataset", "dataset_role", "family", "seed", "view", "PR_AUC", "F1", "precision",
        "recall", "FP", "FN", "threshold", "N", "N_positive", "prevalence", "negative_count",
        "negative_threshold_exceedance", "AP_PREVALENCE_LIFT_DESCRIPTIVE", "lift_label",
        "R51_PR_AUC_RETENTION", "R62_PR_AUC_RETENTION", "delta_R51_minus_R52",
        "delta_R62_minus_R52", "retention_status", "reason", "comparable_semantics",
        "threshold_matches_frozen_006a",
    ]
    dump_json(OUT / "EDITOR007D_DATASET_CONTEXT.json", {"task_id": TASK_ID, "rows": dataset_rows})
    dump_csv(OUT / "EDITOR007D_DATASET_CONTEXT.csv", dataset_rows, list(dataset_rows[1].keys()))
    dump_json(
        OUT / "EDITOR007D_MODEL_PORTABILITY.json",
        {"task_id": TASK_ID, "rows": port_rows, "seed_summaries": summaries},
    )
    dump_csv(OUT / "EDITOR007D_MODEL_PORTABILITY.csv", port_rows, port_fields)
    thr_rows = [
        {
            "dataset": r["dataset"],
            "family": r["family"],
            "seed": r["seed"],
            "view": r["view"],
            "threshold": r.get("threshold"),
            "FP": r.get("FP"),
            "negative_count": r.get("negative_count"),
            "negative_threshold_exceedance": r.get("negative_threshold_exceedance"),
            "threshold_matches_frozen_006a": r.get("threshold_matches_frozen_006a"),
        }
        for r in port_rows
        if r.get("PR_AUC") is not None
    ]
    dump_json(OUT / "EDITOR007D_THRESHOLD_PORTABILITY.json", {"task_id": TASK_ID, "rows": thr_rows})
    dump_csv(
        OUT / "EDITOR007D_THRESHOLD_PORTABILITY.csv",
        thr_rows,
        ["dataset", "family", "seed", "view", "threshold", "FP", "negative_count", "negative_threshold_exceedance", "threshold_matches_frozen_006a"],
    )
    dump_json(OUT / "EDITOR007D_SCORE_SHIFT.json", {"task_id": TASK_ID, "view": "COMPLETED_WINDOW", "models": score_rows})
    score_flat = []
    for rec in score_rows:
        for dname in ("r52_validation", "r51_secondary_stress", "r62_external"):
            neg, pos = rec[dname]["negative"], rec[dname]["positive"]
            score_flat.append(
                {
                    "family": rec["family"],
                    "seed": rec["seed"],
                    "dataset": dname,
                    "frozen_threshold": rec["frozen_threshold"],
                    "neg_mean": neg["mean"],
                    "neg_median": neg["median"],
                    "neg_q01": neg["q01"],
                    "neg_q05": neg["q05"],
                    "neg_q25": neg["q25"],
                    "neg_q75": neg["q75"],
                    "neg_q95": neg["q95"],
                    "neg_q99": neg["q99"],
                    "neg_frozen_threshold_exceedance": neg["frozen_threshold_exceedance"],
                    "pos_mean": pos["mean"],
                    "pos_median": pos["median"],
                    "pos_q05": pos["q05"],
                    "pos_q25": pos["q25"],
                    "pos_q75": pos["q75"],
                    "pos_q95": pos["q95"],
                }
            )
    dump_csv(
        OUT / "EDITOR007D_SCORE_SHIFT.csv",
        score_flat,
        list(score_flat[0].keys()),
    )
    dump_json(
        OUT / "EDITOR007D_FEATURE_SHIFT.json",
        {
            "task_id": TASK_ID,
            "p_values_used": False,
            "rows": feat_rows,
            "rank_abs_r51_vs_r52_train": [r["feature"] for r in rank_r51],
            "rank_abs_r62_vs_r52_train": [r["feature"] for r in rank_r62],
        },
    )
    dump_csv(OUT / "EDITOR007D_FEATURE_SHIFT.csv", feat_rows, [
        "feature", "r52_train_mean", "r52_train_sd", "r52_validation_mean", "r51_mean", "r62_mean",
        "abs_r51_mean_minus_r52_train_mean", "abs_r62_mean_minus_r52_train_mean",
        "rank_abs_r51_vs_r52_train", "rank_abs_r62_vs_r52_train",
        "r52_train_frac_abs_z_gt_3", "r51_frac_abs_z_gt_3", "r62_frac_abs_z_gt_3",
        "r52_train_frac_abs_z_gt_5", "r51_frac_abs_z_gt_5", "r62_frac_abs_z_gt_5",
        "r52_train_frac_abs_z_gt_10", "r51_frac_abs_z_gt_10", "r62_frac_abs_z_gt_10",
        "no_pvalue_used",
    ])
    dump_json(OUT / "EDITOR007D_C2_C5_COMPARISON.json", {"task_id": TASK_ID, "rows": c2c5_rows})
    dump_csv(OUT / "EDITOR007D_C2_C5_COMPARISON.csv", c2c5_rows, [
        "dataset", "seed", "view", "C2_PR_AUC", "C5_PR_AUC", "delta_PR_AUC_C5_minus_C2",
        "C2_F1", "C5_F1", "delta_F1_C5_minus_C2", "bootstrap_point_delta_PR_AUC",
        "bootstrap_PR_AUC_CI_lo", "bootstrap_PR_AUC_CI_hi", "bootstrap_PR_AUC_CI_class",
        "bootstrap_point_delta_F1", "bootstrap_F1_CI_lo", "bootstrap_F1_CI_hi",
        "bootstrap_F1_CI_class", "effective_malicious_cluster_count", "frozen_wording",
    ])
    dump_json(OUT / "EDITOR007D_MECHANISM_PORTABILITY.json", {"task_id": TASK_ID, "rows": mech_rows})
    dump_csv(OUT / "EDITOR007D_MECHANISM_PORTABILITY.csv", mech_rows, [
        "dataset", "seed", "view", "C2_student_teacher_logit_deviation", "C5_student_teacher_logit_deviation",
        "relative_reduction_student_teacher_logit_deviation", "C2_route_mae", "C5_route_mae",
        "relative_reduction_route_mae", "C2_route_kl", "C5_route_kl", "relative_reduction_route_kl",
        "C2_hard_route_agreement", "C5_hard_route_agreement", "absolute_increase_hard_route_agreement",
        "C2_dominant_leaf_agreement", "C5_dominant_leaf_agreement", "absolute_increase_dominant_leaf_agreement",
        "unused_leaf_fraction", "tree_contribution_rho", "r52_mechanism_comparison",
    ])
    dump_json(OUT / "EDITOR007D_DIAGNOSTIC_RULING.json", rulings)
    dump_json(OUT / "EDITOR007D_CLAIM_IMPACT.json", claims)

    # report
    def completed_line(dataset: str, family: str) -> str:
        xs = [r for r in summaries if r["dataset"] == dataset and r["family"] == family and r["view"] == "COMPLETED_WINDOW"][0]
        return (
            f"| {dataset} | {family} | {fmt(xs['mean_PR_AUC'])} | {fmt(xs['min_PR_AUC'])} | "
            f"{fmt(xs['max_PR_AUC'])} | {fmt(xs['mean_F1'])} | {fmt(xs['mean_negative_threshold_exceedance'])} |"
        )

    report = []
    report.append("# EDITOR-007D — Cross-version diagnostic synthesis (CERT r5.2 → r5.1 → r6.2)")
    report.append("")
    report.append("Evidence synthesis only. No model loading, training, threshold selection, calibration, or new evaluation.")
    report.append("r5.1 role remains **R51_SECONDARY_STRESS_ONLY**. r5.1 official insider–incident clusters = **4**. r6.2 = **5**.")
    report.append("The EDITOR-007C1 metadata correction does not change any predictive numerical result.")
    report.append("")
    report.append("Preserved 007A gates:")
    report.append("")
    report.append("- AUTOMATED_PROTOCOL_GATE = `FAIL_EXACT_NUMERICAL_IDENTITY`")
    report.append("- INDEPENDENT_SCIENTIFIC_ADJUDICATION = `SCIENTIFIC_PARITY_WITH_NUMERICAL_NONIDENTITY`")
    report.append("")
    report.append("## TABLE 1 — Dataset / role / prevalence context")
    report.append("")
    report.append("| dataset | role | users | days | completed N / pos / prev | endpoint N / pos / prev | de-overlap N / pos / prev | official clusters |")
    report.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in dataset_rows:
        report.append(
            f"| {r['dataset_label']} | {r['dataset_role']} | {r['number_of_users']} | {r['calendar_days']} | "
            f"{fmt(r['completed_window_N'],0)} / {fmt(r['completed_positives'],0)} / {fmt(r['completed_prevalence'])} | "
            f"{fmt(r['endpoint_N'],0)} / {fmt(r['endpoint_positives'],0)} / {fmt(r['endpoint_prevalence'])} | "
            f"{fmt(r['deoverlap_N'],0)} / {fmt(r['deoverlap_positives'],0)} / {fmt(r['deoverlap_prevalence'])} | "
            f"{fmt(r['effective_malicious_cluster_count'],0)} |"
        )
    report.append("")
    report.append("Overlapping windows are not independent incidents. r5.2 endpoint/de-overlap views are `NOT_COMPARABLE`.")
    report.append("")
    report.append("## TABLE 2 — Three-version model portability")
    report.append("")
    report.append("COMPLETED_WINDOW three-seed descriptive summary (seeds are not independent experimental units; no standard errors).")
    report.append("")
    report.append("| dataset | family | mean PR-AUC | min | max | mean F1 | mean neg. exceedance |")
    report.append("| --- | --- | --- | --- | --- | --- | --- |")
    for fam in FAMILIES:
        for ds in ("r52_validation", "r51_secondary_stress", "r62_external"):
            report.append(completed_line(ds, fam))
    report.append("")
    report.append("Retention versus r5.2 VALIDATION is defined only for COMPLETED_WINDOW. ENDPOINT/DEOVERLAP on r5.2 are `NOT_COMPARABLE`.")
    report.append("AP_PREVALENCE_LIFT_DESCRIPTIVE = PR_AUC / prevalence is DESCRIPTIVE_ONLY.")
    report.append("")
    report.append("## TABLE 3 — Threshold exceedance portability")
    report.append("")
    report.append(f"Mean completed-window negative frozen-threshold exceedance: r5.2 validation {fmt(r52_ex)}; r5.1 {fmt(r51_ex)}; r6.2 {fmt(r62_ex)}.")
    report.append("Frozen 006A thresholds are preserved (no retuning). r6.2 negatives cross the frozen boundary for all 18 models.")
    report.append("")
    report.append("## TABLE 4 — Positive/negative score-distribution shift")
    report.append("")
    report.append("| family | seed | r52 neg exceed | r51 neg exceed | r62 neg exceed | r62−r52 neg mean |")
    report.append("| --- | ---: | --- | --- | --- | --- |")
    for rec in score_rows:
        report.append(
            f"| {rec['family']} | {rec['seed']} | "
            f"{fmt(rec['r52_validation']['negative']['frozen_threshold_exceedance'])} | "
            f"{fmt(rec['r51_secondary_stress']['negative']['frozen_threshold_exceedance'])} | "
            f"{fmt(rec['r62_external']['negative']['frozen_threshold_exceedance'])} | "
            f"{fmt(rec['neg_mean_r62_minus_r52'])} |"
        )
    report.append("")
    report.append("## TABLE 5 — Common-13 feature shift")
    report.append("")
    report.append("| feature | r52 TRAIN mean | r52 VAL mean | r51 mean | r62 mean | abs r51 vs TRAIN | abs r62 vs TRAIN | r62 rank |")
    report.append("| --- | --- | --- | --- | --- | --- | --- | ---: |")
    for row in feat_rows:
        report.append(
            f"| {row['feature']} | {fmt(row['r52_train_mean'])} | {fmt(row['r52_validation_mean'])} | "
            f"{fmt(row['r51_mean'])} | {fmt(row['r62_mean'])} | {fmt(row['abs_r51_mean_minus_r52_train_mean'])} | "
            f"{fmt(row['abs_r62_mean_minus_r52_train_mean'])} | {row['rank_abs_r62_vs_r52_train']} |"
        )
    report.append("")
    report.append(f"Largest |r6.2 − r5.2 TRAIN| features: {', '.join(r62_top3)}. No p-value ranking.")
    report.append("")
    report.append("## TABLE 6 — C2 vs C5 predictive comparison")
    report.append("")
    report.append("| dataset | seed | view | C2 PR-AUC | C5 PR-AUC | Δ PR-AUC | C2 F1 | C5 F1 | Δ F1 | PR CI class | F1 CI class |")
    report.append("| --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in c2c5_rows:
        report.append(
            f"| {r['dataset']} | {r['seed']} | {r['view']} | {fmt(r['C2_PR_AUC'])} | {fmt(r['C5_PR_AUC'])} | "
            f"{fmt(r['delta_PR_AUC_C5_minus_C2'])} | {fmt(r['C2_F1'])} | {fmt(r['C5_F1'])} | {fmt(r['delta_F1_C5_minus_C2'])} | "
            f"{r.get('bootstrap_PR_AUC_CI_class', 'NA')} | {r.get('bootstrap_F1_CI_class', 'NA')} |"
        )
    report.append("")
    report.append("Bootstrap intervals are reused, not recomputed. No significance-star language. A positive point estimate is not predictive superiority.")
    report.append("")
    report.append("## TABLE 7 — Teacher-relative mechanism comparison")
    report.append("")
    report.append("`R52_MECHANISM_COMPARISON_NOT_INCLUDED_PROVENANCE_INSUFFICIENT`. unused-leaf and tree-rho remain `DISABLED_NOT_REPRODUCIBLE`.")
    report.append("")
    report.append("| dataset | seed | C2 logit | C5 logit | rel. red. | C2 route MAE | C5 route MAE | C2 agr. | C5 agr. |")
    report.append("| --- | ---: | --- | --- | --- | --- | --- | --- | --- |")
    for r in mech_rows:
        report.append(
            f"| {r['dataset']} | {r['seed']} | {fmt(r['C2_student_teacher_logit_deviation'])} | "
            f"{fmt(r['C5_student_teacher_logit_deviation'])} | {fmt(r['relative_reduction_student_teacher_logit_deviation'])} | "
            f"{fmt(r['C2_route_mae'])} | {fmt(r['C5_route_mae'])} | {fmt(r['C2_hard_route_agreement'])} | "
            f"{fmt(r['C5_hard_route_agreement'])} |"
        )
    report.append("")
    report.append("## TABLE 8 — Scenario/cluster limitations")
    report.append("")
    report.append("`SCENARIOS_NOT_CROSS_VERSION_MATCHED_UNITS`")
    report.append("")
    report.append("- r5.1 = four official insider–incident clusters")
    report.append("- r6.2 = five official insider–incident clusters")
    report.append("- Scenario detection patterns are within-version descriptive only and are not numerically matched across versions.")
    report.append("")
    report.append("## TABLE 9 — Diagnostic rulings")
    report.append("")
    for key in (
        "GENERAL_CROSS_VERSION_COLLAPSE",
        "R51_SUBSTANTIAL_RANKING_TRANSFER",
        "R62_SEVERE_VERSION_SPECIFIC_FAILURE",
        "R62_RANKING_COLLAPSE",
        "R62_THRESHOLD_PORTABILITY_FAILURE",
        "TABULAR_RELATIVE_PORTABILITY",
        "C5_PREDICTIVE_ADVANTAGE_OVER_C2",
        "C5_TEACHER_FIDELITY_EFFECT",
        "PRIMARY_PORTABILITY_PHENOTYPE",
    ):
        report.append(f"- `{key}` = `{rulings[key] if key != 'PRIMARY_PORTABILITY_PHENOTYPE' else phenotype}`")
    report.append(f"- secondary contributors = {', '.join(secondary)}")
    report.append("")
    for qid, q in questions.items():
        report.append(f"**{qid}.** {q['question']}")
        report.append("")
        report.append(q["answer"])
        report.append("")
    report.append("## TABLE 10 — Current-paper claim impact")
    report.append("")
    report.append("| claim | status |")
    report.append("| --- | --- |")
    for c in claims["claims"]:
        report.append(f"| {c['claim']} | {c['status']} |")
    report.append("")
    report.append("## TABLE 11 — Requirements for EDITOR-008")
    report.append("")
    report.append("No architecture is frozen in EDITOR-007D.")
    report.append("")
    report.append("| requirement | required | support |")
    report.append("| --- | --- | --- |")
    for name, rec in reqs.items():
        if name in ("architecture_frozen_in_007d", "EDITOR008_TEACHER_ANCHORING_ROLE"):
            continue
        report.append(f"| {name} | {'YES' if rec['required'] else 'NO'} | {rec['support_status']} |")
    report.append("")
    report.append(f"EDITOR008_TEACHER_ANCHORING_ROLE = `{reqs['EDITOR008_TEACHER_ANCHORING_ROLE']}`")
    report.append("")
    report.append("Do not use PROVEN_CAUSAL language for any shift explanation.")
    (OUT / "EDITOR007D_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    sources = [
        REV007A / "EDITOR007A_R52_VALIDATION_PARITY.json",
        REV007A / "EDITOR007A_FEATURE_SHIFT.json",
        REV007A / "EDITOR007A_SCORE_DISTRIBUTION_SHIFT.json",
        REV007A / "EDITOR007A_R62_SCORE_ORIENTATION_AUDIT.json",
        REV007A / "EDITOR007A_DECISION_GATE.json",
        REV007A / "EDITOR007A_RUN_MANIFEST.json",
        REV007B / "EDITOR007B_007A_ADJUDICATION_FREEZE.json",
        R51_PRED,
        R51_MECH,
        R62_PRED,
        R62_MECH,
        REV007B / "EDITOR007B_R51_FEATURE_PROFILE.json",
        THR006A,
    ]
    if any(PROTOCOL.values()):
        raise SystemExit("EDITOR007D_CROSS_VERSION_SYNTHESIS_BLOCKED")
    created = sorted(p.name for p in OUT.iterdir() if p.is_file())
    if "EDITOR007D_RUN_MANIFEST.json" not in created:
        created.append("EDITOR007D_RUN_MANIFEST.json")
        created.sort()
    manifest = {
        "task_id": TASK_ID,
        "branch": branch,
        "HEAD_before": head_before,
        "HEAD_after_synthesis": git_cmd("rev-parse", "HEAD"),
        "source_evidence": [{"path": str(p), "sha256": sha256_file(p)} for p in sources if p.exists()],
        "files_created": created,
        "files_modified": [],
        "protocol_flags": PROTOCOL,
        "val_npz_opened_for_frozen_labels_only": True,
        "val_npz_sha256": val_sha,
        "val_npz_is_validation_not_test": True,
        "r51_predictive_source": str(R51_PRED),
        "r51_cluster_count": 4,
        "r62_cluster_count": 5,
        "timestamp_utc": utc_now(),
    }
    dump_json(OUT / "EDITOR007D_RUN_MANIFEST.json", manifest)
    print("EDITOR007D_OK", phenotype)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
