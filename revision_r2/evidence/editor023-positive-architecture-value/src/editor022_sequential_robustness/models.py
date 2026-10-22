"""CFP0 student / frozen-reference construction. No architecture search."""

from __future__ import annotations

from pathlib import Path
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
from editor021_cfpr.models import load_ta2_reference, load_ta2_student

from .constants import (
    CANDIDATES,
    CFP0_INNER_LOGICAL,
    CFP0_INNER_SHA256,
    EDITOR021_WORKTREE,
    PRIMARY_SEEDS,
)
from .safety import OUTPUT_ROOT, REPO_ROOT, Editor022Blocked, refuse_historical_write, sha256_file


def candidate_rho(name: str) -> float:
    key = str(name).replace("_FULL", "")
    if key not in CANDIDATES:
        raise Editor022Blocked(f"unauthorised candidate {name}")
    return float(CANDIDATES[key]["rho"])


def resolve_cfp0_inner_path(seed: int) -> Path:
    if int(seed) not in PRIMARY_SEEDS:
        raise Editor022Blocked(f"unauthorised seed {seed}")
    logical = CFP0_INNER_LOGICAL[int(seed)]
    sibling = EDITOR021_WORKTREE / logical
    local = REPO_ROOT / logical
    if sibling.is_file():
        return sibling
    if local.is_file():
        return local
    raise Editor022Blocked(f"EDITOR022_CFP0_CHECKPOINT_GATE = FAIL missing {logical}")


def hash_gate_cfp0_inner(seed: int) -> tuple[Path, str]:
    path = resolve_cfp0_inner_path(seed)
    observed = hash_gate_checkpoint(path, CFP0_INNER_SHA256[int(seed)])
    if observed != CFP0_INNER_SHA256[int(seed)]:
        raise Editor022Blocked("EDITOR022_CFP0_CHECKPOINT_GATE = FAIL")
    return path, observed


def hash_gate_all_cfp0_inner() -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    for seed in PRIMARY_SEEDS:
        path, sha = hash_gate_cfp0_inner(seed)
        out[int(seed)] = {
            "path": str(path),
            "logical_path": str(CFP0_INNER_LOGICAL[int(seed)]).replace("\\", "/"),
            "sha256": sha,
        }
    return out


def _load_cfp0_payload(seed: int) -> tuple[dict[str, Any], Path, str]:
    path, sha = hash_gate_cfp0_inner(seed)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if "student_state_dict" not in payload:
        raise Editor022Blocked(f"CFP0 checkpoint missing student_state_dict: {path}")
    return payload, path, sha


def load_cfp0_student(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    payload, _path, sha = _load_cfp0_payload(seed)
    student = build_odst046_model()
    student.load_state_dict(payload["student_state_dict"])
    student.to(device)
    enable_student(student)
    assert_odst046(student)
    return student, sha


def load_cfp0_reference(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    payload, _path, sha = _load_cfp0_payload(seed)
    ref = build_odst046_model()
    ref.load_state_dict(payload["student_state_dict"])
    ref.to(device)
    freeze_teacher(ref)
    ref.eval()
    assert_odst046(ref)
    for p in ref.parameters():
        if p.requires_grad:
            raise Editor022Blocked("frozen CFP0 reference parameter requires grad")
    return ref, sha


def load_cfp0_full_student(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    path = OUTPUT_ROOT / "CFP0_FULL" / f"seed{seed}" / "best.pt"
    if not path.is_file():
        raise Editor022Blocked(f"missing CFP0_FULL checkpoint {path}")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    student = build_odst046_model()
    student.load_state_dict(payload["student_state_dict"])
    student.to(device)
    enable_student(student)
    assert_odst046(student)
    return student, sha256_file(path)


def load_cfp0_full_reference(seed: int, device: torch.device) -> tuple[nn.Module, str]:
    path = OUTPUT_ROOT / "CFP0_FULL" / f"seed{seed}" / "best.pt"
    if not path.is_file():
        raise Editor022Blocked(f"missing CFP0_FULL checkpoint {path}")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    ref = build_odst046_model()
    ref.load_state_dict(payload["student_state_dict"])
    ref.to(device)
    freeze_teacher(ref)
    ref.eval()
    assert_odst046(ref)
    for p in ref.parameters():
        if p.requires_grad:
            raise Editor022Blocked("frozen CFP0_FULL reference parameter requires grad")
    return ref, sha256_file(path)


def assert_initial_match(student: nn.Module, reference: nn.Module, x: torch.Tensor, *, atol: float = 1e-6) -> dict[str, float]:
    student.eval()
    reference.eval()
    with torch.no_grad():
        s = student_forward(student, x)
        r = student_forward(reference, x)
    logit_mae = float((s["logit"] - r["logit"]).abs().max())
    z_mae = float((s["z"] - r["z"]).abs().max())
    if logit_mae > atol or z_mae > atol:
        raise Editor022Blocked(f"student/reference initial mismatch logit_mae={logit_mae} z_mae={z_mae}")
    return {"logit_max_abs": logit_mae, "z_max_abs": z_mae}


def build_optimizer(student: nn.Module) -> torch.optim.Optimizer:
    """Fresh inherited EDITOR-021/TA2 optimiser. Never restore CFP0 optimiser state."""
    enable_student(student)
    return build_student_optimizer(student)


def assert_reference_not_in_optimizer(reference: nn.Module, optimizer: torch.optim.Optimizer) -> None:
    ref_ids = {id(p) for p in reference.parameters()}
    for group in optimizer.param_groups:
        for p in group["params"]:
            if id(p) in ref_ids:
                raise Editor022Blocked("frozen reference parameter found in optimiser")


def save_checkpoint(
    *,
    candidate: str,
    seed: int,
    student: nn.Module,
    extra: dict[str, Any],
    filename: str,
) -> tuple[str, str]:
    out_dir = OUTPUT_ROOT / candidate / f"seed{seed}"
    refuse_historical_write(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    refuse_historical_write(path)
    payload = {
        "student_state_dict": {k: v.detach().cpu().clone() for k, v in student.state_dict().items()},
        "candidate": candidate,
        "seed": seed,
        "campaign": "EDITOR-022",
        "test_evaluated": False,
        "OPTIMISER_STATE_CONTINUED_FROM_CFP0": False,
        "FRESH_STAGE2_OPTIMISER": True,
        **extra,
    }
    torch.save(payload, path)
    return str(path), sha256_file(path)


def load_trained(candidate: str, seed: int, device: torch.device, *, filename: str | None = None) -> dict[str, Any]:
    if filename is None:
        filename = "best.pt" if candidate in {"CFP0_FULL"} else "stage2.pt"
    path = OUTPUT_ROOT / candidate / f"seed{seed}" / filename
    payload = torch.load(path, map_location="cpu", weights_only=False)
    student = build_odst046_model()
    student.load_state_dict(payload["student_state_dict"])
    student.to(device)
    student.eval()
    assert_odst046(student)
    return {"student": student, "payload": payload, "path": str(path), "sha256": sha256_file(path)}


def identities_ok() -> dict[str, Any]:
    teacher = build_odst046_model()
    student = build_odst046_model()
    assert_odst046(teacher)
    assert_odst046(student)
    assert_teacher_student_match(teacher, student)
    return {"odst046": architecture_identity(teacher), "match": True}


__all__ = [
    "load_cfp0_student",
    "load_cfp0_reference",
    "load_ta2_student",
    "load_ta2_reference",
    "load_topt",
    "load_ta2",
    "student_forward",
    "freeze_teacher",
    "load_state_dict",
]
