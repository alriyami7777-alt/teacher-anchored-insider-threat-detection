"""EDITOR-016 autonomous uncertainty-routed ODST specialist orchestrator."""

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
from editor012_rescue.producing import build_odst046_model, pin_producing_sources

from .constants import (
    BEST_CURRENT_PAPER_MODEL,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    EDITOR015_RESULTS_FULL_COMMIT,
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
    FIXED_LINEAR_ODST_COMPLEMENTARITY,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_MEAN_PR_AUC,
    HISTORICAL_GLOBAL_TOPK_FAITHFULNESS,
    L1_CHECKPOINTS,
    LAMBDA_ROUTE,
    LAMBDA_TEACHER,
    LOCAL_DIRECTIONAL_TREE_FAITHFULNESS,
    ODST046,
    POST_ATTENTION_ODST_INCREMENTAL_VALUE,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    Q_VALUES,
    RESIDUAL_ODST_VALUE,
    SCREENING_SEED,
    SPECIALIST_CONDITIONS,
    SPECIALIST_ORDER,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TEMPORAL_ODST_INCREMENTAL_VALUE,
    TOPT_CHECKPOINTS,
)
from .efficiency import measure_cascade_efficiency
from .explain import routed_directional_table, train_references
from .freeze import write_protocol_packet
from .gate import freeze_thresholds, gate_indicator, gate_metrics, l1_margin
from .io_util import write_csv, write_json
from .promotion import decide_promotions
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor016Blocked,
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
    evaluate_specialist,
    load_l1_pair,
    load_ta2,
    load_topt,
    load_trained_specialist,
    score_l1,
    score_ta2,
    train_specialist,
)


def _review(*parts: str) -> Path:
    path = REVIEW_ROOT.joinpath(*parts)
    refuse_historical_write(path)
    return path


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _mean(xs: list[float]) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def _cond(name: str, q: float) -> str:
    return f"{name}@q{q:.2f}"


def verify_identities() -> dict[str, Any]:
    try:
        refuse_r52_test(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz"
        )
        raise Editor016Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    pins = pin_producing_sources()
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4 or float(ODST046["temperature"]) != 0.5:
        raise Editor016Blocked("ODST-046 lock mismatch")
    if abs(float(LAMBDA_TEACHER) - 0.5) > 1e-15 or abs(float(LAMBDA_ROUTE) - 0.5) > 1e-15:
        raise Editor016Blocked("lambda mismatch")
    teacher = build_odst046_model()
    assert_odst046(teacher)
    if EDITOR015_RESULTS_FULL_COMMIT != "d8e1d04b8c199f56cab9956f62c16cd4301f0bac":
        raise Editor016Blocked("EDITOR-015 results commit mismatch")
    if EDITOR012_RESULTS_COMMIT != "4bcf522a502ed98e5dd393a80bd9da7fffd51964":
        raise Editor016Blocked("EDITOR-012 results commit mismatch")
    if EDITOR013_RESULTS_COMMIT != "09c4bb97b143810147feef08f31a8d8d042a6726":
        raise Editor016Blocked("EDITOR-013 results commit mismatch")
    if EDITOR014_RESULTS_COMMIT != "c3343462dc3b35d20907da6ad017f5f853852f84":
        raise Editor016Blocked("EDITOR-014 results commit mismatch")
    return {
        "r52_test_hard_denied": True,
        "odst046_identity_verified": True,
        "lambda_teacher": LAMBDA_TEACHER,
        "lambda_route": LAMBDA_ROUTE,
        "producing_pins": pins,
        "architecture": architecture_identity(teacher),
        "EDITOR015_RESULTS_FULL_COMMIT": EDITOR015_RESULTS_FULL_COMMIT,
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "POST_ATTENTION_ODST_INCREMENTAL_VALUE": POST_ATTENTION_ODST_INCREMENTAL_VALUE,
        "TEMPORAL_ODST_INCREMENTAL_VALUE": TEMPORAL_ODST_INCREMENTAL_VALUE,
        "RESIDUAL_ODST_VALUE": RESIDUAL_ODST_VALUE,
        "FIXED_LINEAR_ODST_COMPLEMENTARITY": FIXED_LINEAR_ODST_COMPLEMENTARITY,
    }


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor016Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor016Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor016Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor016Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    rec = {
        "USER_MAPPING_RECOVERED": True,
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "per_user_count_min": int(counts.min()),
        "per_user_count_max": int(counts.max()),
        "n_malicious_users": int(len(malicious)),
        "malicious_users": malicious,
        "mapping_sha256": mapping_hash,
        "hash_matches_EDITOR011_012_013_014_015": True,
        "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
    }
    write_json(_review("04_statistics", "EDITOR016_USER_MAPPING_VERIFICATION.json"), rec)
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
def _cache_l1(student, modules, X, y, device: torch.device) -> dict[str, np.ndarray]:
    loader = make_xy_loader(X, y, seed=0, shuffle=False)
    scored = score_l1(student, modules, loader, device)
    return {"z": scored["z"], "l1_logit": scored["logits"], "y": scored["y"]}


@torch.no_grad()
def _cache_topt_choices(teacher, X, y, device: torch.device) -> np.ndarray:
    loader = make_xy_loader(X, y, seed=0, shuffle=False)
    scored = score_ta2(teacher, loader, device)
    return scored["choices"]


def _loader(X, y, ens, l1, gate, *, seed: int, shuffle: bool, choices=None, mask=None):
    if mask is not None:
        X = X[mask]
        y = y[mask]
        ens = ens[mask]
        l1 = l1[mask]
        gate = gate[mask]
        if choices is not None:
            choices = choices[mask]
    extras = [ens, l1, gate.astype(np.float32)]
    if choices is not None:
        extras.append(choices)
    return make_xy_loader(X, y, seed=seed, shuffle=shuffle, extras=extras)


