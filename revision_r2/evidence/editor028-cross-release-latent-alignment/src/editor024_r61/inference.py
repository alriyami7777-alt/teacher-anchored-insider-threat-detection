"""Frozen-checkpoint inference. No parameter update. No target-side fitting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics import (
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
)

from editor012_rescue.metrics import sigmoid, teacher_relative
from editor012_rescue.models import student_forward
from editor013_odst_value.models import editor013_forward
from editor017_robustness.models import load_l1, load_odst, parameter_fingerprint

from .cert_parse import gather_windows
from .constants import BATCH_SIZE, ROUTE_MODELS, SEEDS, STUDENT_MODELS, TEACHER_MODEL
from .io_util import write_npz
from .safety import OUTPUT_ROOT, Editor024Blocked, utc_now


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def _unload(loaded: dict[str, Any], device: torch.device) -> None:
    if loaded["family"] == "linear":
        del loaded["student"], loaded["modules"]
    else:
        del loaded["model"]
    if device.type == "cuda":
        torch.cuda.empty_cache()


def load_student(alias: str, seed: int, device: torch.device) -> dict[str, Any]:
    if alias == "L1":
        student, modules, sha = load_l1(seed, device)
        fp = parameter_fingerprint(student, modules)
        return {"student": student, "modules": modules, "sha256": sha, "fingerprint": fp, "family": "linear"}
    model, sha = load_odst(alias, seed, device)
    fp = parameter_fingerprint(model)
    return {"model": model, "sha256": sha, "fingerprint": fp, "family": "odst"}


def assert_fingerprint(alias: str, seed: int, loaded: dict[str, Any]) -> None:
    if loaded["family"] == "linear":
        now = parameter_fingerprint(loaded["student"], loaded["modules"])
    else:
        now = parameter_fingerprint(loaded["model"])
    if now != loaded["fingerprint"]:
        raise Editor024Blocked(
            f"EDITOR024_TRAINING_GATE = FAIL: parameter update detected for {alias}/{seed}"
        )


@torch.no_grad()
def _forward_odst(model: torch.nn.Module, xb: torch.Tensor, *, routes: bool) -> dict[str, np.ndarray]:
    out = student_forward(model, xb)
    rec = {"logit": out["logit"].detach().cpu().numpy()}
    if routes:
        rec["choices"] = out["choices"].detach().cpu().numpy()
        rec["leaf_probs_all"] = out["leaf_probs_all"].detach().cpu().numpy()
    return rec


@torch.no_grad()
def _forward_l1(student: torch.nn.Module, modules: torch.nn.Module, xb: torch.Tensor) -> dict[str, np.ndarray]:
    out = editor013_forward(student, xb, modules)
    return {"logit": out["logit"].detach().cpu().numpy()}


def score_windows(
    *,
    alias: str,
    seed: int,
    dense: np.ndarray,
    user_idx: np.ndarray,
    start_idx: np.ndarray,
    y: np.ndarray,
    threshold: float,
    device: torch.device,
    collect_routes: bool = False,
    teacher_loaded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    loaded = load_student(alias, seed, device)
    n = int(len(y))
    logits = np.empty(n, dtype=np.float64)
    route_acc = {
        "n": 0,
        "mae_sum": 0.0,
        "kl_sum": 0.0,
        "hard_sum": 0.0,
        "leaf_sum": 0.0,
        "leaf_n": 0,
    }
    if loaded["family"] == "odst":
        loaded["model"].eval()
    else:
        loaded["student"].eval()
        loaded["modules"].eval()
    if teacher_loaded is not None:
        teacher_loaded["model"].eval()

    for lo in range(0, n, BATCH_SIZE):
        hi = min(n, lo + BATCH_SIZE)
        windows = gather_windows(dense, user_idx[lo:hi], start_idx[lo:hi])
        xb = torch.from_numpy(np.ascontiguousarray(windows)).to(device)
        if loaded["family"] == "linear":
            rec = _forward_l1(loaded["student"], loaded["modules"], xb)
        else:
            rec = _forward_odst(loaded["model"], xb, routes=collect_routes and teacher_loaded is not None)
        logits[lo:hi] = rec["logit"].reshape(-1)
        if collect_routes and teacher_loaded is not None and "choices" in rec:
            t_rec = _forward_odst(teacher_loaded["model"], xb, routes=True)
            rel = teacher_relative(
                rec["logit"],
                t_rec["logit"],
                rec["choices"],
                t_rec["choices"],
                rec.get("leaf_probs_all"),
                t_rec.get("leaf_probs_all"),
            )
            bsz = hi - lo
            route_acc["n"] += bsz
            if "route_MAE" in rel:
                route_acc["mae_sum"] += float(rel["route_MAE"]) * bsz
                route_acc["kl_sum"] += float(rel["route_KL"]) * bsz
                route_acc["hard_sum"] += float(rel["hard_route_agreement"]) * bsz
            if "dominant_leaf_agreement" in rel:
                route_acc["leaf_sum"] += float(rel["dominant_leaf_agreement"]) * bsz
                route_acc["leaf_n"] += bsz
        del xb

    assert_fingerprint(alias, seed, loaded)
    _unload(loaded, device)
    probs = sigmoid(logits)
    pred = (probs >= float(threshold)).astype(np.int8)
    out: dict[str, Any] = {
        "model": alias,
        "seed": int(seed),
        "logits": logits,
        "probs": probs,
        "pred": pred,
        "threshold": float(threshold),
        "fingerprint_unchanged": True,
    }
    if collect_routes and route_acc["n"] > 0:
        out["route"] = {
            "teacher_relative_route_MAE": route_acc["mae_sum"] / route_acc["n"],
            "teacher_relative_route_KL": route_acc["kl_sum"] / route_acc["n"],
            "hard_route_agreement": route_acc["hard_sum"] / route_acc["n"],
            "dominant_leaf_agreement": (
                route_acc["leaf_sum"] / route_acc["leaf_n"] if route_acc["leaf_n"] else float("nan")
            ),
        }
    return out


def write_raw_predictions(
    *,
    alias: str,
    seed: int,
    view: str,
    user_ids: np.ndarray,
    sequence_ids: np.ndarray,
    y: np.ndarray,
    scored: dict[str, Any],
) -> Path:
    dest = OUTPUT_ROOT / "raw_predictions"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{alias}_seed{seed}_{view}.npz"
    write_npz(
        path,
        user_id=np.asarray(user_ids).astype(str),
        sequence_id=np.asarray(sequence_ids).astype(str),
        label=np.asarray(y).astype(np.int8),
        logit=np.asarray(scored["logits"], dtype=np.float64),
        probability=np.asarray(scored["probs"], dtype=np.float64),
        frozen_threshold=np.array([scored["threshold"]], dtype=np.float64),
        thresholded_prediction=np.asarray(scored["pred"], dtype=np.int8),
    )
    return path


def threshold_metrics(y: np.ndarray, probs: np.ndarray, threshold: float) -> dict[str, float]:
    y = np.asarray(y).astype(int).ravel()
    p = np.clip(np.asarray(probs, dtype=np.float64).ravel(), 1e-7, 1 - 1e-7)
    pred = (p >= float(threshold)).astype(int)
    return {
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "F1": float(f1_score(y, pred, zero_division=0)),
        "false_positives": float(int(np.sum((pred == 1) & (y == 0)))),
        "false_negatives": float(int(np.sum((pred == 0) & (y == 1)))),
        "Brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "threshold": float(threshold),
        "THRESHOLD_SOURCE": "R52_FROZEN",
    }


def maybe_load_teacher(seed: int, device: torch.device) -> dict[str, Any] | None:
    try:
        model, sha = load_odst(TEACHER_MODEL, seed, device)
        fp = parameter_fingerprint(model)
        model.eval()
        for p in model.parameters():
            p.requires_grad = False
        return {"model": model, "sha256": sha, "fingerprint": fp, "family": "odst"}
    except Exception as exc:  # noqa: BLE001
        _log(f"teacher load skipped for seed {seed}: {exc}")
        return None
