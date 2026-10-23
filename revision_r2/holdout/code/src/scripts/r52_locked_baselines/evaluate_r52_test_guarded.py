"""One-pass guarded CERT r5.2 test evaluator for Objective 2.

Dual confirmation is required before the test loader may be called:

  python -m scripts.r52_locked_baselines.evaluate_r52_test_guarded \\
    --evaluate-test \\
    --confirmation-token OBJECTIVE2_R52_ONE_PASS_TEST_CONFIRMATION

Non-accessing verification (safe for pretest freeze tasks):

  python -m scripts.r52_locked_baselines.evaluate_r52_test_guarded --verify-only
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.r52_locked_baselines import OUTPUT_NAMESPACE, SEEDS  # noqa: E402
from scripts.r52_locked_baselines.guards import (  # noqa: E402
    CONFIRMATION_PHRASE,
    LOCKED_OUTPUT_NAMES,
    PRETEST_FREEZE_TAG_V2,
    refuse_forbidden_tensor_paths,
    repo_rel,
    run_preflight,
)
from scripts.r52_locked_baselines.metrics import evaluate_validation  # noqa: E402
from scripts.r52_locked_baselines.safety import ProtocolAccessError, sha256_file  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _summary_rows(by_seed: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [
        "pr_auc",
        "f1",
        "precision",
        "recall",
        "fp",
        "fn",
        "n_alerts",
        "brier_score",
        "log_loss",
        "roc_auc",
    ]
    rows: list[dict[str, Any]] = []
    for model, g in by_seed.groupby("model"):
        row: dict[str, Any] = {"model": model, "n_seeds": int(len(g))}
        for col in metric_cols:
            vals = [float(v) for v in g[col].tolist()]
            row[f"{col}_mean"] = float(statistics.fmean(vals))
            row[f"{col}_std"] = float(statistics.stdev(vals)) if len(vals) > 1 else 0.0
            row[f"{col}_min"] = float(min(vals))
            row[f"{col}_max"] = float(max(vals))
            row[f"{col}_seeds"] = ";".join(f"{v:.8g}" for v in vals)
        row["threshold_per_seed"] = ";".join(f"{float(v):.8g}" for v in g["threshold"].tolist())
        row["threshold_note"] = "frozen validation-selected; unchanged on test"
        rows.append(row)
    return pd.DataFrame(rows)


def _paired_rows(by_seed: pd.DataFrame) -> pd.DataFrame:
    metrics = ["pr_auc", "f1", "precision", "recall", "fp", "fn", "n_alerts", "brier_score", "log_loss"]
    models = list(dict.fromkeys(by_seed["model"].tolist()))
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        sub = by_seed[by_seed["seed"] == seed].set_index("model")
        for i, a in enumerate(models):
            for b in models[i + 1 :]:
                if a not in sub.index or b not in sub.index:
                    continue
                for m in metrics:
                    rows.append(
                        {
                            "seed": int(seed),
                            "model_a": a,
                            "model_b": b,
                            "metric": m,
                            "value_a": float(sub.loc[a, m]),
                            "value_b": float(sub.loc[b, m]),
                            "difference_a_minus_b": float(sub.loc[a, m]) - float(sub.loc[b, m]),
                        }
                    )
    return pd.DataFrame(rows)


def run_armed_evaluation(
    root: Path,
    preflight: dict[str, Any],
    *,
    tensor_dir: Path,
    load_test_fn: Callable[..., tuple[Any, Any, dict[str, Any]]] | None = None,
    predict_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute the one-pass evaluation after preflight + dual confirmation."""
    from scripts.r52_locked_baselines.inference import (
        load_r52_test_once,
        predict_one,
        prepare_test_matrices,
    )

    load_test_fn = load_test_fn or load_r52_test_once
    predict_fn = predict_fn or predict_one

    out_dir = root / OUTPUT_NAMESPACE
    start = _utc_now()
    refuse_forbidden_tensor_paths([tensor_dir])

    X_seq, y_test, test_meta = load_test_fn(tensor_dir, armed=True)
    X_agg, feat_names = prepare_test_matrices(X_seq)
    if feat_names != preflight["feature_names"]:
        raise ProtocolAccessError("REFUSED: aggregated test feature order mismatch")

    seed_rows: list[dict[str, Any]] = []
    pred_manifest: list[dict[str, Any]] = []

    for entry in preflight["models"]:
        model = entry["model"]
        seed = int(entry["seed"])
        thr = float(entry["threshold"])
        model_path = root / entry["model_path"]
        config_path = model_path.parent / "config.json"
        probs = predict_fn(
            model=model,
            model_path=model_path,
            config_path=config_path,
            X_seq=X_seq,
            X_agg=X_agg,
        )
        if len(probs) != len(y_test):
            raise ProtocolAccessError(
                f"Prediction length mismatch for {model} seed{seed}: "
                f"{len(probs)} vs {len(y_test)}"
            )
        metrics = evaluate_validation(y_test, probs, thr)
        # Intentionally do not print metric values (no progressive decision feedback).
        seed_rows.append(
            {
                "model": model,
                "seed": seed,
                "threshold": thr,
                "threshold_source": "frozen_validation_selected",
                "threshold_changed": False,
                "calibration_fitted": False,
                "model_selection_performed": False,
                **metrics,
                "model_path": entry["model_path"],
                "model_sha256": entry["model_sha256"],
                "threshold_path": entry["threshold_path"],
                "threshold_sha256": entry["threshold_sha256"],
            }
        )
        pred_manifest.append(
            {
                "model": model,
                "seed": seed,
                "n_scores": int(len(probs)),
                "threshold": thr,
                "model_sha256": entry["model_sha256"],
                "note": "scores retained only ephemerally during one-pass; not written as raw arrays",
            }
        )

    by_seed = pd.DataFrame(seed_rows)
    summary = _summary_rows(by_seed)
    paired = _paired_rows(by_seed)

    paths = {name: out_dir / name for name in LOCKED_OUTPUT_NAMES}
    # Write predetermined outputs; completion lock last.
    by_seed.to_csv(paths["r52_test_results_by_seed.csv"], index=False)
    summary.to_csv(paths["r52_test_results_summary.csv"], index=False)
    paired.to_csv(paths["r52_test_paired_comparisons.csv"], index=False)
    _write_json(
        paths["r52_test_predictions_manifest.json"],
        {
            "status": "one_pass_complete",
            "n_model_seed_pairs": len(pred_manifest),
            "entries": pred_manifest,
            "raw_prediction_arrays_written": False,
        },
    )

    output_hashes = {
        name: sha256_file(path)
        for name, path in paths.items()
        if name != "r52_test_completed.lock" and path.exists()
    }
    completion = _utc_now()
    execution_record = {
        "status": "success",
        "started_at_utc": start,
        "completed_at_utc": completion,
        "repository_commit": preflight["git"].get("head"),
        "git_tag": preflight["git"].get("matched_tag") or PRETEST_FREEZE_TAG_V2,
        "preregistration_sha256": preflight["preregistration_sha256"],
        "freeze_manifest_path": preflight["freeze_manifest_path"],
        "freeze_manifest_sha256": preflight["freeze_manifest_sha256"],
        "evaluator_script": "scripts/r52_locked_baselines/evaluate_r52_test_guarded.py",
        "evaluator_script_sha256": sha256_file(
            root / "scripts/r52_locked_baselines/evaluate_r52_test_guarded.py"
        ),
        "model_and_threshold_hashes": [
            {
                "model": e["model"],
                "seed": e["seed"],
                "model_sha256": e["model_sha256"],
                "threshold": e["threshold"],
                "threshold_sha256": e["threshold_sha256"],
            }
            for e in preflight["models"]
        ],
        "test_split_metadata": {
            "path": repo_rel(root, Path(test_meta["path"])),
            "sha256": test_meta["sha256"],
            "shape": test_meta["shape"],
            "n": test_meta["n"],
        },
        "thresholds_changed": False,
        "calibration_fitted": False,
        "model_selection_performed": False,
        "output_hashes": output_hashes,
        "confirmation_token_accepted": True,
        "interpretation": (
            "External temporal confirmation on the chronological r5.2 test partition; "
            "not further model development."
        ),
    }
    _write_json(paths["r52_test_execution_record.json"], execution_record)
    output_hashes["r52_test_execution_record.json"] = sha256_file(
        paths["r52_test_execution_record.json"]
    )
    # Completion marker only after all other outputs exist.
    missing = [
        name
        for name in LOCKED_OUTPUT_NAMES
        if name != "r52_test_completed.lock" and not paths[name].exists()
    ]
    if missing:
        raise ProtocolAccessError(
            "REFUSED: incomplete outputs; completion marker not written: " + ", ".join(missing)
        )
    lock_payload = {
        "status": "r52_test_evaluation_completed",
        "completed_at_utc": completion,
        "one_pass": True,
        "rerun_prohibited": True,
        "execution_record_sha256": output_hashes["r52_test_execution_record.json"],
    }
    _write_json(paths["r52_test_completed.lock"], lock_payload)
    execution_record["output_hashes"]["r52_test_completed.lock"] = sha256_file(
        paths["r52_test_completed.lock"]
    )
    _write_json(paths["r52_test_execution_record.json"], execution_record)
    return execution_record


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Guarded one-pass r5.2 Objective 2 test evaluator")
    p.add_argument("--root", type=Path, default=_ROOT)
    p.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate freeze artefacts/Git/output readiness without loading test data.",
    )
    p.add_argument(
        "--evaluate-test",
        action="store_true",
        help="Arm test evaluation (requires --confirmation-token).",
    )
    p.add_argument(
        "--confirmation-token",
        type=str,
        default="",
        help=f"Must equal {CONFIRMATION_PHRASE} exactly when --evaluate-test is set.",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional freeze manifest path (defaults to v2 if present else v1).",
    )
    p.add_argument(
        "--tensor-dir",
        type=Path,
        default=None,
        help="Directory containing r52_T20_s1_test.npz (armed mode only).",
    )
    p.add_argument(
        "--require-v2-tag",
        action="store_true",
        help="For --verify-only, require HEAD at objective2-r52-pretest-freeze-v2.",
    )
    p.add_argument(
        "--skip-git-checks",
        action="store_true",
        help="Test-only escape hatch (unit tests). Never use for real evaluation.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    token = args.confirmation_token or None

    print("=" * 72, flush=True)
    print("r5.2 Objective 2 guarded test evaluator", flush=True)
    print(f"root={root}", flush=True)
    print("=" * 72, flush=True)

    try:
        if not args.verify_only and not args.evaluate_test:
            raise ProtocolAccessError(
                "REFUSED: provide --verify-only, or both --evaluate-test and "
                f"--confirmation-token {CONFIRMATION_PHRASE}"
            )
        if args.evaluate_test and args.verify_only:
            raise ProtocolAccessError("REFUSED: --verify-only and --evaluate-test are mutually exclusive")
        if args.evaluate_test and token != CONFIRMATION_PHRASE:
            # Refuse before any preflight I/O that could be confused with test access.
            raise ProtocolAccessError(
                "REFUSED: incorrect or missing --confirmation-token; test loader not called"
            )
        if (not args.evaluate_test) and token:
            raise ProtocolAccessError(
                "REFUSED: --confirmation-token without --evaluate-test"
            )

        preflight = run_preflight(
            root,
            verify_only=bool(args.verify_only),
            evaluate_test=bool(args.evaluate_test),
            confirmation_token=token,
            require_v2_tag=bool(args.require_v2_tag),
            manifest_path=args.manifest,
            check_git_tag=not args.skip_git_checks,
            check_clean_worktree=not args.skip_git_checks,
        )
        print(f"preflight_status={preflight['status']}", flush=True)
        print(f"freeze_manifest={preflight['freeze_manifest_path']}", flush=True)
        print(f"models_verified={len(preflight['models'])}", flush=True)
        print(f"git={preflight['git']}", flush=True)

        if args.verify_only:
            print("verify_only=true", flush=True)
            print("test_data_accessed=false", flush=True)
            print("test_loader_called=false", flush=True)
            print("test_predictions_generated=false", flush=True)
            print("test_metrics_generated=false", flush=True)
            print("VERIFY_ONLY_OK", flush=True)
            return 0

        tensor_dir = (
            args.tensor_dir
            if args.tensor_dir is not None
            else root / "data" / "processed" / "r5.2" / "tensors"
        )
        if not tensor_dir.is_absolute():
            tensor_dir = (root / tensor_dir).resolve()
        refuse_forbidden_tensor_paths([tensor_dir])

        print("armed_evaluation_starting (one-pass)", flush=True)
        record = run_armed_evaluation(root, preflight, tensor_dir=tensor_dir)
        print(f"execution_status={record['status']}", flush=True)
        print("DONE one-pass r5.2 test evaluation.", flush=True)
        return 0
    except ProtocolAccessError as exc:
        print(f"PROTOCOL BLOCKED / REFUSED: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
