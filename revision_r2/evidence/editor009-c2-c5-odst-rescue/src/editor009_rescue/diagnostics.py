"""EDITOR009_DIAGNOSTIC_ONLY ODST state, permutation, and matching diagnostics."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
from scipy.optimize import linear_sum_assignment

from .losses import route_consistency_loss
from .models import student_forward, teacher_forward


def odst_state_from_forward(out: dict[str, torch.Tensor]) -> dict[str, float]:
    choices = out["choices"].detach()
    leaves = out["leaf_probs_all"].detach()
    trees = out["tree_outputs"].detach()
    p = choices.clamp(1e-8, 1 - 1e-8)
    route_ent = float((-(p * p.log() + (1 - p) * (1 - p).log())).mean().item())
    sat = float(((choices < 0.05) | (choices > 0.95)).float().mean().item())
    leaf_mass = leaves.mean(dim=0)
    active = float((leaf_mass > 1e-3).float().mean().item() * leaf_mass.numel())
    return {
        "EDITOR009_DIAGNOSTIC_ONLY": True,
        "routing_entropy": route_ent,
        "route_probability_saturation": sat,
        "tree_output_variance": float(trees.var(unbiased=False).item()),
        "per_tree_output_variance_mean": float(trees.var(dim=0, unbiased=False).mean().item()),
        "leaf_mass_max": float(leaf_mass.max().item()),
        "leaf_mass_min": float(leaf_mass.min().item()),
        "effective_active_leaves": active,
        "feature_selector_entropy": float(out["feature_selector_entropy"].detach().item()),
    }


@torch.no_grad()
def collect_odst_state(model, loader, device, *, residual: bool = False, max_batches: int = 16) -> dict[str, float]:
    model.eval()
    rows = []
    for i, (xb, _yb) in enumerate(loader):
        if i >= max_batches:
            break
        xb = xb.to(device)
        out = student_forward(model, xb, residual=residual)
        rows.append(odst_state_from_forward(out))
    keys = [k for k in rows[0] if k != "EDITOR009_DIAGNOSTIC_ONLY"]
    agg = {k: float(np.mean([r[k] for r in rows])) for k in keys}
    agg["EDITOR009_DIAGNOSTIC_ONLY"] = True
    return agg


@torch.no_grad()
def permutation_route_loss(teacher, student, xb, device, n_perm: int = 16, seed: int = 42) -> dict[str, Any]:
    tr = teacher_forward(teacher, xb.to(device))
    sr = student_forward(student, xb.to(device), residual=False)
    base = float(route_consistency_loss(sr["choices"], tr["choices"]).item())
    n_trees = sr["choices"].size(1)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_perm):
        perm = torch.as_tensor(rng.permutation(n_trees), device=device, dtype=torch.long)
        vals.append(float(route_consistency_loss(sr["choices"].index_select(1, perm), tr["choices"]).item()))
    mean_p = float(np.mean(vals))
    return {
        "raw_index_route_loss": base,
        "permuted_route_loss_mean": mean_p,
        "permuted_route_loss_std": float(np.std(vals)),
        "ratio_perm_over_raw": mean_p / max(base, 1e-12),
        "ROUTE_ANCHOR_PERMUTATION_SENSITIVE": "YES" if mean_p < 0.7 * base or mean_p > 1.3 * base else "NO",
    }


@torch.no_grad()
def match_trees_by_output(teacher_trees: torch.Tensor, student_trees: torch.Tensor) -> dict[str, Any]:
    """Deterministic Hungarian match per 8-tree layer. trees: (B, 16) for 2 layers × 8."""
    n = teacher_trees.size(1)
    layer_size = 8
    assignments = []
    matched = student_trees.clone()
    for start in range(0, n, layer_size):
        sl = slice(start, start + layer_size)
        t = teacher_trees[:, sl]
        s = student_trees[:, sl]
        cost = torch.cdist(s.transpose(0, 1), t.transpose(0, 1), p=2).cpu().numpy()
        ri, ci = linear_sum_assignment(cost)
        order = np.zeros(layer_size, dtype=np.int64)
        for r, c in zip(ri, ci):
            order[c] = r
        assignments.extend((int(start + int(c)), int(start + int(order[c]))) for c in range(layer_size))
        matched[:, sl] = s[:, torch.as_tensor(order)]
    return {"matched_student_trees": matched, "assignment": assignments}


@torch.no_grad()
def match_route_assignment_from_train(
    teacher, student, xb, device
) -> torch.Tensor:
    """Return perm such that teacher.choices.index_select(1, perm) is in student-index order."""
    tr = teacher_forward(teacher, xb.to(device))
    sr = student_forward(student, xb.to(device), residual=False)
    n = sr["choices"].size(1)
    layer_size = 8
    perm = torch.arange(n, device=device)
    for start in range(0, n, layer_size):
        sl = slice(start, start + layer_size)
        t = tr["tree_outputs"][:, sl]
        s = sr["tree_outputs"][:, sl]
        cost = torch.cdist(s.transpose(0, 1), t.transpose(0, 1), p=2).cpu().numpy()
        ri, ci = linear_sum_assignment(cost)
        for student_i, teacher_i in zip(ri, ci):
            perm[start + int(student_i)] = start + int(teacher_i)
    return perm
