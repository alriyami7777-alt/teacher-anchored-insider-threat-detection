"""Frozen-threshold alert burden, episodes, budgets, user aggregation, incidents."""

from __future__ import annotations


import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from .constants import (
    BUDGETS,
    INCIDENT_CANDIDATE_PATHS,
    MODEL_AL,
    MODEL_ODST,
    MODEL_XGB,
    SEEDS,
)
from .evidence import ModelPredictions
from .safety import OpenedFilesRegister


def _to_dates(arr: np.ndarray) -> pd.Series:
    return pd.to_datetime(pd.Series(np.asarray(arr).astype(str)), errors="coerce")


def frozen_threshold_burden(bundle: ModelPredictions) -> dict[str, Any]:
    y = np.asarray(bundle.y_true).astype(int)
    p = np.asarray(bundle.probability, dtype=np.float64)
    users = np.asarray(bundle.user).astype(str)
    thr = float(bundle.threshold)
    alert = p >= thr

    # User labels
    user_has_mal = {}
    for u in np.unique(users):
        user_has_mal[u] = bool(y[users == u].max() == 1)
    benign_users = {u for u, m in user_has_mal.items() if not m}
    insider_users = {u for u, m in user_has_mal.items() if m}

    alerted_users = set(users[alert].tolist())
    detected_insiders = {
        u
        for u in insider_users
        if bool(np.logical_and(users == u, np.logical_and(alert, y == 1)).any())
    }
    false_alert_users = alerted_users & benign_users

    tp_alerts = int(np.logical_and(alert, y == 1).sum())
    fp_alerts = int(np.logical_and(alert, y == 0).sum())
    n_alerts = int(alert.sum())

    alerts_per_user = (
        pd.Series(users[alert]).value_counts() if n_alerts else pd.Series(dtype=int)
    )
    per_detected = (
        [int(alerts_per_user.get(u, 0)) for u in detected_insiders] if detected_insiders else []
    )
    fp_per_false_user = []
    for u in false_alert_users:
        fp_per_false_user.append(int(np.logical_and(users == u, np.logical_and(alert, y == 0)).sum()))

    return {
        "model": bundle.model,
        "seed": bundle.seed,
        "threshold": thr,
        "n_sequence_alerts": n_alerts,
        "n_tp_sequence_alerts": tp_alerts,
        "n_fp_sequence_alerts": fp_alerts,
        "n_unique_alerted_users": len(alerted_users),
        "n_detected_insider_users": len(detected_insiders),
        "n_false_alert_users": len(false_alert_users),
        "n_benign_users": len(benign_users),
        "pct_benign_users_alerted": (
            100.0 * len(false_alert_users) / len(benign_users) if benign_users else float("nan")
        ),
        "alerts_per_detected_insider_mean": float(np.mean(per_detected)) if per_detected else float("nan"),
        "fp_windows_per_false_alert_user_mean": (
            float(np.mean(fp_per_false_user)) if fp_per_false_user else float("nan")
        ),
        "alerts_per_alerted_user_median": float(alerts_per_user.median()) if len(alerts_per_user) else float("nan"),
        "alerts_per_alerted_user_mean": float(alerts_per_user.mean()) if len(alerts_per_user) else float("nan"),
        "alerts_per_alerted_user_p90": float(alerts_per_user.quantile(0.9)) if len(alerts_per_user) else float("nan"),
        "alerts_per_alerted_user_max": float(alerts_per_user.max()) if len(alerts_per_user) else float("nan"),
    }


