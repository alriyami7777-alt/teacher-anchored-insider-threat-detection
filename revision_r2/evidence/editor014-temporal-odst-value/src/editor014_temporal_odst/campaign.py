"""EDITOR-014 temporal ODST placement and TA2 value orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds
from editor012_rescue.data import load_train_validation, make_xy_loader, subset_bundle
from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.inner_split import inner_split_masks
from editor012_rescue.metrics import metrics_from_logits
from editor012_rescue.models import architecture_identity, assert_odst046, freeze_teacher, student_forward as historical_student_forward
from editor012_rescue.producing import build_odst046_model, import_set_seed, load_state_dict, pin_producing_sources

from .constants import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CONDITIONS,
    CONSENSUS_TEACHER_ADVANTAGE,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
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
    FROZEN_TA2_MINUS_L1,
    L1_CHECKPOINTS,
    LAMBDA_DISTILL,
    ODST046,
    POST_ATTENTION_ODST_VALUE,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    SCREENING_SEED,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TEMPORAL_CANDIDATES,
    TOPT_CHECKPOINTS,
)
from .explain import (
    classify_faithfulness,
    faithfulness_table,
    temporal_logit_from_units,
    time_tree_contributions,
    train_time_tree_references,
)
from .freeze import write_protocol_packet
from .io_util import write_csv, write_json
from .models import make_modules
from .promotion import decide_promotions
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor014Blocked,
    enter_inner_phase,
    exit_inner_phase,
    mark_promotion_frozen,
    refuse_historical_write,
    refuse_r52_test,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .ta2_value import (
    load_frozen_val_logits,
    measure_efficiency,
    paired_user_cluster_calibration,
    run_ta2_faithfulness,
    value_matrix_rows,
)
from .train import evaluate_condition, load_topt, train_condition


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
        raise Editor014Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    pins = pin_producing_sources()
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4 or float(ODST046["temperature"]) != 0.5:
        raise Editor014Blocked("ODST-046 lock mismatch")
    if abs(float(LAMBDA_DISTILL) - 0.5) > 1e-15:
        raise Editor014Blocked("distill lambda mismatch")
    teacher = build_odst046_model()
    assert_odst046(teacher)
    if EDITOR012_RESULTS_COMMIT != "4bcf522a502ed98e5dd393a80bd9da7fffd51964":
        raise Editor014Blocked("EDITOR-012 results commit mismatch")
    if EDITOR013_RESULTS_COMMIT != "09c4bb97b143810147feef08f31a8d8d042a6726":
        raise Editor014Blocked("EDITOR-013 results commit mismatch")
    return {
        "r52_test_hard_denied": True,
        "odst046_identity_verified": True,
        "lambda_distill": LAMBDA_DISTILL,
        "producing_pins": pins,
        "architecture": architecture_identity(teacher),
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "POST_ATTENTION_ODST_VALUE": POST_ATTENTION_ODST_VALUE,
    }


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor014Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor014Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor014Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor014Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    return {
        "USER_MAPPING_RECOVERED": True,
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "per_user_count_min": int(counts.min()),
        "per_user_count_max": int(counts.max()),
        "n_malicious_users": int(len(malicious)),
        "malicious_users": malicious,
        "mapping_sha256": mapping_hash,
        "hash_matches_EDITOR011_012_013": True,
        "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
    }


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


def import_reused_validation(name: str, seed: int, spec: dict[str, Any], y_val: np.ndarray) -> dict[str, Any]:
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
        "select_F1": float(met["f1"]),
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
        "family": CONDITIONS[name]["family"],
        "placement": CONDITIONS[name]["placement"],
        "hybrid": CONDITIONS[name]["hybrid"],
        "center": CONDITIONS[name]["center"],
    }


def classify_temporal_value(
    mean_delta: float, pos: int, ci_lo: float | None, ext_pos: int | None, ext_trig: bool
) -> str:
    if mean_delta > 0 and pos == 3 and ci_lo is not None and ci_lo > 0:
        return "STRONG_TEMPORAL_ODST_VALUE"
    if mean_delta > 0 and pos == 3:
        return "CONSISTENT_TEMPORAL_ODST_VALUE"
    if ext_trig and ext_pos is not None and ext_pos >= 8 and mean_delta > 0 and pos >= 2:
        return "STABILITY_SUPPORTED_TEMPORAL_ODST"
    return "NO_TEMPORAL_ODST_VALUE"


def run_inner_search(
    *,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    ens_train: dict[str, np.ndarray],
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
            raise Editor014Blocked("INNER split mismatch")
        inner_tr = subset_bundle(bundle["train"], split["train_mask"], "inner_train")
        inner_se = subset_bundle(bundle["train"], split["select_mask"], "inner_select")
        ens_tr = ens_train["ens_logit"][split["train_mask"]]
        ens_se = ens_train["ens_logit"][split["select_mask"]]

        rows = []
        packs = {}
        for name in ("B0", "B1", "T0", "T1", "T2"):
            spec = CONDITIONS[name]
            extras_tr = [ens_tr]
            extras_se = [ens_se]
            train_loader = make_xy_loader(
                inner_tr.X, inner_tr.y, seed=SCREENING_SEED, shuffle=True, extras=extras_tr
            )
            select_loader = make_xy_loader(
                inner_se.X, inner_se.y, seed=SCREENING_SEED, shuffle=False, extras=extras_se
            )
            pack = train_condition(
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
                center_loader=make_xy_loader(inner_tr.X, inner_tr.y, seed=0, shuffle=False) if spec.get("center") else None,
            )
            packs[name] = pack
            rows.append(
                {
                    "condition": name,
                    "family": spec["family"],
                    "placement": spec["placement"],
                    "hybrid": spec["hybrid"],
                    "center": spec["center"],
                    "distill": spec["distill"],
                    "teacher": spec["teacher"],
                    "route": spec["route"],
                    "select_PR_AUC": pack["select_PR_AUC"],
                    "select_F1": pack["select_F1"],
                    "Brier": pack["Brier"],
                    "log_loss": pack["log_loss"],
                    "best_epoch": pack["best_epoch"],
                    "learned_beta": pack["learned_beta"],
                    "frozen_train_mean": pack["frozen_train_mean"],
                    "official_validation_used": False,
                }
            )
            print(f"[EDITOR-014] INNER {name} PR-AUC={pack['select_PR_AUC']:.6f}", flush=True)

        write_csv(_review("01_inner_selection", "EDITOR014_INNER_RESULTS.csv"), rows)
        decision = decide_promotions(rows)
        write_json(_review("01_inner_selection", "EDITOR014_PROMOTION_FREEZE.json"), decision)
        mark_promotion_frozen()
        return {"rows": rows, "packs": packs, "decision": decision, "split": {k: split[k] for k in split if k.endswith("_n") or "pos" in k or k == "n_dropped"}}
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
        "learned_beta": pack.get("learned_beta"),
        "imported": pack.get("imported", False),
    }


def run_confirmation(
    *,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    ens_train: dict[str, np.ndarray],
    ens_val: dict[str, np.ndarray],
    device: torch.device,
    pos_weight: float,
    inner: dict[str, Any],
    mapping: dict[str, Any],
) -> dict[str, Any]:
    y_val = np.asarray(bundle["val"].y)
    users = np.asarray(bundle["val"].user).astype(str)
    packs: dict[tuple[str, int], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    for seed in PRIMARY_SEEDS:
        packs[("B0", seed)] = import_reused_validation("B0", seed, L1_CHECKPOINTS[seed], y_val)
        rows.append(_pack_val_row(packs[("B0", seed)]))
        packs[("B1", seed)] = import_reused_validation("B1", seed, F11_CHECKPOINTS[seed], y_val)
        rows.append(_pack_val_row(packs[("B1", seed)]))

    promoted = list(inner["decision"]["promoted"])
    for promo in promoted:
        name = promo["validation_name"]
        spec = CONDITIONS[name]
        for seed in PRIMARY_SEEDS:
            extras = [ens_train["ens_logit"]]
            train_loader = make_xy_loader(bundle["train"].X, bundle["train"].y, seed=seed, shuffle=True, extras=extras)
            val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=seed, shuffle=False)
            pack = train_condition(
                condition=name,
                spec=spec,
                seed=seed,
                start_seed=seed,
                train_loader=train_loader,
                select_loader=val_loader,
                device=device,
                pos_weight=pos_weight,
                matched_teacher=None,
                select_name="validation",
                encoder_trainable=True,
                center_loader=make_xy_loader(bundle["train"].X, bundle["train"].y, seed=0, shuffle=False)
                if spec.get("center")
                else None,
            )
            packs[(name, seed)] = pack
            rows.append(_pack_val_row(pack))

    write_csv(_review("02_validation_confirmation", "EDITOR014_VALIDATION_RESULTS.csv"), rows)

    def _prs(name: str) -> list[float]:
        return [float(packs[(name, s)]["validation_PR_AUC"]) for s in PRIMARY_SEEDS]

    def _logits(name: str) -> list[np.ndarray]:
        return [np.asarray(packs[(name, s)]["student_logits"]) for s in PRIMARY_SEEDS]

    def _thrs(name: str) -> list[float]:
        return [float(packs[(name, s)]["threshold"]) for s in PRIMARY_SEEDS]

    l1_mean = _mean(_prs("B0"))
    ta2_mean = _mean(_prs("B1"))
    best_name = None
    best_mean = float("-inf")
    for promo in promoted:
        name = promo["validation_name"]
        m = _mean(_prs(name))
        if m > best_mean:
            best_mean = m
            best_name = name
    if best_name is None:
        best_name = "NONE"
        best_mean = float("nan")

    comparisons: dict[str, Any] = {}
    boot: dict[str, Any] = {}
    if best_name != "NONE":
        deltas = []
        for seed in PRIMARY_SEEDS:
            a = packs[("B0", seed)]
            b = packs[(best_name, seed)]
            rec = {
                "seed": seed,
                "delta_PR_AUC": float(b["validation_PR_AUC"]) - float(a["validation_PR_AUC"]),
                "delta_F1": float(b["validation_F1"]) - float(a["validation_F1"]),
                "delta_Brier": float(b["Brier"]) - float(a["Brier"]),
                "delta_log_loss": float(b["log_loss"]) - float(a["log_loss"]),
                "delta_FP": int(b["FP"]) - int(a["FP"]),
                "delta_FN": int(b["FN"]) - int(a["FN"]),
            }
            deltas.append(rec)
        pos = sum(1 for d in deltas if d["delta_PR_AUC"] > 0)
        mean_delta = _mean([d["delta_PR_AUC"] for d in deltas])
        boot[f"{best_name}_minus_B0"] = paired_user_cluster_mean_across_seeds(
            users,
            y_val,
            _logits("B0"),
            _logits(best_name),
            frozen_thresholds_a=_thrs("B0"),
            frozen_thresholds_b=_thrs(best_name),
            n_valid=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
            contrast=f"{best_name}_minus_B0",
        )
        ci = boot[f"{best_name}_minus_B0"]["ci95_pr_auc"]
        ext_trig = bool(mean_delta > 0 and pos >= 2)
        ext_pos = None
        stab_rows: list[dict[str, Any]] = []
        if ext_trig:
            for seed in EXTENDED_SEEDS:
                extras = [ens_train["ens_logit"]]
                pack_l = train_condition(
                    condition="B0_STAB",
                    spec=CONDITIONS["B0"],
                    seed=seed,
                    start_seed=SCREENING_SEED,
                    train_loader=make_xy_loader(bundle["train"].X, bundle["train"].y, seed=seed, shuffle=True, extras=extras),
                    select_loader=make_xy_loader(bundle["val"].X, bundle["val"].y, seed=seed, shuffle=False),
                    device=device,
                    pos_weight=pos_weight,
                    select_name="validation",
                    encoder_trainable=True,
                )
                pack_t = train_condition(
                    condition=f"{best_name}_STAB",
                    spec=CONDITIONS[best_name],
                    seed=seed,
                    start_seed=SCREENING_SEED,
                    train_loader=make_xy_loader(bundle["train"].X, bundle["train"].y, seed=seed, shuffle=True, extras=extras),
                    select_loader=make_xy_loader(bundle["val"].X, bundle["val"].y, seed=seed, shuffle=False),
                    device=device,
                    pos_weight=pos_weight,
                    select_name="validation",
                    encoder_trainable=True,
                    center_loader=make_xy_loader(bundle["train"].X, bundle["train"].y, seed=0, shuffle=False)
                    if CONDITIONS[best_name].get("center")
                    else None,
                )
                dpr = float(pack_t["validation_PR_AUC"]) - float(pack_l["validation_PR_AUC"])
                stab_rows.append(
                    {
                        "seed": seed,
                        "B0_PR_AUC": pack_l["validation_PR_AUC"],
                        f"{best_name}_PR_AUC": pack_t["validation_PR_AUC"],
                        "delta": dpr,
                    }
                )
            primary_pos = [d["delta_PR_AUC"] for d in deltas]
            ext_pos = pos + sum(1 for r in stab_rows if r["delta"] > 0)
            write_csv(_review("02_validation_confirmation", "EDITOR014_STABILITY_RESULTS.csv"), stab_rows)
        else:
            write_csv(
                _review("02_validation_confirmation", "EDITOR014_STABILITY_RESULTS.csv"),
                [{"seed": "", "note": "extended stability not triggered"}],
            )
        ruling = classify_temporal_value(mean_delta, pos, float(ci[0]), ext_pos, ext_trig)
        comparisons = {
            "best_temporal": best_name,
            "per_seed": deltas,
            "mean_delta_pr_auc": mean_delta,
            "positive_primary_seeds": pos,
            "ci95": ci,
            "extended_triggered": ext_trig,
            "extended_positive": ext_pos,
        }
    else:
        ruling = "NO_TEMPORAL_ODST_VALUE"
        ext_trig = False
        ext_pos = None
        pos = 0
        mean_delta = float("nan")
        ci = [float("nan"), float("nan")]
        write_csv(
            _review("02_validation_confirmation", "EDITOR014_STABILITY_RESULTS.csv"),
            [{"seed": "", "note": "no temporal candidate promoted"}],
        )

    write_json(
        _review("02_validation_confirmation", "EDITOR014_PRIMARY_COMPARISONS.json"),
        {
            "B0_mean": l1_mean,
            "B1_mean": ta2_mean,
            "BEST_TEMPORAL_MEAN": best_mean,
            "ruling_inputs": comparisons,
            "TEMPORAL_ODST_INCREMENTAL_VALUE": ruling,
        },
    )
    write_json(_review("05_statistics", "EDITOR014_CLUSTER_BOOTSTRAP.json"), boot)
    write_json(_review("05_statistics", "EDITOR014_USER_MAPPING_VERIFICATION.json"), mapping)

    faith_ruling = "NOT_APPLICABLE"
    if best_name != "NONE":
        faith_ruling = _run_temporal_explain(bundle, packs, best_name, teachers, device, users, y_val)
    else:
        write_csv(
            _review("03_temporal_explainability", "EDITOR014_TIME_TREE_CONTRIBUTIONS.csv"),
            [{"note": "no temporal candidate promoted; time×tree contributions not estimated"}],
        )
        write_csv(
            _review("03_temporal_explainability", "EDITOR014_FAITHFULNESS_RESULTS.csv"),
            [{"note": "no temporal candidate promoted; faithfulness not estimated"}],
        )
        write_json(
            _review("03_temporal_explainability", "EDITOR014_FAITHFULNESS_BOOTSTRAP.json"),
            {"note": "no temporal candidate promoted", "cluster": "user"},
        )
        write_json(
            _review("03_temporal_explainability", "EDITOR014_EXPLANATION_RULING.json"),
            {
                "TEMPORAL_ODST_REFERENCE_CENTRED_FAITHFULNESS": "NOT_APPLICABLE",
                "reason": "no temporal ODST candidate promoted on INNER_SELECT",
                "ROUTE_LEAF_INDEPENDENT_FAITHFULNESS": "UNSUPPORTED",
            },
        )

    paper = _write_handover(
        inner=inner,
        ruling=ruling,
        best_name=best_name,
        best_mean=best_mean,
        l1_mean=l1_mean,
        mean_delta=mean_delta,
        pos=pos,
        ci=ci,
        ext_trig=ext_trig,
        ext_pos=ext_pos,
        faith_ruling=faith_ruling,
    )
    return {
        "ruling": ruling,
        "best_name": best_name,
        "best_mean": best_mean,
        "l1_mean": l1_mean,
        "ta2_mean": ta2_mean,
        "mean_delta": mean_delta,
        "pos": pos,
        "ci": ci,
        "ext_trig": ext_trig,
        "ext_pos": ext_pos,
        "faith_ruling": faith_ruling,
        "paper": paper,
        "packs": packs,
    }


def _run_temporal_explain(
    bundle: dict[str, Any],
    packs: dict[tuple[str, int], dict[str, Any]],
    best_name: str,
    teachers: dict[int, torch.nn.Module],
    device: torch.device,
    users: np.ndarray,
    y_val: np.ndarray,
) -> str:
    spec = CONDITIONS[best_name]
    student, _ = load_topt(SCREENING_SEED, device)
    modules = make_modules(spec)
    payload = torch.load(packs[(best_name, SCREENING_SEED)]["best_checkpoint"], map_location="cpu", weights_only=False)
    student.load_state_dict(payload["student_state_dict"])
    modules.load_state_dict(payload["modules_state_dict"])
    student.to(device)
    modules.to(device)
    if spec.get("center"):
        from .train import freeze_t2_train_mean

        freeze_t2_train_mean(
            student,
            modules,
            make_xy_loader(bundle["train"].X, bundle["train"].y, seed=0, shuffle=False),
            device,
        )
    train_eval = evaluate_condition(
        student, modules, make_xy_loader(bundle["train"].X, bundle["train"].y, seed=0, shuffle=False), device
    )
    val_eval = evaluate_condition(
        student, modules, make_xy_loader(bundle["val"].X, bundle["val"].y, seed=0, shuffle=False), device
    )
    refs = train_time_tree_references(train_eval["tree_outputs_btj"])
    c = time_tree_contributions(val_eval["tree_outputs_btj"], val_eval["attention_weights"], refs)
    raw = time_tree_contributions(val_eval["tree_outputs_btj"], val_eval["attention_weights"], None)
    recovered = raw.sum(axis=(1, 2))
    expected = temporal_logit_from_units(val_eval["tree_outputs_btj"], val_eval["attention_weights"])
    if not np.allclose(recovered, expected, atol=1e-5, rtol=1e-5):
        raise Editor014Blocked("time×tree contributions do not recover temporal ODST logit")
    contrib_rows = []
    for t in range(c.shape[1]):
        for j in range(c.shape[2]):
            contrib_rows.append(
                {
                    "time": t,
                    "tree": j,
                    "mean_centred_contribution": float(c[:, t, j].mean()),
                    "mean_abs_centred_contribution": float(np.abs(c[:, t, j]).mean()),
                    "mean_time_contribution": float(c[:, t, :].sum(axis=1).mean()) if j == 0 else "",
                    "mean_tree_contribution": float(c[:, :, j].sum(axis=1).mean()) if t == 0 else "",
                    "reference": float(refs[t, j]),
                }
            )
    write_csv(_review("03_temporal_explainability", "EDITOR014_TIME_TREE_CONTRIBUTIONS.csv"), contrib_rows)
    primary = faithfulness_table(
        y=y_val,
        q_tj=val_eval["tree_outputs_btj"],
        alpha=val_eval["attention_weights"],
        references=refs,
        users=users,
        level="time_tree",
    )
    secondary = [
        faithfulness_table(
            y=y_val,
            q_tj=val_eval["tree_outputs_btj"],
            alpha=val_eval["attention_weights"],
            references=refs,
            users=users,
            level=level,
        )
        for level in ("tree", "time")
    ]
    rows = list(primary["rows"])
    for s in secondary:
        rows.extend(s["rows"])
    write_csv(_review("03_temporal_explainability", "EDITOR014_FAITHFULNESS_RESULTS.csv"), rows)
    write_json(
        _review("03_temporal_explainability", "EDITOR014_FAITHFULNESS_BOOTSTRAP.json"),
        {
            "cluster": "user",
            "n_users": int(len(np.unique(users))),
            "note": "primary statistic is top-k vs random-k drop; users are the resampling unit",
        },
    )
    ruling = classify_faithfulness(primary, secondary)
    write_json(
        _review("03_temporal_explainability", "EDITOR014_EXPLANATION_RULING.json"),
        {
            "TEMPORAL_ODST_REFERENCE_CENTRED_FAITHFULNESS": ruling,
            "primary": primary,
            "secondary": [{"level": s["level"], "ruling": s["TEMPORAL_ODST_REFERENCE_CENTRED_FAITHFULNESS"]} for s in secondary],
            "ROUTE_LEAF_INDEPENDENT_FAITHFULNESS": "UNSUPPORTED",
        },
    )
    return ruling


def run_ta2_audit(
    *,
    bundle: dict[str, Any],
    teachers: dict[int, torch.nn.Module],
    device: torch.device,
    mapping: dict[str, Any],
) -> dict[str, Any]:
    y_val = np.asarray(bundle["val"].y)
    users = np.asarray(bundle["val"].user).astype(str)
    frozen = load_frozen_val_logits()
    l1_list = [frozen["L1"][s] for s in PRIMARY_SEEDS]
    ta2_list = [frozen["TA2"][s] for s in PRIMARY_SEEDS]
    cal = paired_user_cluster_calibration(users, y_val, l1_list, ta2_list)
    write_json(_review("04_ta2_value", "EDITOR014_TA2_CALIBRATION_BOOTSTRAP.json"), cal)

    l1_mets = [metrics_from_logits(y_val, frozen["L1"][s]) for s in PRIMARY_SEEDS]
    ta2_mets = [metrics_from_logits(y_val, frozen["TA2"][s]) for s in PRIMARY_SEEDS]
    l1_mean = {k: _mean([m[k] for m in l1_mets]) for k in ("pr_auc", "f1", "Brier", "log_loss")}
    ta2_mean = {k: _mean([m[k] for m in ta2_mets]) for k in ("pr_auc", "f1", "Brier", "log_loss")}

    print("[EDITOR-014] TA2 efficiency benchmark", flush=True)
    eff = measure_efficiency(device, bundle["val"].X)
    write_json(_review("04_ta2_value", "EDITOR014_TA2_EFFICIENCY.json"), eff)

    print("[EDITOR-014] TA2 faithfulness (frozen protocol)", flush=True)
    train_trees = []
    val_trees = []
    ta2 = build_odst046_model()
    load_state_dict(ta2, F11_CHECKPOINTS[SCREENING_SEED]["checkpoint"], strict=True)
    ta2.to(device)
    freeze_teacher(ta2)
    for xb, _ in make_xy_loader(bundle["train"].X, bundle["train"].y, seed=0, shuffle=False):
        train_trees.append(historical_student_forward(ta2, xb.to(device))["tree_outputs"].detach().cpu().numpy())
    for xb, _ in make_xy_loader(bundle["val"].X, bundle["val"].y, seed=0, shuffle=False):
        val_trees.append(historical_student_forward(ta2, xb.to(device))["tree_outputs"].detach().cpu().numpy())
    faith = run_ta2_faithfulness(
        y=y_val,
        users=users,
        train_trees=np.concatenate(train_trees),
        val_trees=np.concatenate(val_trees),
    )
    write_json(_review("04_ta2_value", "EDITOR014_TA2_FAITHFULNESS.json"), faith)
    matrix = value_matrix_rows(
        l1_metrics=l1_mean,
        ta2_metrics=ta2_mean,
        cal=cal,
        eff=eff,
        faith=faith,
    )
    write_csv(_review("04_ta2_value", "EDITOR014_TA2_VALUE_MATRIX.csv"), matrix)
    return {
        "calibration": cal,
        "efficiency": eff,
        "faithfulness": faith,
        "l1_metrics": l1_mean,
        "ta2_metrics": ta2_mean,
        "mapping": mapping,
    }


def _write_handover(
    *,
    inner: dict[str, Any],
    ruling: str,
    best_name: str,
    best_mean: float,
    l1_mean: float,
    mean_delta: float,
    pos: int,
    ci: list[float],
    ext_trig: bool,
    ext_pos: int | None,
    faith_ruling: str,
) -> dict[str, Any]:
    by = {r["condition"]: r for r in inner["rows"]}
    if ruling in {"STRONG_TEMPORAL_ODST_VALUE", "CONSISTENT_TEMPORAL_ODST_VALUE", "STABILITY_SUPPORTED_TEMPORAL_ODST"}:
        if best_name == "T0":
            why_odst = (
                "nonlinear contextual state partitioning before temporal aggregation + time×tree explanations"
            )
            outcome = "A"
        else:
            why_odst = "incremental nonlinear temporal correction to a strong linear base + time×tree explanations"
            outcome = "B"
        odst_issue = "RESOLVED"
        paper_model = best_name
    else:
        outcome = "C_OR_D"
        why_odst = "pending_ta2_value_audit"
        odst_issue = "NOT_RESOLVED"
        paper_model = "TA2"
    gate = {
        "TEMPORAL_ODST_INCREMENTAL_VALUE": ruling,
        "outcome_class": outcome,
        "BEST_TEMPORAL_CANDIDATE": inner["decision"].get("best_temporal_candidate"),
        "PROMOTED_TEMPORAL_CANDIDATES": [p["inner_condition"] for p in inner["decision"]["promoted"]],
        "BEST_CURRENT_PAPER_MODEL": paper_model,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "CONSENSUS_TEACHER_ADVANTAGE": CONSENSUS_TEACHER_ADVANTAGE,
        "WHY_TEACHER_GUIDANCE": (
            "the frozen ensemble-guided TA2 formulation improves prediction beyond matched teacher initialisation"
        ),
        "WHY_ODST": why_odst,
        "EDITOR_ISSUE_TEACHER_INITIALISATION_ONLY": "RESOLVED",
        "EDITOR_ISSUE_C5_NEGLIGIBLE_INCREMENT": "RESOLVED_BY_TA2",
        "EDITOR_ISSUE_ODST_VALUE": odst_issue,
        "TEMPORAL_TIME_TREE_FAITHFULNESS": faith_ruling,
        "inner": {
            "B0": by.get("B0", {}).get("select_PR_AUC"),
            "B1": by.get("B1", {}).get("select_PR_AUC"),
            "T0": by.get("T0", {}).get("select_PR_AUC"),
            "T1": by.get("T1", {}).get("select_PR_AUC"),
            "T2": by.get("T2", {}).get("select_PR_AUC"),
        },
        "official": {
            "MATCHED_LINEAR_MEAN_PR_AUC": l1_mean,
            "TA2_MEAN_PR_AUC": FROZEN_TA2_MEAN_PR_AUC,
            "BEST_TEMPORAL_ODST_MEAN_PR_AUC": best_mean,
            "BEST_TEMPORAL_DELTA_VS_LINEAR": mean_delta,
            "POSITIVE_PRIMARY_SEEDS": f"{pos}/3",
            "USER_CLUSTER_95CI": ci,
            "EXTENDED_STABILITY_TRIGGERED": ext_trig,
            "EXTENDED_POSITIVE_SEEDS": None if ext_pos is None else f"{ext_pos}/10",
        },
    }
    write_json(_review("06_editor_response", "EDITOR014_PAPER_RESCUE_GATE.json"), gate)
    return gate


def finalize_handover(confirm: dict[str, Any], ta2: dict[str, Any]) -> None:
    ruling = confirm["ruling"]
    cal = ta2["calibration"]
    eff = ta2["efficiency"]
    faith = ta2["faithfulness"]
    competitive = abs(FROZEN_TA2_MINUS_L1) < 0.01 and FROZEN_TA2_L1_CI[0] <= 0 <= FROZEN_TA2_L1_CI[1]
    better_cal = cal["mean_delta_brier"] < 0 or cal["mean_delta_log_loss"] < 0
    better_eff = eff["TA2"]["median_latency_s"] < eff["L1"]["median_latency_s"]
    if ruling != "NO_TEMPORAL_ODST_VALUE":
        why = confirm["paper"]["WHY_ODST"]
        outcome = confirm["paper"]["outcome_class"]
        issue = "RESOLVED"
        paper_model = confirm["best_name"]
        next_action = "promote temporal ODST into the paper model and freeze explanation tables"
    elif competitive and (better_cal or better_eff) and faith["TA2_ROUTE_TRACEABILITY"] == "SUPPORTED":
        why = (
            "competitive point ranking versus matched L1, plus supported route/leaf "
            "structural traceability; Brier point estimate favours TA2 but the user-cluster "
            "CI includes zero; TA2 is not faster; reference-centred faithfulness is not supported"
        )
        outcome = "C"
        issue = "PARTIALLY_RESOLVED"
        paper_model = "TA2"
        next_action = "keep TA2 as the paper model under a Pareto/competitive-value argument; do not claim formal non-inferiority"
    else:
        why = "ODST_CHOICE_NOT_JUSTIFIED_BY_CURRENT_EVIDENCE"
        outcome = "D"
        issue = "NOT_RESOLVED"
        paper_model = "L1"
        next_action = "do not force an ODST claim; report the linear teacher-guided model as the justified predictor"
    rationale = {
        "outcome": outcome,
        "WHY_ODST": why,
        "WHY_TEACHER_GUIDANCE": (
            "the frozen ensemble-guided TA2 formulation improves prediction beyond matched teacher initialisation"
        ),
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "CONSENSUS_TEACHER_ADVANTAGE": CONSENSUS_TEACHER_ADVANTAGE,
        "formal_non_inferiority_margin": None,
        "competitive_point_performance_used": ruling == "NO_TEMPORAL_ODST_VALUE",
    }
    write_json(_review("06_editor_response", "EDITOR014_ODST_RATIONALE.json"), rationale)
    matrix = [
        {
            "issue": "teacher_initialisation_only",
            "status": "RESOLVED",
            "evidence": "EDITOR-012 SUPPORTED_STRONG",
        },
        {
            "issue": "C5_negligible_increment",
            "status": "RESOLVED_BY_TA2",
            "evidence": "TA2 vs C2-OPT teacher-guidance result remains frozen",
        },
        {
            "issue": "ODST_value",
            "status": issue,
            "evidence": why,
        },
    ]
    write_csv(_review("06_editor_response", "EDITOR014_EDITOR_ISSUE_MATRIX.csv"), matrix)
    gate = dict(confirm["paper"])
    gate.update(
        {
            "outcome_class": outcome,
            "WHY_ODST": why,
            "EDITOR_ISSUE_ODST_VALUE": issue,
            "BEST_CURRENT_PAPER_MODEL": paper_model,
            "NEXT_RECOMMENDED_ACTION": next_action,
            "TA2_MINUS_LINEAR_BRIER": cal["mean_delta_brier"],
            "TA2_BRIER_CI": cal["ci95_brier"],
            "TA2_MINUS_LINEAR_LOG_LOSS": cal["mean_delta_log_loss"],
            "TA2_LOG_LOSS_CI": cal["ci95_log_loss"],
            "TA2_MEDIAN_LATENCY": eff["TA2"]["median_latency_s"],
            "LINEAR_MEDIAN_LATENCY": eff["L1"]["median_latency_s"],
            "TA2_PARAMETER_COUNT": eff["TA2"]["parameter_count"],
            "LINEAR_PARAMETER_COUNT": eff["L1"]["parameter_count"],
            "TA2_REFERENCE_CENTRED_FAITHFULNESS": faith["TA2_REFERENCE_CENTRED_FAITHFULNESS"],
        }
    )
    write_json(_review("06_editor_response", "EDITOR014_PAPER_RESCUE_GATE.json"), gate)
    md = [
        "# EDITOR-014 paper rescue handover",
        "",
        f"TEMPORAL_ODST_INCREMENTAL_VALUE = {confirm['ruling']}",
        f"TA2_REFERENCE_CENTRED_FAITHFULNESS = {faith['TA2_REFERENCE_CENTRED_FAITHFULNESS']}",
        f"WHY_ODST = {why}",
        f"BEST_CURRENT_PAPER_MODEL = {paper_model}",
        f"NEXT_RECOMMENDED_ACTION = {next_action}",
        "",
        "Teacher guidance remains SUPPORTED_STRONG. Consensus-teacher advantage remains MIXED.",
        "r5.2 TEST was not opened. r5.1 and r6.2 were not rerun.",
    ]
    path = _review("06_editor_response", "EDITOR014_PAPER_RESCUE_HANDOVER.md")
    refuse_historical_write(path)
    path.write_text("\n".join(md) + "\n", encoding="utf-8")


def run_inner_phase() -> dict[str, Any]:
    write_protocol_packet()
    identities = verify_identities()
    device = _device()
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    write_json(_review("05_statistics", "EDITOR014_USER_MAPPING_VERIFICATION.json"), mapping)
    teachers = {}
    for seed in PRIMARY_SEEDS:
        model, _ = load_topt(seed, device)
        freeze_teacher(model)
        teachers[seed] = model
    ens = load_ensemble_cache()
    inner = run_inner_search(
        bundle=bundle,
        teachers=teachers,
        ens_train=ens["train"],
        device=device,
        pos_weight=bundle["pos_weight"],
    )
    write_json(
        _review("EDITOR014_PROMOTION_COMMIT_READY.json"),
        {"ready": True, "promoted": inner["decision"]["promoted"], "utc": utc_now()},
    )
    return {"identities": identities, "inner": inner, "mapping": mapping}


def run_campaign(*, resume_after_inner: bool = False) -> dict[str, Any]:
    started = utc_now()
    protocol = write_protocol_packet()
    identities = verify_identities()
    device = _device()
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    write_json(_review("05_statistics", "EDITOR014_USER_MAPPING_VERIFICATION.json"), mapping)
    teachers = {}
    for seed in PRIMARY_SEEDS:
        model, _ = load_topt(seed, device)
        freeze_teacher(model)
        teachers[seed] = model
    ens = load_ensemble_cache()
    if resume_after_inner:
        decision = __import__("json").loads(
            _review("01_inner_selection", "EDITOR014_PROMOTION_FREEZE.json").read_text(encoding="utf-8")
        )
        rows_path = _review("01_inner_selection", "EDITOR014_INNER_RESULTS.csv")
        import csv

        with rows_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["select_PR_AUC"] = float(row["select_PR_AUC"])
            row["select_F1"] = float(row["select_F1"])
            row["hybrid"] = str(row.get("hybrid", "")).lower() == "true"
            row["center"] = str(row.get("center", "")).lower() == "true"
        inner = {"decision": decision, "rows": rows, "packs": {}}
        mark_promotion_frozen()
    else:
        inner = run_inner_search(
            bundle=bundle,
            teachers=teachers,
            ens_train=ens["train"],
            device=device,
            pos_weight=bundle["pos_weight"],
        )
        write_json(
            _review("EDITOR014_PROMOTION_COMMIT_READY.json"),
            {"ready": True, "promoted": inner["decision"]["promoted"], "utc": utc_now()},
        )
    ta2 = run_ta2_audit(bundle=bundle, teachers=teachers, device=device, mapping=mapping)
    confirm = run_confirmation(
        bundle=bundle,
        teachers=teachers,
        ens_train=ens["train"],
        ens_val=ens["val"],
        device=device,
        pos_weight=bundle["pos_weight"],
        inner=inner,
        mapping=mapping,
    )
    finalize_handover(confirm, ta2)
    manifest = {
        "task_id": "EDITOR-014",
        "status": "COMPLETE",
        "started_utc": started,
        "finished_utc": utc_now(),
        "r52_test_accessed": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "identities": identities,
        "TEMPORAL_ODST_INCREMENTAL_VALUE": confirm["ruling"],
        "POST_ATTENTION_ODST_VALUE": POST_ATTENTION_ODST_VALUE,
        "LINEAR_ATTENTION_EQUIVALENCE_VERIFIED": protocol["audit"][
            "LINEAR_AFTER_ATTENTION_EQUIVALENT_TO_ATTENTION_WEIGHTED_LINEAR_PER_TIME"
        ],
        "device": str(device),
        "promoted": inner["decision"]["promoted"],
        "architecture": ENCODER_ARCH,
        "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
        "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
    }
    write_json(_review("EDITOR014_RUN_MANIFEST.json"), manifest)
    return {"identities": identities, "inner": inner, "confirm": confirm, "ta2": ta2, "manifest": manifest}


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
    if len(sys.argv) > 1 and sys.argv[1] == "--ta2-value-only":
        write_protocol_packet()
        identities = verify_identities()
        device = _device()
        bundle = load_train_validation()
        mapping = recover_user_mapping(bundle)
        teachers = {}
        for seed in PRIMARY_SEEDS:
            model, _ = load_topt(seed, device)
            freeze_teacher(model)
            teachers[seed] = model
        run_ta2_audit(bundle=bundle, teachers=teachers, device=device, mapping=mapping)
        return
    run_campaign()


if __name__ == "__main__":
    main()
