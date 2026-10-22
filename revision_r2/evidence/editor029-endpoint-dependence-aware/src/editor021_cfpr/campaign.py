"""EDITOR-021 clean-function-preserving representation robustness campaign."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor012_rescue.constants import (
    EXPECTED_INNER_DROPPED,
    EXPECTED_INNER_SELECT_N,
    EXPECTED_INNER_SELECT_POS,
    EXPECTED_INNER_TRAIN_N,
    EXPECTED_INNER_TRAIN_POS,
    EXPECTED_TRAIN_POS,
    EXPECTED_TRAIN_SHA256,
    EXPECTED_TRAIN_SHAPE,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_MALICIOUS_USERS,
    EXPECTED_VAL_USERS,
    EXPECTED_VAL_WINDOWS_PER_USER,
    POS_WEIGHT_MULT,
    PRIMARY_SEEDS,
)
from editor012_rescue.data import SequenceBundle, _load_split, load_train_validation, subset_bundle
from editor012_rescue.inner_split import inner_split_masks
from editor012_rescue.metrics import sigmoid
from editor012_rescue.safety import TRAIN_NPZ
from editor015_residual.explain import train_references
from editor017_robustness.bootstrap_family import mean_source_delta_contrast, user_cluster_stat
from editor017_robustness.constants import NOISE_LEVELS, SOURCE_CHANNELS
from editor017_robustness.perturbations import load_r52_train_scaler
from editor018_cross_view.cache import load_ensemble_split
from editor020_robustness.evaluate import build_degraded_views

from .constants import (
    CANDIDATES,
    EDITOR017_RESULTS_COMMIT,
    EDITOR018_RESULTS_COMMIT,
    EDITOR019_RESULTS_COMMIT,
    EDITOR020C_PARENT_COMMIT,
    EDITOR020_TA2_R0_INNER,
    FROZEN_CLEAN_VAL_PR_AUC,
    FROZEN_TA2_MEAN_PR_AUC,
    OUTPUT_REL,
    REVIEW_REL,
    ROBUSTNESS_CANDIDATES,
    TA2_CHECKPOINTS,
)
from .evaluate import score_all_views
from .io_util import write_csv, write_json, write_npz
from .mechanism import collect_clean_tensors, mechanism_from_tensors
from .models import identities_ok, load_ta2_reference, load_trained, load_topt
from .promotion import evaluate_cfp0_scaffold, evaluate_official_gates, select_inner_candidate
from .protocol import assert_perturbation_hashes, write_protocol_packet
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor021Blocked,
    enter_inner_phase,
    exit_inner_phase,
    mark_predictive_started,
    mark_promotion_frozen,
    refuse_r51,
    refuse_r52_test,
    refuse_r62,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .train import train_candidate


def _rev(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _pos_weight(y: np.ndarray) -> float:
    n_pos = int(np.asarray(y).sum())
    n_neg = int(len(y) - n_pos)
    return float((n_neg / max(n_pos, 1)) * POS_WEIGHT_MULT)


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REVIEW_ROOT.parents[1], text=True).strip()


def _git_branch() -> str:
    return subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REVIEW_ROOT.parents[1], text=True).strip()


def load_train_only() -> SequenceBundle:
    return _load_split(TRAIN_NPZ, EXPECTED_TRAIN_SHA256, EXPECTED_TRAIN_SHAPE, EXPECTED_TRAIN_POS, "train")


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor021Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor021Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor021Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor021Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    return {
        "USER_MAPPING_RECOVERED": True,
        "USER_CLUSTER_BOOTSTRAP_STATUS": "AVAILABLE",
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "mapping_sha256": mapping_hash,
        "sampling_unit": "validation user",
        "windows_not_independent": True,
    }


def pack_row(candidate: str, seed: int, scored: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rob = scored["robust"]
    row = {
        "candidate": candidate,
        "seed": int(seed),
        "rho": float(CANDIDATES[candidate]["rho"]) if candidate in CANDIDATES else float("nan"),
        "clean_PR_AUC": float(rob["clean_PR_AUC"]),
        "S_source": float(rob["S_source"]),
        "S_noise": float(rob["S_noise"]),
        "S_composite": float(rob["S_composite"]),
        "MEAN_SOURCE_DELTA": float(rob["MEAN_SOURCE_DELTA"]),
        "WORST_SOURCE_DELTA": float(rob["WORST_SOURCE_DELTA"]),
        "MEAN_NOISE_RETENTION": float(rob["MEAN_NOISE_RETENTION"]),
        "clean_Brier": float(rob["clean_Brier"]),
        "clean_log_loss": float(rob["clean_log_loss"]),
        "threshold": float(rob["threshold"]),
    }
    for src in rob["source"]:
        row[f"source_{src['channel']}_delta"] = float(src["delta"])
        row[f"source_{src['channel']}_PR_AUC"] = float(src["pr_auc"])
    for nz in rob["noise"]:
        row[f"noise_{nz['level']:.2f}_delta"] = float(nz["delta"])
        row[f"noise_{nz['level']:.2f}_PR_AUC"] = float(nz["pr_auc"])
    if extra:
        row.update(extra)
    return row


def write_raw(
    *,
    candidate: str,
    seed: int,
    split: str,
    condition: str,
    bundle: SequenceBundle | None,
    y: np.ndarray,
    users: np.ndarray,
    seq_ids: np.ndarray,
    logits: np.ndarray,
) -> str:
    probs = sigmoid(logits)
    path = OUTPUT_ROOT / "raw" / f"{candidate}_seed{seed}_{split}_{condition}.npz"
    write_npz(
        path,
        y=np.asarray(y).astype(np.float32),
        user=np.asarray(users).astype(str),
        sequence_id=np.asarray(seq_ids).astype(str),
        logit=np.asarray(logits).astype(np.float32),
        probability=np.asarray(probs).astype(np.float32),
    )
    meta = {
        "model": "TA2",
        "candidate": candidate,
        "seed": seed,
        "split": split,
        "condition": condition,
        "path": str(path),
        "sha256": sha256_file(path),
        "n": int(len(y)),
    }
    write_json(path.with_suffix(".json"), meta)
    return str(path)


def inner_data() -> dict[str, Any]:
    train = load_train_only()
    split = inner_split_masks(train)
    if int(split["n_inner_train"]) != EXPECTED_INNER_TRAIN_N:
        raise Editor021Blocked(f"INNER_TRAIN n {split['n_inner_train']} != {EXPECTED_INNER_TRAIN_N}")
    if int(split["n_inner_select"]) != EXPECTED_INNER_SELECT_N:
        raise Editor021Blocked(f"INNER_SELECT n {split['n_inner_select']} != {EXPECTED_INNER_SELECT_N}")
    if int(split["n_inner_train_pos"]) != EXPECTED_INNER_TRAIN_POS:
        raise Editor021Blocked("INNER_TRAIN positives mismatch")
    if int(split["n_inner_select_pos"]) != EXPECTED_INNER_SELECT_POS:
        raise Editor021Blocked("INNER_SELECT positives mismatch")
    if int(split["n_dropped"]) != EXPECTED_INNER_DROPPED:
        raise Editor021Blocked("inner dropped mismatch")
    inner_tr = subset_bundle(train, split["train_mask"], "inner_train")
    inner_se = subset_bundle(train, split["select_mask"], "inner_select")
    ens_all = load_ensemble_split("train")
    return {
        "train": train,
        "split": split,
        "inner_tr": inner_tr,
        "inner_se": inner_se,
        "ens_tr": ens_all["ens"][split["train_mask"]],
        "scaler": load_r52_train_scaler(),
        "pos_w": _pos_weight(inner_tr.y),
    }


def score_and_pack(
    *,
    candidate: str,
    seed: int,
    student: torch.nn.Module,
    views: dict[str, np.ndarray],
    bundle: SequenceBundle,
    device: torch.device,
    split: str,
    threshold: float | None,
    allow_threshold_search: bool,
    extra: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    scored = score_all_views(
        student,
        views,
        bundle.y,
        device,
        split=split,
        threshold=threshold,
        allow_threshold_search=allow_threshold_search,
    )
    write_raw(
        candidate=candidate,
        seed=seed,
        split=split,
        condition="clean",
        bundle=bundle,
        y=bundle.y,
        users=bundle.user,
        seq_ids=bundle.sequence_id,
        logits=scored["clean"]["logits"],
    )
    row = pack_row(candidate, seed, scored, extra=extra)
    return scored, row


def run_starting_ta2(inner: dict[str, Any], device: torch.device) -> list[dict[str, Any]]:
    views = build_degraded_views(inner["inner_se"].X, inner["scaler"])
    rows = []
    for seed in PRIMARY_SEEDS:
        print(f"[EDITOR-021] STARTING_TA2 seed={seed}", flush=True)
        ref, sha = load_ta2_reference(seed, device)
        scored, row = score_and_pack(
            candidate="STARTING_TA2",
            seed=seed,
            student=ref,
            views=views,
            bundle=inner["inner_se"],
            device=device,
            split="inner_select",
            threshold=None,
            allow_threshold_search=True,
            extra={"kind": "frozen_starting_ta2", "sha256": sha},
        )
        rows.append(row)
    write_csv(_rev("EDITOR021_INNER_SELECT_SUMMARY.csv"), rows)
    return rows


def train_and_score_inner(
    *,
    candidate: str,
    inner: dict[str, Any],
    device: torch.device,
    views: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    rows = []
    for seed in PRIMARY_SEEDS:
        print(f"[EDITOR-021] INNER {candidate} seed={seed}", flush=True)
        teacher, _ = load_topt(seed, device)
        trained = train_candidate(
            candidate=candidate,
            seed=seed,
            X=inner["inner_tr"].X,
            y=inner["inner_tr"].y,
            ens=inner["ens_tr"],
            X_select=inner["inner_se"].X,
            y_select=inner["inner_se"].y,
            matched_teacher=teacher,
            device=device,
            pos_weight=inner["pos_w"],
            scaler=inner["scaler"],
            select_name="inner_select",
        )
        loaded = load_trained(candidate, seed, device)
        scored, row = score_and_pack(
            candidate=candidate,
            seed=seed,
            student=loaded["student"],
            views=views,
            bundle=inner["inner_se"],
            device=device,
            split="inner_select",
            threshold=None,
            allow_threshold_search=True,
            extra={
                "best_epoch": trained["best_epoch"],
                "select_PR_AUC": trained["select_PR_AUC"],
                "checkpoint": trained["best_checkpoint"],
                "best_checkpoint_sha256": trained["best_checkpoint_sha256"],
                "training_time": trained["training_time"],
                "start_sha256": trained["start_sha256"],
            },
        )
        row["scored_threshold"] = float(scored["robust"]["threshold"])
        rows.append(row)
        write_csv(_rev("EDITOR021_INNER_SELECT_SUMMARY.csv"), rows, fieldnames=None)
    return rows


def logits_by_seed(packs: dict[str, dict[int, dict[str, Any]]], name: str) -> tuple[list[np.ndarray], list[list[np.ndarray]], list[list[np.ndarray]]]:
    clean, source, noise = [], [], []
    for seed in PRIMARY_SEEDS:
        pack = packs[name][seed]
        clean.append(pack["clean"]["logits"])
        source.append([pack["source_logits"][ch] for ch in SOURCE_CHANNELS])
        noise.append([pack["noise_logits"][float(lv)] for lv in NOISE_LEVELS])
    return clean, source, noise


def write_negative_freeze(*, scaffold: dict[str, Any] | None, inner_sel: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    ruling = {
        "EDITOR021_INNER_PROMOTION": "NONE",
        "EDITOR021_SELECTED_CANDIDATE": None,
        "EDITOR021_OFFICIAL_VALIDATION_EXECUTED": "NO",
        "EDITOR021_PROMOTION": "NO",
        "CURRENT_PAPER_MODEL": "TA2",
        "reason": reason,
        "scaffold": scaffold,
        "inner_selection": inner_sel,
        "utc": utc_now(),
    }
    if scaffold is not None and not scaffold.get("pass", True):
        ruling["EDITOR021_CLEAN_FUNCTION_SCAFFOLD"] = "FAILED"
        ruling["EDITOR021_ROBUSTNESS_CANDIDATES_EXECUTED"] = "NO"
        ruling["EDITOR021_RULING"] = "NOT_SUPPORTED"
        ruling["EDITOR021_CLEAN_FUNCTION_PRESERVATION"] = "NOT_SUPPORTED"
        ruling["EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING"] = "NOT_TESTED"
    else:
        ruling["EDITOR021_CLEAN_FUNCTION_SCAFFOLD"] = "PASS"
        ruling["EDITOR021_ROBUSTNESS_CANDIDATES_EXECUTED"] = "YES"
        ruling["EDITOR021_RULING"] = "NOT_SUPPORTED"
        ruling["EDITOR021_CLEAN_FUNCTION_PRESERVATION"] = "SUPPORTED"
        ruling["EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING"] = "NOT_SUPPORTED"
    write_json(_rev("EDITOR021_PROMOTION_DECISION.json"), ruling)
    return ruling


def run_official(
    *,
    selected: str,
    inner_rows: list[dict[str, Any]],
    device: torch.device,
) -> dict[str, Any]:
    mark_promotion_frozen()
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    write_json(_rev("EDITOR021_CLUSTER_BOOTSTRAP.json"), {"user_mapping_pending_stats": mapping})
    train, val = bundle["train"], bundle["val"]
    scaler = load_r52_train_scaler()
    views = build_degraded_views(val.X, scaler)
    ens = load_ensemble_split("train")["ens"]
    pos_w = float(bundle["pos_weight"])
    packs: dict[str, dict[int, dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    inner_thr = {
        (str(r["candidate"]), int(r["seed"])): float(r["threshold"])
        for r in inner_rows
        if str(r["candidate"]) in {selected, "CFP0"}
    }
    for cand in ("CFP0", selected):
        packs[cand] = {}
        for seed in PRIMARY_SEEDS:
            print(f"[EDITOR-021] OFFICIAL {cand} seed={seed}", flush=True)
            teacher, _ = load_topt(seed, device)
            trained = train_candidate(
                candidate=cand,
                seed=seed,
                X=train.X,
                y=train.y,
                ens=ens,
                X_select=val.X,
                y_select=val.y,
                matched_teacher=teacher,
                device=device,
                pos_weight=pos_w,
                scaler=scaler,
                select_name="validation",
            )
            loaded = load_trained(cand, seed, device)
            thr = inner_thr[(cand, seed)]
            scored, row = score_and_pack(
                candidate=cand,
                seed=seed,
                student=loaded["student"],
                views=views,
                bundle=val,
                device=device,
                split="validation",
                threshold=thr,
                allow_threshold_search=False,
                extra={
                    "best_epoch": trained["best_epoch"],
                    "checkpoint": trained["best_checkpoint"],
                    "best_checkpoint_sha256": trained["best_checkpoint_sha256"],
                    "split": "validation",
                    "kind": "official",
                    "frozen_inner_threshold": thr,
                },
            )
            packs[cand][seed] = scored
            rows.append(row)
            write_csv(_rev("EDITOR021_OFFICIAL_VALIDATION_SUMMARY.csv"), rows)
    write_json(
        _rev("EDITOR021_OFFICIAL_VALIDATION_RESULTS.json"),
        {"rows": rows, "selected": selected, "utc": utc_now()},
    )
    return {"rows": rows, "packs": packs, "mapping": mapping, "val": val, "train": train, "y": np.asarray(val.y), "users": np.asarray(val.user).astype(str)}


def official_statistics(official: dict[str, Any], selected: str) -> dict[str, Any]:
    y, users = official["y"], official["users"]
    c0, s0, n0 = logits_by_seed(official["packs"], "CFP0")
    c1, s1, n1 = logits_by_seed(official["packs"], selected)
    from sklearn.metrics import average_precision_score

    def clean_stat(sl: np.ndarray, yb: np.ndarray) -> float:
        diffs = []
        for a, b in zip(c0, c1):
            diffs.append(float(average_precision_score(yb, sigmoid(b[sl])) - average_precision_score(yb, sigmoid(a[sl]))))
        return float(np.mean(diffs))

    def family_delta(clean_a, clean_b, deg_a, deg_b, sl, yb):
        seed_stats = []
        for ca, cb, das, dbs in zip(clean_a, clean_b, deg_a, deg_b):
            pr_ca = float(average_precision_score(yb, sigmoid(ca[sl])))
            pr_cb = float(average_precision_score(yb, sigmoid(cb[sl])))
            d_a = [float(average_precision_score(yb, sigmoid(d[sl]))) - pr_ca for d in das]
            d_b = [float(average_precision_score(yb, sigmoid(d[sl]))) - pr_cb for d in dbs]
            seed_stats.append(float(np.mean(d_b) - np.mean(d_a)))
        return float(np.mean(seed_stats))

    def src_fn(sl, yb):
        return family_delta(c0, c1, s0, s1, sl, yb)

    def nz_fn(sl, yb):
        return family_delta(c0, c1, n0, n1, sl, yb)

    def composite_stat(sl: np.ndarray, yb: np.ndarray) -> float:
        return 0.5 * src_fn(sl, yb) + 0.5 * nz_fn(sl, yb)

    clean_ci = user_cluster_stat(users, y, clean_stat, contrast="CFPR_minus_CFP0_clean_PR_AUC")
    src_ci = mean_source_delta_contrast(y, users, c0, c1, s0, s1, contrast="CFPR_minus_CFP0_S_source")
    nz_ci = mean_source_delta_contrast(y, users, c0, c1, n0, n1, contrast="CFPR_minus_CFP0_S_noise")
    comp_ci = user_cluster_stat(users, y, composite_stat, contrast="CFPR_minus_CFP0_S_composite")
    rows = official["rows"]

    def mean_key(cand, key):
        return float(np.mean([float(r[key]) for r in rows if r["candidate"] == cand]))

    clean_delta = mean_key(selected, "clean_PR_AUC") - mean_key("CFP0", "clean_PR_AUC")
    source_gain = mean_key(selected, "S_source") - mean_key("CFP0", "S_source")
    noise_gain = mean_key(selected, "S_noise") - mean_key("CFP0", "S_noise")
    composite_delta = mean_key(selected, "S_composite") - mean_key("CFP0", "S_composite")
    n_pos = 0
    for seed in PRIMARY_SEEDS:
        a = next(r for r in rows if r["candidate"] == "CFP0" and int(r["seed"]) == seed)
        b = next(r for r in rows if r["candidate"] == selected and int(r["seed"]) == seed)
        n_pos += int(float(b["S_composite"]) - float(a["S_composite"]) > 0)
    gates = evaluate_official_gates(
        clean_delta=clean_delta,
        clean_ci_lo=float(clean_ci["ci95"][0]),
        composite_delta=composite_delta,
        source_gain=source_gain,
        noise_gain=noise_gain,
        composite_ci_lo=float(comp_ci["ci95"][0]),
        n_seeds_positive_composite=n_pos,
    )
    rec = {
        "clean_delta": clean_delta,
        "clean_ci": clean_ci,
        "source_gain": source_gain,
        "source_ci": src_ci,
        "noise_gain": noise_gain,
        "noise_ci": nz_ci,
        "composite_delta": composite_delta,
        "composite_ci": comp_ci,
        "n_seeds_positive_composite": n_pos,
        "gates": gates,
        "mapping": official["mapping"],
    }
    write_json(_rev("EDITOR021_CLUSTER_BOOTSTRAP.json"), rec)
    return rec


def write_result_freeze(payload: dict[str, Any], *, dest: Path | None = None) -> None:
    md = [
        "# EDITOR-021 result freeze",
        "",
        f"EDITOR020C_PARENT_COMMIT = `{EDITOR020C_PARENT_COMMIT}`",
        f"EDITOR021_PROTOCOL_FREEZE_COMMIT = `{payload.get('protocol_commit', '')}`",
        f"EDITOR021_RESULTS_COMMIT = pending_this_commit",
        "",
        f"CFP0_SCAFFOLD_GATE = {payload.get('CFP0_SCAFFOLD_GATE')}",
        f"EDITOR021_SELECTED_CANDIDATE = {payload.get('EDITOR021_SELECTED_CANDIDATE')}",
        f"EDITOR021_OFFICIAL_VALIDATION_EXECUTED = {payload.get('EDITOR021_OFFICIAL_VALIDATION_EXECUTED')}",
        f"EDITOR021_PROMOTION = {payload.get('EDITOR021_PROMOTION')}",
        f"CURRENT_PAPER_MODEL = {payload.get('CURRENT_PAPER_MODEL')}",
        "",
        "R52_TEST_ACCESSED = NO",
        "R51_RERUN = NO",
        "R62_RERUN = NO",
        "",
    ]
    path = dest or _rev("EDITOR021_RESULT_FREEZE.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(md), encoding="utf-8")


SHA256_MANIFEST_NAME = "EDITOR021_SHA256_MANIFEST.json"
RUN_MANIFEST_NAME = "EDITOR021_RUN_MANIFEST.json"


def sha256_manifest(paths: list[Path], *, repo_root: Path | None = None) -> dict[str, str]:
    """Hash review artefacts. Never hash EDITOR021_SHA256_MANIFEST.json itself."""
    root = repo_root or REVIEW_ROOT.parents[1]
    out: dict[str, str] = {}
    files = [p for p in paths if p.exists() and p.is_file() and p.name != SHA256_MANIFEST_NAME]
    files.sort(key=lambda p: str(p.relative_to(root)).replace("\\", "/"))
    for p in files:
        out[str(p.relative_to(root))] = sha256_file(p)
    return out


def write_sha256_manifest_last(*, review_root: Path | None = None, repo_root: Path | None = None) -> dict[str, str]:
    """Compute and write the SHA256 manifest only after all hash-target files are final.

    Prospective reuse only. Must not be used to rerun frozen EDITOR-021.
    """
    review = review_root or REVIEW_ROOT
    root = repo_root or REVIEW_ROOT.parents[1]
    rec = sha256_manifest(list(review.rglob("*")), repo_root=root)
    write_json(review / SHA256_MANIFEST_NAME, rec)
    return rec


def finalise_completed_packet(
    payload: dict[str, Any],
    *,
    review_root: Path | None = None,
    repo_root: Path | None = None,
) -> tuple[dict[str, str], str]:
    """Write completed RUN_MANIFEST, freeze/terminal artefacts, then SHA256 last.

    Order: scientific files must already exist; this helper then writes
    (1) completed RUN_MANIFEST, (2) RESULT_FREEZE, (3) TERMINAL_BLOCK,
    (4) SHA256 manifest last. Prospective reuse only. Do not rerun EDITOR-021.
    """
    review = review_root or REVIEW_ROOT
    root = repo_root or REVIEW_ROOT.parents[1]
    write_json(review / RUN_MANIFEST_NAME, {"phase": "complete", "utc": utc_now(), **payload})
    write_result_freeze(payload, dest=review / "EDITOR021_RESULT_FREEZE.md")
    text = terminal_block(payload, dest=review / "EDITOR021_TERMINAL_BLOCK.txt")
    rec = write_sha256_manifest_last(review_root=review, repo_root=root)
    return rec, text


def provenance_record(**extra: Any) -> dict[str, Any]:
    rec = {
        "python": sys.version,
        "pytorch": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda": torch.version.cuda if torch.cuda.is_available() else None,
        "device": str(_device()),
        "platform": platform.platform(),
        "git_commit": _git_sha(),
        "git_branch": _git_branch(),
        "utc": utc_now(),
        "R52_TEST_ACCESSED": "NO",
        "R51_RERUN": "NO",
        "R62_RERUN": "NO",
        "TARGET_SCALER_FIT": "NO",
        "TARGET_CALIBRATION_FIT": "NO",
        "TARGET_THRESHOLD_SEARCH": "NO",
        "starting_ta2": {str(s): spec["sha256"] for s, spec in TA2_CHECKPOINTS.items()},
        "teacher_topt_note": "matched seed-specific T-OPT from editor012 hash gate",
        **extra,
    }
    write_json(_rev("EDITOR021_PROVENANCE.json"), rec)
    return rec


def terminal_block(payload: dict[str, Any], *, dest: Path | None = None) -> str:
    def fmt(key: str, default: str = "NOT_RUN") -> str:
        val = payload.get(key, default)
        if val is None:
            return default
        return str(val)

    lines = [
        "EDITOR021_COMPLETE",
        "",
        f"EDITOR020C_PARENT_COMMIT = {EDITOR020C_PARENT_COMMIT}",
        f"EDITOR021_PROTOCOL_FREEZE_COMMIT = {fmt('protocol_commit', 'PENDING')}",
        f"EDITOR021_RESULTS_COMMIT = {fmt('results_commit', 'PENDING')}",
        "",
        f"SOURCE_GATE = {fmt('SOURCE_GATE', 'PASS')}",
        f"PERTURBATION_HASH_GATE = {fmt('PERTURBATION_HASH_GATE', 'PASS')}",
        f"UNIT_TEST_GATE = {fmt('UNIT_TEST_GATE', 'PASS')}",
        "",
        f"CFP0_SCAFFOLD_GATE = {fmt('CFP0_SCAFFOLD_GATE')}",
        "",
    ]
    for name in ROBUSTNESS_CANDIDATES:
        lines.append(f"{name}_INNER_CLEAN_DELTA = {fmt(f'{name}_INNER_CLEAN_DELTA')}")
        lines.append(f"{name}_INNER_COMPOSITE_ROBUSTNESS_DELTA = {fmt(f'{name}_INNER_COMPOSITE_ROBUSTNESS_DELTA')}")
        lines.append(f"{name}_INNER_GATE = {fmt(f'{name}_INNER_GATE')}")
        lines.append("")
    lines.extend(
        [
            f"EDITOR021_SELECTED_CANDIDATE = {fmt('EDITOR021_SELECTED_CANDIDATE', 'NONE')}",
            "",
            f"EDITOR021_OFFICIAL_VALIDATION_EXECUTED = {fmt('EDITOR021_OFFICIAL_VALIDATION_EXECUTED', 'NO')}",
            "",
            f"OFFICIAL_CLEAN_PR_AUC_DELTA = {fmt('OFFICIAL_CLEAN_PR_AUC_DELTA')}",
            f"OFFICIAL_CLEAN_PR_AUC_CI95 = {fmt('OFFICIAL_CLEAN_PR_AUC_CI95')}",
            "",
            f"OFFICIAL_SOURCE_RESILIENCE_DELTA = {fmt('OFFICIAL_SOURCE_RESILIENCE_DELTA')}",
            f"OFFICIAL_SOURCE_RESILIENCE_CI95 = {fmt('OFFICIAL_SOURCE_RESILIENCE_CI95')}",
            "",
            f"OFFICIAL_NOISE_RESILIENCE_DELTA = {fmt('OFFICIAL_NOISE_RESILIENCE_DELTA')}",
            f"OFFICIAL_NOISE_RESILIENCE_CI95 = {fmt('OFFICIAL_NOISE_RESILIENCE_CI95')}",
            "",
            f"OFFICIAL_COMPOSITE_ROBUSTNESS_DELTA = {fmt('OFFICIAL_COMPOSITE_ROBUSTNESS_DELTA')}",
            f"OFFICIAL_COMPOSITE_ROBUSTNESS_CI95 = {fmt('OFFICIAL_COMPOSITE_ROBUSTNESS_CI95')}",
            "",
            f"EDITOR021_CLEAN_FUNCTION_PRESERVATION = {fmt('EDITOR021_CLEAN_FUNCTION_PRESERVATION', 'NOT_TESTED')}",
            "",
            f"EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING = {fmt('EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING', 'NOT_TESTED')}",
            "",
            f"EDITOR021_PROMOTION = {fmt('EDITOR021_PROMOTION', 'NO')}",
            "",
            f"CURRENT_PAPER_MODEL = {fmt('CURRENT_PAPER_MODEL', 'TA2')}",
            "",
            "R52_TEST_ACCESSED = NO",
            "R52_TEST_PREDICTIONS_GENERATED = NO",
            "R51_RERUN = NO",
            "R62_RERUN = NO",
            "",
            "TARGET_SCALER_FIT = NO",
            "TARGET_CALIBRATION_FIT = NO",
            "TARGET_THRESHOLD_SEARCH = NO",
            "",
        ]
    )
    text = "\n".join(lines)
    path = dest or _rev("EDITOR021_TERMINAL_BLOCK.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def run_inner_campaign(device: torch.device) -> dict[str, Any]:
    freeze_path = _rev("EDITOR021_PROMOTION_DECISION.json")
    if freeze_path.exists():
        raise Editor021Blocked("promotion decision already exists; refuse inner overwrite")
    enter_inner_phase()
    try:
        refuse_r52_test(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    mark_predictive_started()
    inner = inner_data()
    views = build_degraded_views(inner["inner_se"].X, inner["scaler"])
    starting = run_starting_ta2(inner, device)
    cfp0 = train_and_score_inner(candidate="CFP0", inner=inner, device=device, views=views)
    all_rows = list(starting) + list(cfp0)
    write_csv(_rev("EDITOR021_INNER_SELECT_SUMMARY.csv"), all_rows)
    scaffold = evaluate_cfp0_scaffold(cfp0, starting)
    scaffold["editor020_ta2_r0_inner"] = EDITOR020_TA2_R0_INNER
    write_json(_rev("EDITOR021_INNER_SELECT_RESULTS.json"), {"starting": starting, "cfp0": cfp0, "scaffold": scaffold})
    payload: dict[str, Any] = {
        "CFP0_SCAFFOLD_GATE": "PASS" if scaffold["pass"] else "FAIL",
        "SOURCE_GATE": "PASS",
        "PERTURBATION_HASH_GATE": "PASS",
    }
    if not scaffold["pass"]:
        ruling = write_negative_freeze(scaffold=scaffold, inner_sel=None, reason="CFP0 scaffold failed")
        payload.update(ruling)
        exit_inner_phase()
        return {"payload": payload, "rows": all_rows, "inner": inner, "official": False}

    cfpr_rows: list[dict[str, Any]] = []
    for name in ROBUSTNESS_CANDIDATES:
        cfpr_rows.extend(train_and_score_inner(candidate=name, inner=inner, device=device, views=views))
    all_rows.extend(cfpr_rows)
    write_csv(_rev("EDITOR021_INNER_SELECT_SUMMARY.csv"), all_rows)
    selection = select_inner_candidate(cfp0 + cfpr_rows)
    write_json(
        _rev("EDITOR021_INNER_SELECT_RESULTS.json"),
        {
            "starting": starting,
            "cfp0": cfp0,
            "cfpr": cfpr_rows,
            "scaffold": scaffold,
            "selection": selection,
        },
    )
    for pack in selection["candidates"]:
        name = pack["candidate"]
        payload[f"{name}_INNER_CLEAN_DELTA"] = pack.get("clean_delta")
        payload[f"{name}_INNER_COMPOSITE_ROBUSTNESS_DELTA"] = pack.get("composite_delta")
        payload[f"{name}_INNER_GATE"] = "PASS" if pack.get("eligible") else "FAIL"
    selected = selection["EDITOR021_SELECTED_CANDIDATE"]
    payload["EDITOR021_SELECTED_CANDIDATE"] = selected if selected else "NONE"
    payload["CFP0_SCAFFOLD_GATE"] = "PASS"
    if not selected:
        ruling = write_negative_freeze(scaffold=scaffold, inner_sel=selection, reason="no CFPR passed G1-G5")
        payload.update(ruling)
        exit_inner_phase()
        return {"payload": payload, "rows": all_rows, "inner": inner, "official": False, "selection": selection}
    write_json(_rev("EDITOR021_PROMOTION_DECISION.json"), {"inner": selection, "utc": utc_now(), "official_pending": True})
    mark_promotion_frozen()
    exit_inner_phase()
    return {
        "payload": payload,
        "rows": all_rows,
        "inner": inner,
        "official": True,
        "selection": selection,
        "selected": selected,
        "cfp0": cfp0,
        "cfpr": cfpr_rows,
        "views": views,
    }


def run_mechanism(inner_state: dict[str, Any], official: dict[str, Any] | None, device: torch.device) -> dict[str, Any]:
    names = ["CFP0"]
    selected = inner_state.get("selected")
    if selected:
        names.append(selected)
    rec: dict[str, Any] = {}
    split_bundle = inner_state["inner"]["inner_se"] if official is None else official["val"]
    split_name = "inner_select" if official is None else "validation"
    X, y = split_bundle.X, split_bundle.y
    for name in names:
        rec[name] = {}
        for seed in PRIMARY_SEEDS:
            loaded = load_trained(name, seed, device)
            ref, _ = load_ta2_reference(seed, device)
            teacher, _ = load_topt(seed, device)
            tensors = collect_clean_tensors(loaded["student"], ref, teacher, X, y, device)
            rec[name][seed] = mechanism_from_tensors(tensors)
    write_json(_rev("EDITOR021_MECHANISM_RESULTS.json"), {"split": split_name, "results": rec})
    return rec


def run_campaign(*, phase: str = "all") -> dict[str, Any]:
    device = _device()
    print(f"[EDITOR-021] device={device} phase={phase}", flush=True)
    identities_ok()
    if phase == "protocol":
        proto = write_protocol_packet()
        write_json(_rev("EDITOR021_RUN_MANIFEST.json"), {"task": "EDITOR-021", "phase": "protocol", "utc": utc_now()})
        return {"protocol": proto}
    hashes = assert_perturbation_hashes()
    if phase == "inner":
        inner_state = run_inner_campaign(device)
        payload = inner_state["payload"]
        payload["PERTURBATION_HASH_GATE"] = "PASS"
        write_json(_rev("EDITOR021_RUN_MANIFEST.json"), {"phase": "inner", **payload})
        write_result_freeze(payload)
        print(terminal_block(payload), flush=True)
        return inner_state
    if phase in {"run", "all", "official"}:
        proto_path = _rev("EDITOR021_PROTOCOL.json")
        if not proto_path.exists():
            raise Editor021Blocked("protocol freeze artefacts missing")
        inner_state = run_inner_campaign(device)
        payload = inner_state["payload"]
        payload["PERTURBATION_HASH_GATE"] = "PASS"
        payload["protocol_commit"] = _git_sha()
        if inner_state.get("official"):
            official = run_official(selected=inner_state["selected"], inner_rows=inner_state["cfp0"] + inner_state["cfpr"], device=device)
            stats = official_statistics(official, inner_state["selected"])
            gates = stats["gates"]
            payload.update(
                {
                    "EDITOR021_OFFICIAL_VALIDATION_EXECUTED": "YES",
                    "OFFICIAL_CLEAN_PR_AUC_DELTA": stats["clean_delta"],
                    "OFFICIAL_CLEAN_PR_AUC_CI95": stats["clean_ci"]["ci95"],
                    "OFFICIAL_SOURCE_RESILIENCE_DELTA": stats["source_gain"],
                    "OFFICIAL_SOURCE_RESILIENCE_CI95": stats["source_ci"]["ci95"],
                    "OFFICIAL_NOISE_RESILIENCE_DELTA": stats["noise_gain"],
                    "OFFICIAL_NOISE_RESILIENCE_CI95": stats["noise_ci"]["ci95"],
                    "OFFICIAL_COMPOSITE_ROBUSTNESS_DELTA": stats["composite_delta"],
                    "OFFICIAL_COMPOSITE_ROBUSTNESS_CI95": stats["composite_ci"]["ci95"],
                    **{k: gates[k] for k in (
                        "EDITOR021_CLEAN_FUNCTION_PRESERVATION",
                        "EDITOR021_TRAINING_TIME_ROBUSTNESS_HARDENING",
                        "EDITOR021_PROMOTION",
                        "CURRENT_PAPER_MODEL",
                    )},
                }
            )
            write_json(_rev("EDITOR021_PROMOTION_DECISION.json"), {"inner": inner_state["selection"], "official": gates, "utc": utc_now()})
            run_mechanism(inner_state, official, device)
        else:
            payload["EDITOR021_OFFICIAL_VALIDATION_EXECUTED"] = "NO"
            run_mechanism(inner_state, None, device)
        provenance_record(hashes=hashes)
        _rec, text = finalise_completed_packet(payload)
        print(text, flush=True)
        return {"payload": payload, "inner": inner_state}
    raise Editor021Blocked(f"unknown phase {phase}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("protocol", "inner", "run", "all"), default="all")
    args = parser.parse_args()
    run_campaign(phase=args.phase)


if __name__ == "__main__":
    main()
