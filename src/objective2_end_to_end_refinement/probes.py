"""Deterministic linear probe protocol shared across representation stages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from torch.utils.data import DataLoader

from .protocol import PROBE_PROTOCOL
from .representations import extract_stage_batch


class LinearProbe(nn.Module):
    def __init__(self, in_dim: int) -> None:
        super().__init__()
        self.linear = nn.Linear(in_dim, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear(x).squeeze(-1)


class OnlineStandardizer:
    """Welford online mean/variance over training representation batches."""

    def __init__(self, dim: int) -> None:
        self.n = 0
        self.mean = np.zeros(dim, dtype=np.float64)
        self.m2 = np.zeros(dim, dtype=np.float64)

    def update(self, x: np.ndarray) -> None:
        x = np.asarray(x, dtype=np.float64)
        for row in x:
            self.n += 1
            delta = row - self.mean
            self.mean += delta / self.n
            delta2 = row - self.mean
            self.m2 += delta * delta2

    @property
    def var(self) -> np.ndarray:
        if self.n < 2:
            return np.ones_like(self.mean)
        return self.m2 / (self.n - 1)

    @property
    def std(self) -> np.ndarray:
        return np.sqrt(np.maximum(self.var, 1e-12))

    def transform_torch(self, x: torch.Tensor) -> torch.Tensor:
        mean = torch.as_tensor(self.mean, device=x.device, dtype=x.dtype)
        std = torch.as_tensor(self.std, device=x.device, dtype=x.dtype)
        return (x - mean) / std

    def state_dict(self) -> dict[str, Any]:
        return {"n": self.n, "mean": self.mean.tolist(), "std": self.std.tolist()}


def _fit_standardizer(model, loader, stage: str, device, dim: int) -> OnlineStandardizer:
    stdz = OnlineStandardizer(dim)
    key = "P2" if stage == "P2_P3" else stage
    model.eval()
    with torch.no_grad():
        for xb, _yb in loader:
            feat = extract_stage_batch(model, xb.to(device), key).cpu().numpy()
            stdz.update(feat)
    return stdz


def train_linear_probe(
    encoder,
    train_loader: DataLoader,
    val_loader: DataLoader,
    *,
    stage: str,
    in_dim: int,
    device: torch.device,
    n_pos_train: int,
    n_neg_train: int,
    seed: int = 42,
) -> dict[str, Any]:
    """Train one shared-protocol linear probe on a frozen representation stage."""
    torch.manual_seed(seed)
    np.random.seed(seed)

    # Freeze encoder completely.
    for p in encoder.parameters():
        p.requires_grad = False
    encoder.eval()

    cfg = PROBE_PROTOCOL
    stdz = _fit_standardizer(encoder, train_loader, stage, device, in_dim) if cfg["standardize"] else None
    probe = LinearProbe(in_dim).to(device)
    pos_weight = torch.tensor(
        [cfg["pos_weight_mult"] * (n_neg_train / max(n_pos_train, 1))],
        device=device,
        dtype=torch.float32,
    )
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.Adam(
        probe.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"]
    )

    key = "P2" if stage == "P2_P3" else stage
    history = []
    converged = True
    for epoch in range(1, int(cfg["epochs"]) + 1):
        probe.train()
        total = 0.0
        n = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            with torch.no_grad():
                feat = extract_stage_batch(encoder, xb, key)
                if stdz is not None:
                    feat = stdz.transform_torch(feat)
            opt.zero_grad(set_to_none=True)
            logits = probe(feat)
            loss = criterion(logits, yb)
            if not torch.isfinite(loss):
                converged = False
                break
            loss.backward()
            opt.step()
            bs = int(yb.size(0))
            total += float(loss.item()) * bs
            n += bs
        history.append({"epoch": epoch, "train_loss": total / max(n, 1)})
        if not converged:
            break

    # Validation evaluation
    probe.eval()
    logits_all = []
    y_all = []
    with torch.no_grad():
        for xb, yb in val_loader:
            xb = xb.to(device)
            feat = extract_stage_batch(encoder, xb, key)
            if stdz is not None:
                feat = stdz.transform_torch(feat)
            logits_all.append(probe(feat).cpu().numpy())
            y_all.append(yb.numpy())
    logits = np.concatenate(logits_all)
    y = np.concatenate(y_all).astype(int)
    probs = 1.0 / (1.0 + np.exp(-logits))
    coef_norm = float(probe.linear.weight.detach().norm().cpu().item())
    result = {
        "stage": stage,
        "in_dim": in_dim,
        "pr_auc": float(average_precision_score(y, probs)),
        "roc_auc": float(roc_auc_score(y, probs)),
        "brier": float(brier_score_loss(y, probs)),
        "log_loss": float(log_loss(y, np.clip(probs, 1e-7, 1 - 1e-7))),
        "converged": bool(converged and np.isfinite(probs).all()),
        "coefficient_norm": coef_norm,
        "history": history,
        "standardizer": stdz.state_dict() if stdz is not None else None,
        "scores": {
            "y_true": y,
            "logit": logits,
            "prob": probs,
        },
        "pos_score_mean": float(probs[y == 1].mean()) if (y == 1).any() else float("nan"),
        "neg_score_mean": float(probs[y == 0].mean()) if (y == 0).any() else float("nan"),
        "pos_score_std": float(probs[y == 1].std()) if (y == 1).any() else float("nan"),
        "neg_score_std": float(probs[y == 0].std()) if (y == 0).any() else float("nan"),
    }
    return result


def decide_probe_outcome(stage_results: list[dict[str, Any]]) -> str:
    by = {r["stage"]: r for r in stage_results}
    if any(not r.get("converged", False) for r in stage_results):
        return "representation_probe_invalid"
    p0 = by.get("P0", {}).get("pr_auc", float("nan"))
    p1 = by.get("P1", {}).get("pr_auc", float("nan"))
    p2 = by.get("P2_P3", by.get("P2", {})).get("pr_auc", float("nan"))
    if not np.isfinite([p0, p1, p2]).all():
        return "representation_probe_invalid"
    d01 = p0 - p1
    d12 = p1 - p2
    # Large declines
    if d01 >= 0.05 and d01 > d12:
        return "encoder_information_loss"
    if d12 >= 0.05 and d12 >= d01:
        return "attention_pooling_information_loss"
    if p2 >= 0.70:
        return "representation_preserved_odst_optimisation_likely"
    if max(p0, p1, p2) < 0.40:
        return "representation_probe_inconclusive"
    return "representation_probe_inconclusive"


def save_probe_protocol(path: Path) -> None:
    path.write_text(json.dumps(PROBE_PROTOCOL, indent=2), encoding="utf-8")
