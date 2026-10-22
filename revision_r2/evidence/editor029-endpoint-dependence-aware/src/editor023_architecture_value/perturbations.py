"""EDITOR-023 graded-source and dense-noise wrappers around frozen EDITOR-017 operators.

Labels never enter degradation construction.
d=1.00 is byte-identical to the historical complete source ablation.
Historical Gaussian levels 0.05 / 0.10 / 0.20 use the same paired RNG as EDITOR-017.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from objective3_perturbations import apply_paired_perturbation
from editor017_robustness.perturbations import (
    apply_source_ablation as editor017_apply_source_ablation,
    load_r52_train_scaler,
    perturbation_module_hashes,
)
from editor017_robustness.constants import NOISE_PERTURBATION_SEED, NOISE_SCENARIO, SOURCE_CHANNELS

from .constants import NOISE_LEVELS, SOURCE_DEGRADATION_LEVELS
from .safety import Editor023Blocked, sha256_bytes


def apply_source_ablation(x: np.ndarray, source: str, scaler: dict[str, Any]) -> np.ndarray:
    return editor017_apply_source_ablation(x, source, scaler)


def apply_graded_source(
    x_clean: np.ndarray,
    x_ablation: np.ndarray,
    d: float,
) -> np.ndarray:
    """Interpolate between clean and the exact historical ablation endpoint.

    x_degraded = (1 - d) * x_clean + d * x_historical_ablation
    """
    level = float(d)
    if level not in SOURCE_DEGRADATION_LEVELS:
        raise Editor023Blocked(f"unauthorised source degradation d={d}; frozen={SOURCE_DEGRADATION_LEVELS}")
    if x_clean.shape != x_ablation.shape:
        raise Editor023Blocked("clean/ablation shape mismatch")
    if level == 0.0:
        return np.asarray(x_clean, dtype=np.float32)
    if level == 1.0:
        return np.asarray(x_ablation, dtype=np.float32)
    clean = np.asarray(x_clean, dtype=np.float32)
    abl = np.asarray(x_ablation, dtype=np.float32)
    out = (1.0 - np.float32(level)) * clean + np.float32(level) * abl
    return np.asarray(out, dtype=np.float32)


def apply_gaussian_noise(x: np.ndarray, level: float) -> np.ndarray:
    lvl = float(level)
    if lvl not in NOISE_LEVELS:
        raise Editor023Blocked(f"unauthorised noise level {level}; frozen={NOISE_LEVELS}")
    if lvl == 0.0:
        return np.asarray(x, dtype=np.float32)
    out = apply_paired_perturbation(
        x,
        NOISE_SCENARIO,
        lvl,
        perturbation_seed=NOISE_PERTURBATION_SEED,
    )
    return np.asarray(out, dtype=np.float32)


def tensor_sha256(array: np.ndarray) -> str:
    arr = np.asarray(array)
    return sha256_bytes(arr.tobytes())


def build_source_family(x_clean: np.ndarray, scaler: dict[str, Any]) -> dict[str, dict[float, np.ndarray]]:
    """Build graded source tensors. d=1.00 is the exact EDITOR-017 ablation."""
    out: dict[str, dict[float, np.ndarray]] = {}
    x_clean = np.asarray(x_clean, dtype=np.float32)
    for src in SOURCE_CHANNELS:
        abl = apply_source_ablation(x_clean, src, scaler)
        if np.array_equal(abl, x_clean):
            raise Editor023Blocked(f"source ablation produced an unmodified tensor for {src}")
        family: dict[float, np.ndarray] = {0.0: x_clean}
        for d in SOURCE_DEGRADATION_LEVELS:
            if d == 0.0:
                continue
            family[float(d)] = apply_graded_source(x_clean, abl, float(d))
        d1 = family[1.0]
        if d1 is not abl and not np.array_equal(d1, abl):
            raise Editor023Blocked(f"d=1.00 endpoint is not identical to EDITOR-017 ablation for {src}")
        out[src] = family
    return out


def build_noise_family(x_clean: np.ndarray) -> dict[float, np.ndarray]:
    x_clean = np.asarray(x_clean, dtype=np.float32)
    out: dict[float, np.ndarray] = {0.0: x_clean}
    for lvl in NOISE_LEVELS:
        if float(lvl) == 0.0:
            continue
        out[float(lvl)] = apply_gaussian_noise(x_clean, float(lvl))
    return out
