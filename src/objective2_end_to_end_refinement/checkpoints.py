"""Pinned checkpoints and architecture defaults for end-to-end refinement."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prototype_v2.safety import default_v1_encoder_checkpoint, sha256_file

FUSION_VARIANT = "sparsemax_sigmoid_odst"

R42_ODST_CHECKPOINTS: dict[int, dict[str, Any]] = {
    42: {
        "seed": 42,
        "fusion_variant": FUSION_VARIANT,
        "relative_dir": (
            "outputs/v3_node/seed42_full_20260723_095912/"
            "seed42_full_20260723_095916/sparsemax_sigmoid_odst_seed42"
        ),
        "checkpoint_name": "best.pt",
        "expected_sha256": (
            "ff7ceb287df27689d3cd52bfee79e1aa617bbf1f72ba5f4769a3c4b7598d0167"
        ),
    },
    52: {
        "seed": 52,
        "fusion_variant": FUSION_VARIANT,
        "relative_dir": (
            "outputs/v3_node/seed52_full_20260723_101933/"
            "seed52_full_20260723_101936/sparsemax_sigmoid_odst_seed52"
        ),
        "checkpoint_name": "best.pt",
        "expected_sha256": (
            "8de6398b49a802b9676d564600614c84db679def6be2026761f2ed9c1502f182"
        ),
    },
    62: {
        "seed": 62,
        "fusion_variant": FUSION_VARIANT,
        "relative_dir": (
            "outputs/v3_node/seed62_full_20260723_102938/"
            "seed62_full_20260723_102942/sparsemax_sigmoid_odst_seed62"
        ),
        "checkpoint_name": "best.pt",
        "expected_sha256": (
            "af898f4845817833d2d30a9f93f034f62e9273df2e523fe3f7720f33e3c051fa"
        ),
    },
}

DEFAULT_ODST_HYPERPARAMS: dict[str, Any] = {
    "input_dim": 13,
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "fusion_variant": FUSION_VARIANT,
    "node_num_layers": 2,
    "node_n_trees": 8,
    "node_depth": 4,
    "node_tree_dim": 1,
    "node_temperature": 1.0,
    "node_dropout": 0.0,
    "leaf_init_std": 0.05,
    "gate_hidden_dim": 32,
}


def pretrained_encoder_path(repo_root: Path, seed: int) -> Path:
    return Path(default_v1_encoder_checkpoint(seed=seed, root=repo_root))


def resolve_frozen_odst(repo_root: Path, seed: int) -> dict[str, Path | str]:
    if seed not in R42_ODST_CHECKPOINTS:
        raise KeyError(f"No pinned ODST checkpoint for seed={seed}")
    meta = R42_ODST_CHECKPOINTS[seed]
    run_dir = (repo_root / meta["relative_dir"]).resolve()
    ckpt = run_dir / meta["checkpoint_name"]
    return {
        "run_dir": run_dir,
        "checkpoint": ckpt,
        "threshold_json": run_dir / "threshold.json",
        "summary_json": run_dir / "summary.json",
        "expected_sha256": meta["expected_sha256"],
    }


def verify_checkpoint_sha256(path: Path, expected: str) -> str:
    digest = sha256_file(path)
    if digest.lower() != expected.lower():
        raise RuntimeError(
            f"Checkpoint hash mismatch for {path}: got {digest}, expected {expected}"
        )
    return digest
