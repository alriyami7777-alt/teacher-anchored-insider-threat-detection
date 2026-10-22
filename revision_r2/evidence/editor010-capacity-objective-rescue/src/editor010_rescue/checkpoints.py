"""Load frozen r5.2 baselines read-only. Never writes historical packets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

from .constants import BASELINES, C5_DENYLIST_SHA256
from .hashes import sha256_file
from .models import build_attention_node, build_encoder
from .safety import Editor010SafetyError, assert_path_allowed_for_read


def _unwrap_state(payload: Any) -> dict[str, torch.Tensor]:
    if not isinstance(payload, dict):
        raise Editor010SafetyError("Checkpoint is not a dict")
    if "model_state_dict" in payload and isinstance(payload["model_state_dict"], dict):
        return payload["model_state_dict"]
    if "state_dict" in payload and isinstance(payload["state_dict"], dict):
        return payload["state_dict"]
    # Some student checkpoints store the raw state dict.
    if any(k.startswith("lstm.") or k.startswith("node_head.") for k in payload):
        return payload
    raise Editor010SafetyError("Checkpoint missing model_state_dict")


def load_baseline(family: str, seed: int, device: torch.device) -> nn.Module:
    meta = BASELINES[family][int(seed)]
    path = assert_path_allowed_for_read(Path(meta["checkpoint"]), context=f"{family}:{seed}")
    digest = sha256_file(path)
    if digest != meta["sha256"]:
        raise Editor010SafetyError(f"{family} seed {seed} SHA mismatch: {digest}")
    if digest in set(C5_DENYLIST_SHA256.values()):
        raise Editor010SafetyError(f"Deny-listed ablation C5 hash supplied as {family}")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    state = _unwrap_state(payload)
    if meta["kind"] == "attention_linear":
        model = build_encoder()
    else:
        model = build_attention_node()
    incompatible = model.load_state_dict(state, strict=True)
    model.to(device)
    model.eval()
    for p in model.parameters():
        p.requires_grad = False
    return model
