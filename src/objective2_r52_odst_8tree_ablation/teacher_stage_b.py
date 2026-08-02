"""Matched 8-tree frozen-representation teacher (Stage-B protocol, n_trees=4)."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from prototype_v3_node.architecture import (
    AttentionNodeEnsemble,
    load_v1_attention_linear_checkpoint,
)
from prototype_v3_node.diagnostics import gradient_norm_report
from prototype_v3_node.losses import v3_total_loss
from prototype_v3_node.train import (
    choose_threshold_f1,
    evaluate_loader_diagnostics,
    metrics_at_threshold,
    predict_with_extras,
    rebuild_optimizer_frozen,
    set_seed,
)

from .constants import (
    ANTI_COLLAPSE_WEIGHT,
    ARCHITECTURE,
    BATCH_SIZE,
    ENCODERS,
    EXPECTED_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_TRAIN_SHAPE,
    EXPECTED_VAL_POS,
    EXPECTED_VAL_SHA256,
    EXPECTED_VAL_SHAPE,
    GRAD_CLIP_NORM,
    LINEAR_AUX_WEIGHT,
    MAX_EPOCHS,
    NODE_AUX_WEIGHT,
    NODE_DEPTH,
    NODE_N_TREES,
    NODE_NUM_LAYERS,
    PATIENCE,
    POS_WEIGHT_MULT,
    RESIDUAL_PENALTY_WEIGHT,
    STAGE_B_LR,
    TENSOR_DIR_REL,
    TRAIN_NAME,
    VAL_NAME,
)
from .safety import OpenedFilesRegister, StudyBlockedError, sha256_file


def _encoder_weight_sha256(model: AttentionNodeEnsemble) -> str:
    blobs = []
    for name, param in sorted(model.named_parameters()):
        if name.startswith(("lstm.", "attention.", "linear_head.", "dropout.")):
            blobs.append(param.detach().cpu().numpy().tobytes())
    return hashlib.sha256(b"".join(blobs)).hexdigest()


def _assert_backbone_frozen(model: AttentionNodeEnsemble) -> None:
    for name, param in model.named_parameters():
        if name.startswith(("lstm.", "attention.", "linear_head.", "dropout.")):
            if param.requires_grad:
                raise RuntimeError(f"Backbone unexpectedly trainable: {name}")


def load_train_val(repo: Path, opened: OpenedFilesRegister) -> dict[str, Any]:
    train_p = opened.record(repo / TENSOR_DIR_REL / TRAIN_NAME, "train")
    val_p = opened.record(repo / TENSOR_DIR_REL / VAL_NAME, "validation")
    if sha256_file(train_p) != EXPECTED_TRAIN_SHA256:
        raise StudyBlockedError("objective2_odst_8tree_blocked_provenance", "train hash mismatch")
    if sha256_file(val_p) != EXPECTED_VAL_SHA256:
        raise StudyBlockedError("objective2_odst_8tree_blocked_provenance", "val hash mismatch")
    ztr = np.load(train_p, allow_pickle=True)
    zv = np.load(val_p, allow_pickle=True)
    Xtr = np.asarray(ztr["X"], dtype=np.float32)
    ytr = np.asarray(ztr["y"], dtype=np.int64)
    Xv = np.asarray(zv["X"], dtype=np.float32)
    yv = np.asarray(zv["y"], dtype=np.int64)
    users_v = np.asarray(zv["user"]).astype(str)
    if Xtr.shape != EXPECTED_TRAIN_SHAPE or Xv.shape != EXPECTED_VAL_SHAPE:
        raise StudyBlockedError("objective2_odst_8tree_blocked_provenance", "shape mismatch")
    if int((ytr == 1).sum()) != EXPECTED_TRAIN_POS or int((yv == 1).sum()) != EXPECTED_VAL_POS:
        raise StudyBlockedError("objective2_odst_8tree_blocked_provenance", "pos count mismatch")
    return {
        "X_train": Xtr,
        "y_train": ytr,
        "X_val": Xv,
        "y_val": yv,
        "users_val": users_v,
        "train_path": train_p,
        "val_path": val_p,
    }


def _loader(X: np.ndarray, y: np.ndarray, shuffle: bool) -> DataLoader:
    ds = TensorDataset(torch.from_numpy(X), torch.from_numpy(y.astype(np.float32)))
    return DataLoader(ds, batch_size=BATCH_SIZE, shuffle=shuffle, drop_last=False)


def train_8tree_teacher(
    *,
    repo: Path,
    seed: int,
    out_dir: Path,
    device: torch.device,
    data: dict[str, Any],
    opened: OpenedFilesRegister,
) -> dict[str, Any]:
    """Frozen Bi-LSTM–attention + train 8-tree ODST head (matched teacher)."""
    set_seed(int(seed))
    meta = ENCODERS[seed]
    enc_path = opened.record(repo / meta["ckpt_rel"], f"encoder_{seed}")
    enc_sha_file = sha256_file(enc_path)

    train_loader = _loader(data["X_train"], data["y_train"], shuffle=True)
    val_loader = _loader(data["X_val"], data["y_val"], shuffle=False)
    y_train = data["y_train"]
    y_val = data["y_val"]

    n_pos = float((y_train == 1).sum())
    n_neg = float((y_train == 0).sum())
    effective_pos_weight = (n_neg / max(n_pos, 1.0)) * POS_WEIGHT_MULT
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([effective_pos_weight], dtype=torch.float32, device=device)
    )

    model = AttentionNodeEnsemble(
        input_dim=13,
        hidden_size=int(ARCHITECTURE["hidden_size"]),
        dropout=float(ARCHITECTURE["dropout"]),
        attention_dim=int(ARCHITECTURE["attention_dim"]),
        fusion_variant="sparsemax_sigmoid_odst",
        node_num_layers=NODE_NUM_LAYERS,
        node_n_trees=NODE_N_TREES,
        node_depth=NODE_DEPTH,
        node_tree_dim=1,
        node_temperature=1.0,
    ).to(device)

    before = sha256_file(enc_path)
    load_v1_attention_linear_checkpoint(model, enc_path)
    after = sha256_file(enc_path)
    if before != after:
        raise RuntimeError("Encoder checkpoint mutated during load")
    model.apply_frozen_node_trainability()
    _assert_backbone_frozen(model)

    encoder_hash_before = _encoder_weight_sha256(model)
    if encoder_hash_before != meta["encoder_weight_sha256"]:
        raise StudyBlockedError(
            "objective2_odst_8tree_blocked_provenance",
            f"encoder weight hash mismatch seed={seed}",
        )

    x_init, _ = next(iter(train_loader))
    model.data_aware_initialize_from_batch(x_init.to(device))
    if _encoder_weight_sha256(model) != encoder_hash_before:
        raise RuntimeError("Encoder changed during data-aware init")

    optimizer, optimizer_lrs = rebuild_optimizer_frozen(model, STAGE_B_LR)

    history: list[dict[str, Any]] = []
    best_pr = -1.0
    best_epoch = 0
    patience_left = PATIENCE
    peak_mem_mb = 0.0
    t0 = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    out_dir.mkdir(parents=True, exist_ok=True)
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        model.lstm.eval()
        model.attention.eval()
        model.linear_head.eval()
        model.dropout.eval()
        total = 0.0
        n = 0
        last_parts: dict[str, float] = {}
        last_grad: dict[str, float] = {}
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits, extras = model(xb)
            if not torch.isfinite(logits).all():
                raise RuntimeError("Non-finite logits in 8-tree teacher training")
            loss, parts = v3_total_loss(
                logits,
                yb,
                extras,
                criterion,
                node_aux_weight=NODE_AUX_WEIGHT,
                linear_aux_weight=LINEAR_AUX_WEIGHT,
                residual_penalty_weight=RESIDUAL_PENALTY_WEIGHT,
                anti_collapse_weight=ANTI_COLLAPSE_WEIGHT,
            )
            if not torch.isfinite(loss):
                raise RuntimeError(f"Non-finite teacher loss: {float(loss)}")
            loss.backward()
            for name, param in model.named_parameters():
                if not param.requires_grad and param.grad is not None:
                    raise RuntimeError(f"Unexpected grad on frozen {name}")
            last_grad = gradient_norm_report(model)
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad],
                GRAD_CLIP_NORM,
            )
            optimizer.step()
            bs = int(yb.size(0))
            total += float(loss.detach()) * bs
            n += bs
            last_parts = {k: float(v) for k, v in parts.items()}

        train_loss = total / max(n, 1)
        metrics, diagnostics = evaluate_loader_diagnostics(model, val_loader, y_val, device)
        if _encoder_weight_sha256(model) != encoder_hash_before:
            raise RuntimeError(f"Encoder weights changed at teacher epoch {epoch}")

        row = {
            "seed": seed,
            "phase": "8tree_teacher",
            "epoch": epoch,
            "train_loss": train_loss,
            "validation_pr_auc": metrics["pr_auc"],
            "validation_f1": metrics["f1"],
            "validation_precision": metrics["precision"],
            "validation_recall": metrics["recall"],
            "validation_threshold": metrics["threshold"],
            "validation_fp": metrics["fp"],
            "validation_fn": metrics["fn"],
            "routing_entropy_mean": diagnostics.get("routing_entropy_mean"),
            "unused_leaves_frac": diagnostics.get("unused_leaves_frac"),
            **last_parts,
            **optimizer_lrs,
            **{f"grad_{k}": v for k, v in last_grad.items()},
        }
        history.append(row)
        print(
            f"[8tree-teacher seed={seed}] epoch {epoch:02d}: "
            f"loss={train_loss:.6f} pr_auc={metrics['pr_auc']:.6f} f1={metrics['f1']:.6f}",
            flush=True,
        )

        current_pr = float(metrics["pr_auc"])
        ckpt = {
            "model_state_dict": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
            "epoch": epoch,
            "best_epoch": best_epoch if current_pr <= best_pr else epoch,
            "best_val_pr_auc": max(best_pr, current_pr),
            "seed": int(seed),
            "fusion_variant": "sparsemax_sigmoid_odst",
            "stage": "odst_r52_8tree_frozen_encoder_teacher",
            "node_n_trees": NODE_N_TREES,
            "node_num_layers": NODE_NUM_LAYERS,
            "M_trees": NODE_NUM_LAYERS * NODE_N_TREES,
            "test_evaluated": False,
            "encoder_checkpoint": str(enc_path),
            "encoder_weight_sha256": encoder_hash_before,
            "encoder_file_sha256": enc_sha_file,
            "history": history,
        }
        torch.save(ckpt, out_dir / "latest.pt")
        if current_pr > best_pr + 1e-6:
            best_pr = current_pr
            best_epoch = epoch
            patience_left = PATIENCE
            torch.save(ckpt, out_dir / "best.pt")
        else:
            patience_left -= 1
            if patience_left <= 0:
                print(f"[8tree-teacher seed={seed}] early stop at {epoch} (best={best_epoch})", flush=True)
                break

    if device.type == "cuda":
        peak_mem_mb = float(torch.cuda.max_memory_allocated(device) / (1024**2))
    duration = time.perf_counter() - t0

    best_payload = torch.load(out_dir / "best.pt", map_location="cpu", weights_only=False)
    model.load_state_dict(best_payload["model_state_dict"])
    model.to(device)
    if _encoder_weight_sha256(model) != encoder_hash_before:
        raise RuntimeError("Encoder changed after best reload")

    probs, extras = predict_with_extras(model, val_loader, device)
    thr, _ = choose_threshold_f1(y_val, probs)
    metrics = metrics_at_threshold(y_val, probs, thr)
    _, diagnostics = evaluate_loader_diagnostics(model, val_loader, y_val, device, fixed_threshold=thr)

    best_path = out_dir / "best.pt"
    summary = {
        "seed": seed,
        "role": "8tree_teacher",
        "best_epoch": best_epoch,
        "duration_sec": duration,
        "peak_gpu_memory_mb": peak_mem_mb,
        "effective_pos_weight": effective_pos_weight,
        "node_n_trees": NODE_N_TREES,
        "M_trees": NODE_NUM_LAYERS * NODE_N_TREES,
        "validation_metrics": metrics,
        "validation_diagnostics": diagnostics,
        "checkpoint_sha256": sha256_file(best_path),
        "encoder_weight_sha256": encoder_hash_before,
        "encoder_file_sha256": enc_sha_file,
        "encoder_frozen_verified": True,
        "parameter_counts": model.component_parameter_counts(),
        "teacher_unchanged_during_student": None,
    }
    (out_dir / "teacher_summary.json").write_text(
        __import__("json").dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    np.savez_compressed(
        out_dir / "teacher_val_predictions.npz",
        y=y_val,
        proba=probs.astype(np.float32),
        threshold=np.array([thr], dtype=np.float32),
    )
    return {"summary": summary, "history": history, "best_path": best_path, "model": model}
