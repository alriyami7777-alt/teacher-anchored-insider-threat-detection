"""Training and scoring loops for EDITOR-010 (inner encoder, cached heads, confirmation)."""

from __future__ import annotations

import copy
import random
import time
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from .constants import (
    BATCH_SIZE,
    GRAD_CLIP_NORM,
    LR_ATTENTION_LINEAR,
    MAX_EPOCHS,
    PATIENCE,
)
from .losses import combined_objective
from .metrics import evaluate_scores
from .models import build_encoder, build_head, extract_attended
from .safety import refuse_test_loader_construction


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def select_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _state_clone(model: nn.Module) -> dict[str, torch.Tensor]:
    return {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}


@torch.no_grad()
def predict_logits(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    logits_all: list[np.ndarray] = []
    y_all: list[np.ndarray] = []
    for batch in loader:
        xb = batch[0].to(device)
        yb = batch[1]
        out = model(xb)
        logit = out[0] if isinstance(out, tuple) else out
        logits_all.append(logit.detach().cpu().numpy())
        y_all.append(np.asarray(yb).reshape(-1))
    return np.concatenate(logits_all), np.concatenate(y_all)


def _predict_two(model: nn.Module, loader: DataLoader, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    return predict_logits(model, loader, device)


def evaluate_loader(model: nn.Module, loader: DataLoader, device: torch.device) -> dict[str, Any]:
    logits, y = _predict_two(model, loader, device)
    return evaluate_scores(y, logits=logits)


def train_attention_linear(
    train_loader: DataLoader,
    select_loader: DataLoader,
    *,
    pos_weight: float,
    seed: int,
    device: torch.device,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
    lr: float = LR_ATTENTION_LINEAR,
) -> dict[str, Any]:
    refuse_test_loader_construction(partition="inner_train")
    set_seed(seed)
    model = build_encoder().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=0.0)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, mode="max", factor=0.5, patience=2, min_lr=1e-5
    )
    pw = torch.tensor([pos_weight], device=device, dtype=torch.float32)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pw)
    best = -1.0
    wait = 0
    best_state = _state_clone(model)
    best_epoch = 0
    history: list[dict[str, Any]] = []
    t0 = time.time()
    for epoch in range(1, max_epochs + 1):
        model.train()
        running = 0.0
        n_seen = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            logit, _ = model(xb)
            loss = loss_fn(logit, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP_NORM)
            opt.step()
            running += float(loss.item()) * xb.size(0)
            n_seen += xb.size(0)
        sel = evaluate_loader(model, select_loader, device)
        tr = evaluate_loader(model, train_loader, device)
        sched.step(sel["pr_auc"])
        row = {
            "epoch": epoch,
            "train_loss": running / max(n_seen, 1),
            "train_pr_auc": tr["pr_auc"],
            "select_pr_auc": sel["pr_auc"],
            "select_f1": sel["f1"],
        }
        history.append(row)
        if sel["pr_auc"] > best:
            best = float(sel["pr_auc"])
            wait = 0
            best_state = _state_clone(model)
            best_epoch = epoch
        else:
            wait += 1
            if wait >= patience:
                break
    model.load_state_dict(best_state)
    return {
        "model": model,
        "best_epoch": best_epoch,
        "best_select_pr_auc": best,
        "history": history,
        "seconds": time.time() - t0,
        "seed": seed,
    }


@torch.no_grad()
def cache_embeddings(
    encoder: nn.Module,
    X: np.ndarray,
    y: np.ndarray,
    *,
    device: torch.device,
    batch_size: int = BATCH_SIZE,
) -> tuple[np.ndarray, np.ndarray]:
    encoder.eval()
    hs: list[np.ndarray] = []
    loader = DataLoader(
        TensorDataset(torch.from_numpy(np.asarray(X, dtype=np.float32))),
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
    )
    for (xb,) in loader:
        z = extract_attended(encoder, xb.to(device))
        hs.append(z.detach().cpu().numpy().astype(np.float32))
    return np.concatenate(hs, axis=0), np.asarray(y, dtype=np.float32).reshape(-1)


