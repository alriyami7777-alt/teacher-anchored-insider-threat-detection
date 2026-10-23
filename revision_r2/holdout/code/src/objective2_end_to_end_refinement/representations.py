"""Representation stage extraction (P0–P3) for frozen encoder probes."""

from __future__ import annotations

from typing import Any, Iterator

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from prototype_v3_node.architecture import AttentionNodeEnsemble

STAGE_ALIASES = {
    "P0": "raw_sequence_flat",
    "P1": "bilstm_hidden_sequence_flat",
    "P2": "attention_pooled",
    "P3": "odst_input",
}


@torch.no_grad()
def extract_stage_batch(
    model: AttentionNodeEnsemble,
    x: torch.Tensor,
    stage: str,
) -> torch.Tensor:
    """Extract a representation stage without updating parameters."""
    if stage == "P0":
        return x.reshape(x.size(0), -1)
    model.eval()
    # Exact graph: LSTM -> dropout -> attention pool; ODST input is pooled vector.
    hidden, _ = model.lstm(x)
    hidden = model.dropout(hidden)
    if stage == "P1":
        return hidden.reshape(hidden.size(0), -1)
    aggregated, _attn = model.attention(hidden)
    if stage in {"P2", "P3"}:
        return aggregated
    raise ValueError(f"Unknown stage {stage!r}")


def stages_to_probe(p2_equals_p3: bool = True) -> list[dict[str, Any]]:
    stages = [
        {"stage_id": "P0", "aliases": ["P0"], "dim": 20 * 13, "description": STAGE_ALIASES["P0"]},
        {
            "stage_id": "P1",
            "aliases": ["P1"],
            "dim": 20 * 128,
            "description": STAGE_ALIASES["P1"],
        },
    ]
    if p2_equals_p3:
        stages.append(
            {
                "stage_id": "P2_P3",
                "aliases": ["P2", "P3"],
                "dim": 128,
                "description": "attention_pooled_identical_to_odst_input",
                "p2_equals_p3": True,
            }
        )
    else:
        stages.append(
            {"stage_id": "P2", "aliases": ["P2"], "dim": 128, "description": STAGE_ALIASES["P2"]}
        )
        stages.append(
            {"stage_id": "P3", "aliases": ["P3"], "dim": 128, "description": STAGE_ALIASES["P3"]}
        )
    return stages


def verify_p2_p3_identity(
    model: AttentionNodeEnsemble,
    x: torch.Tensor,
    atol: float = 0.0,
) -> dict[str, Any]:
    p2 = extract_stage_batch(model, x, "P2")
    p3 = extract_stage_batch(model, x, "P3")
    identical = bool(torch.equal(p2, p3)) if atol == 0 else bool(torch.allclose(p2, p3, atol=atol))
    # Also confirm forward path uses the same tensor without transform.
    aggregated, _ = model.encode_attention_h(x)
    return {
        "numerically_identical": identical,
        "max_abs_diff": float((p2 - p3).abs().max().item()),
        "matches_encode_attention_h": bool(torch.equal(p2, aggregated)),
        "semantic_note": (
            "P3 is the exact tensor received by node_head; architecture passes "
            "attention-pooled aggregated with no projection/normalisation."
        ),
    }


def iter_stage_batches(
    model: AttentionNodeEnsemble,
    loader: DataLoader,
    stage: str,
    device: torch.device,
) -> Iterator[tuple[torch.Tensor, torch.Tensor]]:
    model.eval()
    for xb, yb in loader:
        xb = xb.to(device)
        yb = yb.to(device)
        with torch.no_grad():
            feat = extract_stage_batch(model, xb, "P2" if stage == "P2_P3" else stage)
        yield feat, yb


def count_trainable(module: nn.Module) -> int:
    return sum(p.numel() for p in module.parameters() if p.requires_grad)
