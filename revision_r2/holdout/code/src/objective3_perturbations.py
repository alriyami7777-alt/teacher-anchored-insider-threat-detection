#!/usr/bin/env python3
"""Fixed, non-adversarial input perturbations for Objective 3 pilot.

Perturbation definitions are developed and selected on validation data only.
Levels are fixed at 5%, 10%, and 20%. No gradient-based adversarial search.

Paired fairness
---------------
``paired_rng_seed(perturbation_seed, scenario, level)`` is independent of the
model checkpoint / model training seed. The same (perturbation_seed, scenario,
level) therefore yields identical masks or noise for every locked model.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

import numpy as np

from objective3_locked_common import (
    BINARY_FEATURE_INDICES,
    CONTINUOUS_FEATURE_INDICES,
    N_FEATURES,
    SAFE_FEATURES,
)

# Canonical scenario names used in results / manifests.
SCENARIO_RANDOM_OBSERVATION_MASKING = "random_observation_masking"
SCENARIO_MISSING_RANDOM_FEATURES = "missing_random_features"
SCENARIO_MISSING_COMPLETE_DAYS = "missing_complete_days"
SCENARIO_GAUSSIAN_NOISE = "gaussian_noise_continuous"

# Legacy name kept only for metadata / CLI compatibility. The implementation
# zeros day-level tensor observations; it does NOT remove events from raw logs
# and reconstruct daily features.
SCENARIO_LEGACY_NAMES = {
    "missing_random_events": SCENARIO_RANDOM_OBSERVATION_MASKING,
}

CANONICAL_SCENARIOS = (
    SCENARIO_RANDOM_OBSERVATION_MASKING,
    SCENARIO_MISSING_RANDOM_FEATURES,
    SCENARIO_MISSING_COMPLETE_DAYS,
    SCENARIO_GAUSSIAN_NOISE,
)

# Stable integer codes for seed mixing (must not rely on PYTHONHASHSEED).
_SCENARIO_CODES = {
    SCENARIO_RANDOM_OBSERVATION_MASKING: 1,
    SCENARIO_MISSING_RANDOM_FEATURES: 2,
    SCENARIO_MISSING_COMPLETE_DAYS: 3,
    SCENARIO_GAUSSIAN_NOISE: 4,
}


def canonicalize_scenario(scenario: str) -> str:
    """Map legacy scenario names to the canonical name."""
    return SCENARIO_LEGACY_NAMES.get(scenario, scenario)


def paired_rng_seed(perturbation_seed: int, scenario: str, level: float) -> int:
    """Derive a deterministic RNG seed shared across all models.

    Depends only on (perturbation_seed, canonical scenario, level). Model seed
    and checkpoint identity are intentionally excluded so comparisons are paired.
    """
    scenario = canonicalize_scenario(scenario)
    if scenario not in _SCENARIO_CODES:
        raise ValueError(f"Unknown scenario for paired RNG: {scenario}")
    level_code = int(round(float(level) * 1000))
    payload = f"{int(perturbation_seed)}|{scenario}|{level_code}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    # 63-bit positive int suitable for np.random.default_rng
    return int(digest[:16], 16) % (2**63)


def _validate_batch(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim != 3 or x.shape[-1] != N_FEATURES:
        raise ValueError(f"Expected (N, T, {N_FEATURES}); got {x.shape}")
    return x.copy()


def mask_feature_channel(x: np.ndarray, feature_index: int) -> np.ndarray:
    """Zero one feature channel across all timesteps (feature masking)."""
    if not 0 <= feature_index < N_FEATURES:
        raise ValueError(f"feature_index must be in [0, {N_FEATURES}); got {feature_index}")
    out = _validate_batch(x)
    out[:, :, feature_index] = 0.0
    return out


def random_observation_masking(
    x: np.ndarray, level: float, rng: np.random.Generator
) -> np.ndarray:
    """Zero a fraction of random (sequence, day) observation slots in the tensor.

    This operates on already-built daily feature tensors. It does **not** remove
    events from raw CERT logs or rebuild daily aggregates. Continuous count
    features and binary activity flags are jointly cleared for each selected day.
    Level is the fraction of (N, T) day-slots targeted.
    """
    out = _validate_batch(x)
    n, t, _ = out.shape
    n_drop = int(round(level * n * t))
    if n_drop <= 0:
        return out
    flat_idx = rng.choice(n * t, size=min(n_drop, n * t), replace=False)
    rows = flat_idx // t
    cols = flat_idx % t
    for i, j in zip(rows, cols):
        out[i, j, CONTINUOUS_FEATURE_INDICES] = 0.0
        out[i, j, BINARY_FEATURE_INDICES] = 0.0
    return out


# Backwards-compatible alias (legacy name). Prefer random_observation_masking.
missing_random_events = random_observation_masking


def missing_random_features(x: np.ndarray, level: float, rng: np.random.Generator) -> np.ndarray:
    """Zero a fraction of feature channels independently per sequence."""
    out = _validate_batch(x)
    n, _, f = out.shape
    n_feat = max(1, int(round(level * f)))
    n_feat = min(n_feat, f)
    for i in range(n):
        idxs = rng.choice(f, size=n_feat, replace=False)
        out[i, :, idxs] = 0.0
    return out


def missing_complete_days(x: np.ndarray, level: float, rng: np.random.Generator) -> np.ndarray:
    """Zero a fraction of timesteps (complete days) per sequence."""
    out = _validate_batch(x)
    n, t, _ = out.shape
    n_days = max(1, int(round(level * t)))
    n_days = min(n_days, t)
    for i in range(n):
        days = rng.choice(t, size=n_days, replace=False)
        out[i, days, :] = 0.0
    return out


def gaussian_noise_continuous(
    x: np.ndarray,
    level: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Add bounded Gaussian noise to continuous features only.

    Noise std = level * per-feature |x| scale (elementwise), then clip to keep
    non-negative counts/durations. Binary features are untouched.
    """
    out = _validate_batch(x)
    cont = out[:, :, CONTINUOUS_FEATURE_INDICES]
    scale = np.maximum(np.abs(cont), 1e-3)
    noise = rng.normal(loc=0.0, scale=level, size=cont.shape).astype(np.float32) * scale
    bound = level * scale
    noise = np.clip(noise, -bound, bound)
    cont = cont + noise
    cont = np.maximum(cont, 0.0)
    out[:, :, CONTINUOUS_FEATURE_INDICES] = cont
    return out


