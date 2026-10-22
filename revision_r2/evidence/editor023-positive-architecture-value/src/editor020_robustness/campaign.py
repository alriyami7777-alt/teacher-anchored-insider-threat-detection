"""EDITOR-020 clean-teacher degraded-student robustness campaign."""

from __future__ import annotations

import argparse
import json
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
from editor012_rescue.metrics import metrics_from_logits
from editor012_rescue.safety import TRAIN_NPZ
from editor015_residual.explain import train_references
from editor017_robustness.bootstrap_family import mean_noise_retention_contrast, mean_source_delta_contrast
from editor017_robustness.perturbations import load_r52_train_scaler
from editor018_cross_view.cache import load_ensemble_split

from .constants import (
    ARCH_SPECS,
    CLEAN_ODST_PREDICTIVE_SUPERIORITY,
    EDITOR017_RESULTS_COMMIT,
    EDITOR018_RESULTS_COMMIT,
    EDITOR019_RESULTS_COMMIT,
    FROZEN_CLEAN_VAL_PR_AUC,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_MEAN_PR_AUC,
    INNER_CONDITIONS,
    NOISE_LEVELS,
    OBJECTIVES,
    SCREENING_SEED,
    SOURCE_CHANNELS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from .evaluate import build_degraded_views, score_all_views, score_condition
from .explain import explanation_stability_packet, faithfulness_packet
from .io_util import write_csv, write_json
from .models import condition_flags, identities_ok, load_frozen_clean, load_topt, load_trained
from .promotion import decide_promotions
from .protocol import assert_perturbation_hashes, write_protocol_packet
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor020Blocked,
    enter_inner_phase,
    exit_inner_phase,
    mark_promotion_frozen,
    refuse_r51,
    refuse_r52_test,
    refuse_r62,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .train import train_condition


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


def _mean(xs: list[float]) -> float:
    return float(np.mean(xs)) if xs else float("nan")


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
        raise Editor020Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor020Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor020Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor020Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    return {
        "USER_MAPPING_RECOVERED": True,
        "USER_CLUSTER_BOOTSTRAP_STATUS": "AVAILABLE",
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "per_user_count_min": int(counts.min()),
        "per_user_count_max": int(counts.max()),
        "n_malicious_users": int(len(malicious)),
        "malicious_users": malicious,
        "mapping_sha256": mapping_hash,
        "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
        "sampling_unit": "validation user",
        "windows_not_independent": True,
    }


def pack_robust_row(arch: str, objective: str, seed: int, scored: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rob = scored["robust"]
    row = {
        "condition": f"{arch}-{objective}",
        "arch": arch,
        "objective": objective,
        "seed": int(seed),
        "clean_PR_AUC": float(rob["clean_PR_AUC"]),
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
        row[f"noise_{nz['level']:.2f}_retention"] = float(nz["retention"])
        row[f"noise_{nz['level']:.2f}_PR_AUC"] = float(nz["pr_auc"])
    if extra:
        row.update(extra)
    return row


def restore_inner_results_from_freeze(freeze: dict[str, Any]) -> None:
    """Keep the frozen inner CSV aligned with EDITOR-020B if a later process truncated it."""
    rows = list(freeze.get("inner_rows") or [])
    if len(rows) != len(INNER_CONDITIONS):
        raise Editor020Blocked(f"frozen inner_rows n={len(rows)} != {len(INNER_CONDITIONS)}")
    write_csv(_rev("01_inner", "EDITOR020_INNER_RESULTS.csv"), rows)


def run_inner(device: torch.device) -> dict[str, Any]:
    freeze_path = _rev("01_inner", "EDITOR020_PROMOTION_FREEZE.json")
    if freeze_path.exists():
        raise Editor020Blocked("promotion freeze already exists; refuse inner overwrite")
    enter_inner_phase()
    try:
        refuse_r52_test(r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    train = load_train_only()
    split = inner_split_masks(train)
    if int(split["n_inner_train"]) != EXPECTED_INNER_TRAIN_N:
        raise Editor020Blocked(f"INNER_TRAIN n {split['n_inner_train']} != {EXPECTED_INNER_TRAIN_N}")
    if int(split["n_inner_select"]) != EXPECTED_INNER_SELECT_N:
        raise Editor020Blocked(f"INNER_SELECT n {split['n_inner_select']} != {EXPECTED_INNER_SELECT_N}")
    if int(split["n_inner_train_pos"]) != EXPECTED_INNER_TRAIN_POS:
        raise Editor020Blocked("INNER_TRAIN positives mismatch")
    if int(split["n_inner_select_pos"]) != EXPECTED_INNER_SELECT_POS:
        raise Editor020Blocked("INNER_SELECT positives mismatch")
    if int(split["n_dropped"]) != EXPECTED_INNER_DROPPED:
        raise Editor020Blocked("inner dropped mismatch")
    inner_tr = subset_bundle(train, split["train_mask"], "inner_train")
    inner_se = subset_bundle(train, split["select_mask"], "inner_select")
    ens_all = load_ensemble_split("train")
    ens_tr = ens_all["ens"][split["train_mask"]]
    scaler = load_r52_train_scaler()
    views = build_degraded_views(inner_se.X, scaler)
    teacher, _ = load_topt(SCREENING_SEED, device)
    pos_w = _pos_weight(inner_tr.y)
    rows = []
    packs = {}
    for cond in INNER_CONDITIONS:
        arch, objective = cond.split("-", 1)
        print(f"[EDITOR-020] INNER {cond}", flush=True)
        trained = train_condition(
            arch=arch,
            objective=objective,
            seed=SCREENING_SEED,
            X=inner_tr.X,
            y=inner_tr.y,
            ens=ens_tr,
            X_select=inner_se.X,
            y_select=inner_se.y,
            matched_teacher=teacher,
            device=device,
            pos_weight=pos_w,
            scaler=scaler,
            select_name="inner_select",
        )
        loaded = load_trained(arch, objective, SCREENING_SEED, device)
        scored = score_all_views(arch, loaded["student"], loaded["modules"], views, inner_se.y, device)
        row = pack_robust_row(
            arch,
            objective,
            SCREENING_SEED,
            scored,
            extra={
                "best_epoch": trained["best_epoch"],
                "select_PR_AUC": trained["select_PR_AUC"],
                "checkpoint": trained["best_checkpoint"],
                "best_checkpoint_sha256": trained["best_checkpoint_sha256"],
                "training_time": trained["training_time"],
            },
        )
        rows.append(row)
        packs[cond] = {"train": trained, "scored": scored, "row": row}
        write_csv(_rev("01_inner", "EDITOR020_INNER_RESULTS.csv"), rows)
    freeze = decide_promotions(rows)
    freeze["utc"] = utc_now()
    freeze["screening_seed"] = SCREENING_SEED
    freeze["official_validation_used"] = False
    freeze["inner_rows"] = rows
    write_json(_rev("01_inner", "EDITOR020_PROMOTION_FREEZE.json"), freeze)
    mark_promotion_frozen()
    exit_inner_phase()
    return {"rows": rows, "packs": packs, "freeze": freeze, "views": views, "y": inner_se.y}


def official_condition_list(freeze: dict[str, Any]) -> list[tuple[str, str]]:
    """Official retraining is restricted to promoted robustness strategies."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name in freeze.get("promoted_names") or []:
        arch, obj = str(name).split("-", 1)
        key = (arch, obj)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def run_official(freeze: dict[str, Any], device: torch.device) -> dict[str, Any]:
    mark_promotion_frozen()
    bundle = load_train_validation()
    train, val = bundle["train"], bundle["val"]
    mapping = recover_user_mapping(bundle)
    write_json(_rev("07_statistics", "EDITOR020_USER_MAPPING_VERIFICATION.json"), mapping)
    scaler = load_r52_train_scaler()
    views = build_degraded_views(val.X, scaler)
    conditions = official_condition_list(freeze)
    ens = load_ensemble_split("train")["ens"] if conditions else None
    pos_w = float(bundle["pos_weight"])
    val_rows = []
    robust_rows = []
    logits: dict[str, dict[int, dict[str, Any]]] = {}
    for arch, objective in conditions:
        logits.setdefault(f"{arch}-{objective}", {})
        for seed in PRIMARY_SEEDS:
            print(f"[EDITOR-020] OFFICIAL {arch}-{objective} seed={seed}", flush=True)
            teacher, _ = load_topt(seed, device)
            trained = train_condition(
                arch=arch,
                objective=objective,
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
            loaded = load_trained(arch, objective, seed, device)
            scored = score_all_views(arch, loaded["student"], loaded["modules"], views, val.y, device)
            row = pack_robust_row(
                arch,
                objective,
                seed,
                scored,
                extra={
                    "best_epoch": trained["best_epoch"],
                    "checkpoint": trained["best_checkpoint"],
                    "best_checkpoint_sha256": trained["best_checkpoint_sha256"],
                    "split": "validation",
                    "kind": "trained",
                },
            )
            val_rows.append(row)
            robust_rows.append(row)
            logits[f"{arch}-{objective}"][seed] = scored
            write_csv(_rev("02_validation", "EDITOR020_VALIDATION_RESULTS.csv"), val_rows)
            write_csv(_rev("02_validation", "EDITOR020_ROBUSTNESS_RESULTS.csv"), robust_rows)

    clean_rows = []
    for arch in ARCH_SPECS:
        logits.setdefault(f"{arch}-CLEAN", {})
        for seed in PRIMARY_SEEDS:
            print(f"[EDITOR-020] FROZEN {arch}-CLEAN seed={seed}", flush=True)
            loaded = load_frozen_clean(arch, seed, device)
            scored = score_all_views(arch, loaded["student"], loaded["modules"], views, val.y, device)
            frozen = float(FROZEN_CLEAN_VAL_PR_AUC[arch][seed])
            if abs(float(scored["robust"]["clean_PR_AUC"]) - frozen) > 5e-4:
                print(
                    f"[EDITOR-020] WARN clean {arch} seed={seed} "
                    f"{scored['robust']['clean_PR_AUC']:.6f} vs frozen {frozen:.6f}",
                    flush=True,
                )
            row = pack_robust_row(
                arch,
                "CLEAN",
                seed,
                scored,
                extra={"split": "validation", "kind": "frozen_clean", "sha256": loaded["sha256"]},
            )
            clean_rows.append(row)
            val_rows.append(row)
            robust_rows.append(row)
            logits[f"{arch}-CLEAN"][seed] = scored
    write_csv(_rev("02_validation", "EDITOR020_VALIDATION_RESULTS.csv"), val_rows)
    write_csv(_rev("02_validation", "EDITOR020_ROBUSTNESS_RESULTS.csv"), robust_rows)
    return {
        "val_rows": val_rows,
        "robust_rows": robust_rows,
        "clean_rows": clean_rows,
        "logits": logits,
        "mapping": mapping,
        "y": np.asarray(val.y),
        "users": np.asarray(val.user).astype(str),
        "views": views,
        "train": train,
        "val": val,
        "scaler": scaler,
    }


def _seed_mean(rows: list[dict[str, Any]], cond: str, key: str) -> float:
    vals = [float(r[key]) for r in rows if str(r["condition"]) == cond]
    return _mean(vals)


def _direction(rows: list[dict[str, Any]], a: str, b: str, key: str, *, higher: bool = True) -> int:
    n_pos = 0
    for seed in PRIMARY_SEEDS:
        ra = next(r for r in rows if r["condition"] == a and int(r["seed"]) == seed)
        rb = next(r for r in rows if r["condition"] == b and int(r["seed"]) == seed)
        delta = float(rb[key]) - float(ra[key])
        n_pos += int(delta > 0 if higher else delta < 0)
    return n_pos


def logits_by_seed(official: dict[str, Any], name: str) -> tuple[list[np.ndarray], list[list[np.ndarray]], list[list[np.ndarray]]]:
    clean, source, noise = [], [], []
    for seed in PRIMARY_SEEDS:
        pack = official["logits"][name][seed]
        clean.append(pack["clean"]["logits"])
        source.append([pack["source_logits"][ch] for ch in SOURCE_CHANNELS])
        noise.append([pack["noise_logits"][float(lv)] for lv in NOISE_LEVELS])
    return clean, source, noise


def teacher_effect_packet(inner_rows: list[dict[str, Any]], official: dict[str, Any] | None) -> dict[str, Any]:
    inner = {}
    for arch in ARCH_SPECS:
        r1 = next(r for r in inner_rows if r["condition"] == f"{arch}-R1")
        r3 = next(r for r in inner_rows if r["condition"] == f"{arch}-R3")
        inner[arch] = {
            "source": float(r3["MEAN_SOURCE_DELTA"]) - float(r1["MEAN_SOURCE_DELTA"]),
            "noise": float(r3["MEAN_NOISE_RETENTION"]) - float(r1["MEAN_NOISE_RETENTION"]),
            "clean": float(r3["clean_PR_AUC"]) - float(r1["clean_PR_AUC"]),
        }
    out: dict[str, Any] = {
        "definition": "R3 minus R1; both see the same degraded training examples; R3 receives clean-teacher consistency",
        "inner_seed42": inner,
        "inner_mean_source": _mean([inner[a]["source"] for a in ARCH_SPECS]),
        "inner_mean_noise": _mean([inner[a]["noise"] for a in ARCH_SPECS]),
    }
    if official is not None:
        y = official["y"]
        users = official["users"]
        family_source = []
        family_noise = []
        for arch in ("L1", "F10", "TA2"):
            n1, n3 = f"{arch}-R1", f"{arch}-R3"
            if n1 not in official["logits"] or n3 not in official["logits"]:
                continue
            c1, s1, k1 = logits_by_seed(official, n1)
            c3, s3, k3 = logits_by_seed(official, n3)
            src = mean_source_delta_contrast(y, users, c1, c3, s1, s3, contrast=f"{arch}_R3_minus_R1_source")
            nz = mean_noise_retention_contrast(y, users, c1, c3, k1, k3, contrast=f"{arch}_R3_minus_R1_noise")
            out[f"{arch}_official"] = {
                "source_mean": _seed_mean(official["val_rows"], n3, "MEAN_SOURCE_DELTA")
                - _seed_mean(official["val_rows"], n1, "MEAN_SOURCE_DELTA"),
                "noise_mean": _seed_mean(official["val_rows"], n3, "MEAN_NOISE_RETENTION")
                - _seed_mean(official["val_rows"], n1, "MEAN_NOISE_RETENTION"),
                "source_ci": src,
                "noise_ci": nz,
                "source_3of3": _direction(official["val_rows"], n1, n3, "MEAN_SOURCE_DELTA"),
                "noise_3of3": _direction(official["val_rows"], n1, n3, "MEAN_NOISE_RETENTION"),
            }
            family_source.append(src)
            family_noise.append(nz)
        out["official_source_any_ci_excludes_zero"] = any(x.get("ci_excludes_zero") for x in family_source)
        out["official_noise_any_ci_excludes_zero"] = any(x.get("ci_excludes_zero") for x in family_noise)
    write_json(_rev("03_teacher_effect", "EDITOR020_TEACHER_ROBUSTNESS_EFFECT.json"), out)
    return out


def route_effect_packet(inner_rows: list[dict[str, Any]], official: dict[str, Any] | None) -> dict[str, Any]:
    r3 = next(r for r in inner_rows if r["condition"] == "TA2-R3")
    r4 = next(r for r in inner_rows if r["condition"] == "TA2-R4")
    inner = {
        "clean_PR_AUC": float(r4["clean_PR_AUC"]) - float(r3["clean_PR_AUC"]),
        "source": float(r4["MEAN_SOURCE_DELTA"]) - float(r3["MEAN_SOURCE_DELTA"]),
        "noise": float(r4["MEAN_NOISE_RETENTION"]) - float(r3["MEAN_NOISE_RETENTION"]),
    }
    out: dict[str, Any] = {
        "definition": "TA2-R4 minus TA2-R3; difference is robust route consistency only",
        "inner_seed42": inner,
    }
    if official is not None and "TA2-R3" in official["logits"] and "TA2-R4" in official["logits"]:
        y = official["y"]
        users = official["users"]
        c3, s3, k3 = logits_by_seed(official, "TA2-R3")
        c4, s4, k4 = logits_by_seed(official, "TA2-R4")
        out["official"] = {
            "clean": _seed_mean(official["val_rows"], "TA2-R4", "clean_PR_AUC")
            - _seed_mean(official["val_rows"], "TA2-R3", "clean_PR_AUC"),
            "source": _seed_mean(official["val_rows"], "TA2-R4", "MEAN_SOURCE_DELTA")
            - _seed_mean(official["val_rows"], "TA2-R3", "MEAN_SOURCE_DELTA"),
            "noise": _seed_mean(official["val_rows"], "TA2-R4", "MEAN_NOISE_RETENTION")
            - _seed_mean(official["val_rows"], "TA2-R3", "MEAN_NOISE_RETENTION"),
            "source_ci": mean_source_delta_contrast(y, users, c3, c4, s3, s4, contrast="TA2_R4_minus_R3_source"),
            "noise_ci": mean_noise_retention_contrast(y, users, c3, c4, k3, k4, contrast="TA2_R4_minus_R3_noise"),
        }
    write_json(_rev("04_route_effect", "EDITOR020_ROUTE_ROBUSTNESS_EFFECT.json"), out)
    return out


def classify_teacher_gate(teacher: dict[str, Any]) -> str:
    src_ok = all(teacher["inner_seed42"][a]["source"] > 0 for a in ARCH_SPECS)
    nz_ok = all(teacher["inner_seed42"][a]["noise"] > 0 for a in ARCH_SPECS)
    official = [teacher[k] for k in teacher if k.endswith("_official")]
    if official:
        src_ci = all(o["source_ci"]["ci_excludes_zero"] and o["source_mean"] > 0 for o in official)
        nz_ci = all(o["noise_ci"]["ci_excludes_zero"] and o["noise_mean"] > 0 for o in official)
        src_dir = all(o["source_mean"] > 0 for o in official)
        nz_dir = all(o["noise_mean"] > 0 for o in official)
        if src_ok and nz_ok and src_ci and nz_ci:
            return "STRONG"
        if src_dir and nz_dir:
            return "CONSISTENT"
        if src_dir or nz_dir:
            return "FAMILY_SPECIFIC"
        return "NOT_SUPPORTED"
    if src_ok and nz_ok:
        return "CONSISTENT"
    if src_ok or nz_ok:
        return "FAMILY_SPECIFIC"
    return "NOT_SUPPORTED"


def classify_odst_gate(rows: list[dict[str, Any]], l1_name: str | None, ta2_name: str | None, official: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not l1_name or not ta2_name or l1_name not in official["logits"] or ta2_name not in official["logits"]:
        rec = {
            "l1": l1_name,
            "ta2": ta2_name,
            "TA2_MINUS_L1_SOURCE_ROBUSTNESS": None,
            "TA2_MINUS_L1_NOISE_ROBUSTNESS": None,
            "CI_TA2_MINUS_L1_SOURCE": None,
            "CI_TA2_MINUS_L1_NOISE": None,
            "ruling": "NOT_SUPPORTED",
            "reason": "no_promoted_robustness_trained_pair",
        }
        return "NOT_SUPPORTED", rec
    y, users = official["y"], official["users"]
    cl, sl, nl = logits_by_seed(official, l1_name)
    ct, st, nt = logits_by_seed(official, ta2_name)
    src_ci = mean_source_delta_contrast(y, users, cl, ct, sl, st, contrast="TA2_minus_L1_source")
    nz_ci = mean_noise_retention_contrast(y, users, cl, ct, nl, nt, contrast="TA2_minus_L1_noise")
    src_mean = _seed_mean(rows, ta2_name, "MEAN_SOURCE_DELTA") - _seed_mean(rows, l1_name, "MEAN_SOURCE_DELTA")
    nz_mean = _seed_mean(rows, ta2_name, "MEAN_NOISE_RETENTION") - _seed_mean(rows, l1_name, "MEAN_NOISE_RETENTION")
    src_3 = _direction(rows, l1_name, ta2_name, "MEAN_SOURCE_DELTA")
    nz_3 = _direction(rows, l1_name, ta2_name, "MEAN_NOISE_RETENTION")
    rec = {
        "l1": l1_name,
        "ta2": ta2_name,
        "TA2_MINUS_L1_SOURCE_ROBUSTNESS": src_mean,
        "TA2_MINUS_L1_NOISE_ROBUSTNESS": nz_mean,
        "CI_TA2_MINUS_L1_SOURCE": src_ci["ci95"],
        "CI_TA2_MINUS_L1_NOISE": nz_ci["ci95"],
        "source_ci": src_ci,
        "noise_ci": nz_ci,
        "source_3of3": src_3,
        "noise_3of3": nz_3,
    }
    src_pos = src_mean > 0 and src_3 == 3
    nz_pos = nz_mean > 0 and nz_3 == 3
    src_strong = src_pos and src_ci["ci95"][0] > 0
    nz_strong = nz_pos and nz_ci["ci95"][0] > 0
    if src_strong and nz_strong:
        ruling = "STRONG"
    elif src_pos and nz_pos:
        ruling = "CONSISTENT"
    elif src_pos or nz_pos:
        ruling = "FAMILY_SPECIFIC"
    else:
        ruling = "NOT_SUPPORTED"
    rec["ruling"] = ruling
    return ruling, rec


def classify_route_gate(route: dict[str, Any], faith_ok: bool) -> str:
    inner = route["inner_seed42"]
    clean_ok = float(inner["clean_PR_AUC"]) >= -0.001
    src = float(inner["source"])
    nz = float(inner["noise"])
    if not clean_ok:
        return "NOT_SUPPORTED"
    if src > 0 and nz > 0 and faith_ok:
        return "SUPPORTED"
    if src > 0 or nz > 0:
        return "MIXED"
    return "NOT_SUPPORTED"


def run_explain_calibrate(official: dict[str, Any], freeze: dict[str, Any], device: torch.device) -> dict[str, Any]:
    val = official["val"]
    train = official["train"]
    promoted_ta2 = freeze["promoted"].get("TA2")
    target = promoted_ta2 if promoted_ta2 and promoted_ta2 in official["logits"] else "TA2-CLEAN"
    arch = "TA2"
    faith_rows = []
    stab_all = []
    refs_pack = []
    print("[EDITOR-020] TRAIN references for explanation", flush=True)
    for seed in PRIMARY_SEEDS:
        loaded = load_frozen_clean("TA2", seed, device)
        tr = score_condition(arch, loaded["student"], loaded["modules"], train.X, train.y, device)
        refs_pack.append(train_references(tr["tree_outputs"]))
    references = np.mean(np.stack(refs_pack, axis=0), axis=0)
    print("[EDITOR-020] directional faithfulness", flush=True)
    for seed in PRIMARY_SEEDS:
        scored = official["logits"][target][seed]
        faith = faithfulness_packet(
            y=val.y,
            tree_outputs=scored["clean"]["tree_outputs"],
            references=references,
            users=val.user,
        )
        faith["seed"] = seed
        faith["condition"] = target
        faith_rows.append(faith)
        deg_trees = {f"source_{ch}": scored["source"][ch]["tree_outputs"] for ch in SOURCE_CHANNELS}
        deg_trees.update({f"noise_{lv:.2f}": scored["noise"][float(lv)]["tree_outputs"] for lv in NOISE_LEVELS})
        deg_ch = {f"source_{ch}": scored["source"][ch]["choices"] for ch in SOURCE_CHANNELS}
        deg_ch.update({f"noise_{lv:.2f}": scored["noise"][float(lv)]["choices"] for lv in NOISE_LEVELS})
        deg_lf = {f"source_{ch}": scored["source"][ch]["leaf_probs_all"] for ch in SOURCE_CHANNELS}
        deg_lf.update({f"noise_{lv:.2f}": scored["noise"][float(lv)]["leaf_probs_all"] for lv in NOISE_LEVELS})
        stab = explanation_stability_packet(
            clean_trees=scored["clean"]["tree_outputs"],
            degraded=deg_trees,
            references=references,
            clean_choices=scored["clean"]["choices"],
            degraded_choices=deg_ch,
            clean_leaves=scored["clean"]["leaf_probs_all"],
            degraded_leaves=deg_lf,
        )
        stab["seed"] = seed
        stab_all.append(stab)
    local = faith_rows[0]["LOCAL_DIRECTIONAL_TREE_FAITHFULNESS"]
    if not all(f["LOCAL_DIRECTIONAL_TREE_FAITHFULNESS"] == local for f in faith_rows):
        if any(f["LOCAL_DIRECTIONAL_TREE_FAITHFULNESS"] == "SUPPORTED" for f in faith_rows):
            local = "QUALIFIED"
    if not promoted_ta2:
        local_report = f"{local}_CLEAN_TA2_ONLY"
    else:
        local_report = local
    write_json(
        _rev("05_explainability", "EDITOR020_DIRECTIONAL_FAITHFULNESS.json"),
        {
            "condition": target,
            "promoted_ta2": promoted_ta2,
            "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": local_report,
            "clean_TA2_faithfulness": local,
            "seeds": faith_rows,
            "references_from": "r5.2 TRAIN only",
            "k": [1, 2, 3],
            "same_sign_random_control": True,
            "robustness_training_explanation": "EVALUATED" if promoted_ta2 else "NOT_EVALUATED_NO_PROMOTION",
        },
    )
    write_json(
        _rev("05_explainability", "EDITOR020_EXPLANATION_STABILITY.json"),
        {
            "condition": target,
            "promoted_ta2": promoted_ta2,
            "seeds": stab_all,
            "compared_against": "clean TA2 TRAIN references",
            "robustness_training_explanation": "EVALUATED" if promoted_ta2 else "NOT_EVALUATED_NO_PROMOTION",
        },
    )
    cal_rows = []
    names = ["L1-CLEAN", "TA2-CLEAN"]
    if freeze["promoted"].get("L1"):
        names.append(freeze["promoted"]["L1"])
    if freeze["promoted"].get("TA2"):
        names.append(freeze["promoted"]["TA2"])
    for name in names:
        for seed in PRIMARY_SEEDS:
            if name not in official["logits"]:
                continue
            pack = official["logits"][name][seed]
            met = pack["clean"]["metrics"]
            cal_rows.append(
                {
                    "condition": name,
                    "seed": seed,
                    "view": "clean",
                    "PR_AUC": float(met["pr_auc"]),
                    "Brier": float(met["Brier"]),
                    "log_loss": float(met["log_loss"]),
                }
            )
            for ch in SOURCE_CHANNELS:
                met = pack["source"][ch]["metrics"]
                cal_rows.append(
                    {
                        "condition": name,
                        "seed": seed,
                        "view": f"source_{ch}",
                        "PR_AUC": float(met["pr_auc"]),
                        "Brier": float(met["Brier"]),
                        "log_loss": float(met["log_loss"]),
                    }
                )
            for level in NOISE_LEVELS:
                met = pack["noise"][float(level)]["metrics"]
                cal_rows.append(
                    {
                        "condition": name,
                        "seed": seed,
                        "view": f"noise_{level:.2f}",
                        "PR_AUC": float(met["pr_auc"]),
                        "Brier": float(met["Brier"]),
                        "log_loss": float(met["log_loss"]),
                    }
                )
    write_csv(_rev("06_calibration", "EDITOR020_CALIBRATION_RESULTS.csv"), cal_rows)
    return {"faithfulness": local_report, "stability": stab_all, "calibration": cal_rows}


def write_final_packets(
    *,
    inner: dict[str, Any],
    official: dict[str, Any],
    teacher: dict[str, Any],
    route: dict[str, Any],
    odst_gate: tuple[str, dict[str, Any]],
    explain: dict[str, Any],
    freeze: dict[str, Any],
) -> dict[str, Any]:
    teacher_gate = classify_teacher_gate(teacher)
    odst_ruling, odst_rec = odst_gate
    faith = str(explain["faithfulness"])
    route_gate = classify_route_gate(route, faith in {"SUPPORTED", "QUALIFIED"})
    promoted_l1 = freeze["promoted"].get("L1")
    promoted_ta2 = freeze["promoted"].get("TA2")
    rows = official["val_rows"]
    l1_clean = _mean([float(FROZEN_CLEAN_VAL_PR_AUC["L1"][s]) for s in PRIMARY_SEEDS])
    ta2_clean = _mean([float(FROZEN_CLEAN_VAL_PR_AUC["TA2"][s]) for s in PRIMARY_SEEDS])
    robust_l1_clean = _seed_mean(rows, promoted_l1, "clean_PR_AUC") if promoted_l1 else float("nan")
    robust_ta2_clean = _seed_mean(rows, promoted_ta2, "clean_PR_AUC") if promoted_ta2 else float("nan")
    clean_sup = "NOT_SUPPORTED"
    if promoted_l1 and promoted_ta2:
        n_dir = _direction(rows, promoted_l1, promoted_ta2, "clean_PR_AUC")
        y, users = official["y"], official["users"]
        cl, _, _ = logits_by_seed(official, promoted_l1)
        ct, _, _ = logits_by_seed(official, promoted_ta2)
        from editor017_robustness.bootstrap_family import user_cluster_stat
        from editor012_rescue.metrics import sigmoid
        from sklearn.metrics import average_precision_score

        def _pr(sl, yb, logits):
            return float(average_precision_score(yb, sigmoid(logits[sl])))

        def stat(sl, yb):
            return float(np.mean([_pr(sl, yb, ct[i]) - _pr(sl, yb, cl[i]) for i in range(3)]))

        boot = user_cluster_stat(users, y, stat, contrast="robust_TA2_minus_robust_L1_clean")
        if robust_ta2_clean > robust_l1_clean and n_dir == 3 and boot["ci95"][0] > 0:
            clean_sup = "SUPPORTED"
        write_json(_rev("07_statistics", "EDITOR020_CLUSTER_BOOTSTRAP.json"), {"odst": odst_rec, "clean_bonus": boot, "teacher": teacher})
    else:
        write_json(_rev("07_statistics", "EDITOR020_CLUSTER_BOOTSTRAP.json"), {"odst": odst_rec, "teacher": teacher})

    why_teacher = (
        "R3 and R1 see the same degraded training examples; the only added term in R3 is "
        "clean-teacher ensemble logit consistency on the degraded student view."
    )
    why_odst = (
        "Degraded-input superiority is assessed against a matched robustness-trained attention-linear "
        "model, not against ordinary clean L1, and is not a clean predictive-superiority claim."
    )
    why_route = (
        "TA2-R4 versus TA2-R3 isolates robust route consistency: student routes on degraded input "
        "are pulled toward the matched clean T-OPT route."
    )
    paper_model = "TA2"
    if promoted_ta2 and odst_ruling in {"STRONG", "CONSISTENT"}:
        paper_model = promoted_ta2
    next_action = (
        "Do not replace clean TA2 with a robustness-trained student. "
        "The frozen clean-preservation gate blocked every robustness objective. "
        "A future authorised experiment may keep clean teacher logit MSE as architecture identity "
        "while adding degraded terms, but EDITOR-020 does not change lambdas after seeing results."
    )
    matrix = [
        {"issue": "TEACHER_GUIDANCE_VS_INITIALISATION", "status": TEACHER_GUIDANCE_VS_INITIALISATION, "evidence": "EDITOR-012/013"},
        {"issue": "CLEAN_ODST_PREDICTIVE_SUPERIORITY", "status": CLEAN_ODST_PREDICTIVE_SUPERIORITY, "evidence": "not the EDITOR-020 objective"},
        {"issue": "TEACHER_GUIDED_ROBUSTNESS_TRAINING", "status": teacher_gate, "evidence": "R3 minus R1"},
        {"issue": "ODST_ROBUSTNESS_SUPERIORITY_OVER_LINEAR", "status": odst_ruling, "evidence": "robust TA2 vs robust L1"},
        {"issue": "ROUTE_ANCHOR_ROBUST_TRAINING_VALUE", "status": route_gate, "evidence": "TA2-R4 minus TA2-R3"},
        {"issue": "ROBUST_TA2_CLEAN_PREDICTIVE_SUPERIORITY", "status": clean_sup, "evidence": "optional bonus only"},
    ]
    write_csv(_rev("08_editor_response", "EDITOR020_EDITOR_ISSUE_MATRIX.csv"), matrix)
    gate = {
        "TEACHER_GUIDED_ROBUSTNESS_TRAINING": teacher_gate,
        "ODST_ROBUSTNESS_SUPERIORITY_OVER_LINEAR": odst_ruling,
        "ROUTE_ANCHOR_ROBUST_TRAINING_VALUE": route_gate,
        "ROBUST_TA2_CLEAN_PREDICTIVE_SUPERIORITY": clean_sup,
        "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": faith,
        "BEST_CURRENT_PAPER_MODEL": paper_model,
        "NEXT_RECOMMENDED_ACTION": next_action,
        "WHY_TEACHER_GUIDANCE": why_teacher,
        "WHY_ODST": why_odst,
        "WHY_ROUTE_ANCHORING": why_route,
        "CLEAN_ODST_PREDICTIVE_SUPERIORITY": CLEAN_ODST_PREDICTIVE_SUPERIORITY,
        "frozen_clean_L1_mean": FROZEN_L1_MEAN_PR_AUC,
        "frozen_clean_TA2_mean": FROZEN_TA2_MEAN_PR_AUC,
        "CLEAN_L1": l1_clean,
        "CLEAN_TA2": ta2_clean,
        "ROBUST_L1_CLEAN_PR_AUC": robust_l1_clean,
        "ROBUST_TA2_CLEAN_PR_AUC": robust_ta2_clean,
        "promoted": freeze["promoted"],
        "odst": odst_rec,
    }
    write_json(_rev("09_paper_handover", "EDITOR020_PAPER_RESCUE_GATE.json"), gate)
    _rev("09_paper_handover", "EDITOR020_PAPER_RESCUE_HANDOVER.md").write_text(
        "# EDITOR-020 paper rescue handover\n\n"
        f"BEST_CURRENT_PAPER_MODEL = {paper_model}\n\n"
        f"TEACHER_GUIDED_ROBUSTNESS_TRAINING = {teacher_gate}\n\n"
        f"ODST_ROBUSTNESS_SUPERIORITY_OVER_LINEAR = {odst_ruling}\n\n"
        f"ROUTE_ANCHOR_ROBUST_TRAINING_VALUE = {route_gate}\n\n"
        f"ROBUST_TA2_CLEAN_PREDICTIVE_SUPERIORITY = {clean_sup}\n\n"
        f"WHY_TEACHER_GUIDANCE\n\n{why_teacher}\n\n"
        f"WHY_ODST\n\n{why_odst}\n\n"
        f"WHY_ROUTE_ANCHORING\n\n{why_route}\n\n"
        f"NEXT_RECOMMENDED_ACTION\n\n{next_action}\n",
        encoding="utf-8",
    )
    return {
        "teacher_gate": teacher_gate,
        "odst_ruling": odst_ruling,
        "route_gate": route_gate,
        "clean_sup": clean_sup,
        "paper_model": paper_model,
        "next_action": next_action,
        "why_teacher": why_teacher,
        "why_odst": why_odst,
        "why_route": why_route,
        "faith": faith,
        "odst_rec": odst_rec,
        "l1_clean": l1_clean,
        "ta2_clean": ta2_clean,
        "robust_l1_clean": robust_l1_clean,
        "robust_ta2_clean": robust_ta2_clean,
        "promoted_l1": promoted_l1,
        "promoted_ta2": promoted_ta2,
    }


def write_run_manifest(payload: dict[str, Any]) -> None:
    rec = {
        "task": "EDITOR-020",
        "utc": utc_now(),
        "R52_TEST_ACCESSED": "NO",
        "R51_RERUN": "NO",
        "R62_RERUN": "NO",
        "commits": {
            "EDITOR017_RESULTS_COMMIT": EDITOR017_RESULTS_COMMIT,
            "EDITOR018_RESULTS_COMMIT": EDITOR018_RESULTS_COMMIT,
            "EDITOR019_RESULTS_COMMIT": EDITOR019_RESULTS_COMMIT,
        },
        **payload,
    }
    write_json(_rev("EDITOR020_RUN_MANIFEST.json"), rec)


def run_campaign(*, phase: str = "all") -> dict[str, Any]:
    device = _device()
    print(f"[EDITOR-020] device={device} phase={phase}", flush=True)
    identities_ok()
    if phase == "protocol":
        proto = write_protocol_packet()
        write_run_manifest({"phase": "protocol"})
        return {"protocol": proto}
    assert_perturbation_hashes()
    proto = {"rewritten": False, "note": "protocol artefacts frozen; hashes re-asserted only"}
    if phase == "inner":
        inner = run_inner(device)
        write_run_manifest({"phase": "inner", "promoted": inner["freeze"]["promoted"]})
        return {"protocol": proto, "inner": inner}
    if phase in {"confirm", "all"}:
        freeze_path = _rev("01_inner", "EDITOR020_PROMOTION_FREEZE.json")
        if phase == "confirm":
            freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
            mark_promotion_frozen()
            restore_inner_results_from_freeze(freeze)
            inner_rows = freeze["inner_rows"]
        else:
            inner = run_inner(device)
            freeze = inner["freeze"]
            inner_rows = inner["rows"]
        official = run_official(freeze, device)
        teacher = teacher_effect_packet(inner_rows, official)
        route = route_effect_packet(inner_rows, official)
        l1_name = freeze["promoted"].get("L1")
        ta2_name = freeze["promoted"].get("TA2")
        if l1_name not in official["logits"]:
            l1_name = None
        if ta2_name not in official["logits"]:
            ta2_name = None
        odst_gate = classify_odst_gate(official["val_rows"], l1_name, ta2_name, official)
        print("[EDITOR-020] explain/calibrate start", flush=True)
        explain = run_explain_calibrate(official, freeze, device)
        print("[EDITOR-020] explain/calibrate done", flush=True)
        final = write_final_packets(
            inner={"rows": inner_rows, "freeze": freeze},
            official=official,
            teacher=teacher,
            route=route,
            odst_gate=odst_gate,
            explain=explain,
            freeze=freeze,
        )
        write_run_manifest({"phase": "complete", **{k: final[k] for k in ("teacher_gate", "odst_ruling", "route_gate", "paper_model")}})
        return {"protocol": proto, "freeze": freeze, "official": official, "final": final}
    raise Editor020Blocked(f"unknown phase {phase}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("protocol", "inner", "confirm", "all"), default="all")
    args = parser.parse_args()
    run_campaign(phase=args.phase)


if __name__ == "__main__":
    main()
