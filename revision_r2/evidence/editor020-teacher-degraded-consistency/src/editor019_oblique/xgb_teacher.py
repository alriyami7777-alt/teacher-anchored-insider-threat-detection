"""Frozen r5.2 TRAIN-only XGBoost-40 teacher. Never retrain or tune XGB."""

from __future__ import annotations

from typing import Any

import numpy as np
from xgboost import XGBClassifier

from .constants import LOCKED_AGG_FEATURES, XGB40_EXPECTED_SHA256, XGB40_PATH, XGB40_SEED, XGB_PROB_EPS
from .safety import Editor019Blocked, Editor019ProtocolError, note_open, sha256_file


def load_frozen_xgb40() -> dict[str, Any]:
    path = note_open(XGB40_PATH, role="frozen_xgb40")
    if not path.is_file():
        raise Editor019ProtocolError(f"missing frozen XGBoost-40 artefact: {path}")
    digest = sha256_file(path)
    if digest != XGB40_EXPECTED_SHA256:
        raise Editor019Blocked(f"XGB40 hash mismatch expected={XGB40_EXPECTED_SHA256} observed={digest}")
    before = sha256_file(path)
    model = XGBClassifier()
    model.load_model(str(path))
    after = sha256_file(path)
    if before != after:
        raise Editor019Blocked("XGBoost artefact mutated on load")
    return {
        "model": model,
        "path": str(path),
        "sha256": after,
        "seed": XGB40_SEED,
        "retrained": False,
        "feature_order": list(LOCKED_AGG_FEATURES),
        "n_features": 40,
    }


def xgb_probability(model: Any, raw40: np.ndarray) -> np.ndarray:
    if raw40.ndim != 2 or raw40.shape[1] != 40:
        raise Editor019ProtocolError(f"XGB expects raw 40-summary features; got {raw40.shape}")
    return np.asarray(model.predict_proba(raw40)[:, 1], dtype=np.float64)


def xgb_logit_from_prob(prob: np.ndarray, *, eps: float = XGB_PROB_EPS) -> np.ndarray:
    p = np.clip(np.asarray(prob, dtype=np.float64), eps, 1.0 - eps)
    return np.log(p / (1.0 - p)).astype(np.float32)


def xgb_residual(xgb_logit: np.ndarray, l1_logit: np.ndarray) -> np.ndarray:
    return np.asarray(xgb_logit, dtype=np.float32).reshape(-1) - np.asarray(l1_logit, dtype=np.float32).reshape(-1)


def score_frozen_xgb(
    *,
    raw_train: np.ndarray,
    raw_select: np.ndarray,
    l1_train: np.ndarray,
    l1_select: np.ndarray,
) -> dict[str, Any]:
    pack = load_frozen_xgb40()
    p_tr = xgb_probability(pack["model"], raw_train)
    p_se = xgb_probability(pack["model"], raw_select)
    z_tr = xgb_logit_from_prob(p_tr)
    z_se = xgb_logit_from_prob(p_se)
    return {
        **{k: v for k, v in pack.items() if k != "model"},
        "train_prob": p_tr.astype(np.float32),
        "select_prob": p_se.astype(np.float32),
        "train_logit": z_tr,
        "select_logit": z_se,
        "train_residual": xgb_residual(z_tr, l1_train),
        "select_residual": xgb_residual(z_se, l1_select),
        "temperature_scaled": False,
        "validation_calibrated": False,
        "test_accessed": False,
    }