PERTURBATION_FNS: dict[str, Callable[[np.ndarray, float, np.random.Generator], np.ndarray]] = {
    SCENARIO_RANDOM_OBSERVATION_MASKING: random_observation_masking,
    SCENARIO_MISSING_RANDOM_FEATURES: missing_random_features,
    SCENARIO_MISSING_COMPLETE_DAYS: missing_complete_days,
    SCENARIO_GAUSSIAN_NOISE: gaussian_noise_continuous,
    # Legacy key resolves to the same function; canonicalize before lookup in apply.
    "missing_random_events": random_observation_masking,
}


def apply_perturbation(
    x: np.ndarray,
    scenario: str,
    level: float,
    seed: int,
) -> np.ndarray:
    """Apply a fixed perturbation.

    ``seed`` should be the *perturbation realization seed* (or a value derived
    solely via ``paired_rng_seed``). Do not mix in the model training seed.
    """
    scenario = canonicalize_scenario(scenario)
    if scenario not in PERTURBATION_FNS:
        raise ValueError(f"Unknown perturbation scenario: {scenario}")
    if not (0.0 < level <= 1.0):
        raise ValueError(f"level must be in (0, 1]; got {level}")
    rng = np.random.default_rng(int(seed))
    return PERTURBATION_FNS[scenario](x, level, rng)


def apply_paired_perturbation(
    x: np.ndarray,
    scenario: str,
    level: float,
    perturbation_seed: int,
) -> np.ndarray:
    """Apply perturbation with a model-independent paired RNG seed."""
    rng_seed = paired_rng_seed(perturbation_seed, scenario, level)
    return apply_perturbation(x, scenario, level, seed=rng_seed)


def feature_mask_all(x: np.ndarray) -> list[tuple[str, int, np.ndarray]]:
    """Return (feature_name, index, masked_x) for each of the 13 features."""
    return [(name, i, mask_feature_channel(x, i)) for i, name in enumerate(SAFE_FEATURES)]


# Future faithfulness / deletion experiments should call the common inference
# interface rather than soft-forest routing. These names document planned hooks;
# no faithfulness metrics are computed here.
FUTURE_INFERENCE_COMPATIBLE_PERTURBATIONS = (
    "feature_channel_masking",
    "grouped_log_source_masking",
    "timestep_masking",
    "high_attention_timestep_deletion",
    "low_attention_timestep_deletion",
    "odst_ranked_feature_deletion",
    "random_deletion_controls",
)


def to_torch_batch(x: np.ndarray) -> "torch.Tensor":
    """Convert a (B,T,F) numpy batch to float32 torch tensor (CPU) for inference."""
    import torch

    arr = _validate_batch(x)
    return torch.from_numpy(np.array(arr, dtype=np.float32, copy=True))


def run_inference_on_perturbed_batch(
    loaded_model: Any,
    x_perturbed: np.ndarray,
    *,
    mask: Any | None = None,
    threshold: float | None = None,
    return_explanations: bool = True,
) -> Any:
    """Thin adapter: perturbed numpy → ``objective3_inference`` (no metrics).

    Intended for future robustness/faithfulness work. Does not open datasets.
    """
    from objective3_model_interface import objective3_inference

    return objective3_inference(
        loaded_model,
        to_torch_batch(x_perturbed),
        mask=mask,
        threshold=threshold,
        return_explanations=return_explanations,
        require_gradients=False,
    )
