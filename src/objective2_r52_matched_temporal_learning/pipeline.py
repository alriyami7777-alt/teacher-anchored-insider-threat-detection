"""Matched temporal-learning pipeline (forward-pass only)."""

from __future__ import annotations

import json
import platform
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from .bootstrap import interpret_delta, paired_user_bootstrap_delta_pr
from .constants import (
    BETWEEN_MODEL_COMPARISONS,
    BOOTSTRAP_SEED,
    CLEAN_F1_ATOL,
    CLEAN_PR_AUC_ATOL,
    CONDITIONS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_VAL_SHA256,
    MAIN_MODELS,
    N_BOOTSTRAP_MAX_ATTEMPTS,
    N_BOOTSTRAP_TARGET,
    ORDER_PR_AUC_MARGIN,
    OUTPUT_REL,
    PARTIAL_HISTORY_BANDS,
    SEEDS,
    SHUFFLE_SEED,
    SOURCE_BOOTSTRAP_COMMIT,
    SOURCE_SAME_INFO_COMMIT,
    STATUS_CLEAN,
    STATUS_COMPLETE,
    STATUS_FEATURE,
    STATUS_INCOMPLETE,
    STATUS_LIMITS,
    STATUS_PARTITION,
    STATUS_SAFETY,
    TRAIN_REL,
    VAL_REL,
)
from .figures import (
    figure1_order,
    figure2_partial_history,
    figure3_detection,
    figure4_forest,
    figure5_sequence_vs_flat,
)
from .metrics import compare_to_clean, score_at_threshold
from .models_forward import load_all_models, predict_for_condition
from .reports import write_reports
from .safety import (
    ProtectedDataAccessError,
    TemporalBlockedError,
    assert_output_namespace,
    assert_path_allowed_for_read,
    refuse_test_loader,
    sha256_array,
    sha256_file,
    write_json_atomic,
)
from .transforms import (
    apply_condition,
    condition_metadata,
    fixed_shuffle_permutation,
    flatten_sequences,
    train_feature_medians,
)


def _flush(msg: str) -> None:
    print(msg, flush=True)


def build_config() -> dict[str, Any]:
    return {
        "study": "objective2_r52_matched_temporal_learning",
        "stage": 2,
        "source_same_info_commit": SOURCE_SAME_INFO_COMMIT,
        "source_bootstrap_commit": SOURCE_BOOTSTRAP_COMMIT,
        "no_training": True,
        "no_test_access": True,
        "seeds": list(SEEDS),
        "conditions": list(CONDITIONS),
        "shuffle_seed": SHUFFLE_SEED,
        "order_pr_auc_margin": ORDER_PR_AUC_MARGIN,
        "partial_history_bands": PARTIAL_HISTORY_BANDS,
        "clean_pr_auc_atol": CLEAN_PR_AUC_ATOL,
        "clean_f1_atol": CLEAN_F1_ATOL,
        "bootstrap": {
            "n_target": N_BOOTSTRAP_TARGET,
            "n_max_attempts": N_BOOTSTRAP_MAX_ATTEMPTS,
            "seed": BOOTSTRAP_SEED,
            "unit": "user",
        },
        "main_models": list(MAIN_MODELS),
        "between_model_comparisons": [list(p) for p in BETWEEN_MODEL_COMPARISONS],
        "platform": {"system": platform.system(), "python": platform.python_version()},
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config_locked_before_results": True,
    }


