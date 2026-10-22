"""TA2 student / frozen-reference construction. No architecture search."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.models import (
    architecture_identity,
    assert_odst046,
    assert_teacher_student_match,
    build_student_optimizer,
    enable_student,
    freeze_teacher,
    student_forward,
)
from editor012_rescue.producing import build_odst046_model, load_state_dict
from editor015_residual.train import load_ta2, load_topt

from .constants import CANDIDATES, TA2_CHECKPOINTS
from .safety import OUTPUT_ROOT, Editor021Blocked, sha256_file


def candidate_rho(name: str) -> float:
    if name not in CANDIDATES:
        raise Editor021Blocked(f"unauthorised candidate {name}")
    return float(CANDIDATES[name]["rho"])


def load_ta2_student(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    spec = TA2_CHECKPOINTS[seed]
    sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    student = build_odst046_model()
    load_state_dict(student, spec["checkpoint"], strict=True)
    student.to(device)
    enable_student(student)
    assert_odst046(student)
    return student, sha


def load_ta2_reference(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    spec = TA2_CHECKPOINTS[seed]
    sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    ref = build_odst046_model()
    load_state_dict(ref, spec["checkpoint"], strict=True)
    ref.to(device)
    freeze_teacher(ref)
    ref.eval()
    assert_odst046(ref)
    for p in ref.parameters():
        if p.requires_grad:
            raise Editor021Blocked("frozen TA2 reference parameter requires grad")
    return ref, sha


def assert_initial_match(student: nn.Module, reference: nn.Module, x: torch.Tensor, *, atol: float = 1e-6) -> dict[str, float]:
    student.eval()
    reference.eval()
    with torch.no_grad():
        s = student_forward(student, x)
        r = student_forward(reference, x)
    logit_mae = float((s["logit"] - r["logit"]).abs().max())
    z_mae = float((s["z"] - r["z"]).abs().max())
    if logit_mae > atol or z_mae > atol:
        raise Editor021Blocked(f"student/reference initial mismatch logit_mae={logit_mae} z_mae={z_mae}")
    return {"logit_max_abs": logit_mae, "z_max_abs": z_mae}


def build_optimizer(student: nn.Module) -> torch.optim.Optimizer:
    enable_student(student)
    return build_student_optimizer(student)


def assert_reference_not_in_optimizer(reference: nn.Module, optimizer: torch.optim.Optimizer) -> None:
    ref_ids = {id(p) for p in reference.parameters()}
    for group in optimizer.param_groups:
        for p in group["params"]:
            if id(p) in ref_ids:
                raise Editor021Blocked("frozen reference parameter found in optimiser")


def save_checkpoint(
    *,
    candidate: str,
    seed: int,
    student: nn.Module,
    extra: dict[str, Any],
) -> tuple[str, str]:
    out_dir = OUTPUT_ROOT / candidate / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "best.pt"
    payload = {
        "student_state_dict": {k: v.detach().cpu().clone() for k, v in student.state_dict().items()},
        "candidate": candidate,
        "seed": seed,
        "campaign": "EDITOR-021",
        "test_evaluated": False,
        **extra,
    }
    torch.save(payload, path)
    return str(path), sha256_file(path)


def load_trained(candidate: str, seed: int, device: torch.device) -> dict[str, Any]:
    path = OUTPUT_ROOT / candidate / f"seed{seed}" / "best.pt"
    payload = torch.load(path, map_location="cpu", weights_only=False)
    student = build_odst046_model()
    student.load_state_dict(payload["student_state_dict"])
    student.to(device)
    student.eval()
    assert_odst046(student)
    return {"student": student, "payload": payload, "path": str(path)}


def identities_ok() -> dict[str, Any]:
    teacher = build_odst046_model()
    student = build_odst046_model()
    assert_odst046(teacher)
    assert_odst046(student)
    assert_teacher_student_match(teacher, student)
    return {"odst046": architecture_identity(teacher), "match": True}


__all__ = [
    "load_ta2_student",
    "load_ta2_reference",
    "load_topt",
    "load_ta2",
    "student_forward",
    "freeze_teacher",
]
