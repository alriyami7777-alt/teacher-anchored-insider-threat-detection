"""EDITOR-017 protocol freeze. Written before any model result is viewed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from editor012_rescue.constants import (
    EXPECTED_TRAIN_SHA256,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_SHA256,
)
from editor012_rescue.safety import TRAIN_NPZ, VAL_NPZ, sha256_file

from .constants import (
    AUTHORITATIVE_GAUSSIAN,
    AUTHORITATIVE_SOURCE_ABLATION,
    BASE_COMMIT,
    CONTROLLED_GAUSSIAN_INPUT_NOISE,
    CONTROLLED_SOURCE_CHANNEL_ABLATION,
    DIRECTIONAL_KS,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    EDITOR015_RESULTS_COMMIT,
    EDITOR016_RESULTS_COMMIT,
    EXPECTED_SCALER_JSON_SHA256,
    FEASIBILITY_WORKTREE,
    FORBIDDEN_THREAT_TERMS,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    LEAF_TRACEABILITY,
    MODEL_SPECS,
    NOISE_LEVELS,
    NOISE_PERTURBATION_SEED,
    NOISE_SLOPE_DEFINITION,
    NOISE_SLOPE_LEVELS,
    ODST_PREDICTIVE_SUPERIORITY_OVER_LINEAR,
    PAPER_ROBUSTNESS_WORKTREE,
    PRIMARY_MODELS,
    PRIMARY_SEEDS,
    R52_PORTABILITY_WORKTREE,
    ROUTE_ANCHOR_INCREMENTAL_PREDICTIVE_EFFECT,
    ROUTE_FIDELITY_EFFECT,
    ROUTE_TRACEABILITY,
    SCALER_JSON,
    SOURCE_CHANNELS,
    TA2_GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    TA2_LOCAL_DIRECTIONAL_TREE_FAITHFULNESS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from .io_util import write_json
from .models import producing_pins, recover_frozen_thresholds
from .perturbations import perturbation_module_hashes, protocol_lock
from .safety import REPO_ROOT, REVIEW_ROOT, Editor017ProtocolError, utc_now


def _optional_sha(path: Path) -> str | None:
    if path.is_file():
        return sha256_file(path)
    return None


def build_perturbation_audit() -> dict[str, Any]:
    repo_hashes = perturbation_module_hashes(REPO_ROOT)
    paper_src = PAPER_ROBUSTNESS_WORKTREE / "scripts"
    feas_src = FEASIBILITY_WORKTREE / "scripts"
    port_src = R52_PORTABILITY_WORKTREE / "scripts"
    candidates = [
        {
            "candidate_id": "paper_r42_inverse_scale_source_ablation",
            "source_worktree": str(PAPER_ROBUSTNESS_WORKTREE),
            "path": str(paper_src / "objective3_missing_source_robustness.py"),
            "SHA256": _optional_sha(paper_src / "objective3_missing_source_robustness.py"),
            "exact_feature_treatment": "inverse_scale_raw_zero_then_forward_scale",
            "reference_replacement_value": "raw_0.0 -> scaled (-mean/scale)",
            "noise_distribution": None,
            "noise_scale_definition": None,
            "binary_feature_handling": "removed_source_has_star_set_raw_zero_then_rescale",
            "continuous_feature_handling": "removed_source_counts_raw_zero; total_events recomputed",
            "random_seed": "deterministic_no_RNG; PROTOCOL_SEED=20260724 elsewhere",
            "labels_change": False,
            "total_events_recomputed": True,
            "active_duration_changed": "zero_if_inactive_else_retain_residual_span",
            "channel_ablation_or_physical_absence": "CONTROLLED_SOURCE_CHANNEL_ABLATION",
            "dataset": "r4.2_producing; library_semantically_identical_in_editor017",
            "producing": True,
            "selected_for_editor017": False,
            "reason_not_selected": "r4.2_scaler_must_not_be_applied_to_r52_tensors",
        },
        {
            "candidate_id": "editor017_library_inverse_scale_with_r52_train_scaler",
            "source_worktree": str(REPO_ROOT),
            "path": str(REPO_ROOT / "src" / "objective3_missing_source_robustness.py"),
            "SHA256": repo_hashes["objective3_missing_source_robustness.py"],
            "exact_feature_treatment": "inverse_scale_raw_zero_then_forward_scale",
            "reference_replacement_value": "raw_0.0 -> scaled (-mean/scale) using EDITOR006A r5.2 TRAIN scaler",
            "noise_distribution": None,
            "noise_scale_definition": None,
            "binary_feature_handling": "removed_source_has_star_set_raw_zero_then_rescale",
            "continuous_feature_handling": "removed_source_counts_raw_zero; total_events recomputed in raw space",
            "random_seed": "deterministic_no_RNG",
            "labels_change": False,
            "total_events_recomputed": True,
            "active_duration_changed": "zero_if_inactive_else_retain_residual_span",
            "channel_ablation_or_physical_absence": "CONTROLLED_SOURCE_CHANNEL_ABLATION",
            "dataset": "r5.2_with_verified_TRAIN_scaler",
            "producing": False,
            "selected_for_editor017": True,
            "selection_rationale": (
                "Authoritative Objective-3 library implementation, now wired to the "
                "verified r5.2 TRAIN scaler. Historical r5.2 scaled-space zeroing was "
                "a documented fallback (scaled_space_zeroing_no_verified_scaler) and "
                "is not mixed into this branch."
            ),
        },
        {
            "candidate_id": "r52_portability_scaled_space_zero_source_ablation",
            "source_worktree": str(R52_PORTABILITY_WORKTREE if R52_PORTABILITY_WORKTREE.exists() else FEASIBILITY_WORKTREE),
            "path": str(
                (port_src if (port_src / "objective3_r52_explanation_robustness_portability").exists() else feas_src)
                / "objective3_r52_explanation_robustness_portability"
                / "analyses.py"
            ),
            "SHA256": _optional_sha(
                feas_src / "objective3_r52_explanation_robustness_portability" / "analyses.py"
            ),
            "exact_feature_treatment": "scaled_space_zeroing_no_verified_scaler",
            "reference_replacement_value": "literal_0.0_on_scaled_count_and_binary_channels",
            "noise_distribution": None,
            "noise_scale_definition": None,
            "binary_feature_handling": "zero_scaled_has_star_for_removed_source",
            "continuous_feature_handling": "zero_scaled_count; total_events = sum of scaled remaining counts",
            "random_seed": "deterministic_no_RNG",
            "labels_change": False,
            "total_events_recomputed": "partial_in_scaled_space",
            "active_duration_changed": False,
            "channel_ablation_or_physical_absence": "CONTROLLED_SOURCE_CHANNEL_ABLATION",
            "dataset": "r5.2_historical_producing_fallback",
            "producing": True,
            "selected_for_editor017": False,
            "reason_not_selected": (
                "Documented fallback used only because the r5.2 scaler was then unverified. "
                "EDITOR-017 has EDITOR006A and must not silently mix scaled-space zeroing "
                "with inverse-scale absence."
            ),
        },
        {
            "candidate_id": "paper_r42_bounded_continuous_gaussian_paired",
            "source_worktree": str(PAPER_ROBUSTNESS_WORKTREE),
            "path": str(paper_src / "objective3_perturbations.py"),
            "SHA256": _optional_sha(paper_src / "objective3_perturbations.py"),
            "exact_feature_treatment": "add_bounded_gaussian_to_continuous_indices_0_to_6",
            "reference_replacement_value": None,
            "noise_distribution": "gaussian_elementwise_clipped",
            "noise_scale_definition": "std=level*max(|x|,1e-3); clip +/- level*scale; floor at 0",
            "binary_feature_handling": "untouched",
            "continuous_feature_handling": "indices_0_to_6_only",
            "random_seed": "apply_paired_perturbation perturbation_seed=101",
            "labels_change": False,
            "total_events_recomputed": False,
            "active_duration_changed": False,
            "channel_ablation_or_physical_absence": None,
            "dataset": "r4.2_producing",
            "producing": True,
            "selected_for_editor017": False,
            "reason_not_selected": "same_function_as_editor017_library; editor017_copy_is_the_gated_source",
        },
        {
            "candidate_id": "editor017_library_bounded_continuous_gaussian_paired",
            "source_worktree": str(REPO_ROOT),
            "path": str(REPO_ROOT / "src" / "objective3_perturbations.py"),
            "SHA256": repo_hashes["objective3_perturbations.py"],
            "exact_feature_treatment": "add_bounded_gaussian_to_continuous_indices_0_to_6",
            "reference_replacement_value": None,
            "noise_distribution": "gaussian_elementwise_clipped",
            "noise_scale_definition": "std=level*max(|x|,1e-3); clip +/- level*scale; floor at 0",
            "binary_feature_handling": "untouched",
            "continuous_feature_handling": "indices_0_to_6_only",
            "random_seed": f"apply_paired_perturbation perturbation_seed={NOISE_PERTURBATION_SEED}",
            "labels_change": False,
            "total_events_recomputed": False,
            "active_duration_changed": False,
            "channel_ablation_or_physical_absence": None,
            "dataset": "r5.2",
            "producing": False,
            "selected_for_editor017": True,
            "selection_rationale": (
                "Authoritative Objective-3 Gaussian implementation. Historical severity "
                f"levels {list(NOISE_LEVELS)} are used unchanged. Paired RNG is required "
                "for multi-model comparison and is the paper protocol."
            ),
        },
        {
            "candidate_id": "r52_portability_bounded_gaussian_unpaired_seed101",
            "source_worktree": str(FEASIBILITY_WORKTREE),
            "path": str(feas_src / "objective3_r52_explanation_robustness_portability" / "analyses.py"),
            "SHA256": _optional_sha(
                feas_src / "objective3_r52_explanation_robustness_portability" / "analyses.py"
            ),
            "exact_feature_treatment": "same_bounded_continuous_gaussian",
            "reference_replacement_value": None,
            "noise_distribution": "gaussian_elementwise_clipped",
            "noise_scale_definition": "std=level*max(|x|,1e-3); clip +/- level*scale; floor at 0",
            "binary_feature_handling": "untouched",
            "continuous_feature_handling": "indices_0_to_6_only",
            "random_seed": "apply_perturbation seed=101 (NOT paired derivation)",
            "labels_change": False,
            "total_events_recomputed": False,
            "active_duration_changed": False,
            "channel_ablation_or_physical_absence": None,
            "dataset": "r5.2_historical_producing",
            "producing": True,
            "selected_for_editor017": False,
            "reason_not_selected": "unpaired_seed_is_not_the_paper_paired_protocol; function_is_the_same",
        },
        {
            "candidate_id": "odst_value_audit_additive_all_feature_gaussian",
            "source_worktree": str(FEASIBILITY_WORKTREE),
            "path": str(feas_src / "objective2_r52_odst_vs_attention_linear_value_audit" / "forward_analyses.py"),
            "SHA256": _optional_sha(
                feas_src / "objective2_r52_odst_vs_attention_linear_value_audit" / "forward_analyses.py"
            ),
            "exact_feature_treatment": "additive_N(0,level)_on_all_13_features",
            "reference_replacement_value": None,
            "noise_distribution": "unbounded_gaussian_all_features",
            "noise_scale_definition": "std=level on already-scaled tensor including binaries",
            "binary_feature_handling": "also_noised",
            "continuous_feature_handling": "also_noised",
            "random_seed": "NOISE_SEED=101 plus model seed",
            "labels_change": False,
            "total_events_recomputed": False,
            "active_duration_changed": False,
            "channel_ablation_or_physical_absence": None,
            "dataset": "r5.2",
            "producing": True,
            "selected_for_editor017": False,
            "reason_not_selected": "different_severity_profile_not_paper_compatible",
        },
    ]
    selected = [c for c in candidates if c.get("selected_for_editor017")]
    selected_source = [c for c in selected if "inverse_scale" in c["candidate_id"] or "source_ablation" in c["candidate_id"]]
    selected_noise = [c for c in selected if "gaussian" in c["candidate_id"]]
    if len(selected_source) != 1 or len(selected_noise) != 1:
        raise Editor017ProtocolError("exactly one source and one Gaussian implementation must be selected")
    return {
        "ROBUSTNESS_BRANCH": "AUTHORISED",
        "PERTURBATION_PROTOCOL_RECOVERED": True,
        "selection_locked_before_results": True,
        "selected_source_ablation": selected_source[0]["candidate_id"],
        "selected_gaussian": selected_noise[0]["candidate_id"],
        "terminology": {
            "source": CONTROLLED_SOURCE_CHANNEL_ABLATION,
            "noise": CONTROLLED_GAUSSIAN_INPUT_NOISE,
            "forbidden": list(FORBIDDEN_THREAT_TERMS),
        },
        "candidates": candidates,
        "module_hashes_in_this_worktree": repo_hashes,
        "scaler_sha256": EXPECTED_SCALER_JSON_SHA256,
        "written_at": utc_now(),
    }


def freeze_protocol(*, y_val: Any | None = None) -> dict[str, Any]:
    from .safety import REVIEW_ROOT

    review = REVIEW_ROOT
    (review / "00_protocol").mkdir(parents=True, exist_ok=True)
    audit = build_perturbation_audit()
    write_json(review / "00_protocol" / "EDITOR017_PERTURBATION_PROTOCOL_AUDIT.json", audit)

    pins = producing_pins()
    artefacts = []
    for alias, spec in MODEL_SPECS.items():
        for seed in PRIMARY_SEEDS:
            ck = spec["checkpoints"][seed]
            artefacts.append(
                {
                    "role": f"{alias}/{seed}",
                    "path": str(ck["checkpoint"]),
                    "SHA256": ck["sha256"],
                    "exists": Path(ck["checkpoint"]).is_file(),
                }
            )
            artefacts.append(
                {
                    "role": f"{alias}_val_logits/{seed}",
                    "path": str(spec["val_logits"][seed]),
                    "exists": Path(spec["val_logits"][seed]).is_file(),
                }
            )
    artefacts.append(
        {
            "role": "r52_TRAIN",
            "path": str(TRAIN_NPZ),
            "SHA256": EXPECTED_TRAIN_SHA256,
            "exists": TRAIN_NPZ.is_file(),
        }
    )
    artefacts.append(
        {
            "role": "r52_VALIDATION",
            "path": str(VAL_NPZ),
            "SHA256": EXPECTED_VAL_SHA256,
            "exists": VAL_NPZ.is_file(),
        }
    )
    artefacts.append(
        {
            "role": "r52_TRAIN_scaler",
            "path": str(SCALER_JSON),
            "SHA256": EXPECTED_SCALER_JSON_SHA256,
            "exists": Path(SCALER_JSON).is_file(),
        }
    )
    register = {
        "task_id": "EDITOR-017",
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
        "EDITOR015_RESULTS_COMMIT": EDITOR015_RESULTS_COMMIT,
        "EDITOR016_RESULTS_COMMIT": EDITOR016_RESULTS_COMMIT,
        "BASE_COMMIT": BASE_COMMIT,
        "historical_packets_readonly": True,
        "no_merge": True,
        "no_push": True,
        "no_new_training": True,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "ROUTE_ANCHOR_INCREMENTAL_PREDICTIVE_EFFECT": ROUTE_ANCHOR_INCREMENTAL_PREDICTIVE_EFFECT,
        "ROUTE_FIDELITY_EFFECT": ROUTE_FIDELITY_EFFECT,
        "ODST_PREDICTIVE_SUPERIORITY_OVER_LINEAR": ODST_PREDICTIVE_SUPERIORITY_OVER_LINEAR,
        "TA2_LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": TA2_LOCAL_DIRECTIONAL_TREE_FAITHFULNESS,
        "TA2_GLOBAL_TOPK_PR_AUC_FAITHFULNESS": TA2_GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        "ROUTE_TRACEABILITY": ROUTE_TRACEABILITY,
        "LEAF_TRACEABILITY": LEAF_TRACEABILITY,
        "producing_pins": pins,
        "artefacts": artefacts,
        "r52_test_opened": False,
        "r51_rerun": False,
        "r62_rerun": False,
    }
    write_json(review / "00_protocol" / "EDITOR017_SOURCE_REGISTER.json", register)

    protocol = {
        "task_id": "EDITOR-017",
        "evaluation_mode": "frozen_checkpoint_only",
        "partitions": {"train": "AUTHORISED", "validation": "AUTHORISED", "test": "HARD_DENY"},
        "models": PRIMARY_MODELS,
        "seeds": list(PRIMARY_SEEDS),
        "source_channels": list(SOURCE_CHANNELS),
        "noise_levels": list(NOISE_LEVELS),
        "noise_slope_levels": list(NOISE_SLOPE_LEVELS),
        "noise_slope_definition": NOISE_SLOPE_DEFINITION,
        "noise_slope_frozen_before_results": True,
        "directional_k": list(DIRECTIONAL_KS),
        "directional_references": "r5.2 TRAIN only",
        "directional_random_control": "same-sign eligible trees only",
        "bootstrap": {
            "n_users": 2000,
            "windows_per_user": 32,
            "malicious_users": 31,
            "mapping_sha256": EXPECTED_USER_MAPPING_SHA256,
            "n_resamples": 2000,
            "rng_seed": 42,
            "sampling_unit": "validation user",
        },
        "perturbation_lock": protocol_lock(),
        "authoritative_source_ablation": AUTHORITATIVE_SOURCE_ABLATION,
        "authoritative_gaussian": AUTHORITATIVE_GAUSSIAN,
        "fixed_feature_explanation_stability": (
            "NOT_AVAILABLE_no_ODST_native_original_feature_importance_for_M0_M3"
        ),
        "tree_identities_across_seeds": "FORBIDDEN",
        "threshold_retuning": False,
        "parameter_update": False,
        "terminology_lock": {
            "allowed": [
                CONTROLLED_SOURCE_CHANNEL_ABLATION,
                CONTROLLED_GAUSSIAN_INPUT_NOISE,
                "DEGRADED_INPUT_RESILIENCE",
                "DATA_QUALITY_SENSITIVITY",
            ],
            "forbidden": list(FORBIDDEN_THREAT_TERMS),
        },
        "written_at": utc_now(),
    }
    write_json(review / "00_protocol" / "EDITOR017_PROTOCOL.json", protocol)

    checksums = {
        "train_npz": EXPECTED_TRAIN_SHA256,
        "validation_npz": EXPECTED_VAL_SHA256,
        "scaler_json": EXPECTED_SCALER_JSON_SHA256,
        "user_mapping": EXPECTED_USER_MAPPING_SHA256,
        "producing_pins": pins,
        "perturbation_modules": perturbation_module_hashes(REPO_ROOT),
        "checkpoints": {
            f"{alias}/{seed}": spec["checkpoints"][seed]["sha256"]
            for alias, spec in MODEL_SPECS.items()
            for seed in PRIMARY_SEEDS
        },
    }
    write_json(review / "00_protocol" / "EDITOR017_INPUT_CHECKSUMS.json", checksums)

    thresholds = None
    if y_val is not None:
        thresholds = recover_frozen_thresholds(y_val)
        write_json(
            review / "00_protocol" / "EDITOR017_FROZEN_THRESHOLDS.json",
            {alias: {str(s): t for s, t in seeds.items()} for alias, seeds in thresholds.items()},
        )
    return {
        "audit": audit,
        "register": register,
        "protocol": protocol,
        "checksums": checksums,
        "thresholds": thresholds,
    }
