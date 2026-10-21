"""Train and evaluate same-information flat baselines (LR, MLP, RF, XGBoost)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset
from xgboost import XGBClassifier

from .constants import (
    LOGISTIC_REGRESSION_LOCKED,
    MLP_LOCKED,
    RANDOM_FOREST_LOCKED,
    SEEDS,
    XGBOOST_LOCKED,
)
from .metrics import choose_threshold, evaluate_validation
from .safety import assert_output_namespace, refuse_overwrite, sha256_file, write_json_atomic


def _flush(msg: str) -> None:
    print(msg, flush=True)


class ShallowMLP(nn.Module):
    def __init__(self, in_dim: int = 260, hidden: list[int] | None = None, dropout: float = 0.2) -> None:
        super().__init__()
        hidden = hidden or [128, 64]
        layers: list[nn.Module] = []
        prev = in_dim
        for h in hidden:
            layers.extend([nn.Linear(prev, h), nn.ReLU(), nn.Dropout(dropout)])
            prev = h
        layers.append(nn.Linear(prev, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def _scale_fit_transform(
    X_train: np.ndarray, X_val: np.ndarray
) -> tuple[np.ndarray, np.ndarray, StandardScaler]:
    scaler = StandardScaler()
    Xtr = scaler.fit_transform(X_train).astype(np.float32)
    Xva = scaler.transform(X_val).astype(np.float32)
    return Xtr, Xva, scaler


def _save_predictions(
    out_dir: Path,
    *,
    y_true: np.ndarray,
    y_proba: np.ndarray,
    sequence_id: np.ndarray,
    user: np.ndarray,
    threshold: float,
) -> Path:
    path = out_dir / "validation_predictions.npz"
    refuse_overwrite(path)
    np.savez_compressed(
        path,
        y_true=np.asarray(y_true, dtype=np.int32),
        y_proba=np.asarray(y_proba, dtype=np.float32),
        sequence_id=np.asarray(sequence_id),
        user=np.asarray(user),
        threshold=np.asarray([threshold], dtype=np.float64),
    )
    return path


def train_logistic_regression(
    *,
    out_dir: Path,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    sequence_id: np.ndarray,
    user: np.ndarray,
    seed: int,
) -> dict[str, Any]:
    assert_output_namespace(out_dir)
    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        _flush(f"[logreg_flat260 seed={seed}] resume: using existing summary.json")
        return json.loads(summary_path.read_text(encoding="utf-8"))
    refuse_overwrite(summary_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    Xtr, Xva, scaler = _scale_fit_transform(X_train, X_val)
    cfg = {**LOGISTIC_REGRESSION_LOCKED, "random_state": seed, "input_dim": 260}
    write_json_atomic(out_dir / "config.json", cfg)
    joblib.dump(scaler, out_dir / "scaler.joblib")

    model = SGDClassifier(
        loss=str(LOGISTIC_REGRESSION_LOCKED["loss"]),
        penalty=str(LOGISTIC_REGRESSION_LOCKED["penalty"]),
        alpha=float(LOGISTIC_REGRESSION_LOCKED["alpha"]),
        max_iter=int(LOGISTIC_REGRESSION_LOCKED["max_iter"]),
        tol=float(LOGISTIC_REGRESSION_LOCKED["tol"]),
        learning_rate=str(LOGISTIC_REGRESSION_LOCKED["learning_rate"]),
        class_weight=str(LOGISTIC_REGRESSION_LOCKED["class_weight"]),
        random_state=int(seed),
    )
    _flush(f"[logreg_flat260 seed={seed}] training ...")
    t0 = time.perf_counter()
    model.fit(Xtr, y_train)
    train_sec = time.perf_counter() - t0

    t1 = time.perf_counter()
    # decision_function -> sigmoid for probabilities
    scores = model.decision_function(Xva).astype(np.float64)
    p_val = 1.0 / (1.0 + np.exp(-scores))
    infer_sec = time.perf_counter() - t1

    thr, _ = choose_threshold(y_val, p_val)
    metrics = evaluate_validation(y_val, p_val, thr)

    model_path = out_dir / "model.joblib"
    refuse_overwrite(model_path)
    joblib.dump(model, model_path)
    _save_predictions(out_dir, y_true=y_val, y_proba=p_val, sequence_id=sequence_id, user=user, threshold=thr)

    n_params = int(model.coef_.size + (model.intercept_.size if hasattr(model, "intercept_") else 0))
    summary = {
        "model": "logistic_regression_flat260",
        "panel": "A",
        "seed": seed,
        "input_representation": "flattened_260_ordered",
        "preprocessing": "StandardScaler_train_only",
        "n_parameters": n_params,
        "model_size_bytes": int(model_path.stat().st_size),
        "model_sha256": sha256_file(model_path),
        "training_duration_sec": float(train_sec),
        "inference_duration_sec": float(infer_sec),
        "peak_gpu_memory_mb": None,
        "device": "cpu",
        "validation_metrics": metrics,
        "comparison_label": "r5.2 validation comparison",
    }
    write_json_atomic(out_dir / "summary.json", summary)
    write_json_atomic(out_dir / "threshold.json", {"selected_threshold": thr, **metrics})
    _flush(f"[logreg_flat260 seed={seed}] PR-AUC={metrics['pr_auc']:.6f} F1={metrics['f1']:.6f}")
    return summary


def train_random_forest(
    *,
    out_dir: Path,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    sequence_id: np.ndarray,
    user: np.ndarray,
    seed: int,
) -> dict[str, Any]:
    assert_output_namespace(out_dir)
    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        _flush(f"[rf_flat260 seed={seed}] resume: using existing summary.json")
        return json.loads(summary_path.read_text(encoding="utf-8"))
    refuse_overwrite(summary_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = {**RANDOM_FOREST_LOCKED, "random_state": seed, "input_dim": 260, "preprocessing": "none_unscaled"}
    write_json_atomic(out_dir / "config.json", cfg)

    model = RandomForestClassifier(
        n_estimators=int(RANDOM_FOREST_LOCKED["n_estimators"]),
        max_depth=int(RANDOM_FOREST_LOCKED["max_depth"]),
        min_samples_leaf=int(RANDOM_FOREST_LOCKED["min_samples_leaf"]),
        n_jobs=int(RANDOM_FOREST_LOCKED["n_jobs"]),
        class_weight=str(RANDOM_FOREST_LOCKED["class_weight"]),
        random_state=int(seed),
    )
    _flush(f"[rf_flat260 seed={seed}] training ...")
    t0 = time.perf_counter()
    model.fit(X_train, y_train)
    train_sec = time.perf_counter() - t0
    t1 = time.perf_counter()
    p_val = model.predict_proba(X_val)[:, 1].astype(np.float64)
    infer_sec = time.perf_counter() - t1

    thr, _ = choose_threshold(y_val, p_val)
    metrics = evaluate_validation(y_val, p_val, thr)
    model_path = out_dir / "model.joblib"
    refuse_overwrite(model_path)
    joblib.dump(model, model_path)
    _save_predictions(out_dir, y_true=y_val, y_proba=p_val, sequence_id=sequence_id, user=user, threshold=thr)

    summary = {
        "model": "random_forest_flat260",
        "panel": "A",
        "seed": seed,
        "input_representation": "flattened_260_ordered",
        "preprocessing": "none_unscaled",
        "n_parameters": None,
        "n_estimators": int(RANDOM_FOREST_LOCKED["n_estimators"]),
        "model_size_bytes": int(model_path.stat().st_size),
        "model_sha256": sha256_file(model_path),
        "training_duration_sec": float(train_sec),
        "inference_duration_sec": float(infer_sec),
        "peak_gpu_memory_mb": None,
        "device": "cpu",
        "validation_metrics": metrics,
        "comparison_label": "r5.2 validation comparison",
    }
    write_json_atomic(out_dir / "summary.json", summary)
    write_json_atomic(out_dir / "threshold.json", {"selected_threshold": thr, **metrics})
    _flush(f"[rf_flat260 seed={seed}] PR-AUC={metrics['pr_auc']:.6f} F1={metrics['f1']:.6f}")
    return summary


def train_xgboost(
    *,
    out_dir: Path,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    sequence_id: np.ndarray,
    user: np.ndarray,
    seed: int,
    scale_pos_weight: float,
) -> dict[str, Any]:
    assert_output_namespace(out_dir)
    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        _flush(f"[xgb_flat260 seed={seed}] resume: using existing summary.json")
        return json.loads(summary_path.read_text(encoding="utf-8"))
    refuse_overwrite(summary_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = {
        **XGBOOST_LOCKED,
        "random_state": seed,
        "scale_pos_weight": scale_pos_weight,
        "input_dim": 260,
        "preprocessing": "none_unscaled",
    }
    write_json_atomic(out_dir / "config.json", cfg)

    model = XGBClassifier(
        n_estimators=int(XGBOOST_LOCKED["n_estimators"]),
        max_depth=int(XGBOOST_LOCKED["max_depth"]),
        learning_rate=float(XGBOOST_LOCKED["learning_rate"]),
        subsample=float(XGBOOST_LOCKED["subsample"]),
        colsample_bytree=float(XGBOOST_LOCKED["colsample_bytree"]),
        reg_lambda=float(XGBOOST_LOCKED["reg_lambda"]),
        objective=str(XGBOOST_LOCKED["objective"]),
        eval_metric=str(XGBOOST_LOCKED["eval_metric"]),
        scale_pos_weight=float(scale_pos_weight),
        n_jobs=int(XGBOOST_LOCKED["n_jobs"]),
        random_state=int(seed),
        tree_method=str(XGBOOST_LOCKED["tree_method"]),
    )
    _flush(f"[xgb_flat260 seed={seed}] training ...")
    t0 = time.perf_counter()
    model.fit(X_train, y_train)
    train_sec = time.perf_counter() - t0
    t1 = time.perf_counter()
    p_val = model.predict_proba(X_val)[:, 1].astype(np.float64)
    infer_sec = time.perf_counter() - t1

    thr, _ = choose_threshold(y_val, p_val)
    metrics = evaluate_validation(y_val, p_val, thr)
    model_path = out_dir / "model.json"
    refuse_overwrite(model_path)
    model.save_model(model_path)
    _save_predictions(out_dir, y_true=y_val, y_proba=p_val, sequence_id=sequence_id, user=user, threshold=thr)

    summary = {
        "model": "xgboost_flat260",
        "panel": "A",
        "seed": seed,
        "input_representation": "flattened_260_ordered",
        "preprocessing": "none_unscaled",
        "n_parameters": None,
        "n_estimators": int(XGBOOST_LOCKED["n_estimators"]),
        "model_size_bytes": int(model_path.stat().st_size),
        "model_sha256": sha256_file(model_path),
        "training_duration_sec": float(train_sec),
        "inference_duration_sec": float(infer_sec),
        "peak_gpu_memory_mb": None,
        "device": "cpu",
        "scale_pos_weight": float(scale_pos_weight),
        "validation_metrics": metrics,
        "comparison_label": "r5.2 validation comparison",
    }
    write_json_atomic(out_dir / "summary.json", summary)
    write_json_atomic(out_dir / "threshold.json", {"selected_threshold": thr, **metrics})
    _flush(f"[xgb_flat260 seed={seed}] PR-AUC={metrics['pr_auc']:.6f} F1={metrics['f1']:.6f}")
    return summary


def _count_params(model: nn.Module) -> int:
    return int(sum(p.numel() for p in model.parameters()))


def train_mlp(
    *,
    out_dir: Path,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    sequence_id: np.ndarray,
    user: np.ndarray,
    seed: int,
    device: torch.device,
) -> dict[str, Any]:
    assert_output_namespace(out_dir)
    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        _flush(f"[mlp_flat260 seed={seed}] resume: using existing summary.json")
        return json.loads(summary_path.read_text(encoding="utf-8"))
    refuse_overwrite(summary_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(seed)
    np.random.seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.cuda.reset_peak_memory_stats(device)

    Xtr, Xva, scaler = _scale_fit_transform(X_train, X_val)
    joblib.dump(scaler, out_dir / "scaler.joblib")

    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    pos_weight = float((n_neg / max(n_pos, 1)) * float(MLP_LOCKED["pos_weight_multiplier"]))

    cfg = {**MLP_LOCKED, "seed": seed, "pos_weight": pos_weight, "device": str(device)}
    write_json_atomic(out_dir / "config.json", cfg)

    model = ShallowMLP(
        in_dim=Xtr.shape[1],
        hidden=list(MLP_LOCKED["hidden_layers"]),
        dropout=float(MLP_LOCKED["dropout"]),
    ).to(device)
    opt = torch.optim.Adam(
        model.parameters(),
        lr=float(MLP_LOCKED["learning_rate"]),
        weight_decay=float(MLP_LOCKED["weight_decay"]),
    )
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight], device=device))

    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(Xtr), torch.from_numpy(y_train.astype(np.float32))),
        batch_size=int(MLP_LOCKED["batch_size"]),
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
    )
    val_x = torch.from_numpy(Xva).to(device)

    best_pr = -1.0
    best_state: dict[str, Any] | None = None
    best_epoch = -1
    patience_left = int(MLP_LOCKED["patience"])
    t0 = time.perf_counter()

    for epoch in range(1, int(MLP_LOCKED["max_epochs"]) + 1):
        model.train()
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad(set_to_none=True)
            logits = model(xb)
            loss = loss_fn(logits, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(MLP_LOCKED["grad_clip_norm"]))
            opt.step()

        model.eval()
        with torch.no_grad():
            logits_val = []
            for i in range(0, len(Xva), int(MLP_LOCKED["batch_size"])):
                logits_val.append(model(val_x[i : i + int(MLP_LOCKED["batch_size"])]).detach().cpu())
            logits_cat = torch.cat(logits_val).numpy()
            p_val = 1.0 / (1.0 + np.exp(-logits_cat))
        from sklearn.metrics import average_precision_score

        pr = float(average_precision_score(y_val, p_val))
        _flush(f"[mlp_flat260 seed={seed}] epoch={epoch} val_pr_auc={pr:.6f}")
        if pr > best_pr:
            best_pr = pr
            best_epoch = epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            patience_left = int(MLP_LOCKED["patience"])
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    train_sec = time.perf_counter() - t0
    assert best_state is not None
    model.load_state_dict(best_state)
    model.eval()
    t1 = time.perf_counter()
    with torch.no_grad():
        logits_val = []
        for i in range(0, len(Xva), int(MLP_LOCKED["batch_size"])):
            logits_val.append(model(val_x[i : i + int(MLP_LOCKED["batch_size"])]).detach().cpu())
        logits_cat = torch.cat(logits_val).numpy()
        p_val = 1.0 / (1.0 + np.exp(-logits_cat))
    infer_sec = time.perf_counter() - t1

    thr, _ = choose_threshold(y_val, p_val)
    metrics = evaluate_validation(y_val, p_val, thr)

    ckpt_path = out_dir / "model.pt"
    refuse_overwrite(ckpt_path)
    torch.save(
        {
            "state_dict": best_state,
            "seed": seed,
            "best_epoch": best_epoch,
            "config": cfg,
            "test_evaluated": False,
            "r52_test_accessed": False,
        },
        ckpt_path,
    )
    _save_predictions(out_dir, y_true=y_val, y_proba=p_val, sequence_id=sequence_id, user=user, threshold=thr)

    peak_gpu = None
    if device.type == "cuda":
        peak_gpu = float(torch.cuda.max_memory_allocated(device) / (1024 * 1024))

    summary = {
        "model": "mlp_flat260",
        "panel": "A",
        "seed": seed,
        "input_representation": "flattened_260_ordered",
        "preprocessing": "StandardScaler_train_only",
        "n_parameters": _count_params(model),
        "best_epoch": best_epoch,
        "model_size_bytes": int(ckpt_path.stat().st_size),
        "model_sha256": sha256_file(ckpt_path),
        "training_duration_sec": float(train_sec),
        "inference_duration_sec": float(infer_sec),
        "peak_gpu_memory_mb": peak_gpu,
        "device": str(device),
        "validation_metrics": metrics,
        "comparison_label": "r5.2 validation comparison",
    }
    write_json_atomic(out_dir / "summary.json", summary)
    write_json_atomic(out_dir / "threshold.json", {"selected_threshold": thr, **metrics})
    return summary


def run_flat_baselines(
    *,
    out_root: Path,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    sequence_id: np.ndarray,
    user: np.ndarray,
    device: torch.device,
    seeds: tuple[int, ...] = SEEDS,
) -> list[dict[str, Any]]:
    scale_pos_weight = float((len(y_train) - y_train.sum()) / max(int(y_train.sum()), 1))
    summaries: list[dict[str, Any]] = []

    # Logistic regression: run once with seed 42 (solver seed) and mirror seed column for bookkeeping.
    # Spec: LR may be deterministic but record solver seed; still use three seeds where supported.
    for seed in seeds:
        summaries.append(
            train_logistic_regression(
                out_dir=out_root / f"logistic_regression_seed{seed}",
                X_train=X_train,
                y_train=y_train,
                X_val=X_val,
                y_val=y_val,
                sequence_id=sequence_id,
                user=user,
                seed=seed,
            )
        )

    for seed in seeds:
        summaries.append(
            train_mlp(
                out_dir=out_root / f"mlp_seed{seed}",
                X_train=X_train,
                y_train=y_train,
                X_val=X_val,
                y_val=y_val,
                sequence_id=sequence_id,
                user=user,
                seed=seed,
                device=device,
            )
        )

    for seed in seeds:
        summaries.append(
            train_random_forest(
                out_dir=out_root / f"random_forest_seed{seed}",
                X_train=X_train,
                y_train=y_train,
                X_val=X_val,
                y_val=y_val,
                sequence_id=sequence_id,
                user=user,
                seed=seed,
            )
        )

    for seed in seeds:
        summaries.append(
            train_xgboost(
                out_dir=out_root / f"xgboost_seed{seed}",
                X_train=X_train,
                y_train=y_train,
                X_val=X_val,
                y_val=y_val,
                sequence_id=sequence_id,
                user=user,
                seed=seed,
                scale_pos_weight=scale_pos_weight,
            )
        )
    return summaries
