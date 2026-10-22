"""Hash-gated caches for L1 logits, teacher logits, 40 summaries, and labels."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor012_rescue.constants import EXPECTED_TRAIN_POS, EXPECTED_TRAIN_SHA256, EXPECTED_TRAIN_SHAPE, POS_WEIGHT_MULT
from editor012_rescue.data import SequenceBundle, _load_split, make_xy_loader
from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.safety import TRAIN_NPZ
from editor014_temporal_odst.constants import ENSEMBLE_CACHE
from editor015_residual.train import load_l1_pair
from editor017_robustness.score import score_l1_full

from .aggregate40 import (
    aggregate40,
    alignment_keys_hash,
    assert_no_metadata_in_features,
    fit_standard_scaler,
    metadata_keys_only,
    scaler_payload,
    transform_standard,
)
from .constants import BATCH_SIZE, L1_CHECKPOINTS, SUMMARY_DIM
from .safety import OUTPUT_ROOT, Editor018Blocked, Editor018ProtocolError, note_open, sha256_file
from .io_util import write_json


def load_train_only() -> dict[str, Any]:
    """Inner-phase loader. Official VALIDATION is not opened."""
    train = _load_split(TRAIN_NPZ, EXPECTED_TRAIN_SHA256, EXPECTED_TRAIN_SHAPE, EXPECTED_TRAIN_POS, "train")
    n_neg = int(len(train.y) - EXPECTED_TRAIN_POS)
    pos_weight = float((n_neg / max(EXPECTED_TRAIN_POS, 1)) * POS_WEIGHT_MULT)
    return {"train": train, "pos_weight": pos_weight, "n_train": int(len(train.y)), "val_opened": False}


def _cache_dir() -> Path:
    path = OUTPUT_ROOT / "head_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_npy(path: Path, arr: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, arr)
    return sha256_file(path)


def load_ensemble_split(split: str) -> dict[str, np.ndarray]:
    key = "train" if split == "train" else "val"
    paths = {
        "ens": ENSEMBLE_CACHE[f"{key}_ens"],
        "logit42": ENSEMBLE_CACHE[f"{key}_42"],
        "logit52": ENSEMBLE_CACHE[f"{key}_52"],
        "logit62": ENSEMBLE_CACHE[f"{key}_62"],
    }
    out = {}
    for name, path in paths.items():
        note_open(path, role=f"ensemble_{split}_{name}")
        out[name] = np.asarray(np.load(path), dtype=np.float32).reshape(-1)
    recomputed = (out["logit42"] + out["logit52"] + out["logit62"]) / 3.0
    if not np.allclose(recomputed, out["ens"], atol=1e-5, rtol=1e-5):
        raise Editor018Blocked("teacher ensemble cache is not the mean of T-OPT 42/52/62")
    return out


@torch.no_grad()
def score_l1_logits(
    seed: int,
    X: np.ndarray,
    y: np.ndarray,
    device: torch.device,
) -> np.ndarray:
    student, modules, _sha = load_l1_pair(seed, device)
    student.eval()
    modules.eval()
    loader = make_xy_loader(X, y, seed=0, batch_size=BATCH_SIZE, shuffle=False)
    scored = score_l1_full(student, modules, loader, device)
    if not np.array_equal(np.asarray(scored["y"]).reshape(-1), np.asarray(y).reshape(-1)):
        raise Editor018Blocked("L1 scoring label order mismatch")
    return np.asarray(scored["logits"], dtype=np.float32).reshape(-1)


def cached_l1_logits(
    *,
    seed: int,
    split: str,
    X: np.ndarray,
    y: np.ndarray,
    device: torch.device,
) -> tuple[np.ndarray, str]:
    path = _cache_dir() / f"l1_seed{seed}_{split}_logits.npy"
    if path.is_file():
        logits = np.asarray(np.load(path), dtype=np.float32).reshape(-1)
        if logits.shape[0] != len(y):
            raise Editor018ProtocolError(f"cached L1 logits length {logits.shape[0]} != {len(y)}")
        return logits, sha256_file(path)
    spec = L1_CHECKPOINTS[seed]
    hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    logits = score_l1_logits(seed, X, y, device)
    digest = save_npy(path, logits)
    return logits, digest


def cached_summaries(bundle: SequenceBundle, split: str) -> dict[str, Any]:
    raw_path = _cache_dir() / f"{split}_s40_raw.npy"
    if raw_path.is_file():
        raw = np.asarray(np.load(raw_path), dtype=np.float32)
    else:
        raw, names = aggregate40(bundle.X)
        if names != list(raw_path.with_name("unused").name) and raw.shape[0] != len(bundle.y):
            raise Editor018Blocked("summary row count does not match sequences")
        save_npy(raw_path, raw)
    if raw.shape != (len(bundle.y), SUMMARY_DIM):
        raise Editor018Blocked(f"{split} 40-view shape {raw.shape} != {(len(bundle.y), SUMMARY_DIM)}")
    meta = metadata_keys_only(bundle.user, bundle.sequence_id, bundle.start_date, bundle.end_date)
    assert_no_metadata_in_features(raw, meta)
    y = np.asarray(bundle.y, dtype=np.float32).reshape(-1)
    return {
        "s40_raw": raw,
        "y": y,
        "meta": meta,
        "raw_path": str(raw_path),
        "raw_sha256": sha256_file(raw_path),
        "alignment_sha256": alignment_keys_hash(meta),
        "n": int(len(y)),
        "n_pos": int(y.sum()),
    }


def fit_and_transform_views(
    *,
    train_raw: np.ndarray,
    other_raw: dict[str, np.ndarray],
    fitted_on: str,
) -> dict[str, Any]:
    scaler = fit_standard_scaler(train_raw)
    payload = scaler_payload(scaler, fitted_on=fitted_on)
    if payload["n_fit_rows"] != int(len(train_raw)):
        raise Editor018Blocked("scaler n_samples_seen mismatch")
    transformed = {"fit": transform_standard(scaler, train_raw)}
    for name, raw in other_raw.items():
        transformed[name] = transform_standard(scaler, raw)
    return {"scaler": scaler, "payload": payload, "transformed": transformed}


def write_head_cache_manifest(obj: dict[str, Any]) -> Path:
    path = OUTPUT_ROOT.parent.parent / "review" / "editor018_cross_view_tree_rescue" / "01_inner_cross_view" / "EDITOR018_HEAD_CACHE.json"
    # campaign writes the review copy; keep an outputs copy too
    out = _cache_dir() / "EDITOR018_HEAD_CACHE.json"
    write_json(out, obj)
    return out
