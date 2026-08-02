"""Train locked XGBoost / Random Forest on r5.2 validation protocol."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

from . import OUTPUT_NAMESPACE, RANDOM_FOREST_LOCKED, SEEDS, XGBOOST_LOCKED
from .data import aggregate_common13_windows
from .metrics import choose_threshold, evaluate_validation
from .safety import (
    ProtocolAccessError,
    assert_output_namespace,
    refuse_overwrite,
    sha256_file,
    write_json_atomic,
)


def _flush(msg: str) -> None:
    print(msg, flush=True)


def _run_one(
    *,
    model_name: str,
    seed: int,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    feature_names: list[str],
    out_dir: Path,
    scale_pos_weight: float,
) -> dict[str, Any]:
    refuse_overwrite(out_dir / "summary.json")
    out_dir.mkdir(parents=True, exist_ok=True)

    if model_name == "xgboost":
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
        model_path = out_dir / "model.json"
    elif model_name == "random_forest":
        model = RandomForestClassifier(
            n_estimators=int(RANDOM_FOREST_LOCKED["n_estimators"]),
            max_depth=int(RANDOM_FOREST_LOCKED["max_depth"]),
            min_samples_leaf=int(RANDOM_FOREST_LOCKED["min_samples_leaf"]),
            n_jobs=int(RANDOM_FOREST_LOCKED["n_jobs"]),
            class_weight=str(RANDOM_FOREST_LOCKED["class_weight"]),
            random_state=int(seed),
        )
        model_path = out_dir / "model.joblib"
    else:
        raise ProtocolAccessError(f"Unknown model {model_name}")

    cfg = {
        "model": model_name,
        "seed": seed,
        "dataset": "CERT r5.2",
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "hyperparameters": (
            {**XGBOOST_LOCKED, "scale_pos_weight": scale_pos_weight, "random_state": seed}
            if model_name == "xgboost"
            else {**RANDOM_FOREST_LOCKED, "random_state": seed}
        ),
        "threshold_procedure": "max_validation_f1 (locked r4.2)",
        "test_evaluated": False,
        "r52_test_accessed": False,
        "r62_accessed": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json_atomic(out_dir / "config.json", cfg)

    _flush(f"[{model_name} seed={seed}] training on {X_train.shape[0]:,} x {X_train.shape[1]} ...")
    t0 = time.perf_counter()
    model.fit(X_train, y_train)
    train_sec = time.perf_counter() - t0
    _flush(f"[{model_name} seed={seed}] train done in {train_sec:.1f}s")

    t1 = time.perf_counter()
    p_val = model.predict_proba(X_val)[:, 1].astype(np.float64)
    infer_sec = time.perf_counter() - t1
    _flush(f"[{model_name} seed={seed}] validation inference in {infer_sec:.1f}s")

    thr, thr_f1 = choose_threshold(y_val, p_val)
    metrics = evaluate_validation(y_val, p_val, thr)
    _flush(
        f"[{model_name} seed={seed}] PR-AUC={metrics['pr_auc']:.6f} "
        f"F1={metrics['f1']:.6f} thr={metrics['threshold']:.6f} "
        f"FP={metrics['fp']} FN={metrics['fn']} alerts={metrics['n_alerts']}"
    )

    refuse_overwrite(model_path)
    if model_name == "xgboost":
        model.save_model(model_path)
    else:
        joblib.dump(model, model_path)
    model_hash = sha256_file(model_path)

    probs_path = out_dir / "validation_probabilities.npz"
    refuse_overwrite(probs_path)
    np.savez_compressed(
        probs_path,
        y_true=np.asarray(y_val, dtype=np.int32),
        y_proba=p_val.astype(np.float32),
        threshold=np.asarray([thr], dtype=np.float64),
    )

    # Feature importance
    if model_name == "xgboost":
        imp = np.asarray(model.feature_importances_, dtype=np.float64)
        importance_type = "xgboost_feature_importances_gain_default"
    else:
        imp = np.asarray(model.feature_importances_, dtype=np.float64)
        importance_type = "sklearn_gini_impurity_decrease"
    imp_df = pd.DataFrame(
        {
            "feature_index": np.arange(len(feature_names), dtype=int),
            "feature_name": feature_names,
            "importance": imp,
        }
    ).sort_values("importance", ascending=False)
    imp_path = out_dir / "feature_importance.csv"
    refuse_overwrite(imp_path)
    imp_df.to_csv(imp_path, index=False)

    threshold_payload = {
        "selection_criterion": "max_validation_f1",
        "selected_threshold": thr,
        "validation_f1_at_selected_threshold": thr_f1,
        **{k: metrics[k] for k in ("precision", "recall", "f1", "tp", "tn", "fp", "fn", "fpr", "fnr", "n_alerts")},
    }
    write_json_atomic(out_dir / "threshold.json", threshold_payload)
    write_json_atomic(
        out_dir / "confusion_matrix.json",
        {k: metrics[k] for k in ("tp", "tn", "fp", "fn", "fpr", "fnr", "n_alerts")},
    )
    write_json_atomic(
        out_dir / "calibration.json",
        {"brier_score": metrics["brier_score"], "log_loss": metrics["log_loss"]},
    )
    write_json_atomic(out_dir / "model_hash.json", {"model_path": model_path.name, "sha256": model_hash})

    summary = {
        "model": model_name,
        "seed": seed,
        "dataset": "CERT r5.2",
        "n_train": int(X_train.shape[0]),
        "n_validation": int(X_val.shape[0]),
        "n_features": int(X_train.shape[1]),
        "scale_pos_weight": float(scale_pos_weight) if model_name == "xgboost" else None,
        "training_duration_sec": float(train_sec),
        "validation_inference_duration_sec": float(infer_sec),
        "duration_sec": float(train_sec),
        "validation_metrics": metrics,
        "feature_importance_type": importance_type,
        "model_hash": model_hash,
        "model_path": model_path.name,
        "test_evaluated": False,
        "r52_test_accessed": False,
        "r62_accessed": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json_atomic(out_dir / "summary.json", summary)
    return summary


def run_all_seeds(
    root: Path,
    datasets: dict[str, Any],
) -> list[dict[str, Any]]:
    out_root = assert_output_namespace(root / OUTPUT_NAMESPACE, root)
    _flush("Aggregating train/validation windows to locked 40-feature representation ...")
    X_train_seq = datasets["train"]["X"]
    y_train = np.asarray(datasets["train"]["y"]).astype(np.int32).ravel()
    X_val_seq = datasets["validation"]["X"]
    y_val = np.asarray(datasets["validation"]["y"]).astype(np.int32).ravel()

    X_train, feature_names = aggregate_common13_windows(np.asarray(X_train_seq))
    X_val, feature_names_v = aggregate_common13_windows(np.asarray(X_val_seq))
    if feature_names != feature_names_v:
        raise ProtocolAccessError("Train/val feature name mismatch after aggregation")

    n_pos = int((y_train == 1).sum())
    n_neg = int((y_train == 0).sum())
    scale_pos_weight = (n_neg / n_pos) if n_pos else 1.0
    _flush(f"Train class counts: neg={n_neg:,}, pos={n_pos:,}")
    _flush(f"XGBoost scale_pos_weight (train-only): {scale_pos_weight:.6f}")

    # Persist aggregated matrices once for audit (not test).
    agg_dir = out_root / "aggregated_features"
    agg_dir.mkdir(parents=True, exist_ok=True)
    for split, X, y in (("train", X_train, y_train), ("validation", X_val, y_val)):
        path = agg_dir / f"r52_T20_s1_{split}_agg40.npz"
        if not path.exists():
            np.savez_compressed(path, X=X, y=y, feature_names=np.asarray(feature_names))
            _flush(f"Wrote {path.name} sha256={sha256_file(path)}")

    feat_json = out_root / "feature_names.json"
    if not feat_json.exists():
        write_json_atomic(
            feat_json,
            {"n_features": len(feature_names), "feature_names": feature_names},
        )

    summaries: list[dict[str, Any]] = []
    for model_name, folder_prefix in (
        ("xgboost", "xgboost_seed"),
        ("random_forest", "random_forest_seed"),
    ):
        for seed in SEEDS:
            out_dir = out_root / f"{folder_prefix}{seed}"
            if (out_dir / "summary.json").exists():
                _flush(f"Skip existing {out_dir.name}")
                summaries.append(json.loads((out_dir / "summary.json").read_text(encoding="utf-8")))
                continue
            summaries.append(
                _run_one(
                    model_name=model_name,
                    seed=seed,
                    X_train=X_train,
                    y_train=y_train,
                    X_val=X_val,
                    y_val=y_val,
                    feature_names=feature_names,
                    out_dir=out_dir,
                    scale_pos_weight=scale_pos_weight,
                )
            )
    return summaries