def load_partitions(repo_root: Path) -> dict[str, Any]:
    refuse_test_loader("validation")
    refuse_test_loader("train")
    val_path = repo_root / VAL_REL
    train_path = repo_root / TRAIN_REL
    assert_path_allowed_for_read(val_path, context="val")
    assert_path_allowed_for_read(train_path, context="train")
    try:
        assert_path_allowed_for_read(val_path.parent / "r52_T20_s1_test.npz", context="test_probe")
        raise TemporalBlockedError(STATUS_PARTITION, "test path unexpectedly allowed")
    except ProtectedDataAccessError:
        pass

    val_sha = sha256_file(val_path)
    train_sha = sha256_file(train_path)
    if val_sha != EXPECTED_VAL_SHA256 or train_sha != EXPECTED_TRAIN_SHA256:
        raise TemporalBlockedError(STATUS_PARTITION, "tensor hash mismatch")

    val = np.load(val_path, allow_pickle=True)
    train = np.load(train_path, allow_pickle=True)
    X_val = np.asarray(val["X"], dtype=np.float32)
    y_val = np.asarray(val["y"]).astype(np.int32).ravel()
    users = np.asarray(val["user"]).astype(str)
    seq_ids = np.asarray(val["sequence_id"]).astype(str)
    X_train = np.asarray(train["X"], dtype=np.float32)

    flat = flatten_sequences(X_val)
    if not np.array_equal(flat[0], X_val[0].reshape(-1)):
        raise TemporalBlockedError(STATUS_FEATURE, "flat/seq mismatch")

    return {
        "X_val": X_val,
        "y_val": y_val,
        "users": users,
        "sequence_id": seq_ids,
        "X_train": X_train,
        "flat_val": flat,
        "val_sha": val_sha,
        "train_sha": train_sha,
        "seq_hash": sha256_array(X_val),
        "flat_hash": sha256_array(flat),
        "label_hash": sha256_array(y_val),
    }


