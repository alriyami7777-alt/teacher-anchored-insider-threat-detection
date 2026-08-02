"""Grouped temperature (primary) and Platt (secondary) calibration."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold

from .constants import (
    CLASS_IMPROVED_CONSISTENT,
    CLASS_IMPROVED_SEED_VAR,
    CLASS_NOT_IMPROVED,
    CLASS_SLOPE_INTERCEPT,
    CLASS_UNVERIFIABLE,
    LOGIT_CLIP,
    METHOD_PLATT,
    METHOD_TEMP,
    METHOD_UNCAL,
    MODEL_ODST,
    N_ECE_BINS,
    N_FOLDS,
    RANK_ATOL,
    RANK_SPEARMAN_MIN,
    SEEDS,
)
from .evidence import ModelPredictions, reconstruct_logit


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = pd.Series(a).rank(method="average").to_numpy()
    rb = pd.Series(b).rank(method="average").to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def assert_oof_ranking_ok(
    p_base: np.ndarray,
    p_cal: np.ndarray,
    y: np.ndarray,
    *,
    method: str,
    strict: bool = True,
) -> dict[str, float]:
    """Within-fold monotonicity is asserted during OOF.

    Global Spearman can drop when fold-specific T (especially T≪1 on compressed
    logits) stitches held-out folds. Primary materiality gate is PR-AUC delta.
    """
    m0 = float(average_precision_score(y, p_base))
    m1 = float(average_precision_score(y, p_cal))
    delta = m1 - m0
    spear = _spearman(p_base, p_cal)
    hard_atol = RANK_ATOL if strict else 0.05
    if abs(delta) > hard_atol:
        raise RuntimeError(
            f"PR-AUC changed materially under {method} OOF: {m0} -> {m1} "
            f"(delta={delta}, atol={hard_atol}, spearman={spear})"
        )
    if not np.isfinite(spear):
        raise RuntimeError(f"OOF {method} Spearman is non-finite")
    # Soft diagnostic only: warn via return payload when Spearman is low
    return {
        "pr_auc_base": m0,
        "pr_auc_cal": m1,
        "pr_auc_delta": delta,
        "spearman": spear,
        "ranking_check": "within_fold_exact_plus_pr_auc_atol",
        "spearman_below_guidance": bool(spear < RANK_SPEARMAN_MIN),
    }


def sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.asarray(z, dtype=np.float64)
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def _nll(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, dtype=np.float64), LOGIT_CLIP, 1.0 - LOGIT_CLIP)
    return float(log_loss(np.asarray(y).astype(int), p, labels=[0, 1]))


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    logits = np.asarray(logits, dtype=np.float64).ravel()
    y = np.asarray(y).astype(int).ravel()

    def objective(log_t: np.ndarray) -> float:
        t = float(np.exp(log_t[0]))
        return _nll(y, sigmoid(logits / t))

    res = minimize(objective, x0=np.array([0.0]), method="L-BFGS-B")
    t = float(np.exp(res.x[0]))
    if not np.isfinite(t) or t <= 0:
        raise RuntimeError(f"temperature fit failed: T={t}")
    return {
        "T": t,
        "log_T": float(res.x[0]),
        "success": bool(res.success),
        "message": str(res.message),
        "nll": float(res.fun),
    }


def fit_platt(logits: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    logits = np.asarray(logits, dtype=np.float64).ravel()
    y = np.asarray(y).astype(int).ravel()

    def objective(params: np.ndarray) -> float:
        a = float(np.exp(params[0]))
        b = float(params[1])
        return _nll(y, sigmoid(a * logits + b))

    res = minimize(objective, x0=np.array([0.0, 0.0]), method="L-BFGS-B")
    a = float(np.exp(res.x[0]))
    b = float(res.x[1])
    if not np.isfinite(a) or a <= 0:
        raise RuntimeError(f"platt fit failed: a={a}")
    return {
        "a": a,
        "b": b,
        "log_a": float(res.x[0]),
        "success": bool(res.success),
        "message": str(res.message),
        "nll": float(res.fun),
    }


def apply_temperature(logits: np.ndarray, t: float) -> np.ndarray:
    return sigmoid(np.asarray(logits, dtype=np.float64) / float(t))


def apply_platt(logits: np.ndarray, a: float, b: float) -> np.ndarray:
    return sigmoid(float(a) * np.asarray(logits, dtype=np.float64) + float(b))


def make_group_folds(
    users: np.ndarray, *, n_folds: int = N_FOLDS
) -> tuple[np.ndarray, pd.DataFrame]:
    """Deterministic GroupKFold: users sorted as strings for stable group labels."""
    users = np.asarray(users).astype(str)
    # Map each user to a sorted-rank label so fold assignment is deterministic.
    uniq = np.array(sorted(set(users.tolist())), dtype=str)
    user_to_code = {u: i for i, u in enumerate(uniq)}
    groups = np.array([user_to_code[u] for u in users], dtype=np.int64)
    gkf = GroupKFold(n_splits=n_folds)
    fold_id = np.full(len(users), -1, dtype=np.int32)
    fold_rows: list[dict[str, Any]] = []
    # Dummy X/y for splitter API
    x_dummy = np.zeros((len(users), 1))
    y_dummy = np.zeros(len(users), dtype=int)
    for fold, (_, test_idx) in enumerate(gkf.split(x_dummy, y_dummy, groups)):
        fold_id[test_idx] = fold
    for u in uniq:
        mask = users == u
        f = int(fold_id[np.flatnonzero(mask)[0]])
        fold_rows.append(
            {
                "user": u,
                "fold": f,
                "n_sequences": int(mask.sum()),
                "n_positives": 0,  # filled by caller if y provided
            }
        )
    return fold_id, pd.DataFrame(fold_rows)


def annotate_fold_positives(fold_df: pd.DataFrame, users: np.ndarray, y: np.ndarray) -> pd.DataFrame:
    users = np.asarray(users).astype(str)
    y = np.asarray(y).astype(int)
    rows = []
    for _, r in fold_df.iterrows():
        mask = users == r["user"]
        rows.append(
            {
                **r.to_dict(),
                "n_positives": int(y[mask].sum()),
            }
        )
    return pd.DataFrame(rows)


def oof_calibrate(
    logits: np.ndarray,
    y: np.ndarray,
    users: np.ndarray,
    *,
    method: str,
) -> tuple[np.ndarray, list[dict[str, Any]], pd.DataFrame]:
    logits = np.asarray(logits, dtype=np.float64).ravel()
    y = np.asarray(y).astype(int).ravel()
    users = np.asarray(users).astype(str)
    fold_id, fold_df = make_group_folds(users)
    fold_df = annotate_fold_positives(fold_df, users, y)
    p_oof = np.full(len(y), np.nan, dtype=np.float64)
    param_rows: list[dict[str, Any]] = []

    for fold in range(N_FOLDS):
        test_mask = fold_id == fold
        train_mask = ~test_mask
        if method == METHOD_TEMP:
            fit = fit_temperature(logits[train_mask], y[train_mask])
            p_hold = apply_temperature(logits[test_mask], fit["T"])
            # Within-fold ranking must be identical under T>0
            base_p = 1.0 / (1.0 + np.exp(-logits[test_mask]))
            if not np.array_equal(
                np.argsort(base_p, kind="mergesort"),
                np.argsort(p_hold, kind="mergesort"),
            ):
                raise RuntimeError(
                    f"within-fold ranking changed under temperature fold={fold}"
                )
            p_oof[test_mask] = p_hold
            param_rows.append(
                {
                    "method": METHOD_TEMP,
                    "fold": fold,
                    "T": fit["T"],
                    "a": np.nan,
                    "b": np.nan,
                    "success": fit["success"],
                    "message": fit["message"],
                    "n_train": int(train_mask.sum()),
                    "n_test": int(test_mask.sum()),
                }
            )
        elif method == METHOD_PLATT:
            fit = fit_platt(logits[train_mask], y[train_mask])
            p_hold = apply_platt(logits[test_mask], fit["a"], fit["b"])
            base_p = 1.0 / (1.0 + np.exp(-logits[test_mask]))
            if not np.array_equal(
                np.argsort(base_p, kind="mergesort"),
                np.argsort(p_hold, kind="mergesort"),
            ):
                raise RuntimeError(f"within-fold ranking changed under Platt fold={fold}")
            p_oof[test_mask] = p_hold
            param_rows.append(
                {
                    "method": METHOD_PLATT,
                    "fold": fold,
                    "T": np.nan,
                    "a": fit["a"],
                    "b": fit["b"],
                    "success": fit["success"],
                    "message": fit["message"],
                    "n_train": int(train_mask.sum()),
                    "n_test": int(test_mask.sum()),
                }
            )
        else:
            raise ValueError(method)

    if np.isnan(p_oof).any():
        raise RuntimeError("incomplete OOF calibrated probabilities")
    return p_oof, param_rows, fold_df


def fixed_ece(y: np.ndarray, p: np.ndarray, *, n_bins: int = N_ECE_BINS) -> float:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype=np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y)
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (p >= lo) & (p <= hi) if i == n_bins - 1 else (p >= lo) & (p < hi)
        if not mask.any():
            continue
        ece += (mask.sum() / n) * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return float(ece)


def adaptive_ece(y: np.ndarray, p: np.ndarray, *, n_bins: int = N_ECE_BINS) -> float:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype=np.float64)
    n = len(y)
    if n == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    # Equal-count quantile bins
    edges = np.linspace(0, n, n_bins + 1, dtype=int)
    ece = 0.0
    for i in range(n_bins):
        idx = order[edges[i] : edges[i + 1]]
        if len(idx) == 0:
            continue
        ece += (len(idx) / n) * abs(float(y[idx].mean()) - float(p[idx].mean()))
    return float(ece)


def maximum_calibration_error(y: np.ndarray, p: np.ndarray, *, n_bins: int = N_ECE_BINS) -> float:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype=np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    gaps = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (p >= lo) & (p <= hi) if i == n_bins - 1 else (p >= lo) & (p < hi)
        if not mask.any():
            continue
        gaps.append(abs(float(y[mask].mean()) - float(p[mask].mean())))
    return float(max(gaps)) if gaps else float("nan")


def calibration_slope_intercept(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    y = np.asarray(y).astype(int).ravel()
    p = np.clip(np.asarray(p, dtype=np.float64).ravel(), LOGIT_CLIP, 1.0 - LOGIT_CLIP)
    logit_p = reconstruct_logit(p)
    # Need both classes
    if y.min() == y.max():
        return float("nan"), float("nan")
    lr = LogisticRegression(solver="lbfgs", max_iter=2000, C=1e12)
    lr.fit(logit_p.reshape(-1, 1), y)
    return float(lr.coef_[0, 0]), float(lr.intercept_[0])


def reliability_bins(
    y: np.ndarray, p: np.ndarray, *, n_bins: int = N_ECE_BINS, scheme: str = "fixed"
) -> list[dict[str, Any]]:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype=np.float64)
    rows: list[dict[str, Any]] = []
    if scheme == "fixed":
        edges = np.linspace(0.0, 1.0, n_bins + 1)
        for i in range(n_bins):
            lo, hi = edges[i], edges[i + 1]
            mask = (p >= lo) & (p <= hi) if i == n_bins - 1 else (p >= lo) & (p < hi)
            n = int(mask.sum())
            rows.append(
                {
                    "scheme": "fixed",
                    "bin": i,
                    "lo": float(lo),
                    "hi": float(hi),
                    "n": n,
                    "mean_confidence": float(p[mask].mean()) if n else float("nan"),
                    "empirical_positive_rate": float(y[mask].mean()) if n else float("nan"),
                    "abs_gap": float(abs(y[mask].mean() - p[mask].mean())) if n else float("nan"),
                }
            )
    else:
        order = np.argsort(p, kind="mergesort")
        edges = np.linspace(0, len(y), n_bins + 1, dtype=int)
        for i in range(n_bins):
            idx = order[edges[i] : edges[i + 1]]
            n = int(len(idx))
            rows.append(
                {
                    "scheme": "adaptive",
                    "bin": i,
                    "lo": float(p[idx].min()) if n else float("nan"),
                    "hi": float(p[idx].max()) if n else float("nan"),
                    "n": n,
                    "mean_confidence": float(p[idx].mean()) if n else float("nan"),
                    "empirical_positive_rate": float(y[idx].mean()) if n else float("nan"),
                    "abs_gap": float(abs(y[idx].mean() - p[idx].mean())) if n else float("nan"),
                }
            )
    return rows


def calibration_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    y = np.asarray(y).astype(int)
    p = np.clip(np.asarray(p, dtype=np.float64), LOGIT_CLIP, 1.0 - LOGIT_CLIP)
    slope, intercept = calibration_slope_intercept(y, p)
    return {
        "pr_auc": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "logloss": float(log_loss(y, p, labels=[0, 1])),
        "ece_fixed": fixed_ece(y, p),
        "ece_adaptive": adaptive_ece(y, p),
        "mce": maximum_calibration_error(y, p),
        "slope": slope,
        "intercept": intercept,
        "mean_predicted": float(p.mean()),
        "prevalence": float(y.mean()),
    }


def run_calibration_for_bundle(
    bundle: ModelPredictions,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, np.ndarray], pd.DataFrame]:
    """Return metrics, parameters, reliability bins, calibrated probs, and fold table."""
    y = bundle.y_true
    users = bundle.user
    logits = bundle.logit
    metric_rows: list[dict[str, Any]] = []
    param_rows: list[dict[str, Any]] = []
    bin_rows: list[dict[str, Any]] = []
    probs: dict[str, np.ndarray] = {METHOD_UNCAL: bundle.probability.copy()}

    # Uncalibrated
    m0 = calibration_metrics(y, bundle.probability)
    metric_rows.append({"model": bundle.model, "seed": bundle.seed, "method": METHOD_UNCAL, **m0})
    for scheme in ("fixed", "adaptive"):
        for row in reliability_bins(y, bundle.probability, scheme=scheme):
            bin_rows.append(
                {"model": bundle.model, "seed": bundle.seed, "method": METHOD_UNCAL, **row}
            )

    # Temperature OOF
    p_temp, temp_params, fold_df = oof_calibrate(logits, y, users, method=METHOD_TEMP)
    probs[METHOD_TEMP] = p_temp
    rank_t = assert_oof_ranking_ok(bundle.probability, p_temp, y, method=METHOD_TEMP, strict=True)
    m_t = calibration_metrics(y, p_temp)
    m_t["rank_spearman_vs_uncal"] = rank_t["spearman"]
    m_t["pr_auc_delta_vs_uncal"] = rank_t["pr_auc_delta"]
    metric_rows.append({"model": bundle.model, "seed": bundle.seed, "method": METHOD_TEMP, **m_t})
    for pr in temp_params:
        param_rows.append({"model": bundle.model, "seed": bundle.seed, **pr})
    for scheme in ("fixed", "adaptive"):
        for row in reliability_bins(y, p_temp, scheme=scheme):
            bin_rows.append(
                {"model": bundle.model, "seed": bundle.seed, "method": METHOD_TEMP, **row}
            )

    # Platt OOF (secondary)
    p_platt, platt_params, _ = oof_calibrate(logits, y, users, method=METHOD_PLATT)
    probs[METHOD_PLATT] = p_platt
    rank_p = assert_oof_ranking_ok(
        bundle.probability, p_platt, y, method=METHOD_PLATT, strict=False
    )
    m_p = calibration_metrics(y, p_platt)
    m_p["rank_spearman_vs_uncal"] = rank_p["spearman"]
    m_p["pr_auc_delta_vs_uncal"] = rank_p["pr_auc_delta"]
    metric_rows.append({"model": bundle.model, "seed": bundle.seed, "method": METHOD_PLATT, **m_p})
    for pr in platt_params:
        param_rows.append({"model": bundle.model, "seed": bundle.seed, **pr})
    for scheme in ("fixed", "adaptive"):
        for row in reliability_bins(y, p_platt, scheme=scheme):
            bin_rows.append(
                {"model": bundle.model, "seed": bundle.seed, "method": METHOD_PLATT, **row}
            )

    # Attach fold table once (temperature folds identical to platt)
    fold_out = fold_df.copy()
    fold_out.insert(0, "model", bundle.model)
    fold_out.insert(1, "seed", bundle.seed)

    return (
        pd.DataFrame(metric_rows),
        pd.DataFrame(param_rows),
        pd.DataFrame(bin_rows),
        probs,
        fold_out,
    )


def classify_odst_temperature(metrics: pd.DataFrame) -> str:
    """Classify temperature scaling for ODST using seed-averaged primary metrics."""
    odst = metrics[metrics["model"] == MODEL_ODST]
    if odst.empty:
        return CLASS_UNVERIFIABLE

    seed_flags = []
    brier_deltas = []
    ll_deltas = []
    ece_deltas = []
    slope_uncal = []
    slope_temp = []
    intercept_temp = []
    pr_ok_all = True

    for seed in SEEDS:
        u = odst[(odst.seed == seed) & (odst.method == METHOD_UNCAL)]
        t = odst[(odst.seed == seed) & (odst.method == METHOD_TEMP)]
        if len(u) != 1 or len(t) != 1:
            return CLASS_UNVERIFIABLE
        u, t = u.iloc[0], t.iloc[0]
        if abs(float(t.pr_auc) - float(u.pr_auc)) > RANK_ATOL:
            pr_ok_all = False
        db = float(u.brier) - float(t.brier)  # >0 means improved
        dl = float(u.logloss) - float(t.logloss)
        de = float(u.ece_fixed) - float(t.ece_fixed)
        brier_deltas.append(db)
        ll_deltas.append(dl)
        ece_deltas.append(de)
        slope_uncal.append(float(u.slope))
        slope_temp.append(float(t.slope))
        intercept_temp.append(float(t.intercept))
        # severe deterioration: any metric worsens by >0.02 absolute
        severe = (db < -0.02) or (dl < -0.02) or (de < -0.02)
        seed_flags.append(
            {
                "improved": db > 0 and dl > 0 and de > 0,
                "severe": severe,
            }
        )

    if not pr_ok_all:
        return CLASS_UNVERIFIABLE

    avg_brier = float(np.mean(brier_deltas))
    avg_ll = float(np.mean(ll_deltas))
    avg_ece = float(np.mean(ece_deltas))
    any_severe = any(f["severe"] for f in seed_flags)
    all_improved = all(f["improved"] for f in seed_flags)
    avg_improved = avg_brier > 0 and avg_ll > 0 and avg_ece > 0 and not any_severe

    # Slope closer to 1?
    slope_err_u = float(np.mean([abs(s - 1.0) for s in slope_uncal]))
    slope_err_t = float(np.mean([abs(s - 1.0) for s in slope_temp]))
    slope_improved = slope_err_t < slope_err_u - 1e-6
    intercept_remains = float(np.mean([abs(i) for i in intercept_temp])) > 0.1

    if avg_improved and all_improved:
        return CLASS_IMPROVED_CONSISTENT
    if avg_improved and not all_improved:
        return CLASS_IMPROVED_SEED_VAR
    if slope_improved and intercept_remains:
        return CLASS_SLOPE_INTERCEPT
    if avg_improved:
        return CLASS_IMPROVED_SEED_VAR
    return CLASS_NOT_IMPROVED
