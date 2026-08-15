"""EDITOR-012 autonomous teacher-anchor rescue orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .bootstrap import paired_user_cluster_mean_across_seeds
from .constants import (
    ANCHOR_FORMULATIONS,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    C2OPT_CHECKPOINTS,
    ENCODER_ARCH,
    ET1_LOGIT_DISTILL_WEIGHT,
    EXPECTED_INNER_DROPPED,
    EXPECTED_INNER_SELECT_N,
    EXPECTED_INNER_SELECT_POS,
    EXPECTED_INNER_TRAIN_N,
    EXPECTED_INNER_TRAIN_POS,
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_MALICIOUS_USERS,
    EXPECTED_VAL_USERS,
    EXPECTED_VAL_WINDOWS_PER_USER,
    EXTENDED_SEEDS,
    FACTORIAL,
    HISTORICAL,
    LAMBDA_ROUTE,
    ODST046,
    ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR,
    PRIMARY_SEEDS,
    R2OPT_CHECKPOINTS,
    SCREENING_SEED,
    TOPT_CHECKPOINTS,
)
from .data import load_train_validation, make_xy_loader, subset_bundle
from .evaluate import evaluate_pair, hash_gate_checkpoint
from .freeze import write_protocol_packet
from .inner_split import inner_split_masks
from .io_util import write_csv, write_json
from .metrics import sigmoid
from .models import (
    architecture_identity,
    assert_odst046,
    assert_teacher_student_match,
    enable_student,
    freeze_teacher,
    state_dict_sha256,
)
from .producing import build_odst046_model, import_set_seed, load_state_dict, pin_producing_sources
from .promotion import decide_promotions
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor012Blocked,
    Editor012ProtocolError,
    refuse_historical_write,
    refuse_r52_test,
    sha256_bytes,
    utc_now,
)
from .train import train_student

RESULT_COLS = [
    "condition",
    "seed",
    "validation_PR_AUC",
    "validation_F1",
    "precision",
    "recall",
    "FP",
    "FN",
    "Brier",
    "log_loss",
    "predicted_positive_fraction",
    "best_epoch",
    "best_checkpoint_sha256",
    "ensemble_on",
    "route_on",
]


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    refuse_historical_write(path)
    return path


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _set_seed(seed: int) -> None:
    set_seed = import_set_seed()
    set_seed(int(seed))
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def _mean(xs: list[float]) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def verify_identities() -> dict[str, Any]:
    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor012Blocked("r5.2 TEST deny-list failed to fire")
    except Editor012ProtocolError as exc:
        if "TEST" not in str(exc):
            raise
    pins = pin_producing_sources()
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4 or float(ODST046["temperature"]) != 0.5:
        raise Editor012Blocked("ODST-046 lock mismatch")
    if abs(float(ODST046["lr"]) - 1e-3) > 1e-15 or float(ODST046["weight_decay"]) != 0.0:
        raise Editor012Blocked("ODST-046 optimiser lock mismatch")
    if ET1_LOGIT_DISTILL_WEIGHT != 0.5:
        raise Editor012Blocked("ET1 lambda mismatch")
    teacher = build_odst046_model()
    student = build_odst046_model()
    assert_odst046(teacher)
    assert_odst046(student)
    assert_teacher_student_match(teacher, student)
    return {
        "r52_test_hard_denied": True,
        "odst046_identity_verified": True,
        "et1_lambda": ET1_LOGIT_DISTILL_WEIGHT,
        "et1_temperature": None,
        "producing_pins": pins,
        "architecture": architecture_identity(teacher),
        "ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR": ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR,
    }


def load_frozen_model(spec: dict[str, Any], device: torch.device) -> torch.nn.Module:
    hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    model = build_odst046_model()
    load_state_dict(model, spec["checkpoint"], strict=True)
    model.to(device)
    freeze_teacher(model)
    assert_odst046(model)
    return model


def student_from_topt(seed: int, device: torch.device) -> tuple[torch.nn.Module, str]:
    spec = TOPT_CHECKPOINTS[seed]
    start_sha = hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    student = build_odst046_model()
    load_state_dict(student, spec["checkpoint"], strict=True)
    student.to(device)
    enable_student(student)
    assert_odst046(student)
    return student, start_sha


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor012Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor012Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor012Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor012Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
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
        "hash_matches_EDITOR011": True,
        "EDITOR011_mapping_sha256": EXPECTED_USER_MAPPING_SHA256,
    }


@torch.no_grad()
def score_logits(model: torch.nn.Module, X: np.ndarray, y: np.ndarray, device: torch.device, seed: int = 0) -> np.ndarray:
    loader = make_xy_loader(X, y, seed=seed, shuffle=False)
    model.eval()
    out = []
    from .models import student_forward

    for xb, _ in loader:
        logit = student_forward(model, xb.to(device))["logit"]
        out.append(logit.detach().cpu().numpy())
    return np.concatenate(out)


def precompute_ensemble(
    teachers: dict[int, torch.nn.Module],
    X: np.ndarray,
    y: np.ndarray,
    device: torch.device,
    cache_name: str,
) -> dict[str, np.ndarray]:
    cache_dir = OUTPUT_ROOT / "ensemble_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = {k: cache_dir / f"{cache_name}_{k}.npy" for k in ("logit42", "logit52", "logit62", "ens_logit")}
    if all(p.is_file() for p in paths.values()):
        return {k: np.load(p) for k, p in paths.items()}
    logits = {}
    for seed in PRIMARY_SEEDS:
        print(f"[EDITOR-012] scoring T-OPT({seed}) on {cache_name}", flush=True)
        logits[seed] = score_logits(teachers[seed], X, y, device)
        np.save(paths[f"logit{seed}"], logits[seed])
    ens = np.mean([logits[s] for s in PRIMARY_SEEDS], axis=0)
    np.save(paths["ens_logit"], ens)
    return {"logit42": logits[42], "logit52": logits[52], "logit62": logits[62], "ens_logit": ens}


def _probs(logits: np.ndarray) -> np.ndarray:
    return sigmoid(logits).astype(np.float32)


def _anchor_kwargs(anchor_id: str) -> dict[str, bool]:
    spec = ANCHOR_FORMULATIONS[anchor_id]
    return {
        "confidence_weight": bool(spec["confidence_weight"]),
        "agreement_weight": bool(spec["agreement_weight"]),
        "class_balanced": bool(spec["class_balanced_reduction"]),
    }


def _pack_row(pack: dict[str, Any], *, condition: str | None = None) -> dict[str, Any]:
    row = {k: pack.get(k, "") for k in RESULT_COLS}
    if condition:
        row["condition"] = condition
    if "select_PR_AUC" in pack and (row.get("validation_PR_AUC") in ("", None) or not np.isfinite(float(row.get("validation_PR_AUC") or "nan"))):
        row["validation_PR_AUC"] = pack.get("select_PR_AUC", pack.get("validation_PR_AUC"))
    return row


def evaluate_imported(
    *,
    condition: str,
    seed: int,
    spec: dict[str, Any],
    matched_teacher: torch.nn.Module,
    val_loader,
    device: torch.device,
    ensemble_logits_val: np.ndarray | None,
) -> dict[str, Any]:
    hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
    student = build_odst046_model()
    load_state_dict(student, spec["checkpoint"], strict=True)
    student.to(device)
    freeze_teacher(student)
    assert_odst046(student)
    val = evaluate_pair(
        student=student,
        teacher=matched_teacher,
        loader=val_loader,
        device=device,
        ensemble_logits=ensemble_logits_val,
    )
    s = val["student"]
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "val_logits.npy", val["student_logits"])
    np.save(out_dir / "val_y.npy", val["y"])
    return {
        "condition": condition,
        "seed": seed,
        "best_epoch": "imported",
        "select_PR_AUC": float(s["pr_auc"]),
        "validation_PR_AUC": float(s["pr_auc"]),
        "validation_F1": float(s["f1"]),
        "precision": float(s["precision"]),
        "recall": float(s["recall"]),
        "FP": int(s["fp"]),
        "FN": int(s["fn"]),
        "Brier": float(s["Brier"]),
        "log_loss": float(s["log_loss"]),
        "predicted_positive_fraction": float(s["predicted_positive_fraction"]),
        "threshold": float(val["threshold"]),
        "teacher_logit_deviation": float(val.get("teacher_logit_deviation", float("nan"))),
        "ensemble_logit_deviation": float(val.get("ensemble_logit_deviation", float("nan"))),
        "ensemble_prob_deviation": float(val.get("ensemble_prob_deviation", float("nan"))),
        "route_MAE": float(val.get("route_MAE", float("nan"))),
        "route_KL": float(val.get("route_KL", float("nan"))),
        "hard_route_agreement": float(val.get("hard_route_agreement", float("nan"))),
        "dominant_leaf_agreement": float(val.get("dominant_leaf_agreement", float("nan"))),
        "best_checkpoint": str(spec["checkpoint"]),
        "best_checkpoint_sha256": spec["sha256"],
        "ensemble_on": False,
        "route_on": condition.startswith("F01"),
        "lambda_et1": 0.0,
        "lambda_route": LAMBDA_ROUTE if condition.startswith("F01") else 0.0,
        "historical_single_teacher_logit_anchor": False,
        "imported_from_EDITOR011": True,
        "y_val": val["y"],
        "student_logits": val["student_logits"],
        "epoch_rows": [],
    }


def run_inner_search(
    *,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    ens_train: dict[str, np.ndarray],
    device: torch.device,
    pos_weight: float,
) -> dict[str, Any]:
    split = inner_split_masks(bundle["train"])
    if (
        split["n_inner_train"] != EXPECTED_INNER_TRAIN_N
        or split["n_inner_select"] != EXPECTED_INNER_SELECT_N
        or split["n_inner_train_pos"] != EXPECTED_INNER_TRAIN_POS
        or split["n_inner_select_pos"] != EXPECTED_INNER_SELECT_POS
        or split["n_dropped"] != EXPECTED_INNER_DROPPED
    ):
        raise Editor012Blocked(
            f"INNER split mismatch {split['n_inner_train']}/{split['n_inner_select']}/"
            f"{split['n_inner_train_pos']}/{split['n_inner_select_pos']}/{split['n_dropped']}"
        )
    inner_tr = subset_bundle(bundle["train"], split["train_mask"], "inner_train")
    inner_se = subset_bundle(bundle["train"], split["select_mask"], "inner_select")
    extras_full = [
        ens_train["ens_logit"],
        _probs(ens_train["ens_logit"]),
        _probs(ens_train["logit42"]),
        _probs(ens_train["logit52"]),
        _probs(ens_train["logit62"]),
    ]
    extras_tr = [a[split["train_mask"]] for a in extras_full]
    extras_se = [a[split["select_mask"]] for a in extras_full]
    matched = teachers[SCREENING_SEED]
    rows = []
    route_rows = []

    def _train_one(anchor_id: str, route_on: bool) -> dict[str, Any]:
        _set_seed(SCREENING_SEED)
        student, start_sha = student_from_topt(SCREENING_SEED, device)
        assert start_sha == TOPT_CHECKPOINTS[SCREENING_SEED]["sha256"]
        train_loader = make_xy_loader(
            inner_tr.X, inner_tr.y, seed=SCREENING_SEED, shuffle=True, extras=extras_tr
        )
        select_loader = make_xy_loader(inner_se.X, inner_se.y, seed=SCREENING_SEED, shuffle=False)
        cond = f"INNER_{anchor_id}{'_R' if route_on else ''}"
        pack = train_student(
            condition=cond,
            seed=SCREENING_SEED,
            matched_teacher=matched,
            student=student,
            train_loader=train_loader,
            select_loader=select_loader,
            device=device,
            pos_weight=pos_weight,
            ensemble_on=True,
            route_on=route_on,
            lambda_et1=ET1_LOGIT_DISTILL_WEIGHT,
            lambda_route=LAMBDA_ROUTE if route_on else 0.0,
            select_name="inner_select",
            ensemble_logits_select=extras_se[0],
            **_anchor_kwargs(anchor_id),
        )
        rec = {
            "anchor_id": anchor_id,
            "route_on": route_on,
            "inner_select_pr_auc": float(pack["select_PR_AUC"]),
            "inner_select_f1": float(pack["validation_F1"]),
            "best_epoch": pack["best_epoch"],
            "condition": cond,
            "start_topt_sha256": start_sha,
        }
        return rec

    for aid in ("A0", "A1", "A2", "A3", "A4", "A5"):
        rec = _train_one(aid, False)
        rows.append(rec)
        print(f"[EDITOR-012] INNER {aid} route=OFF PR-AUC={rec['inner_select_pr_auc']:.6f}", flush=True)

    ranked_off = sorted(rows, key=lambda r: (-r["inner_select_pr_auc"], -r["inner_select_f1"], ANCHOR_FORMULATIONS[r["anchor_id"]]["simplicity_rank"]))
    best_two = ranked_off[:2]
    for rec0 in best_two:
        rec = _train_one(rec0["anchor_id"], True)
        route_rows.append(rec)
        print(f"[EDITOR-012] INNER {rec['anchor_id']} route=ON PR-AUC={rec['inner_select_pr_auc']:.6f}", flush=True)

    write_csv(_review("01_inner_anchor_search", "EDITOR012_INNER_ANCHOR_RESULTS.csv"), rows)
    write_csv(_review("01_inner_anchor_search", "EDITOR012_ROUTE_CONDITIONAL_RESULTS.csv"), route_rows)
    decision = decide_promotions(rows + route_rows)
    decision["frozen_before_official_validation_evaluation_of_candidates"] = True
    decision["best_two_for_route_on"] = [r["anchor_id"] for r in best_two]
    write_json(_review("01_inner_anchor_search", "EDITOR012_PROMOTION_FREEZE.json"), decision)
    return {"rows": rows, "route_rows": route_rows, "decision": decision, "split": split}


def run_one_trained(
    *,
    condition: str,
    seed: int,
    start_seed: int,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    ens_train: dict[str, np.ndarray],
    ens_val: dict[str, np.ndarray],
    device: torch.device,
    pos_weight: float,
    ensemble_on: bool,
    route_on: bool,
    anchor_id: str = "A0",
) -> dict[str, Any]:
    _set_seed(seed)
    student, start_sha = student_from_topt(start_seed, device)
    if start_sha != TOPT_CHECKPOINTS[start_seed]["sha256"]:
        raise Editor012Blocked("paired-start T-OPT hash mismatch")
    extras = [
        ens_train["ens_logit"],
        _probs(ens_train["ens_logit"]),
        _probs(ens_train["logit42"]),
        _probs(ens_train["logit52"]),
        _probs(ens_train["logit62"]),
    ]
    train_loader = make_xy_loader(bundle["train"].X, bundle["train"].y, seed=seed, shuffle=True, extras=extras)
    val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=seed, shuffle=False)
    pack = train_student(
        condition=condition,
        seed=seed,
        matched_teacher=teachers[start_seed],
        student=student,
        train_loader=train_loader,
        select_loader=val_loader,
        device=device,
        pos_weight=pos_weight,
        ensemble_on=ensemble_on,
        route_on=route_on,
        lambda_et1=ET1_LOGIT_DISTILL_WEIGHT if ensemble_on else 0.0,
        lambda_route=LAMBDA_ROUTE if route_on else 0.0,
        select_name="validation",
        ensemble_logits_select=ens_val["ens_logit"],
        **(_anchor_kwargs(anchor_id) if ensemble_on else {}),
    )
    pack["start_topt_sha256"] = start_sha
    pack["start_seed"] = start_seed
    out_dir = OUTPUT_ROOT / condition / f"seed{seed}"
    np.save(out_dir / "val_logits.npy", pack["student_logits"])
    np.save(out_dir / "val_y.npy", pack["y_val"])
    write_json(out_dir / "history.json", pack["epoch_rows"])
    return pack


def _metric(rows: list[dict[str, Any]], cond: str, seed: int, key: str) -> float:
    for r in rows:
        if r["condition"] == cond and int(r["seed"]) == seed:
            return float(r[key])
    raise KeyError(f"{cond} seed {seed} {key}")


def classify_teacher_guidance(
    *,
    mean_delta: float,
    pos_primary: int,
    ci_lo: float | None,
    extended_pos: int | None,
    extended_triggered: bool,
) -> str:
    if mean_delta <= 0:
        return "NOT_SUPPORTED"
    if pos_primary == 3 and ci_lo is not None and ci_lo > 0:
        return "SUPPORTED_STRONG"
    if pos_primary == 3:
        return "SUPPORTED_CONSISTENT"
    if pos_primary >= 2 and extended_triggered and extended_pos is not None and extended_pos >= 8:
        return "SUPPORTED_STABILITY_ONLY"
    if pos_primary >= 2 and not extended_triggered:
        return "MIXED"
    return "MIXED"


def _bootstrap_runtime(*, skip_training: bool = False) -> dict[str, Any]:
    started = utc_now()
    write_protocol_packet()
    identities = verify_identities()
    bundle = load_train_validation()
    user_map = recover_user_mapping(bundle)
    write_json(_review("05_statistics", "EDITOR012_USER_MAPPING_VERIFICATION.json"), user_map)
    device = _device()
    pos_weight = float(bundle["pos_weight"])
    print(f"[EDITOR-012] device={device} pos_weight={pos_weight:.6f}", flush=True)

    teachers = {seed: load_frozen_model(TOPT_CHECKPOINTS[seed], device) for seed in PRIMARY_SEEDS}
    for seed in PRIMARY_SEEDS:
        h = state_dict_sha256(teachers[seed].state_dict())
        print(f"[EDITOR-012] T-OPT({seed}) state hash={h[:12]}", flush=True)

    ens_train = precompute_ensemble(teachers, bundle["train"].X, bundle["train"].y, device, "train")
    ens_val = precompute_ensemble(teachers, bundle["val"].X, bundle["val"].y, device, "val")
    ctx = {
        "started": started,
        "identities": identities,
        "bundle": bundle,
        "user_map": user_map,
        "device": device,
        "pos_weight": pos_weight,
        "teachers": teachers,
        "ens_train": ens_train,
        "ens_val": ens_val,
    }
    if skip_training:
        ctx["status"] = "PROTOCOL_ONLY"
    return ctx


def run_inner_phase() -> dict[str, Any]:
    ctx = _bootstrap_runtime()
    inner = run_inner_search(
        bundle=ctx["bundle"],
        teachers=ctx["teachers"],
        ens_train=ctx["ens_train"],
        device=ctx["device"],
        pos_weight=ctx["pos_weight"],
    )
    write_json(
        _review("EDITOR012_PROMOTION_COMMIT_READY.json"),
        {"ready": True, "promoted": inner["decision"]["promoted"], "utc": utc_now()},
    )
    print("[EDITOR-012] INNER SEARCH COMPLETE — promotion freeze written; stop for EDITOR-012B commit", flush=True)
    return {"identities": ctx["identities"], "inner": inner["decision"], "status": "INNER_COMPLETE"}


def run_campaign(*, skip_training: bool = False, resume_after_inner: bool = False) -> dict[str, Any]:
    ctx = _bootstrap_runtime(skip_training=skip_training)
    identities = ctx["identities"]
    bundle = ctx["bundle"]
    teachers = ctx["teachers"]
    ens_train = ctx["ens_train"]
    ens_val = ctx["ens_val"]
    device = ctx["device"]
    pos_weight = ctx["pos_weight"]
    started = ctx["started"]
    if skip_training:
        return {"identities": identities, "user_map": ctx["user_map"], "status": "PROTOCOL_ONLY"}

    if resume_after_inner:
        freeze_path = _review("01_inner_anchor_search", "EDITOR012_PROMOTION_FREEZE.json")
        if not freeze_path.is_file():
            raise Editor012Blocked("promotion freeze missing; cannot resume confirmation")
        inner = {"decision": json.loads(freeze_path.read_text(encoding="utf-8"))}
        print("[EDITOR-012] resuming after promotion freeze", flush=True)
    else:
        inner = run_inner_search(
        bundle=bundle,
        teachers=teachers,
        ens_train=ens_train,
        device=device,
        pos_weight=pos_weight,
    )
    write_json(
        _review("EDITOR012_PROMOTION_COMMIT_READY.json"),
        {"ready": True, "promoted": inner["decision"]["promoted"], "utc": utc_now()},
    )

    val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=0, shuffle=False)
    factorial_packs: dict[tuple[str, int], dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []
    mechanism_rows: list[dict[str, Any]] = []

    for seed in PRIMARY_SEEDS:
        matched = teachers[seed]
        f00 = evaluate_imported(
            condition="F00_C2OPT",
            seed=seed,
            spec=C2OPT_CHECKPOINTS[seed],
            matched_teacher=matched,
            val_loader=val_loader,
            device=device,
            ensemble_logits_val=ens_val["ens_logit"],
        )
        f01 = evaluate_imported(
            condition="F01_R2OPT",
            seed=seed,
            spec=R2OPT_CHECKPOINTS[seed],
            matched_teacher=matched,
            val_loader=val_loader,
            device=device,
            ensemble_logits_val=ens_val["ens_logit"],
        )
        f10 = run_one_trained(
            condition="F10_DOPT",
            seed=seed,
            start_seed=seed,
            bundle=bundle,
            teachers=teachers,
            ens_train=ens_train,
            ens_val=ens_val,
            device=device,
            pos_weight=pos_weight,
            ensemble_on=True,
            route_on=False,
            anchor_id="A0",
        )
        f11 = run_one_trained(
            condition="F11_DROPT",
            seed=seed,
            start_seed=seed,
            bundle=bundle,
            teachers=teachers,
            ens_train=ens_train,
            ens_val=ens_val,
            device=device,
            pos_weight=pos_weight,
            ensemble_on=True,
            route_on=True,
            anchor_id="A0",
        )
        for pack in (f00, f10, f01, f11):
            factorial_packs[(pack["condition"], seed)] = pack
            all_rows.append(_pack_row(pack))
            mechanism_rows.append(
                {
                    "condition": pack["condition"],
                    "seed": seed,
                    "teacher_logit_deviation": pack.get("teacher_logit_deviation"),
                    "ensemble_logit_deviation": pack.get("ensemble_logit_deviation"),
                    "ensemble_prob_deviation": pack.get("ensemble_prob_deviation"),
                    "route_MAE": pack.get("route_MAE"),
                    "route_KL": pack.get("route_KL"),
                    "hard_route_agreement": pack.get("hard_route_agreement"),
                    "dominant_leaf_agreement": pack.get("dominant_leaf_agreement"),
                }
            )

    promoted_rows = []
    for promo in inner["decision"]["promoted"]:
        for seed in PRIMARY_SEEDS:
            pack = run_one_trained(
                condition=promo["condition"],
                seed=seed,
                start_seed=seed,
                bundle=bundle,
                teachers=teachers,
                ens_train=ens_train,
                ens_val=ens_val,
                device=device,
                pos_weight=pos_weight,
                ensemble_on=True,
                route_on=bool(promo["route_on"]),
                anchor_id=promo["anchor_id"],
            )
            factorial_packs[(pack["condition"], seed)] = pack
            promoted_rows.append(_pack_row(pack))
            all_rows.append(_pack_row(pack))
            mechanism_rows.append(
                {
                    "condition": pack["condition"],
                    "seed": seed,
                    "teacher_logit_deviation": pack.get("teacher_logit_deviation"),
                    "ensemble_logit_deviation": pack.get("ensemble_logit_deviation"),
                    "ensemble_prob_deviation": pack.get("ensemble_prob_deviation"),
                    "route_MAE": pack.get("route_MAE"),
                    "route_KL": pack.get("route_KL"),
                    "hard_route_agreement": pack.get("hard_route_agreement"),
                    "dominant_leaf_agreement": pack.get("dominant_leaf_agreement"),
                }
            )

    write_csv(_review("02_factorial_confirmation", "EDITOR012_FACTORIAL_RESULTS.csv"), [r for r in all_rows if str(r["condition"]).startswith("F")], RESULT_COLS)
    write_csv(_review("02_factorial_confirmation", "EDITOR012_PROMOTED_RESULTS.csv"), promoted_rows, RESULT_COLS)

    def _prs(cond: str) -> list[float]:
        return [_metric(all_rows, cond, s, "validation_PR_AUC") for s in PRIMARY_SEEDS]

    f00_prs = _prs("F00_C2OPT")
    f10_prs = _prs("F10_DOPT")
    f01_prs = _prs("F01_R2OPT")
    f11_prs = _prs("F11_DROPT")
    d_f10 = [a - b for a, b in zip(f10_prs, f00_prs)]
    d_f01 = [a - b for a, b in zip(f01_prs, f00_prs)]
    d_f11_f10 = [a - b for a, b in zip(f11_prs, f10_prs)]
    d_f11 = [a - b for a, b in zip(f11_prs, f00_prs)]
    primary_effects = {
        "F00_C2OPT_MEAN_PR_AUC": _mean(f00_prs),
        "F10_DISTILL_ONLY_MEAN_PR_AUC": _mean(f10_prs),
        "F01_ROUTE_ONLY_MEAN_PR_AUC": _mean(f01_prs),
        "F11_DISTILL_PLUS_ROUTE_MEAN_PR_AUC": _mean(f11_prs),
        "DELTA_F10_MINUS_F00": _mean(d_f10),
        "DELTA_F01_MINUS_F00": _mean(d_f01),
        "DELTA_F11_MINUS_F10": _mean(d_f11_f10),
        "DELTA_F11_MINUS_F00": _mean(d_f11),
        "POSITIVE_SEEDS_F10_VS_F00": f"{sum(1 for x in d_f10 if x > 0)}/3",
        "POSITIVE_SEEDS_F11_VS_F00": f"{sum(1 for x in d_f11 if x > 0)}/3",
        "per_seed": {
            str(s): {
                "F00": f00_prs[i],
                "F10": f10_prs[i],
                "F01": f01_prs[i],
                "F11": f11_prs[i],
                "F10_minus_F00": d_f10[i],
                "F01_minus_F00": d_f01[i],
                "F11_minus_F10": d_f11_f10[i],
                "F11_minus_F00": d_f11[i],
            }
            for i, s in enumerate(PRIMARY_SEEDS)
        },
    }
    write_json(_review("02_factorial_confirmation", "EDITOR012_PRIMARY_EFFECTS.json"), primary_effects)

    ref_rows = []
    for name, rec in HISTORICAL.items():
        ref_mean = float(rec.get("paper_facing_mean", rec["mean_PR_AUC"]))
        ref_rows.append(
            {
                "reference": name,
                "reference_mean_PR_AUC": ref_mean,
                "F10_mean_PR_AUC": primary_effects["F10_DISTILL_ONLY_MEAN_PR_AUC"],
                "F11_mean_PR_AUC": primary_effects["F11_DISTILL_PLUS_ROUTE_MEAN_PR_AUC"],
                "delta_F10_minus_reference": primary_effects["F10_DISTILL_ONLY_MEAN_PR_AUC"] - ref_mean,
                "delta_F11_minus_reference": primary_effects["F11_DISTILL_PLUS_ROUTE_MEAN_PR_AUC"] - ref_mean,
            }
        )
    write_csv(_review("02_factorial_confirmation", "EDITOR012_REFERENCE_COMPARISON.csv"), ref_rows)

    users = np.asarray(bundle["val"].user).astype(str)
    y_val = np.asarray(bundle["val"].y)
    logits = {
        cond: [np.asarray(factorial_packs[(cond, s)]["student_logits"]) for s in PRIMARY_SEEDS]
        for cond in ("F00_C2OPT", "F10_DOPT", "F01_R2OPT", "F11_DROPT")
    }
    thrs = {
        cond: [float(factorial_packs[(cond, s)]["threshold"]) for s in PRIMARY_SEEDS]
        for cond in ("F00_C2OPT", "F10_DOPT", "F01_R2OPT", "F11_DROPT")
    }
    boot = {}
    for name, a, b in (
        ("F10_minus_F00", "F00_C2OPT", "F10_DOPT"),
        ("F11_minus_F00", "F00_C2OPT", "F11_DROPT"),
        ("F11_minus_F10", "F10_DOPT", "F11_DROPT"),
    ):
        print(f"[EDITOR-012] bootstrap {name}", flush=True)
        boot[name] = paired_user_cluster_mean_across_seeds(
            users,
            y_val,
            logits[a],
            logits[b],
            frozen_thresholds_a=thrs[a],
            frozen_thresholds_b=thrs[b],
            n_valid=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
            contrast=name,
        )
    write_json(_review("05_statistics", "EDITOR012_CLUSTER_BOOTSTRAP.json"), boot)

    candidates = [
        ("F10_DOPT", primary_effects["F10_DISTILL_ONLY_MEAN_PR_AUC"], primary_effects["DELTA_F10_MINUS_F00"], int(primary_effects["POSITIVE_SEEDS_F10_VS_F00"][0])),
        ("F11_DROPT", primary_effects["F11_DISTILL_PLUS_ROUTE_MEAN_PR_AUC"], primary_effects["DELTA_F11_MINUS_F00"], int(primary_effects["POSITIVE_SEEDS_F11_VS_F00"][0])),
    ]
    for promo in inner["decision"]["promoted"]:
        prs = [_metric(all_rows, promo["condition"], s, "validation_PR_AUC") for s in PRIMARY_SEEDS]
        deltas = [p - c for p, c in zip(prs, f00_prs)]
        candidates.append((promo["condition"], _mean(prs), _mean(deltas), sum(1 for d in deltas if d > 0)))
    best = max(candidates, key=lambda t: (t[2], t[1]))
    best_cond, best_pr, best_delta, best_pos = best

    trigger = bool(best_delta > 0 and best_pos >= 2)
    stability_rows = []
    ext_pos = None
    ext_mean = None
    if trigger:
        start_cycle = list(PRIMARY_SEEDS)
        for i, extra in enumerate(EXTENDED_SEEDS):
            start_seed = start_cycle[i % 3]
            c2 = run_one_trained(
                condition="STAB_C2",
                seed=extra,
                start_seed=start_seed,
                bundle=bundle,
                teachers=teachers,
                ens_train=ens_train,
                ens_val=ens_val,
                device=device,
                pos_weight=pos_weight,
                ensemble_on=False,
                route_on=False,
            )
            tgt_ens = "F11" in best_cond or best_cond.endswith("_R")
            tgt_route = "F11" in best_cond or best_cond.endswith("_R")
            if best_cond == "F10_DOPT":
                tgt_ens, tgt_route = True, False
            elif best_cond == "F11_DROPT":
                tgt_ens, tgt_route = True, True
            else:
                promo = next(p for p in inner["decision"]["promoted"] if p["condition"] == best_cond)
                tgt_ens, tgt_route = True, bool(promo["route_on"])
            ta = run_one_trained(
                condition="STAB_TA",
                seed=extra,
                start_seed=start_seed,
                bundle=bundle,
                teachers=teachers,
                ens_train=ens_train,
                ens_val=ens_val,
                device=device,
                pos_weight=pos_weight,
                ensemble_on=tgt_ens,
                route_on=tgt_route,
                anchor_id="A0" if best_cond.startswith("F") else next(p["anchor_id"] for p in inner["decision"]["promoted"] if p["condition"] == best_cond),
            )
            stability_rows.append(
                {
                    "seed": extra,
                    "start_topt_seed": start_seed,
                    "C2_PR_AUC": c2["validation_PR_AUC"],
                    "TA_PR_AUC": ta["validation_PR_AUC"],
                    "delta": float(ta["validation_PR_AUC"]) - float(c2["validation_PR_AUC"]),
                }
            )
        primary_deltas = []
        for s in PRIMARY_SEEDS:
            primary_deltas.append(
                {
                    "seed": s,
                    "start_topt_seed": s,
                    "C2_PR_AUC": _metric(all_rows, "F00_C2OPT", s, "validation_PR_AUC"),
                    "TA_PR_AUC": _metric(all_rows, best_cond if best_cond.startswith("F") else best_cond, s, "validation_PR_AUC"),
                    "delta": _metric(all_rows, best_cond, s, "validation_PR_AUC") - _metric(all_rows, "F00_C2OPT", s, "validation_PR_AUC"),
                }
            )
        all_stab = primary_deltas + stability_rows
        deltas = [r["delta"] for r in all_stab]
        ext_pos = int(sum(1 for d in deltas if d > 0))
        ext_mean = float(np.mean(deltas))
        ruling = {
            "triggered": True,
            "positive_seeds": f"{ext_pos}/10",
            "mean_delta": ext_mean,
            "median_delta": float(np.median(deltas)),
            "min_delta": float(np.min(deltas)),
            "max_delta": float(np.max(deltas)),
            "seeds_are_not_independent_experimental_units": True,
        }
    else:
        ruling = {
            "triggered": False,
            "reason": "best teacher-anchor mean Δ<=0 or positive primary seeds < 2/3",
        }
    write_csv(_review("03_extended_stability", "EDITOR012_STABILITY_RESULTS.csv"), stability_rows)
    write_json(_review("03_extended_stability", "EDITOR012_STABILITY_RULING.json"), ruling)

    write_csv(_review("04_mechanism", "EDITOR012_TEACHER_GUIDANCE_METRICS.csv"), mechanism_rows)
    write_csv(_review("04_mechanism", "EDITOR012_ROUTE_FIDELITY_METRICS.csv"), mechanism_rows)
    f10_mae = _mean([r["route_MAE"] for r in mechanism_rows if r["condition"] == "F10_DOPT"])
    f11_mae = _mean([r["route_MAE"] for r in mechanism_rows if r["condition"] == "F11_DROPT"])
    f00_mae = _mean([r["route_MAE"] for r in mechanism_rows if r["condition"] == "F00_C2OPT"])
    f01_mae = _mean([r["route_MAE"] for r in mechanism_rows if r["condition"] == "F01_R2OPT"])
    route_pred = "MIXED"
    if abs(primary_effects["DELTA_F11_MINUS_F10"]) < 0.001 and f11_mae < f10_mae:
        route_role = "STRUCTURAL_FIDELITY_REGULARISER"
        route_pred = "NOT_SUPPORTED"
    elif primary_effects["DELTA_F11_MINUS_F10"] > 0:
        route_role = "PREDICTIVE_AND_STRUCTURAL"
        route_pred = "SUPPORTED" if int(primary_effects["POSITIVE_SEEDS_F11_VS_F00"][0]) >= 2 else "MIXED"
    else:
        route_role = "STRUCTURAL_ONLY_OR_NEUTRAL"
    route_fid = "SUPPORTED" if (f01_mae < f00_mae and f11_mae <= f10_mae + 1e-12) else ("MIXED" if f01_mae < f00_mae else "NOT_SUPPORTED")
    mechanism_ruling = {
        "ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR": ORIGINAL_SINGLE_TEACHER_LOGIT_ANCHOR,
        "route_role": route_role,
        "ROUTE_FIDELITY_EFFECT": route_fid,
        "ROUTE_ANCHOR_INCREMENTAL_PREDICTIVE_EFFECT": route_pred,
        "means": {
            "F00_route_MAE": f00_mae,
            "F10_route_MAE": f10_mae,
            "F01_route_MAE": f01_mae,
            "F11_route_MAE": f11_mae,
        },
    }
    write_json(_review("04_mechanism", "EDITOR012_MECHANISM_RULING.json"), mechanism_ruling)

    ci_f10 = boot["F10_minus_F00"]["ci95_pr_auc"]
    ci_best = boot["F10_minus_F00"]["ci95_pr_auc"] if best_cond == "F10_DOPT" else boot["F11_minus_F00"]["ci95_pr_auc"]
    if best_cond not in {"F10_DOPT", "F11_DROPT"}:
        ci_best = [float("nan"), float("nan")]
        ci_lo_best = None
    else:
        ci_lo_best = float(ci_best[0])
    effect = classify_teacher_guidance(
        mean_delta=float(best_delta),
        pos_primary=int(best_pos),
        ci_lo=ci_lo_best,
        extended_pos=ext_pos,
        extended_triggered=trigger,
    )
    al_mean = HISTORICAL["Attention_linear"]["paper_facing_mean"]
    c5_mean = HISTORICAL["Original_C5"]["paper_facing_mean"]
    gate = {
        "EDITOR012_PAPER_RESCUE_GATE": (
            "TEACHER_GUIDANCE_RESCUE_CONFIRMED"
            if effect in {"SUPPORTED_STRONG", "SUPPORTED_CONSISTENT"}
            else (
                "TEACHER_GUIDANCE_STABILITY_ONLY"
                if effect == "SUPPORTED_STABILITY_ONLY"
                else ("TEACHER_GUIDANCE_MIXED" if effect == "MIXED" else "TEACHER_GUIDANCE_NOT_SUPPORTED")
            )
        ),
        "TEACHER_GUIDANCE_PREDICTIVE_EFFECT": effect,
        "BEST_REPAIRED_TEACHER_ANCHORED_CONDITION": best_cond,
        "BEST_TEACHER_ANCHOR_MEAN_PR_AUC": best_pr,
        "MATCHED_C2_MEAN_PR_AUC": primary_effects["F00_C2OPT_MEAN_PR_AUC"],
        "BEST_DELTA_VS_MATCHED_C2": best_delta,
        "BEST_DELTA_VS_ATTENTION_LINEAR": best_pr - al_mean,
        "BEST_DELTA_VS_ORIGINAL_C5": best_pr - c5_mean,
        "do_not_call_this_historical_C5": True,
        "temporary_identifier": "TA2",
    }
    write_json(_review("07_paper_handover", "EDITOR012_PAPER_RESCUE_GATE.json"), gate)

    editor_issue = {
        "EDITOR_ISSUE_TEACHER_INITIALISATION_ONLY": (
            "RESOLVED" if effect in {"SUPPORTED_STRONG", "SUPPORTED_CONSISTENT"} else (
                "PARTIALLY_RESOLVED" if effect in {"SUPPORTED_STABILITY_ONLY", "MIXED"} else "NOT_RESOLVED"
            )
        ),
        "EDITOR_ISSUE_C5_NEGLIGIBLE_INCREMENT": (
            "RESOLVED_BY_REPAIRED_FORMULATION"
            if best_pr > c5_mean and effect != "NOT_SUPPORTED"
            else "NOT_RESOLVED"
        ),
        "EDITOR_ISSUE_RANDOM_INIT_COLLAPSE": "MECHANISTICALLY_EXPLAINED",
        "EDITOR_ISSUE_ODST_OPTIMISATION": "RESOLVED_BY_ODST046",
    }
    write_json(_review("06_editor_response", "EDITOR012_EDITOR_RESPONSE_EVIDENCE.json"), {**editor_issue, "primary_effects": primary_effects, "gate": gate})
    write_csv(
        _review("06_editor_response", "EDITOR012_EDITOR_ISSUE_MATRIX.csv"),
        [{"issue": k, "ruling": v} for k, v in editor_issue.items()],
    )

    next_action = (
        "Freeze TA2 as the repaired teacher-anchored formulation and wait for authorised final-test strategy."
        if effect in {"SUPPORTED_STRONG", "SUPPORTED_CONSISTENT"}
        else (
            "Report teacher guidance as stability-supported but not cluster-significant. Do not over-claim."
            if effect == "SUPPORTED_STABILITY_ONLY"
            else (
                "Report the matched factorial honestly. Teacher guidance beyond initialisation is mixed or unsupported."
            )
        )
    )
    handover = "\n".join(
        [
            "# EDITOR-012 paper rescue handover",
            "",
            f"Teacher-guidance predictive effect: **{effect}**",
            f"Paper rescue gate: **{gate['EDITOR012_PAPER_RESCUE_GATE']}**",
            "",
            f"F00 C2-OPT mean PR-AUC = {primary_effects['F00_C2OPT_MEAN_PR_AUC']:.6f}",
            f"F10 D-OPT mean PR-AUC = {primary_effects['F10_DISTILL_ONLY_MEAN_PR_AUC']:.6f}",
            f"F01 R2-OPT mean PR-AUC = {primary_effects['F01_ROUTE_ONLY_MEAN_PR_AUC']:.6f}",
            f"F11 DR-OPT mean PR-AUC = {primary_effects['F11_DISTILL_PLUS_ROUTE_MEAN_PR_AUC']:.6f}",
            "",
            f"Best repaired condition: {best_cond}",
            f"Δ vs matched C2 = {best_delta:.6f}",
            f"User-cluster 95% CI (F10−F00) = {ci_f10}",
            "",
            "Historical C5 remains the original dual-anchor formulation. TA2 is a distinct repaired identifier.",
            "",
            next_action,
            "",
        ]
    )
    path_md = _review("07_paper_handover", "EDITOR012_PAPER_RESCUE_HANDOVER.md")
    path_md.write_text(handover, encoding="utf-8")

    manifest = {
        "task_id": "EDITOR-012",
        "status": "COMPLETE",
        "started_utc": started,
        "finished_utc": utc_now(),
        "r52_test_accessed": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "identities": identities,
        "TEACHER_GUIDANCE_PREDICTIVE_EFFECT": effect,
        "device": str(device),
        "promoted": inner["decision"]["promoted"],
        "architecture": ENCODER_ARCH,
    }
    write_json(_review("EDITOR012_RUN_MANIFEST.json"), manifest)
    return {
        "identities": identities,
        "primary_effects": primary_effects,
        "inner": inner["decision"],
        "boot": boot,
        "effect": effect,
        "gate": gate,
        "editor_issue": editor_issue,
        "best": best,
        "stability": ruling,
        "next_action": next_action,
        "mechanism": mechanism_ruling,
    }


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--protocol-only":
        write_protocol_packet()
        verify_identities()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--inner-only":
        run_inner_phase()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--confirm":
        run_campaign(resume_after_inner=True)
        return
    run_campaign()


if __name__ == "__main__":
    main()
