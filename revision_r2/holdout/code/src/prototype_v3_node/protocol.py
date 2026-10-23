"""Protocol and continuation policy for Prototype V3 NODE."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .architecture import (
    FUSION_VARIANTS,
    MAX_RESIDUAL_SCALE,
    SEED42_COMPARISON_VARIANTS,
    VARIANT_EQUATIONS,
)
from .odst import (
    ABLATION_EQUATIONS,
    CANONICAL_NODE_EQUATIONS,
    NODE_EQUATIONS,
    summarize_odst_shapes,
)

SEEDS = (42, 52, 62)

CONTINUATION_CRITERIA = {
    "pr_auc_improvement_min": 0.005,
    "pr_auc_noninferiority_tol": 0.005,
    "fn_reduction_min_frac": 0.10,
    "require_higher_f1_without_recall_drop": True,
    "unfreeze_encoder_only_if_met": True,
}

CONTINUATION_CRITERIA_DOC = [
    "Unfreeze Bi-LSTM / temporal attention ONLY if a frozen NODE variant "
    "improves validation over attention_linear_reference by at least one of:",
    "1) PR-AUC improvement >= 0.005; OR",
    "2) PR-AUC within 0.005 of reference AND FN reduced by >= 10%; OR",
    "3) Higher F1 without reducing recall.",
    "Primary first experiment: canonical_entmax15_node (encoder frozen).",
    "Residual/gated variants deferred until primary NODE is competitive.",
]

EXPECTED_ATTENTION_LINEAR_SEED42 = {
    "pr_auc": 0.7900480700496382,
    "f1": 0.8016032064128257,
    "threshold": 0.92,
    "fp": 47,
    "fn": 52,
}


def evaluate_continuation(
    candidate: dict[str, Any],
    reference: dict[str, Any],
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    crit = dict(CONTINUATION_CRITERIA)
    if criteria:
        crit.update(criteria)

    cand_pr = float(candidate["pr_auc"])
    ref_pr = float(reference["pr_auc"])
    cand_fn = float(candidate["fn"])
    ref_fn = float(reference["fn"])
    cand_f1 = float(candidate["f1"])
    ref_f1 = float(reference["f1"])
    cand_rec = float(candidate["recall"])
    ref_rec = float(reference["recall"])

    c1 = cand_pr >= ref_pr + float(crit["pr_auc_improvement_min"])
    c2 = (
        cand_pr >= ref_pr - float(crit["pr_auc_noninferiority_tol"])
        and ref_fn > 0
        and (ref_fn - cand_fn) / ref_fn >= float(crit["fn_reduction_min_frac"])
    )
    c3 = cand_f1 > ref_f1 and cand_rec >= ref_rec

    met = bool(c1 or c2 or c3)
    return {
        "meets_continuation": met,
        "criterion_1_pr_auc_improvement": bool(c1),
        "criterion_2_noninferior_fn_reduction": bool(c2),
        "criterion_3_higher_f1_no_recall_drop": bool(c3),
        "candidate_pr_auc": cand_pr,
        "reference_pr_auc": ref_pr,
        "delta_pr_auc": cand_pr - ref_pr,
        "candidate_fn": cand_fn,
        "reference_fn": ref_fn,
        "fn_reduction_frac": ((ref_fn - cand_fn) / ref_fn) if ref_fn else float("nan"),
        "recommendation": (
            "Eligible to consider unfreezing the encoder after frozen NODE improves."
            if met
            else (
                "Frozen NODE has not yet improved validation; keep encoder frozen "
                "and do not launch encoder fine-tuning."
            )
        ),
        "criteria": crit,
    }


def build_protocol_manifest(
    *,
    output_dir: Path,
    seeds: tuple[int, ...] = SEEDS,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prototype": "v3_node",
        "name": "Bi-LSTM → temporal attention → canonical NODE/ODST (entmax15)",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "training_started": False,
        "test_evaluated": False,
        "selection_uses_r42_test": False,
        "splits_allowed": ["train", "validation"],
        "splits_forbidden": ["test"],
        "releases_forbidden": ["r5.2", "r6.2"],
        "dataset": "CERT r4.2",
        "fusion_variants": list(FUSION_VARIANTS),
        "seed42_comparison_variants": list(SEED42_COMPARISON_VARIANTS),
        "variant_equations": dict(VARIANT_EQUATIONS),
        "primary_first_experiment": "canonical_entmax15_node",
        "canonical_choice_function": "entmax15 + entmoid15",
        "ablation_choice_function": "sparsemax_sigmoid_odst",
        "canonical_readout": "canonical_tree_average",
        "ablation_readout": "dense_linear_readout",
        "begin_with_seed": 42,
        "seeds": list(seeds),
        "max_residual_scale": MAX_RESIDUAL_SCALE,
        "node_equations": dict(CANONICAL_NODE_EQUATIONS),
        "ablation_equations": dict(ABLATION_EQUATIONS),
        "node_equations_alias": dict(NODE_EQUATIONS),
        "node_default_shapes": summarize_odst_shapes(
            choice_function="entmax15",
            readout="canonical_tree_average",
        ),
        "expected_attention_linear_seed42": dict(EXPECTED_ATTENTION_LINEAR_SEED42),
        "backbone_policy": {
            "first_experiment": "freeze_bilstm_and_temporal_attention",
            "train_only": ["node_odst_head"],
            "unfreeze_encoder_only_if_frozen_node_improves_validation": True,
            "residual_gated_deferred_until_primary_competitive": True,
        },
        "selection": {
            "checkpoint": "validation_pr_auc",
            "operating_threshold": "validation_f1",
        },
        "continuation_criteria": dict(CONTINUATION_CRITERIA),
        "continuation_criteria_doc": list(CONTINUATION_CRITERIA_DOC),
        "output_namespace": str(output_dir),
        "preserves_prior_artefacts": True,
        "pretrained_encoder": {
            "seed_42": "outputs/baselines/sequence_ensemble/stage11_A_attn_linear/best.pt",
            "seed_52": "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed52/best.pt",
            "seed_62": "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed62/best.pt",
        },
    }
    if extra:
        payload.update(extra)
    return payload


def write_protocol_manifest(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload.get("test_evaluated") is not False:
        raise ValueError("V3 protocol manifest must have test_evaluated=false")
    if payload.get("training_started") is None:
        raise ValueError("V3 protocol manifest must declare training_started")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
