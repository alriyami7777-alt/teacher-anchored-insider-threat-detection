#!/usr/bin/env python3
"""
Consolidate and lock Objective 2 validation results before test evaluation.

Reads jointly fine-tuned integrated runs (stage11_D_pretrained_seed*_best),
their attention-linear pretraining directories, and Stage 1.1 ablation pilots.
Does not modify checkpoints or evaluate the test split.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

INTEGRATED_DIRS = {
    42: "stage11_D_pretrained_seed42_best",
    52: "stage11_D_pretrained_seed52_best",
    62: "stage11_D_pretrained_seed62_best",
}

PRETRAIN_DIRS = {
    42: "stage11_A_attn_linear",
    52: "pretrain_attn_linear_seed52",
    62: "pretrain_attn_linear_seed62",
}

ABLATION_SPECS = [
    {
        "ablation_id": "A",
        "label": "attention + linear",
        "dir_name": "stage11_A_attn_linear",
        "classification_head": "linear",
        "temporal_aggregation": "attention",
        "jointly_finetuned": False,
    },
    {
        "ablation_id": "B",
        "label": "last + soft forest",
        "dir_name": "stage11_B_last_softforest",
        "classification_head": "soft_forest",
        "temporal_aggregation": "last",
        "jointly_finetuned": False,
    },
    {
        "ablation_id": "C",
        "label": "attention + soft forest (pw×0.25, lr=3e-4)",
        "dir_name": "stage11_C_attn_sf_pw025_lr3e4",
        "classification_head": "soft_forest",
        "temporal_aggregation": "attention",
        "jointly_finetuned": False,
    },
    {
        "ablation_id": "D",
        "label": "pretrained encoder + attention + soft forest (joint fine-tune)",
        "dir_name": None,
        "classification_head": "soft_forest",
        "temporal_aggregation": "attention",
        "jointly_finetuned": True,
    },
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, rel: str | Path) -> Path:
    path = Path(rel)
    return path if path.is_absolute() else (root / path).resolve()


def read_run_metrics(run_dir: Path) -> dict:
    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    thr = json.loads((run_dir / "threshold.json").read_text(encoding="utf-8"))
    hist = pd.read_csv(run_dir / "training_history.csv")
    diag = pd.read_csv(run_dir / "validation_diagnostics.csv")
    vm = thr["validation_metrics"]
    best_epoch = int(thr["best_epoch"])
    diag_row = diag.loc[diag["epoch"] == best_epoch]
    if diag_row.empty:
        diag_row = diag.iloc[[-1]]
    d = diag_row.iloc[0]
    ckpt = run_dir / "best.pt"
    return {
        "seed": int(cfg.get("seed", -1)),
        "best_epoch": best_epoch,
        "selected_threshold": float(thr["selected_threshold"]),
        "validation_pr_auc": float(vm["pr_auc"]),
        "validation_precision": float(vm["precision"]),
        "validation_recall": float(vm["recall"]),
        "validation_f1": float(vm["f1"]),
        "validation_fp": int(vm["fp"]),
        "validation_fn": int(vm["fn"]),
        "validation_tp": int(vm["tp"]),
        "validation_tn": int(vm["tn"]),
        "validation_fpr": float(vm["fpr"]),
        "validation_fnr": float(vm["fnr"]),
        "training_time_sec": float(hist["epoch_time_sec"].sum()),
        "checkpoint_path": str(ckpt.resolve()),
        "encoder_checkpoint_path": cfg.get("encoder_checkpoint"),
        "attention_mean_entropy": float(d.get("attention_mean_entropy", float("nan"))),
        "attention_mean_max_weight": float(d.get("attention_mean_max_weight", float("nan"))),
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
        "run_dir": str(run_dir.resolve()),
    }


def summarise_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for col in cols:
        s = df[col].astype(float)
        rows.append(
            {
                "metric": col,
                "mean": float(s.mean()),
                "std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
                "min": float(s.min()),
                "max": float(s.max()),
                "n_seeds": int(len(s)),
            }
        )
    return pd.DataFrame(rows)


def build_locked_configuration(seed_rows: pd.DataFrame) -> dict:
    """Lock hyperparameters shared across integrated seeds (test not evaluated)."""
    ref = seed_rows.iloc[0].to_dict()
    return {
        "status": "locked_before_test_evaluation",
        "locked_at": datetime.now().isoformat(timespec="seconds"),
        "model": "SequenceEnsembleModel",
        "stage": "1.1 joint fine-tune (ablation D)",
        "classification_head": "soft_forest",
        "temporal_aggregation": "attention",
        "hidden_size": int(ref["hidden_size"]),
        "dropout": float(ref["dropout"]),
        "attention_dim": int(ref["attention_dim"]),
        "n_trees": int(ref["n_trees"]),
        "tree_depth": int(ref["tree_depth"]),
        "learning_rate": float(ref["learning_rate"]),
        "weight_decay": float(ref["weight_decay"]),
        "batch_size": int(ref["batch_size"]),
        "max_epochs": int(ref["max_epochs"]),
        "patience": int(ref["patience"]),
        "base_pos_weight": float(ref["base_pos_weight"]),
        "pos_weight_multiplier": float(ref["pos_weight_multiplier"]),
        "effective_pos_weight": float(ref["effective_pos_weight"]),
        "early_stopping_metric": "validation_pr_auc",
        "threshold_selection": "maximum_validation_f1",
        "seeds": sorted(int(s) for s in seed_rows["seed"].tolist()),
        "integrated_checkpoint_dirs": {
            str(int(r["seed"])): r["checkpoint_path"] for _, r in seed_rows.iterrows()
        },
        "pretrain_checkpoint_dirs": {
            str(seed): str(
                (repo_root() / "outputs/baselines/sequence_ensemble" / PRETRAIN_DIRS[seed] / "best.pt").resolve()
            )
            for seed in PRETRAIN_DIRS
        },
        "test_evaluated": False,
        "note": (
            "Jointly fine-tuned checkpoints are frozen. Test evaluation requires "
            "explicit separate command with --evaluate-test."
        ),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Consolidate Objective 2 validation results.")
    p.add_argument(
        "--ensemble-root",
        default="outputs/baselines/sequence_ensemble",
        help="Root directory containing integrated and ablation runs.",
    )
    p.add_argument(
        "--output-dir",
        default="outputs/objective2",
        help="Directory for consolidated CSV/JSON artefacts.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    ensemble_root = resolve(root, args.ensemble_root)
    out_dir = resolve(root, args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_rows: list[dict] = []
    pretrain_rows: list[dict] = []

    for seed, dirname in INTEGRATED_DIRS.items():
        run_dir = ensemble_root / dirname
        if not run_dir.exists():
            raise FileNotFoundError(f"Missing integrated run: {run_dir}")
        row = read_run_metrics(run_dir)
        row["model_stage"] = "integrated_joint_finetune"
        row["pretrain_dir"] = str((ensemble_root / PRETRAIN_DIRS[seed]).resolve())
        seed_rows.append(row)

        pre_dir = ensemble_root / PRETRAIN_DIRS[seed]
        if pre_dir.exists():
            pr = read_run_metrics(pre_dir)
            pr["model_stage"] = "pretrain_attn_linear"
            pr["integrated_dir"] = str(run_dir.resolve())
            pretrain_rows.append(pr)

    seed_df = pd.DataFrame(seed_rows)
    seed_csv = out_dir / "sequence_ensemble_validation_seed_results.csv"
    seed_df.to_csv(seed_csv, index=False)

    summary_cols = [
        "validation_pr_auc",
        "validation_precision",
        "validation_recall",
        "validation_f1",
        "validation_fp",
        "validation_fn",
        "training_time_sec",
        "attention_mean_entropy",
        "selected_threshold",
        "best_epoch",
    ]
    summary_df = summarise_numeric(seed_df, summary_cols)
    summary_csv = out_dir / "sequence_ensemble_validation_summary.csv"
    summary_df.to_csv(summary_csv, index=False)

    locked = build_locked_configuration(seed_df)
    locked_path = out_dir / "sequence_ensemble_locked_configuration.json"
    locked_path.write_text(json.dumps(locked, indent=2), encoding="utf-8")

    ablation_rows: list[dict] = []
    for spec in ABLATION_SPECS:
        if spec["jointly_finetuned"]:
            for _, r in seed_df.iterrows():
                ablation_rows.append(
                    {
                        "ablation_id": spec["ablation_id"],
                        "ablation_label": spec["label"],
                        "seed": int(r["seed"]),
                        "classification_head": spec["classification_head"],
                        "temporal_aggregation": spec["temporal_aggregation"],
                        "validation_pr_auc": r["validation_pr_auc"],
                        "validation_f1": r["validation_f1"],
                        "validation_precision": r["validation_precision"],
                        "validation_recall": r["validation_recall"],
                        "validation_fp": r["validation_fp"],
                        "validation_fn": r["validation_fn"],
                        "selected_threshold": r["selected_threshold"],
                        "run_dir": r["run_dir"],
                    }
                )
        else:
            run_dir = ensemble_root / spec["dir_name"]
            if not run_dir.exists():
                continue
            m = read_run_metrics(run_dir)
            ablation_rows.append(
                {
                    "ablation_id": spec["ablation_id"],
                    "ablation_label": spec["label"],
                    "seed": m["seed"],
                    "classification_head": spec["classification_head"],
                    "temporal_aggregation": spec["temporal_aggregation"],
                    "validation_pr_auc": m["validation_pr_auc"],
                    "validation_f1": m["validation_f1"],
                    "validation_precision": m["validation_precision"],
                    "validation_recall": m["validation_recall"],
                    "validation_fp": m["validation_fp"],
                    "validation_fn": m["validation_fn"],
                    "selected_threshold": m["selected_threshold"],
                    "run_dir": m["run_dir"],
                }
            )

    ablation_df = pd.DataFrame(ablation_rows)
    ablation_csv = out_dir / "sequence_ensemble_ablation_summary.csv"
    ablation_df.to_csv(ablation_csv, index=False)

    if pretrain_rows:
        pre_df = pd.DataFrame(pretrain_rows)
        pre_df.to_csv(out_dir / "sequence_ensemble_pretrain_validation.csv", index=False)

    print("=" * 72)
    print("OBJECTIVE 2 VALIDATION CONSOLIDATION (test not evaluated)")
    print("=" * 72)
    print(seed_df[
        ["seed", "best_epoch", "selected_threshold", "validation_pr_auc",
         "validation_f1", "validation_fp", "validation_fn", "attention_mean_entropy"]
    ].to_string(index=False))
    print("\nCross-seed summary:")
    print(summary_df.to_string(index=False))
    print("\nGenerated files:")
    for p in [seed_csv, summary_csv, locked_path, ablation_csv]:
        print(f"  {p}")


if __name__ == "__main__":
    main()
