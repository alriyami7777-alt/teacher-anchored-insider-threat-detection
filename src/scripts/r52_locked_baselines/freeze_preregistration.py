"""Freeze r5.2 Objective 2 test preregistration and cryptographic artefact manifest.

Does not load or evaluate the r5.2 test partition. Does not access r6.2 or r4.2 test.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.r52_locked_baselines import OUTPUT_NAMESPACE, SEEDS  # noqa: E402
from scripts.r52_locked_baselines.safety import (  # noqa: E402
    PRETEST_FREEZE_TAG,
    ProtocolAccessError,
    assert_output_namespace,
    assert_path_allowed,
    path_looks_like_r42_test,
    path_looks_like_r62,
    path_looks_like_test,
    refuse_if_prohibited,
    refuse_test_loader,
    sha256_file,
    write_json_atomic,
)

NEURAL_ROOT = Path("outputs/objective2/r52_odst_confirmation")

MODEL_SPECS: list[tuple[str, str, str]] = [
    # model_name, run_dir_prefix relative to repo, model artefact filename
    ("xgboost", "outputs/objective2/r52_locked_baselines/xgboost_seed{seed}", "model.json"),
    ("random_forest", "outputs/objective2/r52_locked_baselines/random_forest_seed{seed}", "model.joblib"),
    ("attention_linear", "outputs/objective2/r52_odst_confirmation/attention_linear_seed{seed}", "best.pt"),
    ("odst", "outputs/objective2/r52_odst_confirmation/odst_seed{seed}", "best.pt"),
]

REQUIRED_PRIMARY = "PR-AUC"
REQUIRED_SECONDARY = [
    "F1",
    "precision",
    "recall",
    "FP",
    "FN",
    "Brier score",
    "log loss",
]
REQUIRED_MODELS = {"xgboost", "random_forest", "attention_linear", "odst"}

TEST_EVAL_SCRIPTS = [
    "scripts/r52_locked_baselines/evaluate_r52_test_guarded.py",
    "scripts/r52_locked_baselines/safety.py",
    "scripts/r52_locked_baselines/data.py",
    "scripts/r52_locked_baselines/metrics.py",
    "scripts/r52_locked_baselines/__init__.py",
    "scripts/r52_locked_baselines/freeze_preregistration.py",
]


def _git(root: Path, *args: str) -> str:
    out = subprocess.check_output(["git", *args], cwd=str(root), text=True)
    return out.strip()


def _rel(root: Path, path: Path) -> str:
    """Return repo-relative POSIX path without resolving directory junctions."""
    root = Path(root)
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        # If a caller passed a junction-resolved absolute path, fall back to name
        # matching under the logical outputs tree.
        text = str(path).replace("\\", "/")
        marker = "/outputs/"
        if marker in text:
            return "outputs/" + text.split(marker, 1)[1]
        raise ProtocolAccessError(f"Path not under repository root: {path}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _threshold_value(threshold_path: Path) -> float:
    payload = _load_json(threshold_path)
    if "selected_threshold" in payload:
        return float(payload["selected_threshold"])
    if "threshold" in payload:
        return float(payload["threshold"])
    raise ProtocolAccessError(f"No selected_threshold in {threshold_path}")


def _expected_model_hash(root: Path, model: str, seed: int, model_path: Path) -> str:
    if model in {"xgboost", "random_forest"}:
        mh = _load_json(model_path.parent / "model_hash.json")
        return str(mh["sha256"])
    ch = _load_json(model_path.parent / "checkpoint_hashes.json")
    return str(ch["best.pt"])


def audit_draft(draft: dict[str, Any]) -> list[str]:
    """Return human-readable gaps relative to freeze requirements (non-fatal for upgrade)."""
    findings: list[str] = []
    models = {m["model"] for m in draft.get("models_to_evaluate", [])}
    if models != REQUIRED_MODELS:
        findings.append(f"models set={sorted(models)} expected={sorted(REQUIRED_MODELS)}")
    seeds = draft.get("seed_list") or []
    if list(seeds) != list(SEEDS):
        findings.append(f"seed_list={seeds} expected={list(SEEDS)}")
    metrics = [str(x) for x in draft.get("test_metrics_to_report", [])]
    if "PR-AUC" not in metrics:
        findings.append("primary metric PR-AUC missing from test_metrics_to_report")
    for sec in ("F1", "precision", "recall", "FP", "FN", "log_loss", "Brier"):
        if sec not in metrics:
            findings.append(f"secondary metric {sec} missing from draft metric list")
    prohibitions = " | ".join(draft.get("prohibitions", [])).lower()
    for needle, label in (
        ("threshold", "threshold immutability"),
        ("hyperparameter", "no retuning"),
        ("best-seed", "no test-based model selection"),
        ("r6.2", "no r6.2 access"),
    ):
        if needle not in prohibitions:
            findings.append(f"draft prohibitions weak/missing for: {label}")
    # Explicit protocol items the draft did not spell out.
    text = json.dumps(draft).lower()
    for label, ok in (
        ("explicit primary_metric=PR-AUC field", "primary_metric" in text),
        ("sample standard deviation wording", "sample standard" in text or "ddof" in text),
        ("paired evaluation on same test partition", "paired" in text),
        ("one guarded test-evaluation pass", "guarded" in text or "one-time" in text or "one pass" in text),
        ("external temporal confirmation interpretation", "temporal confirmation" in text or "external" in text),
        ("no calibration on test", "calibration" in prohibitions),
        ("r4.2 test prohibition", "r4.2" in prohibitions or "r42" in prohibitions),
    ):
        if not ok:
            findings.append(f"draft incomplete: {label}")
    return findings


def build_frozen_preregistration(draft: dict[str, Any], models_locked: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "frozen",
        "dataset": "CERT r5.2",
        "partition_to_evaluate_later": "test",
        "interpretation": (
            "External temporal confirmation on the chronological r5.2 test partition; "
            "not further model development, selection, or retuning."
        ),
        "primary_metric": REQUIRED_PRIMARY,
        "secondary_metrics": list(REQUIRED_SECONDARY),
        "test_metrics_to_report": [
            "PR-AUC",
            "F1",
            "precision",
            "recall",
            "FP",
            "FN",
            "Brier score",
            "log loss",
            # Additional descriptive metrics permitted alongside the locked set:
            "ROC-AUC",
            "TP",
            "TN",
            "FPR",
            "FNR",
            "n_alerts",
        ],
        "models": ["xgboost", "random_forest", "attention_linear", "odst"],
        "seed_list": list(SEEDS),
        "models_to_evaluate": models_locked,
        "threshold_protocol": {
            "rule": "one validation-selected threshold per model and seed",
            "source": "maximum validation F1 on the r5.2 validation partition",
            "immutable_during_test_evaluation": True,
            "no_test_threshold_adjustment": True,
            "do_not_average_thresholds_for_operations": True,
        },
        "evaluation_protocol": {
            "paired_on_same_r52_test_partition": True,
            "guarded_test_evaluation_passes": 1,
            "report_every_seed": True,
            "aggregate": "mean ± sample standard deviation (ddof=1) across seeds 42/52/62",
            "also_report": "min, max, and all individual seed values",
        },
        "prohibitions": [
            "no test-based model selection",
            "no best-seed selection after test access",
            "no retuning or hyperparameter changes after seeing test",
            "no recalibration on test",
            "no threshold re-selection or adjustment on test",
            "thresholds remain unchanged during test evaluation",
            "no r5.2 test access before pretest freeze tag",
            "no r6.2 access",
            "no r4.2 test access",
            "no performance-superiority claims from this freeze step alone",
        ],
        "draft_source": "outputs/objective2/r52_locked_baselines/r52_test_preregistration_draft.json",
        "pretest_git_tag": PRETEST_FREEZE_TAG,
        "note": (
            "Frozen before any r5.2 test loader invocation. "
            "No test predictions or metrics were generated in this freeze task."
        ),
    }


def collect_model_entries(root: Path, draft: dict[str, Any]) -> list[dict[str, Any]]:
    by_key = {(m["model"], int(m["seed"])): m for m in draft["models_to_evaluate"]}
    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    for model, dir_tmpl, model_name in MODEL_SPECS:
        for seed in SEEDS:
            run_dir = root / dir_tmpl.format(seed=seed)
            model_path = run_dir / model_name
            thr_path = run_dir / "threshold.json"
            for p, role in ((model_path, "model"), (thr_path, "threshold")):
                if not p.exists():
                    missing.append(f"{role}:{p}")
                    continue
                if path_looks_like_test(p) or path_looks_like_r62(p) or path_looks_like_r42_test(p):
                    raise ProtocolAccessError(f"REFUSED artefact path looks prohibited: {p}")
            if missing:
                continue
            thr_val = _threshold_value(thr_path)
            model_sha = sha256_file(model_path)
            thr_sha = sha256_file(thr_path)
            expected = _expected_model_hash(root, model, seed, model_path)
            if model_sha != expected:
                raise ProtocolAccessError(
                    f"Model hash mismatch for {model} seed{seed}: "
                    f"file={model_sha} recorded={expected}"
                )
            draft_row = by_key.get((model, seed))
            if draft_row is None:
                raise ProtocolAccessError(f"Draft missing {model} seed{seed}")
            if abs(float(draft_row["validation_selected_threshold"]) - thr_val) > 1e-12:
                raise ProtocolAccessError(
                    f"Threshold mismatch {model} seed{seed}: "
                    f"draft={draft_row['validation_selected_threshold']} file={thr_val}"
                )
            if draft_row["model_or_checkpoint_hash"] != model_sha:
                raise ProtocolAccessError(
                    f"Draft model hash mismatch {model} seed{seed}"
                )
            entries.append(
                {
                    "model": model,
                    "seed": seed,
                    "model_path": _rel(root, model_path),
                    "model_sha256": model_sha,
                    "threshold": thr_val,
                    "threshold_path": _rel(root, thr_path),
                    "threshold_sha256": thr_sha,
                    "validation_pr_auc": draft_row.get("validation_pr_auc"),
                    "validation_selected_threshold": thr_val,
                    "model_or_checkpoint_hash": model_sha,
                }
            )
    if missing:
        raise ProtocolAccessError("Missing artefacts:\n  " + "\n  ".join(missing))
    if len(entries) != 12:
        raise ProtocolAccessError(f"Expected 12 model×seed entries; got {len(entries)}")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze r5.2 test preregistration (no test access)")
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument(
        "--evaluate-test",
        action="store_true",
        help="PROHIBITED during freeze; present only so the guard can refuse it.",
    )
    parser.add_argument(
        "--confirm-test-evaluation",
        action="store_true",
        help="PROHIBITED during freeze; present only so the guard can refuse it.",
    )
    parser.add_argument(
        "--allow-overwrite-freeze",
        action="store_true",
        help="Allow replacing an existing freeze manifest / frozen preregistration.",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    print("=" * 72, flush=True)
    print("r5.2 Objective 2 pretest freeze (NO test access)", flush=True)
    print(f"root={root}", flush=True)
    print("=" * 72, flush=True)

    try:
        refuse_if_prohibited(
            evaluate_test=bool(args.evaluate_test),
            confirm_test_evaluation=bool(args.confirm_test_evaluation),
            allow_guarded_test=False,
        )
        if args.evaluate_test or args.confirm_test_evaluation:
            refuse_test_loader(split="test")

        out = assert_output_namespace(root / OUTPUT_NAMESPACE, root)
        draft_path = out / "r52_test_preregistration_draft.json"
        if not draft_path.exists():
            raise ProtocolAccessError(f"Missing draft preregistration: {draft_path}")
        draft = _load_json(draft_path)
        findings = audit_draft(draft)
        print("[1/4] Draft audit findings:", flush=True)
        for f in findings:
            print(f"  - {f}", flush=True)
        if not findings:
            print("  (none; draft already complete)", flush=True)

        print("[2/4] Verifying model/threshold artefacts + hashing ...", flush=True)
        model_entries = collect_model_entries(root, draft)
        models_locked = [
            {
                "model": e["model"],
                "seed": e["seed"],
                "validation_selected_threshold": e["threshold"],
                "model_or_checkpoint_hash": e["model_sha256"],
                "threshold_path": e["threshold_path"],
                "threshold_sha256": e["threshold_sha256"],
                "model_path": e["model_path"],
                "validation_pr_auc": e["validation_pr_auc"],
            }
            for e in model_entries
        ]
        frozen = build_frozen_preregistration(draft, models_locked)

        feature_path = out / "feature_names.json"
        split_paths = {
            "r52_locked_baselines_split_audit": out / "r52_split_audit.json",
            "r52_locked_baselines_data_manifest": out / "r52_data_manifest.json",
            "r52_odst_confirmation_split_audit": root / NEURAL_ROOT / "r52_split_audit.json",
            "r52_odst_confirmation_data_manifest": root / NEURAL_ROOT / "r52_data_manifest.json",
            "protocol_lock": out / "protocol_lock.json",
        }
        for p in (feature_path, *split_paths.values()):
            if not p.exists():
                raise ProtocolAccessError(f"Missing lock artefact: {p}")
            assert_path_allowed(p, role=_rel(root, p))

        frozen_path = out / "r52_test_preregistration.json"
        manifest_path = out / "r52_test_freeze_manifest.json"
        if frozen_path.exists() or manifest_path.exists():
            if not args.allow_overwrite_freeze:
                raise ProtocolAccessError(
                    "Freeze artefacts already exist; refuse overwrite "
                    "(pass --allow-overwrite-freeze only for deliberate regeneration)."
                )
            if frozen_path.exists():
                frozen_path.unlink()
            if manifest_path.exists():
                manifest_path.unlink()

        print("[3/4] Writing frozen preregistration ...", flush=True)
        write_json_atomic(frozen_path, frozen)
        prereg_sha = sha256_file(frozen_path)

        script_hashes = {}
        for rel in TEST_EVAL_SCRIPTS:
            p = root / rel
            if not p.exists():
                raise ProtocolAccessError(f"Missing test-evaluation related script: {p}")
            script_hashes[rel] = sha256_file(p)

        branch = _git(root, "branch", "--show-current")
        commit = _git(root, "rev-parse", "HEAD")
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        split_meta_hashes = {
            key: {"path": _rel(root, path), "sha256": sha256_file(path)}
            for key, path in split_paths.items()
        }

        manifest: dict[str, Any] = {
            "status": "test_preregistration_frozen_ready_for_guarded_test",
            "repository_path": str(root),
            "branch": branch,
            "commit": commit,
            "pretest_git_tag": PRETEST_FREEZE_TAG,
            "created_at_utc": created,
            "primary_metric": REQUIRED_PRIMARY,
            "secondary_metrics": list(REQUIRED_SECONDARY),
            "seeds": list(SEEDS),
            "feature_list": {
                "path": _rel(root, feature_path),
                "sha256": sha256_file(feature_path),
                "n_features": int(_load_json(feature_path).get("n_features", 40)),
            },
            "split_metadata_hashes": split_meta_hashes,
            "preregistration": {
                "path": _rel(root, frozen_path),
                "sha256": prereg_sha,
                "draft_path": _rel(root, draft_path),
                "draft_sha256": sha256_file(draft_path),
            },
            "test_evaluation_script_hashes": script_hashes,
            "models": [
                {
                    "model_name": e["model"],
                    "seed": e["seed"],
                    "model_path": e["model_path"],
                    "model_sha256": e["model_sha256"],
                    "threshold": e["threshold"],
                    "threshold_path": e["threshold_path"],
                    "threshold_sha256": e["threshold_sha256"],
                }
                for e in model_entries
            ],
            "draft_audit_findings_addressed_in_frozen_prereg": findings,
            "declarations": {
                "r52_test_accessed": False,
                "r52_test_predictions_generated": False,
                "r52_test_metrics_generated": False,
                "r62_accessed": False,
                "r42_test_accessed": False,
                "models_retrained": False,
                "thresholds_changed": False,
                "architectures_or_hyperparameters_changed": False,
                "test_loader_invoked": False,
            },
            "note": (
                "Cryptographic freeze of validation-selected models/thresholds/features/protocol "
                f"before tag {PRETEST_FREEZE_TAG}. Guarded test evaluation is a separate later pass."
            ),
        }

        print("[4/4] Writing freeze manifest ...", flush=True)
        write_json_atomic(manifest_path, manifest)

        # Self-check: never hashed a test tensor.
        for entry in manifest["models"]:
            for key in ("model_path", "threshold_path"):
                if path_looks_like_test(entry[key]):
                    raise ProtocolAccessError("Manifest unexpectedly references test path")

        print(f"  frozen_prereg={frozen_path}", flush=True)
        print(f"  freeze_manifest={manifest_path}", flush=True)
        print(f"  commit={commit}", flush=True)
        print(f"  models_hashed={len(manifest['models'])}", flush=True)
        print("DONE. No test data accessed.", flush=True)
        return 0
    except ProtocolAccessError as exc:
        print(f"PROTOCOL BLOCKED / REFUSED: {exc}", flush=True)
        return 2
    except Exception as exc:
        print(f"IMPLEMENTATION FAILURE: {exc}", flush=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
