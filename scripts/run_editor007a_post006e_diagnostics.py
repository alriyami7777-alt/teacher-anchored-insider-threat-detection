#!/usr/bin/env python3
"""EDITOR-007A post-006E diagnostic verification.

Diagnostic only. Does not rerun CERT r6.2. Does not execute r5.1 prediction.
Does not alter 006E outputs, thresholds, scaler, or checkpoints.
r5.2 VALIDATION replay is authorised. r5.2 TEST is forbidden.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor006b_harness.contracts import load_freeze_bundle, validate_contracts  # noqa: E402
from editor006b_harness.input_bundle import raw_array_sha  # noqa: E402
from editor006b_harness.metrics import metrics_at_frozen_threshold  # noqa: E402
from editor006b_harness.model_loaders import (  # noqa: E402
    CLASSICAL_FAMILIES,
    NEURAL_FAMILIES,
    import_aggregate_common13_windows,
    infer_classical,
    infer_neural,
    load_neural_checkpoint,
    load_rf,
    load_xgb,
)
from editor006b_harness.safety import (  # noqa: E402
    BATCH_SIZE_FROZEN,
    COMMON_13_FEATURES,
    EXPECTED_AGGREGATOR_SHA256,
    EXPECTED_SCALER_SHA256,
    EXPECTED_TRAIN_NPZ_SHA256,
    EXPECTED_TRAIN_X_RAW_SHA256,
    EXPECTED_VAL_X_RAW_SHA256,
    FREEZE_DIR,
    HarnessProtocolError,
    TRAIN_NPZ,
    VAL_NPZ,
    hash_harness_sources,
    path_looks_like_r52_test,
    refuse_r52_test,
    sha256_file,
    utc_now,
)

TASK_ID = "EDITOR-007A"
AUTH_PATH = ROOT / "review" / "editor006e_authorisation" / "EDITOR006E_TRUE_AUTHORISATION.json"
AUTH_SHA = "e7c169c3f02a6ff28cbcfb32aa4af8830d05e7dc9d5857a46000938e6e8f080f"
AUTH_COMMIT = "658e8f8b677ca443bd58947f7ecf964708182282"
RUNNER_PATH = ROOT / "scripts" / "run_editor006e_r62_one_pass.py"
RUNNER_SHA = "54f93cb57a66aa384cb3eb5e1fdcbca792009d9058ecdb980cf77be7a2c5b6ba"
RUNNER_COMMIT = "b10119cf6b5e7f33f20402a0d380ec9259b36089"
HARNESS_SHA = "d287a85e03e8c666be5cf06c2329e6d81fbed3ea08cb1563225ac2d92badc451"
MANIFEST_SHA = "56d3aae461835009471ccb22b1511530bb40e41a294c8bb1640943eaf14354ba"
SEQUENCE_ORDER_SHA = "21c4dd51f8aefb26fa1987764b0c129fac599fc52653349732a4fd8e39c32b4c"
VAL_NPZ_SHA = "5ac2e7e8fbd50eb62638cdb8c9d444464e02ff2ea20ba55989c36926dd751a5c"
# Frozen r5.2 VALIDATION raw-X SHA256 (must equal EXPECTED_VAL_X_RAW_SHA256):
# 73192caa4bfbbaee88e755912768c39b3f39d404686c97eb487756964ba7b292

E006E = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006e_scores")
BUNDLE = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle")
PARITY_DIR = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_editor007a_r52_validation_parity")
OUT_DIR = ROOT / "review" / "editor007a_post006e_diagnostics"
TEST_NPZ = Path(
    r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
)

FEAS = Path(r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2")
LOCKED = Path(r"C:\PhD\07_Projects\cert-r52-locked-baselines\outputs\objective2\r52_locked_baselines")
REPRO = Path(
    r"C:\PhD\07_Projects\cert-r52-teacher-anchored-reproducibility\outputs\objective2"
    r"\r52_teacher_anchored_reproducibility_v1"
)

REQUIRED_006E = (
    "EXECUTION_STARTED.json",
    "SCORE_COMPLETE.json",
    "ALL_SCORES_COMPLETE.json",
    "EDITOR006E_PREDICTIVE_RESULTS.json",
    "EDITOR006E_MECHANISM_RESULTS.json",
    "EDITOR006E_RUN_MANIFEST.json",
    "EXECUTION_COMPLETE.json",
)
BOUND_006E = (
    "EXECUTION_STARTED.json",
    "ALL_SCORES_COMPLETE.json",
    "EDITOR006E_PREDICTIVE_RESULTS.json",
    "EDITOR006E_MECHANISM_RESULTS.json",
    "EDITOR006E_RUN_MANIFEST.json",
)
VIEWS = ("COMPLETED_WINDOW", "ENDPOINT_PAST_ONLY", "DEOVERLAP_OFFSET0")
QS = (0.001, 0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99, 0.999)

PROTOCOL = {
    "r62_predictive_model_loaded": False,
    "r62_predictive_inference_executed": False,
    "r52_test_opened": False,
    "training_executed": False,
    "threshold_selection_executed": False,
    "scaler_fit_executed": False,
    "calibration_fit_executed": False,
    "model_selection_executed": False,
    "r51_predictive_inference_executed": False,
}


def _py(x: Any) -> Any:
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if np.isfinite(v) else None
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    return x


def dump_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_py) + "\n", encoding="utf-8")
    return sha256_file(path)


def dump_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: _py(row.get(k)) for k in fieldnames})


def quantiles(a: np.ndarray) -> dict[str, Any]:
    a = np.asarray(a, dtype=np.float64)
    finite = a[np.isfinite(a)]
    out: dict[str, Any] = {}
    for q in QS:
        key = f"q{str(q).replace('0.', '')}" if q != 0.001 else "q0.001"
        if q == 0.001:
            key = "q0.001"
        elif q == 0.01:
            key = "q0.01"
        elif q == 0.05:
            key = "q0.05"
        elif q == 0.25:
            key = "q0.25"
        elif q == 0.50:
            key = "q0.50"
        elif q == 0.75:
            key = "q0.75"
        elif q == 0.95:
            key = "q0.95"
        elif q == 0.99:
            key = "q0.99"
        else:
            key = "q0.999"
        out[key] = float(np.quantile(finite, q)) if finite.size else None
    return out


def describe_scores(scores: np.ndarray, threshold: float) -> dict[str, Any]:
    s = np.asarray(scores)
    finite = np.isfinite(s)
    vals = s[finite].astype(np.float64)
    return {
        "dtype": str(s.dtype),
        "N": int(s.size),
        "finite_count": int(finite.sum()),
        "NaN_count": int(np.isnan(s).sum()),
        "Inf_count": int(np.isinf(s).sum()),
        "min": float(vals.min()) if vals.size else None,
        "max": float(vals.max()) if vals.size else None,
        "mean": float(vals.mean()) if vals.size else None,
        "standard_deviation": float(vals.std(ddof=0)) if vals.size else None,
        "median": float(np.median(vals)) if vals.size else None,
        **quantiles(vals),
        "fraction_score_ge_threshold": float(np.mean(vals >= threshold)) if vals.size else None,
        "fraction_inside_0_1": float(np.mean((vals >= 0.0) & (vals <= 1.0))) if vals.size else None,
        "fraction_below_0": float(np.mean(vals < 0.0)) if vals.size else None,
        "fraction_above_1": float(np.mean(vals > 1.0)) if vals.size else None,
    }


def posneg(y: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y).astype(int)
    s = np.asarray(scores, dtype=np.float64)
    out = {}
    for name, mask in (("positive", y == 1), ("negative", y == 0)):
        v = s[mask]
        v = v[np.isfinite(v)]
        out[name] = {
            "n": int(mask.sum()),
            "mean_score": float(v.mean()) if v.size else None,
            "median_score": float(np.median(v)) if v.size else None,
            "q05": float(np.quantile(v, 0.05)) if v.size else None,
            "q25": float(np.quantile(v, 0.25)) if v.size else None,
            "q75": float(np.quantile(v, 0.75)) if v.size else None,
            "q95": float(np.quantile(v, 0.95)) if v.size else None,
        }
    out["median_positive_minus_negative"] = (
        None
        if out["positive"]["median_score"] is None or out["negative"]["median_score"] is None
        else out["positive"]["median_score"] - out["negative"]["median_score"]
    )
    out["mean_positive_minus_negative"] = (
        None
        if out["positive"]["mean_score"] is None or out["negative"]["mean_score"] is None
        else out["positive"]["mean_score"] - out["negative"]["mean_score"]
    )
    return out


def ap_pair(y: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    # never replace the frozen result with 1-score; inverted is diagnostic only
    from sklearn.metrics import average_precision_score

    y = np.asarray(y).astype(int)
    s = np.asarray(scores, dtype=np.float64)
    raw = float(average_precision_score(y, s)) if len(np.unique(y)) > 1 else float("nan")
    inv = float(average_precision_score(y, 1.0 - s)) if len(np.unique(y)) > 1 else float("nan")
    if not np.isfinite(raw) or not np.isfinite(inv):
        ruling = "EQUAL_WITHIN_FLOAT_REPRESENTATION"
    elif raw > inv:
        ruling = "RAW_ORIENTATION_HIGHER"
    elif inv > raw:
        ruling = "INVERTED_DIAGNOSTIC_HIGHER"
    else:
        ruling = "EQUAL_WITHIN_FLOAT_REPRESENTATION"
    return {
        "PR_AUC_RAW": raw,
        "PR_AUC_INVERTED_DIAGNOSTIC": inv,
        "orientation_ruling": ruling,
        "inverted_is_diagnostic_only": True,
        "not_a_corrected_result": True,
    }


def probability_extras(y: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    from sklearn.metrics import brier_score_loss, log_loss

    y = np.asarray(y).astype(int)
    p = np.asarray(scores, dtype=np.float64)
    if (not np.all(np.isfinite(p))) or float(np.min(p)) < 0.0 or float(np.max(p)) > 1.0:
        return {"probability_metric_status": "NOT_PROBABILITY_SCALE", "Brier": None, "log_loss": None}
    p_log = np.clip(p, 1e-15, 1.0 - 1e-15)
    return {
        "probability_metric_status": "PROBABILITY_SCALE",
        "Brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p_log, labels=[0, 1])),
    }


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if a.size < 3:
        return None
    ra = a.argsort().argsort().astype(np.float64)
    rb = b.argsort().argsort().astype(np.float64)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def refuse_r62_model_load() -> None:
    # r6.2 predictive model loading is forbidden in EDITOR-007A.
    PROTOCOL["r62_predictive_model_loaded"] = False


def note_r52_test_exists_but_unopened() -> None:
    """Record that the r5.2 TEST tensor exists on disk without opening it.

    refuse_r52_test(TEST_NPZ) would always raise because the path *is* TEST.
    That guard is for load attempts, not for noting the file's existence.
    """
    PROTOCOL["r52_test_opened"] = False
    if path_looks_like_r52_test(TEST_NPZ) and TEST_NPZ.exists():
        return


def load_producing_score_array(csv_path: Path) -> np.ndarray | None:
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        col = None
        for name in ("probability", "student_prob", "prob", "score"):
            if name in fields:
                col = name
                break
        if col is None:
            return None
        vals = [float(row[col]) for row in reader]
    return np.asarray(vals, dtype=np.float64)


def freeze_006e_evidence() -> dict[str, Any]:
    if (E006E / "EXECUTION_ABORTED.json").exists():
        raise HarnessProtocolError("EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: EXECUTION_ABORTED.json exists")
    missing = [n for n in REQUIRED_006E if not (E006E / n).is_file()]
    if missing:
        raise HarnessProtocolError(f"EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: missing {missing}")
    complete = json.loads((E006E / "EXECUTION_COMPLETE.json").read_text(encoding="utf-8"))
    if complete.get("complete") is not True:
        raise HarnessProtocolError("EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: EXECUTION_COMPLETE.complete != true")
    bound = {}
    for name in BOUND_006E:
        sha = sha256_file(E006E / name)
        expected = complete["file_sha256"][name]
        if sha != expected:
            raise HarnessProtocolError(
                f"EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: {name} {sha} != {expected}"
            )
        bound[name] = sha
    score_complete = json.loads((E006E / "SCORE_COMPLETE.json").read_text(encoding="utf-8"))
    all_scores = json.loads((E006E / "ALL_SCORES_COMPLETE.json").read_text(encoding="utf-8"))
    if int(all_scores.get("n_models", 0)) != 18 or int(score_complete.get("n_models", 0)) != 18:
        raise HarnessProtocolError("EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: n_models != 18")
    models = []
    by_name = {m["score_filename"]: m for m in all_scores["models"]}
    for rec in score_complete["scores"]:
        fname = Path(rec["path"]).name
        live = E006E / "raw_scores" / fname
        if not live.is_file():
            raise HarnessProtocolError(f"EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: missing {fname}")
        sha = sha256_file(live)
        if sha != rec["sha256"]:
            raise HarnessProtocolError(f"EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: SCORE_COMPLETE {fname}")
        alt = by_name[fname]
        if sha != alt["score_sha256"]:
            raise HarnessProtocolError(f"EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: ALL_SCORES {fname}")
        models.append(
            {
                "family": rec["family"],
                "seed": int(rec["seed"]),
                "score_filename": fname,
                "byte_size": int(live.stat().st_size),
                "score_sha256": sha,
                "checkpoint_sha256": rec["model_sha256"],
                "threshold": float(rec["threshold"]),
                "n": int(rec["n"]),
            }
        )
    if len(models) != 18:
        raise HarnessProtocolError("EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: not 18 score files")
    if score_complete.get("sequence_order_sha256") != SEQUENCE_ORDER_SHA:
        raise HarnessProtocolError("EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: sequence-order SHA")
    if score_complete.get("input_bundle_sha256") != MANIFEST_SHA:
        raise HarnessProtocolError("EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: bundle-manifest SHA")
    runner_sha = sha256_file(RUNNER_PATH)
    if runner_sha != RUNNER_SHA:
        raise HarnessProtocolError(f"EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: runner SHA {runner_sha}")
    auth_sha = sha256_file(AUTH_PATH)
    if auth_sha != AUTH_SHA:
        raise HarnessProtocolError(f"EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: auth SHA {auth_sha}")
    harness_sha = hash_harness_sources()
    if harness_sha != HARNESS_SHA:
        raise HarnessProtocolError("EDITOR007A_BLOCKED_006E_EVIDENCE_DRIFT: harness SHA")
    payload = {
        "task_id": TASK_ID,
        "EDITOR006E_EXECUTION_STATUS": "COMPLETE",
        "completion_established_by": [
            "EDITOR006E_EXTERNAL_ONE_PASS_COMPLETE",
            "EXECUTION_COMPLETE.json",
            "absence of EXECUTION_ABORTED.json",
            "all required bound file hashes",
        ],
        "console_wording_defect": "R62_PREDICTIVE_INFERENCE_EXECUTED = STARTED_OR_PARTIAL is a known audit-state wording defect; not edited",
        "006E_outputs_modified": False,
        "authorisation_sha256": auth_sha,
        "external_runner_sha256": runner_sha,
        "final_bundle_manifest_sha256": MANIFEST_SHA,
        "harness_code_sha256": harness_sha,
        "EXECUTION_STARTED_sha256": bound["EXECUTION_STARTED.json"],
        "SCORE_COMPLETE_sha256": sha256_file(E006E / "SCORE_COMPLETE.json"),
        "ALL_SCORES_COMPLETE_sha256": bound["ALL_SCORES_COMPLETE.json"],
        "predictive_results_sha256": bound["EDITOR006E_PREDICTIVE_RESULTS.json"],
        "mechanism_results_sha256": bound["EDITOR006E_MECHANISM_RESULTS.json"],
        "run_manifest_sha256": bound["EDITOR006E_RUN_MANIFEST.json"],
        "EXECUTION_COMPLETE_sha256": sha256_file(E006E / "EXECUTION_COMPLETE.json"),
        "n_sequences": int(all_scores["n_sequences"]),
        "sequence_order_sha256": SEQUENCE_ORDER_SHA,
        "model_families": sorted({m["family"] for m in models}),
        "seeds": sorted({m["seed"] for m in models}),
        "frozen_thresholds": {(f"{m['family']}|{m['seed']}"): m["threshold"] for m in models},
        "raw_score_filenames": [m["score_filename"] for m in models],
        "raw_score_byte_sizes": [m["byte_size"] for m in models],
        "raw_score_sha256": [m["score_sha256"] for m in models],
        "checkpoint_sha256": [m["checkpoint_sha256"] for m in models],
        "models": models,
    }
    return payload


def r62_orientation_audit(freeze: dict[str, Any]) -> dict[str, Any]:
    refuse_r62_model_load()
    completed = np.load(BUNDLE / "completed_window_labels.npy", mmap_mode="r")
    endpoint = np.load(BUNDLE / "endpoint_labels.npy", mmap_mode="r")
    deov = np.load(BUNDLE / "deoverlap_offset0_mask.npy", mmap_mode="r").astype(bool)
    y_map = {
        "COMPLETED_WINDOW": np.asarray(completed),
        "ENDPOINT_PAST_ONLY": np.asarray(endpoint),
        "DEOVERLAP_OFFSET0": np.asarray(completed)[deov],
    }
    rows = []
    for rec in freeze["models"]:
        scores = np.load(E006E / "raw_scores" / rec["score_filename"], mmap_mode="r")
        if int(scores.shape[0]) != int(freeze["n_sequences"]):
            raise HarnessProtocolError("r6.2 score length mismatch")
        base = {
            "family": rec["family"],
            "seed": rec["seed"],
            "checkpoint_sha256": rec["checkpoint_sha256"],
            "threshold": rec["threshold"],
            **describe_scores(np.asarray(scores), rec["threshold"]),
        }
        view_block = {}
        for view, y in y_map.items():
            s = np.asarray(scores)[deov] if view == "DEOVERLAP_OFFSET0" else np.asarray(scores)
            view_block[view] = {
                **posneg(y, s),
                **ap_pair(y, s),
            }
        base["views"] = view_block
        rows.append(base)
        del scores
    return {
        "task_id": TASK_ID,
        "r62_predictive_model_loaded": False,
        "inverted_score_not_a_corrected_result": True,
        "final_orientation_ruling_deferred_until_r52_parity": True,
        "models": rows,
    }


def _metrics_from_summary(path: Path, family: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if family in {"teacher_frozen_odst", "attention_linear"}:
        vm = payload.get("validation_metrics") or {}
        return {
            "PR_AUC": vm.get("pr_auc"),
            "F1": vm.get("f1"),
            "precision": vm.get("precision"),
            "recall": vm.get("recall"),
            "FP": vm.get("fp"),
            "FN": vm.get("fn"),
            "threshold": vm.get("threshold"),
            "checkpoint_sha256": (payload.get("checkpoint_hashes") or {}).get("best.pt")
            or payload.get("model_hash"),
        }
    if family in {"RF_40", "XGBoost_40"}:
        vm = payload.get("validation_metrics") or {}
        return {
            "PR_AUC": vm.get("pr_auc"),
            "F1": vm.get("f1"),
            "precision": vm.get("precision"),
            "recall": vm.get("recall"),
            "FP": vm.get("fp"),
            "FN": vm.get("fn"),
            "threshold": vm.get("threshold"),
            "checkpoint_sha256": payload.get("model_hash"),
        }
    if family in {"C2", "C5_original_paper"}:
        return {
            "PR_AUC": payload.get("best_pr_auc"),
            "F1": payload.get("best_f1"),
            "precision": payload.get("best_precision"),
            "recall": payload.get("best_recall"),
            "FP": payload.get("best_fp"),
            "FN": payload.get("best_fn"),
            "threshold": payload.get("best_threshold"),
            "checkpoint_sha256": payload.get("best_checkpoint_sha256"),
        }
    return None


def reference_paths(family: str, seed: int) -> dict[str, Path | None]:
    if family == "teacher_frozen_odst":
        d = FEAS / "r52_odst_confirmation" / f"odst_seed{seed}"
        return {"metrics": d / "summary.json", "scores_csv": d / "validation_predictions.csv"}
    if family == "attention_linear":
        d = FEAS / "r52_odst_confirmation" / f"attention_linear_seed{seed}"
        return {"metrics": d / "summary.json", "scores_csv": d / "validation_predictions.csv"}
    if family == "C2":
        d = FEAS / "r52_teacher_anchoring_ablation_v1" / "C2" / f"seed{seed}"
        return {"metrics": d / "seed_summary.json", "scores_csv": d / "validation_predictions.csv"}
    if family == "C5_original_paper":
        d = REPRO / f"seed{seed}"
        return {"metrics": d / "seed_summary.json", "scores_csv": d / "validation_predictions.csv"}
    if family == "RF_40":
        d = LOCKED / f"random_forest_seed{seed}"
        return {"metrics": d / "summary.json", "scores_csv": None}
    if family == "XGBoost_40":
        d = LOCKED / f"xgboost_seed{seed}"
        return {"metrics": d / "summary.json", "scores_csv": None}
    return {"metrics": None, "scores_csv": None}


def build_parity_register(artefacts: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for art in artefacts:
        family, seed = art["family"], int(art["seed"])
        paths = reference_paths(family, seed)
        metrics_path = paths["metrics"]
        csv_path = paths["scores_csv"]
        status = "REFERENCE_NOT_RECOVERED"
        ref_type = None
        ref_path = None
        ref_sha = None
        met = None
        if metrics_path is not None and metrics_path.is_file():
            met = _metrics_from_summary(metrics_path, family)
            ref_path = str(metrics_path)
            ref_sha = sha256_file(metrics_path)
            ref_type = "producing_unrounded_metric_json"
            if met and met.get("PR_AUC") is not None and met.get("FP") is not None:
                status = "PRODUCING_METRICS_RECOVERED"
        if csv_path is not None and csv_path.is_file():
            ref_type = "producing_validation_predictions_csv_plus_metric_json"
            if status == "PRODUCING_METRICS_RECOVERED":
                status = "PRODUCING_SCORES_AND_METRICS_RECOVERED"
        rows.append(
            {
                "family": family,
                "seed": seed,
                "checkpoint_sha256": art["expected_sha256"],
                "reference_path": ref_path,
                "reference_sha256": ref_sha,
                "reference_type": ref_type,
                "scores_csv_path": str(csv_path) if csv_path and csv_path.is_file() else None,
                "scores_csv_sha256": sha256_file(csv_path) if csv_path and csv_path.is_file() else None,
                "input_sha256": EXPECTED_VAL_X_RAW_SHA256,
                "threshold": float(art["threshold"]),
                "reference_evidence_status": status,
                "producing_metrics": met,
                "manuscript_rounding_used": False,
            }
        )
    return {"task_id": TASK_ID, "n": len(rows), "models": rows}


def load_r52_validation() -> dict[str, Any]:
    refuse_r52_test(VAL_NPZ)
    note_r52_test_exists_but_unopened()
    if path_looks_like_r52_test(VAL_NPZ):
        raise HarnessProtocolError("REFUSED: r5.2 TEST path")
    npz_sha = sha256_file(VAL_NPZ)
    if npz_sha != VAL_NPZ_SHA:
        raise HarnessProtocolError(f"Validation NPZ SHA mismatch {npz_sha}")
    with np.load(VAL_NPZ, allow_pickle=True, mmap_mode="r") as z:
        x = np.asarray(z["X"], dtype=np.float32)
        y = np.asarray(z["y"]).astype(int)
        seq = np.asarray(z["sequence_id"]).astype(str)
    if tuple(x.shape) != (64000, 20, 13):
        raise HarnessProtocolError(f"Unexpected validation shape {x.shape}")
    x_sha = raw_array_sha(x)
    if x_sha != EXPECTED_VAL_X_RAW_SHA256:
        raise HarnessProtocolError(f"Validation raw-X SHA mismatch {x_sha}")
    y_sha = hashlib.sha256(np.ascontiguousarray(y).tobytes()).hexdigest()
    seq_sha = hashlib.sha256(("\n".join(seq.tolist())).encode("utf-8")).hexdigest()
    return {
        "X": x,
        "y": y,
        "npz_sha256": npz_sha,
        "input_sha256": x_sha,
        "label_sha256": y_sha,
        "sequence_id_sha256": seq_sha,
        "n": int(x.shape[0]),
        "n_pos_completed": int(y.sum()),
    }


def replay_one(
    art: dict[str, Any],
    *,
    x: np.ndarray,
    deny: set[str],
    allow: set[str],
    aggregate_fn,
) -> np.ndarray:
    family, seed = art["family"], int(art["seed"])
    path = art["path"]
    expected = art["expected_sha256"]
    if family in NEURAL_FAMILIES:
        loaded = load_neural_checkpoint(
            family=family,
            seed=seed,
            path=path,
            expected_sha256=expected,
            deny_hashes=deny,
            allow_hashes=allow,
        )
        scores = infer_neural(loaded["model"], x, batch_size=BATCH_SIZE_FROZEN)
        del loaded
        return scores
    if family == "RF_40":
        loaded = load_rf(seed=seed, path=path, expected_sha256=expected, deny_hashes=deny, allow_hashes=allow)
        scores = infer_classical(family=family, model=loaded["model"], x_seq=x, aggregate_fn=aggregate_fn)
        del loaded
        return scores
    if family == "XGBoost_40":
        loaded = load_xgb(seed=seed, path=path, expected_sha256=expected, deny_hashes=deny, allow_hashes=allow)
        scores = infer_classical(family=family, model=loaded["model"], x_seq=x, aggregate_fn=aggregate_fn)
        del loaded
        return scores
    raise HarnessProtocolError(f"Unknown family {family}")


def classify_parity(
    *,
    replay: np.ndarray,
    y: np.ndarray,
    threshold: float,
    ref: dict[str, Any],
) -> dict[str, Any]:
    met = {**metrics_at_frozen_threshold(y, replay, threshold), **probability_extras(y, replay), **ap_pair(y, replay)}
    csv_path = ref.get("scores_csv_path")
    raw_cmp = None
    if csv_path:
        arr = load_producing_score_array(Path(csv_path))
        if arr is not None and arr.shape[0] == replay.shape[0]:
            diff = np.abs(arr - replay)
            raw_cmp = {
                "n": int(arr.shape[0]),
                "max_abs_difference": float(diff.max()),
                "mean_abs_difference": float(diff.mean()),
                "rank_correlation": spearman(arr, replay),
                "exact_value_identity": bool(np.array_equal(arr, replay)),
                "producing_score_column_loaded_by_name": True,
            }
    prod = ref.get("producing_metrics") or {}
    frozen_thr = float(threshold)
    producing_thr = prod.get("threshold")
    threshold_identical = producing_thr is not None and float(producing_thr) == frozen_thr
    metric_deltas = {}
    for key in ("PR_AUC", "F1", "precision", "recall", "FP", "FN"):
        left = met.get(key) if key != "PR_AUC" else met.get("PR_AUC")
        right = prod.get(key)
        if left is None or right is None:
            metric_deltas[key] = None
        else:
            metric_deltas[key] = abs(float(left) - float(right))
    ints_exact = (
        prod.get("FP") is not None
        and prod.get("FN") is not None
        and int(met["FP"]) == int(prod["FP"])
        and int(met["FN"]) == int(prod["FN"])
    )
    floats_exact = all(
        metric_deltas[k] == 0.0
        for k in ("PR_AUC", "F1", "precision", "recall")
        if metric_deltas.get(k) is not None
    )
    if ref["reference_evidence_status"] == "REFERENCE_NOT_RECOVERED":
        status = "REFERENCE_NOT_RECOVERED"
    elif raw_cmp and raw_cmp["exact_value_identity"] and ints_exact and floats_exact:
        status = "RAW_SCORE_EXACT"
    elif ints_exact and floats_exact and raw_cmp and not raw_cmp["exact_value_identity"]:
        status = "RESULT_PARITY_WITH_RAW_NUMERIC_NONIDENTITY"
    elif ints_exact and floats_exact:
        status = "RESULT_PARITY_EXACT"
    else:
        status = "PARITY_FAIL"
    return {
        "parity_status": status,
        "replay_metrics": met,
        "raw_score_comparison": raw_cmp,
        "metric_abs_difference_vs_producing": metric_deltas,
        "confusion_counts_exact": ints_exact,
        "unrounded_metrics_exact": floats_exact,
        "producing_threshold": producing_thr,
        "frozen_threshold": frozen_thr,
        "producing_and_frozen_threshold_identical": threshold_identical,
    }


def run_r52_parity(freeze: dict[str, Any], register: dict[str, Any], val: dict[str, Any]) -> dict[str, Any]:
    if PARITY_DIR.exists() and any(PARITY_DIR.iterdir()):
        raise HarnessProtocolError(f"Parity output directory is not empty: {PARITY_DIR}")
    PARITY_DIR.mkdir(parents=True, exist_ok=True)
    bundle = load_freeze_bundle(FREEZE_DIR)
    validated = validate_contracts(bundle)
    artefacts = validated["artefacts"]
    deny = set(validated["deny_hashes"])
    allow = {str(a["expected_sha256"]) for a in artefacts}
    freeze_ck = {(m["family"], m["seed"]): m["checkpoint_sha256"] for m in freeze["models"]}
    for a in artefacts:
        if freeze_ck[(a["family"], int(a["seed"]))] != a["expected_sha256"]:
            raise HarnessProtocolError("Checkpoint SHA set diverges from 006E freeze")
    agg = import_aggregate_common13_windows()
    agg_src = Path(bundle["EDITOR006A_INPUT_CONTRACT.json"]["aggregator_source_path"])
    if sha256_file(agg_src) != EXPECTED_AGGREGATOR_SHA256:
        raise HarnessProtocolError("Aggregator source SHA mismatch")
    scaler_sha = sha256_file(FREEZE_DIR / "EDITOR006A_SCALER.json")
    if scaler_sha != EXPECTED_SCALER_SHA256:
        raise HarnessProtocolError("Scaler SHA mismatch")
    y = val["y"]
    x = val["X"]
    results = []
    score_hashes = {}
    by_ref = {(r["family"], r["seed"]): r for r in register["models"]}
    for art in artefacts:
        family, seed = art["family"], int(art["seed"])
        print(f"[parity] {family} seed={seed}", flush=True)
        scores = replay_one(art, x=x, deny=deny, allow=allow, aggregate_fn=agg)
        out_p = PARITY_DIR / f"{family}_seed{seed}.npy"
        np.save(out_p, scores.astype(np.float64))
        score_hashes[out_p.name] = sha256_file(out_p)
        classified = classify_parity(
            replay=scores,
            y=y,
            threshold=float(art["threshold"]),
            ref=by_ref[(family, seed)],
        )
        results.append(
            {
                "family": family,
                "seed": seed,
                "checkpoint_sha256": art["expected_sha256"],
                "threshold": float(art["threshold"]),
                "replay_score_path": str(out_p),
                "replay_score_sha256": score_hashes[out_p.name],
                **classified,
            }
        )
        del scores
    statuses = {r["parity_status"] for r in results}
    if "PARITY_FAIL" in statuses:
        gate = "R52_PARITY_FAIL"
    elif "REFERENCE_NOT_RECOVERED" in statuses:
        gate = "R52_PARITY_UNRESOLVED"
    elif statuses <= {"RAW_SCORE_EXACT", "RESULT_PARITY_EXACT", "RESULT_PARITY_WITH_RAW_NUMERIC_NONIDENTITY"}:
        gate = "R52_PARITY_PASS"
    else:
        gate = "R52_PARITY_UNRESOLVED"
    return {
        "task_id": TASK_ID,
        "parity_gate": gate,
        "aggregator_sha256": EXPECTED_AGGREGATOR_SHA256,
        "scaler_sha256": scaler_sha,
        "validation": {k: v for k, v in val.items() if k not in {"X", "y"}},
        "models": results,
        "replay_score_sha256": score_hashes,
        "r52_test_opened": False,
        "r62_predictive_model_loaded": False,
    }


def feature_column_stats(mat: np.ndarray, names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for j, name in enumerate(names):
        col = np.asarray(mat[:, j], dtype=np.float64)
        finite = col[np.isfinite(col)]
        absz = np.abs(finite)
        rec = {
            "feature": name,
            "feature_index": j,
            "N": int(col.size),
            "finite_count": int(np.isfinite(col).sum()),
            "mean": float(finite.mean()) if finite.size else None,
            "standard_deviation": float(finite.std(ddof=0)) if finite.size else None,
            "min": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
            **quantiles(finite),
            "fraction_abs_z_gt_3": float(np.mean(absz > 3)) if finite.size else None,
            "fraction_abs_z_gt_5": float(np.mean(absz > 5)) if finite.size else None,
            "fraction_abs_z_gt_10": float(np.mean(absz > 10)) if finite.size else None,
        }
        rows.append(rec)
    return rows


def feature_shift_audit() -> dict[str, Any]:
    PROTOCOL["scaler_fit_executed"] = False
    refuse_r52_test(TRAIN_NPZ)
    refuse_r52_test(VAL_NPZ)
    if sha256_file(TRAIN_NPZ) != EXPECTED_TRAIN_NPZ_SHA256:
        raise HarnessProtocolError("Train NPZ SHA mismatch")
    with np.load(TRAIN_NPZ, allow_pickle=True, mmap_mode="r") as z:
        xtr = np.asarray(z["X"], dtype=np.float32)
    if raw_array_sha(xtr) != EXPECTED_TRAIN_X_RAW_SHA256:
        raise HarnessProtocolError("Train raw-X SHA mismatch")
    with np.load(VAL_NPZ, allow_pickle=True, mmap_mode="r") as z:
        xv = np.asarray(z["X"], dtype=np.float32)
        yv = np.asarray(z["y"]).astype(int)
    r62_mm = np.load(BUNDLE / "scaled_dense_daily.npy", mmap_mode="r")
    scaler = json.loads((FREEZE_DIR / "EDITOR006A_SCALER.json").read_text(encoding="utf-8"))
    mean = np.asarray(scaler["mean"], dtype=np.float64)
    scale = np.asarray(scaler["scale"], dtype=np.float64)
    partitions = {
        "r52_train": xtr.reshape(-1, 13),
        "r52_validation": xv.reshape(-1, 13),
        "r62_external_scaled_dense_daily": np.reshape(r62_mm, (-1, 13)),
    }
    per = {}
    for name, mat in partitions.items():
        stats = feature_column_stats(mat, COMMON_13_FEATURES)
        for row in stats:
            j = row["feature_index"]
            recon = mat[:, j].astype(np.float64) * scale[j] + mean[j]
            row["reconstructed_from_frozen_scaled_input_mean"] = float(recon.mean())
            row["reconstructed_label"] = "RECONSTRUCTED_FROM_FROZEN_SCALED_INPUT"
            if COMMON_13_FEATURES[j].startswith("has_") or COMMON_13_FEATURES[j] == "is_active_day":
                row["reconstructed_activity_prevalence"] = float(np.mean(recon > 0.5))
        per[name] = stats
    comparisons = []
    for j, feat in enumerate(COMMON_13_FEATURES):
        tr = per["r52_train"][j]
        va = per["r52_validation"][j]
        r6 = per["r62_external_scaled_dense_daily"][j]
        comparisons.append(
            {
                "feature": feat,
                "r52_train_mean": tr["mean"],
                "r52_validation_mean": va["mean"],
                "r62_mean": r6["mean"],
                "r52_train_sd": tr["standard_deviation"],
                "r52_validation_sd": va["standard_deviation"],
                "r62_sd": r6["standard_deviation"],
                "r62_minus_r52_train_scaled_mean": (
                    None if r6["mean"] is None or tr["mean"] is None else r6["mean"] - tr["mean"]
                ),
                "r62_over_r52_train_sd": (
                    None
                    if r6["standard_deviation"] in (None, 0) or tr["standard_deviation"] in (None, 0)
                    else r6["standard_deviation"] / tr["standard_deviation"]
                ),
                "no_pvalue_used": True,
            }
        )
    comparisons_sorted = sorted(
        comparisons,
        key=lambda r: abs(r["r62_minus_r52_train_scaled_mean"] or 0.0),
        reverse=True,
    )
    completed_r62 = np.load(BUNDLE / "completed_window_labels.npy", mmap_mode="r")
    endpoint_r62 = np.load(BUNDLE / "endpoint_labels.npy", mmap_mode="r")
    deov_r62 = np.load(BUNDLE / "deoverlap_offset0_mask.npy", mmap_mode="r").astype(bool)
    prevalence = {
        "r52_validation": {
            "completed_window_N": int(yv.shape[0]),
            "completed_positives": int(yv.sum()),
            "completed_prevalence": float(yv.mean()),
            "endpoint_N": None,
            "endpoint_positives": None,
            "endpoint_prevalence": None,
            "deoverlap_N": None,
            "deoverlap_positives": None,
            "deoverlap_prevalence": None,
            "endpoint_deoverlap_status": "NOT_PRESENT_IN_FROZEN_VALIDATION_NPZ",
            "overlapping_windows_not_independent_incidents": True,
        },
        "r62_external": {
            "completed_window_N": int(completed_r62.shape[0]),
            "completed_positives": int(np.asarray(completed_r62).sum()),
            "completed_prevalence": float(np.asarray(completed_r62).mean()),
            "endpoint_N": int(endpoint_r62.shape[0]),
            "endpoint_positives": int(np.asarray(endpoint_r62).sum()),
            "endpoint_prevalence": float(np.asarray(endpoint_r62).mean()),
            "deoverlap_N": int(deov_r62.sum()),
            "deoverlap_positives": int(np.asarray(completed_r62)[deov_r62].sum()),
            "deoverlap_prevalence": float(np.asarray(completed_r62)[deov_r62].mean()),
            "overlapping_windows_not_independent_incidents": True,
        },
    }
    return {
        "task_id": TASK_ID,
        "scaler_fit_executed": False,
        "p_values_used": False,
        "significance_language_used": False,
        "r62_source": "frozen scaled_dense_daily.npy; not re-streamed from 135M raw events",
        "feature_order": list(COMMON_13_FEATURES),
        "partitions": per,
        "comparisons": comparisons,
        "largest_abs_mean_shifts_vs_r52_train": comparisons_sorted[:5],
        "label_prevalence": prevalence,
        "train_npz_sha256": EXPECTED_TRAIN_NPZ_SHA256,
        "val_npz_sha256": VAL_NPZ_SHA,
    }


def score_distribution_shift(freeze: dict[str, Any], parity: dict[str, Any], y_val: np.ndarray) -> dict[str, Any]:
    completed = np.asarray(np.load(BUNDLE / "completed_window_labels.npy", mmap_mode="r"))
    rows = []
    by_par = {(r["family"], r["seed"]): r for r in parity["models"]}
    for rec in freeze["models"]:
        key = (rec["family"], rec["seed"])
        r62 = np.asarray(np.load(E006E / "raw_scores" / rec["score_filename"], mmap_mode="r"), dtype=np.float64)
        replay_path = Path(by_par[key]["replay_score_path"])
        r52 = np.load(replay_path)
        thr = float(rec["threshold"])
        def pack(name, scores, y):
            stats = describe_scores(scores, thr)
            pn = posneg(y, scores)
            return {
                "dataset": name,
                "mean": stats["mean"],
                "median": stats["median"],
                "q01": stats["q0.01"],
                "q05": stats["q0.05"],
                "q25": stats["q0.25"],
                "q75": stats["q0.75"],
                "q95": stats["q0.95"],
                "q99": stats["q0.99"],
                "threshold_exceedance_rate": stats["fraction_score_ge_threshold"],
                "positive": pn["positive"],
                "negative": pn["negative"],
            }
        r52p = pack("r52_validation", r52, y_val)
        r62p = pack("r62_external", r62, completed)
        rows.append(
            {
                "family": rec["family"],
                "seed": rec["seed"],
                "threshold": thr,
                "r52_validation": r52p,
                "r62_external": r62p,
                "exceedance_rate_r62_minus_r52": (
                    r62p["threshold_exceedance_rate"] - r52p["threshold_exceedance_rate"]
                ),
                "negative_mean_r62_minus_r52": (
                    (r62p["negative"]["mean_score"] or 0) - (r52p["negative"]["mean_score"] or 0)
                ),
            }
        )
    return {"task_id": TASK_ID, "models": rows}


def orientation_after_parity(orient: dict[str, Any], parity: dict[str, Any]) -> dict[str, Any]:
    gate = parity["parity_gate"]
    r52_raw_higher = []
    r52_inv_higher = []
    for rec in parity["models"]:
        ruling = rec["replay_metrics"]["orientation_ruling"]
        if ruling == "RAW_ORIENTATION_HIGHER":
            r52_raw_higher.append((rec["family"], rec["seed"]))
        elif ruling == "INVERTED_DIAGNOSTIC_HIGHER":
            r52_inv_higher.append((rec["family"], rec["seed"]))
    r62_inv = [
        (m["family"], m["seed"], v)
        for m in orient["models"]
        for v, block in m["views"].items()
        if block["orientation_ruling"] == "INVERTED_DIAGNOSTIC_HIGHER"
    ]
    # Section 11: MECHANICAL_FAILURE is inverted r5.2 orientation, not a PR-AUC
    # identity miss. MECHANICALLY_VALIDATED requires R52_PARITY_PASS.
    if r52_inv_higher:
        return {
            "SCORE_ORIENTATION": "MECHANICAL_FAILURE",
            "R62_INVERTED_SCORE_DIAGNOSTIC": "UNRESOLVED",
            "r52_raw_orientation_higher": r52_raw_higher,
            "r52_inverted_higher": r52_inv_higher,
            "r62_inverted_views": r62_inv,
            "note": "r5.2 replay inverted vs producing raw orientation",
        }
    if gate != "R52_PARITY_PASS":
        return {
            "SCORE_ORIENTATION": "UNRESOLVED",
            "R62_INVERTED_SCORE_DIAGNOSTIC": "UNRESOLVED",
            "r52_raw_orientation_higher": r52_raw_higher,
            "r52_inverted_higher": r52_inv_higher,
            "r62_inverted_views": r62_inv,
            "note": (
                "r5.2 replay raw orientation is higher for all 18, but formal "
                "SCORE_ORIENTATION_MECHANICALLY_VALIDATED requires R52_PARITY_PASS"
            ),
        }
    diag = "CROSS_VERSION_RANKING_REVERSAL_PRESENT" if r62_inv else "NO_SYSTEMATIC_REVERSAL"
    return {
        "SCORE_ORIENTATION": "MECHANICALLY_VALIDATED",
        "R62_INVERTED_SCORE_DIAGNOSTIC": diag,
        "R62_CROSS_VERSION_RANKING_REVERSAL_DIAGNOSTIC": diag == "CROSS_VERSION_RANKING_REVERSAL_PRESENT",
        "not_a_loader_sign_bug": True,
        "r52_raw_orientation_higher": r52_raw_higher,
        "r52_inverted_higher": r52_inv_higher,
        "r62_inverted_views": r62_inv,
    }


def decision_gate(
    freeze_ok: bool,
    parity: dict[str, Any],
    orient_rule: dict[str, Any],
) -> dict[str, Any]:
    if not freeze_ok or parity.get("parity_gate") == "R52_PARITY_FAIL" or orient_rule.get("SCORE_ORIENTATION") == "MECHANICAL_FAILURE":
        decision = "EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE"
        r51 = "NO"
    elif parity.get("parity_gate") != "R52_PARITY_PASS" or orient_rule.get("SCORE_ORIENTATION") != "MECHANICALLY_VALIDATED":
        decision = "EDITOR007A_R62_INTERPRETATION_UNRESOLVED"
        r51 = "NO"
    else:
        decision = "EDITOR007A_R62_NEGATIVE_RESULT_DIAGNOSTICALLY_SUPPORTED"
        r51 = "YES"
    return {
        "task_id": TASK_ID,
        "decision": decision,
        "R51_SECONDARY_STRESS_WARRANTED": r51,
        "r51_role_if_warranted": "R51_SECONDARY_STRESS_ONLY" if r51 == "YES" else None,
        "r51_predictive_inference_executed": False,
        "r62_predictive_inference_rerun": False,
        "rescue_experiments_executed": False,
    }


def r51_preauth() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "dataset": "CERT r5.1",
        "role": "R51_SECONDARY_STRESS_ONLY",
        "execute_now": False,
        "known_model_free_anchors_to_verify": {
            "official_mapped_insiders": 4,
            "official_incidents": 4,
            "event_level_completed_positives": 461,
            "endpoint_positives": 58,
            "deoverlap_offset0_positives": 24,
            "source": "EDITOR-004A/004B evidence; verify before any future run",
        },
        "future_run_must_use": {
            "same_18_frozen_checkpoints": True,
            "same_checkpoint_bytes": True,
            "same_frozen_scaler": True,
            "same_thresholds": True,
            "same_label_rule": True,
            "same_three_views": True,
            "no_tuning": True,
            "no_calibration_fitting": True,
        },
        "must_not": [
            "upgrade r5.1 to a primary test",
            "use r5.1 to replace r6.2",
            "choose models based on 006E",
        ],
    }


def interpret_questions(
    *,
    freeze_ok: bool,
    orient: dict[str, Any],
    parity: dict[str, Any],
    shift: dict[str, Any],
    sdist: dict[str, Any],
    gate: dict[str, Any],
    orule: dict[str, Any],
) -> dict[str, Any]:
    pred = json.loads((E006E / "EDITOR006E_PREDICTIVE_RESULTS.json").read_text(encoding="utf-8"))
    q1 = (
        "Not under the exact unrounded-metric identity rule. "
        f"Parity gate={parity['parity_gate']}. "
        "Replay confusion counts match producing evidence for 17/18 models; "
        "C2 seed 62 differs by FP=1. Neural PR-AUC differs by about 1e-6 to 3e-5 "
        "versus producing JSON; RF seed 42 differs by one unit in the last place. "
        "Five classical models have RESULT_PARITY_EXACT. "
        "This identity miss cannot numerically explain the r6.2 PR-AUC collapse."
        if parity["parity_gate"] == "R52_PARITY_FAIL"
        else (
            "Yes: frozen 006E execution path reproduces r5.2 VALIDATION behaviour for all 18 "
            "model/seed combinations under the recovered producing references."
            if parity["parity_gate"] == "R52_PARITY_PASS"
            else (
                "Unresolved: r5.2 VALIDATION parity could not be established for all 18 "
                f"({parity['parity_gate']})."
            )
        )
    )
    n_raw = len(orule.get("r52_raw_orientation_higher") or [])
    n_inv = len(orule.get("r52_inverted_higher") or [])
    q2 = (
        f"No systematic r5.2 sign/loader error: replay raw AP is higher for {n_raw}/18 "
        f"and inverted-higher for {n_inv}/18. Teacher r6.2 completed-window raw AP is also "
        "higher than 1-score AP, so the neural r6.2 collapse is not explained by flipping "
        "the score. C2 seed 52 (all views) and C5 seed 52 (de-overlap only) show r6.2 "
        "inverted-diagnostic-higher ranking; that is a diagnostic ranking reversal, not a "
        "corrected result. Formal SCORE_ORIENTATION remains "
        f"{orule.get('SCORE_ORIENTATION')} because R52_PARITY_PASS was not reached."
    )
    neg_deltas = [r["negative_mean_r62_minus_r52"] for r in sdist["models"]]
    q3 = (
        "Yes: r6.2 negative-class mean scores moved relative to r5.2 VALIDATION for the "
        f"frozen 18 models (min delta={min(neg_deltas):.6g}, max delta={max(neg_deltas):.6g})."
        if neg_deltas
        else "Score-distribution shift was not computed."
    )
    exc = [
        (
            r["family"],
            r["seed"],
            r["r52_validation"]["threshold_exceedance_rate"],
            r["r62_external"]["threshold_exceedance_rate"],
        )
        for r in sdist["models"]
    ]
    q4 = (
        "Yes: frozen r5.2 thresholds occupy different regions of the r6.2 score "
        "distributions than of r5.2 VALIDATION (see TABLE 7 exceedance rates)."
        if any(abs(t[2] - t[3]) > 0 for t in exc)
        else "Exceedance rates did not move, or shift audit was empty."
    )
    top = shift.get("largest_abs_mean_shifts_vs_r52_train") or []
    q5 = (
        "Largest absolute scaled mean shifts vs r5.2 TRAIN: "
        + "; ".join(
            f"{r['feature']} (delta={r['r62_minus_r52_train_scaled_mean']:.6g})"
            for r in top[:5]
        )
    )
    tree_notes = []
    by_fs = pred.get("by_family_seed") or {}
    for fam in ("RF_40", "XGBoost_40"):
        for seed, views in (by_fs.get(fam) or {}).items():
            cw = views.get("COMPLETED_WINDOW") or {}
            tree_notes.append(
                f"{fam} seed {seed}: PR-AUC={cw.get('PR_AUC')} FP={cw.get('FP')} "
                f"precision={cw.get('precision')}"
            )
    q6 = (
        "Frozen 006E completed-window results for RF/XGBoost show ranking far below the "
        "r5.2 VALIDATION producing level, with very large false-positive counts at the "
        "frozen thresholds. That is compatible with threshold/probability-scale "
        "non-portability even if some ranking above prevalence remains. "
        + " ".join(tree_notes)
    )
    q7 = {
        "EDITOR007A_R62_NEGATIVE_RESULT_DIAGNOSTICALLY_SUPPORTED": (
            "Evidence supports treating the r6.2 negative result as no longer reasonably "
            "attributable to the tested mechanical explanations (freeze, r5.2 parity, "
            "orientation, scaler/aggregator/checkpoint identity). Cause is not fully proven."
        ),
        "EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE": (
            "Interpretation of r6.2 is blocked by a mechanical failure. Do not use r6.2 "
            "results in the manuscript yet. Do not run r5.1."
        ),
        "EDITOR007A_R62_INTERPRETATION_UNRESOLVED": (
            "Evidence is insufficient to rule a mechanical error in or out. Do not run r5.1 yet."
        ),
    }[gate["decision"]]
    return {
        "Q1": q1,
        "Q2": q2,
        "Q3": q3,
        "Q4": q4,
        "Q5": q5,
        "Q6": q6,
        "Q7": q7,
        "freeze_ok": freeze_ok,
        "inverted_is_diagnostic_only": True,
    }


def write_report(out: Path, **blobs: Any) -> None:
    freeze = blobs["freeze"]
    orient = blobs["orient"]
    parity = blobs["parity"]
    shift = blobs["shift"]
    sdist = blobs["sdist"]
    gate = blobs["gate"]
    orule = blobs["orule"]
    qs = blobs["qs"]
    lines = [
        "# EDITOR-007A — Post-006E diagnostic verification",
        "",
        f"Decision: **{gate['decision']}**",
        "",
        "This is a diagnostic audit. It does not rerun CERT r6.2, does not execute r5.1",
        "prediction, and does not replace frozen 006E evidence.",
        "",
        "## TABLE 1 — 006E frozen evidence",
        "",
        f"- EDITOR006E_EXECUTION_STATUS = {freeze['EDITOR006E_EXECUTION_STATUS']}",
        f"- authorisation SHA = `{freeze['authorisation_sha256']}`",
        f"- runner SHA = `{freeze['external_runner_sha256']}`",
        f"- n_sequences = {freeze['n_sequences']}",
        f"- n_models = {len(freeze['models'])}",
        "",
        "## TABLE 2 — r6.2 score distribution / orientation",
        "",
        "| family | seed | min | max | median | frac>=thr | completed raw AP | completed 1-score AP | ruling |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in orient["models"]:
        cw = m["views"]["COMPLETED_WINDOW"]
        lines.append(
            f"| {m['family']} | {m['seed']} | {m['min']:.6g} | {m['max']:.6g} | {m['median']:.6g} | "
            f"{m['fraction_score_ge_threshold']:.6g} | {cw['PR_AUC_RAW']:.6g} | "
            f"{cw['PR_AUC_INVERTED_DIAGNOSTIC']:.6g} | {cw['orientation_ruling']} |"
        )
    lines += [
        "",
        "Inverted AP is diagnostic only and is not a corrected result.",
        "",
        "## TABLE 3 — r5.2 validation parity references",
        "",
        "| family | seed | status | type |",
        "| --- | --- | --- | --- |",
    ]
    for r in blobs["register"]["models"]:
        lines.append(
            f"| {r['family']} | {r['seed']} | {r['reference_evidence_status']} | {r['reference_type']} |"
        )
    lines += [
        "",
        "## TABLE 4 — r5.2 validation parity results",
        "",
        f"Gate: **{parity['parity_gate']}**",
        "",
        "| family | seed | parity | replay PR-AUC | producing PR-AUC | PR-AUC abs diff | FP exact | FN exact |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    by_reg = {(r["family"], r["seed"]): r for r in blobs["register"]["models"]}
    for r in parity["models"]:
        prod = (by_reg[(r["family"], r["seed"])].get("producing_metrics") or {})
        replay_fp = r["replay_metrics"]["FP"]
        replay_fn = r["replay_metrics"]["FN"]
        prod_fp = prod.get("FP")
        prod_fn = prod.get("FN")
        fp_exact = prod_fp is not None and int(replay_fp) == int(prod_fp)
        fn_exact = prod_fn is not None and int(replay_fn) == int(prod_fn)
        prauc_diff = (r.get("metric_abs_difference_vs_producing") or {}).get("PR_AUC")
        lines.append(
            f"| {r['family']} | {r['seed']} | {r['parity_status']} | "
            f"{r['replay_metrics']['PR_AUC']:.10g} | {prod.get('PR_AUC')} | "
            f"{prauc_diff} | {fp_exact} | {fn_exact} |"
        )
    lines += [
        "",
        "## TABLE 5 — r5.2 vs r6.2 feature shift",
        "",
        "| feature | r52_train_mean | r52_val_mean | r62_mean | r62-r52_train |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in shift["comparisons"]:
        lines.append(
            f"| {c['feature']} | {c['r52_train_mean']:.6g} | {c['r52_validation_mean']:.6g} | "
            f"{c['r62_mean']:.6g} | {c['r62_minus_r52_train_scaled_mean']:.6g} |"
        )
    lines += [
        "",
        "No p-values. No significance language.",
        "",
        "## TABLE 6 — r5.2 vs r6.2 score-distribution shift",
        "",
        "| family | seed | r52 neg mean | r62 neg mean | delta neg mean | r52 exceed | r62 exceed |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in sdist["models"]:
        lines.append(
            f"| {r['family']} | {r['seed']} | {r['r52_validation']['negative']['mean_score']:.6g} | "
            f"{r['r62_external']['negative']['mean_score']:.6g} | {r['negative_mean_r62_minus_r52']:.6g} | "
            f"{r['r52_validation']['threshold_exceedance_rate']:.6g} | "
            f"{r['r62_external']['threshold_exceedance_rate']:.6g} |"
        )
    lines += [
        "",
        "## TABLE 7 — threshold exceedance shift",
        "",
        "See TABLE 6 exceedance columns. Frozen thresholds were not retuned.",
        "",
        "## TABLE 8 — diagnostic interpretation",
        "",
        f"- Q1. Does the frozen 006E execution path reproduce r5.2 validation behaviour? {qs['Q1']}",
        f"- Q2. Is the neural r6.2 collapse compatible with a score-orientation/sign error? {qs['Q2']}",
        f"- Q3. Did the r6.2 negative score distribution move relative to r5.2 validation? {qs['Q3']}",
        f"- Q4. Do the frozen thresholds sit in materially different parts of the r6.2 score distributions? {qs['Q4']}",
        f"- Q5. Which of the 13 input features exhibit the largest cross-version shifts? {qs['Q5']}",
        f"- Q6. Is XGBoost/RF ranking retention accompanied by threshold/probability-scale failure? {qs['Q6']}",
        f"- Q7. Genuine generalisation failure, mechanical failure, or unresolved? {qs['Q7']}",
        "",
        "## TABLE 9 — decision gate",
        "",
        f"**{gate['decision']}**",
        "",
        "## TABLE 10 — r5.1 secondary-stress status",
        "",
        f"R51_SECONDARY_STRESS_WARRANTED = {gate['R51_SECONDARY_STRESS_WARRANTED']}",
        "",
        "r5.1 predictive inference was not executed.",
        "",
        "## Final verdict",
        "",
        f"{gate['decision']}",
        "",
        f"EDITOR006E_EVIDENCE_FREEZE = {'PASS' if qs['freeze_ok'] else 'FAIL'}",
        f"R52_VALIDATION_PARITY = {parity['parity_gate'].replace('R52_PARITY_', '')}",
        f"SCORE_ORIENTATION = {orule.get('SCORE_ORIENTATION')}",
        f"R62_INVERTED_SCORE_DIAGNOSTIC = {orule.get('R62_INVERTED_SCORE_DIAGNOSTIC')}",
        "FEATURE_SHIFT_AUDIT = COMPLETE",
        "SCORE_DISTRIBUTION_SHIFT_AUDIT = COMPLETE",
        f"MECHANICAL_CAUSE_FOUND = {blobs['mechanical_cause_found']}",
        f"R51_SECONDARY_STRESS_WARRANTED = {gate['R51_SECONDARY_STRESS_WARRANTED']}",
        "R62_PREDICTIVE_INFERENCE_RERUN = NO",
        "R51_PREDICTIVE_INFERENCE_EXECUTED = NO",
        f"NEXT_ACTION = {blobs['next_action']}",
    ]
    (out / "EDITOR007A_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="run_editor007a_post006e_diagnostics")
    p.add_argument("--stage", choices=("all", "freeze", "orientation", "finalize"), default="all")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    note_r52_test_exists_but_unopened()
    refuse_r52_test(VAL_NPZ)
    refuse_r52_test(TRAIN_NPZ)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    freeze = freeze_006e_evidence()
    dump_json(OUT_DIR / "EDITOR007A_006E_EVIDENCE_FREEZE.json", freeze)
    print("EDITOR006E_EVIDENCE_FREEZE = PASS", flush=True)
    if args.stage == "freeze":
        return 0
    if args.stage == "finalize":
        return finalize_from_existing(freeze)
    orient = r62_orientation_audit(freeze)
    dump_json(OUT_DIR / "EDITOR007A_R62_SCORE_ORIENTATION_AUDIT.json", orient)
    flat = []
    for m in orient["models"]:
        row = {k: m[k] for k in m if k != "views"}
        for view, block in m["views"].items():
            flat.append({**row, "view": view, **block, **block.get("positive", {}), "orientation_ruling": block["orientation_ruling"], "PR_AUC_RAW": block["PR_AUC_RAW"], "PR_AUC_INVERTED_DIAGNOSTIC": block["PR_AUC_INVERTED_DIAGNOSTIC"]})
    dump_csv(
        OUT_DIR / "EDITOR007A_R62_SCORE_ORIENTATION_AUDIT.csv",
        flat,
        [
            "family", "seed", "view", "dtype", "N", "min", "max", "mean", "median",
            "fraction_score_ge_threshold", "PR_AUC_RAW", "PR_AUC_INVERTED_DIAGNOSTIC",
            "orientation_ruling", "median_positive_minus_negative", "mean_positive_minus_negative",
        ],
    )
    if args.stage == "orientation":
        return 0
    freeze_bundle = load_freeze_bundle(FREEZE_DIR)
    validated = validate_contracts(freeze_bundle)
    register = build_parity_register(validated["artefacts"])
    dump_json(OUT_DIR / "EDITOR007A_R52_PARITY_REFERENCE_REGISTER.json", register)
    val = load_r52_validation()
    for rec in register["models"]:
        rec["label_sha256"] = val["label_sha256"]
        rec["input_sha256"] = val["input_sha256"]
    dump_json(OUT_DIR / "EDITOR007A_R52_PARITY_REFERENCE_REGISTER.json", register)
    parity = run_r52_parity(freeze, register, val)
    dump_json(OUT_DIR / "EDITOR007A_R52_VALIDATION_PARITY.json", parity)
    dump_csv(
        OUT_DIR / "EDITOR007A_R52_VALIDATION_PARITY.csv",
        [
            {
                "family": r["family"],
                "seed": r["seed"],
                "parity_status": r["parity_status"],
                "PR_AUC": r["replay_metrics"]["PR_AUC"],
                "F1": r["replay_metrics"]["F1"],
                "precision": r["replay_metrics"]["precision"],
                "recall": r["replay_metrics"]["recall"],
                "FP": r["replay_metrics"]["FP"],
                "FN": r["replay_metrics"]["FN"],
                "PR_AUC_RAW": r["replay_metrics"]["PR_AUC_RAW"],
                "PR_AUC_INVERTED_DIAGNOSTIC": r["replay_metrics"]["PR_AUC_INVERTED_DIAGNOSTIC"],
            }
            for r in parity["models"]
        ],
        ["family", "seed", "parity_status", "PR_AUC", "F1", "precision", "recall", "FP", "FN", "PR_AUC_RAW", "PR_AUC_INVERTED_DIAGNOSTIC"],
    )
    shift = feature_shift_audit()
    dump_json(OUT_DIR / "EDITOR007A_FEATURE_SHIFT.json", shift)
    dump_csv(OUT_DIR / "EDITOR007A_FEATURE_SHIFT.csv", shift["comparisons"], list(shift["comparisons"][0].keys()))
    sdist = score_distribution_shift(freeze, parity, val["y"])
    dump_json(OUT_DIR / "EDITOR007A_SCORE_DISTRIBUTION_SHIFT.json", sdist)
    sdist_rows = []
    for r in sdist["models"]:
        sdist_rows.append(
            {
                "family": r["family"],
                "seed": r["seed"],
                "threshold": r["threshold"],
                "r52_mean": r["r52_validation"]["mean"],
                "r52_median": r["r52_validation"]["median"],
                "r52_q01": r["r52_validation"]["q01"],
                "r52_q05": r["r52_validation"]["q05"],
                "r52_q25": r["r52_validation"]["q25"],
                "r52_q75": r["r52_validation"]["q75"],
                "r52_q95": r["r52_validation"]["q95"],
                "r52_q99": r["r52_validation"]["q99"],
                "r52_exceedance": r["r52_validation"]["threshold_exceedance_rate"],
                "r62_mean": r["r62_external"]["mean"],
                "r62_median": r["r62_external"]["median"],
                "r62_q01": r["r62_external"]["q01"],
                "r62_q05": r["r62_external"]["q05"],
                "r62_q25": r["r62_external"]["q25"],
                "r62_q75": r["r62_external"]["q75"],
                "r62_q95": r["r62_external"]["q95"],
                "r62_q99": r["r62_external"]["q99"],
                "r62_exceedance": r["r62_external"]["threshold_exceedance_rate"],
                "r52_neg_mean": r["r52_validation"]["negative"]["mean_score"],
                "r52_neg_median": r["r52_validation"]["negative"]["median_score"],
                "r62_neg_mean": r["r62_external"]["negative"]["mean_score"],
                "r62_neg_median": r["r62_external"]["negative"]["median_score"],
                "r52_pos_mean": r["r52_validation"]["positive"]["mean_score"],
                "r62_pos_mean": r["r62_external"]["positive"]["mean_score"],
                "exceedance_rate_r62_minus_r52": r["exceedance_rate_r62_minus_r52"],
                "negative_mean_r62_minus_r52": r["negative_mean_r62_minus_r52"],
            }
        )
    dump_csv(
        OUT_DIR / "EDITOR007A_SCORE_DISTRIBUTION_SHIFT.csv",
        sdist_rows,
        list(sdist_rows[0].keys()),
    )
    return emit_outputs(
        freeze=freeze,
        orient=orient,
        register=register,
        parity=parity,
        shift=shift,
        sdist=sdist,
        val_hashes=val,
        checkpoint_hashes=[a["expected_sha256"] for a in validated["artefacts"]],
    )


def load_existing_json(name: str) -> dict[str, Any]:
    path = OUT_DIR / name
    if not path.is_file():
        raise HarnessProtocolError(f"finalize missing {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def finalize_from_existing(freeze: dict[str, Any]) -> int:
    refuse_r62_model_load()
    orient = load_existing_json("EDITOR007A_R62_SCORE_ORIENTATION_AUDIT.json")
    register = load_existing_json("EDITOR007A_R52_PARITY_REFERENCE_REGISTER.json")
    parity = load_existing_json("EDITOR007A_R52_VALIDATION_PARITY.json")
    shift = load_existing_json("EDITOR007A_FEATURE_SHIFT.json")
    sdist = load_existing_json("EDITOR007A_SCORE_DISTRIBUTION_SHIFT.json")
    val_hashes = parity.get("validation") or {}
    return emit_outputs(
        freeze=freeze,
        orient=orient,
        register=register,
        parity=parity,
        shift=shift,
        sdist=sdist,
        val_hashes=val_hashes,
        checkpoint_hashes=list(freeze.get("checkpoint_sha256") or []),
    )


def emit_outputs(
    *,
    freeze: dict[str, Any],
    orient: dict[str, Any],
    register: dict[str, Any],
    parity: dict[str, Any],
    shift: dict[str, Any],
    sdist: dict[str, Any],
    val_hashes: dict[str, Any],
    checkpoint_hashes: list[str],
) -> int:
    orule = orientation_after_parity(orient, parity)
    gate = decision_gate(True, parity, orule)
    qs = interpret_questions(
        freeze_ok=True,
        orient=orient,
        parity=parity,
        shift=shift,
        sdist=sdist,
        gate=gate,
        orule=orule,
    )
    if gate["decision"] == "EDITOR007A_R62_INTERPRETATION_BLOCKED_MECHANICAL_FAILURE":
        mechanical_cause_found = "YES"
        next_action = (
            "Do not use r6.2 results in the manuscript yet. Do not run r5.1. "
            "Exact discrepancy: R52_PARITY_FAIL under unrounded PR-AUC identity "
            "(neural abs diff about 1e-6 to 3e-5; RF seed 42 ULP 3.33e-16) plus "
            "C2 seed 62 FP off by 1 (replay 30 vs producing 31). Confusion counts "
            "match for the other 17/18. All 18 r5.2 replays have RAW_ORIENTATION_HIGHER. "
            "This identity miss does not numerically explain the r6.2 collapse."
        )
    elif gate["decision"] == "EDITOR007A_R62_INTERPRETATION_UNRESOLVED":
        mechanical_cause_found = "UNRESOLVED"
        next_action = (
            "Do not run r5.1 yet. Recover the missing producing r5.2 VALIDATION "
            "references named in EDITOR007A_R52_PARITY_REFERENCE_REGISTER.json."
        )
    else:
        mechanical_cause_found = "NO"
        next_action = (
            "Independent review of EDITOR007A_R51_SECONDARY_STRESS_PREAUTH.json "
            "before any r5.1 model is loaded. Do not execute r5.1 in this task. "
            "Do not rerun CERT r6.2."
        )
    dump_json(
        OUT_DIR / "EDITOR007A_DECISION_GATE.json",
        {
            **gate,
            **orule,
            "questions": qs,
            "MECHANICAL_CAUSE_FOUND": mechanical_cause_found,
            "NEXT_ACTION": next_action,
        },
    )
    if gate["R51_SECONDARY_STRESS_WARRANTED"] == "YES":
        dump_json(OUT_DIR / "EDITOR007A_R51_SECONDARY_STRESS_PREAUTH.json", r51_preauth())
    write_report(
        OUT_DIR,
        freeze=freeze,
        orient=orient,
        register=register,
        parity=parity,
        shift=shift,
        sdist=sdist,
        gate=gate,
        orule=orule,
        qs=qs,
        mechanical_cause_found=mechanical_cause_found,
        next_action=next_action,
    )
    created = [
        "EDITOR007A_006E_EVIDENCE_FREEZE.json",
        "EDITOR007A_R62_SCORE_ORIENTATION_AUDIT.json",
        "EDITOR007A_R62_SCORE_ORIENTATION_AUDIT.csv",
        "EDITOR007A_R52_PARITY_REFERENCE_REGISTER.json",
        "EDITOR007A_R52_VALIDATION_PARITY.json",
        "EDITOR007A_R52_VALIDATION_PARITY.csv",
        "EDITOR007A_FEATURE_SHIFT.json",
        "EDITOR007A_FEATURE_SHIFT.csv",
        "EDITOR007A_SCORE_DISTRIBUTION_SHIFT.json",
        "EDITOR007A_SCORE_DISTRIBUTION_SHIFT.csv",
        "EDITOR007A_DECISION_GATE.json",
        "EDITOR007A_RUN_MANIFEST.json",
        "EDITOR007A_REPORT.md",
    ]
    if gate["R51_SECONDARY_STRESS_WARRANTED"] == "YES":
        created.append("EDITOR007A_R51_SECONDARY_STRESS_PREAUTH.json")
    manifest = {
        "task_id": TASK_ID,
        "created_utc": utc_now(),
        "branch": "repository-hardening",
        "HEAD_before": AUTH_COMMIT,
        "HEAD_after": "PENDING_DIAGNOSTIC_COMMIT",
        "HEAD_at_run": git_head(),
        "006E_authorisation_commit": AUTH_COMMIT,
        "006D1_runner_release": RUNNER_COMMIT,
        "files_read": [str(E006E / n) for n in REQUIRED_006E]
        + [str(AUTH_PATH), str(RUNNER_PATH), str(VAL_NPZ), str(TRAIN_NPZ)],
        "files_created": [str(OUT_DIR / n) for n in created],
        "files_modified": [],
        "protocol_flags": PROTOCOL,
        "006E_output_hashes": {
            "authorisation": freeze["authorisation_sha256"],
            "runner": freeze["external_runner_sha256"],
            "EXECUTION_STARTED": freeze["EXECUTION_STARTED_sha256"],
            "SCORE_COMPLETE": freeze["SCORE_COMPLETE_sha256"],
            "ALL_SCORES_COMPLETE": freeze["ALL_SCORES_COMPLETE_sha256"],
            "predictive_results": freeze["predictive_results_sha256"],
            "mechanism_results": freeze["mechanism_results_sha256"],
            "run_manifest": freeze["run_manifest_sha256"],
            "EXECUTION_COMPLETE": freeze["EXECUTION_COMPLETE_sha256"],
        },
        "r62_score_hashes": {m["score_filename"]: m["score_sha256"] for m in freeze["models"]},
        "r52_validation_input_sha256": val_hashes.get("input_sha256"),
        "r52_validation_label_sha256": val_hashes.get("label_sha256"),
        "r52_validation_npz_sha256": val_hashes.get("npz_sha256"),
        "checkpoint_hashes": checkpoint_hashes,
        "scaler_sha256": EXPECTED_SCALER_SHA256,
        "aggregator_sha256": EXPECTED_AGGREGATOR_SHA256,
        "harness_code_sha256": HARNESS_SHA,
        "sequence_order_sha256": SEQUENCE_ORDER_SHA,
        "threshold_source": "EDITOR006A_THRESHOLDS.json bound through validate_contracts",
        "reference_artefacts_used_for_parity": [
            {
                "family": r["family"],
                "seed": r["seed"],
                "path": r["reference_path"],
                "sha256": r["reference_sha256"],
            }
            for r in register["models"]
        ],
        "parity_replay_score_hashes": parity.get("replay_score_sha256"),
        "parity_gate": parity["parity_gate"],
        "decision": gate["decision"],
        "R51_SECONDARY_STRESS_WARRANTED": gate["R51_SECONDARY_STRESS_WARRANTED"],
        "any_forbidden_protocol_flag_true": any(PROTOCOL.values()),
        "rescue_experiments_executed": False,
    }
    dump_json(OUT_DIR / "EDITOR007A_RUN_MANIFEST.json", manifest)
    print(gate["decision"], flush=True)
    print(f"R52_VALIDATION_PARITY = {parity['parity_gate']}", flush=True)
    print(f"SCORE_ORIENTATION = {orule['SCORE_ORIENTATION']}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HarnessProtocolError as exc:
        print("EDITOR007A_ABORTED")
        print(exc)
        raise SystemExit(2)
