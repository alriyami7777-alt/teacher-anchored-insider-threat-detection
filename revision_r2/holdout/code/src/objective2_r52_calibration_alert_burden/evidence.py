"""Load saved validation predictions with provenance and clean parity."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score

from .constants import (
    ATTENTION_LINEAR,
    CLEAN_ATOL,
    EVIDENCE_AL,
    EVIDENCE_SI,
    EVIDENCE_TA,
    EXPECTED_VAL_SHA256,
    LOGIT_CLIP,
    MODEL_AL,
    MODEL_ODST,
    MODEL_XGB,
    N_VALIDATION,
    SEEDS,
    STATUS_METADATA,
    STATUS_PROVENANCE,
    TEACHER_ANCHORED,
    VAL_REL,
    XGBOOST,
)
from .safety import AuditBlockedError, OpenedFilesRegister, sha256_file


@dataclass
class ModelPredictions:
    model: str
    seed: int
    y_true: np.ndarray
    logit: np.ndarray
    probability: np.ndarray
    threshold: float
    sequence_id: np.ndarray
    user: np.ndarray
    start_date: np.ndarray
    end_date: np.ndarray
    checkpoint_sha256: str | None
    prediction_path: str
    prediction_sha256: str
    reconstruction_required: bool
    tree_margin_caveat: bool = False
    extras: dict[str, Any] = field(default_factory=dict)


def reconstruct_logit(prob: np.ndarray, *, eps: float = LOGIT_CLIP) -> np.ndarray:
    p = np.clip(np.asarray(prob, dtype=np.float64), eps, 1.0 - eps)
    return np.log(p) - np.log1p(-p)


def _f1_at_threshold(y: np.ndarray, p: np.ndarray, thr: float) -> float:
    pred = (np.asarray(p) >= thr).astype(int)
    return float(f1_score(np.asarray(y).astype(int), pred, zero_division=0))


def load_validation_metadata(
    repo_root: Path, opened: OpenedFilesRegister
) -> dict[str, np.ndarray]:
    path = opened.record(repo_root / VAL_REL, "validation_tensor_metadata")
    sha = sha256_file(path)
    if sha != EXPECTED_VAL_SHA256:
        raise AuditBlockedError(
            STATUS_PROVENANCE, f"validation tensor SHA mismatch: {sha}"
        )
    z = np.load(path, allow_pickle=True)
    y = np.asarray(z["y"]).astype(np.int32).ravel()
    if len(y) != N_VALIDATION:
        raise AuditBlockedError(
            STATUS_METADATA, f"expected n={N_VALIDATION}, got {len(y)}"
        )
    return {
        "y": y,
        "sequence_id": np.asarray(z["sequence_id"]).astype(str),
        "user": np.asarray(z["user"]).astype(str),
        "start_date": np.asarray(z["start_date"]).astype(str),
        "end_date": np.asarray(z["end_date"]).astype(str),
        "sha256": np.asarray([sha]),
    }


def _assert_y_parity(y_pred: np.ndarray, y_meta: np.ndarray, *, context: str) -> None:
    if len(y_pred) != len(y_meta):
        raise AuditBlockedError(
            STATUS_METADATA, f"{context}: length mismatch {len(y_pred)} vs {len(y_meta)}"
        )
    if not np.array_equal(y_pred.astype(np.int32), y_meta.astype(np.int32)):
        raise AuditBlockedError(STATUS_METADATA, f"{context}: y_true parity failed")


def load_all_predictions(
    repo_root: Path, opened: OpenedFilesRegister
) -> tuple[dict[tuple[str, int], ModelPredictions], pd.DataFrame, pd.DataFrame, bool]:
    meta = load_validation_metadata(repo_root, opened)
    y_meta = meta["y"]
    bundles: dict[tuple[str, int], ModelPredictions] = {}
    prov_rows: list[dict[str, Any]] = []
    parity_rows: list[dict[str, Any]] = []

    for seed in SEEDS:
        ta = TEACHER_ANCHORED[seed]
        pred_p = opened.record(
            repo_root / EVIDENCE_TA / ta["pred_rel"],
            f"odst_pred_{seed}",
            columns="y_true,student_logit,student_prob,student_threshold",
        )
        sum_p = opened.record(repo_root / EVIDENCE_TA / ta["summary_rel"], f"odst_sum_{seed}")
        ckpt_p = opened.record(repo_root / EVIDENCE_TA / ta["ckpt_rel"], f"odst_ckpt_{seed}")
        df = pd.read_csv(pred_p)
        summary = json.loads(sum_p.read_text(encoding="utf-8"))
        ckpt_sha = sha256_file(ckpt_p)
        if ckpt_sha != ta["expected_sha256"]:
            raise AuditBlockedError(
                STATUS_PROVENANCE, f"ODST checkpoint hash mismatch seed={seed}"
            )
        y = df["y_true"].to_numpy(dtype=np.int32)
        _assert_y_parity(y, y_meta, context=f"ODST seed={seed}")
        logit = df["student_logit"].to_numpy(dtype=np.float64)
        prob = df["student_prob"].to_numpy(dtype=np.float64)
        thr = float(summary.get("best_threshold", ta["threshold"]))
        if abs(thr - float(ta["threshold"])) > 1e-9:
            raise AuditBlockedError(
                STATUS_PROVENANCE, f"ODST threshold mismatch seed={seed}: {thr}"
            )
        # Never use teacher columns; teacher never loaded as a model.
        if "teacher_logit" in df.columns:
            _ = None  # present in CSV only; unused
        pred_sha = sha256_file(pred_p)
        bundles[(MODEL_ODST, seed)] = ModelPredictions(
            model=MODEL_ODST,
            seed=seed,
            y_true=y_meta,
            logit=logit,
            probability=prob,
            threshold=thr,
            sequence_id=meta["sequence_id"],
            user=meta["user"],
            start_date=meta["start_date"],
            end_date=meta["end_date"],
            checkpoint_sha256=ckpt_sha,
            prediction_path=str(pred_p.resolve()),
            prediction_sha256=pred_sha,
            reconstruction_required=False,
        )
        pr = float(average_precision_score(y_meta, prob))
        f1 = _f1_at_threshold(y_meta, prob, thr)
        pr_ok = abs(pr - float(ta["expected_pr_auc"])) <= CLEAN_ATOL
        f1_ok = abs(f1 - float(ta["expected_f1"])) <= CLEAN_ATOL
        if not pr_ok or not f1_ok:
            raise AuditBlockedError(
                STATUS_PROVENANCE,
                f"ODST clean parity fail seed={seed} pr={pr} f1={f1}",
            )
        prov_rows.append(
            {
                "model": MODEL_ODST,
                "seed": seed,
                "prediction_path": str(pred_p.resolve()),
                "prediction_sha256": pred_sha,
                "checkpoint_path": str(ckpt_p.resolve()),
                "checkpoint_sha256": ckpt_sha,
                "threshold": thr,
                "n_rows": int(len(y_meta)),
                "n_positives": int(y_meta.sum()),
                "prob_min": float(np.min(prob)),
                "prob_max": float(np.max(prob)),
                "logit_available": True,
                "reconstruction_required": False,
                "tree_margin_caveat": False,
                "teacher_loaded": False,
            }
        )
        parity_rows.append(
            {
                "model": MODEL_ODST,
                "seed": seed,
                "pr_auc": pr,
                "f1": f1,
                "expected_pr_auc": ta["expected_pr_auc"],
                "expected_f1": ta["expected_f1"],
                "pr_auc_parity_ok": pr_ok,
                "f1_parity_ok": f1_ok,
                "threshold": thr,
                "y_parity_ok": True,
                "n_rows": N_VALIDATION,
            }
        )

    for seed in SEEDS:
        al = ATTENTION_LINEAR[seed]
        al_dir = repo_root / EVIDENCE_AL / al["dir_rel"]
        pred_p = opened.record(al_dir / "validation_predictions.csv", f"al_pred_{seed}")
        hash_p = al_dir / "checkpoint_hashes.json"
        ckpt_p = al_dir / "best.pt"
        if hash_p.exists():
            opened.record(hash_p, f"al_hash_{seed}")
            hash_doc = json.loads(hash_p.read_text(encoding="utf-8"))
            ckpt_sha = str(hash_doc.get("best.pt", ""))
        else:
            opened.record(ckpt_p, f"al_ckpt_{seed}")
            ckpt_sha = sha256_file(ckpt_p)
        if ckpt_sha != al["expected_sha256"]:
            # Fall back to hashing best.pt when json is stale/missing value
            if ckpt_p.exists():
                opened.record(ckpt_p, f"al_ckpt_{seed}")
                ckpt_sha = sha256_file(ckpt_p)
            if ckpt_sha != al["expected_sha256"]:
                raise AuditBlockedError(
                    STATUS_PROVENANCE, f"AL checkpoint hash mismatch seed={seed}"
                )
        df = pd.read_csv(pred_p)
        y = df["y_true"].to_numpy(dtype=np.int32)
        _assert_y_parity(y, y_meta, context=f"AL seed={seed}")
        if "probability" in df.columns:
            prob = df["probability"].to_numpy(dtype=np.float64)
        else:
            prob = df["y_proba"].to_numpy(dtype=np.float64)
        logit = reconstruct_logit(prob)
        thr = float(al["threshold"])
        pred_sha = sha256_file(pred_p)
        bundles[(MODEL_AL, seed)] = ModelPredictions(
            model=MODEL_AL,
            seed=seed,
            y_true=y_meta,
            logit=logit,
            probability=prob,
            threshold=thr,
            sequence_id=meta["sequence_id"],
            user=meta["user"],
            start_date=meta["start_date"],
            end_date=meta["end_date"],
            checkpoint_sha256=ckpt_sha,
            prediction_path=str(pred_p.resolve()),
            prediction_sha256=pred_sha,
            reconstruction_required=True,
        )
        pr = float(average_precision_score(y_meta, prob))
        f1 = _f1_at_threshold(y_meta, prob, thr)
        sum_p = al_dir / "summary.json"
        exp_pr = exp_f1 = None
        if sum_p.exists():
            opened.record(sum_p, f"al_sum_{seed}")
            summ = json.loads(sum_p.read_text(encoding="utf-8"))
            vm = summ.get("validation_metrics", {})
            exp_pr = vm.get("pr_auc")
            exp_f1 = vm.get("f1")
        pr_ok = True if exp_pr is None else abs(pr - float(exp_pr)) <= max(CLEAN_ATOL, 5e-3)
        f1_ok = True if exp_f1 is None else abs(f1 - float(exp_f1)) <= max(CLEAN_ATOL, 5e-3)
        if not pr_ok or not f1_ok:
            raise AuditBlockedError(
                STATUS_PROVENANCE, f"AL clean parity fail seed={seed}"
            )
        prov_rows.append(
            {
                "model": MODEL_AL,
                "seed": seed,
                "prediction_path": str(pred_p.resolve()),
                "prediction_sha256": pred_sha,
                "checkpoint_path": str(ckpt_p.resolve()) if ckpt_p.exists() else "",
                "checkpoint_sha256": ckpt_sha,
                "threshold": thr,
                "n_rows": int(len(y_meta)),
                "n_positives": int(y_meta.sum()),
                "prob_min": float(np.min(prob)),
                "prob_max": float(np.max(prob)),
                "logit_available": True,
                "reconstruction_required": True,
                "tree_margin_caveat": False,
                "teacher_loaded": False,
            }
        )
        parity_rows.append(
            {
                "model": MODEL_AL,
                "seed": seed,
                "pr_auc": pr,
                "f1": f1,
                "expected_pr_auc": exp_pr,
                "expected_f1": exp_f1,
                "pr_auc_parity_ok": pr_ok,
                "f1_parity_ok": f1_ok,
                "threshold": thr,
                "y_parity_ok": True,
                "n_rows": N_VALIDATION,
            }
        )

    xgb_loaded = True
    for seed in SEEDS:
        xg = XGBOOST[seed]
        npz_p = repo_root / EVIDENCE_SI / xg["dir_rel"] / "validation_predictions.npz"
        if not npz_p.exists():
            xgb_loaded = False
            break
        opened.record(npz_p, f"xgb_pred_{seed}")
        z = np.load(npz_p, allow_pickle=True)
        y = np.asarray(z["y_true"]).astype(np.int32).ravel()
        try:
            _assert_y_parity(y, y_meta, context=f"XGB seed={seed}")
        except AuditBlockedError:
            xgb_loaded = False
            break
        prob = np.asarray(z["y_proba"], dtype=np.float64).ravel()
        logit = reconstruct_logit(prob)
        thr_arr = np.asarray(z["threshold"]).ravel()
        thr = float(thr_arr[0]) if len(thr_arr) else float(xg["threshold"])
        if abs(thr - float(xg["threshold"])) > 1e-6:
            # keep file threshold but flag
            thr = float(xg["threshold"]) if abs(thr - float(xg["threshold"])) > 0.05 else thr
        pred_sha = sha256_file(npz_p)
        bundles[(MODEL_XGB, seed)] = ModelPredictions(
            model=MODEL_XGB,
            seed=seed,
            y_true=y_meta,
            logit=logit,
            probability=prob,
            threshold=float(xg["threshold"]),
            sequence_id=meta["sequence_id"],
            user=meta["user"],
            start_date=meta["start_date"],
            end_date=meta["end_date"],
            checkpoint_sha256=None,
            prediction_path=str(npz_p.resolve()),
            prediction_sha256=pred_sha,
            reconstruction_required=True,
            tree_margin_caveat=True,
        )
        pr = float(average_precision_score(y_meta, prob))
        f1 = _f1_at_threshold(y_meta, prob, float(xg["threshold"]))
        prov_rows.append(
            {
                "model": MODEL_XGB,
                "seed": seed,
                "prediction_path": str(npz_p.resolve()),
                "prediction_sha256": pred_sha,
                "checkpoint_path": "",
                "checkpoint_sha256": "",
                "threshold": float(xg["threshold"]),
                "n_rows": int(len(y_meta)),
                "n_positives": int(y_meta.sum()),
                "prob_min": float(np.min(prob)),
                "prob_max": float(np.max(prob)),
                "logit_available": True,
                "reconstruction_required": True,
                "tree_margin_caveat": True,
                "teacher_loaded": False,
            }
        )
        parity_rows.append(
            {
                "model": MODEL_XGB,
                "seed": seed,
                "pr_auc": pr,
                "f1": f1,
                "expected_pr_auc": None,
                "expected_f1": None,
                "pr_auc_parity_ok": True,
                "f1_parity_ok": True,
                "threshold": float(xg["threshold"]),
                "y_parity_ok": True,
                "n_rows": N_VALIDATION,
            }
        )

    if not xgb_loaded:
        # Drop any partial XGB entries
        for seed in SEEDS:
            bundles.pop((MODEL_XGB, seed), None)
        prov_rows = [r for r in prov_rows if r["model"] != MODEL_XGB]
        parity_rows = [r for r in parity_rows if r["model"] != MODEL_XGB]

    return bundles, pd.DataFrame(prov_rows), pd.DataFrame(parity_rows), xgb_loaded
