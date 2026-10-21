#!/usr/bin/env python3
"""
Fragmented hybrid baseline: frozen pretrained Bi-LSTM+attention encoder + tree classifiers.

Two-stage, leakage-controlled baseline for Objective 2. The encoder is loaded from
the validation-selected attention-linear pretraining checkpoint per seed. Fixed-length
temporal representations are extracted without joint backpropagation. Random Forest
and XGBoost are trained separately; hyperparameters and thresholds use validation only.

Test split representations may be materialised but are not used for training or tuning
unless --evaluate-test is supplied.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch.utils.data import DataLoader, Dataset, Subset
from xgboost import XGBClassifier

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from models.sequence_ensemble import SequenceEnsembleModel  # noqa: E402

PRETRAIN_CHECKPOINTS = {
    42: "outputs/baselines/sequence_ensemble/stage11_A_attn_linear/best.pt",
    52: "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed52/best.pt",
    62: "outputs/baselines/sequence_ensemble/pretrain_attn_linear_seed62/best.pt",
}

SEQ_LEN = 20
INPUT_DIM = 13
DEFAULT_HIDDEN = 64
DEFAULT_DROPOUT = 0.2
DEFAULT_ATTENTION_DIM = 64


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve(root: Path, rel: str | Path) -> Path:
    path = Path(rel)
    return path if path.is_absolute() else (root / path).resolve()


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def choose_threshold_f1(y_true: np.ndarray, probs: np.ndarray) -> tuple[float, float]:
    candidates = set(np.linspace(0.01, 0.99, 99).tolist())
    candidates.update(float(q) for q in np.quantile(probs, np.linspace(0.01, 0.99, 50)))
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(candidates):
        f1 = f1_score(y_true, (probs >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1 = float(f1)
            best_t = float(t)
    return best_t, best_f1


def metrics_at_threshold(y_true: np.ndarray, probs: np.ndarray, threshold: float) -> dict:
    y_pred = (probs >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) else 0.0
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, probs)),
        "roc_auc": float(roc_auc_score(y_true, probs)),
        "fpr": fpr,
        "fnr": fnr,
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "alert_count": int(tp + fp),
    }


def predict_proba_positive(model, x: np.ndarray) -> np.ndarray:
    proba = model.predict_proba(x)
    if proba.shape[1] == 1:
        return proba[:, 0]
    classes = list(getattr(model, "classes_", [0, 1]))
    return proba[:, classes.index(1)] if 1 in classes else proba[:, -1]


class NpzSequenceDataset(Dataset):
    def __init__(self, npz_path: Path, mmap: bool = True, materialize: bool = False) -> None:
        z = np.load(npz_path, allow_pickle=True, mmap_mode="r" if mmap else None)
        x = z["X"]
        y = z["y"]
        if materialize:
            self.X = np.array(x, dtype=np.float32, copy=True)
            self.y = np.array(y, copy=True)
        else:
            self.X = x
            self.y = y
        self.sequence_id = z["sequence_id"] if "sequence_id" in z.files else None
        self.user = z["user"] if "user" in z.files else None

    def __len__(self) -> int:
        return int(self.X.shape[0])

    def __getitem__(self, idx: int):
        x = np.asarray(self.X[idx], dtype=np.float32)
        y = np.float32(self.y[idx])
        return torch.from_numpy(x.copy() if not x.flags.writeable else x), torch.tensor(
            y, dtype=torch.float32
        )


def stratified_smoke_indices(y: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    n_pos = min(len(pos_idx), max(1, n // 10))
    n_neg = min(len(neg_idx), max(0, n - n_pos))
    idx = np.concatenate(
        [
            rng.choice(pos_idx, size=n_pos, replace=False),
            rng.choice(neg_idx, size=n_neg, replace=False),
        ]
    )
    rng.shuffle(idx)
    return idx


def load_pretrained_encoder(
    checkpoint_path: Path,
    device: torch.device,
    hidden_size: int = DEFAULT_HIDDEN,
    dropout: float = DEFAULT_DROPOUT,
    attention_dim: int = DEFAULT_ATTENTION_DIM,
) -> tuple[SequenceEnsembleModel, dict]:
    """Load attention-linear pretrain checkpoint; encoder+attention used for representations."""
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    cfg = payload.get("config", {})
    model = SequenceEnsembleModel(
        input_dim=INPUT_DIM,
        hidden_size=int(cfg.get("hidden_size", hidden_size)),
        dropout=float(cfg.get("dropout", dropout)),
        attention_dim=int(cfg.get("attention_dim", attention_dim)),
        classification_head="linear",
        temporal_aggregation="attention",
        n_trees=5,
        tree_depth=4,
    )
    model.load_state_dict(payload["model_state_dict"])
    model.to(device)
    model.eval()
    for p in model.lstm.parameters():
        p.requires_grad = False
    for p in model.attention.parameters():
        p.requires_grad = False
    report = {
        "checkpoint": str(checkpoint_path.resolve()),
        "encoder_frozen": True,
        "representation_dim": model.encoder_dim,
        "classification_head_ignored": "linear",
        "best_epoch_pretrain": payload.get("best_epoch") or payload.get("epoch"),
        "pretrain_val_pr_auc": payload.get("best_val_pr_auc"),
    }
    thr_path = checkpoint_path.parent / "threshold.json"
    if thr_path.exists():
        thr = json.loads(thr_path.read_text(encoding="utf-8"))
        report["pretrain_selected_threshold"] = thr.get("selected_threshold")
        report["pretrain_validation_pr_auc"] = thr.get("validation_metrics", {}).get("pr_auc")
    return model, report


@torch.no_grad()
def extract_representations(
    model: SequenceEnsembleModel,
    loader: DataLoader,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract attention-aggregated vectors z (B, encoder_dim)."""
    zs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for xb, yb in loader:
        xb = xb.to(device)
        _, extras = model(xb)
        z = extras["aggregated"].detach().cpu().numpy()
        if not np.isfinite(z).all():
            raise ValueError("Non-finite representation vectors detected")
        zs.append(z)
        ys.append(yb.numpy())
    return np.concatenate(zs, axis=0), np.concatenate(ys, axis=0).astype(np.int8)


