"""EDITOR-025 read-only r6.1 failure autopsy campaign. No training. No EDITOR-024 rewrite."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from editor006b_harness.safety import EXPECTED_TRAIN_NPZ_SHA256, EXPECTED_TRAIN_X_RAW_SHA256, EXPECTED_VAL_X_RAW_SHA256
from editor017_robustness.constants import MODEL_SPECS
from editor024_r61.bootstrap import pr_auc as frozen_pr_auc

from .constants import (
    BINARY_FEATURES,
    COUNT_FEATURES,
    EDITOR007D_REVIEW_REL,
    EDITOR024_OUTPUT_REL,
    EDITOR024_RESULTS_COMMIT,
    EDITOR024_REVIEW_REL,
    FALSE_POSITIVE_COHORT_N,
    FEATURE_ORDER,
    R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025,
    R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT,
    R61_COMPLETED_N,
    R61_COMPLETED_POSITIVES,
    R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET,
    R61_MEAN_PR_AUC,
    R61_PREVALENCE,
    R61_ROLE_FROM_EDITOR025,
    REFERENCE_NEGATIVE_COHORT_N,
    REPRESENTATION_NEGATIVE_N,
    REVIEW_REL,
    R52_TRAIN_NPZ,
    R52_VAL_NPZ,
    SEEDS,
    SHA256_MANIFEST_NAME,
    STUDENT_MODELS,
    SUPPORT_CLIP_VIEW_NAME,
    TASK_ID,
    frozen_thresholds,
)
from .feature_shift import inverse_scale, pearson_corr, shift_rows
from .inference import _log, device, score_index
from .io_util import write_csv, write_json, write_npy, write_npz, write_text
from .labels import (
    attribution_counts,
    diagnostic_view_available,
    discover_answer_files,
    enrich_crosswalk,
    inventory_row,
    load_r61_insiders,
    official_insider_map,
    parse_all_answers,
    pr_auc,
    ranking_excess,
    scenario_insider_consistent_day_keys,
    semantic_mismatch_from_crosswalk,
    timestamp_to_iso,
    window_labels_from_day_keys,
)
from .representation import attention_stats, per_model_separation, sample_from_split
from .ruling import apply_rulings, count_activity_shift_dominant
from .safety import (
    EDITOR024_REVIEW_ROOT,
    OUTPUT_ROOT,
    REPO_ROOT,
    REVIEW_ROOT,
    Editor025Blocked,
    require_protocol_frozen,
    sha256_file,
    sha256_text,
    utc_now,
)
from .sampling import false_positive_cohort, reference_negative_cohort
from .scores import distribution_block, ranking_profile, user_positive_windows
from .support_clip import apply_r52_support_clip, clip_view_identity, r52_train_support_bounds
from .training_gate import assert_no_training


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()


def _bundle_dir() -> Path:
    return REPO_ROOT / EDITOR024_OUTPUT_REL / "bundle"


def _pred_dir() -> Path:
    return REPO_ROOT / EDITOR024_OUTPUT_REL / "raw_predictions"


def snapshot_paths(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            out[rel] = sha256_file(path)
    return out


def load_bundle() -> dict[str, Any]:
    b = _bundle_dir()
    return {
        "scaled_dense_daily": np.load(b / "scaled_dense_daily.npy", mmap_mode="r"),
        "y": np.load(b / "completed_window_labels.npy", mmap_mode="r"),
        "deov": np.load(b / "deoverlap_offset0_mask.npy", mmap_mode="r"),
        "user_idx": np.load(b / "window_user_index.npy", mmap_mode="r"),
        "start_idx": np.load(b / "window_start_index.npy", mmap_mode="r"),
        "user_ids_sorted": np.load(b / "user_ids_sorted.npy", allow_pickle=True),
        "user_ids_windows": np.load(b / "user_ids_windows.npy", allow_pickle=True),
        "sequence_ids": np.load(b / "sequence_ids.npy", allow_pickle=True),
        "calendar_dates": np.load(b / "calendar_dates.npy", allow_pickle=True),
    }


def load_logits(alias: str, seed: int) -> np.ndarray:
    path = _pred_dir() / f"{alias}_seed{seed}_COMPLETED_WINDOW.npz"
    with np.load(path) as z:
        return np.asarray(z["logit"], dtype=np.float64)


def load_probs(alias: str, seed: int) -> np.ndarray:
    path = _pred_dir() / f"{alias}_seed{seed}_COMPLETED_WINDOW.npz"
    with np.load(path) as z:
        return np.asarray(z["probability"], dtype=np.float64)


def load_scaler() -> dict[str, Any]:
    from editor024_r61.scaler import load_r52_train_scaler

    return load_r52_train_scaler()


def load_r52_train_scaled() -> tuple[np.ndarray, str, str]:
    path = R52_TRAIN_NPZ
    sha = sha256_file(path)
    if sha != EXPECTED_TRAIN_NPZ_SHA256:
        raise Editor025Blocked(f"r5.2 TRAIN npz hash mismatch: {sha}")
    with np.load(path, allow_pickle=True, mmap_mode="r") as z:
        x = np.asarray(z["X"], dtype=np.float32)
    from editor006b_harness.input_bundle import raw_array_sha

    x_sha = raw_array_sha(x)
    if x_sha != EXPECTED_TRAIN_X_RAW_SHA256:
        raise Editor025Blocked("r5.2 TRAIN X hash mismatch")
    return x.reshape(-1, 13), sha, x_sha


def load_r52_val() -> dict[str, Any]:
    path = R52_VAL_NPZ
    with np.load(path, allow_pickle=True, mmap_mode="r") as z:
        x = np.asarray(z["X"], dtype=np.float32)
        y = np.asarray(z["y"]).astype(int)
        seq = np.asarray(z["sequence_id"]).astype(str)
    from editor006b_harness.input_bundle import raw_array_sha

    if raw_array_sha(x) != EXPECTED_VAL_X_RAW_SHA256:
        raise Editor025Blocked("r5.2 VAL X hash mismatch")
    return {"X": x, "y": y, "sequence_ids": seq, "path": str(path)}


def mean_seed_probs(alias: str) -> np.ndarray:
    acc = None
    for seed in SEEDS:
        p = load_probs(alias, seed)
        acc = p if acc is None else acc + p
    return acc / float(len(SEEDS))


def phase_a(bundle: dict[str, Any]) -> dict[str, Any]:
    _log("Phase A — label autopsy")
    discovered = discover_answer_files()
    inventory = []
    chosen: dict[str, Path | None] = {}
    for name in (
        "r6.1-1.csv",
        "r6.1-2.csv",
        "r6.1-3.csv",
        "r6.1-4.csv",
        "r6.1-5.csv",
        "insiders.csv",
    ):
        paths = discovered.get(name) or []
        path = paths[0] if paths else None
        chosen[name] = path
        rec = inventory_row(name, path)
        rec["n_locations_found"] = len(paths)
        rec["all_paths"] = [str(p) for p in paths]
        inventory.append(rec)
    write_json(REVIEW_ROOT / "EDITOR025_LABEL_FILE_INVENTORY.json", {"files": inventory, "written_at": utc_now()})

    insiders_path = chosen.get("insiders.csv")
    insider_rows = load_r61_insiders(insiders_path) if insiders_path else []
    insider_map = official_insider_map(insider_rows)
    records = parse_all_answers({k: v for k, v in chosen.items() if v is not None})
    crosswalk = enrich_crosswalk(records, insider_map)
    write_csv(REVIEW_ROOT / "EDITOR025_LABEL_EVENT_CROSSWALK.csv", crosswalk)
    attr = attribution_counts(crosswalk)

    y = np.asarray(bundle["y"]).astype(int).ravel()
    users = np.asarray(bundle["user_ids_windows"]).astype(str)
    pos_users = sorted({u for u in np.unique(users[y == 1]).tolist()})
    official_users = sorted(set(insider_map.values()))
    user_to_scenarios: dict[str, set[str]] = defaultdict(set)
    user_event_n: dict[str, int] = defaultdict(int)
    user_days: dict[str, set[str]] = defaultdict(set)
    for rec in crosswalk:
        u = rec["answer_file_user"]
        if not u:
            continue
        user_to_scenarios[u].add(rec["scenario"])
        user_event_n[u] += 1
        iso = timestamp_to_iso(rec["answer_file_timestamp"])
        if iso:
            user_days[u].add(iso)
    pos_index = user_positive_windows(y, users)
    audit_rows = []
    for u in sorted(set(pos_users) | set(official_users)):
        sl = pos_index.get(u, np.zeros(0, dtype=np.int64))
        official = u in official_users
        scenarios = sorted(user_to_scenarios.get(u, set()))
        if not scenarios:
            for sc, ins in insider_map.items():
                if ins == u:
                    scenarios.append(sc)
        audit_rows.append(
            {
                "positive_labelled_user": u,
                "official_insider": "YES" if official else "NO",
                "scenarios": "|".join(scenarios) if scenarios else "",
                "n_matched_answer_events": int(user_event_n.get(u, 0)),
                "n_positive_days_from_answer_timestamps": int(len(user_days.get(u, set()))),
                "n_positive_windows_editor024": int(len(sl)),
                "in_editor024_positive_set": "YES" if u in pos_users else "NO",
            }
        )
    write_csv(REVIEW_ROOT / "EDITOR025_POSITIVE_USER_AUDIT.csv", audit_rows)

    s4 = chosen.get("r6.1-4.csv")
    s4_available = bool(s4 is not None and Path(s4).is_file())
    n_with_answers = sum(1 for i in range(1, 6) if chosen.get(f"r6.1-{i}.csv"))
    diag_ok = diagnostic_view_available(crosswalk, insider_map)
    semantic = semantic_mismatch_from_crosswalk(
        attribution=attr,
        n_positive_bundle_users=len(pos_users),
        n_official_insiders=len(official_users),
    )
    integrity_payload = {
        "R61_SCENARIO4_ANSWER_AVAILABLE": "YES" if s4_available else "NO",
        "R61_GROUND_TRUTH_COVERAGE_COMPLETE": "YES" if s4_available and n_with_answers >= 5 else "NO",
        "R61_OFFICIAL_INSIDERS": official_users,
        "n_official_insiders": len(official_users),
        "R61_POSITIVE_LABEL_USERS_UNDER_EDITOR024_RULE": pos_users,
        "n_positive_label_users": len(pos_users),
        "insider_map": insider_map,
        "attribution_by_scenario": attr,
        "semantic_mismatch_established_from_authoritative_fields": semantic,
        "SCENARIO_INSIDER_CONSISTENT_AVAILABLE": bool(diag_ok),
        "n_scenarios_with_answers": n_with_answers,
        "n_official_scenarios": 5,
        "written_at": utc_now(),
    }

    diagnostic_pr = None
    diagnostic_prev = None
    y_diag = None
    if diag_ok:
        keys = scenario_insider_consistent_day_keys(crosswalk)
        y_diag = window_labels_from_day_keys(
            user_ids_windows=users,
            start_index=np.asarray(bundle["start_idx"]),
            calendar_dates=np.asarray(bundle["calendar_dates"]).astype(str),
            positive_days=keys,
        )
        write_npy(OUTPUT_ROOT / "scenario_insider_consistent_window_labels.npy", y_diag)
        diagnostic_prev = float(y_diag.mean())
        diagnostic_pr = {}
        for alias in STUDENT_MODELS:
            seed_vals = []
            for seed in SEEDS:
                logits = load_logits(alias, seed)
                seed_vals.append(pr_auc(y_diag, logits))
            diagnostic_pr[alias] = float(np.mean(seed_vals))
        integrity_payload["diagnostic_mean_pr_auc"] = diagnostic_pr
        integrity_payload["diagnostic_prevalence"] = diagnostic_prev
        integrity_payload["diagnostic_ranking_excess"] = {
            m: ranking_excess(diagnostic_pr[m], diagnostic_prev) for m in STUDENT_MODELS
        }
    else:
        integrity_payload["SCENARIO_INSIDER_CONSISTENT"] = "UNRESOLVED"
    write_json(REVIEW_ROOT / "EDITOR025_LABEL_INTEGRITY.json", integrity_payload)
    return {
        "inventory": inventory,
        "insider_map": insider_map,
        "official_users": official_users,
        "pos_users": pos_users,
        "attr": attr,
        "semantic_mismatch": semantic,
        "s4_available": s4_available,
        "n_with_answers": n_with_answers,
        "diag_ok": diag_ok,
        "diagnostic_pr": diagnostic_pr,
        "diagnostic_prevalence": diagnostic_prev,
        "y_diag": y_diag,
        "crosswalk": crosswalk,
        "audit_rows": audit_rows,
        "chosen": {k: (str(v) if v else None) for k, v in chosen.items()},
    }


def phase_b_c(bundle: dict[str, Any], scaler: dict[str, Any]) -> dict[str, Any]:
    _log("Phase B/C — feature shift")
    train_scaled, train_sha, train_x_sha = load_r52_train_scaled()
    r61_scaled = np.reshape(np.asarray(bundle["scaled_dense_daily"]), (-1, 13))
    mean = scaler["mean"]
    scale = scaler["scale"]
    train_raw = inverse_scale(train_scaled, mean, scale)
    r61_raw = inverse_scale(r61_scaled, mean, scale)
    active_train = train_raw[:, FEATURE_ORDER.index("is_active_day")] > 0.5
    active_r61 = r61_raw[:, FEATURE_ORDER.index("is_active_day")] > 0.5
    rows_all = shift_rows(
        r52_train_scaled=train_scaled,
        r52_all_scaled=None,
        r61_scaled=r61_scaled,
        r52_train_raw=train_raw,
        r61_raw=r61_raw,
    )
    rows_active = shift_rows(
        r52_train_scaled=train_scaled[active_train],
        r52_all_scaled=None,
        r61_scaled=r61_scaled[active_r61],
        r52_train_raw=train_raw[active_train],
        r61_raw=r61_raw[active_r61],
    )
    for rec in rows_all:
        rec["population"] = "all_user_days"
    for rec in rows_active:
        rec["population"] = "active_user_days_only"
    write_csv(REVIEW_ROOT / "EDITOR025_R61_R52_FEATURE_SHIFT.csv", rows_all + rows_active)
    ranked = [r["feature"] for r in sorted(rows_all, key=lambda r: int(r["shift_severity_rank"]))]
    summary = {
        "bins_fitted_from": "R52_TRAIN",
        "oos_bounds_fitted_from": "R52_TRAIN",
        "r52_train_npz_sha256": train_sha,
        "r52_train_x_sha256": train_x_sha,
        "ranked_features_all_user_days": ranked,
        "top_5_shifted_features": ranked[:5],
        "psi": {r["feature"]: r["PSI_R61_VS_R52"] for r in rows_all},
        "mean_shift_z": {r["feature"]: r["MEAN_SHIFT_Z"] for r in rows_all},
        "oos": {r["feature"]: r["out_of_support_rate"] for r in rows_all},
        "binary_rate_abs_diff": {
            r["feature"]: r.get("binary_rate_abs_diff", 0.0) for r in rows_all if r["feature"] in BINARY_FEATURES
        },
        "count_activity_levels_primary_shift": count_activity_shift_dominant(
            ranked_features=ranked, count_features=COUNT_FEATURES, binary_features=BINARY_FEATURES
        ),
    }
    write_json(REVIEW_ROOT / "EDITOR025_FEATURE_SHIFT_SUMMARY.json", summary)

    ed7 = json.loads((REPO_ROOT / EDITOR007D_REVIEW_REL / "EDITOR007D_FEATURE_SHIFT.json").read_text(encoding="utf-8"))
    by_feat = {row["feature"]: row for row in ed7["rows"]}
    r61_vec = [abs(float(r["MEAN_SHIFT_Z"])) for r in rows_all]
    r62_vec = [float(by_feat[f]["abs_r62_mean_minus_r52_train_mean"]) for f in FEATURE_ORDER]
    r51_vec = [float(by_feat[f]["abs_r51_mean_minus_r52_train_mean"]) for f in FEATURE_ORDER]
    corr_r62 = pearson_corr(r61_vec, r62_vec)
    corr_r51 = pearson_corr(r61_vec, r51_vec)
    resemblance = "r6 generation" if (np.isnan(corr_r51) or abs(corr_r62) >= abs(corr_r51)) else "r5 generation"
    cross = {
        "R61_R62_SHIFT_VECTOR_CORRELATION": corr_r62,
        "R61_R51_SHIFT_VECTOR_CORRELATION": corr_r51,
        "descriptive_resemblance": resemblance,
        "causal_statement": "NONE",
        "r51_rerun": "NO",
        "r62_rerun": "NO",
        "r61_shift_vector_abs_mean_shift_z": dict(zip(FEATURE_ORDER, r61_vec)),
        "r62_frozen_abs_mean_shift": dict(zip(FEATURE_ORDER, r62_vec)),
        "r51_frozen_abs_mean_shift": dict(zip(FEATURE_ORDER, r51_vec)),
        "common_top_shift_features": {
            "r61_top5": ranked[:5],
            "r62_frozen_rank": ed7.get("rank_abs_r62_vs_r52_train"),
            "r51_frozen_rank": ed7.get("rank_abs_r51_vs_r52_train"),
        },
        "source": "review/editor007d_cross_version_synthesis/EDITOR007D_FEATURE_SHIFT.json",
    }
    write_json(REVIEW_ROOT / "EDITOR025_CROSS_RELEASE_SHIFT_COMPARISON.json", cross)
    bounds = r52_train_support_bounds(train_raw)
    return {
        "rows_all": rows_all,
        "summary": summary,
        "cross": cross,
        "train_raw": train_raw,
        "bounds": bounds,
        "train_scaled": train_scaled,
    }


def phase_d_e_f(bundle: dict[str, Any], label_pack: dict[str, Any]) -> dict[str, Any]:
    _log("Phase D/E/F — scores, ranking, scenario profile")
    y = np.asarray(bundle["y"]).astype(int).ravel()
    users = np.asarray(bundle["user_ids_windows"]).astype(str)
    seq = np.asarray(bundle["sequence_ids"]).astype(str)
    thr = frozen_thresholds()
    dist_rows = []
    ranking: dict[str, Any] = {}
    val = load_r52_val()
    for alias in STUDENT_MODELS:
        ranking[alias] = {}
        for seed in SEEDS:
            logits = load_logits(alias, seed)
            pos = logits[y == 1]
            neg = logits[y == 0]
            t = float(thr[alias][str(seed)])
            dpos = distribution_block(pos, t)
            dneg = distribution_block(neg, t)
            dist_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "split": "r61_positive",
                    "logit_mean": dpos["logit"]["mean"],
                    "logit_std": dpos["logit"]["std"],
                    **{f"logit_{k}": v for k, v in dpos["logit"].items() if k not in {"n", "mean", "std"}},
                    "prob_mean": dpos["probability"]["mean"],
                    "fraction_gt_frozen_r52_threshold": dpos["fraction_gt_frozen_r52_threshold"],
                    "fraction_gt_0.5": dpos["fraction_gt_0.5"],
                    "fraction_lt_0.01": dpos["fraction_lt_0.01"],
                    "fraction_gt_0.99": dpos["fraction_gt_0.99"],
                    "NEGATIVE_THRESHOLD_EXCEEDANCE": "",
                }
            )
            dist_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "split": "r61_negative",
                    "logit_mean": dneg["logit"]["mean"],
                    "logit_std": dneg["logit"]["std"],
                    **{f"logit_{k}": v for k, v in dneg["logit"].items() if k not in {"n", "mean", "std"}},
                    "prob_mean": dneg["probability"]["mean"],
                    "fraction_gt_frozen_r52_threshold": dneg["fraction_gt_frozen_r52_threshold"],
                    "fraction_gt_0.5": dneg["fraction_gt_0.5"],
                    "fraction_lt_0.01": dneg["fraction_lt_0.01"],
                    "fraction_gt_0.99": dneg["fraction_gt_0.99"],
                    "NEGATIVE_THRESHOLD_EXCEEDANCE": dneg["fraction_gt_frozen_r52_threshold"],
                }
            )
            val_path = MODEL_SPECS[alias]["val_logits"][seed]
            if Path(val_path).is_file():
                vlogits = np.asarray(np.load(val_path), dtype=np.float64).ravel()
                vy = val["y"].ravel()
                if len(vlogits) == len(vy):
                    dvn = distribution_block(vlogits[vy == 0], t)
                    dvp = distribution_block(vlogits[vy == 1], t)
                    dist_rows.append(
                        {
                            "model": alias,
                            "seed": seed,
                            "split": "r52_validation_negative",
                            "logit_mean": dvn["logit"]["mean"],
                            "logit_std": dvn["logit"]["std"],
                            "prob_mean": dvn["probability"]["mean"],
                            "fraction_gt_frozen_r52_threshold": dvn["fraction_gt_frozen_r52_threshold"],
                            "NEGATIVE_THRESHOLD_EXCEEDANCE": dvn["fraction_gt_frozen_r52_threshold"],
                        }
                    )
                    dist_rows.append(
                        {
                            "model": alias,
                            "seed": seed,
                            "split": "r52_validation_positive",
                            "logit_mean": dvp["logit"]["mean"],
                            "logit_std": dvp["logit"]["std"],
                            "prob_mean": dvp["probability"]["mean"],
                            "fraction_gt_frozen_r52_threshold": dvp["fraction_gt_frozen_r52_threshold"],
                        }
                    )
            prof = ranking_profile(y, logits)
            ranking[alias][str(seed)] = {
                k: v for k, v in prof.items() if k != "positive_percentiles"
            }
    write_csv(REVIEW_ROOT / "EDITOR025_SCORE_DISTRIBUTIONS.csv", dist_rows)
    ta2_mean_p = mean_seed_probs("TA2")
    ta2_rank = ranking_profile(y, ta2_mean_p)
    ranking["TA2_mean_probability"] = {k: v for k, v in ta2_rank.items() if k != "positive_percentiles"}
    write_json(REVIEW_ROOT / "EDITOR025_RANKING_FAILURE.json", ranking)

    pos_index = user_positive_windows(y, users)
    pct = ta2_rank.get("positive_percentiles")
    pos_mask = y == 1
    pos_pct_all = np.zeros(len(y), dtype=np.float64)
    if pct is not None:
        pos_pct_all[pos_mask] = pct
    scenario_rows = []
    for row in label_pack["audit_rows"]:
        u = row["positive_labelled_user"]
        sl = pos_index.get(u)
        if sl is None or len(sl) == 0:
            scenario_rows.append(
                {
                    **row,
                    "TA2_positive_window_score_median": "NOT_EVALUABLE",
                    "TA2_positive_window_global_percentile_median": "NOT_EVALUABLE",
                    "highest_ranked_positive_window": "NOT_EVALUABLE",
                    "lowest_ranked_positive_window": "NOT_EVALUABLE",
                    "evaluable": "NO",
                    "reason": "no authoritative positive windows" if row["n_positive_windows_editor024"] == 0 else "no windows",
                }
            )
            continue
        scores = ta2_mean_p[sl]
        pcts = pos_pct_all[sl]
        seqs = seq[sl]
        hi = int(np.argmax(scores))
        lo = int(np.argmin(scores))
        scenario_rows.append(
            {
                **row,
                "TA2_positive_window_score_median": float(np.median(scores)),
                "TA2_positive_window_global_percentile_median": float(np.median(pcts)),
                "highest_ranked_positive_window": str(seqs[hi]),
                "lowest_ranked_positive_window": str(seqs[lo]),
                "evaluable": "YES",
            }
        )
    write_csv(REVIEW_ROOT / "EDITOR025_SCENARIO_USER_PROFILE.csv", scenario_rows)
    ta2_neg_ex = []
    for seed in SEEDS:
        t = float(thr["TA2"][str(seed)])
        p = load_probs("TA2", seed)
        ta2_neg_ex.append(float(np.mean(p[y == 0] > t)))
    return {
        "ranking": ranking,
        "ta2_mean_p": ta2_mean_p,
        "ta2_neg_exceedance_mean": float(np.mean(ta2_neg_ex)),
        "ta2_pos_median_pct": float(ta2_rank["median_positive_percentile"]),
        "ta2_top_n_capture": float(ta2_rank["capture"]["top_1N"]),
        "y": y,
        "seq": seq,
    }


def phase_g(bundle: dict[str, Any], score_pack: dict[str, Any]) -> dict[str, Any]:
    _log("Phase G — false-positive phenotype")
    y = score_pack["y"]
    seq = score_pack["seq"]
    p = score_pack["ta2_mean_p"]
    fp = false_positive_cohort(y, p, FALSE_POSITIVE_COHORT_N)
    ref = reference_negative_cohort(seq, y, REFERENCE_NEGATIVE_COHORT_N)
    dense = np.asarray(bundle["scaled_dense_daily"])
    ui = np.asarray(bundle["user_idx"])
    si = np.asarray(bundle["start_idx"])
    from editor024_r61.cert_parse import gather_windows

    def _agg(idx: np.ndarray) -> dict[str, dict[str, float]]:
        w = gather_windows(dense, ui[idx], si[idx]).astype(np.float64)
        out: dict[str, dict[str, float]] = {}
        for j, name in enumerate(FEATURE_ORDER):
            col = w[:, :, j]
            out[name] = {
                "window_mean_mean": float(col.mean(axis=1).mean()),
                "window_mean_median": float(np.median(col.mean(axis=1))),
                "window_max_mean": float(col.max(axis=1).mean()),
                "window_max_median": float(np.median(col.max(axis=1))),
                "window_final_mean": float(col[:, -1].mean()),
                "window_final_median": float(np.median(col[:, -1])),
            }
        return out

    fp_stats = _agg(fp)
    ref_stats = _agg(ref)
    rows = []
    for name in FEATURE_ORDER:
        rec = {"feature": name}
        for stat in (
            "window_mean_mean",
            "window_mean_median",
            "window_max_mean",
            "window_max_median",
            "window_final_mean",
            "window_final_median",
        ):
            rec[f"fp_{stat}"] = fp_stats[name][stat]
            rec[f"ref_{stat}"] = ref_stats[name][stat]
            rec[f"effect_{stat}"] = fp_stats[name][stat] - ref_stats[name][stat]
        rows.append(rec)
    write_csv(REVIEW_ROOT / "EDITOR025_FALSE_POSITIVE_PHENOTYPE.csv", rows)
    write_npy(OUTPUT_ROOT / "false_positive_cohort_indices.npy", fp)
    write_npy(OUTPUT_ROOT / "reference_negative_cohort_indices.npy", ref)
    return {"fp": fp, "ref": ref, "rows": rows}


def phase_h(bundle: dict[str, Any]) -> dict[str, Any]:
    _log("Phase H — representation vs head")
    y61 = np.asarray(bundle["y"]).astype(int).ravel()
    seq61 = np.asarray(bundle["sequence_ids"]).astype(str)
    idx61 = sample_from_split(seq61, y61, REPRESENTATION_NEGATIVE_N)
    write_npy(OUTPUT_ROOT / "r61_representation_sample_indices.npy", idx61)
    write_json(
        OUTPUT_ROOT / "r61_representation_sample.json",
        {
            "n": int(len(idx61)),
            "n_pos": int(y61[idx61].sum()),
            "n_neg": int((y61[idx61] == 0).sum()),
            "rule": "all positives PLUS 20000 negatives by ascending SHA256(sequence_id)",
            "score_dependent": False,
            "index_sha256": sha256_text(",".join(str(int(i)) for i in idx61)),
        },
    )
    val = load_r52_val()
    idx52 = sample_from_split(val["sequence_ids"], val["y"], REPRESENTATION_NEGATIVE_N)
    write_npy(OUTPUT_ROOT / "r52_representation_sample_indices.npy", idx52)
    x52 = val["X"][idx52]
    y52_s = val["y"][idx52]
    y61_s = y61[idx61]
    ui = np.asarray(bundle["user_idx"])
    si = np.asarray(bundle["start_idx"])
    dense = bundle["scaled_dense_daily"]
    dev = device()
    sep_rows = []
    attn = {}
    transfer = {}
    for alias in STUDENT_MODELS:
        attn[alias] = {}
        for seed in SEEDS:
            _log(f"H forward {alias} seed{seed}")
            r52 = score_index(alias=alias, seed=seed, windows=x52, collect_representation=True, dev=dev)
            r61 = score_index(
                alias=alias,
                seed=seed,
                dense=dense,
                user_idx=ui[idx61],
                start_idx=si[idx61],
                collect_representation=True,
                dev=dev,
            )
            stats = per_model_separation(z_r52=r52["z"], y_r52=y52_s, z_r61=r61["z"], y_r61=y61_s)
            stats.update({"model": alias, "seed": seed})
            sep_rows.append(stats)
            a52 = attention_stats(r52["attention_weights"])
            a61 = attention_stats(r61["attention_weights"])
            attn[alias][str(seed)] = {"r52": a52, "r61": a61, "delta": {k: a61[k] - a52[k] for k in a52}}
        transfer[alias] = float(np.nanmean([r["REPRESENTATION_TRANSFER_RATIO"] for r in sep_rows if r["model"] == alias]))
    write_csv(REVIEW_ROOT / "EDITOR025_REPRESENTATION_SEPARATION.csv", sep_rows)
    write_json(
        REVIEW_ROOT / "EDITOR025_REPRESENTATION_SHIFT.json",
        {"transfer_ratios_mean_over_seeds": transfer, "rows": sep_rows, "head_swapping": "NOT_PERFORMED"},
    )
    write_json(REVIEW_ROOT / "EDITOR025_ATTENTION_SHIFT.json", attn)
    return {"transfer": transfer, "sep_rows": sep_rows, "attn": attn}


def phase_i(bundle: dict[str, Any], shift_pack: dict[str, Any], scaler: dict[str, Any]) -> dict[str, Any]:
    _log("Phase I — R52_SUPPORT_CLIP")
    identity = clip_view_identity()
    dense = np.asarray(bundle["scaled_dense_daily"])
    clipped = apply_r52_support_clip(
        r61_scaled=dense,
        mean=scaler["mean"],
        scale=scaler["scale"],
        bounds=shift_pack["bounds"],
    )
    write_npy(OUTPUT_ROOT / "r61_scaled_dense_daily_r52_support_clip.npy", clipped)
    y = np.asarray(bundle["y"]).astype(int).ravel()
    ui = np.asarray(bundle["user_idx"])
    si = np.asarray(bundle["start_idx"])
    dev = device()
    results: dict[str, Any] = {"identity": identity, "models": {}}
    for alias in STUDENT_MODELS:
        seed_pr = {}
        for seed in SEEDS:
            _log(f"I clip-forward {alias} seed{seed}")
            scored = score_index(alias=alias, seed=seed, dense=clipped, user_idx=ui, start_idx=si, dev=dev)
            seed_pr[str(seed)] = frozen_pr_auc(y, scored["probs"])
            write_npz(
                OUTPUT_ROOT / "raw_predictions" / f"{alias}_seed{seed}_{SUPPORT_CLIP_VIEW_NAME}.npz",
                logit=scored["logits"],
                probability=scored["probs"],
            )
        mean_pr = float(np.mean(list(seed_pr.values())))
        orig = float(R61_MEAN_PR_AUC[alias])
        results["models"][alias] = {
            "seed_pr_auc": seed_pr,
            "mean_pr_auc": mean_pr,
            "original_r61_pr_auc": orig,
            "delta": mean_pr - orig,
            "ranking_excess": mean_pr - R61_PREVALENCE,
        }
    write_json(REVIEW_ROOT / "EDITOR025_SUPPORT_CLIP_RESULTS.json", results)
    return results


def write_result_freeze(payload: dict[str, Any]) -> None:
    r = payload["rulings"]
    text = f"""# EDITOR-025 result freeze

