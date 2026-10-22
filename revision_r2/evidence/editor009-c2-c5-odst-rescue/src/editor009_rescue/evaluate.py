"""Frozen-checkpoint evaluation on r5.2 VALIDATION only."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader

from .metrics import metrics_from_logits, teacher_relative
from .models import student_forward, teacher_forward
from .safety import Editor009ProtocolError, assert_not_deny_c5, note_open, sha256_file


@torch.no_grad()
def score_odst(
    model: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
    *,
    residual: bool = False,
) -> dict[str, np.ndarray]:
    model.eval()
    logits, choices, trees, zs = [], [], [], []
    ys = []
    for xb, yb in loader:
        xb = xb.to(device)
        out = student_forward(model, xb, residual=residual)
        logits.append(out["logit"].detach().cpu().numpy())
        choices.append(out["choices"].detach().cpu().numpy())
        trees.append(out["tree_outputs"].detach().cpu().numpy())
        zs.append(out["z"].detach().cpu().numpy())
        ys.append(yb.numpy())
    return {
        "logits": np.concatenate(logits),
        "choices": np.concatenate(choices),
        "tree_outputs": np.concatenate(trees),
        "z": np.concatenate(zs),
        "y": np.concatenate(ys).reshape(-1),
    }


@torch.no_grad()
def score_attention_linear(model: torch.nn.Module, loader: DataLoader, device: torch.device) -> dict[str, np.ndarray]:
    model.eval()
    logits, ys = [], []
    for xb, yb in loader:
        xb = xb.to(device)
        logit, _extras = model(xb)
        logits.append(logit.detach().cpu().numpy().reshape(-1))
        ys.append(yb.numpy())
    return {"logits": np.concatenate(logits), "y": np.concatenate(ys).reshape(-1)}


def evaluate_pair(
    *,
    student: torch.nn.Module,
    teacher: torch.nn.Module | None,
    loader: DataLoader,
    device: torch.device,
    residual: bool = False,
    frozen_threshold: float | None = None,
) -> dict[str, Any]:
    s = score_odst(student, loader, device, residual=residual)
    sm = metrics_from_logits(s["y"], s["logits"], threshold=frozen_threshold)
    out: dict[str, Any] = {
        "student": {k: v for k, v in sm.items() if k not in {"probs", "pred"}},
        "y": s["y"],
        "student_logits": s["logits"],
        "student_choices": s["choices"],
        "student_tree_outputs": s["tree_outputs"],
        "student_z": s["z"],
    }
    if teacher is not None:
        t = score_odst(teacher, loader, device, residual=False)
        tm = metrics_from_logits(t["y"], t["logits"], threshold=None)
        out["teacher"] = {k: v for k, v in tm.items() if k not in {"probs", "pred"}}
        out["teacher_logits"] = t["logits"]
        out["teacher_choices"] = t["choices"]
        out["teacher_tree_outputs"] = t["tree_outputs"]
        rel = teacher_relative(s["y"], s["logits"], t["logits"], s["choices"], t["choices"])
        out.update(rel)
    return out


def hash_gate_checkpoint(path, expected: str | None = None) -> str:
    note_open(path, role="checkpoint")
    observed = sha256_file(path)
    assert_not_deny_c5(observed)
    if expected is not None and observed != expected:
        raise Editor009ProtocolError(
            f"checkpoint hash mismatch expected={expected} observed={observed} path={path}"
        )
    return observed
