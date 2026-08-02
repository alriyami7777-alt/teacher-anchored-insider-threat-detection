#!/usr/bin/env python3
"""Read-only Objective 2 architecture-candidate closure audit.

Builds manifests, comparison tables, pairwise differences, figures and reports
from existing experiment artefacts. Does not train models, rewrite checkpoints,
or access locked r5.2 test tensors.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass, asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_fscore_support,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "objective2" / "architecture_candidate_closure"
PROTOCOL_ID = "r42_T20_s1_frozen_encoder_head_val_maxf1"
BRANCH = "main"
HEAD = "83e5bd4cee0b41b991afe7498cef643c54d7c1f1"

MANIFEST_FIELDS = [
    "candidate_name",
    "candidate_family",
    "experiment_path",
    "checkpoint_path",
    "dataset_version",
    "train_partition",
    "validation_partition",
    "evaluation_partition",
    "seed",
    "encoder_type",
    "encoder_checkpoint",
    "encoder_frozen_or_trainable",
    "representation_source",
    "classifier_head",
    "loss_function",
    "threshold_selection_method",
    "selected_threshold",
    "PR_AUC",
    "precision",
    "recall",
    "F1",
    "FP",
    "FN",
    "calibration_metrics_available",
    "protocol_identifier",
    "evidence_source",
    "comparability_status",
    "exclusion_reason",
    "notes",
]


def nr(value: Any) -> str:
    if value is None or value == "":
        return "not_recorded"
    return str(value)


def f4(x: float | None) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return ""
    return f"{x:.6f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def blank_row(**kwargs: Any) -> dict[str, Any]:
    row = {k: "" for k in MANIFEST_FIELDS}
    row.update(kwargs)
    return row


def mean_std(vals: list[float]) -> tuple[float, float]:
    if not vals:
        return float("nan"), float("nan")
    if len(vals) == 1:
        return vals[0], 0.0
    return statistics.mean(vals), statistics.stdev(vals)


@dataclass
class SeedResult:
    candidate_name: str
    candidate_family: str
    seed: int
    pr_auc: float
    precision: float
    recall: float
    f1: float
    fp: float
    fn: float
    threshold: float
    protocol_identifier: str
    experiment_path: str
    checkpoint_path: str
    encoder_checkpoint: str
    encoder_status: str
    notes: str = ""


def collect_v3_node_main() -> tuple[list[dict[str, Any]], list[SeedResult]]:
    """Attention-linear + ODST (+ diagnostic NODE variants) from v3_node."""
    runs = {
        42: ROOT / "outputs/v3_node/seed42_full_20260723_095912/seed42_full_20260723_095916",
        52: ROOT / "outputs/v3_node/seed52_full_20260723_101933/seed52_full_20260723_101936",
        62: ROOT / "outputs/v3_node/seed62_full_20260723_102938/seed62_full_20260723_102942",
    }
    encoder_by_seed = {
        42: "outputs/baselines/sequence_ensemble/stage11_A_attn_linear/best.pt",
        52: "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed52/best.pt",
        62: "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed62/best.pt",
    }
    main_variants = {
        "attention_linear_reference": (
            "bi_lstm_attention_linear",
            "attention_linear",
            "linear",
            "main_comparison_valid",
            "",
        ),
        "sparsemax_sigmoid_odst": (
            "sparsemax_sigmoid_odst",
            "odst",
            "sparsemax_sigmoid_odst",
            "main_comparison_valid",
            "",
        ),
    }
    diagnostic_variants = {
        "canonical_entmax15_node": (
            "canonical_entmax15_node",
            "node",
            "entmax15_entmoid15_node",
            "diagnostic_only",
            "NODE ablation under same frozen protocol; not the selected ODST head.",
        ),
        "dense_linear_readout_node": (
            "dense_linear_readout_node",
            "node_ablation",
            "dense_linear_readout_node",
            "diagnostic_only",
            "Dense linear readout NODE ablation; diagnostic development only.",
        ),
    }
    manifest: list[dict[str, Any]] = []
    main_results: list[SeedResult] = []

    for seed, folder in runs.items():
        for variant, meta in {**main_variants, **diagnostic_variants}.items():
            name, family, head, status, excl = meta
            run_dir = folder / f"{variant}_seed{seed}"
            summary = load_json(run_dir / "summary.json")
            thr = load_json(run_dir / "threshold.json")
            vm = summary.get("validation_metrics") or {}
            enc_report = load_json(run_dir / "encoder_load_report.json")
            ckpt = run_dir / "best.pt"
            row = blank_row(
                candidate_name=name,
                candidate_family=family,
                experiment_path=str(run_dir.relative_to(ROOT)).replace("\\", "/"),
                checkpoint_path=str(ckpt.relative_to(ROOT)).replace("\\", "/")
                if ckpt.exists()
                else "not_recorded",
                dataset_version="CERT r4.2",
                train_partition="r42_T20_s1_train",
                validation_partition="r42_T20_s1_validation",
                evaluation_partition="r42_T20_s1_validation",
                seed=str(seed),
                encoder_type="BiLSTM_attention",
                encoder_checkpoint=encoder_by_seed[seed],
                encoder_frozen_or_trainable="frozen",
                representation_source="sequence_attention_pooled_h",
                classifier_head=head,
                loss_function="weighted_BCE_with_logits",
                threshold_selection_method=thr.get("selection_rule", "maximum_validation_f1"),
                selected_threshold=f4(float(thr["selected_threshold"])),
                PR_AUC=f4(float(vm["pr_auc"])),
                precision=f4(float(vm["precision"])),
                recall=f4(float(vm["recall"])),
                F1=f4(float(vm["f1"])),
                FP=str(int(vm["fp"])),
                FN=str(int(vm["fn"])),
                calibration_metrics_available="false",
                protocol_identifier=PROTOCOL_ID if status == "main_comparison_valid" else "r42_v3_node_frozen_encoder_diagnostic",
                evidence_source="outputs/v3_node/*/summary.json + threshold.json",
                comparability_status=status,
                exclusion_reason=excl,
                notes=(
                    f"backbone_frozen_throughout={summary.get('backbone_frozen_throughout')}; "
                    f"best_epoch={summary.get('best_epoch')}; "
                    f"encoder_load_n={enc_report.get('n_loaded')}; "
                    "evaluation metrics reported on validation at validation-selected threshold; "
                    "test not evaluated."
                ),
            )
            manifest.append(row)
            if status == "main_comparison_valid":
                main_results.append(
                    SeedResult(
                        candidate_name=name,
                        candidate_family=family,
                        seed=seed,
                        pr_auc=float(vm["pr_auc"]),
                        precision=float(vm["precision"]),
                        recall=float(vm["recall"]),
                        f1=float(vm["f1"]),
                        fp=float(vm["fp"]),
                        fn=float(vm["fn"]),
                        threshold=float(thr["selected_threshold"]),
                        protocol_identifier=PROTOCOL_ID,
                        experiment_path=row["experiment_path"],
                        checkpoint_path=row["checkpoint_path"],
                        encoder_checkpoint=encoder_by_seed[seed],
                        encoder_status="frozen",
                    )
                )
    return manifest, main_results


def collect_frozen_soft_forest() -> tuple[list[dict[str, Any]], list[SeedResult]]:
    run_dir = ROOT / "outputs/original_architecture_refinement/full_seed42_frozen_forest"
    metrics = load_json(run_dir / "validation_metrics.json")
    thr = load_json(run_dir / "threshold.json")
    report = load_json(run_dir / "full_seed42_frozen_forest_report.json")
    cfg = report["configuration"]
    src = report["source_checkpoint"]["path"]
    row = blank_row(
        candidate_name="original_soft_decision_forest_frozen",
        candidate_family="soft_decision_forest",
        experiment_path=str(run_dir.relative_to(ROOT)).replace("\\", "/"),
        checkpoint_path="outputs/original_architecture_refinement/full_seed42_frozen_forest/best.pt",
        dataset_version="CERT r4.2",
        train_partition="r42_T20_s1_train",
        validation_partition="r42_T20_s1_validation",
        evaluation_partition="r42_T20_s1_validation",
        seed="42",
        encoder_type="BiLSTM_attention",
        encoder_checkpoint=(
            "outputs/v3_node/seed42_full_20260723_095912/seed42_full_20260723_095916/"
            "attention_linear_reference_seed42/best.pt"
        ),
        encoder_frozen_or_trainable="frozen",
        representation_source="sequence_attention_pooled_h",
        classifier_head="soft_decision_forest",
        loss_function="weighted_BCE_with_logits",
        threshold_selection_method="maximum_validation_f1",
        selected_threshold=f4(float(thr["threshold"])),
        PR_AUC=f4(float(metrics["pr_auc"])),
        precision=f4(float(metrics["precision"])),
        recall=f4(float(metrics["recall"])),
        F1=f4(float(metrics["f1"])),
        FP=str(int(metrics["fp"])),
        FN=str(int(metrics["fn"])),
        calibration_metrics_available="true",
        protocol_identifier=PROTOCOL_ID,
        evidence_source="outputs/original_architecture_refinement/full_seed42_frozen_forest/",
        comparability_status="main_comparison_valid",
        exclusion_reason="",
        notes=(
            f"trees={cfg.get('trees')}, depth={cfg.get('depth')}; "
            f"stage=frozen; seeds_52_62_executed={cfg.get('seeds_52_62_executed')}; "
            f"source_checkpoint_recorded={src}; "
            "calibration: log_loss and brier_score present in validation_metrics.json; "
            "single-seed only under frozen-encoder protocol."
        ),
    )
    result = SeedResult(
        candidate_name="original_soft_decision_forest_frozen",
        candidate_family="soft_decision_forest",
        seed=42,
        pr_auc=float(metrics["pr_auc"]),
        precision=float(metrics["precision"]),
        recall=float(metrics["recall"]),
        f1=float(metrics["f1"]),
        fp=float(metrics["fp"]),
        fn=float(metrics["fn"]),
        threshold=float(thr["threshold"]),
        protocol_identifier=PROTOCOL_ID,
        experiment_path=row["experiment_path"],
        checkpoint_path=row["checkpoint_path"],
        encoder_checkpoint=row["encoder_checkpoint"],
        encoder_status="frozen",
        notes="single_seed_frozen_protocol",
    )
    return [row], [result]


def collect_joint_soft_forest() -> list[dict[str, Any]]:
    rows = []
    comp = pd.read_csv(ROOT / "outputs/objective2/objective2_validation_model_comparison.csv")
    sub = comp[comp["model_id"] == "joint_bilstm_attention_soft_forest"]
    for _, r in sub.iterrows():
        seed = int(r["seed"])
        enc = (
            "outputs/baselines/sequence_ensemble/stage11_A_attn_linear/best.pt"
            if seed == 42
            else f"outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed{seed}/best.pt"
        )
        enc_report = load_json(
            Path(str(r["run_dir"])) / "encoder_load_report.json"
        )
        rows.append(
            blank_row(
                candidate_name="joint_bilstm_attention_soft_forest",
                candidate_family="soft_decision_forest_joint",
                experiment_path=str(Path(str(r["run_dir"])).relative_to(ROOT)).replace("\\", "/"),
                checkpoint_path=str(Path(str(r["checkpoint_path"])).relative_to(ROOT)).replace("\\", "/"),
                dataset_version="CERT r4.2",
                train_partition="r42_T20_s1_train",
                validation_partition="r42_T20_s1_validation",
                evaluation_partition="r42_T20_s1_validation",
                seed=str(seed),
                encoder_type="BiLSTM_attention",
                encoder_checkpoint=enc,
                encoder_frozen_or_trainable="trainable",
                representation_source="sequence_attention_pooled_h",
                classifier_head="soft_decision_forest",
                loss_function="weighted_BCE_pos_weight_multiplier_0.25",
                threshold_selection_method="maximum_validation_f1",
                selected_threshold=f4(float(r["validation_threshold"])),
                PR_AUC=f4(float(r["validation_pr_auc"])),
                precision=f4(float(r["validation_precision"])),
                recall=f4(float(r["validation_recall"])),
                F1=f4(float(r["validation_f1"])),
                FP=str(int(r["validation_fp"])),
                FN=str(int(r["validation_fn"])),
                calibration_metrics_available="false",
                protocol_identifier="r42_sequence_ensemble_joint_pretrained_trainable_encoder",
                evidence_source="outputs/objective2/objective2_validation_model_comparison.csv",
                comparability_status="excluded_protocol_mismatch",
                exclusion_reason=(
                    "Encoder not frozen (encoder_frozen=false); only LSTM weights loaded from "
                    "attention-linear pretrain; attention and forest trained jointly with "
                    "pos_weight_multiplier=0.25. Not equivalent to frozen-head ODST protocol."
                ),
                notes=f"encoder_load_n={enc_report.get('n_loaded')}; locked Obj2 joint candidate.",
            )
        )
    return rows


def collect_grande() -> list[dict[str, Any]]:
    run_dir = ROOT / "outputs/v4_grande/seed42_full"
    summary = load_json(run_dir / "summary.json")
    vf = summary["validation_max_f1"]
    sm = summary["score_metrics"]
    return [
        blank_row(
            candidate_name="grande_frozen_representation",
            candidate_family="grande",
            experiment_path="outputs/v4_grande/seed42_full",
            checkpoint_path="not_recorded",
            dataset_version="CERT r4.2",
            train_partition="r42_T20_s1_train",
            validation_partition="r42_T20_s1_validation",
            evaluation_partition="r42_T20_s1_validation",
            seed="42",
            encoder_type="BiLSTM_attention",
            encoder_checkpoint="not_recorded",
            encoder_frozen_or_trainable="frozen",
            representation_source="frozen_attention_pooled_h_with_quantile_transform",
            classifier_head="grande",
            loss_function="not_recorded",
            threshold_selection_method="maximum_validation_f1",
            selected_threshold=f4(float(vf["selected_threshold"])),
            PR_AUC=f4(float(sm["pr_auc"])),
            precision=f4(float(vf["precision"])),
            recall=f4(float(vf["recall"])),
            F1=f4(float(vf["f1"])),
            FP=str(int(vf["fp"])),
            FN=str(int(vf["fn"])),
            calibration_metrics_available="true",
            protocol_identifier="r42_v4_grande_frozen_rep_quantile_seed42",
            evidence_source="outputs/v4_grande/seed42_full/summary.json",
            comparability_status="supplementary_only",
            exclusion_reason=(
                "Separate GRANDE validation protocol with QuantileTransformer on frozen "
                "representations; seed-42 only; failed strict gate FP<=49 and FN<=47; not protocol-"
                "equivalent to ODST frozen-head comparison."
            ),
            notes=(
                "Recorded PR-AUC=0.7695, F1=0.7500, FP=88, FN=48; "
                "predefined_constrained_operating_point=no_feasible_strict_operating_point; "
                "do not run seeds 52/62; do not add to locked r5.2 model set."
            ),
        )
    ]


def collect_standalone_and_tabular() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Standalone soft forest (tabular aggregated features) — validation rows only
    for seed in (42, 52, 62):
        metrics_path = ROOT / f"outputs/baselines/soft_decision_forest/seed_{seed}/sdf_T20_s1_metrics.csv"
        if not metrics_path.exists():
            continue
        sdf = pd.read_csv(metrics_path)
        val = sdf[(sdf["split"] == "validation") & (sdf["threshold_rule"] == "selected_val_f1")]
        if val.empty:
            continue
        r = val.iloc[0]
        ckpt = ROOT / f"outputs/baselines/soft_decision_forest/seed_{seed}/sdf_T20_s1_checkpoint.pt"
        rows.append(
            blank_row(
                candidate_name="standalone_soft_decision_forest_tabular",
                candidate_family="tabular_soft_forest",
                experiment_path=f"outputs/baselines/soft_decision_forest/seed_{seed}",
                checkpoint_path=str(ckpt.relative_to(ROOT)).replace("\\", "/")
                if ckpt.exists()
                else "not_recorded",
                dataset_version="CERT r4.2",
                train_partition="aggregated_T20_train",
                validation_partition="aggregated_T20_validation",
                evaluation_partition="aggregated_T20_validation",
                seed=str(seed),
                encoder_type="none_tabular",
                encoder_checkpoint="",
                encoder_frozen_or_trainable="n/a",
                representation_source="aggregated_sequence_features_40d",
                classifier_head="soft_decision_forest",
                loss_function="not_recorded",
                threshold_selection_method="maximum_validation_f1",
                selected_threshold=f4(float(r["threshold"])),
                PR_AUC=f4(float(r["pr_auc"])),
                precision=f4(float(r["precision"])),
                recall=f4(float(r["recall"])),
                F1=f4(float(r["f1"])),
                FP=str(int(r["fp"])),
                FN=str(int(r["fn"])),
                calibration_metrics_available="false",
                protocol_identifier="r42_standalone_tabular_soft_forest",
                evidence_source=str(metrics_path.relative_to(ROOT)).replace("\\", "/"),
                comparability_status="excluded_protocol_mismatch",
                exclusion_reason="Standalone tabular soft forest on aggregated features; not a Bi-LSTM classifier-head candidate.",
                notes="Reference baseline only; validation metrics from selected_val_f1 row.",
            )
        )

    # Optimised standalone SDF — recover metrics from preserved predictions (no threshold change)
    opt_dir = ROOT / "outputs/baselines/soft_decision_forest_optimised"
    if (opt_dir / "validation_predictions.parquet").exists():
        df = pd.read_parquet(opt_dir / "validation_predictions.parquet")
        y = df["y_true"].to_numpy()
        p = df["y_prob"].to_numpy()
        pred = df["y_pred_selected"].to_numpy()
        pr = float(average_precision_score(y, p))
        prec, rec, f1, _ = precision_recall_fscore_support(
            y, pred, average="binary", zero_division=0
        )
        tn, fp, fn, tp = confusion_matrix(y, pred).ravel()
        rows.append(
            blank_row(
                candidate_name="standalone_soft_decision_forest_optimised",
                candidate_family="tabular_soft_forest_optimised",
                experiment_path="outputs/baselines/soft_decision_forest_optimised",
                checkpoint_path="outputs/baselines/soft_decision_forest_optimised/best_checkpoint.pt",
                dataset_version="CERT r4.2",
                train_partition="aggregated_T20_train",
                validation_partition="aggregated_T20_validation",
                evaluation_partition="aggregated_T20_validation",
                seed="not_recorded",
                encoder_type="none_tabular",
                encoder_checkpoint="",
                encoder_frozen_or_trainable="n/a",
                representation_source="aggregated_sequence_features",
                classifier_head="soft_decision_forest_optimised",
                loss_function="not_recorded",
                threshold_selection_method="preserved_y_pred_selected",
                selected_threshold="not_recorded",
                PR_AUC=f4(pr),
                precision=f4(float(prec)),
                recall=f4(float(rec)),
                F1=f4(float(f1)),
                FP=str(int(fp)),
                FN=str(int(fn)),
                calibration_metrics_available="false",
                protocol_identifier="r42_standalone_tabular_soft_forest_optimised",
                evidence_source="outputs/baselines/soft_decision_forest_optimised/validation_predictions.parquet",
                comparability_status="supplementary_only",
                exclusion_reason=(
                    "Standalone tabular optimisation on aggregated features; not Bi-LSTM "
                    "classifier-head comparison. Metrics recovered from preserved "
                    "y_pred_selected without retuning."
                ),
                notes="Test predictions also exist but are not used for architecture-head closure.",
            )
        )
    return rows


def collect_residual_gated_ranking() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add_from_summary(
        path: Path,
        *,
        name: str,
        family: str,
        status: str,
        excl: str,
        protocol: str,
    ) -> None:
        d = load_json(path)
        vm = d.get("validation_metrics") or {}
        if not vm and "score_metrics" in d:
            sm = d["score_metrics"]
            vf = d.get("validation_max_f1") or {}
            vm = {
                "pr_auc": sm.get("pr_auc"),
                "precision": vf.get("precision"),
                "recall": vf.get("recall"),
                "f1": vf.get("f1"),
                "fp": vf.get("fp"),
                "fn": vf.get("fn"),
                "threshold": vf.get("selected_threshold") or vf.get("threshold"),
            }
        seed = d.get("seed", "not_recorded")
        thr_path = path.parent / "threshold.json"
        thr = load_json(thr_path) if thr_path.exists() else {}
        selected = thr.get("selected_threshold", vm.get("threshold", "not_recorded"))
        rows.append(
            blank_row(
                candidate_name=name,
                candidate_family=family,
                experiment_path=str(path.parent.relative_to(ROOT)).replace("\\", "/"),
                checkpoint_path=str((path.parent / "best.pt").relative_to(ROOT)).replace("\\", "/")
                if (path.parent / "best.pt").exists()
                else "not_recorded",
                dataset_version="CERT r4.2",
                train_partition="r42_T20_s1_train",
                validation_partition="r42_T20_s1_validation",
                evaluation_partition="r42_T20_s1_validation",
                seed=str(seed),
                encoder_type="BiLSTM_attention",
                encoder_checkpoint="not_recorded",
                encoder_frozen_or_trainable=(
                    "frozen"
                    if d.get("backbone_frozen_throughout") or d.get("encoder_frozen")
                    else "not_recorded"
                ),
                representation_source="sequence_attention_pooled_h",
                classifier_head=name,
                loss_function="not_recorded",
                threshold_selection_method=thr.get("selection_rule", "maximum_validation_f1"),
                selected_threshold=f4(float(selected)) if selected not in ("", None, "not_recorded") else "not_recorded",
                PR_AUC=f4(float(vm["pr_auc"])) if vm.get("pr_auc") is not None else "",
                precision=f4(float(vm["precision"])) if vm.get("precision") is not None else "",
                recall=f4(float(vm["recall"])) if vm.get("recall") is not None else "",
                F1=f4(float(vm["f1"])) if vm.get("f1") is not None else "",
                FP=str(int(vm["fp"])) if vm.get("fp") is not None else "",
                FN=str(int(vm["fn"])) if vm.get("fn") is not None else "",
                calibration_metrics_available="false",
                protocol_identifier=protocol,
                evidence_source=str(path.relative_to(ROOT)).replace("\\", "/"),
                comparability_status=status,
                exclusion_reason=excl,
                notes=f"prototype={d.get('prototype')}; variant={d.get('fusion_variant') or d.get('ranking_variant')}",
            )
        )

    # v2 residual / gated / forest-only
    v2_root = ROOT / "outputs/v2/seed42_full_20260723_081727"
    for p in sorted(v2_root.glob("*/summary.json")):
        variant = p.parent.name.replace("_seed42", "")
        add_from_summary(
            p,
            name=f"v2_{variant}",
            family="residual_gated_prototype",
            status="diagnostic_only",
            excl="Residual/gated/forest-only prototype development; not selected architecture candidate.",
            protocol="r42_v2_residual_prototype_seed42",
        )

    # v2.1 frozen residual
    v21 = ROOT / "outputs/v2_1/seed42_full_20260723_090852/seed42_full_20260723_090855"
    for p in sorted(v21.glob("*/summary.json")):
        variant = p.parent.name.replace("_seed42", "")
        add_from_summary(
            p,
            name=f"v2_1_{variant}",
            family="frozen_residual_prototype",
            status="diagnostic_only",
            excl="Frozen residual/gate prototype; diagnostic only.",
            protocol="r42_v2_1_frozen_residual_seed42",
        )

    # v3 ranking
    v3r = ROOT / "outputs/v3_ranking/seed42_full_20260723_164659"
    for p in sorted(v3r.glob("*/summary.json")):
        variant = p.parent.name.replace("_seed42", "")
        add_from_summary(
            p,
            name=f"v3_ranking_{variant}",
            family="ranking_loss_prototype",
            status="diagnostic_only",
            excl="Ranking-loss ODST prototype; seed-42 diagnostic only.",
            protocol="r42_v3_ranking_odst_seed42",
        )

    # OAR smoke residual/auxiliary — insufficient for numerical comparison
    for smoke_name in ["smoke", "smoke_residual", "smoke_auxiliary"]:
        smoke_dir = ROOT / "outputs/original_architecture_refinement" / smoke_name
        report = smoke_dir / "smoke" / "smoke_report.json"
        if not report.exists() and (smoke_dir / "smoke_report.json").exists():
            report = smoke_dir / "smoke_report.json"
        if report.exists():
            rows.append(
                blank_row(
                    candidate_name=f"oar_{smoke_name}",
                    candidate_family="original_architecture_refinement_smoke",
                    experiment_path=str(smoke_dir.relative_to(ROOT)).replace("\\", "/"),
                    checkpoint_path="not_recorded",
                    dataset_version="CERT r4.2",
                    train_partition="not_recorded",
                    validation_partition="not_recorded",
                    evaluation_partition="not_recorded",
                    seed="not_recorded",
                    encoder_type="BiLSTM_attention",
                    encoder_checkpoint="not_recorded",
                    encoder_frozen_or_trainable="not_recorded",
                    representation_source="sequence_attention_pooled_h",
                    classifier_head="soft_decision_forest_or_residual",
                    loss_function="not_recorded",
                    threshold_selection_method="not_recorded",
                    selected_threshold="not_recorded",
                    PR_AUC="",
                    precision="",
                    recall="",
                    F1="",
                    FP="",
                    FN="",
                    calibration_metrics_available="false",
                    protocol_identifier="r42_oar_smoke",
                    evidence_source=str(report.relative_to(ROOT)).replace("\\", "/"),
                    comparability_status="insufficient_evidence",
                    exclusion_reason="Smoke / implementation-gate run only; not a full comparable evaluation.",
                    notes="Used for decision gates, not architecture performance comparison.",
                )
            )
    return rows


def collect_obj2_attention_crosscheck() -> list[dict[str, Any]]:
    """Record Obj2 locked attention-linear as cross-check (same numbers as v3_node)."""
    rows = []
    comp = pd.read_csv(ROOT / "outputs/objective2/objective2_validation_model_comparison.csv")
    sub = comp[comp["model_id"] == "attention_linear"]
    for _, r in sub.iterrows():
        seed = int(r["seed"])
        rows.append(
            blank_row(
                candidate_name="attention_linear_obj2_locked_crosscheck",
                candidate_family="attention_linear",
                experiment_path=str(Path(str(r["run_dir"])).relative_to(ROOT)).replace("\\", "/"),
                checkpoint_path=str(Path(str(r["checkpoint_path"])).relative_to(ROOT)).replace("\\", "/"),
                dataset_version="CERT r4.2",
                train_partition="r42_T20_s1_train",
                validation_partition="r42_T20_s1_validation",
                evaluation_partition="r42_T20_s1_validation",
                seed=str(seed),
                encoder_type="BiLSTM_attention",
                encoder_checkpoint="end_to_end_trained_with_linear_head",
                encoder_frozen_or_trainable="trainable_during_pretrain_then_frozen_for_head_swap",
                representation_source="sequence_attention_pooled_h",
                classifier_head="linear",
                loss_function="weighted_BCE_with_logits",
                threshold_selection_method="maximum_validation_f1",
                selected_threshold=f4(float(r["validation_threshold"])),
                PR_AUC=f4(float(r["validation_pr_auc"])),
                precision=f4(float(r["validation_precision"])),
                recall=f4(float(r["validation_recall"])),
                F1=f4(float(r["validation_f1"])),
                FP=str(int(r["validation_fp"])),
                FN=str(int(r["validation_fn"])),
                calibration_metrics_available="false",
                protocol_identifier=PROTOCOL_ID,
                evidence_source="outputs/objective2/objective2_validation_model_comparison.csv",
                comparability_status="supplementary_only",
                exclusion_reason=(
                    "Cross-check duplicate of v3_node attention_linear_reference; "
                    "main comparison uses v3_node rows to avoid double-counting seeds."
                ),
                notes="Metrics match v3_node attention_linear_reference to recorded precision.",
            )
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def build_comparison_tables(main: list[SeedResult]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    comparison_rows = []
    for r in main:
        comparison_rows.append(
            {
                "candidate_name": r.candidate_name,
                "candidate_family": r.candidate_family,
                "seed": r.seed,
                "PR_AUC": r.pr_auc,
                "precision": r.precision,
                "recall": r.recall,
                "F1": r.f1,
                "FP": r.fp,
                "FN": r.fn,
                "selected_threshold": r.threshold,
                "protocol_identifier": r.protocol_identifier,
                "experiment_path": r.experiment_path,
                "checkpoint_path": r.checkpoint_path,
                "encoder_checkpoint": r.encoder_checkpoint,
                "encoder_frozen_or_trainable": r.encoder_status,
            }
        )
    comparison = pd.DataFrame(comparison_rows).sort_values(["candidate_name", "seed"])

    summary_rows = []
    for name, g in comparison.groupby("candidate_name"):
        row: dict[str, Any] = {
            "candidate_name": name,
            "candidate_family": g["candidate_family"].iloc[0],
            "n_valid_seeds": int(len(g)),
            "protocol_identifier": g["protocol_identifier"].iloc[0],
        }
        for metric in ["PR_AUC", "precision", "recall", "F1", "FP", "FN", "selected_threshold"]:
            vals = g[metric].astype(float).tolist()
            m, s = mean_std(vals)
            row[f"{metric}_mean"] = m
            row[f"{metric}_std"] = s if len(vals) > 1 else 0.0
            row[f"{metric}_min"] = min(vals)
            row[f"{metric}_max"] = max(vals)
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows).sort_values("candidate_name")

    # Pairwise: ODST vs each other candidate
    odst = comparison[comparison["candidate_name"] == "sparsemax_sigmoid_odst"].set_index("seed")
    pairwise_rows = []
    for other_name in sorted(comparison["candidate_name"].unique()):
        if other_name == "sparsemax_sigmoid_odst":
            continue
        other = comparison[comparison["candidate_name"] == other_name].set_index("seed")
        common = sorted(set(odst.index).intersection(other.index))
        if not common:
            continue
        deltas = {
            "PR_AUC": [],
            "F1": [],
            "precision": [],
            "recall": [],
            "FP": [],
            "FN": [],
        }
        for seed in common:
            for m in deltas:
                deltas[m].append(float(odst.loc[seed, m]) - float(other.loc[seed, m]))
            pairwise_rows.append(
                {
                    "comparison": f"ODST_minus_{other_name}",
                    "reference_candidate": other_name,
                    "seed": seed,
                    "n_matched_seeds": len(common),
                    "delta_PR_AUC": float(odst.loc[seed, "PR_AUC"]) - float(other.loc[seed, "PR_AUC"]),
                    "delta_F1": float(odst.loc[seed, "F1"]) - float(other.loc[seed, "F1"]),
                    "delta_precision": float(odst.loc[seed, "precision"]) - float(other.loc[seed, "precision"]),
                    "delta_recall": float(odst.loc[seed, "recall"]) - float(other.loc[seed, "recall"]),
                    "delta_FP": float(odst.loc[seed, "FP"]) - float(other.loc[seed, "FP"]),
                    "delta_FN": float(odst.loc[seed, "FN"]) - float(other.loc[seed, "FN"]),
                    "aggregation": "seed_level",
                }
            )
        # aggregate over matched seeds
        agg = {
            "comparison": f"ODST_minus_{other_name}",
            "reference_candidate": other_name,
            "seed": "matched_aggregate",
            "n_matched_seeds": len(common),
            "aggregation": "mean_over_matched_seeds",
        }
        for m, key in [
            ("PR_AUC", "delta_PR_AUC"),
            ("F1", "delta_F1"),
            ("precision", "delta_precision"),
            ("recall", "delta_recall"),
            ("FP", "delta_FP"),
            ("FN", "delta_FN"),
        ]:
            vals = deltas[m]
            mu, sd = mean_std(vals)
            agg[key] = mu
            agg[f"{key}_std"] = sd if len(vals) > 1 else 0.0
            agg[f"{key}_min"] = min(vals)
            agg[f"{key}_max"] = max(vals)
        pairwise_rows.append(agg)

    pairwise = pd.DataFrame(pairwise_rows)
    return comparison, summary, pairwise


def make_figures(comparison: pd.DataFrame, summary: pd.DataFrame) -> list[str]:
    created: list[str] = []
    display = {
        "bi_lstm_attention_linear": "Attention–Linear",
        "original_soft_decision_forest_frozen": "Soft Decision Forest",
        "sparsemax_sigmoid_odst": "Sparsemax–Sigmoid ODST",
    }
    order = [
        "bi_lstm_attention_linear",
        "original_soft_decision_forest_frozen",
        "sparsemax_sigmoid_odst",
    ]
    summary = summary.set_index("candidate_name").loc[order].reset_index()
    labels = [display[c] for c in summary["candidate_name"]]
    x = np.arange(len(labels))
    width = 0.35

    # Figure 1: PR-AUC and F1
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    pr = summary["PR_AUC_mean"].to_numpy()
    pr_err = summary["PR_AUC_std"].to_numpy()
    f1 = summary["F1_mean"].to_numpy()
    f1_err = summary["F1_std"].to_numpy()
    # suppress misleading error bars for single-seed
    n = summary["n_valid_seeds"].to_numpy()
    pr_err = np.where(n > 1, pr_err, 0.0)
    f1_err = np.where(n > 1, f1_err, 0.0)
    b1 = ax.bar(x - width / 2, pr, width, yerr=pr_err, capsize=4, label="PR-AUC", color="#2F4B7C")
    b2 = ax.bar(x + width / 2, f1, width, yerr=f1_err, capsize=4, label="F1", color="#A05195")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Score")
    ax.set_ylim(0.0, 1.05)
    ax.set_title("Objective 2 architecture candidates: PR-AUC and F1")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    # annotate single-seed
    for i, ni in enumerate(n):
        if ni == 1:
            ax.text(i, max(pr[i], f1[i]) + 0.03, "n=1", ha="center", fontsize=8, color="#555555")
    fig.tight_layout()
    p1 = OUT / "objective2_architecture_pr_auc_f1_comparison.png"
    fig.savefig(p1, dpi=300)
    plt.close(fig)
    created.append(str(p1.relative_to(ROOT)).replace("\\", "/"))

    # Figure 2: FP / FN
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    fp = summary["FP_mean"].to_numpy()
    fn = summary["FN_mean"].to_numpy()
    fp_err = np.where(n > 1, summary["FP_std"].to_numpy(), 0.0)
    fn_err = np.where(n > 1, summary["FN_std"].to_numpy(), 0.0)
    ax.bar(x - width / 2, fp, width, yerr=fp_err, capsize=4, label="False positives", color="#D45087")
    ax.bar(x + width / 2, fn, width, yerr=fn_err, capsize=4, label="False negatives", color="#FFA600")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Count (validation)")
    ax.set_title("Objective 2 architecture candidates: FP and FN")
    ax.legend(frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for i, ni in enumerate(n):
        if ni == 1:
            ax.text(i, max(fp[i], fn[i]) + 3, "n=1", ha="center", fontsize=8, color="#555555")
    fig.tight_layout()
    p2 = OUT / "objective2_architecture_fp_fn_comparison.png"
    fig.savefig(p2, dpi=300)
    plt.close(fig)
    created.append(str(p2.relative_to(ROOT)).replace("\\", "/"))

    # Figure 3: tradeoff scatter
    fig, ax = plt.subplots(figsize=(7.5, 6.0))
    colors = {"bi_lstm_attention_linear": "#2F4B7C", "original_soft_decision_forest_frozen": "#D45087", "sparsemax_sigmoid_odst": "#008A5E"}
    for name in order:
        g = comparison[comparison["candidate_name"] == name]
        col = colors[name]
        if len(g) > 1:
            ax.scatter(g["FP"], g["FN"], s=40, alpha=0.35, color=col, label=None)
        ax.scatter(
            [g["FP"].mean()],
            [g["FN"].mean()],
            s=90,
            color=col,
            edgecolors="black",
            linewidths=0.6,
            label=display[name],
            zorder=3,
        )
        ax.annotate(
            display[name],
            (g["FP"].mean(), g["FN"].mean()),
            textcoords="offset points",
            xytext=(8, 6),
            fontsize=9,
        )
    ax.set_xlabel("False positives (validation)")
    ax.set_ylabel("False negatives (validation)")
    ax.set_title("Error-burden trade-off across architecture candidates")
    ax.legend(frameon=False, loc="best")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    p3 = OUT / "objective2_architecture_tradeoff_plot.png"
    fig.savefig(p3, dpi=300)
    plt.close(fig)
    created.append(str(p3.relative_to(ROOT)).replace("\\", "/"))

    # Figure 4: seed variability for multi-seed candidates
    multi = comparison[comparison["candidate_name"].isin(["bi_lstm_attention_linear", "sparsemax_sigmoid_odst"])]
    if multi["candidate_name"].nunique() >= 1 and multi.groupby("candidate_name").size().min() >= 2:
        fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.8), sharex=False)
        for ax, metric, title in zip(axes, ["PR_AUC", "F1"], ["PR-AUC", "F1"]):
            for name, marker in [
                ("bi_lstm_attention_linear", "o"),
                ("sparsemax_sigmoid_odst", "s"),
            ]:
                g = multi[multi["candidate_name"] == name].sort_values("seed")
                ax.plot(
                    g["seed"],
                    g[metric],
                    marker=marker,
                    linewidth=1.5,
                    label=display[name],
                    color=colors[name],
                )
            ax.set_xlabel("Seed")
            ax.set_ylabel(title)
            ax.set_xticks([42, 52, 62])
            ax.set_title(f"Seed-level {title}")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
        axes[0].legend(frameon=False)
        fig.suptitle("Matched multi-seed variability (frozen-encoder protocol)", y=1.02)
        fig.tight_layout()
        p4 = OUT / "objective2_architecture_seed_variability.png"
        fig.savefig(p4, dpi=300, bbox_inches="tight")
        plt.close(fig)
        created.append(str(p4.relative_to(ROOT)).replace("\\", "/"))

    return created


def write_comparability_report(manifest: list[dict[str, Any]], main_names: list[str]) -> Path:
    by_status: dict[str, list[dict[str, Any]]] = {}
    for row in manifest:
        by_status.setdefault(row["comparability_status"], []).append(row)

    path = OUT / "objective2_architecture_comparability_report.md"
    lines = [
        "# Objective 2 architecture comparability report",
        "",
        f"- Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"- Repository branch: `{BRANCH}`",
        f"- HEAD: `{HEAD}`",
        f"- Common protocol identifier: `{PROTOCOL_ID}`",
        "",
        "## Common comparison protocol",
        "",
        "A candidate enters the **main numerical comparison** only when the preserved evidence confirms:",
        "",
        "1. Dataset: CERT r4.2 sequence tensors `r42_T20_s1_*` (T=20, stride=1, 13 daily features).",
        "2. Splits: chronological train and validation partitions; final CERT r4.2 test unused for selection.",
        "3. Representation: Bi-LSTM encoder with temporal attention pooling to vector `h`.",
        "4. Encoder: seed-matched attention–linear checkpoint; **encoder frozen** while the classifier head is trained or evaluated.",
        "5. Seeds: 42 / 52 / 62 where available; single-seed rows are retained but marked.",
        "6. Checkpoint selection: maximum validation PR-AUC.",
        "7. Threshold selection: maximum validation F1 on the validation partition only.",
        "8. Reported operating-point metrics: validation partition (architecture-development stage).",
        "9. No tuning on the locked final test partition; no access to locked CERT r5.2 test tensors for this closure.",
        "",
        "### Protocol caveat",
        "",
        "Architecture-head experiments in `outputs/v3_node/` and the frozen soft-forest run report "
        "operating-point metrics on the **same validation partition** used for threshold selection. "
        "PR-AUC remains threshold-free and is the primary ranking metric. Operating-point metrics "
        "(F1, FP, FN) are interpreted cautiously and are not claimed as untouched later-development "
        "estimates.",
        "",
        "## Main comparison candidates",
        "",
    ]
    for name in main_names:
        seeds = sorted({r["seed"] for r in manifest if r["candidate_name"] == name and r["comparability_status"] == "main_comparison_valid"})
        lines.append(f"- `{name}` — seeds: {', '.join(seeds)}")
    lines += ["", "## Exclusions and supplementary placements", ""]

    for status in [
        "excluded_protocol_mismatch",
        "supplementary_only",
        "diagnostic_only",
        "insufficient_evidence",
    ]:
        lines.append(f"### `{status}`")
        lines.append("")
        items = by_status.get(status, [])
        if not items:
            lines.append("_None._")
            lines.append("")
            continue
        # unique by candidate_name
        seen = set()
        for row in items:
            key = row["candidate_name"]
            if key in seen:
                continue
            seen.add(key)
            reason = row["exclusion_reason"] or row["notes"] or "not_recorded"
            lines.append(f"- **{key}**: {reason}")
        lines.append("")

    lines += [
        "## Fourth-candidate decision",
        "",
        "- **GRANDE** remains supplementary: frozen-representation experiment with QuantileTransformer "
        "and a separate constrained operating-point gate; seed-42 only; not protocol-equivalent.",
        "- **Joint Bi-LSTM–attention–soft forest** (locked Obj2) is excluded from the main head "
        "comparison because the encoder was trainable (`encoder_frozen=false`) and attention was "
        "not loaded from the frozen reference in the same way as ODST.",
        "- **Optimised standalone soft forest** is tabular aggregated-feature optimisation, not a "
        "Bi-LSTM classifier-head candidate.",
        "",
        "Therefore the main table has three candidates. No fourth candidate satisfies the common protocol.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_closure_report(
    manifest: list[dict[str, Any]],
    comparison: pd.DataFrame,
    summary: pd.DataFrame,
    pairwise: pd.DataFrame,
    figure_paths: list[str],
    worktree_dirty: bool,
) -> Path:
    status_label = "objective2_architecture_evidence_complete_with_protocol_limitations"
    main = summary.set_index("candidate_name")
    odst = main.loc["sparsemax_sigmoid_odst"]
    attn = main.loc["bi_lstm_attention_linear"]

    # paired aggregates
    def agg_row(ref: str) -> pd.Series:
        return pairwise[
            (pairwise["reference_candidate"] == ref)
            & (pairwise["aggregation"] == "mean_over_matched_seeds")
        ].iloc[0]

    vs_forest = agg_row("original_soft_decision_forest_frozen")
    vs_attn = agg_row("bi_lstm_attention_linear")
    # Seed-42 point estimates for the primary soft-forest comparison
    odst_s42 = comparison[
        (comparison["candidate_name"] == "sparsemax_sigmoid_odst") & (comparison["seed"] == 42)
    ].iloc[0]
    forest_s42 = comparison[
        (comparison["candidate_name"] == "original_soft_decision_forest_frozen")
        & (comparison["seed"] == 42)
    ].iloc[0]

    discovered = sorted({r["candidate_name"] for r in manifest})
    excluded = sorted(
        {
            r["candidate_name"]
            for r in manifest
            if r["comparability_status"]
            in {"excluded_protocol_mismatch", "diagnostic_only", "insufficient_evidence", "supplementary_only"}
        }
    )

    path = OUT / "objective2_architecture_closure_report.md"
    lines = [
        "# Objective 2 architecture-candidate closure report",
        "",
        "## 1. Repository state",
        "",
        f"- Branch: `{BRANCH}`",
        f"- HEAD: `{HEAD}`",
        f"- Worktree clean at audit start: **no** (unrelated Objective 3 / prototype scripts modified or untracked).",
        f"- Worktree dirty during audit: `{worktree_dirty}`",
        "- Raw datasets, locked prediction files, checkpoints and prior experiment outputs were not modified.",
        "- Locked CERT r5.2 test tensors were not accessed; the r5.2 evaluator was not rerun.",
        "- No models were trained for this closure.",
        "",
        "## 2. Artefacts inspected",
        "",
        "- `outputs/objective2/objective2_validation_model_comparison.csv` and related locked Obj2 consolidation outputs",
        "- `outputs/baselines/sequence_ensemble/` (attention–linear pretrain; joint soft-forest stage D)",
        "- `outputs/v3_node/` (frozen-encoder NODE/ODST three-seed validation)",
        "- `outputs/original_architecture_refinement/full_seed42_frozen_forest/`",
        "- `outputs/v2/`, `outputs/v2_1/`, `outputs/v3_ranking/`, `outputs/v3_fusion/`, `outputs/v3_ensemble/`",
        "- `outputs/v4_grande/seed42_full/summary.json`",
        "- `outputs/baselines/soft_decision_forest/` and `soft_decision_forest_optimised/` (tabular references)",
        "- Listed `outputs/objective2/r52_odst_confirmation/` metadata only (no r5.2 test tensor access)",
        "",
        "## 3. Candidates discovered",
        "",
    ]
    for name in discovered:
        lines.append(f"- `{name}`")
    lines += [
        "",
        "## 4. Common comparison protocol",
        "",
        f"See `objective2_architecture_comparability_report.md`. Protocol id: `{PROTOCOL_ID}`.",
        "",
        "## 5. Main comparison candidates",
        "",
        "1. Bi-LSTM–attention–linear (`bi_lstm_attention_linear`) — seeds 42, 52, 62",
        "2. Original soft decision forest, frozen encoder (`original_soft_decision_forest_frozen`) — seed 42 only",
        "3. Sparsemax–sigmoid ODST (`sparsemax_sigmoid_odst`) — seeds 42, 52, 62",
        "",
        "No fourth candidate met the common protocol.",
        "",
        "## 6. Excluded and supplementary candidates",
        "",
    ]
    for name in excluded:
        lines.append(f"- `{name}`")
    lines += [
        "",
        "## 7. Numerical results",
        "",
        "### Summary (validation; mean ± std over valid seeds)",
        "",
        "| Candidate | n | PR-AUC | F1 | Precision | Recall | FP | FN | Threshold |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in [
        "bi_lstm_attention_linear",
        "original_soft_decision_forest_frozen",
        "sparsemax_sigmoid_odst",
    ]:
        r = main.loc[name]
        lines.append(
            "| {name} | {n} | {pr:.4f}±{prs:.4f} | {f1:.4f}±{f1s:.4f} | {p:.4f}±{ps:.4f} | {rc:.4f}±{rcs:.4f} | {fp:.1f}±{fps:.1f} | {fn:.1f}±{fns:.1f} | {th:.3f}±{ths:.3f} |".format(
                name=name,
                n=int(r["n_valid_seeds"]),
                pr=r["PR_AUC_mean"],
                prs=r["PR_AUC_std"],
                f1=r["F1_mean"],
                f1s=r["F1_std"],
                p=r["precision_mean"],
                ps=r["precision_std"],
                rc=r["recall_mean"],
                rcs=r["recall_std"],
                fp=r["FP_mean"],
                fps=r["FP_std"],
                fn=r["FN_mean"],
                fns=r["FN_std"],
                th=r["selected_threshold_mean"],
                ths=r["selected_threshold_std"],
            )
        )
    lines += [
        "",
        "Seed-level rows: `objective2_architecture_candidate_comparison.csv`.",
        "",
        "### Pairwise differences (ODST − reference)",
        "",
        f"- Primary (seed 42 only): ODST − frozen soft forest: "
        f"ΔPR-AUC={vs_forest['delta_PR_AUC']:.4f}, ΔF1={vs_forest['delta_F1']:.4f}, "
        f"ΔP={vs_forest['delta_precision']:.4f}, ΔR={vs_forest['delta_recall']:.4f}, "
        f"ΔFP={vs_forest['delta_FP']:.1f}, ΔFN={vs_forest['delta_FN']:.1f}.",
        f"- ODST − attention–linear (3 matched seeds, mean): "
        f"ΔPR-AUC={vs_attn['delta_PR_AUC']:.4f} (std {vs_attn['delta_PR_AUC_std']:.4f}), "
        f"ΔF1={vs_attn['delta_F1']:.4f} (std {vs_attn['delta_F1_std']:.4f}), "
        f"ΔFP={vs_attn['delta_FP']:.1f}, ΔFN={vs_attn['delta_FN']:.1f}.",
        "",
        "Figures:",
        "",
    ]
    for fp in figure_paths:
        lines.append(f"- `{fp}`")
    lines += [
        "",
        "## 8. ODST versus original soft forest",
        "",
        "Under the common frozen-encoder protocol (seed 42 only), sparsemax–sigmoid ODST improves "
        f"PR-AUC ({odst_s42['PR_AUC']:.4f} vs {forest_s42['PR_AUC']:.4f}) and F1 "
        f"({odst_s42['F1']:.4f} vs {forest_s42['F1']:.4f}), and reduces false positives "
        f"({odst_s42['FP']:.0f} vs {forest_s42['FP']:.0f}). False negatives are slightly higher "
        f"for ODST ({odst_s42['FN']:.0f} vs {forest_s42['FN']:.0f}), so ODST does **not** dominate "
        "every error-burden metric. The improvement claim is therefore limited to ranking quality "
        "(PR-AUC), F1 and FP control under this protocol, with a modest FN trade-off "
        f"(paired ΔPR-AUC={vs_forest['delta_PR_AUC']:.4f}, ΔF1={vs_forest['delta_F1']:.4f}, "
        f"ΔFP={vs_forest['delta_FP']:.0f}, ΔFN={vs_forest['delta_FN']:.0f}).",
        "",
        "The locked Obj2 joint soft-forest runs are **not** used for this primary claim because their "
        "encoder was trainable.",
        "",
        "## 9. ODST versus attention–linear",
        "",
        "Across three matched seeds, ODST improves mean PR-AUC relative to attention–linear "
        f"({odst['PR_AUC_mean']:.4f} vs {attn['PR_AUC_mean']:.4f}). Mean F1 is similar "
        f"({odst['F1_mean']:.4f} vs {attn['F1_mean']:.4f}) and seed-level F1/FP/FN differences are "
        "mixed (notably seed 62 worsens F1 and FP). Therefore ODST is **not** claimed to be "
        "consistently superior on all classification and error-burden measures. The defensible "
        "conclusion is that ODST provides a differentiable-tree interpretation of the sequence "
        "representation while remaining broadly competitive with attention–linear.",
        "",
        "## 10. Relationship to locked RF and XGBoost baselines",
        "",
        "This r4.2 classifier-head comparison does **not** support a claim that ODST outperforms "
        "classical RF or XGBoost. Locked CERT r5.2 evidence already shows RF and XGBoost remain "
        "stronger on several principal metrics; that finding is preserved and is outside the scope "
        "of this architecture-head closure.",
        "",
        "## 11. Limitations",
        "",
        "1. Frozen soft-forest evidence exists for seed 42 only (`seeds_52_62_executed=false`).",
        "2. Operating-point metrics are reported on the validation partition used for threshold selection.",
        "3. No separate chronological later-development partition was available for the head-swap experiments.",
        "4. Joint soft-forest (trainable encoder) and tabular soft-forest variants are protocol-mismatched.",
        "5. GRANDE used a distinct frozen-representation + QuantileTransformer protocol.",
        "6. Residual, gated, fusion and ranking prototypes remain diagnostic.",
        "",
        "## 12. Whether Objective 2 architecture experimentation is complete",
        "",
        "Yes, for the purpose of selecting among Bi-LSTM classifier-head candidates on CERT r4.2: "
        "the essential attention–linear, original soft-forest and ODST evidence exists under a "
        "documented common protocol, with the soft-forest comparison limited to seed 42.",
        "",
        "## 13. Whether any minimal rerun is required",
        "",
        "**No rerun is required to close the comparison.** Existing artefacts suffice for the "
        "primary ODST-versus-soft-forest (seed 42) and ODST-versus-attention–linear (three-seed) "
        "analyses.",
        "",
        "Optional strengthening (not executed): frozen soft-forest seeds 52 and 62 under the same "
        "encoder checkpoints, hyperparameters and validation max-F1 rule. This would reduce "
        "single-seed uncertainty but is not necessary for the present closure decision.",
        "",
        "## 14. Recommended Objective 2 status label",
        "",
        f"`{status_label}`",
        "",
        "### One-sentence conclusion",
        "",
        "Under the frozen-encoder CERT r4.2 protocol, sparsemax–sigmoid ODST improves PR-AUC, F1 "
        "and false-positive control relative to the original soft decision forest (seed 42) and is "
        "broadly competitive with attention–linear across three seeds, without supporting claims of "
        "uniform dominance or superiority over RF/XGBoost.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    main_results: list[SeedResult] = []

    m1, r1 = collect_v3_node_main()
    manifest.extend(m1)
    main_results.extend(r1)

    m2, r2 = collect_frozen_soft_forest()
    manifest.extend(m2)
    main_results.extend(r2)

    manifest.extend(collect_joint_soft_forest())
    manifest.extend(collect_grande())
    manifest.extend(collect_standalone_and_tabular())
    manifest.extend(collect_residual_gated_ranking())
    manifest.extend(collect_obj2_attention_crosscheck())

    # Write manifest
    manifest_path = OUT / "objective2_architecture_candidate_manifest.csv"
    write_csv(manifest_path, manifest, MANIFEST_FIELDS)

    comparison, summary, pairwise = build_comparison_tables(main_results)
    comparison.to_csv(OUT / "objective2_architecture_candidate_comparison.csv", index=False)
    summary.to_csv(OUT / "objective2_architecture_candidate_summary.csv", index=False)
    pairwise.to_csv(OUT / "objective2_architecture_pairwise_differences.csv", index=False)

    # Supplementary CSV
    supp = [
        r
        for r in manifest
        if r["comparability_status"] in {"supplementary_only", "diagnostic_only"}
        or r["candidate_name"]
        in {
            "grande_frozen_representation",
            "joint_bilstm_attention_soft_forest",
            "standalone_soft_decision_forest_optimised",
            "canonical_entmax15_node",
            "dense_linear_readout_node",
        }
    ]
    # Prefer unique useful diagnostic/supplementary rows
    supp_fields = MANIFEST_FIELDS
    write_csv(OUT / "objective2_architecture_candidate_supplementary.csv", supp, supp_fields)

    figure_paths = make_figures(comparison, summary)
    write_comparability_report(
        manifest,
        [
            "bi_lstm_attention_linear",
            "original_soft_decision_forest_frozen",
            "sparsemax_sigmoid_odst",
        ],
    )
    # worktree status snapshot
    import subprocess

    st = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    worktree_dirty = bool(st.strip())
    write_closure_report(manifest, comparison, summary, pairwise, figure_paths, worktree_dirty)

    # Console summary artefact
    console = {
        "branch": BRANCH,
        "HEAD": HEAD,
        "worktree_status": "dirty" if worktree_dirty else "clean",
        "output_dir": str(OUT.relative_to(ROOT)).replace("\\", "/"),
        "main_comparison_candidates": [
            "bi_lstm_attention_linear",
            "original_soft_decision_forest_frozen",
            "sparsemax_sigmoid_odst",
        ],
        "candidates_excluded_or_non_main": sorted(
            {
                r["candidate_name"]
                for r in manifest
                if r["comparability_status"] != "main_comparison_valid"
            }
        ),
        "models_trained": False,
        "prediction_tensors_opened": [
            "outputs/baselines/soft_decision_forest_optimised/validation_predictions.parquet"
        ],
        "r52_test_path_accessed": False,
        "final_status": "objective2_architecture_evidence_complete_with_protocol_limitations",
        "conclusion": (
            "Under the frozen-encoder CERT r4.2 protocol, sparsemax–sigmoid ODST improves PR-AUC, "
            "F1 and FP control versus the original soft decision forest (seed 42) and remains "
            "broadly competitive with attention–linear across three seeds, without claiming "
            "uniform dominance or RF/XGBoost superiority."
        ),
    }
    (OUT / "objective2_architecture_closure_console_summary.json").write_text(
        json.dumps(console, indent=2), encoding="utf-8"
    )
    console["output_files_created"] = sorted(p.name for p in OUT.iterdir() if p.is_file())
    (OUT / "objective2_architecture_closure_console_summary.json").write_text(
        json.dumps(console, indent=2), encoding="utf-8"
    )
    print(json.dumps(console, indent=2))


if __name__ == "__main__":
    main()