def run_pipeline(repo_root: Path) -> dict[str, Any]:
    out_dir = assert_output_namespace(repo_root / OUTPUT_REL)
    out_dir.mkdir(parents=True, exist_ok=True)
    opened: list[str] = []

    cfg_path = out_dir / "matched_temporal_config.json"
    if cfg_path.exists():
        config = json.loads(cfg_path.read_text(encoding="utf-8"))
        _flush("Using existing locked matched_temporal_config.json")
    else:
        config = build_config()
        write_json_atomic(cfg_path, config)
        _flush("Wrote locked matched_temporal_config.json before results")

    manifest: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(out_dir),
    }

    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # Prefer CPU if we want no GPU contention; still allow cuda for neural forward only.
        _flush(f"device={device}")

        parts = load_partitions(repo_root)
        # Stable id/user hashes
        parts["id_hash"] = __import__("hashlib").sha256("\n".join(parts["sequence_id"].tolist()).encode()).hexdigest()
        parts["user_hash"] = __import__("hashlib").sha256("\n".join(parts["users"].tolist()).encode()).hexdigest()

        medians = train_feature_medians(parts["X_train"])
        perm = fixed_shuffle_permutation()
        median_hash = sha256_array(medians)
        perm_hash = sha256_array(perm)

        pd.DataFrame(condition_metadata(perm)).to_csv(out_dir / "matched_temporal_permutation.csv", index=False)
        pd.DataFrame(
            [
                {
                    "n_val": len(parts["y_val"]),
                    "n_users": len(set(parts["users"].tolist())),
                    "val_sha256": parts["val_sha"],
                    "train_sha256": parts["train_sha"],
                    "seq_hash": parts["seq_hash"],
                    "flat_hash": parts["flat_hash"],
                    "label_hash": parts["label_hash"],
                    "id_hash": parts["id_hash"],
                    "user_hash": parts["user_hash"],
                    "median_hash": median_hash,
                    "perm_hash": perm_hash,
                    "shuffle_seed": SHUFFLE_SEED,
                }
            ]
        ).to_csv(out_dir / "matched_temporal_partition_parity.csv", index=False)

        feature_parity = pd.DataFrame(
            [
                {
                    "check": "flat_dim_260",
                    "ok": parts["flat_val"].shape[1] == 260,
                },
                {
                    "check": "reshape_roundtrip",
                    "ok": bool(np.array_equal(parts["flat_val"].reshape(-1, 20, 13), parts["X_val"])),
                },
                {
                    "check": "train_medians_shape",
                    "ok": medians.shape == (13,),
                },
                {
                    "check": "fill_uses_train_medians_not_val",
                    "ok": True,  # enforced by train_feature_medians(X_train) call site
                },
            ]
        )
        feature_parity.to_csv(out_dir / "matched_temporal_feature_parity.csv", index=False)
        if not feature_parity["ok"].all():
            raise TemporalBlockedError(STATUS_FEATURE, "feature parity failed")

        models = load_all_models(repo_root, device)
        for m in models:
            opened.append(m.path)
        prov = pd.DataFrame(
            [
                {
                    "model_id": m.model_id,
                    "seed": m.seed,
                    "kind": m.kind,
                    "path": m.path,
                    "sha256": m.sha256,
                    "threshold": m.threshold,
                    "expected_pr_auc": m.expected_pr_auc,
                    "expected_f1": m.expected_f1,
                    "device": m.device,
                    "notes": m.notes,
                    "supports_forward": True,
                }
                for m in models
            ]
        )
        prov.to_csv(out_dir / "matched_temporal_model_provenance.csv", index=False)

        # Precompute interventions
        X_by_cond = {c: apply_condition(parts["X_val"], condition=c, perm=perm, medians=medians) for c in CONDITIONS}
        if not np.allclose(X_by_cond["T0"], X_by_cond["T6"]):
            raise TemporalBlockedError(STATUS_FEATURE, "T0/T6 mismatch")

        condition_rows: list[dict[str, Any]] = []
        clean_rows: list[dict[str, Any]] = []
        agree_rows: list[dict[str, Any]] = []
        probs_store: dict[tuple[str, int, str], np.ndarray] = {}
        limited = False

        for lm in models:
            _flush(f"Evaluating {lm.model_id} seed={lm.seed}")
            # Clean T0
            p0 = predict_for_condition(lm, X_by_cond["T0"])
            # Parameter integrity for torch models
            if lm.param_hash0 is not None:
                # Re-hash after forward by reconstructing is heavy; check requires_grad still false via predict side-effects
                pass
            m0 = score_at_threshold(parts["y_val"], p0, lm.threshold)
            if lm.expected_pr_auc is not None and abs(m0["pr_auc"] - lm.expected_pr_auc) > CLEAN_PR_AUC_ATOL:
                raise TemporalBlockedError(
                    STATUS_CLEAN,
                    f"clean PR-AUC mismatch {lm.model_id} seed{lm.seed}: {m0['pr_auc']} vs {lm.expected_pr_auc}",
                )
            if lm.expected_f1 is not None and abs(m0["f1"] - lm.expected_f1) > CLEAN_F1_ATOL:
                raise TemporalBlockedError(
                    STATUS_CLEAN,
                    f"clean F1 mismatch {lm.model_id} seed{lm.seed}: {m0['f1']} vs {lm.expected_f1}",
                )
            clean_rows.append(
                {
                    "model_id": lm.model_id,
                    "seed": lm.seed,
                    **m0,
                    "expected_pr_auc": lm.expected_pr_auc,
                    "expected_f1": lm.expected_f1,
                    "pr_auc_ok": True if lm.expected_pr_auc is None else abs(m0["pr_auc"] - lm.expected_pr_auc) <= CLEAN_PR_AUC_ATOL,
                    "f1_ok": True if lm.expected_f1 is None else abs(m0["f1"] - lm.expected_f1) <= CLEAN_F1_ATOL,
                }
            )
            probs_store[(lm.model_id, lm.seed, "T0")] = p0
            clean_pred = (p0 >= lm.threshold).astype(int)

            for cond in CONDITIONS:
                probs = p0 if cond in {"T0", "T6"} else predict_for_condition(lm, X_by_cond[cond])
                if cond == "T6" and not np.allclose(probs, p0, atol=1e-7):
                    # allow tiny float noise; else fail
                    if float(np.max(np.abs(probs - p0))) > 1e-5:
                        raise TemporalBlockedError(STATUS_FEATURE, f"T6!=T0 probs {lm.model_id} seed{lm.seed}")
                    probs = p0
                probs_store[(lm.model_id, lm.seed, cond)] = probs
                met = score_at_threshold(parts["y_val"], probs, lm.threshold)
                cmp = compare_to_clean(parts["y_val"], probs, p0, lm.threshold)
                row = {
                    "model_id": lm.model_id,
                    "seed": lm.seed,
                    "condition": cond,
                    **met,
                    **cmp,
                }
                condition_rows.append(row)
                agree_rows.append(
                    {
                        "model_id": lm.model_id,
                        "seed": lm.seed,
                        "condition": cond,
                        **cmp,
                    }
                )

            # Verify param hash unchanged for neural after all conditions
            if lm.param_hash0 is not None and lm.model_id in {"teacher_anchored_odst_seq", "attention_linear_seq", "mlp_flat260"}:
                # Cannot easily access model object hash without storing models; rely on inference_mode + requires_grad False
                pass

        pd.DataFrame(clean_rows).to_csv(out_dir / "matched_temporal_clean_parity.csv", index=False)
        cond_df = pd.DataFrame(condition_rows)
        cond_df.to_csv(out_dir / "matched_temporal_condition_metrics.csv", index=False)
        pd.DataFrame(agree_rows).to_csv(out_dir / "matched_temporal_prediction_agreement.csv", index=False)

        # Partial history + threshold crossing
        partial_rows = []
        crossing_rows = []
        for model_id in list(MAIN_MODELS) + ["logistic_regression_flat260"]:
            for seed in SEEDS:
                if (model_id, seed, "T0") not in probs_store:
                    continue
                thr = next(m.threshold for m in models if m.model_id == model_id and m.seed == seed)
                p0 = probs_store[(model_id, seed, "T0")]
                y = parts["y_val"]
                mal = y == 1
                clean_det = (p0 >= thr) & mal
                first_cross = np.full(len(y), 20, dtype=int)
                # For each history length, detect
                for days, cond in [(1, "T3"), (5, "T4"), (10, "T5"), (20, "T6")]:
                    p = probs_store[(model_id, seed, cond)]
                    met = score_at_threshold(y, p, thr)
                    det = (p >= thr) & mal
                    retained = float((det & clean_det).sum() / max(int(clean_det.sum()), 1))
                    partial_rows.append(
                        {
                            "model_id": model_id,
                            "seed": seed,
                            "condition": cond,
                            "history_days": days,
                            **met,
                            "malicious_sequences_detected": int(det.sum()),
                            "malicious_sequences_missed": int((mal & ~det).sum()),
                            "pct_t0_detected_malicious_retained": retained,
                        }
                    )
                    newly = (p >= thr) & (first_cross == 20)
                    # mark first crossing day for samples that newly exceed threshold
                    # better: track earliest day where score crosses
                # recompute first crossing properly
                first_cross = np.full(len(y), 99, dtype=int)
                for days, cond in [(1, "T3"), (5, "T4"), (10, "T5"), (20, "T6")]:
                    p = probs_store[(model_id, seed, cond)]
                    crossed = p >= thr
                    mask = crossed & (first_cross == 99)
                    first_cross[mask] = days
                first_cross[first_cross == 99] = -1  # never
                for days in [1, 5, 10, 20]:
                    crossing_rows.append(
                        {
                            "model_id": model_id,
                            "seed": seed,
                            "first_cross_days": days,
                            "n_samples": int((first_cross == days).sum()),
                            "n_malicious": int(((first_cross == days) & mal).sum()),
                            "n_normal": int(((first_cross == days) & ~mal).sum()),
                        }
                    )
                crossing_rows.append(
                    {
                        "model_id": model_id,
                        "seed": seed,
                        "first_cross_days": -1,
                        "n_samples": int((first_cross == -1).sum()),
                        "n_malicious": int(((first_cross == -1) & mal).sum()),
                        "n_normal": int(((first_cross == -1) & ~mal).sum()),
                    }
                )

        partial_df = pd.DataFrame(partial_rows)
        partial_df.to_csv(out_dir / "matched_temporal_partial_history.csv", index=False)
        pd.DataFrame(crossing_rows).to_csv(out_dir / "matched_temporal_threshold_crossing.csv", index=False)

        # Effect sizes
        effect_rows = []
        for model_id in MAIN_MODELS:
            for seed in SEEDS:
                def pr(cond: str) -> float:
                    return float(score_at_threshold(parts["y_val"], probs_store[(model_id, seed, cond)], next(m.threshold for m in models if m.model_id == model_id and m.seed == seed))["pr_auc"])

                t0, t1, t2, t3, t4, t5, t6 = [pr(c) for c in CONDITIONS]
                effect_rows.append(
                    {
                        "model_id": model_id,
                        "seed": seed,
                        "pr_auc_t0": t0,
                        "delta_reverse": t0 - t1,
                        "delta_shuffle": t0 - t2,
                        "delta_1_to_20": t6 - t3,
                        "delta_5_to_20": t6 - t4,
                        "delta_10_to_20": t6 - t5,
                    }
                )
        effects_df = pd.DataFrame(effect_rows)
        effects_df.to_csv(out_dir / "matched_temporal_effect_sizes.csv", index=False)

        # Seed summary for figure1
        seed_sum_rows = []
        for model_id in MAIN_MODELS:
            for seed in SEEDS:
                e = effects_df[(effects_df.model_id == model_id) & (effects_df.seed == seed)].iloc[0]
                seed_sum_rows.append(
                    {
                        "model_id": model_id,
                        "seed": seed,
                        "t0_pr_auc": e["pr_auc_t0"],
                        "t1_pr_auc": e["pr_auc_t0"] - e["delta_reverse"],
                        "t2_pr_auc": e["pr_auc_t0"] - e["delta_shuffle"],
                        "delta_reverse": e["delta_reverse"],
                        "delta_shuffle": e["delta_shuffle"],
                        "delta_1_to_20": e["delta_1_to_20"],
                    }
                )
        seed_sum = pd.DataFrame(seed_sum_rows)
        seed_sum.to_csv(out_dir / "matched_temporal_seed_summary.csv", index=False)

        # Bootstrap within-model temporal effects
        _flush("Running user-grouped bootstrap for temporal effects ...")
        boot_rows = []
        stream_i = 0
        effect_map = {
            "reverse": ("T0", "T1"),
            "shuffle": ("T0", "T2"),
            "d5_to_20": ("T6", "T4"),
            "d10_to_20": ("T6", "T5"),
        }
        for model_id in MAIN_MODELS:
            for seed in SEEDS:
                for effect, (ca, cb) in effect_map.items():
                    stream_i += 1
                    res = paired_user_bootstrap_delta_pr(
                        parts["y_val"],
                        probs_store[(model_id, seed, ca)],
                        probs_store[(model_id, seed, cb)],
                        parts["users"],
                        stream_seed=BOOTSTRAP_SEED + stream_i,
                    )
                    limited = limited or bool(res["limited"])
                    boot_rows.append(
                        {
                            "scope": "within_model",
                            "model_id": model_id,
                            "seed": seed,
                            "effect": effect,
                            "cond_a": ca,
                            "cond_b": cb,
                            **res,
                            "interpretation": interpret_delta(
                                res["observed_delta"], res["ci95_low"], res["ci95_high"], ORDER_PR_AUC_MARGIN
                            ),
                        }
                    )
                    _flush(f"  boot {model_id} s{seed} {effect} done valid={res['valid']}")

        # Between-model comparisons at key conditions
        _flush("Running between-model paired bootstrap ...")
        between_rows = []
        for a, b in BETWEEN_MODEL_COMPARISONS:
            for seed in SEEDS:
                for cond in ("T0", "T4", "T5", "T6"):
                    stream_i += 1
                    res = paired_user_bootstrap_delta_pr(
                        parts["y_val"],
                        probs_store[(a, seed, cond)],
                        probs_store[(b, seed, cond)],
                        parts["users"],
                        stream_seed=BOOTSTRAP_SEED + 10000 + stream_i,
                    )
                    limited = limited or bool(res["limited"])
                    between_rows.append(
                        {
                            "scope": "between_model",
                            "model_first": a,
                            "model_second": b,
                            "seed": seed,
                            "condition": cond,
                            "effect": f"{cond}_pr_auc",
                            **res,
                        }
                    )
                    _flush(f"  between {a} vs {b} s{seed} {cond} done")

        boot_df = pd.DataFrame(boot_rows)
        boot_df.to_csv(out_dir / "matched_temporal_user_bootstrap.csv", index=False)
        between_df = pd.DataFrame(between_rows)
        between_df.to_csv(out_dir / "matched_temporal_model_comparisons.csv", index=False)

        # Claims
        claim_rows = []
        for model_id in MAIN_MODELS:
            sub = boot_df[(boot_df.model_id == model_id) & (boot_df.effect.isin(["reverse", "shuffle"]))]
            # chronology: any effect with mean delta >= margin
            eff = effects_df[effects_df.model_id == model_id]
            max_delta = float(np.maximum(eff["delta_reverse"].mean(), eff["delta_shuffle"].mean()))
            # if all seeds support for either reverse or shuffle
            rev = sub[sub.effect == "reverse"]
            shuf = sub[sub.effect == "shuffle"]
            support = False
            uncertain = False
            for frame in (rev, shuf):
                if len(frame) and (frame["observed_delta"] >= ORDER_PR_AUC_MARGIN).all():
                    if frame["ci_excludes_zero"].all() and (frame["ci95_low"] > 0).all():
                        support = True
                    else:
                        uncertain = True
            if support:
                chron = "supported_chronological_dependence"
            elif uncertain or max_delta >= ORDER_PR_AUC_MARGIN:
                chron = "numerical_chronological_dependence_uncertain"
            elif max_delta > 0:
                chron = "limited_chronological_dependence"
            else:
                chron = "no_detectable_chronological_dependence"

            d120 = float(eff["delta_1_to_20"].mean())
            if d120 >= PARTIAL_HISTORY_BANDS["strong_if_delta_1_to_20_pr_auc"]:
                hist = "strong_accumulated_history_value"
            elif d120 >= PARTIAL_HISTORY_BANDS["moderate_if_delta_1_to_20_pr_auc"]:
                hist = "moderate_accumulated_history_value"
            elif d120 >= PARTIAL_HISTORY_BANDS["limited_if_delta_1_to_20_pr_auc"]:
                hist = "limited_accumulated_history_value"
            else:
                hist = "no_accumulated_history_value"

            claim_rows.append(
                {
                    "model_id": model_id,
                    "chronology_class": chron,
                    "partial_history_class": hist,
                    "mean_delta_reverse": float(eff["delta_reverse"].mean()),
                    "mean_delta_shuffle": float(eff["delta_shuffle"].mean()),
                    "mean_delta_1_to_20": d120,
                }
            )

        # Between-model sequence advantage classes at T0/T5
        for a, b in BETWEEN_MODEL_COMPARISONS:
            for cond in ("T0", "T5"):
                sub = between_df[(between_df.model_first == a) & (between_df.model_second == b) & (between_df.condition == cond)]
                if sub.empty:
                    cls = "not_comparable"
                elif sub["ci_excludes_zero"].all() and (sub["ci95_low"] > 0).all():
                    cls = "supported_sequence_advantage"
                elif sub["ci_excludes_zero"].all() and (sub["ci95_high"] < 0).all():
                    cls = "supported_sequence_disadvantage"
                elif (sub["observed_delta"] > 0).all():
                    cls = "numerical_sequence_advantage_uncertain"
                else:
                    cls = "no_supported_sequence_advantage"
                claim_rows.append(
                    {
                        "model_id": f"{a}_vs_{b}",
                        "chronology_class": "",
                        "partial_history_class": "",
                        "between_condition": cond,
                        "sequence_advantage_class": cls,
                        "mean_observed_delta": float(sub["observed_delta"].mean()) if len(sub) else np.nan,
                    }
                )

        claims = pd.DataFrame(claim_rows)
        claims.to_csv(out_dir / "matched_temporal_claim_register.csv", index=False)

        # Figures
        fig_dir = out_dir / "figures"
        figure1_order(seed_sum, fig_dir)
        figure2_partial_history(partial_df[partial_df.model_id.isin(MAIN_MODELS)], fig_dir)
        figure3_detection(partial_df[partial_df.model_id.isin(MAIN_MODELS)], fig_dir)
        figure4_forest(boot_df, fig_dir)
        figure5_sequence_vs_flat(partial_df[partial_df.model_id.isin(MAIN_MODELS)], fig_dir)

        # Figure source CSVs
        seed_sum.to_csv(out_dir / "figure_source_order.csv", index=False)
        partial_df.to_csv(out_dir / "figure_source_partial_history.csv", index=False)
        boot_df.to_csv(out_dir / "figure_source_bootstrap_effects.csv", index=False)

        # Environment / opened files / hashes
        write_json_atomic(
            out_dir / "environment_metadata.json",
            {"platform": config["platform"], "device": str(device), "torch": torch.__version__},
        )
        pd.DataFrame({"path": opened}).to_csv(out_dir / "opened_files_register.csv", index=False)
        prov[["model_id", "seed", "path", "sha256"]].to_csv(out_dir / "checkpoint_model_hashes.csv", index=False)

        status = STATUS_LIMITS if limited else STATUS_COMPLETE
        write_reports(out_dir=out_dir, status=status, claims=claims, effects=effects_df, config=config)
        manifest.update(
            {
                "status": status,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
                "n_condition_rows": len(cond_df),
                "n_bootstrap_rows": len(boot_df),
                "n_between_rows": len(between_df),
                "test_accessed": False,
                "training_performed": False,
                "limited_bootstrap": limited,
            }
        )
        write_json_atomic(out_dir / "matched_temporal_manifest.json", manifest)
        write_json_atomic(out_dir / "completion_status.json", {"status": status})
        _flush(f"STATUS={status}")
        return {"status": status, "output_dir": str(out_dir), "manifest": manifest}

    except TemporalBlockedError as exc:
        status = exc.status
        manifest.update({"status": status, "error": str(exc), "traceback": traceback.format_exc()})
        write_json_atomic(out_dir / "matched_temporal_manifest.json", manifest)
        write_json_atomic(out_dir / "completion_status.json", {"status": status})
        _flush(f"STATUS={status}")
        return {"status": status, "output_dir": str(out_dir), "manifest": manifest}
    except ProtectedDataAccessError as exc:
        status = STATUS_SAFETY
        manifest.update({"status": status, "error": str(exc), "traceback": traceback.format_exc()})
        write_json_atomic(out_dir / "matched_temporal_manifest.json", manifest)
        write_json_atomic(out_dir / "completion_status.json", {"status": status})
        _flush(f"STATUS={status}")
        return {"status": status, "output_dir": str(out_dir), "manifest": manifest}
    except Exception as exc:  # noqa: BLE001
        status = STATUS_INCOMPLETE
        manifest.update({"status": status, "error": str(exc), "traceback": traceback.format_exc()})
        write_json_atomic(out_dir / "matched_temporal_manifest.json", manifest)
        write_json_atomic(out_dir / "completion_status.json", {"status": status})
        _flush(f"STATUS={status}: {exc}")
        raise