def run_inner_specialist(
    *,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    ens: dict[str, dict[str, np.ndarray]],
    device: torch.device,
    pos_weight: float,
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
            raise Editor016Blocked("INNER split mismatch")
        inner_tr = subset_bundle(bundle["train"], split["train_mask"], "inner_train")
        inner_se = subset_bundle(bundle["train"], split["select_mask"], "inner_select")
        ens_tr = ens["train"]["ens_logit"][split["train_mask"]]
        ens_se = ens["train"]["ens_logit"][split["select_mask"]]
        l1_s, l1_m, _ = load_l1_pair(SCREENING_SEED, device)
        cache_tr = _cache_l1(l1_s, l1_m, inner_tr.X, inner_tr.y, device)
        cache_se = _cache_l1(l1_s, l1_m, inner_se.X, inner_se.y, device)
        topt_tr = _cache_topt_choices(teachers[SCREENING_SEED], inner_tr.X, inner_tr.y, device)
        topt_se = _cache_topt_choices(teachers[SCREENING_SEED], inner_se.X, inner_se.y, device)
        cache_dir = OUTPUT_ROOT / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / "inner_seed42.npz"
        np.savez_compressed(
            cache_path,
            z_tr=cache_tr["z"],
            z_se=cache_se["z"],
            l1_tr=cache_tr["l1_logit"],
            l1_se=cache_se["l1_logit"],
            y_tr=cache_tr["y"],
            y_se=cache_se["y"],
            ens_tr=ens_tr,
            ens_se=ens_se,
            topt_tr=topt_tr,
            topt_se=topt_se,
        )
        cache_rec = {
            "path": str(cache_path),
            "SHA256": sha256_file(cache_path),
            "INNER_TRAIN_n": int(len(cache_tr["y"])),
            "INNER_SELECT_n": int(len(cache_se["y"])),
            "z_dim": int(cache_tr["z"].shape[-1]),
            "seed": SCREENING_SEED,
            "official_validation_used": False,
        }
        write_json(_review("02_inner_specialist", "EDITOR016_HEAD_CACHE.json"), cache_rec)

        taus = freeze_thresholds(cache_tr["l1_logit"], seed=SCREENING_SEED, source="INNER_TRAIN")
        gate_rows = []
        unc_rows = []
        margins_tr = l1_margin(cache_tr["l1_logit"])
        margins_se = l1_margin(cache_se["l1_logit"])
        for part, margins, y, l1, src in (
            ("INNER_TRAIN", margins_tr, cache_tr["y"], cache_tr["l1_logit"], "INNER_TRAIN"),
            ("INNER_SELECT", margins_se, cache_se["y"], cache_se["l1_logit"], "INNER_TRAIN"),
        ):
            unc_rows.append(
                {
                    "partition": part,
                    "seed": SCREENING_SEED,
                    "n": int(len(y)),
                    "margin_mean": float(margins.mean()),
                    "margin_median": float(np.median(margins)),
                    "margin_p10": float(np.quantile(margins, 0.10)),
                    "margin_p50": float(np.quantile(margins, 0.50)),
                    "L1_PR_AUC": float(metrics_from_logits(y, l1)["pr_auc"]),
                    "tau_source": src,
                }
            )
        gates: dict[float, dict[str, np.ndarray]] = {}
        for q in Q_VALUES:
            tau = taus[float(q)]
            g_tr = gate_indicator(cache_tr["l1_logit"], tau)
            g_se = gate_indicator(cache_se["l1_logit"], tau)
            gates[float(q)] = {"train": g_tr, "select": g_se, "tau": tau}
            gate_rows.append(
                gate_metrics(
                    y=cache_tr["y"],
                    l1_logit=cache_tr["l1_logit"],
                    gate=g_tr,
                    partition="INNER_TRAIN",
                    q=q,
                    tau=tau,
                    seed=SCREENING_SEED,
                    tau_source="INNER_TRAIN",
                )
            )
            gate_rows.append(
                gate_metrics(
                    y=cache_se["y"],
                    l1_logit=cache_se["l1_logit"],
                    gate=g_se,
                    partition="INNER_SELECT",
                    q=q,
                    tau=tau,
                    seed=SCREENING_SEED,
                    tau_source="INNER_TRAIN",
                )
            )
        write_csv(_review("01_uncertainty_audit", "EDITOR016_GATE_DISTRIBUTIONS.csv"), gate_rows)
        write_csv(_review("01_uncertainty_audit", "EDITOR016_L1_UNCERTAINTY_RESULTS.csv"), unc_rows)

        l1_sel = metrics_from_logits(cache_se["y"], cache_se["l1_logit"])
        rows = [
            {
                "condition": "L1",
                "q": "",
                "select_PR_AUC": float(l1_sel["pr_auc"]),
                "select_F1": float(l1_sel["f1"]),
                "executed": True,
                "official_validation_used": False,
            }
        ]
        packs: dict[str, Any] = {}
        for q in Q_VALUES:
            g_tr = gates[float(q)]["train"]
            g_se = gates[float(q)]["select"]
            tau = gates[float(q)]["tau"]
            coverage = float(g_se.mean())
            for name in SPECIALIST_ORDER:
                spec = dict(SPECIALIST_CONDITIONS[name])
                spec["q"] = float(q)
                train_mask = g_tr.astype(bool)
                if int(train_mask.sum()) == 0:
                    raise Editor016Blocked(f"empty gated INNER_TRAIN at q={q}")
                choices_tr = topt_tr if spec["route"] else None
                choices_se = topt_se if spec["route"] else None
                train_loader = _loader(
                    cache_tr["z"],
                    cache_tr["y"],
                    ens_tr,
                    cache_tr["l1_logit"],
                    g_tr,
                    seed=SCREENING_SEED,
                    shuffle=True,
                    choices=choices_tr,
                    mask=train_mask,
                )
                select_loader = _loader(
                    cache_se["z"],
                    cache_se["y"],
                    ens_se,
                    cache_se["l1_logit"],
                    g_se,
                    seed=SCREENING_SEED,
                    shuffle=False,
                    choices=choices_se,
                )
                cond = _cond(name, q)
                pack = train_specialist(
                    condition=cond,
                    spec=spec,
                    seed=SCREENING_SEED,
                    start_seed=SCREENING_SEED,
                    train_loader=train_loader,
                    select_loader=select_loader,
                    device=device,
                    pos_weight=pos_weight,
                    matched_teacher=None,
                    select_name="inner_select",
                    encoder_trainable=False,
                    use_source_l1=True,
                )
                packs[cond] = pack
                rows.append(
                    {
                        "condition": cond,
                        "family": name,
                        "q": float(q),
                        "tau": tau,
                        "gate_coverage": coverage,
                        "select_PR_AUC": pack["select_PR_AUC"],
                        "select_F1": pack["select_F1"],
                        "Brier": pack["Brier"],
                        "log_loss": pack["log_loss"],
                        "best_epoch": pack["best_epoch"],
                        "head": spec["head"],
                        "teacher_residual": spec["teacher_residual"],
                        "route": spec["route"],
                        "executed": True,
                        "official_validation_used": False,
                    }
                )
                print(f"[EDITOR-016] INNER {cond} PR-AUC={pack['select_PR_AUC']:.6f}", flush=True)

        l1_pr = float(l1_sel["pr_auc"])
        qualifying = []
        for q in Q_VALUES:
            s1 = next(r for r in rows if r["condition"] == _cond("S1", q))
            s2 = next(r for r in rows if r["condition"] == _cond("S2", q))
            for name in ("S3", "S4"):
                rec = next(r for r in rows if r["condition"] == _cond(name, q))
                if (
                    float(rec["select_PR_AUC"]) >= l1_pr + PROMOTION_MARGIN
                    and float(rec["select_PR_AUC"]) >= float(s1["select_PR_AUC"]) + PROMOTION_MARGIN
                    and float(rec["select_PR_AUC"]) > float(s2["select_PR_AUC"])
                ):
                    qualifying.append((name, float(q)))

        e2e_rows: list[dict[str, Any]] = []
        for name, q in qualifying:
            spec = dict(SPECIALIST_CONDITIONS[name])
            spec["q"] = q
            g_tr = gates[q]["train"]
            g_se = gates[q]["select"]
            train_loader = _loader(
                inner_tr.X,
                inner_tr.y,
                ens_tr,
                cache_tr["l1_logit"],
                g_tr,
                seed=SCREENING_SEED,
                shuffle=True,
                mask=g_tr.astype(bool),
            )
            select_loader = _loader(
                inner_se.X,
                inner_se.y,
                ens_se,
                cache_se["l1_logit"],
                g_se,
                seed=SCREENING_SEED,
                shuffle=False,
            )
            cond = f"E2E_{_cond(name, q)}"
            pack = train_specialist(
                condition=cond,
                spec=spec,
                seed=SCREENING_SEED,
                start_seed=SCREENING_SEED,
                train_loader=train_loader,
                select_loader=select_loader,
                device=device,
                pos_weight=pos_weight,
                matched_teacher=teachers[SCREENING_SEED] if spec["route"] else None,
                select_name="inner_select",
                encoder_trainable=True,
                use_source_l1=False,
            )
            packs[cond] = pack
            rec = {
                "condition": cond,
                "family": name,
                "q": q,
                "tau": gates[q]["tau"],
                "gate_coverage": float(g_se.mean()),
                "select_PR_AUC": pack["select_PR_AUC"],
                "select_F1": pack["select_F1"],
                "Brier": pack["Brier"],
                "log_loss": pack["log_loss"],
                "best_epoch": pack["best_epoch"],
                "head": spec["head"],
                "teacher_residual": spec["teacher_residual"],
                "route": spec["route"],
                "executed": True,
                "official_validation_used": False,
            }
            rows.append(rec)
            e2e_rows.append(rec)
            print(f"[EDITOR-016] INNER {cond} PR-AUC={pack['select_PR_AUC']:.6f}", flush=True)

        write_csv(
            _review("02_inner_specialist", "EDITOR016_INNER_SPECIALIST_RESULTS.csv"),
            rows,
            fieldnames=[
                "condition",
                "family",
                "q",
                "select_PR_AUC",
                "select_F1",
                "head",
                "teacher_residual",
                "route",
                "gate_coverage",
                "Brier",
                "log_loss",
                "best_epoch",
                "executed",
                "official_validation_used",
            ],
        )
        write_csv(_review("02_inner_specialist", "EDITOR016_E2E_CONDITIONAL_RESULTS.csv"), e2e_rows)
        decision = decide_promotions(rows)
        write_json(_review("02_inner_specialist", "EDITOR016_MATCHED_FACTORIAL_EFFECTS.json"), decision["factorial_effects"])
        write_json(_review("02_inner_specialist", "EDITOR016_PROMOTION_FREEZE.json"), decision)
        mark_promotion_frozen()
        return {
            "rows": rows,
            "packs": packs,
            "decision": decision,
            "e2e_rows": e2e_rows,
            "split": split,
            "taus": {str(k): v for k, v in taus.items()},
            "l1_pr": l1_pr,
            "cache": cache_rec,
            "gates": {str(k): {"tau": float(v["tau"]), "coverage_select": float(v["select"].mean())} for k, v in gates.items()},
        }
    finally:
        exit_inner_phase()


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


def _pack_val_row(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition": pack["condition"],
        "seed": pack["seed"],
        "q": pack.get("q", ""),
        "validation_PR_AUC": pack["validation_PR_AUC"],
        "validation_F1": pack.get("validation_F1", pack.get("select_F1")),
        "precision": pack.get("precision"),
        "recall": pack.get("recall"),
        "FP": pack.get("FP"),
        "FN": pack.get("FN"),
        "Brier": pack.get("Brier"),
        "log_loss": pack.get("log_loss"),
        "predicted_positive_fraction": pack.get("predicted_positive_fraction"),
        "gate_coverage": pack.get("gate_coverage"),
        "best_epoch": pack.get("best_epoch"),
        "best_checkpoint_sha256": pack.get("best_checkpoint_sha256"),
        "imported": pack.get("imported", False),
    }


def classify_gate(mean_delta: float, pos: int, ci_lo: float | None, ext_pos: int | None, ext_trig: bool) -> str:
    if mean_delta > 0 and pos == 3 and ci_lo is not None and ci_lo > 0:
        return "STRONG"
    if mean_delta > 0 and pos == 3:
        return "CONSISTENT"
    if ext_trig and ext_pos is not None and ext_pos >= 8 and mean_delta > 0 and pos >= 2:
        return "STABILITY_ONLY"
    return "NOT_SUPPORTED"


def run_confirmation(
    *,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    ens: dict[str, dict[str, np.ndarray]],
    device: torch.device,
    pos_weight: float,
    inner: dict[str, Any],
) -> dict[str, Any]:
    y_val = np.asarray(bundle["val"].y)
    users = np.asarray(bundle["val"].user).astype(str)
    packs: dict[tuple[str, int], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    routed_rows: list[dict[str, Any]] = []
    raw_store: dict[tuple[str, int], dict[str, np.ndarray]] = {}

    for seed in PRIMARY_SEEDS:
        packs[("L1", seed)] = import_frozen_val("L1", seed, L1_CHECKPOINTS[seed], y_val)
        rows.append(_pack_val_row(packs[("L1", seed)]))
        packs[("TA2", seed)] = import_frozen_val("TA2", seed, F11_CHECKPOINTS[seed], y_val)
        rows.append(_pack_val_row(packs[("TA2", seed)]))

    promoted = list(inner["decision"]["promoted"])
    needed: list[dict[str, Any]] = list(promoted)
    seen = {(p["inner_condition"], float(p["q"])) for p in promoted}
    for promo in promoted:
        q = float(promo["q"])
        for name in ("S1", "S2"):
            if (name, q) not in seen:
                needed.append(
                    {
                        "inner_condition": name,
                        "q": q,
                        "promoted_condition": _cond(name, q),
                        "stage": "head_only",
                        "spec": {**SPECIALIST_CONDITIONS[name], "q": q, "encoder_trainable": False},
                    }
                )
                seen.add((name, q))

    for promo in needed:
        name = promo["promoted_condition"]
        family = promo["inner_condition"]
        spec = dict(SPECIALIST_CONDITIONS[family])
        spec["q"] = float(promo["q"])
        encoder_trainable = bool(promo["spec"]["encoder_trainable"])
        q = float(promo["q"])
        for seed in PRIMARY_SEEDS:
            l1_s, l1_m, _ = load_l1_pair(seed, device)
            cache_tr = _cache_l1(l1_s, l1_m, bundle["train"].X, bundle["train"].y, device)
            cache_va = _cache_l1(l1_s, l1_m, bundle["val"].X, bundle["val"].y, device)
            tau = freeze_thresholds(cache_tr["l1_logit"], seed=seed, source="TRAIN")[q]
            g_tr = gate_indicator(cache_tr["l1_logit"], tau)
            g_va = gate_indicator(cache_va["l1_logit"], tau)
            if encoder_trainable:
                train_loader = _loader(
                    bundle["train"].X,
                    bundle["train"].y,
                    ens["train"]["ens_logit"],
                    cache_tr["l1_logit"],
                    g_tr,
                    seed=seed,
                    shuffle=True,
                    mask=g_tr.astype(bool),
                )
                val_loader = _loader(
                    bundle["val"].X,
                    bundle["val"].y,
                    ens["val"]["ens_logit"],
                    cache_va["l1_logit"],
                    g_va,
                    seed=seed,
                    shuffle=False,
                )
            else:
                train_loader = _loader(
                    cache_tr["z"],
                    bundle["train"].y,
                    ens["train"]["ens_logit"],
                    cache_tr["l1_logit"],
                    g_tr,
                    seed=seed,
                    shuffle=True,
                    mask=g_tr.astype(bool),
                )
                val_loader = _loader(
                    cache_va["z"],
                    bundle["val"].y,
                    ens["val"]["ens_logit"],
                    cache_va["l1_logit"],
                    g_va,
                    seed=seed,
                    shuffle=False,
                )
            pack = train_specialist(
                condition=name,
                spec=spec,
                seed=seed,
                start_seed=seed,
                train_loader=train_loader,
                select_loader=val_loader,
                device=device,
                pos_weight=pos_weight,
                matched_teacher=teachers[seed] if spec.get("route") and encoder_trainable else None,
                select_name="validation",
                encoder_trainable=encoder_trainable,
                use_source_l1=not encoder_trainable,
            )
            pack["q"] = q
            pack["tau"] = tau
            pack["gate_coverage"] = float(g_va.mean())
            packs[(name, seed)] = pack
            rows.append(_pack_val_row(pack))
            raw_store[(name, seed)] = {
                "l1": np.asarray(pack["linear_logits"]),
                "delta": np.asarray(pack["deltas"]),
                "final": np.asarray(pack["student_logits"]),
                "gate": np.asarray(pack["gates"]),
            }
            g = np.asarray(pack["gates"]).astype(bool)
            if g.any() and np.unique(y_val[g]).size > 1:
                l1m = metrics_from_logits(y_val[g], np.asarray(pack["linear_logits"])[g])
                sm = metrics_from_logits(y_val[g], np.asarray(pack["student_logits"])[g])
            else:
                l1m = {"pr_auc": float("nan"), "f1": float("nan")}
                sm = {"pr_auc": float("nan"), "f1": float("nan")}
            routed_rows.append(
                {
                    "condition": name,
                    "seed": seed,
                    "q": q,
                    "n": int(g.sum()),
                    "prevalence": float(y_val[g].mean()) if g.any() else float("nan"),
                    "L1_PR_AUC": l1m["pr_auc"],
                    "L1_F1": l1m["f1"],
                    "system_PR_AUC": sm["pr_auc"],
                    "system_F1": sm["f1"],
                }
            )

    write_csv(_review("03_validation_confirmation", "EDITOR016_VALIDATION_RESULTS.csv"), rows)
    write_csv(_review("03_validation_confirmation", "EDITOR016_ROUTED_SUBSET_RESULTS.csv"), routed_rows)

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
    best_promo = None
    for promo in promoted:
        name = promo["promoted_condition"]
        m = _mean(_prs(name))
        if m > best_mean:
            best_mean = m
            best_name = name
            best_promo = promo

    boot: dict[str, Any] = {}
    comparisons: dict[str, Any] = {
        "MATCHED_L1_MEAN_PR_AUC": l1_mean,
        "TA2_MEAN_PR_AUC": ta2_mean,
    }
    ext_trig = False
    ext_pos = None
    stab_rows: list[dict[str, Any]] = []
    full_gate = "NOT_SUPPORTED"
    odst_gate = "NOT_SUPPORTED"
    teacher_gate = "NOT_SUPPORTED"
    if best_name != "NONE" and best_promo is not None:
        q = float(best_promo["q"])
        matched_linear = _cond("S1", q)
        matched_task = _cond("S2", q)
        deltas = []
        for seed in PRIMARY_SEEDS:
            a = packs[("L1", seed)]
            b = packs[(best_name, seed)]
            lin = packs[(matched_linear, seed)]
            task = packs[(matched_task, seed)]
            deltas.append(
                {
                    "seed": seed,
                    "delta_PR_AUC_vs_L1": float(b["validation_PR_AUC"]) - float(a["validation_PR_AUC"]),
                    "delta_PR_AUC_vs_linear_specialist": float(b["validation_PR_AUC"]) - float(lin["validation_PR_AUC"]),
                    "delta_PR_AUC_teacher_guidance": float(b["validation_PR_AUC"]) - float(task["validation_PR_AUC"]),
                }
            )
        pos_l1 = sum(1 for d in deltas if d["delta_PR_AUC_vs_L1"] > 0)
        pos_odst = sum(1 for d in deltas if d["delta_PR_AUC_vs_linear_specialist"] > 0)
        pos_teach = sum(1 for d in deltas if d["delta_PR_AUC_teacher_guidance"] > 0)
        mean_l1 = _mean([d["delta_PR_AUC_vs_L1"] for d in deltas])
        mean_odst = _mean([d["delta_PR_AUC_vs_linear_specialist"] for d in deltas])
        mean_teach = _mean([d["delta_PR_AUC_teacher_guidance"] for d in deltas])
        boot["full_system_minus_L1"] = paired_user_cluster_mean_across_seeds(
            users, y_val, _logits("L1"), _logits(best_name),
            frozen_thresholds_a=_thrs("L1"), frozen_thresholds_b=_thrs(best_name),
            n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast="full_system_minus_L1",
        )
        boot["odst_minus_linear_specialist"] = paired_user_cluster_mean_across_seeds(
            users, y_val, _logits(matched_linear), _logits(best_name),
            frozen_thresholds_a=_thrs(matched_linear), frozen_thresholds_b=_thrs(best_name),
            n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast="odst_minus_linear_specialist",
        )
        boot["teacher_guided_minus_task_odst"] = paired_user_cluster_mean_across_seeds(
            users, y_val, _logits(matched_task), _logits(best_name),
            frozen_thresholds_a=_thrs(matched_task), frozen_thresholds_b=_thrs(best_name),
            n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast="teacher_guided_minus_task_odst",
        )
        route_delta = None
        if len(promoted) == 2:
            a_n = promoted[0]["promoted_condition"]
            b_n = promoted[1]["promoted_condition"]
            off = a_n if not promoted[0]["route"] else b_n
            on = b_n if not promoted[0]["route"] else a_n
            boot["route_on_minus_route_off"] = paired_user_cluster_mean_across_seeds(
                users, y_val, _logits(off), _logits(on),
                frozen_thresholds_a=_thrs(off), frozen_thresholds_b=_thrs(on),
                n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast="route_on_minus_route_off",
            )
            route_delta = _mean(_prs(on)) - _mean(_prs(off))
        ci_l1 = boot["full_system_minus_L1"]["ci95_pr_auc"]
        ci_odst = boot["odst_minus_linear_specialist"]["ci95_pr_auc"]
        ci_teach = boot["teacher_guided_minus_task_odst"]["ci95_pr_auc"]
        ext_trig = bool(mean_l1 > 0 and pos_l1 >= 2)
        ext_odst_pos = None
        if ext_trig:
            family = best_promo["inner_condition"]
            spec = dict(SPECIALIST_CONDITIONS[family])
            spec["q"] = q
            encoder_trainable = bool(best_promo["spec"]["encoder_trainable"])
            start = SCREENING_SEED
            l1_s, l1_m, _ = load_l1_pair(start, device)
            cache_tr = _cache_l1(l1_s, l1_m, bundle["train"].X, bundle["train"].y, device)
            cache_va = _cache_l1(l1_s, l1_m, bundle["val"].X, bundle["val"].y, device)
            tau = freeze_thresholds(cache_tr["l1_logit"], seed=start, source="TRAIN")[q]
            g_tr = gate_indicator(cache_tr["l1_logit"], tau)
            g_va = gate_indicator(cache_va["l1_logit"], tau)
            for seed in EXTENDED_SEEDS:
                if encoder_trainable:
                    train_loader = _loader(
                        bundle["train"].X, bundle["train"].y, ens["train"]["ens_logit"],
                        cache_tr["l1_logit"], g_tr, seed=seed, shuffle=True, mask=g_tr.astype(bool),
                    )
                    val_loader = _loader(
                        bundle["val"].X, bundle["val"].y, ens["val"]["ens_logit"],
                        cache_va["l1_logit"], g_va, seed=seed, shuffle=False,
                    )
                else:
                    train_loader = _loader(
                        cache_tr["z"], bundle["train"].y, ens["train"]["ens_logit"],
                        cache_tr["l1_logit"], g_tr, seed=seed, shuffle=True, mask=g_tr.astype(bool),
                    )
                    val_loader = _loader(
                        cache_va["z"], bundle["val"].y, ens["val"]["ens_logit"],
                        cache_va["l1_logit"], g_va, seed=seed, shuffle=False,
                    )
                pack = train_specialist(
                    condition=best_name,
                    spec=spec,
                    seed=seed,
                    start_seed=start,
                    train_loader=train_loader,
                    select_loader=val_loader,
                    device=device,
                    pos_weight=pos_weight,
                    matched_teacher=teachers[start] if spec.get("route") and encoder_trainable else None,
                    select_name="validation",
                    encoder_trainable=encoder_trainable,
                    use_source_l1=not encoder_trainable,
                )
                l1_ref = float(packs[("L1", SCREENING_SEED)]["validation_PR_AUC"])
                lin_ref = float(packs[(matched_linear, SCREENING_SEED)]["validation_PR_AUC"])
                task_ref = float(packs[(matched_task, SCREENING_SEED)]["validation_PR_AUC"])
                stab_rows.append(
                    {
                        "seed": seed,
                        "system_PR_AUC": pack["validation_PR_AUC"],
                        "delta_vs_L1": float(pack["validation_PR_AUC"]) - l1_ref,
                        "delta_vs_linear_specialist": float(pack["validation_PR_AUC"]) - lin_ref,
                        "delta_teacher_guidance": float(pack["validation_PR_AUC"]) - task_ref,
                    }
                )
            primary_l1 = [d["delta_PR_AUC_vs_L1"] for d in deltas]
            primary_odst = [d["delta_PR_AUC_vs_linear_specialist"] for d in deltas]
            all_l1 = primary_l1 + [r["delta_vs_L1"] for r in stab_rows]
            all_odst = primary_odst + [r["delta_vs_linear_specialist"] for r in stab_rows]
            ext_pos = sum(1 for d in all_l1 if d > 0)
            ext_odst_pos = sum(1 for d in all_odst if d > 0)
            write_csv(
                _review("03_validation_confirmation", "EDITOR016_STABILITY_RESULTS.csv"),
                [{"seed": s, "delta_vs_L1": d} for s, d in zip(PRIMARY_SEEDS, primary_l1)] + stab_rows,
            )
        else:
            write_csv(_review("03_validation_confirmation", "EDITOR016_STABILITY_RESULTS.csv"), [])
        full_gate = classify_gate(mean_l1, pos_l1, ci_l1[0], ext_pos, ext_trig)
        odst_gate = classify_gate(mean_odst, pos_odst, ci_odst[0], ext_odst_pos, ext_trig)
        teacher_gate = classify_gate(mean_teach, pos_teach, ci_teach[0], None, False)
        comparisons.update(
            {
                "BEST_GATED_ODST_SYSTEM": best_name,
                "BEST_GATED_ODST_MEAN_PR_AUC": best_mean,
                "BEST_Q": q,
                "BEST_GATED_LINEAR_SPECIALIST_MEAN_PR_AUC": _mean(_prs(matched_linear)),
                "FULL_SYSTEM_DELTA_VS_L1": mean_l1,
                "ODST_SPECIALIST_DELTA_VS_LINEAR_SPECIALIST": mean_odst,
                "TEACHER_GUIDANCE_DELTA_WITHIN_ODST_SPECIALIST": mean_teach,
                "ROUTE_ANCHOR_DELTA": route_delta,
                "POSITIVE_SEEDS_FULL_SYSTEM_VS_L1": f"{pos_l1}/3",
                "POSITIVE_SEEDS_ODST_VS_LINEAR_SPECIALIST": f"{pos_odst}/3",
                "POSITIVE_SEEDS_TEACHER_GUIDANCE_EFFECT": f"{pos_teach}/3",
                "USER_CLUSTER_CI_FULL_SYSTEM_MINUS_L1": ci_l1,
                "USER_CLUSTER_CI_ODST_MINUS_LINEAR_SPECIALIST": ci_odst,
                "USER_CLUSTER_CI_TEACHER_GUIDANCE_EFFECT": ci_teach,
                "per_seed": deltas,
            }
        )
    else:
        write_csv(_review("03_validation_confirmation", "EDITOR016_STABILITY_RESULTS.csv"), [])
        comparisons.update(
            {
                "BEST_GATED_ODST_SYSTEM": "NONE",
                "BEST_GATED_ODST_MEAN_PR_AUC": None,
                "BEST_Q": None,
                "FULL_SYSTEM_DELTA_VS_L1": None,
            }
        )

    write_json(_review("03_validation_confirmation", "EDITOR016_PRIMARY_COMPARISONS.json"), comparisons)
    write_json(_review("04_statistics", "EDITOR016_CLUSTER_BOOTSTRAP.json"), boot)
    ruling = {
        "FULL_SYSTEM_SUPERIORITY": full_gate,
        "ODST_SPECIALIST_INCREMENTAL_VALUE": odst_gate,
        "TEACHER_GUIDANCE_SPECIALIST_EFFECT": teacher_gate,
        "EXTENDED_STABILITY_TRIGGERED": ext_trig,
        "EXTENDED_FULL_SYSTEM_POSITIVE_SEEDS": None if ext_pos is None else f"{ext_pos}/10",
    }
    write_json(_review("04_statistics", "EDITOR016_STABILITY_RULING.json"), ruling)
    return {
        "packs": packs,
        "comparisons": comparisons,
        "boot": boot,
        "best_name": best_name,
        "best_promo": best_promo,
        "ext_trig": ext_trig,
        "ext_pos": ext_pos,
        "stab_rows": stab_rows,
        "raw_store": raw_store,
        "full_gate": full_gate,
        "odst_gate": odst_gate,
        "teacher_gate": teacher_gate,
        "routed_rows": routed_rows,
    }


def run_mechanism_explain_efficiency(
    *,
    bundle: dict[str, Any],
    ens: dict[str, dict[str, np.ndarray]],
    teachers: dict[int, torch.nn.Module],
    confirm: dict[str, Any],
    device: torch.device,
) -> dict[str, Any]:
    y_val = np.asarray(bundle["val"].y)
    users = np.asarray(bundle["val"].user).astype(str)
    best = confirm["best_name"]
    if best == "NONE" or (best, SCREENING_SEED) not in confirm["packs"]:
        write_csv(_review("05_mechanism", "EDITOR016_RESIDUAL_TARGET_ANALYSIS.csv"), [])
        write_csv(_review("05_mechanism", "EDITOR016_ERROR_RESCUE.csv"), [])
        write_csv(_review("05_mechanism", "EDITOR016_ROUTE_FIDELITY.csv"), [])
        write_json(_review("05_mechanism", "EDITOR016_MECHANISM_RULING.json"), {"skipped": True})
        write_csv(_review("06_explainability", "EDITOR016_ROUTED_DIRECTIONAL_CONTRIBUTIONS.csv"), [])
        write_json(
            _review("06_explainability", "EDITOR016_ROUTED_DIRECTIONAL_FAITHFULNESS.json"),
            {
                "ROUTED_ODST_LOCAL_DIRECTIONAL_FAITHFULNESS": "NOT_SUPPORTED",
                "HISTORICAL_GLOBAL_TOPK_FAITHFULNESS": HISTORICAL_GLOBAL_TOPK_FAITHFULNESS,
                "ROUTE_TRACEABILITY": "SUPPORTED",
                "LEAF_TRACEABILITY": "SUPPORTED",
                "residual_promoted": False,
            },
        )
        write_json(_review("06_explainability", "EDITOR016_ROUTED_DIRECTIONAL_BOOTSTRAP.json"), {})
        eff = measure_cascade_efficiency(
            device, bundle["val"].X, specialist_ckpt=None, head="odst", coverage=0.0, gate=None
        )
        write_json(_review("07_efficiency", "EDITOR016_CASCADE_EFFICIENCY.json"), eff)
        return {"directional": {}, "mechanism": {"skipped": True}, "efficiency": eff}

    pack = confirm["packs"][(best, SCREENING_SEED)]
    student, modules = load_trained_specialist(pack["best_checkpoint"], device, head="odst")
    l1_s, l1_m, _ = load_l1_pair(SCREENING_SEED, device)
    cache_tr = _cache_l1(l1_s, l1_m, bundle["train"].X, bundle["train"].y, device)
    cache_va = _cache_l1(l1_s, l1_m, bundle["val"].X, bundle["val"].y, device)
    q = float(pack["q"])
    tau = freeze_thresholds(cache_tr["l1_logit"], seed=SCREENING_SEED, source="TRAIN")[q]
    g_tr = gate_indicator(cache_tr["l1_logit"], tau)
    g_va = gate_indicator(cache_va["l1_logit"], tau)
    train_loader = _loader(
        bundle["train"].X, bundle["train"].y, ens["train"]["ens_logit"], cache_tr["l1_logit"], g_tr,
        seed=0, shuffle=False,
    )
    val_loader = _loader(
        bundle["val"].X, bundle["val"].y, ens["val"]["ens_logit"], cache_va["l1_logit"], g_va,
        seed=0, shuffle=False,
    )
    tr = evaluate_specialist(student, modules, train_loader, device, from_z=False, use_source_l1=False)
    va = evaluate_specialist(student, modules, val_loader, device, from_z=False, use_source_l1=False)
    resid = np.asarray(va["deltas"])
    target = ens["val"]["ens_logit"] - cache_va["l1_logit"]
    g = np.asarray(va["gates"]).astype(bool)
    y = np.asarray(va["y"]).astype(int)
    rows = []
    for tag, mask in (
        ("all_routed", g),
        ("positive_routed", np.logical_and(g, y == 1)),
        ("negative_routed", np.logical_and(g, y == 0)),
    ):
        if int(mask.sum()) > 2:
            corr = float(np.corrcoef(resid[mask], target[mask])[0, 1])
        else:
            corr = float("nan")
        rows.append(
            {
                "subset": tag,
                "n": int(mask.sum()),
                "correlation": corr,
                "MAE_to_teacher_residual": float(np.mean(np.abs(resid[mask] - target[mask]))) if mask.any() else float("nan"),
                "correction_variance": float(np.var(resid[mask])) if mask.any() else float("nan"),
                "mean_absolute_correction": float(np.mean(np.abs(resid[mask]))) if mask.any() else float("nan"),
            }
        )
    write_csv(_review("05_mechanism", "EDITOR016_RESIDUAL_TARGET_ANALYSIS.csv"), rows)

    l1_thr = float(confirm["packs"][("L1", SCREENING_SEED)]["threshold"])
    res_thr = float(pack["threshold"])
    l1_logit = cache_va["l1_logit"]
    from editor012_rescue.metrics import sigmoid

    l1_pred = (sigmoid(l1_logit) >= l1_thr).astype(int)
    res_pred = (sigmoid(va["logits"]) >= res_thr).astype(int)
    rescue = []
    for tag, mask in (("malicious", np.logical_and(g, y == 1)), ("benign", np.logical_and(g, y == 0))):
        rescue.append(
            {
                "class": tag,
                "L1_wrong_ODST_correct": int(np.logical_and(l1_pred != y, res_pred == y)[mask].sum()),
                "L1_correct_ODST_wrong": int(np.logical_and(l1_pred == y, res_pred != y)[mask].sum()),
                "both_correct": int(np.logical_and(l1_pred == y, res_pred == y)[mask].sum()),
                "both_wrong": int(np.logical_and(l1_pred != y, res_pred != y)[mask].sum()),
            }
        )
    write_csv(_review("05_mechanism", "EDITOR016_ERROR_RESCUE.csv"), rescue)

    route_rec = {}
    if pack.get("route"):
        teacher = teachers[SCREENING_SEED]
        freeze_teacher(teacher)
        t_scored = score_ta2(teacher, make_xy_loader(bundle["val"].X, bundle["val"].y, seed=0, shuffle=False), device)
        rel = teacher_relative(
            va["logits"],
            t_scored["logits"],
            va["choices"],
            t_scored["choices"],
            va["leaf_probs_all"],
            t_scored["leaf_probs_all"],
        )
        route_rec = {
            "route_MAE": rel.get("route_MAE"),
            "route_KL": rel.get("route_KL"),
            "hard_route_agreement": rel.get("hard_route_agreement"),
            "dominant_leaf_agreement": rel.get("dominant_leaf_agreement"),
        }
        write_csv(_review("05_mechanism", "EDITOR016_ROUTE_FIDELITY.csv"), [route_rec])
    else:
        write_csv(_review("05_mechanism", "EDITOR016_ROUTE_FIDELITY.csv"), [])

    mech = {
        "ODST_CORRECTION_TEACHER_RESIDUAL_CORRELATION": rows[0]["correlation"],
        "L1_WRONG_ODST_CORRECT_POSITIVES": rescue[0]["L1_wrong_ODST_correct"],
        "L1_CORRECT_ODST_WRONG_POSITIVES": rescue[0]["L1_correct_ODST_wrong"],
        "ROUTE_FIDELITY_EFFECT": route_rec,
    }
    write_json(_review("05_mechanism", "EDITOR016_MECHANISM_RULING.json"), mech)

    refs = train_references(tr["tree_outputs"])
    faith = routed_directional_table(
        y=y_val,
        tree_outputs=va["tree_outputs"],
        references=refs,
        linear_logit=va["linear_logits"],
        reference_tree_outputs=None,
        users=users,
        gate=g,
    )
    write_csv(_review("06_explainability", "EDITOR016_ROUTED_DIRECTIONAL_CONTRIBUTIONS.csv"), faith.get("contributions", []))
    write_json(
        _review("06_explainability", "EDITOR016_ROUTED_DIRECTIONAL_FAITHFULNESS.json"),
        {k: faith[k] for k in faith if k not in {"contributions", "bootstrap"}},
    )
    write_json(_review("06_explainability", "EDITOR016_ROUTED_DIRECTIONAL_BOOTSTRAP.json"), faith.get("bootstrap", {}))

    coverage = float(g.mean())
    eff = measure_cascade_efficiency(
        device,
        bundle["val"].X,
        specialist_ckpt=pack["best_checkpoint"],
        head="odst",
        coverage=coverage,
        gate=g,
    )
    write_json(_review("07_efficiency", "EDITOR016_CASCADE_EFFICIENCY.json"), eff)
    return {"directional": faith, "mechanism": mech, "efficiency": eff, "coverage": coverage}


def write_editor_response(
    *,
    identities: dict[str, Any],
    inner: dict[str, Any],
    confirm: dict[str, Any],
    mech: dict[str, Any],
    commits: dict[str, str],
) -> dict[str, Any]:
    full = confirm["full_gate"]
    odst = confirm["odst_gate"]
    teach = confirm["teacher_gate"]
    faith = mech.get("directional", {})
    local = faith.get("ROUTED_ODST_LOCAL_DIRECTIONAL_FAITHFULNESS", "NOT_SUPPORTED")
    odst_ok = odst in {"STRONG", "CONSISTENT"}
    full_ok = full in {"STRONG", "CONSISTENT", "STABILITY_ONLY"}
    if odst_ok and full_ok:
        issue = "RESOLVED"
    elif odst != "NOT_SUPPORTED" or full != "NOT_SUPPORTED":
        issue = "PARTIALLY_RESOLVED"
    else:
        issue = "NOT_RESOLVED"

    inner_by = {r["condition"]: r for r in inner["rows"]}
    l1_pr = float(inner_by["L1"]["select_PR_AUC"])
    best_lin = None
    best_lin_pr = -1.0
    best_od = None
    best_od_pr = -1.0
    for r in inner["rows"]:
        cond = str(r.get("condition", ""))
        family = str(r.get("family") or (cond.split("@", 1)[0] if cond.startswith("S") else ""))
        pr = r.get("select_PR_AUC")
        if pr in {None, "", "nan", "None"}:
            continue
        pr = float(pr)
        if family in {"S0", "S1"} and pr > best_lin_pr:
            best_lin = cond
            best_lin_pr = pr
        if family in {"S2", "S3", "S4"} and pr > best_od_pr:
            best_od = cond
            best_od_pr = pr

    why_teacher = (
        "Equal-weight ensemble residual guidance remains the supported teacher mechanism; "
        "EDITOR-016 tests whether that signal improves an uncertainty-routed ODST specialist."
    )
    if odst_ok:
        why_odst = (
            "A teacher-guided ODST specialist improved ranking over a matched teacher-guided "
            "linear specialist on source-frozen uncertain sequences."
        )
        paper_model = confirm["comparisons"].get("BEST_GATED_ODST_SYSTEM", "TA2")
    else:
        why_odst = (
            "The uncertainty-routed ODST specialist did not establish incremental ranking value "
            "over a matched linear specialist on source-frozen uncertain sequences."
        )
        paper_model = "TA2"
    if issue == "RESOLVED":
        next_action = "Promote the gated teacher-guided ODST cascade into the paper-facing comparison table."
    elif issue == "PARTIALLY_RESOLVED":
        next_action = "Report qualified specialist evidence; keep TA2 as BEST_CURRENT_PAPER_MODEL unless full-system superiority is STRONG."
    else:
        next_action = "Keep TA2 as BEST_CURRENT_PAPER_MODEL. Do not launch another generic ODST search."

    ruling = {
        "FULL_SYSTEM_SUPERIORITY": full,
        "ODST_SPECIALIST_INCREMENTAL_VALUE": odst,
        "TEACHER_GUIDANCE_SPECIALIST_EFFECT": teach,
        "ROUTED_ODST_LOCAL_DIRECTIONAL_FAITHFULNESS": local,
        "HISTORICAL_GLOBAL_TOPK_FAITHFULNESS": HISTORICAL_GLOBAL_TOPK_FAITHFULNESS,
        "ROUTE_TRACEABILITY": "SUPPORTED",
        "LEAF_TRACEABILITY": "SUPPORTED",
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "EDITOR_ISSUE_TEACHER_INITIALISATION_ONLY": "RESOLVED",
        "EDITOR_ISSUE_C5_NEGLIGIBLE_INCREMENT": "RESOLVED_BY_TA2",
        "EDITOR_ISSUE_ODST_VALUE": issue,
        "BEST_CURRENT_PAPER_MODEL": paper_model if full == "STRONG" else BEST_CURRENT_PAPER_MODEL,
        "WHY_TEACHER_GUIDANCE": why_teacher,
        "WHY_ODST": why_odst,
        "NEXT_RECOMMENDED_ACTION": next_action,
        "mechanism": mech.get("mechanism", {}),
        "commits": commits,
        "INNER_L1_PR_AUC": l1_pr,
        "BEST_LINEAR_SPECIALIST": best_lin,
        "BEST_LINEAR_SPECIALIST_PR_AUC": best_lin_pr if best_lin else None,
        "BEST_ODST_SPECIALIST": best_od,
        "BEST_ODST_SPECIALIST_PR_AUC": best_od_pr if best_od else None,
    }
    write_json(_review("08_editor_response", "EDITOR016_ODST_SUPERIORITY_RULING.json"), ruling)
    matrix = [
        {"issue": "TEACHER_GUIDANCE_VS_INITIALISATION", "status": "SUPPORTED_STRONG", "resolution": "RESOLVED"},
        {"issue": "EDITOR_ISSUE_TEACHER_INITIALISATION_ONLY", "status": "RESOLVED", "resolution": "RESOLVED"},
        {"issue": "EDITOR_ISSUE_C5_NEGLIGIBLE_INCREMENT", "status": "RESOLVED_BY_TA2", "resolution": "RESOLVED_BY_TA2"},
        {"issue": "POST_ATTENTION_ODST_INCREMENTAL_VALUE", "status": POST_ATTENTION_ODST_INCREMENTAL_VALUE, "resolution": "frozen"},
        {"issue": "TEMPORAL_ODST_INCREMENTAL_VALUE", "status": TEMPORAL_ODST_INCREMENTAL_VALUE, "resolution": "frozen"},
        {"issue": "RESIDUAL_ODST_VALUE", "status": RESIDUAL_ODST_VALUE, "resolution": "frozen"},
        {"issue": "FIXED_LINEAR_ODST_COMPLEMENTARITY", "status": FIXED_LINEAR_ODST_COMPLEMENTARITY, "resolution": "frozen"},
        {"issue": "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS", "status": LOCAL_DIRECTIONAL_TREE_FAITHFULNESS, "resolution": "frozen_global_TA2"},
        {"issue": "ROUTED_ODST_LOCAL_DIRECTIONAL_FAITHFULNESS", "status": local, "resolution": local},
        {"issue": "FULL_SYSTEM_SUPERIORITY", "status": full, "resolution": full},
        {"issue": "ODST_SPECIALIST_INCREMENTAL_VALUE", "status": odst, "resolution": odst},
        {"issue": "TEACHER_GUIDANCE_SPECIALIST_EFFECT", "status": teach, "resolution": teach},
        {"issue": "EDITOR_ISSUE_ODST_VALUE", "status": issue, "resolution": issue},
    ]
    write_csv(_review("08_editor_response", "EDITOR016_EDITOR_ISSUE_MATRIX.csv"), matrix)
    gate = {
        "paper_rescue_ready": issue == "RESOLVED",
        "BEST_CURRENT_PAPER_MODEL": ruling["BEST_CURRENT_PAPER_MODEL"],
        "FULL_SYSTEM_SUPERIORITY": full,
        "ODST_SPECIALIST_INCREMENTAL_VALUE": odst,
        "EDITOR_ISSUE_ODST_VALUE": issue,
        "do_not_overwrite_global_topk_faithfulness": True,
    }
    write_json(_review("09_paper_handover", "EDITOR016_PAPER_RESCUE_GATE.json"), gate)
    md = [
        "# EDITOR-016 paper rescue handover",
        "",
        f"Full-system superiority: **{full}**",
        f"ODST specialist incremental value: **{odst}**",
        f"Teacher-guidance specialist effect: **{teach}**",
        f"Routed local directional faithfulness: **{local}**",
        f"Historical global top-k faithfulness: **{HISTORICAL_GLOBAL_TOPK_FAITHFULNESS}** (frozen)",
        f"Best current paper model: **{ruling['BEST_CURRENT_PAPER_MODEL']}**",
        "",
        f"Why teacher guidance: {why_teacher}",
        "",
        f"Why ODST: {why_odst}",
        "",
        f"Next recommended action: {next_action}",
        "",
        "Do not convert routed directional faithfulness into a global PR-AUC faithfulness claim.",
    ]
    path = _review("09_paper_handover", "EDITOR016_PAPER_RESCUE_HANDOVER.md")
    refuse_historical_write(path)
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return {
        "ruling": ruling,
        "paper_model": ruling["BEST_CURRENT_PAPER_MODEL"],
        "odst_issue": issue,
        "why_teacher": why_teacher,
        "why_odst": why_odst,
        "next_action": next_action,
        "inner_l1": l1_pr,
        "best_linear": best_lin,
        "best_linear_pr": best_lin_pr,
        "best_odst": best_od,
        "best_odst_pr": best_od_pr,
    }


def _load_inner_from_disk() -> dict[str, Any]:
    import csv
    import json

    promo_path = _review("02_inner_specialist", "EDITOR016_PROMOTION_FREEZE.json")
    decision = json.loads(promo_path.read_text(encoding="utf-8"))
    inner_csv = _review("02_inner_specialist", "EDITOR016_INNER_SPECIALIST_RESULTS.csv")
    rows = []
    if inner_csv.is_file():
        with inner_csv.open(encoding="utf-8") as handle:
            for rec in csv.DictReader(handle):
                if rec.get("select_PR_AUC") not in {"", "nan", "None"}:
                    rec["select_PR_AUC"] = float(rec["select_PR_AUC"])
                if rec.get("select_F1") not in {"", "nan", "None"}:
                    rec["select_F1"] = float(rec["select_F1"])
                rec["executed"] = str(rec.get("executed", "True")).lower() == "true"
                if rec.get("q") not in {"", "nan", "None"}:
                    rec["q"] = float(rec["q"])
                rows.append(rec)
    mark_promotion_frozen()
    return {"rows": rows, "packs": {}, "decision": decision, "e2e_rows": []}


def run_campaign(*, resume_after_inner: bool = False) -> dict[str, Any]:
    protocol = write_protocol_packet()
    identities = verify_identities()
    device = _device()
    print(f"[EDITOR-016] device={device}", flush=True)
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    ens = load_ensemble_cache()
    teachers = {}
    for seed in PRIMARY_SEEDS:
        model, _ = load_topt(seed, device)
        freeze_teacher(model)
        teachers[seed] = model
    pos_weight = float(bundle["pos_weight"])
    promo_path = _review("02_inner_specialist", "EDITOR016_PROMOTION_FREEZE.json")
    if resume_after_inner and promo_path.is_file():
        inner = _load_inner_from_disk()
    else:
        inner = run_inner_specialist(
            bundle=bundle, teachers=teachers, ens=ens, device=device, pos_weight=pos_weight
        )
    confirm = run_confirmation(
        bundle=bundle, teachers=teachers, ens=ens, device=device, pos_weight=pos_weight, inner=inner
    )
    mech = run_mechanism_explain_efficiency(
        bundle=bundle, ens=ens, teachers=teachers, confirm=confirm, device=device
    )
    commits = {
        "EDITOR016_PROTOCOL_COMMIT": "PENDING_016A",
        "EDITOR016_IMPLEMENTATION_COMMIT": "PENDING_016A",
        "EDITOR016_PROMOTION_COMMIT": "PENDING_016B",
        "EDITOR016_RESULTS_COMMIT": "PENDING_016C",
    }
    synth = write_editor_response(
        identities=identities, inner=inner, confirm=confirm, mech=mech, commits=commits
    )
    manifest = {
        "task_id": "EDITOR-016",
        "created_utc": utc_now(),
        "device": str(device),
        "promoted": inner["decision"]["promoted"],
        "architecture": ENCODER_ARCH,
        "EDITOR015_RESULTS_FULL_COMMIT": EDITOR015_RESULTS_FULL_COMMIT,
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
        "r52_test_accessed": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "identities": identities,
        "comparisons": confirm["comparisons"],
        "FULL_SYSTEM_SUPERIORITY": confirm["full_gate"],
        "ODST_SPECIALIST_INCREMENTAL_VALUE": confirm["odst_gate"],
        "TEACHER_GUIDANCE_SPECIALIST_EFFECT": confirm["teacher_gate"],
        "EDITOR_ISSUE_ODST_VALUE": synth["odst_issue"],
        "user_mapping": mapping["mapping_sha256"],
    }
    write_json(_review("EDITOR016_RUN_MANIFEST.json"), manifest)
    return {
        "identities": identities,
        "protocol": protocol,
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
    inner = run_inner_specialist(
        bundle=bundle, teachers=teachers, ens=ens, device=device, pos_weight=float(bundle["pos_weight"])
    )
    return {"protocol": protocol, "identities": identities, "inner": inner}


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
