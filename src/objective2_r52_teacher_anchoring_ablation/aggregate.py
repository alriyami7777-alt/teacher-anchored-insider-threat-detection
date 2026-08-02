"""Aggregate per-seed ablation metrics → mean ± SD (no seed dropping)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .constants import METRIC_COLUMNS, PRIMARY_ALL_IDS


def rows_to_seed_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def mean_sd_table(seed_df: pd.DataFrame, *, config_order: tuple[str, ...] = PRIMARY_ALL_IDS) -> pd.DataFrame:
    """One row per config_id with mean/sd for each metric; all seeds retained."""
    out_rows: list[dict[str, Any]] = []
    present = [c for c in config_order if c in set(seed_df["config_id"].astype(str))]
    extra = [c for c in sorted(seed_df["config_id"].astype(str).unique()) if c not in present]
    for cid in present + extra:
        g = seed_df[seed_df["config_id"].astype(str) == cid]
        row: dict[str, Any] = {
            "config_id": cid,
            "n_seeds": int(len(g)),
            "seeds": ",".join(str(int(s)) for s in sorted(g["seed"].tolist())),
            "init": g["init"].iloc[0] if "init" in g.columns else "",
            "lambda_logit": float(g["lambda_logit"].iloc[0]) if "lambda_logit" in g.columns else float("nan"),
            "lambda_route": float(g["lambda_route"].iloc[0]) if "lambda_route" in g.columns else float("nan"),
            "purpose": g["purpose"].iloc[0] if "purpose" in g.columns else "",
            "role": g["role"].iloc[0] if "role" in g.columns else "",
            "source": g["source"].iloc[0] if "source" in g.columns else "",
        }
        for col in METRIC_COLUMNS:
            if col not in g.columns:
                row[f"{col}_mean"] = float("nan")
                row[f"{col}_sd"] = float("nan")
                continue
            vals = pd.to_numeric(g[col], errors="coerce").to_numpy(dtype=np.float64)
            row[f"{col}_mean"] = float(np.nanmean(vals)) if len(vals) else float("nan")
            row[f"{col}_sd"] = float(np.nanstd(vals, ddof=1)) if np.sum(np.isfinite(vals)) > 1 else (
                0.0 if np.sum(np.isfinite(vals)) == 1 else float("nan")
            )
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def format_mean_sd(mean: float, sd: float, digits: int = 4) -> str:
    if not np.isfinite(mean):
        return "n/a"
    if not np.isfinite(sd):
        return f"{mean:.{digits}f}"
    return f"{mean:.{digits}f} ± {sd:.{digits}f}"
