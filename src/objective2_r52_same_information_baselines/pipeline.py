"""End-to-end same-information baseline comparison pipeline."""

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

from .analyses import (
    build_bootstrap_table,
    claim_register,
    model_summary_table,
    pairwise_comparisons,
    seed_metrics_table,
)
from .constants import (
    ATTENTION_LINEAR,
    BOOTSTRAP_POLICY,
    CANDIDATE_TAG,
    EVIDENCE_AL_REL,
    EVIDENCE_LB_REL,
    EVIDENCE_TA_REL,
    FLAT_DIM,
    LOGISTIC_REGRESSION_LOCKED,
    MLP_LOCKED,
    OBJ2_AUDIT_COMMIT,
    OUTPUT_REL,
    RANDOM_FOREST_LOCKED,
    R52_TA_PACKAGE_COMMIT,
    R52_TA_STAMP_COMMIT,
    SEEDS,
    STATUS_COMPLETE,
    STATUS_CONFIG_BLOCKED,
    STATUS_FEATURE_MISMATCH,
    STATUS_GPU_BLOCKED,
    STATUS_INCOMPLETE,
    STATUS_PARTITION_MISMATCH,
    STATUS_SAFETY,
    TEACHER_ANCHORED,
    TEMPORAL_COMMITS,
    THRESHOLD_POLICY,
    XGBOOST_LOCKED,
)
from .data import load_train_validation, parity_tables
from .evidence import (
    load_attention_linear_summaries,
    load_engineered_context,
    load_engineered_seed_details,
    load_teacher_anchored_summaries,
)
from .figures import (
    figure1_same_information,
    figure2_engineered_context,
    figure3_perf_vs_train_cost,
    figure4_perf_vs_complexity,
)
from .models import run_flat_baselines
from .reports import write_reports
from .safety import (
    ComparisonBlockedError,
    ProtectedDataAccessError,
    assert_output_namespace,
    gpu_busy_with_protected_jobs,
    list_python_processes,
    nvidia_smi_text,
    sha256_file,
    software_versions,
    write_json_atomic,
)


def _flush(msg: str) -> None:
    print(msg, flush=True)


