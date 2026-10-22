"""Architecture-value ruling. Criteria frozen before new-severity results."""

from __future__ import annotations

from typing import Any

from .constants import PRIMARY_SEEDS
from .curves import seed_direction


def _lb(ci: list[float] | None) -> float:
    if not ci:
        return float("nan")
    return float(ci[0])


def teacher_guidance_clean_value(ta2_minus_c2: float, seeds_pos: int) -> str:
    if ta2_minus_c2 <= 0:
        return "CONTRADICTED"
    if seeds_pos == 3:
        return "SUPPORTED_STRONG"
    return "PRESERVED"


def teacher_guidance_degraded_value(
    src_delta: float,
    noise_delta: float,
    src_ci: list[float],
    noise_ci: list[float],
) -> str:
    src_pos = src_delta > 0
    noise_pos = noise_delta > 0
    src_ci_pos = _lb(src_ci) > 0
    noise_ci_pos = _lb(noise_ci) > 0
    other_nonneg = (src_delta >= 0) and (noise_delta >= 0)
    if other_nonneg and (src_ci_pos or noise_ci_pos) and (src_pos or noise_pos):
        if src_pos and noise_pos and (src_ci_pos or noise_ci_pos):
            return "SUPPORTED_STRONG"
        return "SUPPORTED"
    if src_pos and noise_pos:
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def route_anchor_structural_value(
    clean_ta2_mae: float,
    clean_f10_mae: float,
    degraded_ta2_mae: float,
    degraded_f10_mae: float,
) -> str:
    clean_better = clean_ta2_mae < clean_f10_mae
    degraded_better = degraded_ta2_mae < degraded_f10_mae
    if clean_better and degraded_better:
        return "SUPPORTED"
    return "NOT_SUPPORTED"


def odst_degraded_over_linear(
    src_delta: float,
    noise_delta: float,
    src_ci: list[float],
    noise_ci: list[float],
) -> str:
    src_pos = src_delta > 0
    noise_pos = noise_delta > 0
    src_ci_pos = _lb(src_ci) > 0
    noise_ci_pos = _lb(noise_ci) > 0
    if src_pos and noise_pos and (src_ci_pos or noise_ci_pos):
        return "SUPPORTED"
    if src_pos and noise_pos:
        return "CONSISTENT"
    return "NOT_SUPPORTED"


def overall_architecture_value(
    clean: str,
    degraded: str,
    route: str,
    odst_linear: str,
) -> str:
    clean_ok = clean in {"SUPPORTED_STRONG", "PRESERVED"}
    degraded_ok = degraded in {"SUPPORTED_STRONG", "SUPPORTED", "CONSISTENT"}
    route_ok = route == "SUPPORTED"
    linear_ok = odst_linear in {"SUPPORTED", "CONSISTENT"}
    if not clean_ok:
        return "NOT_SUPPORTED"
    if degraded in {"SUPPORTED_STRONG", "SUPPORTED"} and route_ok and linear_ok:
        return "SUPPORTED"
    if degraded_ok or route_ok or linear_ok:
        return "SUPPORTED_WITH_QUALIFICATION"
    return "NOT_SUPPORTED"


def explanation_stability_value(ta2_minus_f10: float) -> str:
    return "SUPPORTED" if ta2_minus_f10 > 0 else "NOT_SUPPORTED"


def seed_direction_table(source_aurc: dict[str, Any], noise_aurc: dict[str, Any], clean_by_seed: dict[str, dict[int, float]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    clean_ta2_c2 = {s: clean_by_seed["TA2"][s] - clean_by_seed["C2-OPT"][s] for s in PRIMARY_SEEDS}
    clean_f10_c2 = {s: clean_by_seed["F10"][s] - clean_by_seed["C2-OPT"][s] for s in PRIMARY_SEEDS}
    out["TA2_minus_C2_CLEAN"] = seed_direction(clean_ta2_c2, higher_is_better=True)
    out["F10_minus_C2_CLEAN"] = seed_direction(clean_f10_c2, higher_is_better=True)
    for name, block in (("SOURCE_AURC", source_aurc), ("NOISE_AURC", noise_aurc)):
        for contrast, mapping in block["per_seed_deltas"].items():
            keyed = {int(k): float(v) for k, v in mapping.items()}
            out[f"{contrast}_{name}"] = seed_direction(keyed, higher_is_better=True)
    return out
