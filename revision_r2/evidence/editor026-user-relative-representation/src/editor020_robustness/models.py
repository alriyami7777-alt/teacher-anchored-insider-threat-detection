"""Matched L1 / F10 / TA2 construction. No new architecture search."""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.models import (
    architecture_identity,
    assert_odst046,
    assert_teacher_student_match,
    enable_student,
    freeze_teacher,
    student_forward,
)
from editor012_rescue.producing import build_odst046_model, load_state_dict
from editor013_odst_value.models import Editor013Modules, build_editor013_optimizer, editor013_forward, make_modules
from editor015_residual.train import load_l1_pair, load_ta2

from .constants import ARCH_SPECS, F10_CHECKPOINTS, OBJECTIVES, TOPT_CHECKPOINTS
from .safety import OUTPUT_ROOT, Editor020Blocked, sha256_file


def load_topt(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    spec = TOPT_CHECKPOINTS[seed]
    start_sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    model = build_odst046_model()
    load_state_dict(model, spec["checkpoint"], strict=True)
    model.to(device)
    freeze_teacher(model)
    assert_odst046(model)
    return model, start_sha


def student_from_topt(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    spec = TOPT_CHECKPOINTS[seed]
    start_sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    student = build_odst046_model()
    load_state_dict(student, spec["checkpoint"], strict=True)
    student.to(device)
    enable_student(student)
    assert_odst046(student)
    return student, start_sha


def make_l1_modules() -> Editor013Modules:
    return make_modules({"family": "linear", "readout": "none", "hybrid": False})


def forward_student(
    arch: str,
    student: nn.Module,
    x: torch.Tensor,
    modules: Editor013Modules | None = None,
) -> dict[str, torch.Tensor]:
    if arch == "L1":
        if modules is None:
            raise Editor020Blocked("L1 forward requires linear modules")
        return editor013_forward(student, x, modules)
    return student_forward(student, x)


def build_optimizer(arch: str, student: nn.Module, modules: Editor013Modules | None) -> torch.optim.Optimizer:
    if arch == "L1":
        if modules is None:
            raise Editor020Blocked("L1 optimiser requires linear modules")
        return build_editor013_optimizer(student, modules, encoder_trainable=True)
    from editor012_rescue.models import build_student_optimizer

    enable_student(student)
    return build_student_optimizer(student)


def condition_flags(arch: str, objective: str) -> dict[str, Any]:
    if objective not in ARCH_SPECS[arch]["objectives"]:
        raise Editor020Blocked(f"{arch}-{objective} is not an authorised condition")
    spec = OBJECTIVES[objective]
    return {
        "arch": arch,
        "objective": objective,
        "family": ARCH_SPECS[arch]["family"],
        "task_clean": bool(spec["task_clean"]),
        "task_degraded": bool(spec["task_degraded"]),
        "teacher_clean": bool(spec["teacher_clean"]),
        "teacher_degraded": bool(spec["teacher_degraded"]),
        "route_clean": bool(ARCH_SPECS[arch]["route_clean"]),
        "route_robust": bool(spec["route_robust"]) and bool(ARCH_SPECS[arch]["route_anchor"]),
        "needs_degraded": bool(spec["task_degraded"] or spec["teacher_degraded"] or spec["route_robust"]),
    }


def save_checkpoint(
    *,
    arch: str,
    objective: str,
    seed: int,
    student: nn.Module,
    modules: Editor013Modules | None,
    extra: dict[str, Any],
) -> tuple[str, str]:
    out_dir = OUTPUT_ROOT / f"{arch}-{objective}" / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "best.pt"
    payload = {
        "student_state_dict": {k: v.detach().cpu().clone() for k, v in student.state_dict().items()},
        "modules_state_dict": None
        if modules is None
        else {k: v.detach().cpu().clone() for k, v in modules.state_dict().items()},
        "arch": arch,
        "objective": objective,
        "seed": seed,
        "campaign": "EDITOR-020",
        "test_evaluated": False,
        **extra,
    }
    torch.save(payload, path)
    return str(path), sha256_file(path)


def load_trained(arch: str, objective: str, seed: int, device: torch.device) -> dict[str, Any]:
    path = OUTPUT_ROOT / f"{arch}-{objective}" / f"seed{seed}" / "best.pt"
    payload = torch.load(path, map_location="cpu", weights_only=False)
    student = build_odst046_model()
    student.load_state_dict(payload["student_state_dict"])
    student.to(device)
    student.eval()
    modules = None
    if arch == "L1":
        modules = make_l1_modules()
        modules.load_state_dict(payload["modules_state_dict"])
        modules.to(device)
        modules.eval()
    else:
        assert_odst046(student)
    return {"student": student, "modules": modules, "payload": payload, "path": str(path)}


def load_frozen_clean(arch: str, seed: int, device: torch.device) -> dict[str, Any]:
    if arch == "L1":
        student, modules, sha = load_l1_pair(seed, device)
        return {"student": student, "modules": modules, "sha256": sha, "family": "linear"}
    if arch == "TA2":
        model, sha = load_ta2(seed, device)
        return {"student": model, "modules": None, "sha256": sha, "family": "odst"}
    spec = F10_CHECKPOINTS[seed]
    sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    model = build_odst046_model()
    load_state_dict(model, spec["checkpoint"], strict=True)
    model.to(device)
    model.eval()
    freeze_teacher(model)
    return {"student": model, "modules": None, "sha256": sha, "family": "odst"}


def identities_ok() -> dict[str, Any]:
    teacher = build_odst046_model()
    student = build_odst046_model()
    assert_odst046(teacher)
    assert_odst046(student)
    assert_teacher_student_match(teacher, student)
    return {"odst046": architecture_identity(teacher), "match": True}