def build_predeclared_config(*, device: str, gpu_blocked: bool) -> dict[str, Any]:
    return {
        "study": "objective2_r52_same_information_baselines",
        "comparison_label": "r5.2 validation comparison",
        "not_independent_test": True,
        "candidate_tag": CANDIDATE_TAG,
        "obj2_audit_commit": OBJ2_AUDIT_COMMIT,
        "r52_ta_package_commit": R52_TA_PACKAGE_COMMIT,
        "r52_ta_stamp_commit": R52_TA_STAMP_COMMIT,
        "temporal_commits": list(TEMPORAL_COMMITS),
        "seeds": list(SEEDS),
        "flat_dim": FLAT_DIM,
        "flatten_order": "day1_features_1to13_then_day2_..._day20",
        "threshold_policy": THRESHOLD_POLICY,
        "bootstrap_policy": BOOTSTRAP_POLICY,
        "models": {
            "logistic_regression_flat260": LOGISTIC_REGRESSION_LOCKED,
            "mlp_flat260": MLP_LOCKED,
            "random_forest_flat260": RANDOM_FOREST_LOCKED,
            "xgboost_flat260": XGBOOST_LOCKED,
            "attention_linear_seq": {
                "source": "saved_r52_odst_confirmation",
                "retrain": False,
                "seeds": list(SEEDS),
                "dirs": {str(k): v for k, v in ATTENTION_LINEAR.items()},
            },
            "teacher_anchored_odst_seq": {
                "source": "saved_r52_teacher_anchored_reproducibility_v1",
                "retrain": False,
                "seeds": list(SEEDS),
                "checkpoints": {str(k): v for k, v in TEACHER_ANCHORED.items()},
            },
        },
        "class_weighting_policy": {
            "logistic_regression": "balanced",
            "mlp": "BCE pos_weight = n_neg/n_pos from train only",
            "random_forest": "balanced_subsample",
            "xgboost": "scale_pos_weight = n_neg/n_pos from train only",
        },
        "preprocessing": {
            "logistic_regression": "StandardScaler fit train-only",
            "mlp": "StandardScaler fit train-only",
            "random_forest": "unscaled flattened values",
            "xgboost": "unscaled flattened values",
            "sequence_models": "prebaked train-only scaling in tensor files; no retrain",
        },
        "maximum_training_budget": {
            "mlp_max_epochs": MLP_LOCKED["max_epochs"],
            "mlp_patience": MLP_LOCKED["patience"],
            "rf_n_estimators": RANDOM_FOREST_LOCKED["n_estimators"],
            "xgb_n_estimators": XGBOOST_LOCKED["n_estimators"],
            "logistic_max_iter": LOGISTIC_REGRESSION_LOCKED["max_iter"],
            "logistic_model_class": LOGISTIC_REGRESSION_LOCKED.get("model_class", "LogisticRegression"),
        },
        "hardware_assignment": {
            "classical_baselines": "cpu",
            "mlp": device,
            "saved_neural_evidence": "no_retrain",
            "gpu_blocked_for_launch": gpu_blocked,
        },
        "software_versions": software_versions(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config_locked_before_results": True,
    }


def run_pipeline(repo_root: Path, *, force_cpu_mlp: bool = False) -> dict[str, Any]:
    out_dir = assert_output_namespace(repo_root / OUTPUT_REL)
    out_dir.mkdir(parents=True, exist_ok=True)

    smi = nvidia_smi_text()
    (out_dir / "nvidia_smi_preflight.txt").write_text(smi, encoding="utf-8")
    procs = list_python_processes()
    write_json_atomic(out_dir / "python_process_preflight.json", procs)
    gpu_blocked = gpu_busy_with_protected_jobs(smi)

    device = torch.device("cpu" if force_cpu_mlp or not torch.cuda.is_available() else "cuda")
    if gpu_blocked:
        # Complete implementation path: classical on CPU; MLP on CPU only.
        device = torch.device("cpu")
        _flush("GPU occupied by protected job — continuing with CPU-compatible training only.")

    # 1) Freeze config BEFORE any model results.
    cfg_path = out_dir / "same_information_config.json"
    if cfg_path.exists():
        config = json.loads(cfg_path.read_text(encoding="utf-8"))
        _flush("Using existing predeclared same_information_config.json (no modification).")
    else:
        config = build_predeclared_config(device=str(device), gpu_blocked=gpu_blocked)
        write_json_atomic(cfg_path, config)
        _flush("Wrote locked same_information_config.json before results.")

    status = STATUS_INCOMPLETE
    manifest: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(out_dir),
        "gpu_blocked": gpu_blocked,
    }

    try:
        # Verify evidence junctions exist and are read-only sources.
        for rel in (EVIDENCE_TA_REL, EVIDENCE_AL_REL, EVIDENCE_LB_REL):
            p = repo_root / rel
            if not p.exists():
                raise ComparisonBlockedError(
                    STATUS_CONFIG_BLOCKED,
                    f"Missing read-only evidence path: {p}",
                )

        bundle = load_train_validation(repo_root, verify_hashes=True)
        partition_df, label_df, feature_audit_df, mapping_df = parity_tables(bundle)
        partition_df.to_csv(out_dir / "same_information_partition_parity.csv", index=False)
        label_df.to_csv(out_dir / "same_information_label_parity.csv", index=False)
        feature_audit_df.to_csv(out_dir / "same_information_feature_audit.csv", index=False)
        mapping_df.to_csv(out_dir / "same_information_flatten_mapping.csv", index=False)

        if not bool(label_df["ok"].all()):
            raise ComparisonBlockedError(STATUS_PARTITION_MISMATCH, "label parity failed")

        train = bundle["train"]
        val = bundle["validation"]

        # Load saved neural evidence (no retrain).
        ta_rows = load_teacher_anchored_summaries(repo_root, val.y)
        al_rows = load_attention_linear_summaries(repo_root, val.y)
        for r in ta_rows:
            expected = TEACHER_ANCHORED[int(r["seed"])].get("expected_sha256")
            if expected and r["model_sha256"] != expected:
                raise ComparisonBlockedError(
                    STATUS_SAFETY,
                    f"Teacher-anchored checkpoint hash changed for seed {r['seed']}",
                )

        # Train flat baselines.
        flat_summaries = run_flat_baselines(
            out_root=out_dir,
            X_train=train.X_flat,
            y_train=train.y,
            X_val=val.X_flat,
            y_val=val.y,
            sequence_id=val.sequence_id,
            user=val.user,
            device=device,
            seeds=SEEDS,
        )

        # Attach probabilities for bootstrap from saved npz files.
        for s in flat_summaries:
            pred = out_dir / f"{s['model'].replace('_flat260','')}_seed{s['seed']}" / "validation_predictions.npz"
            # map model names to folder prefixes
            folder_map = {
                "logistic_regression_flat260": "logistic_regression",
                "mlp_flat260": "mlp",
                "random_forest_flat260": "random_forest",
                "xgboost_flat260": "xgboost",
            }
            pred = out_dir / f"{folder_map[s['model']]}_seed{s['seed']}" / "validation_predictions.npz"
            z = np.load(pred, allow_pickle=True)
            s["y_proba"] = z["y_proba"].astype(np.float64)

        panel_a = flat_summaries + al_rows + ta_rows
        seed_df = seed_metrics_table(panel_a)
        seed_df.to_csv(out_dir / "same_information_seed_metrics.csv", index=False)

        summary_a = model_summary_table(seed_df)
        summary_a.to_csv(out_dir / "same_information_model_summary.csv", index=False)

        thr_rows = seed_df[
            ["model", "seed", "threshold", "precision", "recall", "f1", "fp", "fn", "pr_auc"]
        ].copy()
        thr_rows["threshold_source"] = "validation_max_f1"
        thr_rows["comparison_label"] = "r5.2 validation comparison"
        thr_rows.to_csv(out_dir / "same_information_thresholds.csv", index=False)

        seed_df[
            ["model", "seed", "training_duration_sec", "device", "peak_gpu_memory_mb"]
        ].to_csv(out_dir / "same_information_training_cost.csv", index=False)
        seed_df[["model", "seed", "inference_duration_sec"]].to_csv(
            out_dir / "same_information_inference_cost.csv", index=False
        )
        seed_df[["model", "seed", "model_size_bytes", "n_parameters"]].to_csv(
            out_dir / "same_information_model_complexity.csv", index=False
        )

        eng_seed = load_engineered_seed_details(repo_root)
        eng_ctx = load_engineered_context(repo_root)
        if not eng_seed.empty:
            eng_seed.to_csv(out_dir / "engineered_feature_context.csv", index=False)
            eng_for_pair = model_summary_table(
                eng_seed.rename(columns={})  # already seed-level with required cols
                .assign(
                    roc_auc=eng_seed.get("roc_auc", np.nan),
                    model_size_bytes=np.nan,
                    n_parameters=np.nan,
                    peak_gpu_memory_mb=np.nan,
                    inference_duration_sec=eng_seed.get("inference_duration_sec", np.nan),
                    comparison_label="r5.2 validation comparison",
                )
            )
            # Rebuild eng seed metrics-compatible frame
            eng_metrics = pd.DataFrame(
                {
                    "model": eng_seed["model"],
                    "panel": "B",
                    "seed": eng_seed["seed"],
                    "input_representation": eng_seed["input_representation"],
                    "pr_auc": eng_seed["pr_auc"],
                    "precision": eng_seed["precision"],
                    "recall": eng_seed["recall"],
                    "f1": eng_seed["f1"],
                    "fp": eng_seed["fp"],
                    "fn": eng_seed["fn"],
                    "roc_auc": eng_seed.get("roc_auc", np.nan),
                    "threshold": eng_seed["threshold"],
                    "training_duration_sec": eng_seed.get("training_duration_sec", np.nan),
                    "inference_duration_sec": eng_seed.get("inference_duration_sec", np.nan),
                    "peak_gpu_memory_mb": np.nan,
                    "model_size_bytes": np.nan,
                    "n_parameters": np.nan,
                    "device": "saved_evidence",
                    "retrained": False,
                    "comparison_label": "r5.2 validation comparison",
                }
            )
            eng_for_pair = model_summary_table(eng_metrics)
        else:
            eng_ctx.to_csv(out_dir / "engineered_feature_context.csv", index=False)
            eng_for_pair = pd.DataFrame()

        combined_summary = pd.concat([summary_a, eng_for_pair], ignore_index=True) if not eng_for_pair.empty else summary_a
        pairwise = pairwise_comparisons(combined_summary)
        pairwise.to_csv(out_dir / "same_information_pairwise_comparisons.csv", index=False)

        bootstrap = build_bootstrap_table(y_val=val.y, users=val.user, panel_a_rows=panel_a)
        bootstrap.to_csv(out_dir / "same_information_bootstrap_comparisons.csv", index=False)

        claims = claim_register(pairwise, bootstrap)
        claims.to_csv(out_dir / "same_information_claim_register.csv", index=False)

        fig_dir = out_dir / "figures"
        figure1_same_information(summary_a, fig_dir)
        figure2_engineered_context(summary_a, eng_seed if not eng_seed.empty else eng_ctx, fig_dir)
        figure3_perf_vs_train_cost(seed_df, fig_dir)
        figure4_perf_vs_complexity(seed_df, fig_dir)

        write_reports(
            out_dir=out_dir,
            status=STATUS_COMPLETE if not gpu_blocked else STATUS_COMPLETE,
            summary_a=summary_a,
            engineered=eng_seed if not eng_seed.empty else eng_ctx,
            pairwise=pairwise,
            bootstrap=bootstrap,
            config=config,
            manifest=manifest,
        )

        # Environment metadata
        env_meta = {
            "software_versions": software_versions(),
            "platform": config.get("platform"),
            "device_used_for_mlp": str(device),
            "gpu_blocked_at_launch": gpu_blocked,
            "output_namespace": str(OUTPUT_REL),
        }
        write_json_atomic(out_dir / "environment_metadata.json", env_meta)

        # Model file hashes inventory
        hash_rows = []
        for p in sorted(out_dir.glob("**/model.*")):
            hash_rows.append({"path": str(p.relative_to(out_dir)).replace("\\", "/"), "sha256": sha256_file(p)})
        pd.DataFrame(hash_rows).to_csv(out_dir / "baseline_model_hashes.csv", index=False)

        status = STATUS_COMPLETE
        # If GPU was blocked we still completed on CPU; only use prepared_gpu_blocked when we could not run.
        # Spec: use prepared_gpu_blocked if experiment cannot safely start. We started safely on CPU.
        manifest.update(
            {
                "status": status,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
                "n_panel_a_seed_rows": int(len(seed_df)),
                "flat_train_hash": train.flat_hash,
                "flat_val_hash": val.flat_hash,
                "seq_train_hash": train.seq_hash,
                "seq_val_hash": val.seq_hash,
                "attention_linear_retrained": False,
                "teacher_anchored_retrained": False,
                "test_accessed": False,
            }
        )
        write_json_atomic(out_dir / "same_information_manifest.json", manifest)
        write_json_atomic(out_dir / "completion_status.json", {"status": status})
        _flush(f"STATUS={status}")
        return {"status": status, "output_dir": str(out_dir), "manifest": manifest}

    except ComparisonBlockedError as exc:
        status = exc.status
        manifest.update({"status": status, "error": str(exc), "traceback": traceback.format_exc()})
        write_json_atomic(out_dir / "same_information_manifest.json", manifest)
        write_json_atomic(out_dir / "completion_status.json", {"status": status})
        write_reports(
            out_dir=out_dir,
            status=status,
            summary_a=pd.DataFrame(),
            engineered=pd.DataFrame(),
            pairwise=pd.DataFrame(),
            bootstrap=pd.DataFrame(),
            config=config,
            manifest=manifest,
        )
        _flush(f"STATUS={status}")
        return {"status": status, "output_dir": str(out_dir), "manifest": manifest}
    except ProtectedDataAccessError as exc:
        status = STATUS_SAFETY
        manifest.update({"status": status, "error": str(exc), "traceback": traceback.format_exc()})
        write_json_atomic(out_dir / "same_information_manifest.json", manifest)
        write_json_atomic(out_dir / "completion_status.json", {"status": status})
        _flush(f"STATUS={status}")
        return {"status": status, "output_dir": str(out_dir), "manifest": manifest}
    except Exception as exc:  # noqa: BLE001
        status = STATUS_INCOMPLETE
        manifest.update({"status": status, "error": str(exc), "traceback": traceback.format_exc()})
        write_json_atomic(out_dir / "same_information_manifest.json", manifest)
        write_json_atomic(out_dir / "completion_status.json", {"status": status})
        _flush(f"STATUS={status}: {exc}")
        raise
