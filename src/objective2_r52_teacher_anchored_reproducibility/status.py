"""Final status labels for the r5.2 teacher-anchored reproducibility study."""

from __future__ import annotations

from typing import Any


def classify_final_status(
    *,
    gpu_blocked: bool = False,
    missing_teacher: bool = False,
    interface_mismatch: bool = False,
    initial_parity_failed: bool = False,
    safety_failure: bool = False,
    incomplete: bool = False,
    multiseed: dict[str, Any] | None = None,
    implementation_ok_all: bool = False,
) -> str:
    if gpu_blocked:
        return "objective2_r52_teacher_anchored_prepared_gpu_blocked"
    if missing_teacher:
        return "objective2_r52_teacher_anchored_blocked_missing_teacher"
    if interface_mismatch:
        return "objective2_r52_teacher_anchored_blocked_interface_mismatch"
    if initial_parity_failed:
        return "objective2_r52_teacher_anchored_blocked_initial_parity"
    if safety_failure:
        return "objective2_r52_teacher_anchored_stopped_safety_failure"
    if incomplete or multiseed is None:
        return "objective2_r52_teacher_anchored_incomplete"
    if not implementation_ok_all:
        return "objective2_r52_teacher_anchored_incomplete"
    if not multiseed.get("multiseed_viable"):
        return "objective2_r52_teacher_anchored_multiseed_not_supported"
    if multiseed.get("any_improved"):
        return "objective2_r52_teacher_anchored_multiseed_reproducible_with_improvement"
    return "objective2_r52_teacher_anchored_multiseed_reproducible_no_improvement"