def alerted_user_summary(bundle: ModelPredictions) -> pd.DataFrame:
    y = np.asarray(bundle.y_true).astype(int)
    p = np.asarray(bundle.probability, dtype=np.float64)
    users = np.asarray(bundle.user).astype(str)
    thr = float(bundle.threshold)
    alert = p >= thr
    rows = []
    for u in sorted(set(users.tolist())):
        mask = users == u
        a_mask = np.logical_and(mask, alert)
        n_alerts = int(a_mask.sum())
        if n_alerts == 0:
            continue
        has_mal = bool(y[mask].max() == 1)
        tp = int(np.logical_and(a_mask, y == 1).sum())
        fp = int(np.logical_and(a_mask, y == 0).sum())
        rows.append(
            {
                "model": bundle.model,
                "seed": bundle.seed,
                "user": u,
                "n_alerts": n_alerts,
                "n_tp_alerts": tp,
                "n_fp_alerts": fp,
                "user_has_malicious": has_mal,
                "is_detected_insider": has_mal and tp > 0,
                "is_false_alert_user": (not has_mal) and fp > 0,
                "max_prob": float(p[mask].max()),
            }
        )
    return pd.DataFrame(rows)


def consolidate_episodes(
    end_dates: np.ndarray,
    y_alert: np.ndarray,
    *,
    gap_days: float = 1.0,
) -> list[dict[str, Any]]:
    """Consolidate alerts for a single user.

    Same episode when consecutive alerted end dates differ by <= gap_days.
    New episode when gap > gap_days.
    """
    if len(end_dates) == 0:
        return []
    dates = pd.to_datetime(pd.Series(np.asarray(end_dates).astype(str)), errors="coerce")
    y = np.asarray(y_alert).astype(int)
    order = np.argsort(dates.values.astype("datetime64[ns]"), kind="mergesort")
    dates = dates.iloc[order].reset_index(drop=True)
    y = y[order]

    episodes: list[dict[str, Any]] = []
    cur_dates = [dates.iloc[0]]
    cur_y = [int(y[0])]
    for i in range(1, len(dates)):
        delta = (dates.iloc[i] - cur_dates[-1]).days
        if pd.isna(delta) or delta > gap_days:
            episodes.append(_episode_record(cur_dates, cur_y))
            cur_dates = [dates.iloc[i]]
            cur_y = [int(y[i])]
        else:
            cur_dates.append(dates.iloc[i])
            cur_y.append(int(y[i]))
    episodes.append(_episode_record(cur_dates, cur_y))
    return episodes


def _episode_record(dates: list, y: list[int]) -> dict[str, Any]:
    mal = any(v == 1 for v in y)
    return {
        "n_windows": len(dates),
        "start_end_date": str(dates[0].date()) if hasattr(dates[0], "date") else str(dates[0]),
        "last_end_date": str(dates[-1].date()) if hasattr(dates[-1], "date") else str(dates[-1]),
        "malicious_associated": mal,
        "false_episode": not mal,
    }


def episode_tables(bundle: ModelPredictions) -> tuple[pd.DataFrame, pd.DataFrame]:
    y = np.asarray(bundle.y_true).astype(int)
    p = np.asarray(bundle.probability, dtype=np.float64)
    users = np.asarray(bundle.user).astype(str)
    end_dates = bundle.end_date
    thr = float(bundle.threshold)
    alert = p >= thr

    records = []
    for u in sorted(set(users[alert].tolist())):
        mask = np.logical_and(users == u, alert)
        eps = consolidate_episodes(end_dates[mask], y[mask])
        for i, ep in enumerate(eps):
            records.append(
                {
                    "model": bundle.model,
                    "seed": bundle.seed,
                    "user": u,
                    "episode_id": i,
                    **ep,
                }
            )
    rec_df = pd.DataFrame(records)
    if rec_df.empty:
        summary = pd.DataFrame(
            [
                {
                    "model": bundle.model,
                    "seed": bundle.seed,
                    "n_alert_episodes": 0,
                    "n_malicious_associated_episodes": 0,
                    "n_false_episodes": 0,
                    "n_users_represented": 0,
                    "mean_windows_per_episode": float("nan"),
                    "median_windows_per_episode": float("nan"),
                    "p90_windows_per_episode": float("nan"),
                    "n_sequence_alerts": int(alert.sum()),
                    "reduction_sequence_to_episodes": float("nan"),
                    "false_episodes_per_detected_insider": float("nan"),
                }
            ]
        )
        return summary, rec_df

    n_seq = int(alert.sum())
    n_ep = len(rec_df)
    detected = set(
        rec_df.loc[rec_df.malicious_associated, "user"].astype(str).tolist()
    )
    n_false = int(rec_df.false_episode.sum())
    summary = pd.DataFrame(
        [
            {
                "model": bundle.model,
                "seed": bundle.seed,
                "n_alert_episodes": n_ep,
                "n_malicious_associated_episodes": int(rec_df.malicious_associated.sum()),
                "n_false_episodes": n_false,
                "n_users_represented": int(rec_df.user.nunique()),
                "mean_windows_per_episode": float(rec_df.n_windows.mean()),
                "median_windows_per_episode": float(rec_df.n_windows.median()),
                "p90_windows_per_episode": float(rec_df.n_windows.quantile(0.9)),
                "n_sequence_alerts": n_seq,
                "reduction_sequence_to_episodes": float(n_seq - n_ep),
                "false_episodes_per_detected_insider": (
                    float(n_false / len(detected)) if detected else float("nan")
                ),
            }
        ]
    )
    return summary, rec_df