def select_rf_on_validation(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    seed: int,
    smoke: bool,
) -> tuple[RandomForestClassifier, dict]:
    depths = [10, 20] if smoke else [10, 20, 30]
    n_est = 20 if smoke else 200
    best_model = None
    best_pr = -1.0
    best_cfg: dict = {}
    for depth in depths:
        clf = RandomForestClassifier(
            n_estimators=n_est,
            max_depth=depth,
            min_samples_leaf=2,
            n_jobs=-1,
            class_weight="balanced_subsample",
            random_state=seed,
        )
        clf.fit(x_train, y_train)
        p_val = predict_proba_positive(clf, x_val)
        pr = float(average_precision_score(y_val, p_val))
        if pr > best_pr:
            best_pr = pr
            best_model = clf
            best_cfg = {"max_depth": depth, "n_estimators": n_est, "validation_pr_auc": pr}
    assert best_model is not None
    return best_model, best_cfg


def select_xgb_on_validation(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    seed: int,
    smoke: bool,
) -> tuple[XGBClassifier, dict]:
    lrs = [0.1] if smoke else [0.05, 0.1]
    n_est = 20 if smoke else 300
    n_pos = float((y_train == 1).sum())
    n_neg = float((y_train == 0).sum())
    scale_pos_weight = n_neg / max(n_pos, 1.0)
    best_model = None
    best_pr = -1.0
    best_cfg: dict = {}
    for lr in lrs:
        clf = XGBClassifier(
            n_estimators=n_est,
            max_depth=6,
            learning_rate=lr,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            objective="binary:logistic",
            eval_metric="aucpr",
            scale_pos_weight=scale_pos_weight,
            n_jobs=-1,
            random_state=seed,
            tree_method="hist",
        )
        clf.fit(x_train, y_train)
        p_val = predict_proba_positive(clf, x_val)
        pr = float(average_precision_score(y_val, p_val))
        if pr > best_pr:
            best_pr = pr
            best_model = clf
            best_cfg = {
                "learning_rate": lr,
                "n_estimators": n_est,
                "max_depth": 6,
                "scale_pos_weight": scale_pos_weight,
                "validation_pr_auc": pr,
            }
    assert best_model is not None
    return best_model, best_cfg


