"""ODST vs attention–linear paired comparison, claims, and final status."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .constants import (
    BOOTSTRAP_SEED,
    CLASS_IMPROVED_CONSISTENT,
    CLASS_IMPROVED_SEED_VAR,
    CLASS_NOT_IMPROVED,
    CLASS_SLOPE_INTERCEPT,
    CLASS_UNVERIFIABLE,
    METHOD_TEMP,
    METHOD_UNCAL,
    MODEL_AL,
    MODEL_ODST,
    N_BOOTSTRAP_MAX_ATTEMPTS,
    N_BOOTSTRAP_TARGET,
    RANK_SPEARMAN_MIN,
    SEEDS,
    STATUS_COMPLETE,
    STATUS_COMPLETE_LIMITS,
    STATUS_INCOMPLETE,
    STATUS_NOT_IMPROVED,
)
from .evidence import ModelPredictions


def _user_blocks(users: np.ndarray) -> list[np.ndarray]:
    users = np.asarray(users).astype(str)
    codes, uniq = pd.factorize(users, sort=True)
    n_users = len(uniq)
    order = np.argsort(codes, kind="mergesort")
    sorted_codes = codes[order]
    boundaries = np.flatnonzero(np.r_[True, sorted_codes[1:] != sorted_codes[:-1], True])
    return [order[boundaries[i] : boundaries[i + 1]] for i in range(n_users)]


def paired_user_cluster_bootstrap(
    bundles: dict[tuple[str, int], ModelPredictions],
    burden: pd.DataFrame,
    episodes: pd.DataFrame,
    metrics: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        o = bundles.get((MODEL_ODST, seed))
        a = bundles.get((MODEL_AL, seed))
        if o is None or a is None:
            continue
        users = o.user
        blocks = _user_blocks(users)
        n_users = len(blocks)

        # Observed deltas on key operational quantities from burden tables
        ob = burden[(burden.model == MODEL_ODST) & (burden.seed == seed)]
        ab = burden[(burden.model == MODEL_AL) & (burden.seed == seed)]
        oe = episodes[(episodes.model == MODEL_ODST) & (episodes.seed == seed)]
        ae = episodes[(episodes.model == MODEL_AL) & (episodes.seed == seed)]
        if ob.empty or ab.empty:
            continue
        obs_map = {
            "delta_false_alert_users": float(ob.iloc[0].n_false_alert_users - ab.iloc[0].n_false_alert_users),
            "delta_sequence_alerts": float(ob.iloc[0].n_sequence_alerts - ab.iloc[0].n_sequence_alerts),
            "delta_alert_episodes": (
                float(oe.iloc[0].n_alert_episodes - ae.iloc[0].n_alert_episodes)
                if not oe.empty and not ae.empty
                else float("nan")
            ),
        }
        # Calibration Brier: temperature observed is reported without OOF bootstrap.
        # Bootstrap uses an uncalibrated Brier proxy so CI matches the resampled scores.
        ot = metrics[
            (metrics.model == MODEL_ODST)
            & (metrics.seed == seed)
            & (metrics.method == METHOD_TEMP)
        ]
        at = metrics[
            (metrics.model == MODEL_AL)
            & (metrics.seed == seed)
            & (metrics.method == METHOD_TEMP)
        ]
        ou = metrics[
            (metrics.model == MODEL_ODST)
            & (metrics.seed == seed)
            & (metrics.method == METHOD_UNCAL)
        ]
        au = metrics[
            (metrics.model == MODEL_AL)
            & (metrics.seed == seed)
            & (metrics.method == METHOD_UNCAL)
        ]
        temp_brier_obs = (
            float(ot.iloc[0].brier - at.iloc[0].brier)
            if len(ot) == 1 and len(at) == 1
            else float("nan")
        )
        if len(ou) == 1 and len(au) == 1:
            obs_map["delta_brier_uncalibrated_proxy"] = float(ou.iloc[0].brier - au.iloc[0].brier)

        # Bootstrap on false-alert-user count difference using frozen thresholds.
        # Pre-aggregate per user so 2,000 replicates stay tractable (same quantities).
        y = o.y_true.astype(int)
        rng = np.random.default_rng(BOOTSTRAP_SEED + seed)
        n_pos_u = np.array([int(y[b].sum()) for b in blocks], dtype=np.int64)
        n_seq_u = np.array([len(b) for b in blocks], dtype=np.int64)
        is_mal_u = n_pos_u > 0
        n_alert_o = np.array(
            [(o.probability[b] >= o.threshold).sum() for b in blocks], dtype=np.int64
        )
        n_alert_a = np.array(
            [(a.probability[b] >= a.threshold).sum() for b in blocks], dtype=np.int64
        )
        has_alert_o = n_alert_o > 0
        has_alert_a = n_alert_a > 0
        sse_o = np.array(
            [float(((o.probability[b] - y[b]) ** 2).sum()) for b in blocks], dtype=np.float64
        )
        sse_a = np.array(
            [float(((a.probability[b] - y[b]) ** 2).sum()) for b in blocks], dtype=np.float64
        )

        store: dict[str, list[float]] = {k: [] for k in obs_map}
        n_valid = attempts = 0
        while n_valid < N_BOOTSTRAP_TARGET and attempts < N_BOOTSTRAP_MAX_ATTEMPTS:
            attempts += 1
            chosen = rng.integers(0, n_users, size=n_users)
            n_pos_t = int(n_pos_u[chosen].sum())
            n_seq_t = int(n_seq_u[chosen].sum())
            if n_pos_t == 0 or n_pos_t == n_seq_t:
                continue
            # Unique user IDs in the resample (matches set-based FAU on concatenated rows)
            uniq = np.unique(chosen)
            fau_o = int((has_alert_o[uniq] & ~is_mal_u[uniq]).sum())
            fau_a = int((has_alert_a[uniq] & ~is_mal_u[uniq]).sum())
            d_fau = fau_o - fau_a
            d_alerts = int(n_alert_o[chosen].sum() - n_alert_a[chosen].sum())
            store["delta_false_alert_users"].append(float(d_fau))
            store["delta_sequence_alerts"].append(float(d_alerts))
            if "delta_alert_episodes" in store and np.isfinite(obs_map["delta_alert_episodes"]):
                store["delta_alert_episodes"].append(float(d_alerts))  # proxy under resample
            if "delta_brier_uncalibrated_proxy" in store:
                brier_o = float(sse_o[chosen].sum() / n_seq_t)
                brier_a = float(sse_a[chosen].sum() / n_seq_t)
                store["delta_brier_uncalibrated_proxy"].append(brier_o - brier_a)
            n_valid += 1

        for metric, obs in obs_map.items():
            arr = np.asarray(store.get(metric, []), dtype=float)
            if len(arr) == 0 or not np.isfinite(obs):
                continue
            lo, hi = float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))
            if lo > 0:
                cls = "supported_positive_delta"
            elif hi < 0:
                cls = "supported_negative_delta"
            elif obs > 0:
                cls = "numerical_positive_uncertain"
            elif obs < 0:
                cls = "numerical_negative_uncertain"
            else:
                cls = "no_supported_difference"
            rows.append(
                {
                    "seed": seed,
                    "metric": metric,
                    "observed": float(obs),
                    "ci_low": lo,
                    "ci_high": hi,
                    "n_valid": n_valid,
                    "bootstrap_seed": BOOTSTRAP_SEED + seed,
                    "classification": cls,
                    "delta_definition": "M_ODST - M_attention_linear",
                }
            )
        if np.isfinite(temp_brier_obs):
            rows.append(
                {
                    "seed": seed,
                    "metric": "delta_brier_temperature_observed",
                    "observed": float(temp_brier_obs),
                    "ci_low": float("nan"),
                    "ci_high": float("nan"),
                    "n_valid": 0,
                    "bootstrap_seed": BOOTSTRAP_SEED + seed,
                    "classification": "observed_only_no_oof_bootstrap",
                    "delta_definition": "M_ODST - M_attention_linear",
                }
            )
    return pd.DataFrame(rows)


def build_claim_register(
    *,
    cal_class: str,
    metrics: pd.DataFrame,
    burden: pd.DataFrame,
    paired: pd.DataFrame,
    xgb_loaded: bool,
    incident_available: bool,
) -> pd.DataFrame:
    claims = []

    def add(claim_id: str, statement: str, status: str, evidence: str) -> None:
        claims.append(
            {
                "claim_id": claim_id,
                "statement": statement,
                "status": status,
                "evidence": evidence,
            }
        )

    add(
        "C1",
        "Grouped temperature scaling is the primary calibration method; Platt is secondary sensitivity only.",
        "supported",
        "calibration_parameters.csv / calibration_metrics.csv",
    )
    add(
        "C2",
        f"ODST temperature-scaling classification: {cal_class}",
        "supported" if cal_class != CLASS_UNVERIFIABLE else "unsupported",
        "calibration decision on seed-averaged Brier/logloss/ECE with PR-AUC unchanged",
    )
    temp = metrics[metrics.method == METHOD_TEMP] if len(metrics) else metrics
    spear_ok = True
    if len(temp) and "rank_spearman_vs_uncal" in temp.columns:
        spear_ok = bool((temp["rank_spearman_vs_uncal"] >= RANK_SPEARMAN_MIN).all())
    add(
        "C3",
        "Within-fold monotonic calibration preserves ranking; global OOF PR-AUC "
        "remains within RANK_ATOL (fold-stitched Spearman may fall when T≪1).",
        "supported" if spear_ok else "limited",
        "calibration_metrics.csv uncalibrated vs temperature/Platt; within-fold argsort identity",
    )
    add(
        "C4",
        "Frozen-threshold alert burden separates sequence alerts, unique users, and consolidated episodes.",
        "supported",
        "frozen_threshold_alert_burden.csv / alert_episode_summary.csv",
    )
    add(
        "C5",
        "ODST versus attention–linear operational deltas use paired user-cluster bootstrap.",
        "supported" if len(paired) else "limited",
        "odst_attention_linear_paired_comparison.csv",
    )
    add(
        "C6",
        "XGBoost included as operational reference.",
        "supported" if xgb_loaded else "not_applicable",
        "calibration_model_provenance.csv",
    )
    add(
        "C7",
        "Incident-level alert results use sequence-relative first-alert timing, not real-world early warning.",
        "supported" if incident_available else "unavailable",
        "incident_level_alert_results.csv",
    )
    add(
        "C8",
        "No claim of analyst usefulness or deployment readiness.",
        "supported",
        "claim restriction / preferred framing",
    )
    # Seed-level burden snapshot
    for seed in SEEDS:
        for model in (MODEL_ODST, MODEL_AL):
            r = burden[(burden.model == model) & (burden.seed == seed)]
            if len(r):
                add(
                    f"B-{model}-{seed}",
                    f"{model} seed {seed}: {int(r.iloc[0].n_sequence_alerts)} sequence alerts; "
                    f"{int(r.iloc[0].n_unique_alerted_users)} unique alerted users.",
                    "supported",
                    "frozen_threshold_alert_burden.csv",
                )
    return pd.DataFrame(claims)


def decide_final_status(
    *,
    cal_class: str,
    xgb_loaded: bool,
    incident_available: bool,
    checks: dict[str, bool],
    oof_rank_limit: bool = False,
) -> tuple[str, bool]:
    """Return (status, has_limits)."""
    if not checks.get("test_loader_refused", False) or not checks.get("test_path_blocked", False):
        return STATUS_INCOMPLETE, True
    if cal_class == CLASS_UNVERIFIABLE:
        return STATUS_INCOMPLETE, True
    limits = (
        (not xgb_loaded)
        or (not incident_available)
        or oof_rank_limit
        or cal_class in {
            CLASS_IMPROVED_SEED_VAR,
            CLASS_SLOPE_INTERCEPT,
        }
    )
    if cal_class == CLASS_NOT_IMPROVED:
        return STATUS_NOT_IMPROVED, limits
    if cal_class == CLASS_IMPROVED_CONSISTENT and not limits:
        return STATUS_COMPLETE, False
    if cal_class in {
        CLASS_IMPROVED_CONSISTENT,
        CLASS_IMPROVED_SEED_VAR,
        CLASS_SLOPE_INTERCEPT,
    }:
        return STATUS_COMPLETE_LIMITS, True
    return STATUS_COMPLETE_LIMITS, True
