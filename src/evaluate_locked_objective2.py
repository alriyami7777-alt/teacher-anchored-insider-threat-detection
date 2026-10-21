#!/usr/bin/env python3
"""
Safe locked Objective 2 test evaluator.

Loads paths, thresholds and configurations only from
outputs/objective2/objective2_final_locked_manifest.json.
Never retrains, never retunes thresholds, never selects thresholds on test.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset
from xgboost import XGBClassifier

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from models.sequence_ensemble import SequenceEnsembleModel  # noqa: E402
from objective2_locked_common import (  # noqa: E402
    DISPLAY_NAMES,
    default_output_dir,
    hash_artefact,
    load_json,
    locked_manifest_path,
    metrics_at_threshold,
    rel_to_root,
    repo_root,
    resolve,
    sha256_file,
    summarise_numeric,
    test_evaluation_manifest_path,
    verify_artefact_hash,
    write_json,
)
from run_bilstm_baseline import BiLSTMClassifier, NpzSequenceDataset  # noqa: E402


class LockedEvaluationError(RuntimeError):
    """Raised when locked artefacts are missing or inconsistent."""


def select_device(choice: str) -> torch.device:
    if choice == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if choice == "cuda":
        if not torch.cuda.is_available():
            raise SystemExit("CUDA requested but unavailable")
        return torch.device("cuda")
    return torch.device("cpu")


def make_loader(ds: Dataset, batch_size: int) -> DataLoader:
    return DataLoader(
        ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )


@torch.no_grad()
def predict_bilstm(model: BiLSTMClassifier, loader: DataLoader, device: torch.device) -> np.ndarray:
    model.eval()
    outs: list[np.ndarray] = []
    for xb, _ in loader:
        logits = model(xb.to(device))
        outs.append(torch.sigmoid(logits).cpu().numpy())
    return np.concatenate(outs, axis=0)


@torch.no_grad()
def predict_ensemble(
    model: SequenceEnsembleModel, loader: DataLoader, device: torch.device
) -> np.ndarray:
    model.eval()
    outs: list[np.ndarray] = []
    for xb, _ in loader:
        logits, _ = model(xb.to(device))
        outs.append(torch.sigmoid(logits).cpu().numpy())
    return np.concatenate(outs, axis=0)


def load_bilstm(checkpoint: Path, config: dict[str, Any], device: torch.device) -> BiLSTMClassifier:
    arch = config.get("architecture", {})
    model = BiLSTMClassifier(
        input_dim=int(arch.get("input_dim", 13)),
        hidden_size=int(arch.get("hidden_size", 64)),
        dropout=float(arch.get("dropout", 0.2)),
    )
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    if payload.get("architecture") not in {None, "BiLSTMClassifier"}:
        raise LockedEvaluationError(
            f"Unexpected Bi-LSTM architecture tag in {checkpoint}: {payload.get('architecture')}"
        )
    if int(payload.get("seed", config.get("seed", -1))) != int(config.get("seed", -1)):
        raise LockedEvaluationError(
            f"Seed mismatch in Bi-LSTM checkpoint {checkpoint}: "
            f"ckpt={payload.get('seed')} config={config.get('seed')}"
        )
    model.load_state_dict(payload["model_state_dict"])
    model.to(device)
    model.eval()
    return model


def load_sequence_ensemble(
    checkpoint: Path, config: dict[str, Any], device: torch.device
) -> SequenceEnsembleModel:
    model = SequenceEnsembleModel(
        input_dim=13,
        hidden_size=int(config.get("hidden_size", 64)),
        dropout=float(config.get("dropout", 0.2)),
        attention_dim=int(config.get("attention_dim", 64)),
        n_trees=int(config.get("n_trees", 5)),
        tree_depth=int(config.get("tree_depth", 4)),
        classification_head=str(config.get("classification_head", "soft_forest")),
        temporal_aggregation=str(config.get("temporal_aggregation", "attention")),
    )
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    ckpt_cfg = payload.get("config", {})
    for key in (
        "classification_head",
        "temporal_aggregation",
        "hidden_size",
        "dropout",
        "attention_dim",
        "n_trees",
        "tree_depth",
        "seed",
    ):
        if key in ckpt_cfg and key in config and ckpt_cfg[key] != config[key]:
            raise LockedEvaluationError(
                f"Config mismatch for {key} in {checkpoint}: "
                f"ckpt={ckpt_cfg[key]} locked={config[key]}"
            )
    model.load_state_dict(payload["model_state_dict"])
    model.to(device)
    model.eval()
    return model


def load_tree_classifier(model_id: str, path: Path):
    if model_id == "fragmented_bilstm_rf":
        return joblib.load(path)
    if model_id == "fragmented_bilstm_xgboost":
        model = XGBClassifier()
        model.load_model(str(path))
        return model
    raise LockedEvaluationError(f"Unknown tree classifier model_id={model_id}")


def predict_tree(model, x: np.ndarray) -> np.ndarray:
    proba = model.predict_proba(x)
    if proba.shape[1] == 1:
        return proba[:, 0]
    classes = list(getattr(model, "classes_", [0, 1]))
    return proba[:, classes.index(1)] if 1 in classes else proba[:, -1]


def audit_model_entry(
    root: Path,
    entry: dict[str, Any],
    artefacts_by_path: dict[str, dict],
    *,
    dry_run: bool = False,
) -> list[str]:
    messages: list[str] = []
    paths = entry.get("paths", {})
    hashes = entry.get("hashes", {})
    for role, rel in paths.items():
        if not rel or role == "run_dir":
            continue
        abs_path = (root / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
        if not abs_path.exists():
            raise LockedEvaluationError(
                f"Missing {role} for {entry['model_id']} seed={entry['seed']}: {abs_path}"
            )
        # Dry-run must not open test label files (existence-only check).
        if dry_run and role in {"test_y"}:
            messages.append(
                f"OK {entry['model_id']} seed={entry['seed']} {role} exists (labels not read)"
            )
            continue
        expected = hashes.get(role)
        if expected:
            digest = sha256_file(abs_path)
            if digest != expected:
                raise LockedEvaluationError(
                    f"Hash mismatch ({role}) for {entry['model_id']} seed={entry['seed']}: "
                    f"expected {expected}, got {digest}"
                )
        messages.append(f"OK {entry['model_id']} seed={entry['seed']} {role}={rel}")
    # Threshold consistency vs locked numeric value.
    thr_rel = paths.get("threshold")
    if thr_rel:
        thr_path = (root / thr_rel).resolve() if not Path(thr_rel).is_absolute() else Path(thr_rel)
        thr_payload = load_json(thr_path)
        selected = thr_payload.get("selected_threshold")
        if selected is None:
            raise LockedEvaluationError(f"selected_threshold missing in {thr_path}")
        if abs(float(selected) - float(entry["validation_threshold"])) > 1e-12:
            raise LockedEvaluationError(
                f"Threshold mismatch for {entry['model_id']} seed={entry['seed']}: "
                f"manifest={entry['validation_threshold']} file={selected}"
            )
        messages.append(
            f"OK threshold locked={entry['validation_threshold']} for "
            f"{entry['model_id']} seed={entry['seed']}"
        )
    # Config seed / architecture checks where applicable.
    cfg_rel = paths.get("config")
    if cfg_rel and entry["seed"] is not None:
        cfg_path = (root / cfg_rel).resolve() if not Path(cfg_rel).is_absolute() else Path(cfg_rel)
        cfg = load_json(cfg_path)
        if "seed" in cfg and int(cfg["seed"]) != int(entry["seed"]):
            raise LockedEvaluationError(
                f"Config seed mismatch for {entry['model_id']}: "
                f"config={cfg['seed']} manifest={entry['seed']}"
            )
    for art in artefacts_by_path.values():
        if art.get("role") == "test_y" and dry_run:
            continue
        if art["path"] in {paths.get(k) for k in paths}:
            verify_artefact_hash(root, art)
    return messages


def save_predictions(
    path: Path,
    y_true: np.ndarray,
    probs: np.ndarray,
    threshold: float,
    meta: dict[str, Any],
) -> None:
    frame = {
        "model_id": meta["model_id"],
        "model_name": meta["model_name"],
        "seed": meta["seed"],
        "y_true": y_true.astype(np.int8),
        "y_prob": probs.astype(np.float32),
        "y_pred": (probs >= threshold).astype(np.int8),
        "threshold": float(threshold),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(frame).to_parquet(path, index=False)


def evaluate_entry(
    root: Path,
    entry: dict[str, Any],
    device: torch.device,
    batch_size: int,
    test_ds: NpzSequenceDataset | None,
    y_test: np.ndarray | None,
    out_dir: Path,
) -> dict[str, Any]:
    model_id = entry["model_id"]
    seed = int(entry["seed"])
    thr = float(entry["validation_threshold"])
    paths = entry["paths"]
    t0 = time.perf_counter()

    if model_id == "standalone_bilstm":
        assert test_ds is not None and y_test is not None
        cfg = load_json(root / paths["config"])
        model = load_bilstm(root / paths["checkpoint"], cfg, device)
        loader = make_loader(test_ds, batch_size=int(cfg.get("batch_size", batch_size)))
        probs = predict_bilstm(model, loader, device)
    elif model_id in {"attention_linear", "joint_bilstm_attention_soft_forest"}:
        assert test_ds is not None and y_test is not None
        cfg = load_json(root / paths["config"])
        model = load_sequence_ensemble(root / paths["checkpoint"], cfg, device)
        loader = make_loader(test_ds, batch_size=int(cfg.get("batch_size", batch_size)))
        probs = predict_ensemble(model, loader, device)
    elif model_id in {"fragmented_bilstm_rf", "fragmented_bilstm_xgboost"}:
        x_test = np.load(root / paths["test_repr"])
        y_path = root / paths.get("test_y", str(Path(paths["test_repr"]).parent / "test_y.npy"))
        if not y_path.exists():
            y_path = (root / paths["test_repr"]).parent / "test_y.npy"
        y_test = np.load(y_path).astype(np.int8)
        clf = load_tree_classifier(model_id, root / paths["classifier"])
        probs = predict_tree(clf, x_test)
    else:
        raise LockedEvaluationError(f"Model {model_id} is not included in locked test evaluation")

    infer_time = time.perf_counter() - t0
    assert y_test is not None
    if len(probs) != len(y_test):
        raise LockedEvaluationError(
            f"Prediction/label length mismatch for {model_id} seed={seed}: "
            f"{len(probs)} vs {len(y_test)}"
        )
    metrics = metrics_at_threshold(y_test, probs, thr)
    pred_path = out_dir / "test_predictions" / f"{model_id}_seed{seed}.parquet"
    save_predictions(
        pred_path,
        y_test,
        probs,
        thr,
        {"model_id": model_id, "model_name": entry["model_name"], "seed": seed},
    )
    return {
        "model_name": entry["model_name"],
        "model_id": model_id,
        "model_family": entry["model_family"],
        "seed": seed,
        "validation_threshold": thr,
        "test_pr_auc": metrics["pr_auc"],
        "test_precision": metrics["precision"],
        "test_recall": metrics["recall"],
        "test_f1": metrics["f1"],
        "test_fp": metrics["fp"],
        "test_fn": metrics["fn"],
        "test_tp": metrics["tp"],
        "test_tn": metrics["tn"],
        "test_fpr": metrics["fpr"],
        "test_fnr": metrics["fnr"],
        "inference_time_sec": infer_time,
        "predictions_path": rel_to_root(root, pred_path),
        "checkpoint_path": paths.get("checkpoint", ""),
        "classifier_path": paths.get("classifier", ""),
        "encoder_checkpoint_path": paths.get("encoder_checkpoint", ""),
    }


def paired_test_differences(seed_df: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [
        "test_pr_auc",
        "test_precision",
        "test_recall",
        "test_f1",
        "test_fp",
        "test_fn",
    ]
    rows: list[dict[str, Any]] = []
    for seed, g in seed_df.groupby("seed"):
        sub = g.set_index("model_id")
        ids = list(sub.index)
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                for col in metric_cols:
                    rows.append(
                        {
                            "seed": int(seed),
                            "model_a": DISPLAY_NAMES[a],
                            "model_a_id": a,
                            "model_b": DISPLAY_NAMES[b],
                            "model_b_id": b,
                            "metric": col,
                            "value_a": float(sub.loc[a, col]),
                            "value_b": float(sub.loc[b, col]),
                            "difference_a_minus_b": float(sub.loc[a, col]) - float(sub.loc[b, col]),
                        }
                    )
    return pd.DataFrame(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Locked Objective 2 test evaluator.")
    p.add_argument(
        "--manifest",
        default=None,
        help="Path to objective2_final_locked_manifest.json (default under outputs/objective2).",
    )
    p.add_argument("--output-dir", default="outputs/objective2")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--batch-size", type=int, default=1024)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Audit artefacts/hashes/thresholds without reading test labels or writing metrics.",
    )
    p.add_argument(
        "--confirm-test-evaluation",
        action="store_true",
        help="Required for actual one-time test evaluation.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    out_dir = resolve(root, args.output_dir)
    manifest_path = resolve(root, args.manifest) if args.manifest else locked_manifest_path(root)
    eval_manifest_path = test_evaluation_manifest_path(root)

    if not manifest_path.exists():
        raise SystemExit(f"Locked manifest not found: {manifest_path}")

    manifest = load_json(manifest_path)
    if manifest.get("test_evaluated") is True and not args.dry_run:
        raise SystemExit("Locked manifest already marks test_evaluated=true; refusing.")

    if eval_manifest_path.exists() and not args.dry_run:
        raise SystemExit(
            f"Completed evaluation manifest already exists: {eval_manifest_path}. "
            "Refusing second actual test evaluation."
        )

    if not args.dry_run and not args.confirm_test_evaluation:
        raise SystemExit(
            "Refusing test evaluation without --confirm-test-evaluation. "
            "Use --dry-run to audit artefacts without reading test labels."
        )

    if args.dry_run and args.confirm_test_evaluation:
        raise SystemExit("Use either --dry-run or --confirm-test-evaluation, not both.")

    # Verify global artefact table (skip test label files during dry-run).
    artefacts_by_path = {a["path"]: a for a in manifest.get("artefacts", [])}
    for art in manifest.get("artefacts", []):
        if args.dry_run and art.get("role") == "test_y":
            path = Path(art.get("absolute_path") or (root / art["path"]))
            if not path.exists():
                raise LockedEvaluationError(f"Missing test label artefact: {path}")
            continue
        verify_artefact_hash(root, art)

    entries = [
        e
        for e in manifest["models"]
        if e.get("include_in_locked_test_evaluation") and e.get("seed") is not None
    ]
    if not entries:
        raise SystemExit("No models flagged for locked test evaluation in manifest.")

    audit_msgs: list[str] = []
    for entry in entries:
        audit_msgs.extend(
            audit_model_entry(root, entry, artefacts_by_path, dry_run=bool(args.dry_run))
        )

    # Ensure test tensor / repr files exist (existence only in dry-run).
    tensor_test = resolve(root, manifest.get("tensor_files", {}).get("test", "data/processed/tensors/r42_T20_s1_test.npz"))
    if not tensor_test.exists():
        raise LockedEvaluationError(f"Missing test tensor file: {tensor_test}")
    audit_msgs.append(f"OK test tensor present: {rel_to_root(root, tensor_test)}")

    command = " ".join(["python", "scripts/evaluate_locked_objective2.py", *sys.argv[1:]])

    if args.dry_run:
        print("=" * 72)
        print("OBJECTIVE 2 LOCKED TEST EVALUATOR — DRY RUN (no test labels read)")
        print("=" * 72)
        print(f"Manifest: {manifest_path}")
        print(f"Models audited: {len(entries)}")
        for msg in audit_msgs:
            print(f"  {msg}")
        print("\nDry-run complete: hashes/thresholds/configs verified.")
        print("Test labels were not read; no test metrics written.")
        return 0

    device = select_device(args.device)
    test_ds = NpzSequenceDataset(tensor_test, mmap=True, materialize=False)
    y_test = np.asarray(test_ds.y).astype(np.int8)

    seed_rows: list[dict[str, Any]] = []
    for entry in entries:
        print(f"Evaluating {entry['model_name']} seed={entry['seed']} ...")
        is_fragmented = entry["model_id"] in {
            "fragmented_bilstm_rf",
            "fragmented_bilstm_xgboost",
        }
        row = evaluate_entry(
            root,
            entry,
            device,
            args.batch_size,
            None if is_fragmented else test_ds,
            None if is_fragmented else y_test,
            out_dir,
        )
        seed_rows.append(row)
        print(
            f"  PR-AUC={row['test_pr_auc']:.4f} F1={row['test_f1']:.4f} "
            f"FP={row['test_fp']} FN={row['test_fn']}"
        )

    seed_df = pd.DataFrame(seed_rows)
    summary_df = summarise_numeric(
        seed_df,
        [
            "test_pr_auc",
            "test_precision",
            "test_recall",
            "test_f1",
            "test_fp",
            "test_fn",
            "inference_time_sec",
            "validation_threshold",
        ],
        ["model_name", "model_id", "model_family"],
    )
    pairwise_df = paired_test_differences(seed_df)

    seed_csv = out_dir / "objective2_test_seed_results.csv"
    summary_csv = out_dir / "objective2_test_model_summary.csv"
    pairwise_csv = out_dir / "objective2_test_pairwise_comparison.csv"
    seed_df.to_csv(seed_csv, index=False)
    summary_df.to_csv(summary_csv, index=False)
    pairwise_df.to_csv(pairwise_csv, index=False)

    eval_manifest = {
        "status": "test_evaluation_complete",
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "command": command,
        "locked_manifest_path": rel_to_root(root, manifest_path),
        "locked_manifest_sha256": sha256_file(manifest_path),
        "device": str(device),
        "batch_size": args.batch_size,
        "test_tensor": rel_to_root(root, tensor_test),
        "test_tensor_sha256": sha256_file(tensor_test),
        "thresholds_used": {
            f"{e['model_id']}_seed{e['seed']}": e["validation_threshold"] for e in entries
        },
        "configurations": {
            f"{e['model_id']}_seed{e['seed']}": e.get("hyperparameters", {}) for e in entries
        },
        "output_files": {
            "seed_results": rel_to_root(root, seed_csv),
            "model_summary": rel_to_root(root, summary_csv),
            "pairwise": rel_to_root(root, pairwise_csv),
            "predictions_dir": rel_to_root(root, out_dir / "test_predictions"),
        },
        "output_hashes": {
            "seed_results": hash_artefact(root, seed_csv, "test_seed_results"),
            "model_summary": hash_artefact(root, summary_csv, "test_model_summary"),
            "pairwise": hash_artefact(root, pairwise_csv, "test_pairwise"),
        },
        "models_evaluated": seed_rows,
        "note": "Validation-selected thresholds applied unchanged; no test-side threshold optimisation.",
    }
    write_json(eval_manifest_path, eval_manifest)

    # Mark locked manifest as evaluated (append-only flag update).
    manifest["test_evaluated"] = True
    manifest["test_evaluation_manifest"] = rel_to_root(root, eval_manifest_path)
    manifest["test_evaluated_at"] = eval_manifest["completed_at"]
    write_json(manifest_path, manifest)

    print("=" * 72)
    print("OBJECTIVE 2 LOCKED TEST EVALUATION COMPLETE")
    print("=" * 72)
    print(seed_df[["model_name", "seed", "test_pr_auc", "test_f1", "test_fp", "test_fn"]].to_string(index=False))
    print("\nWrote:")
    for p in (seed_csv, summary_csv, pairwise_csv, eval_manifest_path):
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LockedEvaluationError as exc:
        print(f"LOCKED EVALUATION REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