def fixed_budget_results(bundle: ModelPredictions) -> pd.DataFrame:
    y = np.asarray(bundle.y_true).astype(int)
    p = np.asarray(bundle.probability, dtype=np.float64)
    users = np.asarray(bundle.user).astype(str)
    n = len(y)
    order = np.argsort(-p, kind="mergesort")
    user_has_mal = {u: bool(y[users == u].max() == 1) for u in np.unique(users)}
    rows = []
    for budget in BUDGETS:
        k = max(1, int(round(budget * n)))
        idx = order[:k]
        y_sel = y[idx]
        u_sel = users[idx]
        mal_recall = float(y_sel.sum() / max(int(y.sum()), 1))
        precision = float(y_sel.mean()) if k else float("nan")
        alerted = set(u_sel.tolist())
        detected = {u for u in alerted if user_has_mal.get(u, False)}
        # require at least one selected malicious window for that user
        detected = {
            u
            for u in detected
            if bool(np.logical_and(u_sel == u, y_sel == 1).any())
        }
        false_users = {u for u in alerted if not user_has_mal.get(u, False)}
        rows.append(
            {
                "model": bundle.model,
                "seed": bundle.seed,
                "budget_fraction": budget,
                "n_selected": k,
                "malicious_sequence_recall": mal_recall,
                "precision": precision,
                "n_detected_insider_users": len(detected),
                "n_benign_users_alerted": len(false_users),
                "false_alert_users_per_detected_insider": (
                    float(len(false_users) / len(detected)) if detected else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows)


def user_level_aggregation(bundle: ModelPredictions) -> pd.DataFrame:
    y = np.asarray(bundle.y_true).astype(int)
    p = np.asarray(bundle.probability, dtype=np.float64)
    users = np.asarray(bundle.user).astype(str)
    rows = []
    uniq = sorted(set(users.tolist()))
    user_y = []
    max_scores = []
    mean_top3 = []
    for u in uniq:
        mask = users == u
        pu = p[mask]
        yu = int(y[mask].max())
        user_y.append(yu)
        max_scores.append(float(pu.max()))
        top = np.sort(pu)[-3:]
        mean_top3.append(float(top.mean()))

    user_y_arr = np.asarray(user_y, dtype=int)
    for rule, scores in (("max", max_scores), ("mean_top3", mean_top3)):
        scores_arr = np.asarray(scores, dtype=np.float64)
        pr = float(average_precision_score(user_y_arr, scores_arr)) if user_y_arr.sum() else float("nan")
        order = np.argsort(-scores_arr, kind="mergesort")
        n_users = len(uniq)
        for budget in BUDGETS:
            k = max(1, int(round(budget * n_users)))
            sel = order[:k]
            detected = int(user_y_arr[sel].sum())
            benign_alerted = int((user_y_arr[sel] == 0).sum())
            rows.append(
                {
                    "model": bundle.model,
                    "seed": bundle.seed,
                    "aggregation": rule,
                    "user_pr_auc": pr,
                    "budget_fraction": budget,
                    "n_selected_users": k,
                    "n_detected_insider_users": detected,
                    "n_benign_users_alerted": benign_alerted,
                }
            )
    return pd.DataFrame(rows)


def find_incident_metadata(repo_root: Path, opened: OpenedFilesRegister) -> Path | None:
    # Prefer junction evidence, then recorded_results, then external audit repo.
    candidates = list(INCIDENT_CANDIDATE_PATHS)
    external_value = os.environ.get("CERT_R52_INCIDENT_METADATA")
    if external_value:
        candidates.append(Path(external_value).expanduser())
    for rel in candidates:
        p = rel if rel.is_absolute() else repo_root / rel
        if p.exists():
            return opened.record(p, "incident_positive_sequence_metadata")
    return None


def incident_level_analysis(
    bundles: dict[tuple[str, int], ModelPredictions],
    repo_root: Path,
    opened: OpenedFilesRegister,
) -> pd.DataFrame:
    path = find_incident_metadata(repo_root, opened)
    if path is None:
        return pd.DataFrame(
            [
                {
                    "status": "unavailable",
                    "reason": "low_and_slow_positive_sequence_metadata.csv not found",
                }
            ]
        )

    meta = pd.read_csv(path)
    if "sequence_id" not in meta.columns:
        return pd.DataFrame(
            [{"status": "unavailable", "reason": "incident metadata missing sequence_id"}]
        )
    meta = meta.copy()
    meta["sequence_id"] = meta["sequence_id"].astype(str)
    if "incident_id" not in meta.columns:
        return pd.DataFrame(
            [{"status": "unavailable", "reason": "incident metadata missing incident_id"}]
        )

    rows = []
    for (model, seed), bundle in bundles.items():
        if model not in (MODEL_ODST, MODEL_AL, MODEL_XGB):
            continue
        df = pd.DataFrame(
            {
                "sequence_id": np.asarray(bundle.sequence_id).astype(str),
                "user": np.asarray(bundle.user).astype(str),
                "y_true": np.asarray(bundle.y_true).astype(int),
                "probability": np.asarray(bundle.probability, dtype=np.float64),
                "end_date": np.asarray(bundle.end_date).astype(str),
            }
        )
        df["alert"] = df["probability"] >= float(bundle.threshold)
        pos = meta[meta["sequence_id"].isin(df["sequence_id"])].copy()
        if pos.empty:
            continue
        merged = pos.merge(df, on="sequence_id", how="left", suffixes=("_meta", ""))
        # Prefer tensor join fields when duplicated
        if "user" not in merged.columns and "user_meta" in merged.columns:
            merged["user"] = merged["user_meta"]

        for incident_id, g in merged.groupby("incident_id"):
            g = g.sort_values("end_date")
            n_seq = len(g)
            alerts = g[g["alert"] == True]  # noqa: E712
            detected = len(alerts) > 0
            # first malicious-labelled window among this incident's sequences
            mal = g[g["y_true"] == 1]
            first_mal_end = mal["end_date"].iloc[0] if len(mal) else None
            first_alert_end = alerts["end_date"].iloc[0] if detected else None
            rel = None
            if detected and first_mal_end is not None:
                # sequence-relative: index of first alert vs first malicious window in timeline
                ends = list(g["end_date"].astype(str))
                try:
                    i_mal = ends.index(str(first_mal_end))
                    i_alert = ends.index(str(first_alert_end))
                    rel = int(i_alert - i_mal)
                except ValueError:
                    rel = None
            rows.append(
                {
                    "status": "ok",
                    "model": model,
                    "seed": seed,
                    "incident_id": incident_id,
                    "n_sequences_represented": n_seq,
                    "detected": detected,
                    "n_alerts": int(len(alerts)),
                    "first_alert_relative_to_first_malicious_window": rel,
                    "timing_definition": "sequence_relative_not_real_world_early_warning",
                    "n_users": int(g["user"].nunique()) if "user" in g.columns else None,
                }
            )
    if not rows:
        return pd.DataFrame(
            [{"status": "unavailable", "reason": "no joinable incident sequences"}]
        )
    return pd.DataFrame(rows)
