"""Analysis protocol. Must not run before SCORE_COMPLETE validates.

Fixture outputs are engineering self-tests, not scientific results.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_fscore_support

from .safety import HarnessProtocolError, SEEDS
from .scoring import load_sequence_metadata, require_score_complete


VIEWS = ("completed_window", "endpoint_past_only", "deoverlap_offset0")


def metrics_at_frozen_threshold(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    y = np.asarray(y).astype(int)
    p = np.asarray(scores, dtype=np.float64)
    if y.shape != p.shape:
        raise HarnessProtocolError("y/score length mismatch")
    if len(np.unique(y)) < 2:
        pr_auc = float("nan")
    else:
        pr_auc = float(average_precision_score(y, p))
    pred = (p >= float(threshold)).astype(int)
    prec, rec, f1, _ = precision_recall_fscore_support(
        y, pred, average="binary", zero_division=0
    )
    fp = int(np.sum((pred == 1) & (y == 0)))
    fn = int(np.sum((pred == 0) & (y == 1)))
    return {
        "PR_AUC": pr_auc,
        "precision": float(prec),
        "recall": float(rec),
        "F1": float(f1),
        "FP": fp,
        "FN": fn,
        "threshold": float(threshold),
        "n": int(y.shape[0]),
        "n_pos": int(y.sum()),
        "observations_correlated": True,
        "naive_independent_window_ci": "NOT_ATTACHED",
    }


def seed_mean_sd(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    return {"mean": float(arr.mean()), "sample_sd": float(arr.std(ddof=1)) if len(arr) > 1 else float("nan")}


def analyse_views(
    *,
    out_dir,
    identifiers: list[Any],
    expected_n: int,
) -> dict[str, Any]:
    man = require_score_complete(out_dir, expected_n=expected_n)
    y_completed = np.asarray([int(r.completed_window_label) for r in identifiers], dtype=int)
    y_endpoint = np.asarray([int(r.endpoint_label) for r in identifiers], dtype=int)
    deov = np.asarray([int(r.deoverlap_offset0_flag) for r in identifiers], dtype=int)
    if np.any(y_endpoint < 0) or np.any(deov < 0):
        raise HarnessProtocolError("Endpoint/de-overlap labels unavailable on this fixture")
    mask_deov = deov == 1
    by_family: dict[str, Any] = {}
    for rec in man["scores"]:
        family, seed = rec["family"], int(rec["seed"])
        scores = np.load(rec["path"])
        thr = float(rec["threshold"])
        views = {
            "completed_window": {
                **metrics_at_frozen_threshold(y_completed, scores, thr),
                "stride": 1,
                "label_rule": "any constituent day event-level answer-match",
                "use": "primary whole-cohort external ranking (correlated windows)",
            },
            "endpoint_past_only": {
                **metrics_at_frozen_threshold(y_endpoint, scores, thr),
                "interpretation": "endpoint-defined past-only evaluation",
                "never": ["real-time", "streaming", "intra-day"],
            },
            "deoverlap_offset0": {
                **metrics_at_frozen_threshold(y_completed[mask_deov], scores[mask_deov], thr),
                "n_retained": int(mask_deov.sum()),
                "offset": 0,
                "offset_sweep": False,
                "role": "primary dependence sensitivity",
            },
        }
        by_family.setdefault(family, {})[seed] = views
    summary: dict[str, Any] = {}
    for family, seed_map in by_family.items():
        fam_sum: dict[str, Any] = {}
        for view in VIEWS:
            prauc = [seed_map[s][view]["PR_AUC"] for s in SEEDS]
            f1 = [seed_map[s][view]["F1"] for s in SEEDS]
            fam_sum[view] = {
                "PR_AUC_mean_sd": seed_mean_sd(prauc),
                "F1_mean_sd": seed_mean_sd(f1),
                "primary_is_seedwise_then_mean_sd": True,
                "seed_averaged_predictions": False,
            }
    summary[family] = fam_sum
    metadata = None
    try:
        metadata = load_sequence_metadata(out_dir)
    except HarnessProtocolError:
        metadata = None
    return {
        "kind": "engineering_protocol_selftest",
        "not_scientific_results": True,
        "by_family_seed": by_family,
        "family_mean_sd": summary,
        "score_complete_validated": True,
        "sequence_metadata": metadata,
        "official_incident_id_distinct_from_answer_scenario_ids": True,
    }
