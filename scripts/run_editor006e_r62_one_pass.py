#!/usr/bin/env python3
"""EDITOR-006E one-pass CERT r6.2 external execution entrypoint.

Frozen by EDITOR-006D. Reuses editor006b_harness modules; does not copy them.
This module does not write a true predictive authorisation.
EDITOR-006D must not score CERT r6.2; future EDITOR-006E requires a true
authorisation that this task does not create.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor006b_harness.bootstrap import paired_user_cluster_bootstrap  # noqa: E402
from editor006b_harness.cli import validate_external_authorization  # noqa: E402
from editor006b_harness.contracts import load_freeze_bundle, validate_contracts  # noqa: E402
from editor006b_harness.hash_gate import preflight_all_eighteen  # noqa: E402
from editor006b_harness.input_bundle import DenseDailyWindowProvider  # noqa: E402
from editor006b_harness.mechanism import (  # noqa: E402
    STATUS_DISABLED,
    compare_student_teacher,
    mechanism_registry,
    paper_facing_mechanism_names,
)
from editor006b_harness.metrics import metrics_at_frozen_threshold  # noqa: E402
from editor006b_harness.model_loaders import producing_source_preflight  # noqa: E402
from editor006b_harness.safety import (  # noqa: E402
    BATCH_SIZE_FROZEN,
    BOOTSTRAP_SEED,
    BOOTSTRAP_VALID_RESAMPLES,
    C2_SEED62_THRESHOLD,
    FREEZE_DIR,
    N_FEATURES,
    SEEDS,
    T_WINDOW,
    HarnessProtocolError,
    hash_harness_sources,
    path_looks_like_r52_test,
    refuse_r52_test,
    refuse_r62_without_auth,
    sha256_file,
    utc_now,
)
from editor006b_harness.scoring import (  # noqa: E402
    write_scores_phase_streaming,
)

TASK_ID_FUTURE = "EDITOR-006E"
DATASET_ID = "CERT r6.2"
HARNESS_RELEASE_COMMIT = "2a73123b25f9bf9d92b651e07ce06b8fa1ba6017"
HARNESS_CODE_SHA256 = "d287a85e03e8c666be5cf06c2329e6d81fbed3ea08cb1563225ac2d92badc451"
HARNESS_RUNNER_SHA256 = "3965f47a08fa79f17bc2d4c1cbf54fbdcd3ce1d6add6d7f864c123a501f8d17d"
CONTRACT_BUNDLE_SHA256 = "d9f3daf89da4b1d06d22081245a63eac50a0768aece1f1e566187593783e734a"
MODEL_ALLOWLIST_SHA256 = "699c983d1ad98a5dcce7768447dcac4a44f5a5e8fed740b4c8378876efa52e5a"
SCALER_SHA256 = "6a092df8275e15b6e05c685b306f48de72ab55fb1e88ede5ed5899ecd63f3488"
SEQUENCE_ORDER_SHA256 = "21c4dd51f8aefb26fa1987764b0c129fac599fc52653349732a4fd8e39c32b4c"
FINAL_RELEASE_MANIFEST_SHA256 = "56d3aae461835009471ccb22b1511530bb40e41a294c8bb1640943eaf14354ba"
EDITOR006C_RELEASE_COMMIT = "b4b19d44b31c4b9d054fa0d782f80e65a18dac4b"

BUNDLE_DIR_DEFAULT = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006c_bundle")
OUTPUT_DIR_DEFAULT = Path(r"C:\PhD\06_Datasets\derived\teacher_anchored_r62_editor006e_scores")
FINAL_MANIFEST_DEFAULT = (
    ROOT / "review" / "editor006c_r62_input_bundle" / "EDITOR006C_FINAL_RELEASE_MANIFEST.json"
)
HARNESS_RUNNER_PATH = ROOT / "scripts" / "run_editor006b_harness.py"
EXTERNAL_RUNNER_PATH = ROOT / "scripts" / "run_editor006e_r62_one_pass.py"

N_USERS = 4000
N_DAYS = 516
N_WINDOWS = 1_988_000
N_DEOVERLAP = 100_000
N_STARTS = N_DAYS - T_WINDOW + 1

REQUIRED_BUNDLE_FILES = (
    "scaled_dense_daily.npy",
    "window_index.npy",
    "completed_window_labels.npy",
    "endpoint_labels.npy",
    "deoverlap_offset0_mask.npy",
    "user_ids.npy",
    "calendar_dates.npy",
    "official_insider_flags.npy",
    "official_incident_codes.npy",
    "window_scenario_bitmask.npy",
    "endpoint_scenario_bitmask.npy",
)

ADDITIONAL_AUTH_FIELDS = (
    "external_runner_sha256",
    "harness_runner_sha256",
    "editor006c_release_commit",
    "sequence_order_sha256",
    "scaler_sha256",
)

FORBIDDEN_CLAIMS = (
    "overall predictive superiority",
    "teacher anchoring improves prediction",
    "real-time detection",
    "causal detection",
    "unseen-user generalisation",
    "adversarial robustness",
    "35 independent malicious incidents",
    "10 independent malicious clusters",
)

PREDECLARED_VIEWS = (
    {
        "name": "COMPLETED_WINDOW",
        "labels": "completed_window_labels",
        "n": N_WINDOWS,
        "mask": None,
    },
    {
        "name": "ENDPOINT_PAST_ONLY",
        "labels": "endpoint_labels",
        "n": N_WINDOWS,
        "mask": None,
        "never": ["real-time", "streaming", "intra-day"],
    },
    {
        "name": "DEOVERLAP_OFFSET0",
        "labels": "completed_window_labels[mask]",
        "n": N_DEOVERLAP,
        "mask": "deoverlap_offset0_mask",
    },
)


def compute_external_runner_sha256(path: Path | None = None) -> str:
    return sha256_file(Path(path) if path is not None else EXTERNAL_RUNNER_PATH)


def refuse_dev_array_scorer_for_external(*_args: Any, **_kwargs: Any) -> None:
    raise HarnessProtocolError(
        "EXTERNAL: development-array scorer (write_scores_phase) is forbidden for CERT r6.2"
    )


def require_all_scores_complete(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir) / "ALL_SCORES_COMPLETE.json"
    if not path.is_file():
        raise HarnessProtocolError("ANALYSIS BLOCKED: ALL_SCORES_COMPLETE.json missing")
    man = json.loads(path.read_text(encoding="utf-8"))
    if not man.get("complete"):
        raise HarnessProtocolError("ANALYSIS BLOCKED: ALL_SCORES_COMPLETE incomplete")
    if int(man.get("n_models", 0)) != 18:
        raise HarnessProtocolError("ANALYSIS BLOCKED: ALL_SCORES_COMPLETE does not list 18 models")
    return man


def probability_extras(y: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import brier_score_loss, log_loss

    y = np.asarray(y).astype(int)
    p = np.clip(np.asarray(scores, dtype=np.float64), 1e-15, 1.0 - 1e-15)
    return {
        "Brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
    }


def assert_output_dir_ready(out_dir: Path) -> None:
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise HarnessProtocolError(
            f"ONE-PASS: output directory is not empty: {out_dir}"
        )
    started = out_dir / "EXECUTION_STARTED.json"
    if started.is_file():
        raise HarnessProtocolError("ONE-PASS: EXECUTION_STARTED.json already exists; abort")


def write_execution_started(
    out_dir: Path,
    *,
    authorisation_sha256: str,
    external_runner_sha256: str,
    final_release_manifest_sha256: str,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "EXECUTION_STARTED.json"
    if path.is_file():
        raise HarnessProtocolError("ONE-PASS: EXECUTION_STARTED.json already exists; abort")
    payload = {
        "task_id": TASK_ID_FUTURE,
        "authorisation_sha256": authorisation_sha256,
        "external_runner_sha256": external_runner_sha256,
        "final_release_manifest_sha256": final_release_manifest_sha256,
        "start_timestamp": utc_now(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def validate_additional_release_bindings(
    auth: dict[str, Any],
    *,
    runner_sha256: str,
) -> None:
    missing = [k for k in ADDITIONAL_AUTH_FIELDS if k not in auth]
    if missing:
        raise HarnessProtocolError(f"EXTERNAL GATE: missing additional fields {missing}")
    if auth.get("external_runner_sha256") != runner_sha256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong external_runner_sha256")
    if auth.get("harness_runner_sha256") != HARNESS_RUNNER_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong harness_runner_sha256")
    if auth.get("editor006c_release_commit") != EDITOR006C_RELEASE_COMMIT:
        raise HarnessProtocolError("EXTERNAL GATE: wrong editor006c_release_commit")
    if auth.get("sequence_order_sha256") != SEQUENCE_ORDER_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong sequence_order_sha256")
    if auth.get("scaler_sha256") != SCALER_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong scaler_sha256")


def verify_frozen_identities(
    *,
    final_manifest_path: Path,
    freeze_dir: Path,
) -> dict[str, Any]:
    man_sha = sha256_file(final_manifest_path)
    if man_sha != FINAL_RELEASE_MANIFEST_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong final release manifest SHA-256")
    harness_sha = hash_harness_sources()
    if harness_sha != HARNESS_CODE_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong harness_code_sha256 (live sources)")
    runner_sha = sha256_file(HARNESS_RUNNER_PATH)
    if runner_sha != HARNESS_RUNNER_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: wrong harness_runner_sha256 (live file)")
    freeze = load_freeze_bundle(freeze_dir)
    validated = validate_contracts(freeze)
    if freeze["_file_sha256"]["EDITOR006A_MODEL_ALLOWLIST.json"] != MODEL_ALLOWLIST_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: allow-list file SHA drift")
    if freeze["_file_sha256"]["EDITOR006A_SCALER.json"] != SCALER_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: scaler file SHA drift")
    contract_hash = __import__("hashlib").sha256(
        json.dumps(
            {k: freeze["_file_sha256"][k] for k in (
                "EDITOR006A_MODEL_ALLOWLIST.json",
                "EDITOR006A_C5_DENYLIST.json",
                "EDITOR006A_THRESHOLDS.json",
                "EDITOR006A_SCALER.json",
                "EDITOR006A_R62_LABEL_CONTRACT.json",
                "EDITOR006A_INPUT_CONTRACT.json",
                "EDITOR006A_DATA_QUALITY_CAVEATS.json",
            )},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if contract_hash != CONTRACT_BUNDLE_SHA256:
        raise HarnessProtocolError("EXTERNAL GATE: contract_bundle_sha256 drift")
    c2_62 = next(
        t for t in validated["thresholds"] if t["family"] == "C2" and int(t["seed"]) == 62
    )
    if float(c2_62["threshold"]) != C2_SEED62_THRESHOLD:
        raise HarnessProtocolError("EXTERNAL GATE: C2 seed 62 threshold drift")
    ancestor_proc = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", EDITOR006C_RELEASE_COMMIT, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestor_proc.returncode != 0:
        raise HarnessProtocolError("EXTERNAL GATE: EDITOR-006C release commit is not an ancestor of HEAD")
    return {
        "final_release_manifest_sha256": man_sha,
        "harness_code_sha256": harness_sha,
        "harness_runner_sha256": runner_sha,
        "contract_bundle_sha256": contract_hash,
        "model_allowlist_sha256": MODEL_ALLOWLIST_SHA256,
        "scaler_sha256": SCALER_SHA256,
        "validated": validated,
        "freeze": freeze,
        "editor006c_release_commit_is_ancestor": True,
    }


def run_pre_bundle_gates(
    *,
    auth_path: Path,
    output_dir: Path,
    final_manifest_path: Path,
    freeze_dir: Path | None = None,
    bundle_dir: Path | None = None,
) -> dict[str, Any]:
    """Steps 1–12. Never opens r6.2 .npy components."""
    opened_npy: list[str] = []
    runner_sha = compute_external_runner_sha256()
    auth_path = Path(auth_path)
    if not auth_path.is_file():
        raise HarnessProtocolError("EXTERNAL GATE: authorisation file not found")
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    if auth.get("task_id") != TASK_ID_FUTURE:
        raise HarnessProtocolError(
            f"EXTERNAL GATE: wrong task_id {auth.get('task_id')!r} expected {TASK_ID_FUTURE!r}"
        )
    if auth.get("dataset_id") != DATASET_ID:
        raise HarnessProtocolError(
            f"EXTERNAL GATE: wrong dataset_id {auth.get('dataset_id')!r} expected {DATASET_ID!r}"
        )
    validate_external_authorization(
        auth_path,
        expected_task_id=TASK_ID_FUTURE,
        expected_dataset_id=DATASET_ID,
        expected_input_bundle_manifest_sha256=FINAL_RELEASE_MANIFEST_SHA256,
        expected_contract_bundle_sha256=CONTRACT_BUNDLE_SHA256,
        expected_harness_code_sha256=HARNESS_CODE_SHA256,
        expected_model_allowlist_sha256=MODEL_ALLOWLIST_SHA256,
    )
    validate_additional_release_bindings(auth, runner_sha256=runner_sha)
    identities = verify_frozen_identities(
        final_manifest_path=Path(final_manifest_path),
        freeze_dir=Path(freeze_dir) if freeze_dir is not None else FREEZE_DIR,
    )
    source_preflight = producing_source_preflight()
    artefacts = identities["validated"]["artefacts"]
    deny_hashes = set(identities["validated"]["deny_hashes"])
    model_preflight = preflight_all_eighteen(artefacts, deny_hashes)
    assert_output_dir_ready(Path(output_dir))
    if bundle_dir is not None:
        refuse_r62_without_auth(bundle_dir, authorised=True)
        refuse_r52_test(bundle_dir)
    if opened_npy:
        raise HarnessProtocolError("PROTOCOL: npy opened during pre-bundle gates")
    return {
        "status": "PRE_BUNDLE_GATES_PASS",
        "bundle_opened": False,
        "npy_opened": opened_npy,
        "models_deserialised": False,
        "runner_sha256": runner_sha,
        "authorisation_sha256": sha256_file(auth_path),
        "source_preflight": source_preflight,
        "model_preflight": model_preflight,
        "identities": {k: v for k, v in identities.items() if k not in {"validated", "freeze"}},
        "artefacts": artefacts,
        "deny_hashes": sorted(deny_hashes),
        "thresholds": identities["validated"]["thresholds"],
        "auth": auth,
    }


def open_external_bundle(bundle_dir: Path, *, authorised: bool) -> dict[str, Any]:
    if not authorised:
        raise HarnessProtocolError("EXTERNAL GATE: refusing to open bundle without authorisation")
    bundle_dir = Path(bundle_dir)
    refuse_r62_without_auth(bundle_dir, authorised=True)
    refuse_r52_test(bundle_dir)
    missing = [name for name in REQUIRED_BUNDLE_FILES if not (bundle_dir / name).is_file()]
    if missing:
        raise HarnessProtocolError(f"EXTERNAL BUNDLE: missing {missing}")
    dense = np.load(bundle_dir / "scaled_dense_daily.npy", mmap_mode="r")
    window_index = np.load(bundle_dir / "window_index.npy", mmap_mode="r")
    completed = np.load(bundle_dir / "completed_window_labels.npy", mmap_mode="r")
    endpoint = np.load(bundle_dir / "endpoint_labels.npy", mmap_mode="r")
    deov = np.load(bundle_dir / "deoverlap_offset0_mask.npy", mmap_mode="r")
    user_ids = np.load(bundle_dir / "user_ids.npy", mmap_mode="r")
    calendar = np.load(bundle_dir / "calendar_dates.npy", mmap_mode="r")
    official_flags = np.load(bundle_dir / "official_insider_flags.npy", mmap_mode="r")
    official_incidents = np.load(bundle_dir / "official_incident_codes.npy", mmap_mode="r")
    window_bits = np.load(bundle_dir / "window_scenario_bitmask.npy", mmap_mode="r")
    endpoint_bits = np.load(bundle_dir / "endpoint_scenario_bitmask.npy", mmap_mode="r")
    return {
        "dense": dense,
        "window_index": window_index,
        "completed": completed,
        "endpoint": endpoint,
        "deov": deov,
        "user_ids": user_ids,
        "calendar": calendar,
        "official_flags": official_flags,
        "official_incidents": official_incidents,
        "window_bits": window_bits,
        "endpoint_bits": endpoint_bits,
    }


def validate_bundle_geometry(bundle: dict[str, Any]) -> None:
    dense = bundle["dense"]
    if dense.shape != (N_USERS, N_DAYS, N_FEATURES) or dense.dtype != np.float32:
        raise HarnessProtocolError(f"Bad dense shape/dtype {dense.shape} {dense.dtype}")
    wi = np.asarray(bundle["window_index"])
    if wi.shape != (N_WINDOWS, 2):
        raise HarnessProtocolError(f"Bad window_index shape {wi.shape}")
    if not np.all(np.diff(wi[:, 0]) >= 0):
        raise HarnessProtocolError("window_index users are not non-decreasing")
    if int(bundle["completed"].shape[0]) != N_WINDOWS:
        raise HarnessProtocolError("completed_window_labels length mismatch")
    if int(bundle["endpoint"].shape[0]) != N_WINDOWS:
        raise HarnessProtocolError("endpoint_labels length mismatch")
    if int(np.asarray(bundle["deov"]).sum()) != N_DEOVERLAP:
        raise HarnessProtocolError("de-overlap retained count mismatch")
    if int(bundle["user_ids"].shape[0]) != N_USERS:
        raise HarnessProtocolError("user_ids length mismatch")
    if int(bundle["calendar"].shape[0]) != N_DAYS:
        raise HarnessProtocolError("calendar_dates length mismatch")
    ui = np.asarray(wi[:, 0])
    si = np.asarray(wi[:, 1])
    expected_ui = np.repeat(np.arange(N_USERS, dtype=wi.dtype), N_STARTS)
    expected_si = np.tile(np.arange(N_STARTS, dtype=wi.dtype), N_USERS)
    if not np.array_equal(ui, expected_ui) or not np.array_equal(si, expected_si):
        raise HarnessProtocolError("window_index order is not user-then-start ascending")


def write_all_scores_complete(out_dir: Path, score_manifest: dict[str, Any]) -> Path:
    records = []
    for rec in score_manifest["scores"]:
        records.append(
            {
                "family": rec["family"],
                "seed": rec["seed"],
                "checkpoint_sha256": rec["model_sha256"],
                "source_code_sha_status": "preflight_PASS",
                "threshold": rec["threshold"],
                "score_filename": Path(rec["path"]).name,
                "score_count": rec["n"],
                "score_sha256": rec["sha256"],
            }
        )
    payload = {
        "complete": True,
        "n_models": 18,
        "n_sequences": score_manifest["n_sequences"],
        "scoring_mode": "streaming_batchwise",
        "models": records,
        "created_utc": utc_now(),
    }
    path = Path(out_dir) / "ALL_SCORES_COMPLETE.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def analyse_predeclared_views(
    *,
    out_dir: Path,
    completed: np.ndarray,
    endpoint: np.ndarray,
    deov: np.ndarray,
    user_ids_by_window: np.ndarray,
    thresholds: list[dict[str, Any]],
) -> dict[str, Any]:
    man = require_all_scores_complete(out_dir)
    y_c = np.asarray(completed)
    y_e = np.asarray(endpoint)
    mask = np.asarray(deov).astype(bool)
    if y_c.shape[0] != N_WINDOWS or y_e.shape[0] != N_WINDOWS:
        raise HarnessProtocolError("Analysis label length mismatch")
    if int(mask.sum()) != N_DEOVERLAP:
        raise HarnessProtocolError("Analysis de-overlap count mismatch")
    by_family: dict[str, Any] = {}
    score_dir = Path(out_dir) / "raw_scores"
    for rec in man["models"]:
        family, seed = rec["family"], int(rec["seed"])
        scores = np.load(score_dir / rec["score_filename"])
        thr = float(rec["threshold"])
        views = {
            "COMPLETED_WINDOW": {
                **metrics_at_frozen_threshold(y_c, scores, thr),
                **probability_extras(y_c, scores),
            },
            "ENDPOINT_PAST_ONLY": {
                **metrics_at_frozen_threshold(y_e, scores, thr),
                **probability_extras(y_e, scores),
                "interpretation": "endpoint-defined past-only evaluation",
                "never": ["real-time", "streaming", "intra-day"],
            },
            "DEOVERLAP_OFFSET0": {
                **metrics_at_frozen_threshold(y_c[mask], scores[mask], thr),
                **probability_extras(y_c[mask], scores[mask]),
                "n_retained": int(mask.sum()),
            },
        }
        by_family.setdefault(family, {})[seed] = views
    primary: dict[str, Any] = {}
    for seed in SEEDS:
        c2 = by_family["C2"][seed]
        c5 = by_family["C5_original_paper"][seed]
        seed_block = {}
        for view in ("COMPLETED_WINDOW", "ENDPOINT_PAST_ONLY", "DEOVERLAP_OFFSET0"):
            seed_block[view] = {
                "C2_PR_AUC": c2[view]["PR_AUC"],
                "C5_PR_AUC": c5[view]["PR_AUC"],
                "delta_PR_AUC_C5_minus_C2": c5[view]["PR_AUC"] - c2[view]["PR_AUC"],
                "C2_F1": c2[view]["F1"],
                "C5_F1": c5[view]["F1"],
                "delta_F1_C5_minus_C2": c5[view]["F1"] - c2[view]["F1"],
                "positive_delta_is_not_automatic_superiority": True,
            }
        primary[seed] = seed_block
    thr_c2 = {int(t["seed"]): float(t["threshold"]) for t in thresholds if t["family"] == "C2"}
    thr_c5 = {
        int(t["seed"]): float(t["threshold"])
        for t in thresholds
        if t["family"] == "C5_original_paper"
    }
    bootstrap = {}
    for seed in SEEDS:
        s2 = np.load(score_dir / f"c2_seed{seed}.npy")[mask]
        s5 = np.load(score_dir / f"c5_seed{seed}.npy")[mask]
        bootstrap[seed] = paired_user_cluster_bootstrap(
            user_ids=np.asarray(user_ids_by_window)[mask],
            y=y_c[mask],
            scores_c2=s2,
            scores_c5=s5,
            threshold_c2=thr_c2[seed],
            threshold_c5=thr_c5[seed],
            n_valid=BOOTSTRAP_VALID_RESAMPLES,
            seed=BOOTSTRAP_SEED,
        )
    return {
        "by_family_seed": by_family,
        "primary_c5_vs_c2": primary,
        "deoverlap_user_cluster_bootstrap": bootstrap,
        "views": PREDECLARED_VIEWS,
        "no_model_ranking_as_selection": True,
        "forbidden_claims": list(FORBIDDEN_CLAIMS),
        "effective_malicious_cluster_count": 5,
        "frozen_wording": "Five official insider–incident clusters are represented.",
    }


def mechanism_on_deoverlap(
    *,
    loaded_by_key: dict[tuple[str, int], Any],
    dense: np.ndarray,
    window_index: np.ndarray,
    deov: np.ndarray,
    batch_size: int = BATCH_SIZE_FROZEN,
) -> dict[str, Any]:
    registry = mechanism_registry()
    disabled = [m["metric_name"] for m in registry["metrics"] if m["status"] == STATUS_DISABLED]
    if "unused_leaf_fraction" not in disabled or "tree_contribution_rho" not in disabled:
        raise HarnessProtocolError("Disabled mechanism metrics are not disabled")
    mask = np.asarray(deov).astype(bool)
    ui = np.asarray(window_index[:, 0])[mask]
    si = np.asarray(window_index[:, 1])[mask]
    provider = DenseDailyWindowProvider(dense, ui, si, batch_size=batch_size)
    # Gather only de-overlap windows batchwise; never (N,20,13) of the full cohort.
    chunks = []
    for _lo, _hi, batch in provider:
        chunks.append(np.asarray(batch, dtype=np.float32))
    x = np.concatenate(chunks, axis=0)
    provider.assert_never_full_sequence_tensor()
    per_seed = {}
    for seed in SEEDS:
        teacher = loaded_by_key[("teacher_frozen_odst", seed)]
        c2 = loaded_by_key[("C2", seed)]
        c5 = loaded_by_key[("C5_original_paper", seed)]
        per_seed[int(seed)] = {
            "C2_vs_teacher": compare_student_teacher(student=c2, teacher=teacher, x=x),
            "C5_vs_teacher": compare_student_teacher(student=c5, teacher=teacher, x=x),
        }
        for block in per_seed[int(seed)].values():
            if block.get("unused_leaf_fraction") != "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE":
                raise HarnessProtocolError("unused-leaf must remain disabled")
            if block.get("tree_contribution_rho") != "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE":
                raise HarnessProtocolError("tree-contribution rho must remain disabled")
    return {
        "view": "DEOVERLAP_OFFSET0",
        "registry": registry,
        "paper_facing": paper_facing_mechanism_names(),
        "per_seed": per_seed,
        "no_c5_must_improve": True,
    }


def execute_external_one_pass(
    *,
    auth_path: Path,
    output_dir: Path,
    bundle_dir: Path,
    final_manifest_path: Path,
    freeze_dir: Path | None = None,
    open_bundle_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Full one-pass. Requires a true authorisation. EDITOR-006D must not call this
    against CERT r6.2 because no true authorisation exists."""
    gates = run_pre_bundle_gates(
        auth_path=auth_path,
        output_dir=output_dir,
        final_manifest_path=final_manifest_path,
        freeze_dir=freeze_dir,
        bundle_dir=bundle_dir,
    )
    if gates["auth"].get("predictive_external_run_authorised") is not True:
        raise HarnessProtocolError("EXTERNAL GATE: predictive_external_run_authorised is not true")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    opener = open_bundle_fn if open_bundle_fn is not None else open_external_bundle
    bundle = opener(Path(bundle_dir), authorised=True)
    validate_bundle_geometry(bundle)
    write_execution_started(
        out_dir,
        authorisation_sha256=gates["authorisation_sha256"],
        external_runner_sha256=gates["runner_sha256"],
        final_release_manifest_sha256=FINAL_RELEASE_MANIFEST_SHA256,
    )
    ui = np.asarray(bundle["window_index"][:, 0])
    si = np.asarray(bundle["window_index"][:, 1])
    provider = DenseDailyWindowProvider(
        bundle["dense"], ui, si, batch_size=BATCH_SIZE_FROZEN
    )
    print("streaming 18-model score phase started", flush=True)
    score_man = write_scores_phase_streaming(
        artefacts=gates["artefacts"],
        deny_hashes=set(gates["deny_hashes"]),
        provider=provider,
        out_dir=out_dir,
        identifiers_sha256=SEQUENCE_ORDER_SHA256,
        input_bundle_sha256=FINAL_RELEASE_MANIFEST_SHA256,
        thresholds=gates["thresholds"],
        batch_size=BATCH_SIZE_FROZEN,
    )
    print("model 18/18 completed", flush=True)
    write_all_scores_complete(out_dir, score_man)
    user_ids = np.asarray(bundle["user_ids"])
    user_ids_by_window = user_ids[ui.astype(int)]
    analysis = analyse_predeclared_views(
        out_dir=out_dir,
        completed=np.asarray(bundle["completed"]),
        endpoint=np.asarray(bundle["endpoint"]),
        deov=np.asarray(bundle["deov"]),
        user_ids_by_window=user_ids_by_window,
        thresholds=gates["thresholds"],
    )
    return {
        "status": "EXTERNAL_ONE_PASS_COMPLETE",
        "score_manifest": score_man,
        "analysis": analysis,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_editor006e_r62_one_pass")
    parser.add_argument(
        "--mode",
        choices=("external", "identity-preflight", "engineering-synthetic"),
        default="identity-preflight",
    )
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--bundle-dir", type=Path, default=BUNDLE_DIR_DEFAULT)
    parser.add_argument("--final-release-manifest", type=Path, default=FINAL_MANIFEST_DEFAULT)
    parser.add_argument("--freeze-dir", type=Path, default=FREEZE_DIR)
    parser.add_argument(
        "--execute-external",
        action="store_true",
        help="Required together with a true authorisation to open the r6.2 bundle and score.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if path_looks_like_r52_test(args.bundle_dir):
            raise HarnessProtocolError("REFUSED: r5.2 TEST path")
        if args.mode == "engineering-synthetic":
            raise HarnessProtocolError(
                "engineering-synthetic is test-only via pytest imports; CLI refuses this mode"
            )
        if args.mode == "external" and not args.execute_external:
            raise HarnessProtocolError(
                "EXTERNAL: --execute-external is required for the scoring path; "
                "EDITOR-006D must not score CERT r6.2"
            )
        if args.mode == "identity-preflight":
            run_pre_bundle_gates(
                auth_path=args.authorization,
                output_dir=args.output_dir,
                final_manifest_path=args.final_release_manifest,
                freeze_dir=args.freeze_dir,
                bundle_dir=None,
            )
            print("EDITOR006E_PRE_BUNDLE_GATES_PASS")
            print("R62_BUNDLE_OPENED_FOR_INFERENCE = NO")
            print("R62_PREDICTIVE_INFERENCE_EXECUTED = NO")
            return 0
        execute_external_one_pass(
            auth_path=args.authorization,
            output_dir=args.output_dir,
            bundle_dir=args.bundle_dir,
            final_manifest_path=args.final_release_manifest,
            freeze_dir=args.freeze_dir,
        )
        print("EDITOR006E_EXTERNAL_ONE_PASS_COMPLETE")
        return 0
    except HarnessProtocolError as exc:
        print("EDITOR006E_EXTERNAL_RUN_ABORTED")
        print(exc)
        print("R62_BUNDLE_OPENED_FOR_INFERENCE = NO")
        print("R62_PREDICTIVE_INFERENCE_EXECUTED = NO")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
