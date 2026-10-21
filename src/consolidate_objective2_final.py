#!/usr/bin/env python3
"""
Final Objective 2 validation consolidation and locked manifest.

Reads completed validation outputs for seeds 42/52/62 across primary models
and clearly labelled reference baselines. Does not retrain, retune, or evaluate
the test set. Does not overwrite existing sequence_ensemble_* lock artefacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from objective2_locked_common import (  # noqa: E402
    DISPLAY_NAMES,
    INPUT_REPRESENTATION,
    JOINT_DIRS,
    MODEL_FAMILIES,
    PRETRAIN_DIRS,
    PRIMARY_MODEL_IDS,
    REFERENCE_MODEL_IDS,
    SEEDS,
    SUMMARY_METRIC_COLS,
    default_output_dir,
    hash_artefact,
    load_json,
    paired_seed_differences,
    rel_to_root,
    repo_root,
    resolve,
    summarise_numeric,
    write_json,
)


def _nan() -> float:
    return float("nan")


def _attention_entropy(run_dir: Path, best_epoch: int | None) -> float:
    diag_path = run_dir / "validation_diagnostics.csv"
    if not diag_path.exists():
        return _nan()
    diag = pd.read_csv(diag_path)
    if best_epoch is not None and "epoch" in diag.columns:
        rows = diag.loc[diag["epoch"] == best_epoch]
        if not rows.empty:
            return float(rows.iloc[0].get("attention_mean_entropy", _nan()))
    if "attention_mean_entropy" in diag.columns and not diag.empty:
        return float(diag.iloc[-1]["attention_mean_entropy"])
    return _nan()


def _base_row(model_id: str, seed: int | None, is_reference: bool) -> dict[str, Any]:
    return {
        "model_name": DISPLAY_NAMES[model_id],
        "model_id": model_id,
        "model_family": MODEL_FAMILIES[model_id],
        "is_reference_baseline": bool(is_reference),
        "input_representation": INPUT_REPRESENTATION[model_id],
        "seed": seed,
        "best_epoch": None,
        "validation_threshold": _nan(),
        "validation_pr_auc": _nan(),
        "validation_precision": _nan(),
        "validation_recall": _nan(),
        "validation_f1": _nan(),
        "validation_fp": _nan(),
        "validation_fn": _nan(),
        "validation_tp": _nan(),
        "validation_tn": _nan(),
        "training_time_sec": _nan(),
        "inference_time_sec": _nan(),
        "checkpoint_path": "",
        "encoder_checkpoint_path": "",
        "classifier_path": "",
        "config_path": "",
        "threshold_path": "",
        "run_dir": "",
        "hyperparameters_json": "{}",
        "attention_entropy": _nan(),
        "include_in_locked_test_evaluation": model_id in PRIMARY_MODEL_IDS,
    }


def collect_bilstm(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        run_dir = root / "outputs" / "objective2" / f"bilstm_seed{seed}"
        metrics = pd.read_csv(run_dir / "validation_metrics.csv").iloc[0]
        thr = load_json(run_dir / "threshold.json")
        cfg = load_json(run_dir / "config.json")
        row = _base_row("standalone_bilstm", seed, False)
        row.update(
            {
                "best_epoch": int(metrics["best_epoch"]),
                "validation_threshold": float(thr["selected_threshold"]),
                "validation_pr_auc": float(metrics["pr_auc"]),
                "validation_precision": float(metrics["precision"]),
                "validation_recall": float(metrics["recall"]),
                "validation_f1": float(metrics["f1"]),
                "validation_fp": int(metrics["fp"]),
                "validation_fn": int(metrics["fn"]),
                "validation_tp": int(metrics["tp"]),
                "validation_tn": int(metrics["tn"]),
                "training_time_sec": float(metrics["training_time_sec"]),
                "checkpoint_path": str((run_dir / "best.pt").resolve()),
                "config_path": str((run_dir / "config.json").resolve()),
                "threshold_path": str((run_dir / "threshold.json").resolve()),
                "run_dir": str(run_dir.resolve()),
                "hyperparameters_json": json.dumps(
                    {
                        "architecture": cfg.get("architecture"),
                        "hidden_size": cfg.get("architecture", {}).get("hidden_size", 64),
                        "dropout": cfg.get("architecture", {}).get("dropout", 0.2),
                        "batch_size": cfg.get("batch_size"),
                        "learning_rate": cfg.get("learning_rate"),
                        "max_epochs": cfg.get("max_epochs"),
                        "patience": cfg.get("patience"),
                        "pos_weight_train": cfg.get("pos_weight_train"),
                        "early_stopping_metric": cfg.get("early_stopping_metric"),
                        "threshold_selection": cfg.get("threshold_selection"),
                    },
                    sort_keys=True,
                ),
            }
        )
        rows.append(row)
    return rows


def collect_attention_linear(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ens = root / "outputs" / "baselines" / "sequence_ensemble"
    for seed in SEEDS:
        run_dir = ens / PRETRAIN_DIRS[seed]
        thr = load_json(run_dir / "threshold.json")
        cfg = load_json(run_dir / "config.json")
        vm = thr["validation_metrics"]
        hist = pd.read_csv(run_dir / "training_history.csv")
        best_epoch = int(thr["best_epoch"])
        row = _base_row("attention_linear", seed, False)
        row.update(
            {
                "best_epoch": best_epoch,
                "validation_threshold": float(thr["selected_threshold"]),
                "validation_pr_auc": float(vm["pr_auc"]),
                "validation_precision": float(vm["precision"]),
                "validation_recall": float(vm["recall"]),
                "validation_f1": float(vm["f1"]),
                "validation_fp": int(vm["fp"]),
                "validation_fn": int(vm["fn"]),
                "validation_tp": int(vm["tp"]),
                "validation_tn": int(vm["tn"]),
                "training_time_sec": float(hist["epoch_time_sec"].sum())
                if "epoch_time_sec" in hist.columns
                else _nan(),
                "checkpoint_path": str((run_dir / "best.pt").resolve()),
                "config_path": str((run_dir / "config.json").resolve()),
                "threshold_path": str((run_dir / "threshold.json").resolve()),
                "run_dir": str(run_dir.resolve()),
                "attention_entropy": _attention_entropy(run_dir, best_epoch),
                "hyperparameters_json": json.dumps(
                    {
                        "classification_head": cfg.get("classification_head"),
                        "temporal_aggregation": cfg.get("temporal_aggregation"),
                        "hidden_size": cfg.get("hidden_size"),
                        "dropout": cfg.get("dropout"),
                        "attention_dim": cfg.get("attention_dim"),
                        "learning_rate": cfg.get("learning_rate"),
                        "batch_size": cfg.get("batch_size"),
                        "max_epochs": cfg.get("max_epochs"),
                        "patience": cfg.get("patience"),
                        "effective_pos_weight": cfg.get("effective_pos_weight"),
                    },
                    sort_keys=True,
                ),
            }
        )
        rows.append(row)
    return rows


def collect_fragmented(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        parent = root / "outputs" / "objective2" / f"fragmented_hybrid_seed{seed}"
        parent_cfg = load_json(parent / "config.json")
        summary = load_json(parent / "validation_summary.json")
        elapsed = float(summary.get("elapsed_sec", _nan()))
        for clf_key, model_id, clf_dir_name, clf_file in (
            ("random_forest", "fragmented_bilstm_rf", "random_forest", "model.joblib"),
            ("xgboost", "fragmented_bilstm_xgboost", "xgboost", "model.json"),
        ):
            clf_dir = parent / clf_dir_name
            thr = load_json(clf_dir / "threshold.json")
            cfg = load_json(clf_dir / "config.json")
            vm = thr["validation_metrics"]
            row = _base_row(model_id, seed, False)
            row.update(
                {
                    "best_epoch": None,
                    "validation_threshold": float(thr["selected_threshold"]),
                    "validation_pr_auc": float(vm["pr_auc"]),
                    "validation_precision": float(vm["precision"]),
                    "validation_recall": float(vm["recall"]),
                    "validation_f1": float(vm["f1"]),
                    "validation_fp": int(vm["fp"]),
                    "validation_fn": int(vm["fn"]),
                    "validation_tp": int(vm["tp"]),
                    "validation_tn": int(vm["tn"]),
                    "training_time_sec": elapsed,
                    "checkpoint_path": "",
                    "encoder_checkpoint_path": str(
                        Path(parent_cfg["encoder_checkpoint"]).resolve()
                    ),
                    "classifier_path": str((clf_dir / clf_file).resolve()),
                    "config_path": str((clf_dir / "config.json").resolve()),
                    "threshold_path": str((clf_dir / "threshold.json").resolve()),
                    "run_dir": str(clf_dir.resolve()),
                    "hyperparameters_json": json.dumps(
                        {
                            "classifier": clf_key,
                            "model_hyperparameters": cfg.get("model_hyperparameters"),
                            "encoder_checkpoint": parent_cfg.get("encoder_checkpoint"),
                            "encoder_frozen": parent_cfg.get("encoder_frozen"),
                            "representation_dim": parent_cfg.get("representation_dim"),
                            "threshold_selection": cfg.get("threshold_selection"),
                        },
                        sort_keys=True,
                    ),
                }
            )
            rows.append(row)
    return rows


def collect_joint(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ens = root / "outputs" / "baselines" / "sequence_ensemble"
    for seed in SEEDS:
        run_dir = ens / JOINT_DIRS[seed]
        thr = load_json(run_dir / "threshold.json")
        cfg = load_json(run_dir / "config.json")
        vm = thr["validation_metrics"]
        hist = pd.read_csv(run_dir / "training_history.csv")
        best_epoch = int(thr["best_epoch"])
        row = _base_row("joint_bilstm_attention_soft_forest", seed, False)
        enc = cfg.get("encoder_checkpoint") or ""
        row.update(
            {
                "best_epoch": best_epoch,
                "validation_threshold": float(thr["selected_threshold"]),
                "validation_pr_auc": float(vm["pr_auc"]),
                "validation_precision": float(vm["precision"]),
                "validation_recall": float(vm["recall"]),
                "validation_f1": float(vm["f1"]),
                "validation_fp": int(vm["fp"]),
                "validation_fn": int(vm["fn"]),
                "validation_tp": int(vm["tp"]),
                "validation_tn": int(vm["tn"]),
                "training_time_sec": float(hist["epoch_time_sec"].sum())
                if "epoch_time_sec" in hist.columns
                else _nan(),
                "checkpoint_path": str((run_dir / "best.pt").resolve()),
                "encoder_checkpoint_path": str(Path(enc).resolve()) if enc else "",
                "config_path": str((run_dir / "config.json").resolve()),
                "threshold_path": str((run_dir / "threshold.json").resolve()),
                "run_dir": str(run_dir.resolve()),
                "attention_entropy": _attention_entropy(run_dir, best_epoch),
                "hyperparameters_json": json.dumps(
                    {
                        "classification_head": cfg.get("classification_head"),
                        "temporal_aggregation": cfg.get("temporal_aggregation"),
                        "hidden_size": cfg.get("hidden_size"),
                        "dropout": cfg.get("dropout"),
                        "attention_dim": cfg.get("attention_dim"),
                        "n_trees": cfg.get("n_trees"),
                        "tree_depth": cfg.get("tree_depth"),
                        "learning_rate": cfg.get("learning_rate"),
                        "weight_decay": cfg.get("weight_decay"),
                        "batch_size": cfg.get("batch_size"),
                        "max_epochs": cfg.get("max_epochs"),
                        "patience": cfg.get("patience"),
                        "base_pos_weight": cfg.get("base_pos_weight"),
                        "pos_weight_multiplier": cfg.get("pos_weight_multiplier"),
                        "effective_pos_weight": cfg.get("effective_pos_weight"),
                        "encoder_checkpoint": enc,
                    },
                    sort_keys=True,
                ),
            }
        )
        rows.append(row)
    return rows


def collect_soft_forest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        run_dir = root / "outputs" / "baselines" / "soft_decision_forest" / f"seed_{seed}"
        metrics = pd.read_csv(run_dir / "sdf_T20_s1_metrics.csv")
        val = metrics[metrics["split"] == "validation"].iloc[0]
        thr = load_json(run_dir / "sdf_T20_s1_threshold.json")
        cfg = load_json(run_dir / "sdf_T20_s1_config.json")
        # Prefer metrics CSV training time from test row if present.
        train_time = _nan()
        test_rows = metrics[metrics["split"] == "test"]
        if not test_rows.empty and pd.notna(test_rows.iloc[0].get("training_time_sec")):
            train_time = float(test_rows.iloc[0]["training_time_sec"])
        elif "training_time_sec" in cfg:
            train_time = float(cfg["training_time_sec"])
        infer = _nan()
        if not test_rows.empty and pd.notna(test_rows.iloc[0].get("test_inference_time_sec")):
            infer = float(test_rows.iloc[0]["test_inference_time_sec"])
        best_epoch = None
        if not test_rows.empty and pd.notna(test_rows.iloc[0].get("best_epoch")):
            best_epoch = int(test_rows.iloc[0]["best_epoch"])
        elif "best_epoch" in cfg:
            best_epoch = int(cfg["best_epoch"])
        row = _base_row("standalone_soft_forest", seed, True)
        row.update(
            {
                "best_epoch": best_epoch,
                "validation_threshold": float(thr["selected_threshold"]),
                "validation_pr_auc": float(val["pr_auc"]),
                "validation_precision": float(val["precision"]),
                "validation_recall": float(val["recall"]),
                "validation_f1": float(val["f1"]),
                "validation_fp": int(val["fp"]),
                "validation_fn": int(val["fn"]),
                "validation_tp": int(val["tp"]),
                "validation_tn": int(val["tn"]),
                "training_time_sec": train_time,
                "inference_time_sec": infer,
                "checkpoint_path": str((run_dir / "sdf_T20_s1_checkpoint.pt").resolve()),
                "config_path": str((run_dir / "sdf_T20_s1_config.json").resolve()),
                "threshold_path": str((run_dir / "sdf_T20_s1_threshold.json").resolve()),
                "run_dir": str(run_dir.resolve()),
                "hyperparameters_json": json.dumps(
                    {
                        "architecture": cfg.get("architecture"),
                        "n_trees": cfg.get("architecture", {}).get("n_trees"),
                        "tree_depth": cfg.get("architecture", {}).get("tree_depth"),
                        "n_features": cfg.get("n_features"),
                        "batch_size": cfg.get("batch_size"),
                        "learning_rate": cfg.get("learning_rate"),
                        "max_epochs": cfg.get("max_epochs"),
                        "early_stopping_patience": cfg.get("early_stopping_patience"),
                        "pos_weight_train": cfg.get("pos_weight_train"),
                    },
                    sort_keys=True,
                ),
            }
        )
        rows.append(row)
    return rows


def collect_classical(root: Path) -> list[dict[str, Any]]:
    metrics = pd.read_csv(root / "outputs" / "baselines" / "r42_T20_s1_baseline_metrics.csv")
    thr_df = pd.read_csv(root / "outputs" / "baselines" / "r42_T20_s1_selected_thresholds.csv")
    cm = pd.read_csv(root / "outputs" / "baselines" / "r42_T20_s1_confusion_matrices.csv")
    rows: list[dict[str, Any]] = []
    mapping = {
        "random_forest": "classical_rf",
        "xgboost": "classical_xgboost",
    }
    for raw_name, model_id in mapping.items():
        val = metrics[(metrics["model"] == raw_name) & (metrics["split"] == "validation")].iloc[0]
        thr_row = thr_df[thr_df["model"] == raw_name].iloc[0]
        cm_row = cm[(cm["model"] == raw_name) & (cm["split"] == "validation")].iloc[0]
        row = _base_row(model_id, None, True)
        row.update(
            {
                "best_epoch": None,
                "validation_threshold": float(thr_row["selected_threshold"]),
                "validation_pr_auc": float(val["pr_auc"]),
                "validation_precision": float(val["precision"]),
                "validation_recall": float(val["recall"]),
                "validation_f1": float(val["f1"]),
                "validation_fp": int(cm_row["fp"]),
                "validation_fn": int(cm_row["fn"]),
                "validation_tp": int(cm_row["tp"]),
                "validation_tn": int(cm_row["tn"]),
                "training_time_sec": float(val["training_time_sec"]),
                "inference_time_sec": float(val["inference_time_sec"]),
                "config_path": str(
                    (root / "outputs" / "baselines" / "r42_T20_s1_selected_thresholds.csv").resolve()
                ),
                "threshold_path": str(
                    (root / "outputs" / "baselines" / "r42_T20_s1_selected_thresholds.csv").resolve()
                ),
                "run_dir": str((root / "outputs" / "baselines").resolve()),
                "hyperparameters_json": json.dumps(
                    {
                        "note": "Single-run classical baseline; hyperparameters locked in run_baseline_evaluation.py",
                        "model": raw_name,
                        "selection_criterion": thr_row["selection_criterion"],
                        "input": "r42_T20_s1_sequence_feature_table.parquet (40 features)",
                    },
                    sort_keys=True,
                ),
                "include_in_locked_test_evaluation": False,
            }
        )
        rows.append(row)
    return rows


def build_manifest_entries(root: Path, comparison: pd.DataFrame) -> dict[str, Any]:
    models: list[dict[str, Any]] = []
    artefacts: list[dict[str, str]] = []
    seen: dict[str, str] = {}

    def add_hash(path_str: str, role: str) -> str | None:
        if not path_str:
            return None
        path = Path(path_str)
        key = str(path.resolve())
        if key in seen:
            return seen[key]
        entry = hash_artefact(root, path, role)
        artefacts.append(entry)
        seen[key] = entry["sha256"]
        return entry["sha256"]

    for _, r in comparison.iterrows():
        model_entry: dict[str, Any] = {
            "model_id": r["model_id"],
            "model_name": r["model_name"],
            "model_family": r["model_family"],
            "is_reference_baseline": bool(r["is_reference_baseline"]),
            "input_representation": r["input_representation"],
            "seed": None if pd.isna(r["seed"]) else int(r["seed"]),
            "best_epoch": None if pd.isna(r["best_epoch"]) else int(r["best_epoch"]),
            "validation_threshold": float(r["validation_threshold"]),
            "validation_pr_auc": float(r["validation_pr_auc"]),
            "validation_precision": float(r["validation_precision"]),
            "validation_recall": float(r["validation_recall"]),
            "validation_f1": float(r["validation_f1"]),
            "validation_fp": int(r["validation_fp"]),
            "validation_fn": int(r["validation_fn"]),
            "training_time_sec": None
            if pd.isna(r["training_time_sec"])
            else float(r["training_time_sec"]),
            "inference_time_sec": None
            if pd.isna(r["inference_time_sec"])
            else float(r["inference_time_sec"]),
            "attention_entropy": None
            if pd.isna(r["attention_entropy"])
            else float(r["attention_entropy"]),
            "hyperparameters": json.loads(r["hyperparameters_json"]),
            "include_in_locked_test_evaluation": bool(r["include_in_locked_test_evaluation"]),
            "paths": {
                "run_dir": rel_to_root(root, Path(r["run_dir"])) if r["run_dir"] else "",
                "checkpoint": rel_to_root(root, Path(r["checkpoint_path"]))
                if r["checkpoint_path"]
                else "",
                "encoder_checkpoint": rel_to_root(root, Path(r["encoder_checkpoint_path"]))
                if r["encoder_checkpoint_path"]
                else "",
                "classifier": rel_to_root(root, Path(r["classifier_path"]))
                if r["classifier_path"]
                else "",
                "config": rel_to_root(root, Path(r["config_path"])) if r["config_path"] else "",
                "threshold": rel_to_root(root, Path(r["threshold_path"]))
                if r["threshold_path"]
                else "",
            },
            "hashes": {},
        }
        for path_str, role in (
            (r["checkpoint_path"], "checkpoint"),
            (r["encoder_checkpoint_path"], "encoder_checkpoint"),
            (r["classifier_path"], "classifier"),
            (r["config_path"], "config"),
            (r["threshold_path"], "threshold"),
        ):
            digest = add_hash(str(path_str), role)
            if digest:
                model_entry["hashes"][role] = digest
        # Fragmented hybrids also need frozen representations for locked test eval.
        if r["model_id"] in {"fragmented_bilstm_rf", "fragmented_bilstm_xgboost"} and not pd.isna(
            r["seed"]
        ):
            seed = int(r["seed"])
            repr_dir = (
                root / "outputs" / "objective2" / f"fragmented_hybrid_seed{seed}" / "representations"
            )
            for name, role in (
                ("test_repr.npy", "test_repr"),
                ("test_y.npy", "test_y"),
                ("validation_repr.npy", "validation_repr"),
            ):
                p = repr_dir / name
                digest = add_hash(str(p), role)
                if digest:
                    model_entry["hashes"][role] = digest
                    model_entry["paths"][role] = rel_to_root(root, p)
        models.append(model_entry)

    return {
        "status": "locked_before_test_evaluation",
        "locked_at": datetime.now().isoformat(timespec="seconds"),
        "test_evaluated": False,
        "seeds": list(SEEDS),
        "primary_models": list(PRIMARY_MODEL_IDS),
        "reference_baselines": list(REFERENCE_MODEL_IDS),
        "display_names": DISPLAY_NAMES,
        "threshold_selection": "maximum_validation_f1",
        "early_stopping_metric": "validation_pr_auc",
        "tensor_dir": "data/processed/tensors",
        "tensor_files": {
            "test": "data/processed/tensors/r42_T20_s1_test.npz",
            "validation": "data/processed/tensors/r42_T20_s1_validation.npz",
        },
        "note": (
            "Validation metrics and artefacts are locked. Test evaluation requires "
            "scripts/evaluate_locked_objective2.py --confirm-test-evaluation. "
            "Reference baselines use a different input representation and are labelled as such."
        ),
        "models": models,
        "artefacts": artefacts,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Final Objective 2 validation consolidation.")
    p.add_argument(
        "--output-dir",
        default="outputs/objective2",
        help="Directory for consolidated Objective 2 artefacts.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite consolidation CSVs/manifest even if present (refuses if test_evaluated).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    out_dir = resolve(root, args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = {
        "comparison": out_dir / "objective2_validation_model_comparison.csv",
        "summary": out_dir / "objective2_validation_model_summary.csv",
        "paired": out_dir / "objective2_paired_seed_differences.csv",
        "manifest": out_dir / "objective2_final_locked_manifest.json",
    }

    if targets["manifest"].exists():
        existing = load_json(targets["manifest"])
        if existing.get("test_evaluated") is True:
            raise SystemExit(
                "Refusing to overwrite locked manifest: test_evaluated is already true."
            )
        if not args.force:
            # Refresh is allowed for pre-test lock updates only with --force when files exist.
            # First creation proceeds; re-runs need --force to avoid accidental overwrite.
            already = [p.name for p in targets.values() if p.exists()]
            if already:
                raise SystemExit(
                    "Consolidation outputs already exist. Re-run with --force to refresh "
                    f"(pre-test only): {', '.join(already)}"
                )

    rows: list[dict[str, Any]] = []
    rows.extend(collect_bilstm(root))
    rows.extend(collect_attention_linear(root))
    rows.extend(collect_fragmented(root))
    rows.extend(collect_joint(root))
    rows.extend(collect_soft_forest(root))
    rows.extend(collect_classical(root))

    comparison = pd.DataFrame(rows)
    comparison = comparison.sort_values(
        ["is_reference_baseline", "model_id", "seed"], kind="mergesort"
    ).reset_index(drop=True)

    summary = summarise_numeric(
        comparison[~comparison["is_reference_baseline"] | (comparison["model_id"] == "standalone_soft_forest")],
        SUMMARY_METRIC_COLS,
        ["model_name", "model_id", "model_family", "is_reference_baseline"],
    )
    # Also summarise classical single-run as n=1 for completeness.
    classical = comparison[comparison["model_id"].isin(["classical_rf", "classical_xgboost"])]
    if not classical.empty:
        summary = pd.concat(
            [
                summary,
                summarise_numeric(
                    classical,
                    SUMMARY_METRIC_COLS,
                    ["model_name", "model_id", "model_family", "is_reference_baseline"],
                ),
            ],
            ignore_index=True,
        )
        summary = summary.drop_duplicates(
            subset=["model_id", "metric"], keep="last"
        ).reset_index(drop=True)

    paired = paired_seed_differences(comparison)

    manifest = build_manifest_entries(root, comparison)

    comparison.to_csv(targets["comparison"], index=False)
    summary.to_csv(targets["summary"], index=False)
    paired.to_csv(targets["paired"], index=False)
    write_json(targets["manifest"], manifest)

    # Hash the consolidation outputs themselves into a sidecar note inside manifest.
    manifest["consolidation_outputs"] = {
        name: hash_artefact(root, path, f"consolidation_{name}")
        for name, path in targets.items()
        if name != "manifest" and path.exists()
    }
    # Re-write with consolidation hashes (manifest hash intentionally excluded).
    write_json(targets["manifest"], manifest)

    print("=" * 72)
    print("OBJECTIVE 2 FINAL VALIDATION CONSOLIDATION (test_evaluated=false)")
    print("=" * 72)
    show_cols = [
        "model_name",
        "seed",
        "validation_pr_auc",
        "validation_f1",
        "validation_fp",
        "validation_fn",
        "validation_threshold",
        "is_reference_baseline",
    ]
    print(comparison[show_cols].to_string(index=False))
    print("\nGenerated files:")
    for p in targets.values():
        print(f"  {p}")
    print(f"\nLocked artefacts hashed: {len(manifest['artefacts'])}")
    print(f"test_evaluated: {manifest['test_evaluated']}")


if __name__ == "__main__":
    main()
