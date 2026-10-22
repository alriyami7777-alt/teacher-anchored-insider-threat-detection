"""User-relative scaler. Fit only on r5.2 TRAIN user-relative daily values. Transform-only elsewhere."""

from __future__ import annotations

from typing import Any

import numpy as np

from .constants import FEATURE_ORDER, SCALE_NETWORK_SCALER_FIT_DATA
from .safety import Editor027Blocked


class ScaleNetworkScaler:
    """Z-score scaler. Fit exclusively on r5.2 TRAIN user-relative daily values."""

    def __init__(self) -> None:
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.fitted_on = None
        self.n_fit_rows = 0

    def fit(self, x: np.ndarray, *, source: str) -> None:
        if source not in {SCALE_NETWORK_SCALER_FIT_DATA, "R52 TRAIN ONLY", "CERT r5.2 TRAIN ONLY"}:
            raise Editor027Blocked(f"SCALE network scaler fit source refused: {source}")
        v = np.asarray(x, dtype=np.float64)
        if v.ndim == 3:
            v = v.reshape(-1, v.shape[-1])
        if v.ndim != 2 or v.shape[1] != len(FEATURE_ORDER):
            raise Editor027Blocked(f"scaler fit shape {v.shape} != (*, 13)")
        self.mean_ = v.mean(axis=0)
        scale = v.std(axis=0, ddof=0)
        scale[scale == 0.0] = 1.0
        self.scale_ = scale
        self.fitted_on = "CERT r5.2 TRAIN ONLY"
        self.n_fit_rows = int(v.shape[0])

    def transform(self, x: np.ndarray) -> np.ndarray:
        if self.mean_ is None or self.scale_ is None:
            raise Editor027Blocked("SCALE network scaler has not been fitted on r5.2 TRAIN")
        arr = np.asarray(x, dtype=np.float64)
        m = self.mean_.reshape((1,) * (arr.ndim - 1) + (-1,))
        s = self.scale_.reshape(m.shape)
        return ((arr - m) / s).astype(np.float32)

    def to_dict(self) -> dict[str, Any]:
        if self.mean_ is None or self.scale_ is None:
            raise Editor027Blocked("SCALE network scaler not fitted")
        return {
            "features": list(FEATURE_ORDER),
            "mean": self.mean_.tolist(),
            "scale": self.scale_.tolist(),
            "fitted_on": self.fitted_on,
            "SCALE_NETWORK_SCALER_FIT_DATA": SCALE_NETWORK_SCALER_FIT_DATA,
            "R61_SCALER_FIT": "NO",
            "R61_TARGET_NORMALISATION_FIT": "NO",
            "n_fit_rows": self.n_fit_rows,
            "note": (
                "Per-user causal history is part of the input representation and is "
                "not target-wide scaler fitting. This scaler is fit only on r5.2 TRAIN "
                "SCALE daily values after the causal scale-normalised transform."
            ),
        }

    @classmethod
    def from_dict(cls, rec: dict[str, Any]) -> "ScaleNetworkScaler":
        obj = cls()
        obj.mean_ = np.asarray(rec["mean"], dtype=np.float64)
        scale = np.asarray(rec["scale"], dtype=np.float64)
        scale = np.where(scale == 0.0, 1.0, scale)
        obj.scale_ = scale
        obj.fitted_on = rec.get("fitted_on", "CERT r5.2 TRAIN ONLY")
        obj.n_fit_rows = int(rec.get("n_fit_rows") or 0)
        if obj.fitted_on not in {"R52 TRAIN ONLY", "CERT r5.2 TRAIN ONLY", SCALE_NETWORK_SCALER_FIT_DATA}:
            raise Editor027Blocked("loaded scaler was not fit on r5.2 TRAIN")
        return obj
