"""Shared initialisation for fair seed-42 micro-run comparisons."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import torch

from prototype_v3_node.architecture import (
    AttentionNodeEnsemble,
    load_v1_attention_linear_checkpoint,
)
from prototype_v2.safety import sha256_file

from .checkpoints import DEFAULT_ODST_HYPERPARAMS, pretrained_encoder_path, verify_checkpoint_sha256
from .protocol import BATCH_SIZE, LR_ATTENTION, LR_ENCODER, LR_ODST, MAX_EPOCHS, POS_WEIGHT_MULT, THRESHOLD_RULE


def _tensor_hash(t: torch.Tensor) -> str:
    arr = t.detach().cpu().contiguous().numpy().tobytes()
    return hashlib.sha256(arr).hexdigest()


def state_dict_hash(state: dict[str, torch.Tensor]) -> str:
    h = hashlib.sha256()
    for key in sorted(state.keys()):
        h.update(key.encode("utf-8"))
        h.update(_tensor_hash(state[key]).encode("utf-8"))
    return h.hexdigest()


def component_hashes(model: AttentionNodeEnsemble) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, module in [
        ("lstm", model.lstm),
        ("attention", model.attention),
        ("linear_head", model.linear_head),
        ("node_head", model.node_head),
    ]:
        out[name] = state_dict_hash(module.state_dict())
    return out


def build_shared_initialisation(
    repo_root: Path,
    *,
    seed: int = 42,
    device: torch.device | None = None,
    init_batch: torch.Tensor | None = None,
) -> dict[str, Any]:
    """Construct identical starting weights for all seed-42 conditions."""
    device = device or torch.device("cpu")
    enc_path = pretrained_encoder_path(repo_root, seed)
    enc_hash = sha256_file(enc_path)

    torch.manual_seed(seed)
    model = AttentionNodeEnsemble(**DEFAULT_ODST_HYPERPARAMS)
    load_report = load_v1_attention_linear_checkpoint(model, enc_path)

    # Deterministic ODST head init using seed, optionally data-aware from first batch.
    torch.manual_seed(seed)
    if init_batch is not None:
        model.data_aware_initialize_from_batch(init_batch.to(device))
    else:
        # Parameter-level re-seeded init already applied via leaf_init_std construction;
        # re-run data-free RNG touch for reproducibility marker.
        for p in model.node_head.parameters():
            if p.dim() >= 1:
                torch.manual_seed(seed)
                break

    model = model.to(device)
    full_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    start_hash = state_dict_hash(full_state)
    comp = component_hashes(model)

    payload = {
        "model_state_dict": full_state,
        "seed": seed,
        "architecture": dict(DEFAULT_ODST_HYPERPARAMS),
        "encoder_checkpoint": str(enc_path),
        "encoder_checkpoint_sha256": enc_hash,
        "shared_initialisation_hash": start_hash,
        "component_hashes": comp,
        "load_report": {k: load_report[k] for k in ("checkpoint", "n_loaded", "mechanism")},
        "parameter_count": int(sum(p.numel() for p in model.parameters())),
        "trainable_before_condition": {
            "lstm": False,
            "attention": False,
            "odst": True,
        },
        "loss": "BCEWithLogitsLoss",
        "pos_weight_mult": POS_WEIGHT_MULT,
        "batch_size": BATCH_SIZE,
        "optimiser": "Adam",
        "scheduler": None,
        "threshold_selection_rule": THRESHOLD_RULE,
        "max_epochs": MAX_EPOCHS,
        "learning_rates": {
            "lstm": LR_ENCODER,
            "attention": LR_ATTENTION,
            "odst": LR_ODST,
        },
    }
    return payload


def save_shared_initialisation(payload: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pt_path = out_dir / "shared_initialisation_seed42.pt"
    torch.save(payload, pt_path)
    rows = [
        {
            "key": "shared_initialisation_hash",
            "value": payload["shared_initialisation_hash"],
        },
        {"key": "encoder_checkpoint_sha256", "value": payload["encoder_checkpoint_sha256"]},
        {"key": "parameter_count", "value": payload["parameter_count"]},
    ]
    for k, v in payload["component_hashes"].items():
        rows.append({"key": f"component_hash_{k}", "value": v})
    import csv

    with (out_dir / "shared_initialisation_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["key", "value"])
        w.writeheader()
        w.writerows(rows)
    (out_dir / "shared_initialisation_meta.json").write_text(
        json.dumps(
            {k: v for k, v in payload.items() if k != "model_state_dict"},
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return pt_path


def load_shared_model(pt_path: Path, device: torch.device) -> tuple[AttentionNodeEnsemble, str]:
    payload = torch.load(pt_path, map_location="cpu", weights_only=False)
    model = AttentionNodeEnsemble(**payload["architecture"])
    model.load_state_dict(payload["model_state_dict"])
    model.to(device)
    return model, payload["shared_initialisation_hash"]


def verify_starting_hash(model: AttentionNodeEnsemble, expected: str) -> str:
    current = state_dict_hash(model.state_dict())
    if current != expected:
        raise RuntimeError(
            f"Starting-state hash mismatch: got {current}, expected {expected}"
        )
    return current
