"""Write r52_test_freeze_manifest_v2.json after the guarded evaluator is implemented.

Does not access r5.2 test / r6.2 / r4.2 test data.
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
from scripts.r52_locked_baselines.guards import (  # noqa: E402
    MANIFEST_V1_REL,
    MANIFEST_V2_REL,
    PRETEST_FREEZE_TAG_V1,
    PRETEST_FREEZE_TAG_V2,
    PREREG_REL,
    REQUIRED_MODELS,
)
from scripts.r52_locked_baselines.safety import (  # noqa: E402
    ProtocolAccessError,
    sha256_file,
    write_json_atomic,
)

SCRIPT_SET = [
    "scripts/r52_locked_baselines/evaluate_r52_test_guarded.py",
    "scripts/r52_locked_baselines/guards.py",
    "scripts/r52_locked_baselines/inference.py",
    "scripts/r52_locked_baselines/safety.py",
    "scripts/r52_locked_baselines/data.py",
    "scripts/r52_locked_baselines/metrics.py",
    "scripts/r52_locked_baselines/__init__.py",
    "scripts/r52_locked_baselines/freeze_preregistration.py",
    "scripts/r52_locked_baselines/write_freeze_manifest_v2.py",
    "tests/test_r52_guarded_evaluator.py",
]


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(root), text=True).strip()


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        text = str(path).replace("\\", "/")
        if "/outputs/" in text:
            return "outputs/" + text.split("/outputs/", 1)[1]
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--evaluator-commit", type=str, default="")
    parser.add_argument("--allow-overwrite", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()

    v1_path = root / MANIFEST_V1_REL
    prereg_path = root / PREREG_REL
    out_path = root / MANIFEST_V2_REL
    if not v1_path.exists() or not prereg_path.exists():
        raise SystemExit("Missing v1 freeze manifest or frozen preregistration")

    v1 = json.loads(v1_path.read_text(encoding="utf-8"))
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    evaluator_commit = args.evaluator_commit or head

    script_hashes = {}
    for rel in SCRIPT_SET:
        p = root / rel
        if not p.exists():
            raise SystemExit(f"Missing script/test for v2 hash inventory: {rel}")
        script_hashes[rel] = sha256_file(p)

    models: list[dict[str, Any]] = []
    for e in v1["models"]:
        model_path = root / e["model_path"]
        thr_path = root / e["threshold_path"]
        model_sha = sha256_file(model_path)
        thr_sha = sha256_file(thr_path)
        if model_sha != e["model_sha256"] or thr_sha != e["threshold_sha256"]:
            raise SystemExit(
                f"Model/threshold hash drift vs v1 for {e['model_name']} seed{e['seed']}"
            )
        models.append(
            {
                "model_name": e["model_name"],
                "seed": e["seed"],
                "model_path": e["model_path"],
                "model_sha256": model_sha,
                "threshold": e["threshold"],
                "threshold_path": e["threshold_path"],
                "threshold_sha256": thr_sha,
            }
        )

    if {m["model_name"] for m in models} != set(REQUIRED_MODELS):
        raise SystemExit("Model set mismatch")
    if sorted({int(m["seed"]) for m in models}) != list(SEEDS):
        raise SystemExit("Seed set mismatch")

    feat = v1["feature_list"]
    if sha256_file(root / feat["path"]) != feat["sha256"]:
        raise SystemExit("Feature list hash drift vs v1")

    split_hashes = {}
    for key, meta in v1["split_metadata_hashes"].items():
        digest = sha256_file(root / meta["path"])
        if digest != meta["sha256"]:
            raise SystemExit(f"Split metadata hash drift: {key}")
        split_hashes[key] = {"path": meta["path"], "sha256": digest}

    prereg_sha = sha256_file(prereg_path)
    if prereg_sha != v1["preregistration"]["sha256"]:
        raise SystemExit("Preregistration hash drift vs v1")

    payload = {
        "status": "final_test_evaluator_frozen_ready_for_one_pass_r52_test",
        "manifest_version": 2,
        "repository_path": str(root),
        "branch": branch,
        "commits": {
            "evaluator_and_tests_commit": evaluator_commit,
            "manifest_commit": None,
            "authoritative_pretest_commit": None,
            "note": (
                "evaluator_and_tests_commit is the commit that introduced the completed "
                "guarded evaluator and unit tests. After this file is committed, "
                "manifest_commit and authoritative_pretest_commit are set to that commit "
                "hash (the objective2-r52-pretest-freeze-v2 tag target)."
            ),
        },
        "pretest_git_tag": PRETEST_FREEZE_TAG_V2,
        "prior_pretest_git_tag": PRETEST_FREEZE_TAG_V1,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "primary_metric": "PR-AUC",
        "secondary_metrics": [
            "F1",
            "precision",
            "recall",
            "FP",
            "FN",
            "alerts",
            "Brier score",
            "log loss",
        ],
        "seeds": list(SEEDS),
        "models_required": list(REQUIRED_MODELS),
        "feature_list": feat,
        "split_metadata_hashes": split_hashes,
        "preregistration": {
            "path": _rel(root, prereg_path),
            "sha256": prereg_sha,
            "draft_path": v1["preregistration"].get("draft_path"),
            "draft_sha256": v1["preregistration"].get("draft_sha256"),
        },
        "prior_manifest_v1": {
            "path": MANIFEST_V1_REL,
            "sha256": sha256_file(v1_path),
            "recorded_commit_field": v1.get("commit"),
            "tag_target_commit": _git(root, "rev-parse", f"{PRETEST_FREEZE_TAG_V1}^{{commit}}"),
        },
        "v1_commit_field_discrepancy_explanation": {
            "manifest_v1_commit_field": v1.get("commit"),
            "tag_v1_target": _git(root, "rev-parse", f"{PRETEST_FREEZE_TAG_V1}^{{commit}}"),
            "explanation": (
                "v1 freeze_manifest.json was generated at tooling HEAD 16f67b7… (path-fix "
                "commit) and therefore recorded that hash in its commit field. The annotated "
                "tag objective2-r52-pretest-freeze-v1 was then applied to the subsequent commit "
                "85b4bec… that force-added the freeze JSON artefacts. Models/thresholds/features "
                "were unchanged between those commits; only provenance bookkeeping differed. "
                "v2 records evaluator and manifest commits separately to avoid this ambiguity."
            ),
        },
        "test_evaluation_script_hashes": script_hashes,
        "enforce_script_hashes": True,
        "models": models,
        "locked_outputs": [
            "r52_test_results_by_seed.csv",
            "r52_test_results_summary.csv",
            "r52_test_paired_comparisons.csv",
            "r52_test_predictions_manifest.json",
            "r52_test_execution_record.json",
            "r52_test_completed.lock",
        ],
        "confirmation": {
            "evaluate_test_flag": "--evaluate-test",
            "confirmation_token": "OBJECTIVE2_R52_ONE_PASS_TEST_CONFIRMATION",
            "both_required": True,
        },
        "declarations": {
            "r52_test_accessed": False,
            "r52_test_predictions_generated": False,
            "r52_test_metrics_generated": False,
            "r62_accessed": False,
            "r42_test_accessed": False,
            "models_retrained": False,
            "thresholds_changed": False,
            "architectures_or_hyperparameters_changed": False,
            "feature_order_changed": False,
            "test_loader_invoked": False,
            "v1_manifest_and_tag_preserved": True,
        },
        "note": (
            "Final pretest freeze after implementing the one-pass guarded evaluator. "
            "No r5.2 test / r6.2 / r4.2 test data were accessed while producing this manifest."
        ),
    }

    if out_path.exists():
        if not args.allow_overwrite:
            raise SystemExit(f"Refusing overwrite of {out_path}")
        out_path.unlink()
    write_json_atomic(out_path, payload)
    print(f"Wrote {out_path}", flush=True)
    print(f"evaluator_and_tests_commit={evaluator_commit}", flush=True)
    _ = OUTPUT_NAMESPACE  # retained for namespace clarity
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProtocolAccessError as exc:
        print(f"PROTOCOL BLOCKED / REFUSED: {exc}", flush=True)
        raise SystemExit(2)
