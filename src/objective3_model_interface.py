#!/usr/bin/env python3
"""Common Objective 3 model loading and inference (ODST + attention–linear).

Dispatches to ``objective3_odst_loader`` for ODST and a verified attention–linear
loader for the neural reference. Soft-forest stand-in paths are not used.

Synthetic tensors only during integration tests. No dataset loading, no training,
no real CERT access.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

from models.sequence_ensemble import SequenceEnsembleModel
from objective3_model_registry import (
    FEATURE_COUNT,
    NEURAL_REFERENCE_ARCHITECTURE,
    PRIMARY_ARCHITECTURE,
    SEQUENCE_LENGTH,
    ExplanationCapabilities,
    Objective3ModelRegistryEntry,
    ProtectedPartitionError,
    assert_partition_role_permitted,
    get_registry_entry,
)
from objective3_odst_loader import (
    StateDictCompatibilityReport,
    load_objective3_odst_checkpoint,
    repo_root,
    resolve_checkpoint_path,
    sha256_file,
)

UNAVAILABLE = "unavailable"


@dataclass
class Objective3LoadedModel:
    model: nn.Module
    model_id: str
    architecture: str
    dataset_version: str
    seed: int
    checkpoint_path: str
    checkpoint_hash: str
    configuration: dict[str, Any]
    threshold_metadata_path: str | None
    explanation_capabilities: ExplanationCapabilities
    compatibility: StateDictCompatibilityReport | dict[str, Any]
    loader_type: str
    registry_entry: Objective3ModelRegistryEntry
    device: str
    partition_role: str

    def to_metadata_dict(self) -> dict[str, Any]:
        compat = self.compatibility
        if isinstance(compat, StateDictCompatibilityReport):
            compat_out: Any = asdict(compat)
        else:
            compat_out = compat
        return {
            "model_id": self.model_id,
            "architecture": self.architecture,
            "dataset_version": self.dataset_version,
            "seed": self.seed,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_hash": self.checkpoint_hash,
            "configuration": self.configuration,
            "threshold_metadata_path": self.threshold_metadata_path,
            "explanation_capabilities": self.explanation_capabilities.to_dict(),
            "compatibility": compat_out,
            "loader_type": self.loader_type,
            "device": self.device,
            "partition_role": self.partition_role,
        }


@dataclass
class Objective3InferenceResult:
    # Model output
    logits: torch.Tensor
    probabilities: torch.Tensor
    predicted_labels: torch.Tensor | None
    threshold_used: float | None

    # Sequence representation
    pooled_representation: torch.Tensor | None
    sequence_hidden_states: torch.Tensor | None
    timestep_mask: torch.Tensor | None

    # Attention explanation
    attention_logits: torch.Tensor | None
    attention_weights: torch.Tensor | None
    attention_entropy: torch.Tensor | None
    valid_timestep_count: torch.Tensor | None

    # ODST-native explanation
    feature_selection_weights: torch.Tensor | None
    routing_logits_or_choices: torch.Tensor | None
    routing_probabilities: torch.Tensor | None
    leaf_probabilities: torch.Tensor | None
    tree_level_outputs: torch.Tensor | None
    tree_level_contributions: torch.Tensor | None

    # Metadata
    model_id: str
    dataset_version: str
    seed: int
    checkpoint_hash: str
    input_shape: tuple[int, ...]
    device: str
    inference_mode: str
    explanation_fields_available: list[str] = field(default_factory=list)
    explanation_fields_unavailable: list[str] = field(default_factory=list)
    odst_extras_raw_keys: list[str] = field(default_factory=list)

    def unavailable_map(self) -> dict[str, str | None]:
        """Map of ODST-only / optional fields that are None → unavailable."""
        mapping = {
            "attention_logits": self.attention_logits,
            "attention_weights": self.attention_weights,
            "pooled_representation": self.pooled_representation,
            "sequence_hidden_states": self.sequence_hidden_states,
            "feature_selection_weights": self.feature_selection_weights,
            "routing_logits_or_choices": self.routing_logits_or_choices,
            "routing_probabilities": self.routing_probabilities,
            "leaf_probabilities": self.leaf_probabilities,
            "tree_level_outputs": self.tree_level_outputs,
            "tree_level_contributions": self.tree_level_contributions,
        }
        return {k: (None if v is None else "present") for k, v in mapping.items()}


def _attention_linear_compatibility(
    model: SequenceEnsembleModel, state_dict: dict[str, torch.Tensor]
) -> StateDictCompatibilityReport:
    model_sd = model.state_dict()
    missing = sorted(set(model_sd) - set(state_dict))
    unexpected = sorted(set(state_dict) - set(model_sd))
    mismatches: list[str] = []
    saved_count = 0
    for key, tensor in state_dict.items():
        if key not in model_sd:
            continue
        if tuple(tensor.shape) != tuple(model_sd[key].shape):
            mismatches.append(
                f"{key}: ckpt{tuple(tensor.shape)} != model{tuple(model_sd[key].shape)}"
            )
        else:
            saved_count += int(tensor.numel())
    instantiated = sum(p.numel() for p in model.parameters())
    ok = not missing and not unexpected and not mismatches
    return StateDictCompatibilityReport(
        n_checkpoint_tensors=len(state_dict),
        n_model_parameters=len(model_sd),
        missing_keys=missing,
        unexpected_keys=unexpected,
        shape_mismatches=mismatches,
        strict_load_ok=ok,
        parameter_count_match=saved_count == instantiated and ok,
        saved_parameter_count=saved_count,
        instantiated_parameter_count=instantiated,
    )


def _load_attention_linear_checkpoint(
    entry: Objective3ModelRegistryEntry,
    *,
    device: str | torch.device,
    strict: bool,
    evaluation_mode: bool,
    root: Path | None,
) -> tuple[SequenceEnsembleModel, dict[str, Any], StateDictCompatibilityReport, str]:
    path = resolve_checkpoint_path(entry.checkpoint_path, root=root)
    if not path.exists():
        raise FileNotFoundError(f"Attention–linear checkpoint not found: {path}")
    digest = sha256_file(path)
    if digest != entry.checkpoint_sha256:
        raise ValueError(
            f"Checkpoint hash mismatch for {path}: got {digest}, "
            f"expected {entry.checkpoint_sha256}"
        )
    payload = torch.load(path, map_location=device, weights_only=False)
    if not isinstance(payload, dict) or "model_state_dict" not in payload:
        raise TypeError(f"Unexpected attention–linear checkpoint format: {path}")
    cfg_src = dict(payload.get("config") or {})
    configuration = {
        "architecture": "SequenceEnsembleModel",
        "classification_head": "linear",
        "temporal_aggregation": "attention",
        "hidden_size": int(cfg_src.get("hidden_size", 64)),
        "dropout": float(cfg_src.get("dropout", 0.2)),
        "attention_dim": int(cfg_src.get("attention_dim", 64)),
        "input_dim": FEATURE_COUNT,
        "sequence_length_expected": SEQUENCE_LENGTH,
        "n_trees": int(cfg_src.get("n_trees", 5)),
        "tree_depth": int(cfg_src.get("tree_depth", 4)),
    }
    model = SequenceEnsembleModel(
        input_dim=FEATURE_COUNT,
        hidden_size=configuration["hidden_size"],
        dropout=configuration["dropout"],
        attention_dim=configuration["attention_dim"],
        classification_head="linear",
        temporal_aggregation="attention",
        n_trees=configuration["n_trees"],
        tree_depth=configuration["tree_depth"],
    )
    state_dict = payload["model_state_dict"]
    report = _attention_linear_compatibility(model, state_dict)
    if strict and (
        report.missing_keys or report.unexpected_keys or report.shape_mismatches
    ):
        raise RuntimeError(
            "Strict attention–linear load failed for "
            f"{path}: missing={report.missing_keys}, unexpected={report.unexpected_keys}, "
            f"shape_mismatches={report.shape_mismatches}"
        )
    incompatible = model.load_state_dict(state_dict, strict=strict)
    report.missing_keys = list(getattr(incompatible, "missing_keys", report.missing_keys))
    report.unexpected_keys = list(
        getattr(incompatible, "unexpected_keys", report.unexpected_keys)
    )
    report.strict_load_ok = not report.missing_keys and not report.unexpected_keys
    if strict and not report.strict_load_ok:
        raise RuntimeError(
            f"Strict load incompatibilities for {path}: "
            f"missing={report.missing_keys}, unexpected={report.unexpected_keys}"
        )
    model.to(device)
    if evaluation_mode:
        model.eval()
    return model, configuration, report, digest


def load_objective3_model(
    model_id: str,
    dataset_version: str,
    seed: int,
    *,
    device: str | torch.device = "cpu",
    strict: bool = True,
    evaluation_mode: bool = True,
    partition_role: str = "synthetic_test_only",
    root: Path | None = None,
) -> Objective3LoadedModel:
    """Load a selected Objective 3 model (ODST or attention–linear).

    Requires an explicit partition_role. Defaults to ``synthetic_test_only``.
    Requests for protected r5.2 test / r6.2 roles raise ``ProtectedPartitionError``.
    Does not load datasets or run inference.
    """
    role = assert_partition_role_permitted(partition_role)
    entry = get_registry_entry(model_id, dataset_version, seed)
    device_s = str(device)

    if entry.loader_type == "odst":
        result = load_objective3_odst_checkpoint(
            entry.checkpoint_path,
            device=device,
            strict=strict,
            evaluation_mode=evaluation_mode,
            expected_sha256=entry.checkpoint_sha256,
            root=root,
            verify_hash=True,
        )
        thr = result.threshold_metadata_path
        if thr is None and entry.threshold_metadata_path:
            thr_path = resolve_checkpoint_path(entry.threshold_metadata_path, root=root)
            thr = str(thr_path) if thr_path.exists() else entry.threshold_metadata_path
        return Objective3LoadedModel(
            model=result.model,
            model_id=entry.model_id,
            architecture=entry.model_id,
            dataset_version=entry.dataset_version,
            seed=entry.seed,
            checkpoint_path=result.checkpoint_path,
            checkpoint_hash=result.checkpoint_sha256,
            configuration=result.configuration,
            threshold_metadata_path=thr,
            explanation_capabilities=entry.explanation_capabilities,
            compatibility=result.compatibility,
            loader_type="odst",
            registry_entry=entry,
            device=device_s,
            partition_role=role,
        )

    if entry.loader_type == "attention_linear":
        model, configuration, report, digest = _load_attention_linear_checkpoint(
            entry,
            device=device,
            strict=strict,
            evaluation_mode=evaluation_mode,
            root=root,
        )
        thr_path = None
        if entry.threshold_metadata_path:
            cand = resolve_checkpoint_path(entry.threshold_metadata_path, root=root)
            thr_path = str(cand) if cand.exists() else entry.threshold_metadata_path
        return Objective3LoadedModel(
            model=model,
            model_id=entry.model_id,
            architecture=entry.model_id,
            dataset_version=entry.dataset_version,
            seed=entry.seed,
            checkpoint_path=str(resolve_checkpoint_path(entry.checkpoint_path, root=root)),
            checkpoint_hash=digest,
            configuration=configuration,
            threshold_metadata_path=thr_path,
            explanation_capabilities=entry.explanation_capabilities,
            compatibility=report,
            loader_type="attention_linear",
            registry_entry=entry,
            device=device_s,
            partition_role=role,
        )

    raise ValueError(f"Unsupported loader_type={entry.loader_type!r}")


def _validate_inputs(
    inputs: torch.Tensor,
    *,
    sequence_length: int = SEQUENCE_LENGTH,
    feature_count: int = FEATURE_COUNT,
) -> None:
    if not isinstance(inputs, torch.Tensor):
        raise TypeError(f"inputs must be a torch.Tensor; got {type(inputs)}")
    if inputs.dim() != 3:
        raise ValueError(f"Expected inputs shape (B, T, F); got {tuple(inputs.shape)}")
    if inputs.size(1) != sequence_length:
        raise ValueError(
            f"Expected sequence length {sequence_length}; got {inputs.size(1)}"
        )
    if inputs.size(2) != feature_count:
        raise ValueError(
            f"Expected feature count {feature_count}; got {inputs.size(2)}"
        )
    if not torch.isfinite(inputs).all():
        raise ValueError("inputs contain non-finite values")


def _normalise_mask(
    mask: torch.Tensor | None,
    *,
    batch: int,
    seq_len: int,
    device: torch.device,
    dtype: torch.dtype,
) -> torch.Tensor | None:
    if mask is None:
        return None
    if mask.shape != (batch, seq_len):
        raise ValueError(
            f"mask shape must be {(batch, seq_len)}; got {tuple(mask.shape)}"
        )
    # Do not mutate caller tensor.
    m = mask.detach().to(device=device)
    if m.dtype != torch.bool:
        m = m != 0
    if not bool(m.any()):
        raise ValueError("timestep mask has no valid timesteps")
    return m


def _masked_attention_weights(
    attn: torch.Tensor, mask: torch.Tensor | None
) -> tuple[torch.Tensor, torch.Tensor | None, torch.Tensor | None]:
    """Return (weights, entropy, valid_count). Masked positions get zero mass."""
    if mask is None:
        # attn already softmax-normalised over T.
        ent = -(attn.clamp_min(1e-12).log() * attn).sum(dim=-1)
        valid = torch.full(
            (attn.size(0),),
            attn.size(1),
            device=attn.device,
            dtype=torch.long,
        )
        return attn, ent, valid
    m = mask.to(dtype=attn.dtype)
    masked = attn * m
    denom = masked.sum(dim=-1, keepdim=True).clamp_min(1e-12)
    renorm = masked / denom
    # Force exact zeros on invalid positions (numerical).
    renorm = torch.where(mask, renorm, torch.zeros_like(renorm))
    ent = -(renorm.clamp_min(1e-12).log() * renorm).sum(dim=-1)
    # Zero-entropy contribution from masked positions already removed.
    valid = mask.sum(dim=-1).to(dtype=torch.long)
    return renorm, ent, valid


def _tree_outputs_and_contributions(
    extras: dict[str, Any],
) -> tuple[torch.Tensor | None, torch.Tensor | None]:
    bags = extras.get("layer_tree_logits")
    if not bags:
        return None, None
    # Each bag: (B, n_trees); concatenate over layers → (B, n_layers*n_trees)
    stacked = torch.cat([t for t in bags], dim=-1)
    n = stacked.size(-1)
    # Canonical tree average: final_logit = mean_i tree_i
    # so contribution of tree_i is tree_i / n.
    contributions = stacked / float(n)
    return stacked, contributions


def _parameter_digest(model: nn.Module) -> str:
    h = hashlib.sha256()
    for name, param in sorted(model.state_dict().items(), key=lambda kv: kv[0]):
        h.update(name.encode("utf-8"))
        t = param.detach().cpu().contiguous()
        h.update(tuple(t.shape).__repr__().encode("utf-8"))
        h.update(t.numpy().tobytes())
    return h.hexdigest()


def objective3_inference(
    loaded_model: Objective3LoadedModel,
    inputs: torch.Tensor,
    mask: torch.Tensor | None = None,
    threshold: float | None = None,
    return_explanations: bool = True,
    require_gradients: bool = False,
) -> Objective3InferenceResult:
    """Run Objective 3 inference with optional native explanation tensors.

    Does not load data, does not mutate model parameters, and does not mutate
    the caller's input tensor. Thresholding only when ``threshold`` is supplied.
    """
    _validate_inputs(inputs)
    model = loaded_model.model
    device = next(model.parameters()).device
    # Clone so caller tensor is never modified.
    x = inputs.detach().clone().to(device=device, dtype=torch.float32)
    if require_gradients:
        x = x.requires_grad_(True)

    mask_bool = _normalise_mask(
        mask,
        batch=x.size(0),
        seq_len=x.size(1),
        device=device,
        dtype=x.dtype,
    )
    # Respect padding by zeroing invalid timesteps on the working copy only.
    if mask_bool is not None:
        x = x * mask_bool.unsqueeze(-1).to(dtype=x.dtype)

    was_training = model.training
    model.eval()

    def _forward() -> tuple[torch.Tensor, dict[str, Any]]:
        out = model(x)
        if not isinstance(out, tuple) or len(out) != 2:
            raise RuntimeError("Model forward must return (logits, extras)")
        logits_t, extras_t = out
        return logits_t, extras_t

    if require_gradients:
        logits, extras = _forward()
        inference_mode = "grad_enabled"
    else:
        with torch.no_grad():
            logits, extras = _forward()
        inference_mode = "no_grad_eval"

    if was_training:
        model.train()

    probs = torch.sigmoid(logits)
    pred_labels = None
    thr_used = None
    if threshold is not None:
        thr_used = float(threshold)
        pred_labels = (probs >= thr_used).to(dtype=torch.long)

    attn = extras.get("attention_weights")
    pooled = extras.get("aggregated")
    hidden = extras.get("hidden_states")

    attn_w = attn_ent = valid_count = None
    attn_logits = None  # not exposed by TemporalAttention.forward extras
    if return_explanations and attn is not None:
        attn_w, attn_ent, valid_count = _masked_attention_weights(attn, mask_bool)

    feat_sel = routing_choice = routing_probs = leaf_p = tree_out = tree_contrib = None
    raw_keys = sorted(str(k) for k in extras.keys())

    if return_explanations and loaded_model.loader_type == "odst":
        feat_sel = extras.get("feature_selection_weights")
        if feat_sel is None:
            feat_sel = extras.get("feature_selection_probs")
        # choice: soft right-branch probabilities in (0,1) for sparsemax_sigmoid ODST
        routing_choice = extras.get("choice")
        routing_probs = routing_choice  # same tensor; documented as probabilities
        leaf_p = extras.get("leaf_probs")
        tree_out, tree_contrib = _tree_outputs_and_contributions(extras)

    available: list[str] = []
    unavailable: list[str] = []

    def _track(name: str, value: Any) -> None:
        if value is None:
            unavailable.append(name)
        else:
            available.append(name)

    if return_explanations:
        for name, value in [
            ("attention_logits", attn_logits),
            ("attention_weights", attn_w),
            ("attention_entropy", attn_ent),
            ("pooled_representation", pooled),
            ("sequence_hidden_states", hidden),
            ("feature_selection_weights", feat_sel),
            ("routing_logits_or_choices", routing_choice),
            ("routing_probabilities", routing_probs),
            ("leaf_probabilities", leaf_p),
            ("tree_level_outputs", tree_out),
            ("tree_level_contributions", tree_contrib),
        ]:
            _track(name, value)
    else:
        unavailable.extend(
            [
                "attention_logits",
                "attention_weights",
                "attention_entropy",
                "pooled_representation",
                "sequence_hidden_states",
                "feature_selection_weights",
                "routing_logits_or_choices",
                "routing_probabilities",
                "leaf_probabilities",
                "tree_level_outputs",
                "tree_level_contributions",
            ]
        )
        attn_w = attn_ent = valid_count = pooled = hidden = None
        feat_sel = routing_choice = routing_probs = leaf_p = tree_out = tree_contrib = None

    # Attention–linear: ensure ODST fields stay None (no fabricated zeros).
    if loaded_model.loader_type == "attention_linear":
        feat_sel = routing_choice = routing_probs = leaf_p = tree_out = tree_contrib = None
        for name in [
            "feature_selection_weights",
            "routing_logits_or_choices",
            "routing_probabilities",
            "leaf_probabilities",
            "tree_level_outputs",
            "tree_level_contributions",
        ]:
            if name in available:
                available.remove(name)
            if name not in unavailable:
                unavailable.append(name)

    return Objective3InferenceResult(
        logits=logits,
        probabilities=probs,
        predicted_labels=pred_labels,
        threshold_used=thr_used,
        pooled_representation=pooled if return_explanations else None,
        sequence_hidden_states=hidden if return_explanations else None,
        timestep_mask=mask_bool,
        attention_logits=attn_logits,
        attention_weights=attn_w,
        attention_entropy=attn_ent,
        valid_timestep_count=valid_count,
        feature_selection_weights=feat_sel,
        routing_logits_or_choices=routing_choice,
        routing_probabilities=routing_probs,
        leaf_probabilities=leaf_p,
        tree_level_outputs=tree_out,
        tree_level_contributions=tree_contrib,
        model_id=loaded_model.model_id,
        dataset_version=loaded_model.dataset_version,
        seed=loaded_model.seed,
        checkpoint_hash=loaded_model.checkpoint_hash,
        input_shape=tuple(int(s) for s in inputs.shape),
        device=str(device),
        inference_mode=inference_mode,
        explanation_fields_available=available,
        explanation_fields_unavailable=unavailable,
        odst_extras_raw_keys=raw_keys if loaded_model.loader_type == "odst" else [],
    )


# Re-export for callers / tests.
parameter_digest = _parameter_digest


__all__ = [
    "Objective3InferenceResult",
    "Objective3LoadedModel",
    "UNAVAILABLE",
    "ProtectedPartitionError",
    "load_objective3_model",
    "objective3_inference",
    "parameter_digest",
    "PRIMARY_ARCHITECTURE",
    "NEURAL_REFERENCE_ARCHITECTURE",
    "repo_root",
]
