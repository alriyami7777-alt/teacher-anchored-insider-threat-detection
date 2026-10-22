"""Hash-gated frozen-checkpoint loaders. No parameter update."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.producing import build_odst046_model, load_state_dict, pin_producing_sources
from editor013_odst_value.models import Editor013Modules, editor013_forward
from editor015_residual.train import load_l1_pair

from .constants import MODEL_SPECS, PRIMARY_SEEDS
from .safety import Editor017ProtocolError


def load_odst(alias: str, seed: int, device: torch.device) -> tuple[nn.Module, str]:
    spec = MODEL_SPECS[alias]
    ck = spec["checkpoints"][seed]
    sha = hash_gate_checkpoint(ck["checkpoint"], ck["sha256"])
    model = build_odst046_model()
    load_state_dict(model, ck["checkpoint"], strict=True)
    model.to(device)
    model.eval()
    for p in model.parameters():
        p.requires_grad = False
    return model, sha


def load_l1(seed: int, device: torch.device) -> tuple[nn.Module, Editor013Modules, str]:
    student, modules, sha = load_l1_pair(seed, device)
    student.eval()
    modules.eval()
    for p in student.parameters():
        p.requires_grad = False
    for p in modules.parameters():
        p.requires_grad = False
    return student, modules, sha


def parameter_fingerprint(model: nn.Module, extra: nn.Module | None = None) -> str:
    blobs = []
    for p in model.parameters():
        blobs.append(p.detach().cpu().numpy().tobytes())
    if extra is not None:
        for p in extra.parameters():
            blobs.append(p.detach().cpu().numpy().tobytes())
    import hashlib

    return hashlib.sha256(b"".join(blobs)).hexdigest()


def frozen_threshold_from_logits(y: np.ndarray, logits: np.ndarray) -> float:
    from editor012_rescue.metrics import sigmoid
    from editor012_rescue.producing import import_threshold_fns

    choose_threshold_f1, _ = import_threshold_fns()
    probs = sigmoid(np.asarray(logits, dtype=np.float64).reshape(-1))
    thr, _ = choose_threshold_f1(np.asarray(y).astype(int).reshape(-1), probs)
    return float(thr)


def recover_frozen_thresholds(y_val: np.ndarray) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for alias, spec in MODEL_SPECS.items():
        out[alias] = {}
        for seed in PRIMARY_SEEDS:
            path = spec["val_logits"][seed]
            if not path.is_file():
                raise Editor017ProtocolError(f"missing frozen val_logits: {path}")
            logits = np.load(path)
            out[alias][seed] = frozen_threshold_from_logits(y_val, logits)
    return out


def producing_pins() -> dict[str, str]:
    return pin_producing_sources()