def train_head(
    head: nn.Module,
    h_train: np.ndarray,
    y_train: np.ndarray,
    h_select: np.ndarray,
    y_select: np.ndarray,
    *,
    objective: dict[str, Any],
    seed: int,
    device: torch.device,
    lr: float,
    weight_decay: float = 0.0,
    max_epochs: int = MAX_EPOCHS,
    patience: int = PATIENCE,
    collect_diagnostics: bool = False,
) -> dict[str, Any]:
    set_seed(seed)
    head = head.to(device)
    opt = torch.optim.Adam(head.parameters(), lr=lr, weight_decay=weight_decay)
    train_loader = DataLoader(
        TensorDataset(
            torch.from_numpy(np.asarray(h_train, dtype=np.float32)),
            torch.from_numpy(np.asarray(y_train, dtype=np.float32).reshape(-1)),
        ),
        batch_size=BATCH_SIZE,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
        num_workers=0,
    )
    select_loader = DataLoader(
        TensorDataset(
            torch.from_numpy(np.asarray(h_select, dtype=np.float32)),
            torch.from_numpy(np.asarray(y_select, dtype=np.float32).reshape(-1)),
        ),
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=0,
    )
    best = -1.0
    wait = 0
    best_state = _state_clone(head)
    best_epoch = 0
    last_grad = 0.0
    t0 = time.time()
    for epoch in range(1, max_epochs + 1):
        head.train()
        for hb, yb in train_loader:
            hb = hb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            logit, _ = head(hb)
            loss = combined_objective(
                logit,
                yb,
                family=str(objective["family"]),
                pos_weight=float(objective["pos_weight"]),
                gamma=float(objective.get("gamma", 0.0)),
                lambda_rank=float(objective.get("lambda_rank", 0.0)),
            )
            if "teacher_logits" in objective and objective.get("lambda_distill", 0) > 0:
                raise RuntimeError("distill logits must be passed per-batch; use train_head_distill")
            loss.backward()
            last_grad = float(nn.utils.clip_grad_norm_(head.parameters(), GRAD_CLIP_NORM))
            opt.step()
        sel = evaluate_loader(head, select_loader, device)
        if sel["pr_auc"] > best:
            best = float(sel["pr_auc"])
            wait = 0
            best_state = _state_clone(head)
            best_epoch = epoch
        else:
            wait += 1
            if wait >= patience:
                break
    head.load_state_dict(best_state)
    tr = evaluate_loader(
        head,
        DataLoader(
            TensorDataset(
                torch.from_numpy(np.asarray(h_train, dtype=np.float32)),
                torch.from_numpy(np.asarray(y_train, dtype=np.float32).reshape(-1)),
            ),
            batch_size=BATCH_SIZE,
            shuffle=False,
        ),
        device,
    )
    sel = evaluate_loader(head, select_loader, device)
    logits_sel, _ = _predict_two(head, select_loader, device)
    diag = {}
    if collect_diagnostics:
        from .diagnostics import odst_head_diagnostics

        diag = odst_head_diagnostics(head, h_select, device)
        diag["gradient_norm"] = last_grad
        diag["label"] = "EDITOR010_DIAGNOSTIC_ONLY"
    return {
        "head": head,
        "train_metrics": tr,
        "select_metrics": sel,
        "select_logits": logits_sel,
        "best_epoch": best_epoch,
        "seconds": time.time() - t0,
        "diagnostics": diag,
        "seed": seed,
    }


def train_head_distill(
    head: nn.Module,
    h_train: np.ndarray,
    y_train: np.ndarray,
    teacher_logits_train: np.ndarray,
    h_select: np.ndarray,
    y_select: np.ndarray,
    *,
    objective: dict[str, Any],
    seed: int,
    device: torch.device,
    lr: float,
    weight_decay: float = 0.0,
) -> dict[str, Any]:
    """O0 task loss + logit-level equal-weight ensemble distillation. No route anchoring."""
    set_seed(seed)
    head = head.to(device)
    opt = torch.optim.Adam(head.parameters(), lr=lr, weight_decay=weight_decay)
    train_loader = DataLoader(
        TensorDataset(
            torch.from_numpy(np.asarray(h_train, dtype=np.float32)),
            torch.from_numpy(np.asarray(y_train, dtype=np.float32).reshape(-1)),
            torch.from_numpy(np.asarray(teacher_logits_train, dtype=np.float32).reshape(-1)),
        ),
        batch_size=BATCH_SIZE,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
        num_workers=0,
    )
    select_loader = DataLoader(
        TensorDataset(
            torch.from_numpy(np.asarray(h_select, dtype=np.float32)),
            torch.from_numpy(np.asarray(y_select, dtype=np.float32).reshape(-1)),
        ),
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=0,
    )
    lam = float(objective.get("lambda_distill", 0.5))
    best = -1.0
    wait = 0
    best_state = _state_clone(head)
    best_epoch = 0
    t0 = time.time()
    for epoch in range(1, MAX_EPOCHS + 1):
        head.train()
        for hb, yb, tb in train_loader:
            hb = hb.to(device)
            yb = yb.to(device)
            tb = tb.to(device)
            opt.zero_grad(set_to_none=True)
            logit, _ = head(hb)
            task = combined_objective(
                logit,
                yb,
                family=str(objective["family"]),
                pos_weight=float(objective["pos_weight"]),
                gamma=float(objective.get("gamma", 0.0)),
                lambda_rank=float(objective.get("lambda_rank", 0.0)),
            )
            distill = torch.mean((logit - tb) ** 2)
            (task + lam * distill).backward()
            nn.utils.clip_grad_norm_(head.parameters(), GRAD_CLIP_NORM)
            opt.step()
        sel = evaluate_loader(head, select_loader, device)
        if sel["pr_auc"] > best:
            best = float(sel["pr_auc"])
            wait = 0
            best_state = _state_clone(head)
            best_epoch = epoch
        else:
            wait += 1
            if wait >= PATIENCE:
                break
    head.load_state_dict(best_state)
    tr = evaluate_loader(
        head,
        DataLoader(
            TensorDataset(
                torch.from_numpy(np.asarray(h_train, dtype=np.float32)),
                torch.from_numpy(np.asarray(y_train, dtype=np.float32).reshape(-1)),
            ),
            batch_size=BATCH_SIZE,
            shuffle=False,
        ),
        device,
    )
    sel = evaluate_loader(head, select_loader, device)
    logits_sel, _ = predict_logits(head, select_loader, device)
    return {
        "head": head,
        "train_metrics": tr,
        "select_metrics": sel,
        "select_logits": logits_sel,
        "best_epoch": best_epoch,
        "seconds": time.time() - t0,
        "ENSEMBLE_ROUTE_ANCHORING": "OFF",
        "seed": seed,
    }
