"""Reuse the hash-gated EDITOR-018 40-summary and L1 caches."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor018_cross_view.cache import (
    cached_l1_logits,
    cached_summaries,
    fit_and_transform_views,
    load_ensemble_split,
    load_train_only,
    score_l1_logits,
)

from .safety import OUTPUT_ROOT, sha256_file


def cache_dir() -> Path:
    path = OUTPUT_ROOT / "head_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def mirror_editor018_cache(editor018_root: Path) -> dict[str, Any]:
    src = editor018_root / "outputs" / "editor018_cross_view_tree_rescue" / "head_cache"
    copied = []
    if src.is_dir():
        dest = cache_dir()
        for path in src.glob("*.npy"):
            target = dest / path.name
            if not target.is_file():
                target.write_bytes(path.read_bytes())
            copied.append({"name": path.name, "sha256": sha256_file(target)})
    return {"source": str(src), "copied": copied}


__all__ = [
    "cached_l1_logits",
    "cached_summaries",
    "fit_and_transform_views",
    "load_ensemble_split",
    "load_train_only",
    "score_l1_logits",
    "cache_dir",
    "mirror_editor018_cache",
]
