"""Stage-0 model-free shift and input-space class-signal diagnostics."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from editor025_r61_autopsy.feature_shift import (
    mean_shift_z,
    out_of_support_rate,
    population_stability_index,
    support_bounds_from_train,
)

from .constants import (
    BINARY_FEATURES,
    EDITOR025_ORIGINAL_MEAN_SHIFT_Z,
    EDITOR025_ORIGINAL_PSI,
    EDITOR026_CENTERED_MEAN_PSI,
    EDITOR026_CENTERED_PSI,
    FEATURE_ORDER,
    G0A_MEAN_ABS_SHIFT_REDUCTION_MIN,
    G0B_MEAN_PSI_REDUCTION_VS_ORIGINAL_MIN,
    G0C_N_FEATURES_LOWER_PSI_MIN,
    G0D_MEAN_PSI_REDUCTION_VS_CENTERED_MIN,
    G0F_EDITOR024_INPUT_TRANSFER_MIN,
    G0G_INSIDER_INPUT_TRANSFER_MIN,
    SEPARATION_EPSILON,
    VOLUME_FEATURES,
)
from .windows import flatten_windows


def original_mean_abs_shift() -> float:
    return float(np.mean([abs(EDITOR025_ORIGINAL_MEAN_SHIFT_Z[f]) for f in FEATURE_ORDER]))


def original_mean_psi() -> float:
    return float(np.mean([EDITOR025_ORIGINAL_PSI[f] for f in FEATURE_ORDER]))


def centered_mean_psi() -> float:
    return float(np.mean([EDITOR026_CENTERED_PSI[f] for f in FEATURE_ORDER]))


def feature_shift_rows(
    *,
    r52_train_scaled: np.ndarray,
    r61_scaled: np.ndarray,
    r52_train_scale_raw: np.ndarray,
    r61_scale_raw: np.ndarray,
    feature_order: Sequence[str] = FEATURE_ORDER,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tr = np.asarray(r52_train_scaled, dtype=np.float64)
    tg = np.asarray(r61_scaled, dtype=np.float64)
    tr_raw = np.asarray(r52_train_scale_raw, dtype=np.float64)
    tg_raw = np.asarray(r61_scale_raw, dtype=np.float64)
    if tr.ndim > 2:
        tr = tr.reshape(-1, tr.shape[-1])
    if tg.ndim > 2:
        tg = tg.reshape(-1, tg.shape[-1])
    if tr_raw.ndim > 2:
        tr_raw = tr_raw.reshape(-1, tr_raw.shape[-1])
    if tg_raw.ndim > 2:
        tg_raw = tg_raw.reshape(-1, tg_raw.shape[-1])
    for j, name in enumerate(feature_order):
        lo, hi = support_bounds_from_train(tr_raw[:, j])
        psi = population_stability_index(tr[:, j], tg[:, j])
        rec = {
            "feature": name,
            "MEAN_SHIFT_Z": mean_shift_z(float(np.mean(tg[:, j])), float(np.mean(tr[:, j]))),
            "PSI_R61_VS_R52": psi,
            "out_of_support_rate": out_of_support_rate(tg_raw[:, j], lo, hi),
            "support_lo_scale_raw": lo,
            "support_hi_scale_raw": hi,
            "ORIGINAL_SHIFT_REFERENCE": EDITOR025_ORIGINAL_MEAN_SHIFT_Z[name],
            "original_MEAN_SHIFT_Z": EDITOR025_ORIGINAL_MEAN_SHIFT_Z[name],
            "original_PSI": EDITOR025_ORIGINAL_PSI[name],
            "CENTERED_SHIFT_REFERENCE": EDITOR026_CENTERED_PSI[name],
            "centered_PSI": EDITOR026_CENTERED_PSI[name],
            "psi_lower_than_original": bool(psi < EDITOR025_ORIGINAL_PSI[name]),
            "psi_lower_than_centered": bool(psi < EDITOR026_CENTERED_PSI[name]),
            "is_volume": name in VOLUME_FEATURES,
            "is_binary": name in BINARY_FEATURES,
            "bins_fitted_from": "R52_TRAIN",
            "oos_bounds_fitted_from": "R52_TRAIN",
        }
        rows.append(rec)
    return rows


def reduction_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    new_abs = np.mean([abs(float(r["MEAN_SHIFT_Z"])) for r in rows])
    new_psi = np.mean([float(r["PSI_R61_VS_R52"]) for r in rows])
    orig_abs = original_mean_abs_shift()
    orig_psi = original_mean_psi()
    cent_psi = centered_mean_psi()
    n_lower = int(sum(1 for r in rows if r["psi_lower_than_original"]))
    mean_abs_red = 1.0 - (float(new_abs) / float(orig_abs)) if orig_abs != 0.0 else float("nan")
    mean_psi_red = 1.0 - (float(new_psi) / float(orig_psi)) if orig_psi != 0.0 else float("nan")
    mean_psi_vs_centered = 1.0 - (float(new_psi) / float(cent_psi)) if cent_psi != 0.0 else float("nan")
    g0a = bool(mean_abs_red >= G0A_MEAN_ABS_SHIFT_REDUCTION_MIN)
    g0b = bool(mean_psi_red >= G0B_MEAN_PSI_REDUCTION_VS_ORIGINAL_MIN)
    g0c = bool(n_lower >= G0C_N_FEATURES_LOWER_PSI_MIN)
    g0d = bool(mean_psi_vs_centered >= G0D_MEAN_PSI_REDUCTION_VS_CENTERED_MIN)
    dist_pass = bool(g0a and g0b and g0c and g0d)
    return {
        "MEAN_ABS_SHIFT_REDUCTION": mean_abs_red,
        "MEAN_PSI_REDUCTION_VS_ORIGINAL": mean_psi_red,
        "MEAN_PSI_REDUCTION": mean_psi_red,
        "N_FEATURES_LOWER_PSI_VS_ORIGINAL": n_lower,
        "N_FEATURES_WITH_LOWER_PSI": n_lower,
        "MEAN_PSI_REDUCTION_VS_CENTERED": mean_psi_vs_centered,
        "n_features": 13,
        "new_mean_abs_shift_z": float(new_abs),
        "original_mean_abs_shift_z": float(orig_abs),
        "new_mean_psi": float(new_psi),
        "original_mean_psi": float(orig_psi),
        "centered_mean_psi": float(cent_psi),
        "centered_mean_psi_frozen": EDITOR026_CENTERED_MEAN_PSI,
        "ORIGINAL_SHIFT_REFERENCE": "EDITOR-025 frozen absolute-representation shift/PSI",
        "CENTERED_SHIFT_REFERENCE": "EDITOR-026 frozen centred user-relative Stage-0 PSI",
        "G0A": g0a,
        "G0B": g0b,
        "G0C": g0c,
        "G0D": g0d,
        "EDITOR027_DISTRIBUTION_GATE": "PASS" if dist_pass else "FAIL",
        "EDITOR027_REPRESENTATION_DISTRIBUTION_GATE": "PASS" if dist_pass else "FAIL",
    }


def discriminant_direction(x_pos: np.ndarray, x_neg: np.ndarray) -> np.ndarray:
    """d = mean_pos - mean_neg. r5.2 TRAIN only. No classifier fitting."""
    return np.asarray(x_pos, dtype=np.float64).mean(axis=0) - np.asarray(x_neg, dtype=np.float64).mean(
        axis=0
    )


def project(x: np.ndarray, direction: np.ndarray) -> np.ndarray:
    return np.asarray(x, dtype=np.float64) @ np.asarray(direction, dtype=np.float64).ravel()


def class_separation(proj_pos: np.ndarray, proj_neg: np.ndarray, neg_sd_ref: float) -> float:
    sd = float(neg_sd_ref) + float(SEPARATION_EPSILON)
    return float((np.mean(proj_pos) - np.mean(proj_neg)) / sd)


def input_transfer_ratio(r61_sep: float, r52_sep: float) -> float:
    if r52_sep == 0.0 or not np.isfinite(r52_sep):
        return float("nan")
    return float(r61_sep / r52_sep)


def input_signal_packet(
    *,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    x_r61: np.ndarray,
    y_r61_editor024: np.ndarray,
    y_r61_insider: np.ndarray,
) -> dict[str, Any]:
    xt = flatten_windows(x_train)
    xv = flatten_windows(x_val)
    x61 = flatten_windows(x_r61)
    yt = np.asarray(y_train).astype(int).ravel()
    yv = np.asarray(y_val).astype(int).ravel()
    y024 = np.asarray(y_r61_editor024).astype(int).ravel()
    yins = np.asarray(y_r61_insider).astype(int).ravel()
    d = discriminant_direction(xt[yt == 1], xt[yt == 0])
    p_val_pos = project(xv[yv == 1], d)
    p_val_neg = project(xv[yv == 0], d)
    sd_val_neg = float(p_val_neg.std(ddof=0))
    r52_sep = class_separation(p_val_pos, p_val_neg, sd_val_neg)

    def _ratio(y: np.ndarray) -> dict[str, float]:
        pos = x61[y == 1]
        neg = x61[y == 0]
        if pos.size == 0 or neg.size == 0:
            return {
                "R61_SEPARATION": float("nan"),
                "INPUT_TRANSFER_RATIO": float("nan"),
            }
        sep = class_separation(project(pos, d), project(neg, d), sd_val_neg)
        return {
            "R61_SEPARATION": sep,
            "INPUT_TRANSFER_RATIO": input_transfer_ratio(sep, r52_sep),
        }

    a = _ratio(y024)
    b = _ratio(yins)
    g0e = bool(r52_sep > 0.0)
    g0f = bool(a["INPUT_TRANSFER_RATIO"] > G0F_EDITOR024_INPUT_TRANSFER_MIN)
    g0g = bool(b["INPUT_TRANSFER_RATIO"] > G0G_INSIDER_INPUT_TRANSFER_MIN)
    return {
        "discriminant_source": "R52_TRAIN",
        "flatten_dim": 260,
        "SEPARATION_EPSILON": SEPARATION_EPSILON,
        "R52_INPUT_SEPARATION": r52_sep,
        "r52_val_neg_proj_sd": sd_val_neg,
        "R61_EDITOR024_SEPARATION": a["R61_SEPARATION"],
        "R61_EDITOR024_INPUT_TRANSFER_RATIO": a["INPUT_TRANSFER_RATIO"],
        "R61_INSIDER_CONSISTENT_SEPARATION": b["R61_SEPARATION"],
        "R61_INSIDER_CONSISTENT_INPUT_TRANSFER_RATIO": b["INPUT_TRANSFER_RATIO"],
        "G0E": g0e,
        "G0F": g0f,
        "G0G": g0g,
        "EDITOR027_INPUT_SIGNAL_GATE": "PASS" if (g0e and g0f and g0g) else "FAIL",
        "no_classifier_fitting": True,
    }