EDITOR024_RESULTS_COMMIT = {EDITOR024_RESULTS_COMMIT}
EDITOR025_PROTOCOL_FREEZE_COMMIT = {payload["protocol_freeze_commit"]}
EDITOR025_RESULTS_COMMIT = PENDING_BY_DESIGN

R61_ROLE_FROM_EDITOR025 = {R61_ROLE_FROM_EDITOR025}
EDITOR024_RESULT_REMAINS_IMMUTABLE = YES
R61_CAN_SERVE_AS_FUTURE_UNTOUCHED_TARGET = NO

R61_LABEL_INTEGRITY = {r["R61_LABEL_INTEGRITY"]}
REPRESENTATION_NONPORTABILITY = {r["REPRESENTATION_NONPORTABILITY"]}
HEAD_SPECIFIC_FAILURE = {r["HEAD_SPECIFIC_FAILURE"]}
R61_COVARIATE_SHIFT = {r["R61_COVARIATE_SHIFT"]}
EDITOR025_PRIMARY_ROOT_CAUSE = {r["EDITOR025_PRIMARY_ROOT_CAUSE"]}
EDITOR025_RECOMMENDED_NEXT_REMEDY = {r["EDITOR025_RECOMMENDED_NEXT_REMEDY"]}

TRAINING_EXECUTED = NO
MODEL_PARAMETERS_UPDATED = NO
R51_RERUN = NO
R62_RERUN = NO
"""
    write_text(REVIEW_ROOT / "EDITOR025_RESULT_FREEZE.md", text)


def terminal_block(payload: dict[str, Any], *, results_commit: str) -> str:
    r = payload["rulings"]
    lab = payload["label"]
    sh = payload["shift"]["summary"]
    sc = payload["scores"]
    clip = payload["clip"]["models"]["TA2"]
    tr = payload["repr"]["transfer"]
    lines = [
        "EDITOR025_COMPLETE",
        "",
        "EDITOR024_RESULTS_COMMIT =",
        EDITOR024_RESULTS_COMMIT,
        "",
        "EDITOR025_PROTOCOL_FREEZE_COMMIT =",
        payload["protocol_freeze_commit"],
        "",
        "EDITOR025_RESULTS_COMMIT =",
        results_commit,
        "",
        "",
        "SOURCE_GATE =",
        payload["SOURCE_GATE"],
        "",
        "UNIT_TEST_GATE =",
        payload["UNIT_TEST_GATE"],
        "",
        "TRAINING_EXECUTED =",
        "NO",
        "",
        "MODEL_PARAMETERS_UPDATED =",
        "NO",
        "",
        "",
        "R61_ROLE_FROM_EDITOR025 =",
        R61_ROLE_FROM_EDITOR025,
        "",
        "",
        "R61_SCENARIO4_ANSWER_AVAILABLE =",
        "YES" if lab["s4_available"] else "NO",
        "",
        "R61_OFFICIAL_INSIDERS =",
        str(len(lab["official_users"])),
        "",
        "R61_POSITIVE_LABEL_USERS_UNDER_EDITOR024_RULE =",
        str(len(lab["pos_users"])),
        "",
        "R61_LABEL_INTEGRITY =",
        r["R61_LABEL_INTEGRITY"],
        "",
        "",
        "R61_DIAGNOSTIC_LABEL_VIEW_AVAILABLE =",
        "YES" if lab["diag_ok"] else "NO",
        "",
        "R61_TA2_PR_AUC_UNDER_DIAGNOSTIC_LABEL_VIEW =",
        str(lab["diagnostic_pr"]["TA2"] if lab["diagnostic_pr"] else "NOT_RUN"),
        "",
        "R61_DIAGNOSTIC_PREVALENCE =",
        str(lab["diagnostic_prevalence"] if lab["diagnostic_prevalence"] is not None else "NOT_RUN"),
        "",
        "",
        "TOP_5_SHIFTED_FEATURES =",
        ", ".join(sh["top_5_shifted_features"]),
        "",
        "R61_R62_SHIFT_VECTOR_CORRELATION =",
        str(payload["shift"]["cross"]["R61_R62_SHIFT_VECTOR_CORRELATION"]),
        "",
        "R61_COVARIATE_SHIFT =",
        r["R61_COVARIATE_SHIFT"],
        "",
        "",
        "TA2_NEGATIVE_THRESHOLD_EXCEEDANCE =",
        str(sc["ta2_neg_exceedance_mean"]),
        "",
        "TA2_POSITIVE_MEDIAN_GLOBAL_PERCENTILE =",
        str(sc["ta2_pos_median_pct"]),
        "",
        "TA2_TOP_N_POSITIVE_CAPTURE =",
        str(sc["ta2_top_n_capture"]),
        "",
        "",
        "C2_REPRESENTATION_TRANSFER_RATIO =",
        str(tr["C2-OPT"]),
        "",
        "F10_REPRESENTATION_TRANSFER_RATIO =",
        str(tr["F10"]),
        "",
        "TA2_REPRESENTATION_TRANSFER_RATIO =",
        str(tr["TA2"]),
        "",
        "L1_REPRESENTATION_TRANSFER_RATIO =",
        str(tr["L1"]),
        "",
        "REPRESENTATION_NONPORTABILITY =",
        r["REPRESENTATION_NONPORTABILITY"],
        "",
        "HEAD_SPECIFIC_FAILURE =",
        r["HEAD_SPECIFIC_FAILURE"],
        "",
        "",
        "TA2_ORIGINAL_R61_PR_AUC =",
        str(R61_MEAN_PR_AUC["TA2"]),
        "",
        "TA2_R52_SUPPORT_CLIP_PR_AUC =",
        str(clip["mean_pr_auc"]),
        "",
        "TA2_R52_SUPPORT_CLIP_DELTA =",
        str(clip["delta"]),
        "",
        "",
        "EDITOR025_PRIMARY_ROOT_CAUSE =",
        r["EDITOR025_PRIMARY_ROOT_CAUSE"],
        "",
        "",
        "EDITOR025_RECOMMENDED_NEXT_REMEDY =",
        r["EDITOR025_RECOMMENDED_NEXT_REMEDY"],
        "",
        "",
        "EDITOR024_RESULT_REMAINS_IMMUTABLE =",
        "YES",
        "",
        "R61_CAN_SERVE_AS_FUTURE_UNTOUCHED_TARGET =",
        "NO",
        "",
        "",
        "SHA_MANIFEST_VERIFICATION =",
        payload.get("SHA_MANIFEST_VERIFICATION", "PENDING"),
        "",
    ]
    text = "\n".join(lines) + "\n"
    write_text(REVIEW_ROOT / "EDITOR025_TERMINAL_BLOCK.txt", text)
    return text


def sha256_manifest(paths: list[Path], *, repo_root: Path | None = None) -> dict[str, str]:
    root = repo_root or REPO_ROOT
    out: dict[str, str] = {}
    files = [p for p in paths if p.exists() and p.is_file() and p.name != SHA256_MANIFEST_NAME]
    files.sort(key=lambda p: str(p.relative_to(root)).replace("\\", "/"))
    for p in files:
        out[str(p.relative_to(root)).replace("\\", "/")] = sha256_file(p)
    return out


def write_sha256_manifest_last() -> dict[str, str]:
    rec = sha256_manifest(list(REVIEW_ROOT.rglob("*")), repo_root=REPO_ROOT)
    write_json(REVIEW_ROOT / SHA256_MANIFEST_NAME, rec)
    return rec


def verify_sha256_manifest(rec: dict[str, str]) -> str:
    for rel, expected in rec.items():
        if sha256_file(REPO_ROOT / rel) != expected:
            return "FAIL"
    if SHA256_MANIFEST_NAME in rec:
        return "FAIL"
    return "PASS"


def run_unit_tests() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_editor025_r61_autopsy.py", "-q"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    return "PASS" if proc.returncode == 0 else "FAIL"


def finalise(payload: dict[str, Any]) -> dict[str, Any]:
    write_json(
        REVIEW_ROOT / "EDITOR025_RUN_MANIFEST.json",
        {
            "phase": "complete",
            "utc": utc_now(),
            "EDITOR025_RESULTS_COMMIT": "PENDING_BY_DESIGN",
            "TRAINING_EXECUTED": "NO",
            "MODEL_PARAMETERS_UPDATED": "NO",
            "R51_RERUN": "NO",
            "R62_RERUN": "NO",
            "R61_ROLE_FROM_EDITOR025": R61_ROLE_FROM_EDITOR025,
            "R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT": R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT,
            "R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025": (
                R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025
            ),
            "SOURCE_GATE": payload["SOURCE_GATE"],
            "UNIT_TEST_GATE": payload["UNIT_TEST_GATE"],
            "rulings": payload["rulings"],
        },
    )
    write_result_freeze(payload)
    payload["SHA_MANIFEST_VERIFICATION"] = "PASS"
    terminal_block(payload, results_commit="PENDING_BY_DESIGN")
    rec = write_sha256_manifest_last()
    ver = verify_sha256_manifest(rec)
    payload["SHA_MANIFEST_VERIFICATION"] = ver
    if ver != "PASS":
        raise Editor025Blocked("SHA_MANIFEST_VERIFICATION = FAIL")
    return payload


def run_campaign() -> dict[str, Any]:
    assert_no_training()
    freeze_sha = require_protocol_frozen(action="EDITOR-025 diagnostics")
    unit = run_unit_tests()
    if unit != "PASS":
        raise Editor025Blocked("UNIT_TEST_GATE = FAIL before diagnostics")
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    before = snapshot_paths(EDITOR024_REVIEW_ROOT)
    before.update(snapshot_paths(_pred_dir()))
    bundle = load_bundle()
    y = np.asarray(bundle["y"])
    if int(y.size) != R61_COMPLETED_N or int(y.sum()) != R61_COMPLETED_POSITIVES:
        raise Editor025Blocked("frozen EDITOR-024 bundle counts do not match locked facts")
    scaler = load_scaler()
    label = phase_a(bundle)
    shift = phase_b_c(bundle, scaler)
    scores = phase_d_e_f(bundle, label)
    fp = phase_g(bundle, scores)
    repr_pack = phase_h(bundle)
    clip = phase_i(bundle, shift, scaler)
    after = snapshot_paths(EDITOR024_REVIEW_ROOT)
    after.update(snapshot_paths(_pred_dir()))
    if after != before:
        raise Editor025Blocked("EDITOR024 artefacts mutated during EDITOR-025")
    ruling_packet = {
        "scenario4_available": label["s4_available"],
        "n_official_scenarios": 5,
        "n_scenarios_with_answers": label["n_with_answers"],
        "semantic_mismatch": label["semantic_mismatch"],
        "representation_transfer_ratios": repr_pack["transfer"],
        "original_pr_auc": R61_MEAN_PR_AUC,
        "prevalence": R61_PREVALENCE,
        "diagnostic_pr_auc": label["diagnostic_pr"],
        "diagnostic_prevalence": label["diagnostic_prevalence"] or R61_PREVALENCE,
        "psi_values": list(shift["summary"]["psi"].values()),
        "mean_shift_z": list(shift["summary"]["mean_shift_z"].values()),
        "oos_rates": list(shift["summary"]["oos"].values()),
        "binary_rate_diffs": list(shift["summary"]["binary_rate_abs_diff"].values()),
        "count_activity_levels_primary_shift": shift["summary"]["count_activity_levels_primary_shift"],
        "broad_generation_shift_remains": abs(float(shift["cross"]["R61_R62_SHIFT_VECTOR_CORRELATION"] or 0)) >= 0.5,
    }
    rulings = apply_rulings(ruling_packet)
    write_json(REVIEW_ROOT / "EDITOR025_ROOT_CAUSE_RULING.json", {"packet": ruling_packet, **rulings})
    write_json(
        REVIEW_ROOT / "EDITOR025_REMEDY_RECOMMENDATION.json",
        {
            "EDITOR025_RECOMMENDED_NEXT_REMEDY": rulings["EDITOR025_RECOMMENDED_NEXT_REMEDY"],
            "EDITOR025_PRIMARY_ROOT_CAUSE": rulings["EDITOR025_PRIMARY_ROOT_CAUSE"],
            "R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT": R61_CAN_BE_USED_FOR_EDITOR026_DEVELOPMENT,
            "R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025": (
                R61_CAN_BE_USED_AS_FINAL_UNTOUCHED_CONFIRMATION_AFTER_EDITOR025
            ),
            "do_not_start_editor026_automatically": True,
            "do_not_train": True,
        },
    )
    payload: dict[str, Any] = {
        "SOURCE_GATE": "PASS",
        "UNIT_TEST_GATE": unit,
        "protocol_freeze_commit": freeze_sha,
        "label": label,
        "shift": shift,
        "scores": scores,
        "fp": {"n_fp": int(len(fp["fp"])), "n_ref": int(len(fp["ref"]))},
        "repr": repr_pack,
        "clip": clip,
        "rulings": rulings,
        "EDITOR024_RESULTS_COMMIT": EDITOR024_RESULTS_COMMIT,
        "R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET": R61_ELIGIBLE_AS_FUTURE_UNTOUCHED_TARGET,
    }
    # drop large arrays before JSON provenance
    lab_store = {k: v for k, v in label.items() if k not in {"crosswalk", "y_diag", "audit_rows"}}
    payload["label"] = lab_store
    shift_store = {k: v for k, v in shift.items() if k not in {"train_raw", "train_scaled", "rows_all", "bounds"}}
    payload["shift"] = shift_store
    payload["scores"] = {k: v for k, v in scores.items() if k not in {"ta2_mean_p", "y", "seq", "ranking"}}
    write_json(
        REVIEW_ROOT / "EDITOR025_PROVENANCE.json",
        {
            "EDITOR024_RESULTS_COMMIT": EDITOR024_RESULTS_COMMIT,
            "EDITOR025_PROTOCOL_FREEZE_COMMIT": freeze_sha,
            "editor024_review_hashes": before,
            "scaler_sha256": scaler["sha256"],
            "answer_files": lab_store["chosen"],
            "TRAINING_EXECUTED": "NO",
            "MODEL_PARAMETERS_UPDATED": "NO",
            "head": _git_sha(),
            "written_at": utc_now(),
        },
    )
    return finalise(payload)
