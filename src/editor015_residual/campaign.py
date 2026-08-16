"""EDITOR-015 autonomous residual complementarity orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds
from editor012_rescue.data import load_train_validation, make_xy_loader, subset_bundle
from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.inner_split import inner_split_masks
from editor012_rescue.metrics import metrics_from_logits, teacher_relative
from editor012_rescue.models import architecture_identity, assert_odst046, freeze_teacher
from editor012_rescue.producing import build_odst046_model, import_set_seed, pin_producing_sources

from .complementarity import (
    classify_fixed_complementarity,
    classify_predictive_complementarity,
    error_complementarity,
    fixed_combinations,
    residual_teacher_correlation,
    score_relationship,
    user_level_disagreement,
)
from .constants import (
    BEST_CURRENT_PAPER_MODEL,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    ENCODER_ARCH,
    ENSEMBLE_CACHE,
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
    F11_CHECKPOINTS,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_L1_CI,
    FROZEN_TA2_MEAN_PR_AUC,
    L1_CHECKPOINTS,
    LAMBDA_DISTILL,
    LAMBDA_RESIDUAL_TEACHER,
    LAMBDA_ROUTE,
    ODST046,
    POST_ATTENTION_ODST_INCREMENTAL_VALUE,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    RESIDUAL_CONDITIONS,
    SCREENING_SEED,
    TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TEMPORAL_ODST_INCREMENTAL_VALUE,
    TOPT_CHECKPOINTS,
)
from .explain import directional_table, train_references
from .freeze import write_protocol_packet
from .io_util import write_csv, write_json
from .promotion import decide_promotions
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor015Blocked,
    enter_inner_phase,
    exit_inner_phase,
    mark_promotion_frozen,
    refuse_historical_write,
    refuse_r52_test,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .train import (
    evaluate_residual,
    load_l1_pair,
    load_ta2,
    load_topt,
    load_trained_residual,
    score_l1,
    score_ta2,
    train_residual,
)


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
        raise Editor015Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    pins = pin_producing_sources()
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4 or float(ODST046["temperature"]) != 0.5:
        raise Editor015Blocked("ODST-046 lock mismatch")
    if abs(float(LAMBDA_DISTILL) - 0.5) > 1e-15 or abs(float(LAMBDA_RESIDUAL_TEACHER) - 0.5) > 1e-15:
        raise Editor015Blocked("distill / residual-teacher lambda mismatch")
    if abs(float(LAMBDA_ROUTE) - 0.5) > 1e-15:
        raise Editor015Blocked("route lambda mismatch")
    teacher = build_odst046_model()
    assert_odst046(teacher)
    if EDITOR012_RESULTS_COMMIT != "4bcf522a502ed98e5dd393a80bd9da7fffd51964":
        raise Editor015Blocked("EDITOR-012 results commit mismatch")
    if EDITOR013_RESULTS_COMMIT != "09c4bb97b143810147feef08f31a8d8d042a6726":
        raise Editor015Blocked("EDITOR-013 results commit mismatch")
    if EDITOR014_RESULTS_COMMIT != "c3343462dc3b35d20907da6ad017f5f853852f84":
        raise Editor015Blocked("EDITOR-014 results commit mismatch")
    return {
        "r52_test_hard_denied": True,
        "odst046_identity_verified": True,
        "lambda_distill": LAMBDA_DISTILL,
        "lambda_residual_teacher": LAMBDA_RESIDUAL_TEACHER,
        "lambda_route": LAMBDA_ROUTE,
        "producing_pins": pins,
        "architecture": architecture_identity(teacher),
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "POST_ATTENTION_ODST_INCREMENTAL_VALUE": POST_ATTENTION_ODST_INCREMENTAL_VALUE,
        "TEMPORAL_ODST_INCREMENTAL_VALUE": TEMPORAL_ODST_INCREMENTAL_VALUE,
    }


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor015Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor015Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor015Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor015Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    rec = {
        "USER_MAPPING_RECOVERED": True,
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "per_user_count_min": int(counts.min()),
        "per_user_count_max": int(counts.max()),
        "n_malicious_users": int(len(malicious)),
        "malicious_users": malicious,
        "mapping_sha256": mapping_hash,
        "hash_matches_EDITOR011_012_013_014": True,
        "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
    }
    write_json(_review("04_statistics", "EDITOR015_USER_MAPPING_VERIFICATION.json"), rec)
    return rec


def load_ensemble_cache() -> dict[str, dict[str, np.ndarray]]:
    train = {
        "ens_logit": np.load(ENSEMBLE_CACHE["train_ens"]),
        "logit42": np.load(ENSEMBLE_CACHE["train_42"]),
        "logit52": np.load(ENSEMBLE_CACHE["train_52"]),
        "logit62": np.load(ENSEMBLE_CACHE["train_62"]),
    }
    val = {
        "ens_logit": np.load(ENSEMBLE_CACHE["val_ens"]),
        "logit42": np.load(ENSEMBLE_CACHE["val_42"]),
        "logit52": np.load(ENSEMBLE_CACHE["val_52"]),
        "logit62": np.load(ENSEMBLE_CACHE["val_62"]),
    }
    return {"train": train, "val": val}


@torch.no_grad()
def _cache_l1_representation(student, modules, X, y, device: torch.device) -> dict[str, np.ndarray]:
    loader = make_xy_loader(X, y, seed=0, shuffle=False)
    zs, lins = [], []
    for batch in loader:
        xb = batch[0].to(device)
        z, _enc = student.encode_attention_h(xb)
        lin = modules.linear_head(z)
        zs.append(z.detach().cpu().numpy())
        lins.append(lin.detach().cpu().numpy())
    return {"z": np.concatenate(zs), "l1_logit": np.concatenate(lins), "y": np.asarray(y).reshape(-1)}


def _combo_rows(partition: str, y: np.ndarray, l1: np.ndarray, ta2: np.ndarray, seed: int) -> list[dict[str, Any]]:
    combos = fixed_combinations(y, l1, ta2)
    l1m = metrics_from_logits(y, l1)
    t2m = metrics_from_logits(y, ta2)
    rows = [
        {"partition": partition, "condition": "L1", "seed": seed, "PR_AUC": l1m["pr_auc"], "F1": l1m["f1"], **{k: l1m[k] for k in ("precision", "recall", "fp", "fn", "Brier", "log_loss", "predicted_positive_fraction")}},
        {"partition": partition, "condition": "TA2", "seed": seed, "PR_AUC": t2m["pr_auc"], "F1": t2m["f1"], **{k: t2m[k] for k in ("precision", "recall", "fp", "fn", "Brier", "log_loss", "predicted_positive_fraction")}},
    ]
    for name, pack in combos.items():
        m = pack["metrics"]
        rows.append(
            {
                "partition": partition,
                "condition": name,
                "seed": seed,
                "PR_AUC": m["pr_auc"],
                "F1": m["f1"],
                **{k: m[k] for k in ("precision", "recall", "fp", "fn", "Brier", "log_loss", "predicted_positive_fraction")},
                "weights": "0.5/0.5",
            }
        )
    return rows, combos, l1m, t2m


def run_complementarity(
    *,
    bundle: dict[str, Any],
    ens: dict[str, dict[str, np.ndarray]],
    device: torch.device,
) -> dict[str, Any]:
    enter_inner_phase()
    try:
        split = inner_split_masks(bundle["train"])
        if (
            split["n_inner_train"] != EXPECTED_INNER_TRAIN_N
            or split["n_inner_select"] != EXPECTED_INNER_SELECT_N
            or split["n_inner_train_pos"] != EXPECTED_INNER_TRAIN_POS
            or split["n_inner_select_pos"] != EXPECTED_INNER_SELECT_POS
            or split["n_dropped"] != EXPECTED_INNER_DROPPED
        ):
            raise Editor015Blocked("INNER split mismatch")
        inner_se = subset_bundle(bundle["train"], split["select_mask"], "inner_select")
        sel_loader = make_xy_loader(inner_se.X, inner_se.y, seed=0, shuffle=False)
        l1_s, l1_m, _ = load_l1_pair(SCREENING_SEED, device)
        ta2_s, _ = load_ta2(SCREENING_SEED, device)
        l1_sel = score_l1(l1_s, l1_m, sel_loader, device)
        ta2_sel = score_ta2(ta2_s, sel_loader, device)
        ens_sel = ens["train"]["ens_logit"][split["select_mask"]]
        y_sel = np.asarray(inner_se.y)
        l1_thr = float(metrics_from_logits(y_sel, l1_sel["logits"])["threshold"])
        ta2_thr = float(metrics_from_logits(y_sel, ta2_sel["logits"])["threshold"])
        rel_sel = score_relationship(y_sel, l1_sel["logits"], ta2_sel["logits"], l1_threshold=l1_thr, ta2_threshold=ta2_thr)
        err_sel = error_complementarity(y_sel, l1_sel["logits"], ta2_sel["logits"], l1_threshold=l1_thr, ta2_threshold=ta2_thr)
        resid_sel = residual_teacher_correlation(l1_sel["logits"], ta2_sel["logits"], ens_sel, y_sel)
        combo_sel_rows, combos_sel, l1m_sel, t2m_sel = _combo_rows("INNER_SELECT", y_sel, l1_sel["logits"], ta2_sel["logits"], SCREENING_SEED)
    finally:
        exit_inner_phase()

    y_val = np.asarray(bundle["val"].y)
    users = np.asarray(bundle["val"].user).astype(str)
    val_rel_rows = []
    val_err_rows = []
    val_combo_rows = []
    val_user = None
    val_resid = None
    val_combos_by_seed: dict[int, dict[str, Any]] = {}
    l1_val_logits = {}
    ta2_val_logits = {}
    for seed in PRIMARY_SEEDS:
        l1_val_logits[seed] = np.load(L1_CHECKPOINTS[seed]["val_logits"])
        ta2_val_logits[seed] = np.load(F11_CHECKPOINTS[seed]["val_logits"])
        hash_gate_checkpoint(L1_CHECKPOINTS[seed]["checkpoint"], L1_CHECKPOINTS[seed]["sha256"])
        hash_gate_checkpoint(F11_CHECKPOINTS[seed]["checkpoint"], F11_CHECKPOINTS[seed]["sha256"])
        l1m = metrics_from_logits(y_val, l1_val_logits[seed])
        t2m = metrics_from_logits(y_val, ta2_val_logits[seed])
        rel = score_relationship(y_val, l1_val_logits[seed], ta2_val_logits[seed], l1_threshold=l1m["threshold"], ta2_threshold=t2m["threshold"])
        err = error_complementarity(y_val, l1_val_logits[seed], ta2_val_logits[seed], l1_threshold=l1m["threshold"], ta2_threshold=t2m["threshold"])
        resid = residual_teacher_correlation(l1_val_logits[seed], ta2_val_logits[seed], ens["val"]["ens_logit"], y_val)
        rows, combos, _, _ = _combo_rows("VALIDATION", y_val, l1_val_logits[seed], ta2_val_logits[seed], seed)
        val_combo_rows.extend(rows)
        val_rel_rows.append({"partition": "VALIDATION", "seed": seed, **rel})
        val_err_rows.append({"partition": "VALIDATION", "seed": seed, **err})
        val_combos_by_seed[seed] = combos
        if seed == SCREENING_SEED:
            val_user = user_level_disagreement(
                users, y_val, l1_val_logits[seed], ta2_val_logits[seed],
                l1_threshold=l1m["threshold"], ta2_threshold=t2m["threshold"],
            )
            val_resid = resid

    rel_rows = [{"partition": "INNER_SELECT", "seed": SCREENING_SEED, **rel_sel}, *val_rel_rows]
    err_rows = [{"partition": "INNER_SELECT", "seed": SCREENING_SEED, **err_sel}, *val_err_rows]
    combo_rows = [*combo_sel_rows, *val_combo_rows]
    write_csv(_review("01_complementarity", "EDITOR015_SCORE_RELATIONSHIP.csv"), rel_rows)
    write_csv(_review("01_complementarity", "EDITOR015_ERROR_COMPLEMENTARITY.csv"), err_rows)
    write_csv(_review("01_complementarity", "EDITOR015_FIXED_COMBINATIONS.csv"), combo_rows)

    inner_combo_pr = {n: float(combos_sel[n]["metrics"]["pr_auc"]) for n in combos_sel}
    pred_comp = classify_predictive_complementarity(float(l1m_sel["pr_auc"]), float(t2m_sel["pr_auc"]), inner_combo_pr)
    best_fixed = max(inner_combo_pr, key=inner_combo_pr.get)
    ruling = {
        "PREDICTIVE_COMPLEMENTARITY": pred_comp,
        "INNER_SELECT": {
            "L1_PR_AUC": float(l1m_sel["pr_auc"]),
            "TA2_PR_AUC": float(t2m_sel["pr_auc"]),
            "C0_PR_AUC": inner_combo_pr["C0"],
            "C1_PR_AUC": inner_combo_pr["C1"],
            "C2_PR_AUC": inner_combo_pr["C2"],
            "BEST_FIXED_COMBINATION": best_fixed,
            "score_relationship": rel_sel,
            "error_complementarity": err_sel,
            "teacher_residual": resid_sel,
        },
        "VALIDATION_diagnostic_not_used_for_selection": {
            "user_level": {k: val_user[k] for k in val_user if k != "rows"} if val_user else None,
            "teacher_residual_seed42": val_resid,
        },
        "official_validation_not_used_to_select_hyperparameters": True,
        "no_retraining": True,
    }
    write_json(_review("01_complementarity", "EDITOR015_COMPLEMENTARITY_RULING.json"), ruling)
    return {
        "split": split,
        "inner_select": {
            "y": y_sel,
            "l1": l1_sel["logits"],
            "ta2": ta2_sel["logits"],
            "ens": ens_sel,
            "l1_metrics": l1m_sel,
            "ta2_metrics": t2m_sel,
            "combos": combos_sel,
        },
        "val_logits": {"L1": l1_val_logits, "TA2": ta2_val_logits},
        "ruling": ruling,
        "rel_sel": rel_sel,
        "resid_sel": resid_sel,
        "val_user": val_user,
        "val_combos_by_seed": val_combos_by_seed,
    }


def run_inner_residual(
    *,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    ens: dict[str, dict[str, np.ndarray]],
    comp: dict[str, Any],
    device: torch.device,
    pos_weight: float,
) -> dict[str, Any]:
    enter_inner_phase()
    try:
        split = comp["split"]
        inner_tr = subset_bundle(bundle["train"], split["train_mask"], "inner_train")
        inner_se = subset_bundle(bundle["train"], split["select_mask"], "inner_select")
        ens_tr = ens["train"]["ens_logit"][split["train_mask"]]
        ens_se = ens["train"]["ens_logit"][split["select_mask"]]
        l1_s, l1_m, _ = load_l1_pair(SCREENING_SEED, device)
        cache_tr = _cache_l1_representation(l1_s, l1_m, inner_tr.X, inner_tr.y, device)
        cache_se = _cache_l1_representation(l1_s, l1_m, inner_se.X, inner_se.y, device)
        if not np.allclose(cache_se["l1_logit"], comp["inner_select"]["l1"], atol=1e-5):
            raise Editor015Blocked("L1 identity mismatch on INNER_SELECT")

        rows = [
            {
                "condition": "L1",
                "select_PR_AUC": float(comp["inner_select"]["l1_metrics"]["pr_auc"]),
                "select_F1": float(comp["inner_select"]["l1_metrics"]["f1"]),
                "executed": True,
                "official_validation_used": False,
            },
            {
                "condition": "TA2",
                "select_PR_AUC": float(comp["inner_select"]["ta2_metrics"]["pr_auc"]),
                "select_F1": float(comp["inner_select"]["ta2_metrics"]["f1"]),
                "executed": True,
                "official_validation_used": False,
            },
        ]
        for name in ("C0", "C1", "C2"):
            m = comp["inner_select"]["combos"][name]["metrics"]
            rows.append(
                {
                    "condition": name,
                    "select_PR_AUC": float(m["pr_auc"]),
                    "select_F1": float(m["f1"]),
                    "executed": True,
                    "official_validation_used": False,
                }
            )

        packs: dict[str, Any] = {}
        r3_status = "REDUNDANT_NOT_EXECUTED"
        for name in ("R0", "R1", "R2"):
            spec = RESIDUAL_CONDITIONS[name]
            if spec.get("route"):
                train_loader = make_xy_loader(
                    inner_tr.X, inner_tr.y, seed=SCREENING_SEED, shuffle=True, extras=[ens_tr, cache_tr["l1_logit"]]
                )
                select_loader = make_xy_loader(
                    inner_se.X, inner_se.y, seed=SCREENING_SEED, shuffle=False, extras=[ens_se, cache_se["l1_logit"]]
                )
            else:
                train_loader = make_xy_loader(
                    cache_tr["z"], inner_tr.y, seed=SCREENING_SEED, shuffle=True, extras=[ens_tr, cache_tr["l1_logit"]]
                )
                select_loader = make_xy_loader(
                    cache_se["z"], inner_se.y, seed=SCREENING_SEED, shuffle=False, extras=[ens_se, cache_se["l1_logit"]]
                )
            pack = train_residual(
                condition=name,
                spec=spec,
                seed=SCREENING_SEED,
                start_seed=SCREENING_SEED,
                train_loader=train_loader,
                select_loader=select_loader,
                device=device,
                pos_weight=pos_weight,
                matched_teacher=teachers[SCREENING_SEED] if spec.get("route") else None,
                select_name="inner_select",
                encoder_trainable=False,
            )
            packs[name] = pack
            rows.append(
                {
                    "condition": name,
                    "select_PR_AUC": pack["select_PR_AUC"],
                    "select_F1": pack["select_F1"],
                    "Brier": pack["Brier"],
                    "log_loss": pack["log_loss"],
                    "best_epoch": pack["best_epoch"],
                    "final_distill": spec["final_distill"],
                    "residual_teacher": spec["residual_teacher"],
                    "route": spec["route"],
                    "executed": True,
                    "official_validation_used": False,
                }
            )
            print(f"[EDITOR-015] INNER {name} PR-AUC={pack['select_PR_AUC']:.6f}", flush=True)

        rows.append(
            {
                "condition": "R3",
                "select_PR_AUC": float("nan"),
                "select_F1": float("nan"),
                "executed": False,
                "status": r3_status,
                "reason": "MSE(final, ens) == MSE(r, ens-L1) when L1 is frozen",
                "official_validation_used": False,
            }
        )

        l1_pr = float(comp["inner_select"]["l1_metrics"]["pr_auc"])
        e2e_rows: list[dict[str, Any]] = []
        for name in ("R0", "R1", "R2"):
            if float(packs[name]["select_PR_AUC"]) >= l1_pr + PROMOTION_MARGIN:
                spec = dict(RESIDUAL_CONDITIONS[name])
                train_loader = make_xy_loader(
                    inner_tr.X, inner_tr.y, seed=SCREENING_SEED, shuffle=True, extras=[ens_tr, cache_tr["l1_logit"]]
                )
                select_loader = make_xy_loader(
                    inner_se.X, inner_se.y, seed=SCREENING_SEED, shuffle=False, extras=[ens_se, cache_se["l1_logit"]]
                )
                pack = train_residual(
                    condition=f"E2E_{name}",
                    spec=spec,
                    seed=SCREENING_SEED,
                    start_seed=SCREENING_SEED,
                    train_loader=train_loader,
                    select_loader=select_loader,
                    device=device,
                    pos_weight=pos_weight,
                    matched_teacher=teachers[SCREENING_SEED] if spec.get("route") else None,
                    select_name="inner_select",
                    encoder_trainable=True,
                )
                packs[f"E2E_{name}"] = pack
                rec = {
                    "condition": f"E2E_{name}",
                    "select_PR_AUC": pack["select_PR_AUC"],
                    "select_F1": pack["select_F1"],
                    "Brier": pack["Brier"],
                    "log_loss": pack["log_loss"],
                    "best_epoch": pack["best_epoch"],
                    "final_distill": spec["final_distill"],
                    "residual_teacher": spec["residual_teacher"],
                    "route": spec["route"],
                    "executed": True,
                    "official_validation_used": False,
                }
                rows.append(rec)
                e2e_rows.append(rec)
                print(f"[EDITOR-015] INNER E2E_{name} PR-AUC={pack['select_PR_AUC']:.6f}", flush=True)

        write_csv(_review("02_inner_residual", "EDITOR015_INNER_RESIDUAL_RESULTS.csv"), rows)
        write_csv(_review("02_inner_residual", "EDITOR015_E2E_CONDITIONAL_RESULTS.csv"), e2e_rows)
        decision = decide_promotions(rows)
        write_json(_review("02_inner_residual", "EDITOR015_PROMOTION_FREEZE.json"), decision)
        mark_promotion_frozen()
        return {"rows": rows, "packs": packs, "decision": decision, "e2e_rows": e2e_rows, "r3": r3_status}
    finally:
        exit_inner_phase()


def _pack_val_row(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition": pack["condition"],
        "seed": pack["seed"],
        "validation_PR_AUC": pack["validation_PR_AUC"],
        "validation_F1": pack.get("validation_F1", pack.get("select_F1")),
        "precision": pack.get("precision"),
        "recall": pack.get("recall"),
        "FP": pack.get("FP"),
        "FN": pack.get("FN"),
        "Brier": pack.get("Brier"),
        "log_loss": pack.get("log_loss"),
        "predicted_positive_fraction": pack.get("predicted_positive_fraction"),
        "best_epoch": pack.get("best_epoch"),
        "best_checkpoint_sha256": pack.get("best_checkpoint_sha256"),
        "imported": pack.get("imported", False),
    }


def import_frozen_val(name: str, seed: int, spec: dict[str, Any], y_val: np.ndarray) -> dict[str, Any]:
    ckpt = spec["checkpoint"]
    sha = hash_gate_checkpoint(ckpt, spec["sha256"])
    logits = np.load(spec["val_logits"])
    met = metrics_from_logits(y_val, logits)
    return {
        "condition": name,
        "seed": seed,
        "best_epoch": "imported",
        "select_PR_AUC": float(met["pr_auc"]),
        "validation_PR_AUC": float(met["pr_auc"]),
        "validation_F1": float(met["f1"]),
        "precision": float(met["precision"]),
        "recall": float(met["recall"]),
        "FP": int(met["fp"]),
        "FN": int(met["fn"]),
        "Brier": float(met["Brier"]),
        "log_loss": float(met["log_loss"]),
        "predicted_positive_fraction": float(met["predicted_positive_fraction"]),
        "threshold": float(met["threshold"]),
        "best_checkpoint": str(ckpt),
        "best_checkpoint_sha256": sha,
        "student_logits": logits,
        "y_val": y_val,
        "imported": True,
    }


def classify_residual_value(mean_delta: float, pos: int, ci_lo: float | None, ext_pos: int | None, ext_trig: bool) -> str:
    if mean_delta > 0 and pos == 3 and ci_lo is not None and ci_lo > 0:
        return "STRONG_RESIDUAL_ODST_VALUE"
    if mean_delta > 0 and pos == 3:
        return "CONSISTENT_RESIDUAL_ODST_VALUE"
    if ext_trig and ext_pos is not None and ext_pos >= 8 and mean_delta > 0 and pos >= 2:
        return "STABLE_RESIDUAL_ODST_VALUE"
    return "NO_RESIDUAL_ODST_VALUE"


def run_confirmation(
    *,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    ens: dict[str, dict[str, np.ndarray]],
    device: torch.device,
    pos_weight: float,
    inner: dict[str, Any],
    mapping: dict[str, Any],
    comp: dict[str, Any],
) -> dict[str, Any]:
    y_val = np.asarray(bundle["val"].y)
    users = np.asarray(bundle["val"].user).astype(str)
    packs: dict[tuple[str, int], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    l1_train_cache = None

    for seed in PRIMARY_SEEDS:
        packs[("L1", seed)] = import_frozen_val("L1", seed, L1_CHECKPOINTS[seed], y_val)
        rows.append(_pack_val_row(packs[("L1", seed)]))
        packs[("TA2", seed)] = import_frozen_val("TA2", seed, F11_CHECKPOINTS[seed], y_val)
        rows.append(_pack_val_row(packs[("TA2", seed)]))
        combos = comp["val_combos_by_seed"][seed]
        for name in ("C0", "C1", "C2"):
            m = combos[name]["metrics"]
            packs[(name, seed)] = {
                "condition": name,
                "seed": seed,
                "validation_PR_AUC": float(m["pr_auc"]),
                "validation_F1": float(m["f1"]),
                "precision": float(m["precision"]),
                "recall": float(m["recall"]),
                "FP": int(m["fp"]),
                "FN": int(m["fn"]),
                "Brier": float(m["Brier"]),
                "log_loss": float(m["log_loss"]),
                "predicted_positive_fraction": float(m["predicted_positive_fraction"]),
                "threshold": float(m["threshold"]),
                "student_logits": combos[name]["logits"],
                "imported": True,
            }
            rows.append(_pack_val_row(packs[(name, seed)]))

    promoted = list(inner["decision"]["promoted"])
    for promo in promoted:
        name = promo["promoted_condition"]
        family = promo["inner_condition"]
        spec = dict(RESIDUAL_CONDITIONS[family])
        encoder_trainable = bool(promo["spec"]["encoder_trainable"])
        for seed in PRIMARY_SEEDS:
            l1_s, l1_m, _ = load_l1_pair(seed, device)
            cache_tr = _cache_l1_representation(l1_s, l1_m, bundle["train"].X, bundle["train"].y, device)
            extras = [ens["train"]["ens_logit"], cache_tr["l1_logit"]]
            train_loader = make_xy_loader(bundle["train"].X, bundle["train"].y, seed=seed, shuffle=True, extras=extras)
            val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=seed, shuffle=False)
            pack = train_residual(
                condition=name,
                spec=spec,
                seed=seed,
                start_seed=seed,
                train_loader=train_loader,
                select_loader=val_loader,
                device=device,
                pos_weight=pos_weight,
                matched_teacher=teachers[seed] if spec.get("route") else None,
                select_name="validation",
                encoder_trainable=encoder_trainable,
            )
            packs[(name, seed)] = pack
            rows.append(_pack_val_row(pack))
            if seed == SCREENING_SEED:
                l1_train_cache = cache_tr

    write_csv(_review("03_validation_confirmation", "EDITOR015_VALIDATION_RESULTS.csv"), rows)

    def _prs(name: str) -> list[float]:
        return [float(packs[(name, s)]["validation_PR_AUC"]) for s in PRIMARY_SEEDS]

    def _logits(name: str) -> list[np.ndarray]:
        return [np.asarray(packs[(name, s)]["student_logits"]) for s in PRIMARY_SEEDS]

    def _thrs(name: str) -> list[float]:
        return [float(packs[(name, s)]["threshold"]) for s in PRIMARY_SEEDS]

    l1_mean = _mean(_prs("L1"))
    ta2_mean = _mean(_prs("TA2"))
    best_name = "NONE"
    best_mean = float("-inf")
    for promo in promoted:
        name = promo["promoted_condition"]
        m = _mean(_prs(name))
        if m > best_mean:
            best_mean = m
            best_name = name

    boot: dict[str, Any] = {}
    combo_boot: dict[str, Any] = {}
    for name in ("C0", "C1", "C2"):
        combo_boot[f"{name}_minus_L1"] = paired_user_cluster_mean_across_seeds(
            users, y_val, _logits("L1"), _logits(name),
            frozen_thresholds_a=_thrs("L1"), frozen_thresholds_b=_thrs(name),
            n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast=f"{name}_minus_L1",
        )
        combo_boot[f"{name}_minus_TA2"] = paired_user_cluster_mean_across_seeds(
            users, y_val, _logits("TA2"), _logits(name),
            frozen_thresholds_a=_thrs("TA2"), frozen_thresholds_b=_thrs(name),
            n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast=f"{name}_minus_TA2",
        )

    best_combo = max(("C0", "C1", "C2"), key=lambda n: _mean(_prs(n)))
    combo_beats_both = _mean(_prs(best_combo)) > l1_mean and _mean(_prs(best_combo)) > ta2_mean
    fixed_ruling = classify_fixed_complementarity(
        combo_beats_both=combo_beats_both,
        ci_lo_vs_l1=combo_boot[f"{best_combo}_minus_L1"]["ci95_pr_auc"][0],
        ci_lo_vs_ta2=combo_boot[f"{best_combo}_minus_TA2"]["ci95_pr_auc"][0],
        mean_vs_l1=combo_boot[f"{best_combo}_minus_L1"]["mean_delta_pr_auc"],
        mean_vs_ta2=combo_boot[f"{best_combo}_minus_TA2"]["mean_delta_pr_auc"],
    )

    comparisons: dict[str, Any] = {
        "MATCHED_L1_MEAN_PR_AUC": l1_mean,
        "TA2_MEAN_PR_AUC": ta2_mean,
        "BEST_FIXED_COMBINATION": best_combo,
        "FIXED_LINEAR_ODST_COMPLEMENTARITY": fixed_ruling,
        "C0_LOGIT_AVERAGE_PR_AUC": _mean(_prs("C0")),
        "C1_PROBABILITY_AVERAGE_PR_AUC": _mean(_prs("C1")),
        "C2_RANK_AVERAGE_PR_AUC": _mean(_prs("C2")),
    }
    ext_trig = False
    ext_pos = None
    stab_rows: list[dict[str, Any]] = []
    residual_value = "NO_RESIDUAL_ODST_VALUE"
    if best_name != "NONE":
        deltas = []
        for seed in PRIMARY_SEEDS:
            a = packs[("L1", seed)]
            b = packs[(best_name, seed)]
            deltas.append(
                {
                    "seed": seed,
                    "delta_PR_AUC_vs_L1": float(b["validation_PR_AUC"]) - float(a["validation_PR_AUC"]),
                    "delta_PR_AUC_vs_TA2": float(b["validation_PR_AUC"]) - float(packs[("TA2", seed)]["validation_PR_AUC"]),
                }
            )
        pos = sum(1 for d in deltas if d["delta_PR_AUC_vs_L1"] > 0)
        mean_delta = _mean([d["delta_PR_AUC_vs_L1"] for d in deltas])
        boot[f"{best_name}_minus_L1"] = paired_user_cluster_mean_across_seeds(
            users, y_val, _logits("L1"), _logits(best_name),
            frozen_thresholds_a=_thrs("L1"), frozen_thresholds_b=_thrs(best_name),
            n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast=f"{best_name}_minus_L1",
        )
        boot[f"{best_name}_minus_TA2"] = paired_user_cluster_mean_across_seeds(
            users, y_val, _logits("TA2"), _logits(best_name),
            frozen_thresholds_a=_thrs("TA2"), frozen_thresholds_b=_thrs(best_name),
            n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast=f"{best_name}_minus_TA2",
        )
        ci = boot[f"{best_name}_minus_L1"]["ci95_pr_auc"]
        ext_trig = bool(mean_delta > 0 and pos >= 2)
        if ext_trig:
            family = next(p["inner_condition"] for p in promoted if p["promoted_condition"] == best_name)
            spec = dict(RESIDUAL_CONDITIONS[family])
            encoder_trainable = bool(next(p["spec"]["encoder_trainable"] for p in promoted if p["promoted_condition"] == best_name))
            for seed in EXTENDED_SEEDS:
                l1_s, l1_m, _ = load_l1_pair(SCREENING_SEED if seed not in L1_CHECKPOINTS else seed, device)
                # Extended seeds start from L1 seed 42 encoder identity; paired start uses seed 42 L1.
                start = SCREENING_SEED
                l1_s, l1_m, _ = load_l1_pair(start, device)
                cache_tr = _cache_l1_representation(l1_s, l1_m, bundle["train"].X, bundle["train"].y, device)
                extras = [ens["train"]["ens_logit"], cache_tr["l1_logit"]]
                train_loader = make_xy_loader(bundle["train"].X, bundle["train"].y, seed=seed, shuffle=True, extras=extras)
                val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=seed, shuffle=False)
                pack = train_residual(
                    condition=best_name,
                    spec=spec,
                    seed=seed,
                    start_seed=start,
                    train_loader=train_loader,
                    select_loader=val_loader,
                    device=device,
                    pos_weight=pos_weight,
                    matched_teacher=teachers[start] if spec.get("route") else None,
                    select_name="validation",
                    encoder_trainable=encoder_trainable,
                )
                l1_ref = float(packs[("L1", SCREENING_SEED)]["validation_PR_AUC"])
                stab_rows.append(
                    {
                        "seed": seed,
                        "residual_PR_AUC": pack["validation_PR_AUC"],
                        "L1_ref_PR_AUC": l1_ref,
                        "delta": float(pack["validation_PR_AUC"]) - l1_ref,
                    }
                )
            primary_deltas = [d["delta_PR_AUC_vs_L1"] for d in deltas]
            ext_deltas = [r["delta"] for r in stab_rows]
            all_d = primary_deltas + ext_deltas
            ext_pos = sum(1 for d in all_d if d > 0)
            write_csv(
                _review("03_validation_confirmation", "EDITOR015_STABILITY_RESULTS.csv"),
                [{"seed": s, "delta": d} for s, d in zip(PRIMARY_SEEDS, primary_deltas)] + stab_rows,
            )
        residual_value = classify_residual_value(mean_delta, pos, ci[0], ext_pos, ext_trig)
        comparisons.update(
            {
                "BEST_RESIDUAL_MODEL": best_name,
                "BEST_RESIDUAL_MEAN_PR_AUC": best_mean,
                "BEST_RESIDUAL_DELTA_VS_L1": mean_delta,
                "BEST_RESIDUAL_DELTA_VS_TA2": _mean([d["delta_PR_AUC_vs_TA2"] for d in deltas]),
                "POSITIVE_PRIMARY_SEEDS_VS_L1": f"{pos}/3",
                "USER_CLUSTER_95CI_RESIDUAL_MINUS_L1": ci,
                "USER_CLUSTER_95CI_RESIDUAL_MINUS_TA2": boot[f"{best_name}_minus_TA2"]["ci95_pr_auc"],
                "per_seed": deltas,
            }
        )
    else:
        comparisons.update(
            {
                "BEST_RESIDUAL_MODEL": "NONE",
                "BEST_RESIDUAL_MEAN_PR_AUC": None,
                "BEST_RESIDUAL_DELTA_VS_L1": None,
                "BEST_RESIDUAL_DELTA_VS_TA2": None,
                "POSITIVE_PRIMARY_SEEDS_VS_L1": "0/3",
                "USER_CLUSTER_95CI_RESIDUAL_MINUS_L1": None,
                "USER_CLUSTER_95CI_RESIDUAL_MINUS_TA2": None,
            }
        )
        write_csv(_review("03_validation_confirmation", "EDITOR015_STABILITY_RESULTS.csv"), [])

    write_json(_review("03_validation_confirmation", "EDITOR015_PRIMARY_COMPARISONS.json"), comparisons)
    write_json(_review("04_statistics", "EDITOR015_CLUSTER_BOOTSTRAP.json"), boot)
    write_json(_review("04_statistics", "EDITOR015_FIXED_COMBINATION_BOOTSTRAP.json"), combo_boot)
    return {
        "packs": packs,
        "comparisons": comparisons,
        "boot": boot,
        "combo_boot": combo_boot,
        "best_name": best_name,
        "residual_value": residual_value,
        "ext_trig": ext_trig,
        "ext_pos": ext_pos,
        "stab_rows": stab_rows,
        "l1_train_cache": l1_train_cache,
        "fixed_ruling": fixed_ruling,
        "best_combo": best_combo,
    }


def run_mechanism_and_directional(
    *,
    bundle: dict[str, Any],
    ens: dict[str, dict[str, np.ndarray]],
    confirm: dict[str, Any],
    device: torch.device,
) -> dict[str, Any]:
    y_val = np.asarray(bundle["val"].y)
    users = np.asarray(bundle["val"].user).astype(str)
    best = confirm["best_name"]
    if best == "NONE" or (best, SCREENING_SEED) not in confirm["packs"]:
        ta2, _ = load_ta2(SCREENING_SEED, device)
        train_loader = make_xy_loader(bundle["train"].X, bundle["train"].y, seed=0, shuffle=False)
        val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=0, shuffle=False)
        tr = score_ta2(ta2, train_loader, device)
        va = score_ta2(ta2, val_loader, device)
        refs = train_references(tr["tree_outputs"])
        faith = directional_table(
            y=y_val,
            tree_outputs=va["tree_outputs"],
            references=refs,
            linear_logit=np.zeros(len(y_val), dtype=np.float64),
            reference_tree_outputs=None,
            users=users,
        )
        write_csv(_review("05_directional_faithfulness", "EDITOR015_DIRECTIONAL_CONTRIBUTIONS.csv"), faith["contributions"])
        write_json(
            _review("05_directional_faithfulness", "EDITOR015_DIRECTIONAL_FAITHFULNESS.json"),
            {
                **{k: faith[k] for k in faith if k not in {"contributions", "bootstrap"}},
                "model": "TA2",
                "residual_promoted": False,
                "HISTORICAL_GLOBAL_TOPK_FAITHFULNESS": TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS,
            },
        )
        write_json(_review("05_directional_faithfulness", "EDITOR015_DIRECTIONAL_BOOTSTRAP.json"), faith["bootstrap"])
        return {"directional": faith, "mechanism": {"skipped_residual": True, "reason": "no promoted residual model"}}

    pack = confirm["packs"][(best, SCREENING_SEED)]
    student, modules = load_trained_residual(pack["best_checkpoint"], device)
    train_loader = make_xy_loader(bundle["train"].X, bundle["train"].y, seed=0, shuffle=False)
    val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=0, shuffle=False)
    tr = evaluate_residual(student, modules, train_loader, device, from_z=False)
    va = evaluate_residual(student, modules, val_loader, device, from_z=False)
    refs = train_references(tr["tree_outputs"])
    l1_logit = np.asarray(confirm["packs"][("L1", SCREENING_SEED)]["student_logits"])
    ens_val = ens["val"]["ens_logit"]
    resid = np.asarray(va["residual_logits"])
    target = ens_val - l1_logit
    y = np.asarray(va["y"]).astype(int)
    l1_thr = float(confirm["packs"][("L1", SCREENING_SEED)]["threshold"])
    res_thr = float(pack["threshold"])
    l1_pred = (1.0 / (1.0 + np.exp(-np.clip(l1_logit, -60, 60))) >= l1_thr).astype(int)
    res_pred = (1.0 / (1.0 + np.exp(-np.clip(va["logits"], -60, 60))) >= res_thr).astype(int)
    mech = {
        "residual_teacher_target_correlation_all": float(np.corrcoef(resid, target)[0, 1]) if resid.size > 2 else float("nan"),
        "residual_teacher_target_correlation_positive": float(np.corrcoef(resid[y == 1], target[y == 1])[0, 1]) if (y == 1).sum() > 2 else float("nan"),
        "residual_teacher_target_correlation_negative": float(np.corrcoef(resid[y == 0], target[y == 0])[0, 1]) if (y == 0).sum() > 2 else float("nan"),
        "MAE_all": float(np.mean(np.abs(resid - target))),
        "residual_variance": float(np.var(resid)),
        "residual_mean": float(np.mean(resid)),
        "residual_magnitude": float(np.mean(np.abs(resid))),
    }
    for tag, mask in (("positive", y == 1), ("negative", y == 0)):
        mech[f"L1_wrong_residual_correct_{tag}"] = int(np.logical_and(l1_pred != y, res_pred == y)[mask].sum())
        mech[f"L1_correct_residual_wrong_{tag}"] = int(np.logical_and(l1_pred == y, res_pred != y)[mask].sum())
        mech[f"both_correct_{tag}"] = int(np.logical_and(l1_pred == y, res_pred == y)[mask].sum())
        mech[f"both_wrong_{tag}"] = int(np.logical_and(l1_pred != y, res_pred != y)[mask].sum())

    if pack.get("route"):
        teacher, _ = load_topt(SCREENING_SEED, device)
        freeze_teacher(teacher)
        from editor012_rescue.evaluate import evaluate_pair

        rel = evaluate_pair(student=student, teacher=teacher, loader=val_loader, device=device)
        mech["route_MAE"] = rel.get("route_MAE")
        mech["route_KL"] = rel.get("route_KL")
        mech["hard_route_agreement"] = rel.get("hard_route_agreement")
        mech["dominant_leaf_agreement"] = rel.get("dominant_leaf_agreement")
        mech["route_leaf_traceability"] = "internal evidence"

    faith = directional_table(
        y=y_val,
        tree_outputs=va["tree_outputs"],
        references=refs,
        linear_logit=va["linear_logits"],
        reference_tree_outputs=None,
        users=users,
    )
    # Use live residual intervention: reconstruct reference trees from residual definition if available.
    write_csv(_review("05_directional_faithfulness", "EDITOR015_DIRECTIONAL_CONTRIBUTIONS.csv"), faith["contributions"])
    write_json(
        _review("05_directional_faithfulness", "EDITOR015_DIRECTIONAL_FAITHFULNESS.json"),
        {k: faith[k] for k in faith if k not in {"contributions", "bootstrap"}},
    )
    write_json(_review("05_directional_faithfulness", "EDITOR015_DIRECTIONAL_BOOTSTRAP.json"), faith["bootstrap"])
    return {"directional": faith, "mechanism": mech}


def write_editor_response(
    *,
    identities: dict[str, Any],
    protocol: dict[str, Any],
    comp: dict[str, Any],
    inner: dict[str, Any],
    confirm: dict[str, Any],
    mech: dict[str, Any],
    commits: dict[str, str],
) -> dict[str, Any]:
    ruling_pred = confirm["residual_value"]
    faith = mech.get("directional", {})
    local = faith.get("LOCAL_DIRECTIONAL_TREE_FAITHFULNESS", "NOT_SUPPORTED")
    combo = confirm["fixed_ruling"]
    residual_ok = ruling_pred in {
        "STRONG_RESIDUAL_ODST_VALUE",
        "CONSISTENT_RESIDUAL_ODST_VALUE",
        "STABLE_RESIDUAL_ODST_VALUE",
    }
    combo_ok = combo in {"STRONG", "CONSISTENT"}
    local_ok = local == "SUPPORTED" and confirm["best_name"] != "NONE"
    if residual_ok or combo_ok or local_ok:
        odst_issue = "RESOLVED"
    elif ruling_pred == "NO_RESIDUAL_ODST_VALUE" and combo == "MIXED":
        odst_issue = "PARTIALLY_RESOLVED"
    elif local == "QUALIFIED":
        odst_issue = "PARTIALLY_RESOLVED"
    else:
        odst_issue = "NOT_RESOLVED"

    inner_by = {r["condition"]: r for r in inner["rows"]}
    def _inner_pr(name: str) -> Any:
        rec = inner_by.get(name)
        if rec is None or not rec.get("executed", True):
            return "REDUNDANT_NOT_EXECUTED" if name == "R3" else None
        return rec.get("select_PR_AUC")

    why_teacher = (
        "Equal-weight ensemble logit guidance remains the only intervention with a supported "
        "predictive increment over matched task-only training; residual experiments inherit that L1 base."
    )
    if residual_ok:
        why_odst = (
            "Function-preserving residual ODST supplied a nonlinear correction to L1 that improved "
            "official validation ranking under the predeclared residual family."
        )
        paper_model = confirm["best_name"]
    elif combo_ok:
        why_odst = (
            "ODST did not beat L1 as a residual correction, but a frozen L1+TA2 combination "
            "showed complementary ranking signal without new training."
        )
        paper_model = confirm["best_combo"]
    else:
        why_odst = (
            "Neither the function-preserving residual nor a fixed L1+TA2 combination established "
            "reproducible incremental ranking value over the matched teacher-guided linear base."
        )
        paper_model = "TA2" if FROZEN_TA2_MEAN_PR_AUC >= FROZEN_L1_MEAN_PR_AUC else "L1"

    if residual_ok:
        next_action = "Promote the residual model into the paper-facing comparison table and keep global top-k faithfulness frozen as NOT_SUPPORTED."
    elif combo_ok:
        next_action = "Report TA2 as the current paper ODST model and treat the fixed combination as a descriptive complementarity result, not a new trained architecture."
    else:
        next_action = "Keep TA2 as BEST_CURRENT_PAPER_MODEL. Do not launch another generic ODST search."

    odst_ruling = {
        "RESIDUAL_ODST_VALUE": ruling_pred,
        "FIXED_LINEAR_ODST_COMPLEMENTARITY": combo,
        "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": local,
        "HISTORICAL_GLOBAL_TOPK_FAITHFULNESS": TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "EDITOR_ISSUE_TEACHER_INITIALISATION_ONLY": "RESOLVED",
        "EDITOR_ISSUE_C5_NEGLIGIBLE_INCREMENT": "RESOLVED_BY_TA2",
        "EDITOR_ISSUE_ODST_VALUE": odst_issue,
        "BEST_CURRENT_PAPER_MODEL": paper_model,
        "WHY_TEACHER_GUIDANCE": why_teacher,
        "WHY_ODST": why_odst,
        "NEXT_RECOMMENDED_ACTION": next_action,
        "PREVIOUS_RESIDUAL_ODST_INITIAL_GRADIENT": protocol["previous_residual"]["PREVIOUS_RESIDUAL_ODST_INITIAL_GRADIENT"],
        "FUNCTION_PRESERVING_RESIDUAL_INITIAL_OUTPUT": "ZERO",
        "FUNCTION_PRESERVING_RESIDUAL_INITIAL_ODST_GRADIENT": "NONZERO",
        "mechanism": mech.get("mechanism", {}),
        "commits": commits,
    }
    write_json(_review("06_editor_response", "EDITOR015_ODST_VALUE_RULING.json"), odst_ruling)
    matrix = [
        {"issue": "TEACHER_GUIDANCE_VS_INITIALISATION", "status": "SUPPORTED_STRONG", "resolution": "RESOLVED"},
        {"issue": "EDITOR_ISSUE_TEACHER_INITIALISATION_ONLY", "status": "RESOLVED", "resolution": "RESOLVED"},
        {"issue": "EDITOR_ISSUE_C5_NEGLIGIBLE_INCREMENT", "status": "RESOLVED_BY_TA2", "resolution": "RESOLVED_BY_TA2"},
        {"issue": "POST_ATTENTION_ODST_INCREMENTAL_VALUE", "status": POST_ATTENTION_ODST_INCREMENTAL_VALUE, "resolution": "frozen"},
        {"issue": "TEMPORAL_ODST_INCREMENTAL_VALUE", "status": TEMPORAL_ODST_INCREMENTAL_VALUE, "resolution": "frozen"},
        {"issue": "TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS", "status": TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS, "resolution": "frozen"},
        {"issue": "RESIDUAL_ODST_VALUE", "status": ruling_pred, "resolution": odst_issue},
        {"issue": "FIXED_LINEAR_ODST_COMPLEMENTARITY", "status": combo, "resolution": odst_issue},
        {"issue": "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS", "status": local, "resolution": local},
        {"issue": "EDITOR_ISSUE_ODST_VALUE", "status": odst_issue, "resolution": odst_issue},
    ]
    write_csv(_review("06_editor_response", "EDITOR015_EDITOR_ISSUE_MATRIX.csv"), matrix)

    gate = {
        "paper_rescue_ready": residual_ok or combo_ok,
        "BEST_CURRENT_PAPER_MODEL": paper_model,
        "RESIDUAL_ODST_VALUE": ruling_pred,
        "FIXED_LINEAR_ODST_COMPLEMENTARITY": combo,
        "EDITOR_ISSUE_ODST_VALUE": odst_issue,
        "do_not_overwrite_global_topk_faithfulness": True,
    }
    write_json(_review("07_paper_handover", "EDITOR015_PAPER_RESCUE_GATE.json"), gate)
    md = [
        "# EDITOR-015 paper rescue handover",
        "",
        f"Residual ODST value: **{ruling_pred}**",
        f"Fixed L1+TA2 complementarity: **{combo}**",
        f"Local directional faithfulness: **{local}**",
        f"Historical global top-k faithfulness: **{TA2_REFERENCE_CENTRED_GLOBAL_TOPK_FAITHFULNESS}** (frozen)",
        f"Best current paper model: **{paper_model}**",
        "",
        f"Why teacher guidance: {why_teacher}",
        "",
        f"Why ODST: {why_odst}",
        "",
        f"Next recommended action: {next_action}",
        "",
        "Do not convert local directional faithfulness into a global PR-AUC faithfulness claim.",
    ]
    path = _review("07_paper_handover", "EDITOR015_PAPER_RESCUE_HANDOVER.md")
    refuse_historical_write(path)
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return {
        "odst_ruling": odst_ruling,
        "inner_pr": {n: _inner_pr(n) for n in ("L1", "TA2", "R0", "R1", "R2", "R3")},
        "paper_model": paper_model,
        "odst_issue": odst_issue,
        "why_teacher": why_teacher,
        "why_odst": why_odst,
        "next_action": next_action,
    }


def run_campaign(*, resume_after_inner: bool = False) -> dict[str, Any]:
    protocol = write_protocol_packet()
    identities = verify_identities()
    device = _device()
    print(f"[EDITOR-015] device={device}", flush=True)
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    ens = load_ensemble_cache()
    teachers = {}
    for seed in PRIMARY_SEEDS:
        model, _ = load_topt(seed, device)
        freeze_teacher(model)
        teachers[seed] = model
    pos_weight = float(bundle["pos_weight"])
    comp = run_complementarity(bundle=bundle, ens=ens, device=device)
    promo_path = _review("02_inner_residual", "EDITOR015_PROMOTION_FREEZE.json")
    if resume_after_inner and promo_path.is_file():
        import csv
        import json

        decision = json.loads(promo_path.read_text(encoding="utf-8"))
        inner_csv = _review("02_inner_residual", "EDITOR015_INNER_RESIDUAL_RESULTS.csv")
        rows = []
        if inner_csv.is_file():
            with inner_csv.open(encoding="utf-8") as handle:
                for rec in csv.DictReader(handle):
                    if rec.get("select_PR_AUC") not in {"", "nan", "None"}:
                        rec["select_PR_AUC"] = float(rec["select_PR_AUC"])
                    if rec.get("select_F1") not in {"", "nan", "None"}:
                        rec["select_F1"] = float(rec["select_F1"])
                    rec["executed"] = str(rec.get("executed", "True")).lower() == "true"
                    rows.append(rec)
        inner = {"rows": rows, "packs": {}, "decision": decision, "e2e_rows": [], "r3": "REDUNDANT_NOT_EXECUTED"}
        mark_promotion_frozen()
    else:
        inner = run_inner_residual(
            bundle=bundle, teachers=teachers, ens=ens, comp=comp, device=device, pos_weight=pos_weight
        )
    confirm = run_confirmation(
        bundle=bundle, teachers=teachers, ens=ens, device=device, pos_weight=pos_weight,
        inner=inner, mapping=mapping, comp=comp,
    )
    mech = run_mechanism_and_directional(bundle=bundle, ens=ens, confirm=confirm, device=device)
    commits = {
        "EDITOR015_PROTOCOL_COMMIT": "PENDING_015A",
        "EDITOR015_IMPLEMENTATION_COMMIT": "PENDING_015A",
        "EDITOR015_PROMOTION_COMMIT": "PENDING_015B",
        "EDITOR015_RESULTS_COMMIT": "PENDING_015C",
    }
    synth = write_editor_response(
        identities=identities, protocol=protocol, comp=comp, inner=inner, confirm=confirm, mech=mech, commits=commits
    )
    manifest = {
        "task_id": "EDITOR-015",
        "created_utc": utc_now(),
        "device": str(device),
        "promoted": inner["decision"]["promoted"],
        "architecture": ENCODER_ARCH,
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
        "r52_test_accessed": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "identities": identities,
        "comparisons": confirm["comparisons"],
        "residual_value": confirm["residual_value"],
        "EDITOR_ISSUE_ODST_VALUE": synth["odst_issue"],
    }
    write_json(_review("EDITOR015_RUN_MANIFEST.json"), manifest)
    return {
        "identities": identities,
        "protocol": protocol,
        "comp": comp,
        "inner": inner,
        "confirm": confirm,
        "mech": mech,
        "synth": synth,
        "manifest": manifest,
    }


def run_inner_phase() -> dict[str, Any]:
    protocol = write_protocol_packet()
    identities = verify_identities()
    device = _device()
    bundle = load_train_validation()
    recover_user_mapping(bundle)
    ens = load_ensemble_cache()
    teachers = {}
    for seed in PRIMARY_SEEDS:
        model, _ = load_topt(seed, device)
        freeze_teacher(model)
        teachers[seed] = model
    comp = run_complementarity(bundle=bundle, ens=ens, device=device)
    inner = run_inner_residual(
        bundle=bundle, teachers=teachers, ens=ens, comp=comp, device=device, pos_weight=float(bundle["pos_weight"])
    )
    return {"protocol": protocol, "identities": identities, "comp": comp, "inner": inner}


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