def save_predictions_parquet(
    path: Path,
    split: str,
    y: np.ndarray,
    probs: np.ndarray,
    thr: float,
    ds: NpzSequenceDataset,
    indices: np.ndarray | None,
) -> None:
    idx = np.arange(len(y)) if indices is None else indices
    frame = {
        "split": split,
        "y_true": y.astype(np.int8),
        "y_prob": probs.astype(np.float32),
        "y_pred_selected": (probs >= thr).astype(np.int8),
    }
    if ds.sequence_id is not None:
        frame["sequence_id"] = np.asarray(ds.sequence_id)[idx].astype(str)
    if ds.user is not None:
        frame["user"] = np.asarray(ds.user)[idx].astype(str)
    pd.DataFrame(frame).to_parquet(path, index=False)


def run_tree_classifier(
    name: str,
    model,
    model_cfg: dict,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    x_test: np.ndarray | None,
    y_test: np.ndarray | None,
    out_dir: Path,
    val_ds: NpzSequenceDataset,
    val_idx: np.ndarray | None,
    test_ds: NpzSequenceDataset | None,
    evaluate_test: bool,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    p_val = predict_proba_positive(model, x_val)
    thr, thr_f1 = choose_threshold_f1(y_val, p_val)
    val_metrics = metrics_at_threshold(y_val, p_val, thr)

    if hasattr(model, "save_model"):
        model.save_model(str(out_dir / "model.json"))
    else:
        joblib.dump(model, out_dir / "model.joblib")

    config = {
        "classifier": name,
        "model_hyperparameters": model_cfg,
        "selected_threshold": thr,
        "threshold_selection": "maximum_validation_f1",
        "validation_f1_at_selected": thr_f1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (out_dir / "threshold.json").write_text(
        json.dumps(
            {
                "selected_threshold": thr,
                "validation_metrics": val_metrics,
                "test_not_used_for_selection": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    pd.DataFrame([{"split": "validation", **val_metrics}]).to_csv(
        out_dir / "validation_metrics.csv", index=False
    )
    save_predictions_parquet(
        out_dir / "validation_predictions.parquet",
        "validation",
        y_val,
        p_val,
        thr,
        val_ds,
        val_idx,
    )

    result = {"validation": val_metrics, "threshold": thr, "config": config}
    if evaluate_test and x_test is not None and y_test is not None:
        p_test = predict_proba_positive(model, x_test)
        test_metrics = metrics_at_threshold(y_test, p_test, thr)
        pd.DataFrame([{"split": "test", **test_metrics}]).to_csv(
            out_dir / "test_metrics.csv", index=False
        )
        if test_ds is not None:
            save_predictions_parquet(
                out_dir / "test_predictions.parquet",
                "test",
                y_test,
                p_test,
                thr,
                test_ds,
                None,
            )
        result["test"] = test_metrics
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fragmented hybrid baseline (frozen encoder + trees).")
    p.add_argument("--tensor-dir", default="data/processed/tensors")
    p.add_argument("--output-dir", default=None, help="Default: outputs/objective2/fragmented_hybrid_seed{seed}")
    p.add_argument("--seed", type=int, choices=[42, 52, 62], default=42)
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--batch-size", type=int, default=1024)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--smoke-n", type=int, default=2000)
    p.add_argument(
        "--evaluate-test",
        action="store_true",
        help="Apply validation-fixed threshold to test (disabled by default).",
    )
    p.add_argument(
        "--encoder-checkpoint",
        default=None,
        help="Override pretrain checkpoint path (default: seed-mapped pretrain).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = repo_root()
    set_seed(args.seed)

    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    elif args.device == "cuda":
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    out_dir = resolve(root, args.output_dir) if args.output_dir else (
        root / "outputs" / "objective2" / f"fragmented_hybrid_seed{args.seed}"
    )
    if args.smoke:
        out_dir = out_dir / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    ckpt_rel = args.encoder_checkpoint or PRETRAIN_CHECKPOINTS[args.seed]
    ckpt_path = resolve(root, ckpt_rel)
    if not ckpt_path.exists():
        raise FileNotFoundError(f"Encoder checkpoint not found: {ckpt_path}")

    tensor_dir = resolve(root, args.tensor_dir)
    datasets = {
        "train": NpzSequenceDataset(tensor_dir / "r42_T20_s1_train.npz", materialize=args.smoke),
        "validation": NpzSequenceDataset(tensor_dir / "r42_T20_s1_validation.npz"),
        "test": NpzSequenceDataset(tensor_dir / "r42_T20_s1_test.npz"),
    }

    train_idx = val_idx = None
    if args.smoke:
        rng = np.random.default_rng(args.seed)
        y_tr = np.asarray(datasets["train"].y)
        y_va = np.asarray(datasets["validation"].y)
        train_idx = stratified_smoke_indices(y_tr, args.smoke_n, rng)
        val_idx = stratified_smoke_indices(y_va, min(args.smoke_n // 2, len(y_va)), rng)
        if args.evaluate_test:
            print("NOTE: --evaluate-test ignored during smoke mode.")

    print("=" * 72)
    print(f"Fragmented hybrid baseline seed={args.seed}")
    print("=" * 72)
    print(f"Encoder checkpoint: {ckpt_path}")
    print(f"Output: {out_dir}")
    print(f"Evaluate test: {bool(args.evaluate_test) and not args.smoke}")

    encoder, enc_report = load_pretrained_encoder(ckpt_path, device)
    (out_dir / "encoder_load_report.json").write_text(
        json.dumps(enc_report, indent=2), encoding="utf-8"
    )

    repr_dir = out_dir / "representations"
    repr_dir.mkdir(parents=True, exist_ok=True)

    splits_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for split, ds in datasets.items():
        idx = None
        if split == "train":
            idx = train_idx
        elif split == "validation":
            idx = val_idx
        loader = DataLoader(
            Subset(ds, idx.tolist()) if idx is not None else ds,
            batch_size=args.batch_size,
            shuffle=False,
            num_workers=0,
        )
        z, y = extract_representations(encoder, loader, device)
        splits_data[split] = (z, y)
        np.save(repr_dir / f"{split}_repr.npy", z)
        np.save(repr_dir / f"{split}_y.npy", y)
        print(f"  {split}: repr shape={z.shape}, finite={np.isfinite(z).all()}")

    x_train, y_train = splits_data["train"]
    x_val, y_val = splits_data["validation"]
    x_test, y_test = splits_data["test"]

    run_config = {
        "baseline_type": "fragmented_hybrid",
        "seed": args.seed,
        "encoder_checkpoint": str(ckpt_path),
        "representation_dim": int(enc_report["representation_dim"]),
        "encoder_frozen": True,
        "joint_backpropagation": False,
        "classifiers": ["random_forest", "xgboost"],
        "hyperparameter_selection": "validation_pr_auc",
        "threshold_selection": "maximum_validation_f1",
        "test_used_for_training": False,
        "test_evaluated": bool(args.evaluate_test) and not args.smoke,
        "smoke": bool(args.smoke),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (out_dir / "config.json").write_text(json.dumps(run_config, indent=2), encoding="utf-8")

    t0 = time.perf_counter()
    rf_model, rf_cfg = select_rf_on_validation(
        x_train, y_train, x_val, y_val, args.seed, args.smoke
    )
    rf_result = run_tree_classifier(
        "random_forest",
        rf_model,
        rf_cfg,
        x_train,
        y_train,
        x_val,
        y_val,
        x_test if args.evaluate_test and not args.smoke else None,
        y_test if args.evaluate_test and not args.smoke else None,
        out_dir / "random_forest",
        datasets["validation"],
        val_idx,
        datasets["test"],
        args.evaluate_test and not args.smoke,
    )

    xgb_model, xgb_cfg = select_xgb_on_validation(
        x_train, y_train, x_val, y_val, args.seed, args.smoke
    )
    xgb_result = run_tree_classifier(
        "xgboost",
        xgb_model,
        xgb_cfg,
        x_train,
        y_train,
        x_val,
        y_val,
        x_test if args.evaluate_test and not args.smoke else None,
        y_test if args.evaluate_test and not args.smoke else None,
        out_dir / "xgboost",
        datasets["validation"],
        val_idx,
        datasets["test"],
        args.evaluate_test and not args.smoke,
    )
    elapsed = time.perf_counter() - t0

    summary = {
        "seed": args.seed,
        "random_forest": rf_result["validation"],
        "xgboost": xgb_result["validation"],
        "elapsed_sec": elapsed,
    }
    (out_dir / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\nValidation results (threshold fixed before any test evaluation):")
    for name, res in (("Random Forest", rf_result), ("XGBoost", xgb_result)):
        m = res["validation"]
        print(
            f"  {name}: PR-AUC={m['pr_auc']:.4f} F1={m['f1']:.4f} "
            f"P={m['precision']:.4f} R={m['recall']:.4f} FP={m['fp']} FN={m['fn']} thr={res['threshold']:.4f}"
        )
    print(f"\nOutputs: {out_dir}")
    if args.smoke:
        print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
