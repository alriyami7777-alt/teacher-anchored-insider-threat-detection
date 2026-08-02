#!/usr/bin/env python3
"""Hash-pinned Objective 3 model registry (ODST + attention–linear).

Selected architectures only. Soft-forest and classical RF/XGBoost are not
registered here. Checkpoint paths and SHA-256 digests are explicit — there is
no “latest file” discovery.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from objective3_odst_loader import SELECTED_ODST_CHECKPOINTS

ArchitectureId = Literal[
    "bi_lstm_attention_sparsemax_sigmoid_odst",
    "bi_lstm_attention_linear",
]
DatasetVersion = Literal["r4.2", "r5.2"]
PartitionRole = Literal[
    "r42_development",
    "r52_validation",
    "synthetic_test_only",
]
CapabilityStatus = Literal[
    "available_now",
    "interface_available_not_validated",
    "planned",
    "not_yet_validated",
    "unsupported",
]

PRIMARY_ARCHITECTURE: ArchitectureId = "bi_lstm_attention_sparsemax_sigmoid_odst"
NEURAL_REFERENCE_ARCHITECTURE: ArchitectureId = "bi_lstm_attention_linear"

SUPPORTED_SEEDS: tuple[int, ...] = (42, 52, 62)
SEQUENCE_LENGTH = 20
FEATURE_COUNT = 13

# Partition roles that may be requested at this implementation stage.
PERMITTED_PARTITION_ROLES: frozenset[str] = frozenset(
    {"r42_development", "r52_validation", "synthetic_test_only"}
)

# Explicitly protected — raise unless a future guarded protocol enables them.
PROTECTED_PARTITION_ROLES: frozenset[str] = frozenset(
    {
        "r52_test",
        "r5.2_test",
        "r52_guarded_test",
        "r62_external_stress",
        "r6.2",
        "r62",
    }
)

# Superseded Objective 3 pilot model ids (not selectable via this registry).
LEGACY_SUPERSEDED_MODEL_IDS: frozenset[str] = frozenset(
    {
        "joint_bilstm_attention_soft_forest",
        "standalone_bilstm",
        "fragmented_bilstm_xgboost",
        # historical alias retained for documentation only
        "soft_decision_forest",
        "standalone_soft_forest",
    }
)


@dataclass(frozen=True)
class ExplanationCapabilities:
    supports_attention_weights: CapabilityStatus = "unsupported"
    supports_pooled_representation: CapabilityStatus = "unsupported"
    supports_native_feature_selection: CapabilityStatus = "unsupported"
    supports_native_routing: CapabilityStatus = "unsupported"
    supports_leaf_probabilities: CapabilityStatus = "unsupported"
    supports_tree_outputs: CapabilityStatus = "unsupported"
    supports_input_gradients: CapabilityStatus = "planned"
    supports_integrated_gradients: CapabilityStatus = "not_yet_validated"
    supports_feature_masking: CapabilityStatus = "interface_available_not_validated"
    supports_timestep_masking: CapabilityStatus = "interface_available_not_validated"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class RobustnessCapabilities:
    supports_feature_channel_masking: CapabilityStatus = "interface_available_not_validated"
    supports_grouped_log_source_masking: CapabilityStatus = "interface_available_not_validated"
    supports_timestep_masking: CapabilityStatus = "interface_available_not_validated"
    supports_high_attention_timestep_deletion: CapabilityStatus = "planned"
    supports_low_attention_timestep_deletion: CapabilityStatus = "planned"
    supports_odst_ranked_feature_deletion: CapabilityStatus = "planned"
    supports_random_deletion_controls: CapabilityStatus = "interface_available_not_validated"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _odst_explanation_caps() -> ExplanationCapabilities:
    return ExplanationCapabilities(
        supports_attention_weights="available_now",
        supports_pooled_representation="available_now",
        supports_native_feature_selection="available_now",
        supports_native_routing="available_now",
        supports_leaf_probabilities="available_now",
        supports_tree_outputs="available_now",
        supports_input_gradients="planned",
        supports_integrated_gradients="not_yet_validated",
        supports_feature_masking="interface_available_not_validated",
        supports_timestep_masking="interface_available_not_validated",
    )


def _attn_linear_explanation_caps() -> ExplanationCapabilities:
    return ExplanationCapabilities(
        supports_attention_weights="available_now",
        supports_pooled_representation="available_now",
        supports_native_feature_selection="unsupported",
        supports_native_routing="unsupported",
        supports_leaf_probabilities="unsupported",
        supports_tree_outputs="unsupported",
        supports_input_gradients="planned",
        supports_integrated_gradients="not_yet_validated",
        supports_feature_masking="interface_available_not_validated",
        supports_timestep_masking="interface_available_not_validated",
    )


def _robustness_caps(*, odst: bool) -> RobustnessCapabilities:
    return RobustnessCapabilities(
        supports_feature_channel_masking="interface_available_not_validated",
        supports_grouped_log_source_masking="interface_available_not_validated",
        supports_timestep_masking="interface_available_not_validated",
        supports_high_attention_timestep_deletion="planned",
        supports_low_attention_timestep_deletion="planned",
        supports_odst_ranked_feature_deletion="planned" if odst else "unsupported",
        supports_random_deletion_controls="interface_available_not_validated",
    )


@dataclass(frozen=True)
class Objective3ModelRegistryEntry:
    model_id: ArchitectureId
    display_name: str
    architecture_family: str
    dataset_version: DatasetVersion
    seed: int
    checkpoint_path: str
    checkpoint_sha256: str
    loader_type: Literal["odst", "attention_linear"]
    threshold_metadata_path: str | None
    sequence_length: int = SEQUENCE_LENGTH
    feature_count: int = FEATURE_COUNT
    explanation_capabilities: ExplanationCapabilities = field(
        default_factory=_odst_explanation_caps
    )
    robustness_capabilities: RobustnessCapabilities = field(
        default_factory=lambda: _robustness_caps(odst=True)
    )
    protocol_identifier: str = ""
    registry_key: str = ""
    default_partition_role: PartitionRole = "r42_development"

    def to_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "registry_key": self.registry_key,
            "model_id": self.model_id,
            "display_name": self.display_name,
            "architecture_family": self.architecture_family,
            "dataset_version": self.dataset_version,
            "seed": self.seed,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_sha256": self.checkpoint_sha256,
            "loader_type": self.loader_type,
            "threshold_metadata_path": self.threshold_metadata_path or "",
            "sequence_length": self.sequence_length,
            "feature_count": self.feature_count,
            "protocol_identifier": self.protocol_identifier,
            "default_partition_role": self.default_partition_role,
        }
        row.update({f"expl_{k}": v for k, v in self.explanation_capabilities.to_dict().items()})
        row.update({f"rob_{k}": v for k, v in self.robustness_capabilities.to_dict().items()})
        return row


# Audited attention–linear checkpoints (SHA-256 from audit manifest / file hash).
_ATTENTION_LINEAR_CHECKPOINTS: dict[str, dict[str, Any]] = {
    "attn_lin_r42_s42": {
        "path": "outputs/baselines/sequence_ensemble/stage11_A_attn_linear/best.pt",
        "dataset_version": "r4.2",
        "seed": 42,
        "expected_sha256": "7e2f33d579405e9425e5eb63f3aad241d303d52fd2731db7f79b5eb4c5550ec2",
        "threshold_metadata_path": "outputs/baselines/sequence_ensemble/stage11_A_attn_linear/threshold.json",
        "protocol_identifier": "r42_development_attention_linear_reference",
        "default_partition_role": "r42_development",
    },
    "attn_lin_r42_s52": {
        "path": "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed52/best.pt",
        "dataset_version": "r4.2",
        "seed": 52,
        "expected_sha256": "0d83945dc0da22011dff9b37aadf7beecf9e101260d6946aa6ccc61d6edb3925",
        "threshold_metadata_path": "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed52/threshold.json",
        "protocol_identifier": "r42_development_attention_linear_reference",
        "default_partition_role": "r42_development",
    },
    "attn_lin_r42_s62": {
        "path": "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed62/best.pt",
        "dataset_version": "r4.2",
        "seed": 62,
        "expected_sha256": "4428d4532481fe68784ecbfb1b6610ed3ff4f35b35af63b5650865c994da30c9",
        "threshold_metadata_path": "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed62/threshold.json",
        "protocol_identifier": "r42_development_attention_linear_reference",
        "default_partition_role": "r42_development",
    },
    "attn_lin_r52_s42": {
        "path": "outputs/objective2/r52_odst_confirmation/attention_linear_seed42/best.pt",
        "dataset_version": "r5.2",
        "seed": 42,
        "expected_sha256": "b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53",
        "threshold_metadata_path": "outputs/objective2/r52_odst_confirmation/attention_linear_seed42/threshold.json",
        "protocol_identifier": "r52_validation_attention_linear_reference",
        "default_partition_role": "r52_validation",
    },
    "attn_lin_r52_s52": {
        "path": "outputs/objective2/r52_odst_confirmation/attention_linear_seed52/best.pt",
        "dataset_version": "r5.2",
        "seed": 52,
        "expected_sha256": "5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c",
        "threshold_metadata_path": "outputs/objective2/r52_odst_confirmation/attention_linear_seed52/threshold.json",
        "protocol_identifier": "r52_validation_attention_linear_reference",
        "default_partition_role": "r52_validation",
    },
    "attn_lin_r52_s62": {
        "path": "outputs/objective2/r52_odst_confirmation/attention_linear_seed62/best.pt",
        "dataset_version": "r5.2",
        "seed": 62,
        "expected_sha256": "4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a",
        "threshold_metadata_path": "outputs/objective2/r52_odst_confirmation/attention_linear_seed62/threshold.json",
        "protocol_identifier": "r52_validation_attention_linear_reference",
        "default_partition_role": "r52_validation",
    },
}


def _normalise_dataset_version(dataset_version: str) -> DatasetVersion:
    text = str(dataset_version).strip().lower().replace("cert ", "").replace("cert_", "")
    text = text.replace("r42", "r4.2").replace("r52", "r5.2")
    if text in {"4.2", "r4.2"}:
        return "r4.2"
    if text in {"5.2", "r5.2"}:
        return "r5.2"
    raise ValueError(
        f"Unsupported dataset_version={dataset_version!r}; expected 'r4.2' or 'r5.2'"
    )


def _threshold_path_beside_checkpoint(checkpoint_path: str) -> str:
    parent = "/".join(checkpoint_path.replace("\\", "/").split("/")[:-1])
    return f"{parent}/threshold.json"


def _build_registry() -> dict[str, Objective3ModelRegistryEntry]:
    entries: dict[str, Objective3ModelRegistryEntry] = {}

    for meta in SELECTED_ODST_CHECKPOINTS.values():
        ds = _normalise_dataset_version(meta["dataset_version"])
        seed = int(meta["seed"])
        key = f"{PRIMARY_ARCHITECTURE}|{ds}|{seed}"
        entries[key] = Objective3ModelRegistryEntry(
            model_id=PRIMARY_ARCHITECTURE,
            display_name="Bi-LSTM–attention–sparsemax–sigmoid ODST",
            architecture_family="sequence_odst",
            dataset_version=ds,
            seed=seed,
            checkpoint_path=meta["path"],
            checkpoint_sha256=meta["expected_sha256"],
            loader_type="odst",
            threshold_metadata_path=_threshold_path_beside_checkpoint(meta["path"]),
            explanation_capabilities=_odst_explanation_caps(),
            robustness_capabilities=_robustness_caps(odst=True),
            protocol_identifier=(
                "r42_development_selected_odst"
                if ds == "r4.2"
                else "r52_validation_selected_odst"
            ),
            registry_key=key,
            default_partition_role="r42_development" if ds == "r4.2" else "r52_validation",
        )

    for meta in _ATTENTION_LINEAR_CHECKPOINTS.values():
        ds = _normalise_dataset_version(meta["dataset_version"])
        seed = int(meta["seed"])
        key = f"{NEURAL_REFERENCE_ARCHITECTURE}|{ds}|{seed}"
        entries[key] = Objective3ModelRegistryEntry(
            model_id=NEURAL_REFERENCE_ARCHITECTURE,
            display_name="Bi-LSTM–attention–linear",
            architecture_family="sequence_attention_linear",
            dataset_version=ds,
            seed=seed,
            checkpoint_path=meta["path"],
            checkpoint_sha256=meta["expected_sha256"],
            loader_type="attention_linear",
            threshold_metadata_path=meta.get("threshold_metadata_path"),
            explanation_capabilities=_attn_linear_explanation_caps(),
            robustness_capabilities=_robustness_caps(odst=False),
            protocol_identifier=str(meta["protocol_identifier"]),
            registry_key=key,
            default_partition_role=meta["default_partition_role"],
        )

    return entries


OBJECTIVE3_MODEL_REGISTRY: dict[str, Objective3ModelRegistryEntry] = _build_registry()


def list_registry_entries() -> list[Objective3ModelRegistryEntry]:
    return sorted(
        OBJECTIVE3_MODEL_REGISTRY.values(),
        key=lambda e: (e.model_id, e.dataset_version, e.seed),
    )


def get_registry_entry(
    model_id: str,
    dataset_version: str,
    seed: int,
) -> Objective3ModelRegistryEntry:
    if model_id in LEGACY_SUPERSEDED_MODEL_IDS or model_id == "attention_linear":
        # Historical pilot id "attention_linear" is not the selected registry id.
        if model_id == "attention_linear":
            raise KeyError(
                "Model id 'attention_linear' is a legacy pilot alias. "
                f"Use {NEURAL_REFERENCE_ARCHITECTURE!r} via the Objective 3 registry."
            )
        raise KeyError(
            f"Model id {model_id!r} is superseded_model_only and is not in the "
            "selected Objective 3 registry (ODST + attention–linear)."
        )
    if model_id not in {PRIMARY_ARCHITECTURE, NEURAL_REFERENCE_ARCHITECTURE}:
        raise KeyError(
            f"Unsupported model_id={model_id!r}; expected "
            f"{PRIMARY_ARCHITECTURE!r} or {NEURAL_REFERENCE_ARCHITECTURE!r}"
        )
    ds = _normalise_dataset_version(dataset_version)
    seed_i = int(seed)
    if seed_i not in SUPPORTED_SEEDS:
        raise KeyError(
            f"Unsupported seed={seed_i}; expected one of {SUPPORTED_SEEDS}"
        )
    key = f"{model_id}|{ds}|{seed_i}"
    if key not in OBJECTIVE3_MODEL_REGISTRY:
        raise KeyError(f"No registry entry for {key}")
    return OBJECTIVE3_MODEL_REGISTRY[key]


def assert_partition_role_permitted(partition_role: str) -> PartitionRole:
    role = str(partition_role).strip()
    if role in PROTECTED_PARTITION_ROLES or role.lower() in PROTECTED_PARTITION_ROLES:
        raise ProtectedPartitionError(
            f"Partition role {role!r} is protected (r5.2 test / r6.2). "
            "Explicit future guarded protocol required; synthetic_test_only is "
            "the only permitted test role for this integration stage."
        )
    if role not in PERMITTED_PARTITION_ROLES:
        raise ValueError(
            f"Unknown partition_role={role!r}; permitted: "
            f"{sorted(PERMITTED_PARTITION_ROLES)}"
        )
    return role  # type: ignore[return-value]


class ProtectedPartitionError(PermissionError):
    """Raised when a caller requests a protected r5.2 test or r6.2 path."""


def registry_row_count() -> int:
    return len(OBJECTIVE3_MODEL_REGISTRY)


def registry_counts_by_architecture() -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in OBJECTIVE3_MODEL_REGISTRY.values():
        counts[entry.model_id] = counts.get(entry.model_id, 0) + 1
    return counts


__all__ = [
    "ArchitectureId",
    "CapabilityStatus",
    "DatasetVersion",
    "ExplanationCapabilities",
    "FEATURE_COUNT",
    "LEGACY_SUPERSEDED_MODEL_IDS",
    "NEURAL_REFERENCE_ARCHITECTURE",
    "OBJECTIVE3_MODEL_REGISTRY",
    "Objective3ModelRegistryEntry",
    "PERMITTED_PARTITION_ROLES",
    "PRIMARY_ARCHITECTURE",
    "PROTECTED_PARTITION_ROLES",
    "PartitionRole",
    "ProtectedPartitionError",
    "RobustnessCapabilities",
    "SEQUENCE_LENGTH",
    "SUPPORTED_SEEDS",
    "assert_partition_role_permitted",
    "get_registry_entry",
    "list_registry_entries",
    "registry_counts_by_architecture",
    "registry_row_count",
]
