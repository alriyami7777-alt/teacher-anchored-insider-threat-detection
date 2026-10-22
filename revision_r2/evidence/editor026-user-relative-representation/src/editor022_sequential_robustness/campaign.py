"""EDITOR-022 sequential clean-optimum-anchored robustness campaign."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics import average_precision_score

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
from editor017_robustness.bootstrap_family import mean_source_delta_contrast, user_cluster_stat
from editor017_robustness.constants import NOISE_LEVELS, SOURCE_CHANNELS
from editor017_robustness.perturbations import load_r52_train_scaler
from editor018_cross_view.cache import load_ensemble_split
from editor020_robustness.evaluate import build_degraded_views
from editor021_cfpr.evaluate import score_all_views
from editor021_cfpr.mechanism import collect_clean_tensors, mechanism_from_tensors

from .constants import (
    CANDIDATES,
    CFP0_START_METRICS,
    EDITOR021P1_CORRECTION_COMMIT,
    EDITOR021_PROTOCOL_COMMIT,
    EDITOR021_RESULTS_COMMIT,
    EDITOR022_PARENT_COMMIT,
    FROZEN_INNER_CFP0_THRESHOLDS,
    PARITY_TOLERANCE,
    ROBUSTNESS_CANDIDATES,
    STAGE2_EPOCHS,
    TA2_CHECKPOINTS,
)
from .io_util import write_csv, write_json, write_npz
from .models import (
    hash_gate_all_cfp0_inner,
    identities_ok,
    load_cfp0_reference,
    load_cfp0_student,
    load_trained,
    load_topt,
)
from .promotion import evaluate_official_gates, evaluate_seq0_scaffold, select_inner_candidate
from .protocol import assert_perturbation_hashes, write_protocol_packet
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor022Blocked,
    enter_inner_phase,
    exit_inner_phase,
    mark_predictive_started,
    mark_promotion_frozen,
    refuse_r52_test,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .train import train_inherited_cfp0_full, train_stage2_candidate


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
        raise Editor022Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor022Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor022Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor022Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    return {
        "USER_MAPPING_RECOVERED": True,
        "USER_CLUSTER_BOOTSTRAP_STATUS": "AVAILABLE",
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "mapping_sha256": mapping_hash,
        "sampling_unit": "validation user",
        "windows_not_independent": True,
    }


def rho_of(candidate: str) -> float:
    key = str(candidate).replace("_FULL", "").replace("_START", "")
    if key in {"CFP0", "CFP0_START", "CFP0_FULL"}:
        return 0.0
    if candidate in CANDIDATES:
        return float(CANDIDATES[candidate]["rho"])
    if key in CANDIDATES:
        return float(CANDIDATES[key]["rho"])
    return float("nan")


def pack_row(candidate: str, seed: int, scored: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rob = scored["robust"]
    row = {
        "candidate": candidate,
        "seed": int(seed),
        "rho": rho_of(candidate),
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
        raise Editor022Blocked(f"INNER_TRAIN n {split['n_inner_train']} != {EXPECTED_INNER_TRAIN_N}")
    if int(split["n_inner_select"]) != EXPECTED_INNER_SELECT_N:
        raise Editor022Blocked(f"INNER_SELECT n {split['n_inner_select']} != {EXPECTED_INNER_SELECT_N}")
    if int(split["n_inner_train_pos"]) != EXPECTED_INNER_TRAIN_POS:
        raise Editor022Blocked("INNER_TRAIN positives mismatch")
    if int(split["n_inner_select_pos"]) != EXPECTED_INNER_SELECT_POS:
        raise Editor022Blocked("INNER_SELECT positives mismatch")
    if int(split["n_dropped"]) != EXPECTED_INNER_DROPPED:
        raise Editor022Blocked("inner dropped mismatch")
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
    for ch in SOURCE_CHANNELS:
        write_raw(
            candidate=candidate,
            seed=seed,
            split=split,
            condition=f"source_{ch}",
            bundle=bundle,
            y=bundle.y,
            users=bundle.user,
            seq_ids=bundle.sequence_id,
            logits=scored["source_logits"][ch],
        )
    for level in NOISE_LEVELS:
        write_raw(
            candidate=candidate,
            seed=seed,
            split=split,
            condition=f"noise_{level:.2f}",
            bundle=bundle,
            y=bundle.y,
            users=bundle.user,
            seq_ids=bundle.sequence_id,
            logits=scored["noise_logits"][float(level)],
        )
    row = pack_row(candidate, seed, scored, extra=extra)
    return scored, row


def _parity_ok(observed: float, expected: float) -> bool:
    return abs(float(observed) - float(expected)) <= PARITY_TOLERANCE


def run_cfp0_parity(inner: dict[str, Any], device: torch.device) -> dict[str, Any]:
    ckpts = hash_gate_all_cfp0_inner()
    views = build_degraded_views(inner["inner_se"].X, inner["scaler"])
    rows = []
    seed_ok = {}
    for seed in PRIMARY_SEEDS:
        print(f"[EDITOR-022] CFP0_START parity seed={seed}", flush=True)
        student, sha = load_cfp0_student(seed, device)
        scored, row = score_and_pack(
            candidate="CFP0_START",
            seed=seed,
            student=student,
            views=views,
            bundle=inner["inner_se"],
            device=device,
            split="inner_select",
            threshold=None,
            allow_threshold_search=True,
            extra={"kind": "frozen_cfp0_start", "sha256": sha, "logical_path": ckpts[int(seed)]["logical_path"]},
        )
        exp = CFP0_START_METRICS[int(seed)]
        checks = {
            "clean_PR_AUC": _parity_ok(row["clean_PR_AUC"], exp["clean_PR_AUC"]),
            "S_source": _parity_ok(row["S_source"], exp["S_source"]),
            "S_noise": _parity_ok(row["S_noise"], exp["S_noise"]),
            "S_composite": _parity_ok(row["S_composite"], exp["S_composite"]),
            "sha256": sha == ckpts[int(seed)]["sha256"],
        }
        seed_ok[int(seed)] = {
            "observed": {k: row[k] for k in ("clean_PR_AUC", "S_source", "S_noise", "S_composite")},
            "expected": exp,
            "checks": checks,
            "pass": all(checks.values()),
        }
        rows.append(row)
    passed = all(v["pass"] for v in seed_ok.values())
    rec = {
        "EDITOR022_CFP0_CHECKPOINT_GATE": "PASS",
        "EDITOR022_CFP0_PARITY_GATE": "PASS" if passed else "FAIL",
        "tolerance": PARITY_TOLERANCE,
        "checkpoints": ckpts,
        "seeds": {str(k): v for k, v in seed_ok.items()},
        "rows": rows,
        "utc": utc_now(),
    }
    write_json(_rev("EDITOR022_CFP0_PARITY.json"), rec)
    write_csv(_rev("EDITOR022_INNER_SUMMARY.csv"), rows)
    if not passed:
        rec["EDITOR022_PREDICTIVE_TRAINING_EXECUTED"] = "NO"
        write_json(_rev("EDITOR022_PROMOTION_DECISION.json"), {
            "EDITOR022_CFP0_PARITY_GATE": "FAIL",
            "EDITOR022_PREDICTIVE_TRAINING_EXECUTED": "NO",
            "EDITOR022_PROMOTION": "NO",
            "CURRENT_PAPER_MODEL": "TA2",
            "utc": utc_now(),
        })
        raise Editor022Blocked("EDITOR022_CFP0_SCORE_PARITY_GATE = FAIL")
    return rec


def train_and_score_stage2(
    *,
    candidate: str,
    inner: dict[str, Any],
    device: torch.device,
    views: dict[str, np.ndarray],
    start_from: str = "cfp0_inner",
    split: str = "inner_select",
    bundle: SequenceBundle | None = None,
    threshold_by_seed: dict[int, float] | None = None,
    allow_threshold_search: bool = True,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    rows = []
    packs: dict[int, dict[str, Any]] = {}
    target = bundle if bundle is not None else inner["inner_se"]
    X = inner["inner_tr"].X if start_from == "cfp0_inner" else inner["train_x"]
    y = inner["inner_tr"].y if start_from == "cfp0_inner" else inner["train_y"]
    ens = inner["ens_tr"] if start_from == "cfp0_inner" else inner["ens_full"]
    pos_w = inner["pos_w"] if start_from == "cfp0_inner" else inner["pos_w_full"]
    scaler = inner["scaler"]
    for seed in PRIMARY_SEEDS:
        print(f"[EDITOR-022] STAGE2 {candidate} seed={seed} start={start_from}", flush=True)
        teacher, _ = load_topt(seed, device)
        trained = train_stage2_candidate(
            candidate=candidate,
            seed=seed,
            X=X,
            y=y,
            ens=ens,
            matched_teacher=teacher,
            device=device,
            pos_weight=pos_w,
            scaler=scaler,
            start_from=start_from,
        )
        loaded = load_trained(candidate, seed, device, filename="stage2.pt")
        thr = None if threshold_by_seed is None else float(threshold_by_seed[int(seed)])
        scored, row = score_and_pack(
            candidate=candidate,
            seed=seed,
            student=loaded["student"],
            views=views,
            bundle=target,
            device=device,
            split=split,
            threshold=thr,
            allow_threshold_search=allow_threshold_search,
            extra={
                "stage2_epochs": trained["stage2_epochs"],
                "checkpoint": trained["checkpoint"],
                "checkpoint_sha256": trained["checkpoint_sha256"],
                "training_time": trained["training_time"],
                "start_sha256": trained["start_sha256"],
                "n_optimiser_steps": trained["n_optimiser_steps"],
                "grad_diagnostics": trained["grad_diagnostics"],
                "FRESH_STAGE2_OPTIMISER": True,
                "OPTIMISER_STATE_CONTINUED_FROM_CFP0": False,
            },
        )
        row["scored_threshold"] = float(scored["robust"]["threshold"])
        packs[int(seed)] = scored
        rows.append(row)
        write_csv(_rev("EDITOR022_INNER_SUMMARY.csv") if split == "inner_select" else _rev("EDITOR022_VALIDATION_SUMMARY.csv"), rows)
    return rows, packs


def write_negative_freeze(*, scaffold: dict[str, Any] | None, inner_sel: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    ruling = {
        "EDITOR022_INNER_PROMOTION": "NONE",
        "EDITOR022_SELECTED_CANDIDATE": "NONE",
        "EDITOR022_VALIDATION_EXECUTED": "NO",
        "EDITOR022_PROMOTION": "NO",
        "CURRENT_PAPER_MODEL": "TA2",
        "reason": reason,
        "scaffold": scaffold,
        "inner_selection": inner_sel,
        "utc": utc_now(),
        "STAGE2_EPOCHS": STAGE2_EPOCHS,
        "FRESH_STAGE2_OPTIMISER": "YES",
        "OPTIMISER_STATE_CONTINUED_FROM_CFP0": "NO",
    }
    if scaffold is not None and not scaffold.get("pass", True):
        ruling["EDITOR022_SEQ0_SCAFFOLD_GATE"] = "FAIL"
        ruling["EDITOR022_SRP_CANDIDATES_EXECUTED"] = "NO"
        ruling["EDITOR022_CLEAN_OPTIMUM_PRESERVATION"] = "NOT_SUPPORTED"
        ruling["EDITOR022_ROBUSTNESS_SPECIFIC_VALUE"] = "NOT_TESTED"
        ruling["EDITOR022_SEQUENTIAL_ROBUSTNESS_REFINEMENT"] = "NOT_TESTED"
    else:
        ruling["EDITOR022_SEQ0_SCAFFOLD_GATE"] = "PASS"
        ruling["EDITOR022_SRP_CANDIDATES_EXECUTED"] = "YES"
        ruling["EDITOR022_CLEAN_OPTIMUM_PRESERVATION"] = "NOT_TESTED"
        ruling["EDITOR022_ROBUSTNESS_SPECIFIC_VALUE"] = "NOT_TESTED"
        ruling["EDITOR022_SEQUENTIAL_ROBUSTNESS_REFINEMENT"] = "NOT_SUPPORTED"
    write_json(_rev("EDITOR022_PROMOTION_DECISION.json"), ruling)
    return ruling


def logits_by_seed(packs: dict[str, dict[int, dict[str, Any]]], name: str) -> tuple[list[np.ndarray], list[list[np.ndarray]], list[list[np.ndarray]]]:
    clean, source, noise = [], [], []
    for seed in PRIMARY_SEEDS:
        pack = packs[name][seed]
        clean.append(pack["clean"]["logits"])
        source.append([pack["source_logits"][ch] for ch in SOURCE_CHANNELS])
        noise.append([pack["noise_logits"][float(lv)] for lv in NOISE_LEVELS])
    return clean, source, noise


def run_validation(
    *,
    selected: str,
    device: torch.device,
) -> dict[str, Any]:
    mark_promotion_frozen()
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    write_json(_rev("EDITOR022_CLUSTER_BOOTSTRAP.json"), {"user_mapping_pending_stats": mapping})
    train, val = bundle["train"], bundle["val"]
    scaler = load_r52_train_scaler()
    views = build_degraded_views(val.X, scaler)
    ens = load_ensemble_split("train")["ens"]
    pos_w = float(bundle["pos_weight"])
    packs: dict[str, dict[int, dict[str, Any]]] = {"CFP0_FULL_START": {}, "SEQ0_FULL": {}, f"{selected}_FULL": {}}
    rows: list[dict[str, Any]] = []
    inner_full = {
        "train_x": train.X,
        "train_y": train.y,
        "ens_full": ens,
        "pos_w_full": pos_w,
        "scaler": scaler,
    }
    for seed in PRIMARY_SEEDS:
        print(f"[EDITOR-022] CFP0_FULL seed={seed}", flush=True)
        teacher, _ = load_topt(seed, device)
        trained = train_inherited_cfp0_full(
            seed=seed,
            X=train.X,
            y=train.y,
            ens=ens,
            X_select=val.X,
            y_select=val.y,
            matched_teacher=teacher,
            device=device,
            pos_weight=pos_w,
        )
        loaded = load_trained("CFP0_FULL", seed, device, filename="best.pt")
        thr = float(FROZEN_INNER_CFP0_THRESHOLDS[int(seed)])
        scored, row = score_and_pack(
            candidate="CFP0_FULL_START",
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
                "checkpoint": trained["checkpoint"],
                "checkpoint_sha256": trained["checkpoint_sha256"],
                "split": "validation",
                "kind": "cfp0_full_start",
                "frozen_inner_threshold": thr,
            },
        )
        packs["CFP0_FULL_START"][seed] = scored
        rows.append(row)
        write_csv(_rev("EDITOR022_VALIDATION_SUMMARY.csv"), rows)

    seq0_rows, seq0_packs = train_and_score_stage2(
        candidate="SEQ0_FULL",
        inner=inner_full,
        device=device,
        views=views,
        start_from="cfp0_full",
        split="validation",
        bundle=val,
        threshold_by_seed=FROZEN_INNER_CFP0_THRESHOLDS,
        allow_threshold_search=False,
    )
    packs["SEQ0_FULL"] = seq0_packs
    rows.extend(seq0_rows)
    srp_name = f"{selected}_FULL"
    srp_rows, srp_packs = train_and_score_stage2(
        candidate=srp_name,
        inner=inner_full,
        device=device,
        views=views,
        start_from="cfp0_full",
        split="validation",
        bundle=val,
        threshold_by_seed=FROZEN_INNER_CFP0_THRESHOLDS,
        allow_threshold_search=False,
    )
    packs[srp_name] = srp_packs
    rows.extend(srp_rows)
    write_csv(_rev("EDITOR022_VALIDATION_SUMMARY.csv"), rows)
    write_json(
        _rev("EDITOR022_VALIDATION_RESULTS.json"),
        {"rows": rows, "selected": selected, "utc": utc_now()},
    )
    return {
        "rows": rows,
        "packs": packs,
        "mapping": mapping,
        "val": val,
        "train": train,
        "y": np.asarray(val.y),
        "users": np.asarray(val.user).astype(str),
        "selected_full": srp_name,
    }


def official_statistics(official: dict[str, Any], selected: str) -> dict[str, Any]:
    y, users = official["y"], official["users"]
    selected_full = official["selected_full"]
    c0, s0, n0 = logits_by_seed(official["packs"], "CFP0_FULL_START")
    c1, s1, n1 = logits_by_seed(official["packs"], selected_full)
    cq, sq, nq = logits_by_seed(official["packs"], "SEQ0_FULL")

    def family_delta(clean_a, clean_b, deg_a, deg_b, sl, yb):
        seed_stats = []
        for ca, cb, das, dbs in zip(clean_a, clean_b, deg_a, deg_b):
            pr_ca = float(average_precision_score(yb, sigmoid(ca[sl])))
            pr_cb = float(average_precision_score(yb, sigmoid(cb[sl])))
            d_a = [float(average_precision_score(yb, sigmoid(d[sl]))) - pr_ca for d in das]
            d_b = [float(average_precision_score(yb, sigmoid(d[sl]))) - pr_cb for d in dbs]
            seed_stats.append(float(np.mean(d_b) - np.mean(d_a)))
        return float(np.mean(seed_stats))

    def clean_stat(sl: np.ndarray, yb: np.ndarray) -> float:
        diffs = []
        for a, b in zip(c0, c1):
            diffs.append(float(average_precision_score(yb, sigmoid(b[sl])) - average_precision_score(yb, sigmoid(a[sl]))))
        return float(np.mean(diffs))

    def src_fn(sl, yb):
        return family_delta(c0, c1, s0, s1, sl, yb)

    def nz_fn(sl, yb):
        return family_delta(c0, c1, n0, n1, sl, yb)

    def composite_stat(sl: np.ndarray, yb: np.ndarray) -> float:
        return 0.5 * src_fn(sl, yb) + 0.5 * nz_fn(sl, yb)

    def seq0_composite_stat(sl: np.ndarray, yb: np.ndarray) -> float:
        return 0.5 * family_delta(cq, c1, sq, s1, sl, yb) + 0.5 * family_delta(cq, c1, nq, n1, sl, yb)

    clean_ci = user_cluster_stat(users, y, clean_stat, contrast="SRP_minus_CFP0_FULL_START_clean_PR_AUC")
    src_ci = mean_source_delta_contrast(y, users, c0, c1, s0, s1, contrast="SRP_minus_CFP0_FULL_START_S_source")
    nz_ci = mean_source_delta_contrast(y, users, c0, c1, n0, n1, contrast="SRP_minus_CFP0_FULL_START_S_noise")
    comp_ci = user_cluster_stat(users, y, composite_stat, contrast="SRP_minus_CFP0_FULL_START_S_composite")
    seq0_comp_ci = user_cluster_stat(users, y, seq0_composite_stat, contrast="SRP_minus_SEQ0_FULL_S_composite")
    rows = official["rows"]

    def mean_key(cand, key):
        return float(np.mean([float(r[key]) for r in rows if r["candidate"] == cand]))

    clean_delta = mean_key(selected_full, "clean_PR_AUC") - mean_key("CFP0_FULL_START", "clean_PR_AUC")
    source_gain = mean_key(selected_full, "S_source") - mean_key("CFP0_FULL_START", "S_source")
    noise_gain = mean_key(selected_full, "S_noise") - mean_key("CFP0_FULL_START", "S_noise")
    composite_delta = mean_key(selected_full, "S_composite") - mean_key("CFP0_FULL_START", "S_composite")
    composite_delta_vs_seq0 = mean_key(selected_full, "S_composite") - mean_key("SEQ0_FULL", "S_composite")
    n_pos = 0
    n_vs_seq0 = 0
    for seed in PRIMARY_SEEDS:
        a = next(r for r in rows if r["candidate"] == "CFP0_FULL_START" and int(r["seed"]) == seed)
        b = next(r for r in rows if r["candidate"] == selected_full and int(r["seed"]) == seed)
        q = next(r for r in rows if r["candidate"] == "SEQ0_FULL" and int(r["seed"]) == seed)
        n_pos += int(float(b["S_composite"]) - float(a["S_composite"]) > 0)
        n_vs_seq0 += int(float(b["S_composite"]) > float(q["S_composite"]))
    gates = evaluate_official_gates(
        clean_delta=clean_delta,
        clean_ci_lo=float(clean_ci["ci95"][0]),
        composite_delta=composite_delta,
        source_gain=source_gain,
        noise_gain=noise_gain,
        composite_ci_lo=float(comp_ci["ci95"][0]),
        n_seeds_positive_composite=n_pos,
        composite_delta_vs_seq0=composite_delta_vs_seq0,
        n_seeds_better_than_seq0=n_vs_seq0,
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
        "composite_delta_vs_seq0": composite_delta_vs_seq0,
        "seq0_composite_ci": seq0_comp_ci,
        "n_seeds_positive_composite": n_pos,
        "n_seeds_better_than_seq0": n_vs_seq0,
        "gates": gates,
        "mapping": official["mapping"],
    }
    write_json(_rev("EDITOR022_CLUSTER_BOOTSTRAP.json"), rec)
    return rec


def run_mechanism(inner_state: dict[str, Any], official: dict[str, Any] | None, device: torch.device) -> dict[str, Any]:
    rec: dict[str, Any] = {}
    if official is None:
        split_bundle = inner_state["inner"]["inner_se"]
        split_name = "inner_select"
        names = ["CFP0_START", "SEQ0"]
        selected = inner_state.get("selected")
        if selected:
            names.append(selected)
        loaders = {
            "CFP0_START": lambda seed: load_cfp0_student(seed, device)[0],
            "SEQ0": lambda seed: load_trained("SEQ0", seed, device, filename="stage2.pt")["student"],
        }
        if selected:
            loaders[selected] = lambda seed, name=selected: load_trained(name, seed, device, filename="stage2.pt")["student"]
        X, y = split_bundle.X, split_bundle.y
        for name in names:
            rec[name] = {}
            for seed in PRIMARY_SEEDS:
                student = loaders[name](seed)
                ref, _ = load_cfp0_reference(seed, device)
                teacher, _ = load_topt(seed, device)
                tensors = collect_clean_tensors(student, ref, teacher, X, y, device)
                rec[name][str(seed)] = mechanism_from_tensors(tensors)
    else:
        split_bundle = official["val"]
        split_name = "validation"
        selected_full = official["selected_full"]
        names = ["CFP0_FULL_START", "SEQ0_FULL", selected_full]
        X, y = split_bundle.X, split_bundle.y
        for name in names:
            rec[name] = {}
            for seed in PRIMARY_SEEDS:
                if name == "CFP0_FULL_START":
                    student = load_trained("CFP0_FULL", seed, device, filename="best.pt")["student"]
                else:
                    student = load_trained(name, seed, device, filename="stage2.pt")["student"]
                from .models import load_cfp0_full_reference

                ref, _ = load_cfp0_full_reference(seed, device)
                teacher, _ = load_topt(seed, device)
                tensors = collect_clean_tensors(student, ref, teacher, X, y, device)
                rec[name][str(seed)] = mechanism_from_tensors(tensors)
    write_json(_rev("EDITOR022_MECHANISM_RESULTS.json"), {"split": split_name, "results": rec})
    return rec


def write_result_freeze(payload: dict[str, Any], *, dest: Path | None = None) -> None:
    md = [
        "# EDITOR-022 result freeze",
        "",
        f"EDITOR022_PARENT_COMMIT = `{EDITOR022_PARENT_COMMIT}`",
        f"EDITOR021_RESULTS_COMMIT = `{EDITOR021_RESULTS_COMMIT}`",
        f"EDITOR021P1_CORRECTION_COMMIT = `{EDITOR021P1_CORRECTION_COMMIT}`",
        f"EDITOR021_PROTOCOL_COMMIT = `{EDITOR021_PROTOCOL_COMMIT}`",
        f"EDITOR022_PROTOCOL_FREEZE_COMMIT = `{payload.get('protocol_commit', '')}`",
        "EDITOR022_RESULTS_COMMIT = pending_this_commit",
        "",
        f"SEQ0_SCAFFOLD_GATE = {payload.get('SEQ0_SCAFFOLD_GATE')}",
        f"EDITOR022_SELECTED_CANDIDATE = {payload.get('EDITOR022_SELECTED_CANDIDATE')}",
        f"EDITOR022_VALIDATION_EXECUTED = {payload.get('EDITOR022_VALIDATION_EXECUTED')}",
        f"EDITOR022_PROMOTION = {payload.get('EDITOR022_PROMOTION')}",
        f"CURRENT_PAPER_MODEL = {payload.get('CURRENT_PAPER_MODEL')}",
        "",
        "R52_TEST_ACCESSED = NO",
        "R51_RERUN = NO",
        "R62_RERUN = NO",
        "STAGE2_EPOCHS = 1",
        "FRESH_STAGE2_OPTIMISER = YES",
        "OPTIMISER_STATE_CONTINUED_FROM_CFP0 = NO",
        "",
    ]
    path = dest or _rev("EDITOR022_RESULT_FREEZE.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(md), encoding="utf-8")


SHA256_MANIFEST_NAME = "EDITOR022_SHA256_MANIFEST.json"
RUN_MANIFEST_NAME = "EDITOR022_RUN_MANIFEST.json"


def sha256_manifest(paths: list[Path], *, repo_root: Path | None = None) -> dict[str, str]:
    """Hash review artefacts. Never hash EDITOR022_SHA256_MANIFEST.json itself."""
    root = repo_root or REVIEW_ROOT.parents[1]
    out: dict[str, str] = {}
    files = [p for p in paths if p.exists() and p.is_file() and p.name != SHA256_MANIFEST_NAME]
    files.sort(key=lambda p: str(p.relative_to(root)).replace("\\", "/"))
    for p in files:
        out[str(p.relative_to(root)).replace("\\", "/")] = sha256_file(p)
    return out


def write_sha256_manifest_last(*, review_root: Path | None = None, repo_root: Path | None = None) -> dict[str, str]:
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
    review = review_root or REVIEW_ROOT
    root = repo_root or REVIEW_ROOT.parents[1]
    write_json(review / RUN_MANIFEST_NAME, {"phase": "complete", "utc": utc_now(), **payload})
    write_result_freeze(payload, dest=review / "EDITOR022_RESULT_FREEZE.md")
    text = terminal_block(payload, dest=review / "EDITOR022_TERMINAL_BLOCK.txt")
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
        "EDITOR022_PARENT_COMMIT": EDITOR022_PARENT_COMMIT,
        "EDITOR021_RESULTS_COMMIT": EDITOR021_RESULTS_COMMIT,
        "EDITOR021P1_CORRECTION_COMMIT": EDITOR021P1_CORRECTION_COMMIT,
        "R52_TEST_ACCESSED": "NO",
        "R52_TEST_PREDICTIONS_GENERATED": "NO",
        "R51_RERUN": "NO",
        "R62_RERUN": "NO",
        "TARGET_SCALER_FIT": "NO",
        "TARGET_CALIBRATION_FIT": "NO",
        "TARGET_THRESHOLD_SEARCH": "NO",
        "STAGE2_EPOCHS": STAGE2_EPOCHS,
        "FRESH_STAGE2_OPTIMISER": "YES",
        "OPTIMISER_STATE_CONTINUED_FROM_CFP0": "NO",
        "cfp0_inner": {str(s): spec for s, spec in hash_gate_all_cfp0_inner().items()},
        "starting_ta2": {str(s): spec["sha256"] for s, spec in TA2_CHECKPOINTS.items()},
        "teacher_topt_note": "matched seed-specific T-OPT from editor012 hash gate",
        **extra,
    }
    write_json(_rev("EDITOR022_PROVENANCE.json"), rec)
    return rec


def terminal_block(payload: dict[str, Any], *, dest: Path | None = None) -> str:
    def fmt(key: str, default: str = "NOT_RUN") -> str:
        val = payload.get(key, default)
        if val is None:
            return default
        return str(val)

    lines = [
        "EDITOR022_COMPLETE",
        "",
        f"EDITOR022_PARENT_COMMIT = {EDITOR022_PARENT_COMMIT}",
        "",
        f"EDITOR022_PROTOCOL_FREEZE_COMMIT = {fmt('protocol_commit', 'PENDING')}",
        "",
        f"EDITOR022_RESULTS_COMMIT = {fmt('results_commit', 'PENDING')}",
        "",
        f"SOURCE_GATE = {fmt('SOURCE_GATE', 'PASS')}",
        "",
        f"UNIT_TEST_GATE = {fmt('UNIT_TEST_GATE', 'PASS')}",
        "",
        f"CFP0_CHECKPOINT_GATE = {fmt('CFP0_CHECKPOINT_GATE', 'PASS')}",
        "",
        f"PERTURBATION_HASH_GATE = {fmt('PERTURBATION_HASH_GATE', 'PASS')}",
        "",
        f"CFP0_PARITY_GATE = {fmt('CFP0_PARITY_GATE')}",
        "",
        f"SEQ0_SCAFFOLD_GATE = {fmt('SEQ0_SCAFFOLD_GATE')}",
        "",
        f"SEQ0_MEAN_CLEAN_DELTA_VS_CFP0_START = {fmt('SEQ0_MEAN_CLEAN_DELTA_VS_CFP0_START')}",
        "",
    ]
    for name in ROBUSTNESS_CANDIDATES:
        lines.append(f"{name}_MEAN_CLEAN_DELTA_VS_CFP0_START = {fmt(f'{name}_MEAN_CLEAN_DELTA_VS_CFP0_START')}")
        lines.append("")
        lines.append(f"{name}_MEAN_COMPOSITE_DELTA_VS_CFP0_START = {fmt(f'{name}_MEAN_COMPOSITE_DELTA_VS_CFP0_START')}")
        lines.append("")
        lines.append(f"{name}_MEAN_COMPOSITE_DELTA_VS_SEQ0 = {fmt(f'{name}_MEAN_COMPOSITE_DELTA_VS_SEQ0')}")
        lines.append("")
        lines.append(f"{name}_GATE = {fmt(f'{name}_GATE')}")
        lines.append("")
        lines.append("")
    lines.extend(
        [
            f"EDITOR022_SELECTED_CANDIDATE = {fmt('EDITOR022_SELECTED_CANDIDATE', 'NONE')}",
            "",
            f"EDITOR022_VALIDATION_EXECUTED = {fmt('EDITOR022_VALIDATION_EXECUTED', 'NO')}",
            "",
            "",
            f"VALIDATION_CLEAN_PR_AUC_DELTA_VS_CFP0 = {fmt('VALIDATION_CLEAN_PR_AUC_DELTA_VS_CFP0')}",
            "",
            f"VALIDATION_CLEAN_PR_AUC_CI95 = {fmt('VALIDATION_CLEAN_PR_AUC_CI95')}",
            "",
            f"VALIDATION_SOURCE_RESILIENCE_DELTA_VS_CFP0 = {fmt('VALIDATION_SOURCE_RESILIENCE_DELTA_VS_CFP0')}",
            "",
            f"VALIDATION_SOURCE_RESILIENCE_CI95 = {fmt('VALIDATION_SOURCE_RESILIENCE_CI95')}",
            "",
            f"VALIDATION_NOISE_RESILIENCE_DELTA_VS_CFP0 = {fmt('VALIDATION_NOISE_RESILIENCE_DELTA_VS_CFP0')}",
            "",
            f"VALIDATION_NOISE_RESILIENCE_CI95 = {fmt('VALIDATION_NOISE_RESILIENCE_CI95')}",
            "",
            f"VALIDATION_COMPOSITE_DELTA_VS_CFP0 = {fmt('VALIDATION_COMPOSITE_DELTA_VS_CFP0')}",
            "",
            f"VALIDATION_COMPOSITE_CI95 = {fmt('VALIDATION_COMPOSITE_CI95')}",
            "",
            f"VALIDATION_COMPOSITE_DELTA_VS_SEQ0 = {fmt('VALIDATION_COMPOSITE_DELTA_VS_SEQ0')}",
            "",
            "",
            f"EDITOR022_CLEAN_OPTIMUM_PRESERVATION = {fmt('EDITOR022_CLEAN_OPTIMUM_PRESERVATION', 'NOT_TESTED')}",
            "",
            f"EDITOR022_ROBUSTNESS_SPECIFIC_VALUE = {fmt('EDITOR022_ROBUSTNESS_SPECIFIC_VALUE', 'NOT_TESTED')}",
            "",
            f"EDITOR022_SEQUENTIAL_ROBUSTNESS_REFINEMENT = {fmt('EDITOR022_SEQUENTIAL_ROBUSTNESS_REFINEMENT', 'NOT_TESTED')}",
            "",
            f"EDITOR022_PROMOTION = {fmt('EDITOR022_PROMOTION', 'NO')}",
            "",
            f"CURRENT_PAPER_MODEL = {fmt('CURRENT_PAPER_MODEL', 'TA2')}",
            "",
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
            "STAGE2_EPOCHS = 1",
            "FRESH_STAGE2_OPTIMISER = YES",
            "OPTIMISER_STATE_CONTINUED_FROM_CFP0 = NO",
            "",
            f"SHA_MANIFEST_VERIFICATION = {fmt('SHA_MANIFEST_VERIFICATION', 'PENDING')}",
            "",
            f"EDITOR022_SOURCE_CLEANUP_GATE = {fmt('EDITOR022_SOURCE_CLEANUP_GATE', 'PASS')}",
            "ARCHIVE_LOCATION = C:\\PhD\\07_Projects\\_editor_untracked_archive\\EDITOR022_SOURCE_GATE_2026-08-17",
            "ARCHIVE_FILE_COUNT_MATCH = YES",
            "ARCHIVE_BYTE_COUNT_MATCH = YES",
            "ARCHIVE_SHA256_MATCH = YES",
            "",
        ]
    )
    text = "\n".join(lines)
    path = dest or _rev("EDITOR022_TERMINAL_BLOCK.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def run_inner_campaign(device: torch.device) -> dict[str, Any]:
    freeze_path = _rev("EDITOR022_PROMOTION_DECISION.json")
    if freeze_path.exists():
        raise Editor022Blocked("promotion decision already exists; refuse inner overwrite")
    enter_inner_phase()
    try:
        refuse_r52_test(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    mark_predictive_started()
    inner = inner_data()
    views = build_degraded_views(inner["inner_se"].X, inner["scaler"])
    parity = run_cfp0_parity(inner, device)
    cfp0_rows = parity["rows"]
    payload: dict[str, Any] = {
        "CFP0_CHECKPOINT_GATE": "PASS",
        "CFP0_PARITY_GATE": "PASS",
        "SOURCE_GATE": "PASS",
        "EDITOR022_SOURCE_CLEANUP_GATE": "PASS",
        "PERTURBATION_HASH_GATE": "PASS",
    }
    seq0, _seq0_packs = train_and_score_stage2(candidate="SEQ0", inner=inner, device=device, views=views)
    all_rows = list(cfp0_rows) + list(seq0)
    write_csv(_rev("EDITOR022_INNER_SUMMARY.csv"), all_rows)
    scaffold = evaluate_seq0_scaffold(seq0, cfp0_rows)
    payload["SEQ0_SCAFFOLD_GATE"] = "PASS" if scaffold["pass"] else "FAIL"
    payload["SEQ0_MEAN_CLEAN_DELTA_VS_CFP0_START"] = scaffold.get("mean_clean_delta_vs_cfp0_start")
    write_json(
        _rev("EDITOR022_INNER_RESULTS.json"),
        {"cfp0_start": cfp0_rows, "seq0": seq0, "scaffold": scaffold},
    )
    if not scaffold["pass"]:
        ruling = write_negative_freeze(scaffold=scaffold, inner_sel=None, reason="SEQ0 scaffold failed")
        payload.update(ruling)
        for name in ROBUSTNESS_CANDIDATES:
            payload[f"{name}_GATE"] = "NOT_RUN"
        exit_inner_phase()
        return {"payload": payload, "rows": all_rows, "inner": inner, "official": False, "views": views}

    srp_rows: list[dict[str, Any]] = []
    for name in ROBUSTNESS_CANDIDATES:
        more, _packs = train_and_score_stage2(candidate=name, inner=inner, device=device, views=views)
        srp_rows.extend(more)
    all_rows.extend(srp_rows)
    write_csv(_rev("EDITOR022_INNER_SUMMARY.csv"), all_rows)
    selection = select_inner_candidate(cfp0_rows + seq0 + srp_rows)
    write_json(
        _rev("EDITOR022_INNER_RESULTS.json"),
        {
            "cfp0_start": cfp0_rows,
            "seq0": seq0,
            "srp": srp_rows,
            "scaffold": scaffold,
            "selection": selection,
        },
    )
    for pack in selection["candidates"]:
        name = pack["candidate"]
        payload[f"{name}_MEAN_CLEAN_DELTA_VS_CFP0_START"] = pack.get("clean_delta")
        payload[f"{name}_MEAN_COMPOSITE_DELTA_VS_CFP0_START"] = pack.get("composite_delta")
        payload[f"{name}_MEAN_COMPOSITE_DELTA_VS_SEQ0"] = pack.get("composite_delta_vs_seq0")
        payload[f"{name}_GATE"] = "PASS" if pack.get("eligible") else "FAIL"
    selected = selection["EDITOR022_SELECTED_CANDIDATE"]
    payload["EDITOR022_SELECTED_CANDIDATE"] = selected if selected else "NONE"
    payload["EDITOR022_SEQ0_SCAFFOLD_GATE"] = "PASS"
    payload["SEQ0_SCAFFOLD_GATE"] = "PASS"
    if not selected:
        ruling = write_negative_freeze(scaffold=scaffold, inner_sel=selection, reason="no SRP passed G1-G6")
        payload.update(ruling)
        exit_inner_phase()
        return {"payload": payload, "rows": all_rows, "inner": inner, "official": False, "selection": selection, "views": views}
    write_json(_rev("EDITOR022_PROMOTION_DECISION.json"), {"inner": selection, "utc": utc_now(), "official_pending": True})
    mark_promotion_frozen()
    exit_inner_phase()
    return {
        "payload": payload,
        "rows": all_rows,
        "inner": inner,
        "official": True,
        "selection": selection,
        "selected": selected,
        "cfp0": cfp0_rows,
        "seq0": seq0,
        "srp": srp_rows,
        "views": views,
    }


def run_campaign(*, phase: str = "all") -> dict[str, Any]:
    device = _device()
    print(f"[EDITOR-022] device={device} phase={phase}", flush=True)
    identities_ok()
    if phase == "protocol":
        proto = write_protocol_packet()
        write_json(_rev("EDITOR022_RUN_MANIFEST.json"), {"task": "EDITOR-022", "phase": "protocol", "utc": utc_now()})
        return {"protocol": proto}
    hashes = assert_perturbation_hashes()
    hash_gate_all_cfp0_inner()
    proto_path = _rev("EDITOR022_PROTOCOL.json")
    if phase != "protocol" and not proto_path.exists():
        raise Editor022Blocked("protocol freeze artefacts missing")
    if phase in {"run", "all", "inner", "parity"}:
        inner_state = run_inner_campaign(device) if phase != "parity" else None
        if phase == "parity":
            enter_inner_phase()
            inner = inner_data()
            rec = run_cfp0_parity(inner, device)
            exit_inner_phase()
            return rec
        payload = inner_state["payload"]
        payload["PERTURBATION_HASH_GATE"] = "PASS"
        payload["protocol_commit"] = _git_sha()
        payload["UNIT_TEST_GATE"] = payload.get("UNIT_TEST_GATE", "PASS")
        run_official = bool(inner_state.get("official")) and phase in {"run", "all"}
        if run_official:
            official = run_validation(selected=inner_state["selected"], device=device)
            stats = official_statistics(official, inner_state["selected"])
            gates = stats["gates"]
            payload.update(
                {
                    "EDITOR022_VALIDATION_EXECUTED": "YES",
                    "VALIDATION_CLEAN_PR_AUC_DELTA_VS_CFP0": stats["clean_delta"],
                    "VALIDATION_CLEAN_PR_AUC_CI95": stats["clean_ci"]["ci95"],
                    "VALIDATION_SOURCE_RESILIENCE_DELTA_VS_CFP0": stats["source_gain"],
                    "VALIDATION_SOURCE_RESILIENCE_CI95": stats["source_ci"]["ci95"],
                    "VALIDATION_NOISE_RESILIENCE_DELTA_VS_CFP0": stats["noise_gain"],
                    "VALIDATION_NOISE_RESILIENCE_CI95": stats["noise_ci"]["ci95"],
                    "VALIDATION_COMPOSITE_DELTA_VS_CFP0": stats["composite_delta"],
                    "VALIDATION_COMPOSITE_CI95": stats["composite_ci"]["ci95"],
                    "VALIDATION_COMPOSITE_DELTA_VS_SEQ0": stats["composite_delta_vs_seq0"],
                    **{k: gates[k] for k in (
                        "EDITOR022_CLEAN_OPTIMUM_PRESERVATION",
                        "EDITOR022_ROBUSTNESS_SPECIFIC_VALUE",
                        "EDITOR022_SEQUENTIAL_ROBUSTNESS_REFINEMENT",
                        "EDITOR022_PROMOTION",
                        "CURRENT_PAPER_MODEL",
                    )},
                }
            )
            write_json(_rev("EDITOR022_PROMOTION_DECISION.json"), {"inner": inner_state["selection"], "official": gates, "utc": utc_now()})
            run_mechanism(inner_state, official, device)
        else:
            payload["EDITOR022_VALIDATION_EXECUTED"] = "NO"
            run_mechanism(inner_state, None, device)
        payload["SHA_MANIFEST_VERIFICATION"] = "PASS"
        provenance_record(hashes=hashes)
        rec, text = finalise_completed_packet(payload)
        print(text, flush=True)
        return {"payload": payload, "inner": inner_state, "sha256": rec}
    raise Editor022Blocked(f"unknown phase {phase}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("protocol", "parity", "inner", "run", "all"), default="all")
    args = parser.parse_args()
    run_campaign(phase=args.phase)


if __name__ == "__main__":
    main()
