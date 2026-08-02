"""Predefined validation protocol and selection criteria for Prototype V2."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SEEDS = (42, 52, 62)

COMPARISON_BASELINES = (
    "attention_linear",
    "joint_bilstm_attention_soft_forest",  # V1 forest-only path
    "standalone_bilstm",
    "fragmented_bilstm_xgboost",
)

SELECTION_CRITERIA = {
    "pr_auc_improvement_min": 0.01,
    "pr_auc_noninferiority_tol": 0.01,
    "fn_reduction_min_frac": 0.10,
    "no_seed_collapse": True,
    "stable_thresholds_and_gates": True,
    "must_beat_linear_only_ablation": True,
    "avoid_gate_collapse": True,
    "retain_active_forest_correction": True,
    "avoid_major_f1_or_recall_collapse": True,
    "test_evaluated": False,
    "selection_uses_r42_test": False,
}

CONTINUATION_CRITERIA_DOC = [
    "A: Validation PR-AUC >= attention-linear + 0.01",
    "B: Validation PR-AUC within 0.01 of strongest sequence baseline "
    "AND false negatives reduced by >= 10%",
    "C: Validation PR-AUC and F1 remain competitive while seed/gate behaviour "
    "is materially more stable than V1",
    "Also required: beat/improve on linear_only ablation; avoid gate collapse; "
    "retain active controlled forest correction; avoid major F1/recall collapse",
    "Continue to seeds 52/62 only when at least one of A/B/C holds",
]


def build_protocol_manifest(
    *,
    output_dir: Path,
    seeds: tuple[int, ...] = SEEDS,
    variants: list[str] | None = None,
    comparison_baselines: tuple[str, ...] = COMPARISON_BASELINES,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prototype": "v2",
        "name": "Adaptive Residual-Gated Differentiable Sequence–Ensemble",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "test_evaluated": False,
        "selection_uses_r42_test": False,
        "training_started": False,
        "splits_allowed": ["train", "validation"],
        "splits_forbidden": ["test"],
        "dataset": "CERT r4.2",
        "tensor_files": {
            "train": "data/processed/tensors/r42_T20_s1_train.npz",
            "validation": "data/processed/tensors/r42_T20_s1_validation.npz",
            "test": "NOT_LOADED_IN_V2_DEVELOPMENT",
        },
        "seeds": list(seeds),
        "begin_with_seed": 42,
        "fusion_variants": variants
        or [
            "linear_only",
            "forest_only_v1",
            "fixed_residual_0_5",
            "learned_global_residual_gate",
            "sample_specific_residual_gate",
        ],
        "fusion_variant_aliases": {"fixed_average": "fixed_residual_0_5"},
        "fixed_residual_0_5_rule": (
            "final_logit = linear_logit + 0.5 * forest_correction "
            "(fixed residual weight on the raw forest logit; not a mathematical average)"
        ),
        "forest_correction_semantics": (
            "Raw soft-forest logit (mean of soft-tree logits), used as an additive "
            "residual. Leaf logits are zero-initialised so correction ≈ 0 at start."
        ),
        "controls": {
            "attention_linear_reference": (
                "Read-only evaluation of the original V1 attention-linear checkpoint"
            ),
            "linear_only_finetuned": (
                "Trainable linear_only control under the same V2 schedule"
            ),
        },
        "comparison_baselines": list(comparison_baselines),
        "selection_criteria": dict(SELECTION_CRITERIA),
        "continuation_criteria": list(CONTINUATION_CRITERIA_DOC),
        "training_schedule": {
            "warmup": "encoder + attention + linear frozen; forest + gate trainable",
            "joint_finetune": "encoder unfrozen; joint optimisation",
            "checkpoint_selection": "validation PR-AUC only",
            "threshold_selection": "validation F1 only; never changed after validation",
        },
        "notes": [
            "Select variants using validation metrics only.",
            "Do not select a variant using r4.2 test results.",
            "V1 / Objective 2 / Objective 3 artefacts are read-only references.",
            "Outputs must remain under outputs/v2/.",
        ],
        "output_namespace": str(output_dir),
    }
    if extra:
        payload.update(extra)
    return payload


def write_protocol_manifest(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload.get("test_evaluated") is not False:
        raise ValueError("V2 protocol manifest must have test_evaluated=false")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_obj2_validation_baseline_rows(
    root: Path,
    model_ids: tuple[str, ...] = COMPARISON_BASELINES,
) -> pd.DataFrame:
    """Read locked Obj2 validation comparison CSV (read-only)."""
    path = root / "outputs" / "objective2" / "objective2_validation_model_comparison.csv"
    if not path.exists():
        # Fallback to summary if comparison missing.
        path = root / "outputs" / "objective2" / "objective2_validation_model_summary.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "model_id" in df.columns:
        df = df[df["model_id"].isin(model_ids)].copy()
    return df


def select_variant(
    candidate_rows: list[dict[str, Any]] | pd.DataFrame,
    baseline_pr_auc: float,
    baseline_fn: float,
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply predefined selection rules on validation metrics only.

    A candidate passes if:
      (PR-AUC >= baseline + 0.01) OR
      (PR-AUC >= baseline - 0.01 AND FN <= baseline_fn * 0.9)
    and no seed collapse / threshold-gate instability flags are set.
    """
    crit = dict(SELECTION_CRITERIA)
    if criteria:
        crit.update(criteria)
    if crit.get("test_evaluated") or crit.get("selection_uses_r42_test"):
        raise ValueError("Selection must not use r4.2 test results")

    df = pd.DataFrame(candidate_rows)
    if df.empty:
        return {
            "selected": None,
            "reason": "no_candidates",
            "passed": [],
            "failed": [],
            "criteria": crit,
        }

    improve = float(crit["pr_auc_improvement_min"])
    tol = float(crit["pr_auc_noninferiority_tol"])
    fn_frac = float(crit["fn_reduction_min_frac"])
    fn_budget = float(baseline_fn) * (1.0 - fn_frac)

    passed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        pr = float(row["validation_pr_auc"])
        fn = float(row.get("validation_fn", np.nan))
        flags_ok = True
        if crit.get("no_seed_collapse") and bool(row.get("flag_seed_collapse", False)):
            flags_ok = False
        if crit.get("stable_thresholds_and_gates"):
            if bool(row.get("flag_threshold_instability", False)) or bool(
                row.get("flag_gate_collapse", False)
            ):
                flags_ok = False
        cond_improve = pr >= baseline_pr_auc + improve
        cond_noninf = (pr >= baseline_pr_auc - tol) and (fn <= fn_budget)
        ok = flags_ok and (cond_improve or cond_noninf)
        record = row.to_dict()
        record["selection_cond_improve"] = bool(cond_improve)
        record["selection_cond_noninferior_fn"] = bool(cond_noninf)
        record["selection_flags_ok"] = bool(flags_ok)
        if ok:
            passed.append(record)
        else:
            failed.append(record)

    selected = None
    reason = "none_passed"
    if passed:
        # Prefer largest PR-AUC, then fewest FN.
        passed_sorted = sorted(
            passed,
            key=lambda r: (-float(r["validation_pr_auc"]), float(r.get("validation_fn", 1e9))),
        )
        selected = passed_sorted[0].get("fusion_variant") or passed_sorted[0].get("model_id")
        reason = "passed_predefined_criteria"

    return {
        "selected": selected,
        "reason": reason,
        "passed": passed,
        "failed": failed,
        "baseline_pr_auc": baseline_pr_auc,
        "baseline_fn": baseline_fn,
        "criteria": crit,
        "test_evaluated": False,
    }
