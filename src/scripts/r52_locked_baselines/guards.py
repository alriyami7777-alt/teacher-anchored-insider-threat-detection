"""Preflight guards for the one-pass r5.2 guarded test evaluator.

These checks never load the r5.2 test partition. They are shared by
``--verify-only`` and the armed evaluation path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from . import OUTPUT_NAMESPACE, SEEDS
from .data import LOCKED_AGG_FEATURES
from .safety import (
    ProtocolAccessError,
    path_looks_like_r42_test,
    path_looks_like_r62,
    path_looks_like_test,
    sha256_file,
)

CONFIRMATION_PHRASE = "OBJECTIVE2_R52_ONE_PASS_TEST_CONFIRMATION"
PRETEST_FREEZE_TAG_V1 = "objective2-r52-pretest-freeze-v1"
PRETEST_FREEZE_TAG_V2 = "objective2-r52-pretest-freeze-v2"
REQUIRED_MODELS = ("xgboost", "random_forest", "attention_linear", "odst")

PREREG_REL = f"{OUTPUT_NAMESPACE}/r52_test_preregistration.json"
MANIFEST_V1_REL = f"{OUTPUT_NAMESPACE}/r52_test_freeze_manifest.json"
MANIFEST_V2_REL = f"{OUTPUT_NAMESPACE}/r52_test_freeze_manifest_v2.json"
FEATURE_REL = f"{OUTPUT_NAMESPACE}/feature_names.json"

LOCKED_OUTPUT_NAMES = (
    "r52_test_results_by_seed.csv",
    "r52_test_results_summary.csv",
    "r52_test_paired_comparisons.csv",
    "r52_test_predictions_manifest.json",
    "r52_test_execution_record.json",
    "r52_test_completed.lock",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_rel(root: Path, path: Path) -> str:
    root = Path(root)
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        text = str(path).replace("\\", "/")
        marker = "/outputs/"
        if marker in text:
            return "outputs/" + text.split(marker, 1)[1]
        raise ProtocolAccessError(f"Path not under repository root: {path}")


def git_stdout(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(root), text=True).strip()


def assert_clean_worktree(root: Path) -> None:
    porcelain = git_stdout(root, "status", "--porcelain")
    if porcelain:
        raise ProtocolAccessError(
            "REFUSED: dirty worktree; commit or stash before guarded test evaluation.\n"
            + porcelain
        )


def tag_commit(root: Path, tag: str) -> str | None:
    try:
        return git_stdout(root, "rev-parse", f"{tag}^{{commit}}")
    except subprocess.CalledProcessError:
        return None


def assert_git_at_approved_tag(
    root: Path,
    *,
    require_v2: bool,
) -> dict[str, str]:
    head = git_stdout(root, "rev-parse", "HEAD")
    v2 = tag_commit(root, PRETEST_FREEZE_TAG_V2)
    v1 = tag_commit(root, PRETEST_FREEZE_TAG_V1)
    if require_v2:
        if v2 is None:
            raise ProtocolAccessError(
                f"REFUSED: required tag {PRETEST_FREEZE_TAG_V2} does not exist"
            )
        if head != v2:
            raise ProtocolAccessError(
                f"REFUSED: HEAD {head} is not at approved tag {PRETEST_FREEZE_TAG_V2} ({v2})"
            )
        return {"head": head, "matched_tag": PRETEST_FREEZE_TAG_V2, "note": "ok"}
    # verify-only: once v2 exists, HEAD must match it; otherwise allow clean HEAD.
    if v2 is not None:
        if head != v2:
            raise ProtocolAccessError(
                f"REFUSED: HEAD {head} != {PRETEST_FREEZE_TAG_V2} tip {v2}"
            )
        return {"head": head, "matched_tag": PRETEST_FREEZE_TAG_V2, "note": "ok"}
    if v1 is not None and head == v1:
        return {"head": head, "matched_tag": PRETEST_FREEZE_TAG_V1, "note": "v2_tag_pending"}
    return {
        "head": head,
        "matched_tag": "",
        "note": "v2_tag_pending_clean_head_accepted_for_verify_only",
    }


def _expect_hash(path: Path, expected: str, role: str) -> str:
    if not path.exists():
        raise ProtocolAccessError(f"REFUSED: missing artefact ({role}): {path}")
    digest = sha256_file(path)
    if digest != expected:
        raise ProtocolAccessError(
            f"REFUSED: SHA-256 mismatch for {role} at {path}: "
            f"expected {expected}, got {digest}"
        )
    return digest


def verify_feature_list(root: Path, feature_path: Path | None = None) -> list[str]:
    path = feature_path or (root / FEATURE_REL)
    if not path.exists():
        raise ProtocolAccessError(f"REFUSED: missing feature list: {path}")
    payload = load_json(path)
    names = list(payload.get("feature_names") or [])
    if names != list(LOCKED_AGG_FEATURES):
        raise ProtocolAccessError(
            "REFUSED: feature names/order differ from locked 40-feature representation"
        )
    if int(payload.get("n_features", len(names))) != 40 or len(names) != 40:
        raise ProtocolAccessError("REFUSED: expected exactly 40 features")
    return names


def verify_model_set_and_seeds(prereg: dict[str, Any], manifest: dict[str, Any]) -> None:
    models = tuple(prereg.get("models") or [])
    if models != REQUIRED_MODELS:
        raise ProtocolAccessError(
            f"REFUSED: unexpected model set {models}; expected {REQUIRED_MODELS}"
        )
    seeds = tuple(int(s) for s in (prereg.get("seed_list") or []))
    if seeds != tuple(SEEDS):
        raise ProtocolAccessError(f"REFUSED: unexpected seeds {seeds}; expected {tuple(SEEDS)}")
    m_seeds = tuple(int(s) for s in (manifest.get("seeds") or []))
    if m_seeds and m_seeds != tuple(SEEDS):
        raise ProtocolAccessError(f"REFUSED: manifest seeds {m_seeds} != {tuple(SEEDS)}")
    entries = prereg.get("models_to_evaluate") or []
    keys = {(e["model"], int(e["seed"])) for e in entries}
    expected = {(m, s) for m in REQUIRED_MODELS for s in SEEDS}
    if keys != expected:
        raise ProtocolAccessError(
            f"REFUSED: models_to_evaluate keys {sorted(keys)} != {sorted(expected)}"
        )


def verify_thresholds_and_model_hashes(
    root: Path,
    prereg: dict[str, Any],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    man_by_key = {
        (e["model_name"], int(e["seed"])): e for e in (manifest.get("models") or [])
    }
    verified: list[dict[str, Any]] = []
    for row in prereg["models_to_evaluate"]:
        model = row["model"]
        seed = int(row["seed"])
        key = (model, seed)
        if key not in man_by_key:
            raise ProtocolAccessError(f"REFUSED: manifest missing {model} seed{seed}")
        man = man_by_key[key]
        model_path = root / man["model_path"]
        thr_path = root / man["threshold_path"]
        for p in (model_path, thr_path):
            # Model/threshold artefacts themselves are not test tensors; still refuse
            # if a path string unexpectedly points at forbidden corpora.
            text = str(p)
            if path_looks_like_r62(text) or path_looks_like_r42_test(text):
                raise ProtocolAccessError(f"REFUSED: prohibited corpus path: {p}")
            if path_looks_like_test(text) and "threshold" not in p.name.lower():
                # threshold/model dirs never contain *_test.npz; belt-and-braces.
                if p.suffix.lower() in {".npz", ".parquet"}:
                    raise ProtocolAccessError(f"REFUSED: test-like artefact path: {p}")
        _expect_hash(model_path, man["model_sha256"], f"{model}_seed{seed}_model")
        _expect_hash(thr_path, man["threshold_sha256"], f"{model}_seed{seed}_threshold")
        thr_payload = load_json(thr_path)
        thr_val = float(thr_payload.get("selected_threshold", thr_payload.get("threshold")))
        frozen = float(row["validation_selected_threshold"])
        if abs(thr_val - frozen) > 1e-12 or abs(float(man["threshold"]) - frozen) > 1e-12:
            raise ProtocolAccessError(
                f"REFUSED: threshold mismatch for {model} seed{seed}: "
                f"file={thr_val} prereg={frozen} manifest={man['threshold']}"
            )
        if row.get("model_or_checkpoint_hash") and row["model_or_checkpoint_hash"] != man["model_sha256"]:
            raise ProtocolAccessError(
                f"REFUSED: prereg model hash != manifest for {model} seed{seed}"
            )
        verified.append(
            {
                "model": model,
                "seed": seed,
                "threshold": thr_val,
                "model_path": man["model_path"],
                "model_sha256": man["model_sha256"],
                "threshold_path": man["threshold_path"],
                "threshold_sha256": man["threshold_sha256"],
            }
        )
    if len(verified) != 12:
        raise ProtocolAccessError(f"REFUSED: expected 12 model-seed pairs; got {len(verified)}")
    return verified


def verify_manifest_support_hashes(root: Path, manifest: dict[str, Any]) -> None:
    feat = manifest.get("feature_list") or {}
    if feat:
        _expect_hash(root / feat["path"], feat["sha256"], "feature_list")
    for key, meta in (manifest.get("split_metadata_hashes") or {}).items():
        _expect_hash(root / meta["path"], meta["sha256"], f"split_meta:{key}")
    prereg_meta = manifest.get("preregistration") or {}
    if prereg_meta.get("path") and prereg_meta.get("sha256"):
        _expect_hash(root / prereg_meta["path"], prereg_meta["sha256"], "preregistration")
    # Script hashes in v1 may intentionally drift after evaluator completion; v2 is authoritative.
    # Only enforce script hashes when the manifest declares enforce_script_hashes=true.
    if manifest.get("enforce_script_hashes"):
        for rel, expected in (manifest.get("test_evaluation_script_hashes") or {}).items():
            _expect_hash(root / rel, expected, f"script:{rel}")


def assert_no_prior_test_outputs(out_dir: Path) -> None:
    lock = out_dir / "r52_test_completed.lock"
    if lock.exists():
        raise ProtocolAccessError(
            f"REFUSED: completion marker already exists (one-pass already done): {lock}"
        )
    existing = [name for name in LOCKED_OUTPUT_NAMES if (out_dir / name).exists()]
    if existing:
        raise ProtocolAccessError(
            "REFUSED: prior test output(s) already exist: " + ", ".join(existing)
        )


def assert_confirmation(*, evaluate_test: bool, confirmation_token: str | None) -> None:
    if not evaluate_test:
        raise ProtocolAccessError("REFUSED: --evaluate-test is required for armed evaluation")
    if confirmation_token != CONFIRMATION_PHRASE:
        raise ProtocolAccessError(
            "REFUSED: incorrect or missing --confirmation-token "
            f"(expected exact token {CONFIRMATION_PHRASE!r})"
        )


def refuse_forbidden_tensor_paths(paths: list[Path | str]) -> None:
    for p in paths:
        if path_looks_like_r62(p):
            raise ProtocolAccessError(f"REFUSED: r6.2 path detected: {p}")
        if path_looks_like_r42_test(p):
            raise ProtocolAccessError(f"REFUSED: r4.2 test path detected: {p}")


def select_freeze_manifest(root: Path, preferred: Path | None = None) -> Path:
    if preferred is not None:
        path = preferred if preferred.is_absolute() else root / preferred
        if not path.exists():
            raise ProtocolAccessError(f"REFUSED: freeze manifest not found: {path}")
        return path
    v2 = root / MANIFEST_V2_REL
    if v2.exists():
        return v2
    v1 = root / MANIFEST_V1_REL
    if v1.exists():
        return v1
    raise ProtocolAccessError("REFUSED: no freeze manifest (v1 or v2) found")


def run_preflight(
    root: Path,
    *,
    verify_only: bool,
    evaluate_test: bool = False,
    confirmation_token: str | None = None,
    require_v2_tag: bool = False,
    manifest_path: Path | None = None,
    check_git_tag: bool = True,
    check_clean_worktree: bool = True,
) -> dict[str, Any]:
    """Validate freeze artefacts. Never opens the r5.2 test partition."""
    if evaluate_test and verify_only:
        raise ProtocolAccessError("REFUSED: use either --verify-only or armed mode, not both")

    out_dir = root / OUTPUT_NAMESPACE
    prereg_path = root / PREREG_REL
    if not prereg_path.exists():
        raise ProtocolAccessError(f"REFUSED: missing frozen preregistration: {prereg_path}")

    freeze_path = select_freeze_manifest(root, manifest_path)
    prereg = load_json(prereg_path)
    manifest = load_json(freeze_path)

    if prereg.get("status") != "frozen":
        raise ProtocolAccessError(
            f"REFUSED: preregistration status={prereg.get('status')!r}; expected 'frozen'"
        )

    if check_clean_worktree:
        assert_clean_worktree(root)

    git_info = {"head": "", "matched_tag": "", "note": "skipped"}
    if check_git_tag:
        git_info = assert_git_at_approved_tag(
            root,
            require_v2=(not verify_only) or require_v2_tag,
        )

    verify_model_set_and_seeds(prereg, manifest)
    features = verify_feature_list(root)
    verify_manifest_support_hashes(root, manifest)
    models = verify_thresholds_and_model_hashes(root, prereg, manifest)
    assert_no_prior_test_outputs(out_dir)

    if not verify_only:
        assert_confirmation(
            evaluate_test=evaluate_test,
            confirmation_token=confirmation_token,
        )

    return {
        "root": str(root),
        "verify_only": verify_only,
        "preregistration_path": repo_rel(root, prereg_path),
        "preregistration_sha256": sha256_file(prereg_path),
        "freeze_manifest_path": repo_rel(root, freeze_path),
        "freeze_manifest_sha256": sha256_file(freeze_path),
        "feature_names": features,
        "models": models,
        "git": git_info,
        "output_dir": repo_rel(root, out_dir),
        "test_data_accessed": False,
        "test_loader_called": False,
        "status": "preflight_ok",
    }
