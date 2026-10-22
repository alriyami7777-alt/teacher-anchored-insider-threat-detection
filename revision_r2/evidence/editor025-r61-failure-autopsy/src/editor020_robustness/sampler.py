"""Frozen family-first training corruption sampler.

The distribution is locked before any model result is viewed:

P(source) = 0.5, P(noise) = 0.5.

If source: uniform over the five frozen channels.
If noise: uniform over 0.05 / 0.10 / 0.20.

At most one degraded partner is generated per selected TRAIN example per step.
The clean example is always retained. Labels are never changed.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from editor017_robustness.perturbations import apply_gaussian_noise, apply_source_ablation

from .constants import (
    FAMILY_P_NOISE,
    FAMILY_P_SOURCE,
    NOISE_LEVELS,
    SAMPLER_SEED,
    SOURCE_CHANNELS,
)
from .safety import Editor020Blocked, Editor020ProtocolError


def _rng(epoch: int, index: int, *, seed: int = SAMPLER_SEED) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([int(seed), int(epoch), int(index)]))


def sample_partner(index: int, epoch: int, *, seed: int = SAMPLER_SEED) -> tuple[str, Any]:
    if abs(float(FAMILY_P_SOURCE) - 0.5) > 1e-15 or abs(float(FAMILY_P_NOISE) - 0.5) > 1e-15:
        raise Editor020ProtocolError("family-first sampler must remain exactly 0.5/0.5")
    rng = _rng(epoch, index, seed=seed)
    family = "source" if rng.random() < float(FAMILY_P_SOURCE) else "noise"
    if family == "source":
        channel = SOURCE_CHANNELS[int(rng.integers(0, len(SOURCE_CHANNELS)))]
        return "source", channel
    level = NOISE_LEVELS[int(rng.integers(0, len(NOISE_LEVELS)))]
    return "noise", float(level)


def apply_sampled_batch(
    x: np.ndarray,
    indices: np.ndarray,
    epoch: int,
    scaler: dict[str, Any],
    *,
    seed: int = SAMPLER_SEED,
) -> np.ndarray:
    """Apply one frozen sampled corruption to each row. Labels are not touched."""
    x = np.asarray(x, dtype=np.float32)
    idx = np.asarray(indices).reshape(-1).astype(np.int64)
    if x.shape[0] != idx.shape[0]:
        raise Editor020Blocked("sampler batch size does not match index vector")
    out = np.empty_like(x)
    families: list[tuple[str, Any]] = [sample_partner(int(i), int(epoch), seed=seed) for i in idx]
    for ch in SOURCE_CHANNELS:
        sl = [i for i, (fam, spec) in enumerate(families) if fam == "source" and spec == ch]
        if sl:
            out[sl] = apply_source_ablation(x[sl], ch, scaler)
    for level in NOISE_LEVELS:
        sl = [i for i, (fam, spec) in enumerate(families) if fam == "noise" and float(spec) == float(level)]
        if sl:
            out[sl] = apply_gaussian_noise(x[sl], float(level))
    if not np.isfinite(out).all():
        raise Editor020Blocked("non-finite values after sampled corruption")
    return out


def sampler_lock() -> dict[str, Any]:
    return {
        "SAMPLER_SEED": SAMPLER_SEED,
        "family_first": True,
        "P_source": FAMILY_P_SOURCE,
        "P_noise": FAMILY_P_NOISE,
        "source_channels": list(SOURCE_CHANNELS),
        "source_uniform": True,
        "noise_levels": list(NOISE_LEVELS),
        "noise_uniform": True,
        "at_most_one_degraded_partner_per_example_per_step": True,
        "clean_example_always_retained": True,
        "labels_unchanged_by_corruption": True,
        "validation_derived_corruption_parameters": False,
        "overweighting_source_ablation_avoided": "family_first_0.5_0.5_then_uniform_within_family",
        "rng": "numpy SeedSequence([SAMPLER_SEED, epoch, example_index])",
        "distribution_frozen_before_results": True,
    }


def empirical_family_rates(n: int = 20000, epoch: int = 0, *, seed: int = SAMPLER_SEED) -> dict[str, Any]:
    families = [sample_partner(i, epoch, seed=seed)[0] for i in range(n)]
    n_source = sum(f == "source" for f in families)
    return {
        "n": n,
        "p_source": n_source / n,
        "p_noise": 1.0 - n_source / n,
    }
