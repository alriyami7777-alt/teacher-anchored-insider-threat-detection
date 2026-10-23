#!/usr/bin/env python3
"""Objective 3 load-only ODST checkpoint interface.

Loads Bi-LSTM–attention–sparsemax–sigmoid ODST checkpoints without
dataset access, inference on real data, training, or threshold changes.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import torch

from prototype_v3_node import AttentionNodeEnsemble, count_parameters

DEFAULT_ODST_HYPERPARAMS: dict[str, Any] = {
    "input_dim": 13,
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "fusion_variant": "sparsemax_sigmoid_odst",
    "node_num_layers": 2,
    "node_n_trees": 8,
    "node_depth": 4,
    "node_tree_dim": 1,
    "node_temperature": 1.0,
    "node_dropout": 0.0,
    "leaf_init_std": 0.05,
    "gate_hidden_dim": 32,
}

# Selected Objective 3 ODST checkpoints (paths relative to repo root).
SELECTED_ODST_CHECKPOINTS: dict[str, dict[str, Any]] = {
    "odst_r42_s42": {
        "path": "outputs/v3_node/seed42_full_20260723_095912/seed42_full_20260723_095916/sparsemax_sigmoid_odst_seed42/best.pt",
        "dataset_version": "CERT r4.2",
        "seed": 42,
        "expected_sha256": "ff7ceb287df27689d3cd52bfee79e1aa617bbf1f72ba5f4769a3c4b7598d0167",
    },
    "odst_r42_s52": {
        "path": "outputs/v3_node/seed52_full_20260723_101933/seed52_full_20260723_101936/sparsemax_sigmoid_odst_seed52/best.pt",
        "dataset_version": "CERT r4.2",
        "seed": 52,
        "expected_sha256": "8de6398b49a802b9676d564600614c84db679def6be2026761f2ed9c1502f182",
    },
    "odst_r42_s62": {
        "path": "outputs/v3_node/seed62_full_20260723_102938/seed62_full_20260723_102942/sparsemax_sigmoid_odst_seed62/best.pt",
        "dataset_version": "CERT r4.2",
        "seed": 62,
        "expected_sha256": "af898f4845817833d2d30a9f93f034f62e9273df2e523fe3f7720f33e3c051fa",
    },
    "odst_r52_s42": {
        "path": "outputs/objective2/r52_odst_confirmation/odst_seed42/best.pt",
        "dataset_version": "CERT r5.2",
        "seed": 42,
        "expected_sha256": "783d0913f85d492ddacec83a274ba2d4f13ad25eaf1a34ebcc64a960bda8ff86",
    },
    "odst_r52_s52": {
        "path": "outputs/objective2/r52_odst_confirmation/odst_seed52/best.pt",
        "dataset_version": "CERT r5.2",
        "seed": 52,
        "expected_sha256": "7273327495bbe463cfb3d50fa94c81c82de7b304370a816343046f559fc3d191",
    },
    "odst_r52_s62": {
        "path": "outputs/objective2/r52_odst_confirmation/odst_seed62/best.pt",
        "dataset_version": "CERT r5.2",
        "seed": 62,
        "expected_sha256": "247d6e71353b49ea0a77a073a8606fbf35b88106faae7dae6ec53361621e9d92",
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_checkpoint_path(checkpoint_path: str | Path, *, root: Path | None = None) -> Path:
    path = Path(checkpoint_path)
    if path.is_absolute():
        return path
    base = root or repo_root()
    return (base / path).resolve()


def infer_dataset_version(path: Path, payload: dict[str, Any]) -> str:
    text = str(path).replace("\\", "/").lower()
    if "r52" in text or "r5.2" in text or payload.get("stage", "").startswith("odst_r52"):
        return "CERT r5.2"
    if payload.get("prototype") == "v3_node" or "v3_node" in text:
        return "CERT r4.2"
    return "not_recorded"


@dataclass
class StateDictCompatibilityReport:
    n_checkpoint_tensors: int
    n_model_parameters: int
    missing_keys: list[str] = field(default_factory=list)
    unexpected_keys: list[str] = field(default_factory=list)
    shape_mismatches: list[str] = field(default_factory=list)
    strict_load_ok: bool = False
    parameter_count_match: bool = False
    saved_parameter_count: int = 0
    instantiated_parameter_count: int = 0


@dataclass
class Objective3ODSTLoadResult:
    model: AttentionNodeEnsemble
    configuration: dict[str, Any]
    checkpoint_metadata: dict[str, Any]
    dataset_version: str
    seed: int
    checkpoint_path: str
    checkpoint_sha256: str
    threshold_metadata_path: str | None
    compatibility: StateDictCompatibilityReport
    architecture_name: str = "AttentionNodeEnsemble"
    fusion_variant: str = "sparsemax_sigmoid_odst"

    def to_metadata_dict(self) -> dict[str, Any]:
        """JSON-serialisable metadata (excludes the live model object)."""
        return {
            "architecture_name": self.architecture_name,
            "fusion_variant": self.fusion_variant,
            "configuration": self.configuration,
            "checkpoint_metadata": {
                k: v
                for k, v in self.checkpoint_metadata.items()
                if k != "model_state_dict" and not isinstance(v, torch.Tensor)
            },
            "dataset_version": self.dataset_version,
            "seed": self.seed,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_sha256": self.checkpoint_sha256,
            "threshold_metadata_path": self.threshold_metadata_path,
            "compatibility": asdict(self.compatibility),
        }


def build_odst_model(
    *,
    fusion_variant: str = "sparsemax_sigmoid_odst",
    overrides: dict[str, Any] | None = None,
) -> AttentionNodeEnsemble:
    cfg = dict(DEFAULT_ODST_HYPERPARAMS)
    cfg["fusion_variant"] = fusion_variant
    if overrides:
        cfg.update(overrides)
    return AttentionNodeEnsemble(**cfg)


def _load_payload(path: Path, map_location: str | torch.device) -> dict[str, Any]:
    payload = torch.load(path, map_location=map_location, weights_only=False)
    if not isinstance(payload, dict):
        raise TypeError(f"Checkpoint is not a dict: {path} ({type(payload)})")
    if "model_state_dict" not in payload:
        raise KeyError(f"Checkpoint missing model_state_dict: {path}")
    if not isinstance(payload["model_state_dict"], dict):
        raise TypeError(f"model_state_dict is not a dict in {path}")
    return payload


def _compatibility_precheck(
    model: AttentionNodeEnsemble, state_dict: dict[str, torch.Tensor]
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
    instantiated = count_parameters(model)
    return StateDictCompatibilityReport(
        n_checkpoint_tensors=len(state_dict),
        n_model_parameters=len(model_sd),
        missing_keys=missing,
        unexpected_keys=unexpected,
        shape_mismatches=mismatches,
        strict_load_ok=False,
        parameter_count_match=saved_count == instantiated and not missing and not unexpected and not mismatches,
        saved_parameter_count=saved_count,
        instantiated_parameter_count=instantiated,
    )


def load_objective3_odst_checkpoint(
    checkpoint_path: str | Path,
    *,
    device: str | torch.device = "cpu",
    strict: bool = True,
    evaluation_mode: bool = True,
    expected_sha256: str | None = None,
    root: Path | None = None,
    verify_hash: bool = True,
) -> Objective3ODSTLoadResult:
    """Load a selected ODST checkpoint for Objective 3 (CPU-safe, no data).

    Parameters
    ----------
    checkpoint_path:
        Absolute path or path relative to the repository root.
    device:
        Torch device / map_location (default ``cpu``).
    strict:
        Require exact state-dict key and shape match (default True).
    evaluation_mode:
        Call ``model.eval()`` after loading (default True).
    expected_sha256:
        Optional hash check; if omitted and the path matches a known selected
        checkpoint id, the audit hash is used when ``verify_hash`` is True.
    """
    path = resolve_checkpoint_path(checkpoint_path, root=root)
    if not path.exists():
        raise FileNotFoundError(f"ODST checkpoint not found: {path}")

    digest = sha256_file(path)
    known_hash = expected_sha256
    if known_hash is None and verify_hash:
        for meta in SELECTED_ODST_CHECKPOINTS.values():
            if resolve_checkpoint_path(meta["path"], root=root) == path:
                known_hash = meta["expected_sha256"]
                break
    if known_hash is not None and digest != known_hash:
        raise ValueError(
            f"Checkpoint hash mismatch for {path}: got {digest}, expected {known_hash}"
        )

    payload = _load_payload(path, map_location=device)
    fusion_variant = str(payload.get("fusion_variant", "sparsemax_sigmoid_odst"))
    if fusion_variant != "sparsemax_sigmoid_odst":
        raise ValueError(
            f"Unsupported fusion_variant={fusion_variant!r}; "
            "Objective 3 loader expects sparsemax_sigmoid_odst"
        )

    model = build_odst_model(fusion_variant=fusion_variant)
    state_dict = payload["model_state_dict"]
    report = _compatibility_precheck(model, state_dict)
    if strict and (report.missing_keys or report.unexpected_keys or report.shape_mismatches):
        raise RuntimeError(
            "Strict ODST load failed for "
            f"{path}: missing={report.missing_keys}, unexpected={report.unexpected_keys}, "
            f"shape_mismatches={report.shape_mismatches}"
        )

    incompatible = model.load_state_dict(state_dict, strict=strict)
    # torch returns IncompatibleKeys namedtuple
    report.missing_keys = list(getattr(incompatible, "missing_keys", report.missing_keys))
    report.unexpected_keys = list(
        getattr(incompatible, "unexpected_keys", report.unexpected_keys)
    )
    report.strict_load_ok = not report.missing_keys and not report.unexpected_keys and not report.shape_mismatches
    report.parameter_count_match = (
        report.saved_parameter_count == report.instantiated_parameter_count
        and report.strict_load_ok
    )
    if strict and not report.strict_load_ok:
        raise RuntimeError(
            f"Strict load reported incompatibilities for {path}: "
            f"missing={report.missing_keys}, unexpected={report.unexpected_keys}"
        )
    if strict and not report.parameter_count_match:
        raise RuntimeError(
            f"Parameter count mismatch for {path}: "
            f"saved={report.saved_parameter_count}, "
            f"instantiated={report.instantiated_parameter_count}"
        )

    model.to(device)
    if evaluation_mode:
        model.eval()

    thr = path.parent / "threshold.json"
    seed = int(payload.get("seed", -1))
    configuration = {
        **DEFAULT_ODST_HYPERPARAMS,
        "fusion_variant": fusion_variant,
        "choice_function": model.choice_function,
        "readout": model.readout,
        "encoder_dim": model.encoder_dim,
        "bidirectional": True,
        "sequence_length_expected": 20,
    }
    meta = {
        k: v
        for k, v in payload.items()
        if k != "model_state_dict" and not isinstance(v, torch.Tensor)
    }
    return Objective3ODSTLoadResult(
        model=model,
        configuration=configuration,
        checkpoint_metadata=meta,
        dataset_version=infer_dataset_version(path, payload),
        seed=seed,
        checkpoint_path=str(path),
        checkpoint_sha256=digest,
        threshold_metadata_path=str(thr) if thr.exists() else None,
        compatibility=report,
        fusion_variant=fusion_variant,
    )


def load_selected_objective3_odst(
    checkpoint_id: str,
    **kwargs: Any,
) -> Objective3ODSTLoadResult:
    """Load one of the six selected ODST checkpoints by audit id."""
    if checkpoint_id not in SELECTED_ODST_CHECKPOINTS:
        raise KeyError(
            f"Unknown checkpoint_id={checkpoint_id!r}; "
            f"expected one of {sorted(SELECTED_ODST_CHECKPOINTS)}"
        )
    meta = SELECTED_ODST_CHECKPOINTS[checkpoint_id]
    return load_objective3_odst_checkpoint(
        meta["path"],
        expected_sha256=meta["expected_sha256"],
        **kwargs,
    )
