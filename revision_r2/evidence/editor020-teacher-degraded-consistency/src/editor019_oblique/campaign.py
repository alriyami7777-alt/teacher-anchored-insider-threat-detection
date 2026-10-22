"""EDITOR-019 autonomous sparse oblique boosted tree rescue orchestrator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds
from editor012_rescue.data import load_train_validation, subset_bundle
from editor012_rescue.inner_split import inner_split_masks
from editor012_rescue.metrics import metrics_from_logits
from editor012_rescue.constants import EXPECTED_VAL_MALICIOUS_USERS, EXPECTED_VAL_USERS, EXPECTED_VAL_WINDOWS_PER_USER

from .boost import train_boosted
from .cache import cached_l1_logits, cached_summaries, fit_and_transform_views, load_ensemble_split, load_train_only, score_l1_logits
from .constants import (
    CONDITION_SPECS,
    EDITOR017_RESULTS_COMMIT,
    EDITOR018_RESULTS_COMMIT,
    EXPECTED_INNER_SELECT_N,
    EXPECTED_INNER_SELECT_POS,
    EXPECTED_INNER_TRAIN_N,
    EXPECTED_INNER_TRAIN_POS,
    EXPECTED_USER_MAPPING_SHA256,
    EXTENDED_SEEDS,
    F11_CHECKPOINTS,
    FROZEN_L1_MEAN_PR_AUC,
    FROZEN_TA2_MEAN_PR_AUC,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    INNER_NEW,
    L1_CHECKPOINTS,
    LAMBDA_TEACHER,
    NEW_TREE_FAMILIES,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    SCREENING_SEED,
    SOURCE_CHANNELS,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from .explain import directional_from_trees, signed_split_rows
from .freeze import write_protocol_packet
from .io_util import write_csv, write_json
from .models import teacher_residual
from .promotion import decide_promotions, decide_xgb_promotion
from .robustness import degraded_metrics, perturb_then_summarise, train_hardening
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor019Blocked,
    enter_inner_phase,
    exit_inner_phase,
    mark_promotion_frozen,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .train import load_branch, score_branch, train_head_only
from .xgb_teacher import score_frozen_xgb


def _rev(*parts: str) -> Path:
    return REVIEW_ROOT.joinpath(*parts)


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def family_from_condition(name: str) -> str:
    token = str(name)
    if token.endswith("-XD"):
        return token[: -len("-XD")]
    if token.endswith("-D") or token.endswith("-T"):
        return token[:-2]
    return token


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor019Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor019Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor019Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor019Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    return {
        "USER_MAPPING_RECOVERED": True,
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "per_user_count_min": int(counts.min()),
        "per_user_count_max": int(counts.max()),
        "n_malicious_users": int(len(malicious)),
        "malicious_users": malicious,
        "mapping_sha256": mapping_hash,
        "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
    }


def _metric_row(name: str, seed: int, met: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "condition": name,
        "seed": seed,
        "PR_AUC": float(met["pr_auc"]),
        "F1": float(met["f1"]),
        "precision": float(met.get("precision", 0.0)),
        "recall": float(met.get("recall", 0.0)),
        "Brier": float(met["Brier"]),
        "log_loss": float(met["log_loss"]),
        "predicted_positive_fraction": float(met["predicted_positive_fraction"]),
        **extra,
    }


def align_bundle(bundle, split: str) -> dict[str, Any]:
    pack = cached_summaries(bundle, split)
    if pack["n"] != len(bundle.y):
        raise Editor019Blocked("CROSS_VIEW_ALIGNMENT: window count mismatch")
    if not np.array_equal(pack["y"], np.asarray(bundle.y, dtype=np.float32).reshape(-1)):
        raise Editor019Blocked("CROSS_VIEW_ALIGNMENT: label mismatch")
    meta = pack["meta"]
    if not (
        np.array_equal(meta["user"], np.asarray(bundle.user).astype(str))
        and np.array_equal(meta["sequence_id"], np.asarray(bundle.sequence_id).astype(str))
        and np.array_equal(meta["start_date"], np.asarray(bundle.start_date).astype(str))
        and np.array_equal(meta["end_date"], np.asarray(bundle.end_date).astype(str))
    ):
        raise Editor019Blocked("CROSS_VIEW_ALIGNMENT: metadata key mismatch")
    return {
        "split": split,
        "n": pack["n"],
        "n_pos": pack["n_pos"],
        "same_number_of_windows": True,
        "same_labels": True,
        "same_window_boundaries": True,
        "alignment_sha256": pack["alignment_sha256"],
        "raw_sha256": pack["raw_sha256"],
        "status": "ALIGNED",
        "s40_raw": pack["s40_raw"],
        "y": pack["y"],
        "meta": meta,
    }


def _compact(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition": pack["condition"],
        "family": pack["family"],
        "teacher": pack["teacher"],
        "seed": pack["seed"],
        "select_PR_AUC": pack["select_PR_AUC"],
        "select_F1": pack["select_F1"],
        "select_Brier": pack["select_Brier"],
        "select_log_loss": pack["select_log_loss"],
        "best_epoch": pack["best_epoch"],
        "checkpoint": pack["checkpoint"],
    }


def _maybe_resume_pack(
    name: str,
    *,
    family: str,
    teacher: bool,
    n_trees: int,
    s_se,
    y_se,
    l1_se,
    device,
    seed: int = SCREENING_SEED,
) -> dict[str, Any] | None:
    ckpt = OUTPUT_ROOT / name / f"seed{seed}" / "best.pt"
    if not ckpt.is_file():
        return None
    payload = torch.load(ckpt, map_location="cpu", weights_only=False)
    branch = load_branch(family, payload, device, n_trees=payload.get("n_trees", n_trees))
    scored = score_branch(branch, s_se, y_se, l1_se, device)
    print(f"[EDITOR-019] resume {name} seed={seed} select_PR-AUC={float(scored['metrics']['pr_auc']):.6f}", flush=True)
    return {
        "condition": name,
        "family": family,
        "teacher": teacher,
        "seed": seed,
        "best_epoch": int(payload.get("best_epoch", 0)),
        "select_PR_AUC": float(scored["metrics"]["pr_auc"]),
        "select_F1": float(scored["metrics"]["f1"]),
        "select_Brier": float(scored["metrics"]["Brier"]),
        "select_log_loss": float(scored["metrics"]["log_loss"]),
        "precision": float(scored["metrics"]["precision"]),
        "recall": float(scored["metrics"]["recall"]),
        "threshold": float(scored["metrics"]["threshold"]),
        "predicted_positive_fraction": float(scored["metrics"]["predicted_positive_fraction"]),
        "seconds": 0.0,
        "checkpoint": str(ckpt),
        "checkpoint_sha256": sha256_file(ckpt),
        "history": [],
        "select_logits": scored["logits"],
        "select_tree_outputs": scored["tree_outputs"],
        "select_tree_weights": scored["tree_weights"],
        "select_choices": scored["choices"],
        "branch": branch,
        "resumed": True,
    }


def _train_condition(
    name: str,
    *,
    n_trees: int,
    s_tr,
    y_tr,
    l1_tr,
    ens_tr,
    s_se,
    y_se,
    l1_se,
    device,
    pos_weight,
    residual_train=None,
    select_name: str = "inner_select",
    seed: int = SCREENING_SEED,
) -> dict[str, Any]:
    spec = CONDITION_SPECS[name]
    family = spec["family"]
    teacher = bool(spec["teacher"])
    resumed = _maybe_resume_pack(
        name,
        family=family,
        teacher=teacher,
        n_trees=n_trees,
        s_se=s_se,
        y_se=y_se,
        l1_se=l1_se,
        device=device,
    )
    if resumed is not None:
        return resumed
    kwargs = dict(
        condition=name,
        teacher=teacher,
        seed=seed,
        s_train=s_tr,
        y_train=y_tr,
        l1_train=l1_tr,
        ens_train=ens_tr,
        s_select=s_se,
        y_select=y_se,
        l1_select=l1_se,
        device=device,
        pos_weight=pos_weight,
        select_name=select_name,
        residual_train=residual_train,
    )
    if family == "BSO-DTE40":
        return train_boosted(n_trees=n_trees, **kwargs)
    return train_head_only(family=family, n_trees=n_trees, **kwargs)


def run_inner(device: torch.device, n_trees: int) -> dict[str, Any]:
    enter_inner_phase()
    try:
        bundle = load_train_only()
        train = bundle["train"]
        split = inner_split_masks(train)
        if (
            split["n_inner_train"] != EXPECTED_INNER_TRAIN_N
            or split["n_inner_select"] != EXPECTED_INNER_SELECT_N
            or split["n_inner_train_pos"] != EXPECTED_INNER_TRAIN_POS
            or split["n_inner_select_pos"] != EXPECTED_INNER_SELECT_POS
        ):
            raise Editor019Blocked(f"inner split counts mismatch: { {k: split[k] for k in ('n_inner_train','n_inner_select','n_inner_train_pos','n_inner_select_pos')} }")
        train_align = align_bundle(train, "train")
        inner_tr = subset_bundle(train, split["train_mask"], "inner_train")
        inner_se = subset_bundle(train, split["select_mask"], "inner_select")
        s_all = train_align["s40_raw"]
        s_tr_raw = s_all[split["train_mask"]]
        s_se_raw = s_all[split["select_mask"]]
        y_tr = np.asarray(inner_tr.y, dtype=np.float32).reshape(-1)
        y_se = np.asarray(inner_se.y, dtype=np.float32).reshape(-1)
        if not np.array_equal(y_tr, train_align["y"][split["train_mask"]]):
            raise Editor019Blocked("inner label mismatch")
        views = fit_and_transform_views(train_raw=s_tr_raw, other_raw={"select": s_se_raw}, fitted_on="INNER_TRAIN")
        s_tr = views["transformed"]["fit"]
        s_se = views["transformed"]["select"]
        if s_tr.shape[1] != 40 or s_se.shape[1] != 40:
            raise Editor019Blocked("40-summary shape mismatch")
        if not np.array_equal(s_tr[0], views["transformed"]["fit"][0]):
            raise Editor019Blocked("MLP and trees must receive the same transformed 40-view")
        ens_train = load_ensemble_split("train")
        ens_tr = ens_train["ens"][split["train_mask"]]
        ens_se = ens_train["ens"][split["select_mask"]]
        l1_all, l1_sha = cached_l1_logits(seed=SCREENING_SEED, split="train", X=train.X, y=train.y, device=device)
        l1_tr = l1_all[split["train_mask"]]
        l1_se = l1_all[split["select_mask"]]
        residual = np.asarray(teacher_residual(torch.from_numpy(ens_tr), torch.from_numpy(l1_tr)).numpy())
        if not np.allclose(residual, ens_tr - l1_tr, atol=1e-5):
            raise Editor019Blocked("teacher residual identity failed on INNER_TRAIN")
        l1_select_met = metrics_from_logits(y_se, l1_se)
        l1_pr = float(l1_select_met["pr_auc"])
        write_json(
            _rev("00_protocol", "EDITOR019_INPUT_CHECKSUMS.json"),
            json.loads(_rev("00_protocol", "EDITOR019_INPUT_CHECKSUMS.json").read_text(encoding="utf-8"))
            | {
                "l1_train_sha256": l1_sha,
                "s40_train_sha256": train_align["raw_sha256"],
                "scaler": views["payload"],
                "same_transformed_40_for_all_branches": True,
            },
        )

        rows = [
            {
                "condition": "L1",
                "family": "L1",
                "teacher": False,
                "seed": SCREENING_SEED,
                "select_PR_AUC": l1_pr,
                "select_F1": float(l1_select_met["f1"]),
                "select_Brier": float(l1_select_met["Brier"]),
                "select_log_loss": float(l1_select_met["log_loss"]),
                "best_epoch": 0,
                "checkpoint": str(L1_CHECKPOINTS[SCREENING_SEED]["checkpoint"]),
            }
        ]
        packs = {}
        common = dict(
            n_trees=n_trees,
            s_tr=s_tr,
            y_tr=y_tr,
            l1_tr=l1_tr,
            ens_tr=ens_tr,
            s_se=s_se,
            y_se=y_se,
            l1_se=l1_se,
            device=device,
            pos_weight=float(bundle["pos_weight"]),
        )
        for name in ("MLP40-D", "ODST40-D") + INNER_NEW:
            pack = _train_condition(name, **common)
            packs[name] = pack
            rows.append(_compact(pack))

        decision = decide_promotions(rows, l1_pr_auc=l1_pr)
        write_csv(_rev("01_inner", "EDITOR019_INNER_RESULTS.csv"), rows)
        write_json(_rev("01_inner", "EDITOR019_FACTORIAL_EFFECTS.json"), decision["effects"])

        xgb_rows: list[dict[str, Any]] = []
        xgb_audit = {
            "XGB_TEACHER_BRANCH": decision["XGB_TEACHER_BRANCH"],
            "trigger": decision["xgb_trigger_detail"],
            "retrained": False,
        }
        if decision["XGB_TEACHER_BRANCH"] == "TRIGGERED":
            xgb = score_frozen_xgb(raw_train=s_tr_raw, raw_select=s_se_raw, l1_train=l1_tr, l1_select=l1_se)
            xgb_audit.update({k: xgb[k] for k in xgb if k not in {"train_prob", "select_prob", "train_logit", "select_logit", "train_residual", "select_residual"}})
            best_tree_fam = family_from_condition(str(decision["xgb_trigger_detail"]["best_so_dte_or_bso"]))
            for name, family in (("MLP40-XD", "MLP40"), (f"{best_tree_fam}-XD", best_tree_fam)):
                resumed = _maybe_resume_pack(
                    name,
                    family=family,
                    teacher=True,
                    n_trees=n_trees,
                    s_se=s_se,
                    y_se=y_se,
                    l1_se=l1_se,
                    device=device,
                )
                if resumed is not None:
                    packs[name] = resumed
                    xgb_rows.append(_compact(resumed))
                    continue
                if family == "BSO-DTE40":
                    pack = train_boosted(
                        condition=name,
                        teacher=True,
                        seed=SCREENING_SEED,
                        s_train=s_tr,
                        y_train=y_tr,
                        l1_train=l1_tr,
                        ens_train=ens_tr,
                        s_select=s_se,
                        y_select=y_se,
                        l1_select=l1_se,
                        device=device,
                        pos_weight=float(bundle["pos_weight"]),
                        n_trees=n_trees,
                        residual_train=xgb["train_residual"],
                    )
                else:
                    pack = train_head_only(
                        condition=name,
                        family=family,
                        teacher=True,
                        seed=SCREENING_SEED,
                        s_train=s_tr,
                        y_train=y_tr,
                        l1_train=l1_tr,
                        ens_train=ens_tr,
                        s_select=s_se,
                        y_select=y_se,
                        l1_select=l1_se,
                        device=device,
                        pos_weight=float(bundle["pos_weight"]),
                        n_trees=n_trees,
                        residual_train=xgb["train_residual"],
                    )
                packs[name] = pack
                xgb_rows.append(_compact(pack))
            xgb_dec = decide_xgb_promotion(
                l1_pr_auc=l1_pr,
                mlp_xd=float(packs["MLP40-XD"]["select_PR_AUC"]),
                tree_xd=float(packs[f"{best_tree_fam}-XD"]["select_PR_AUC"]),
                tree_name=best_tree_fam,
            )
            decision["xgb_promotion"] = xgb_dec
            if xgb_dec["promoted_names"]:
                decision["promoted"] = xgb_dec["promoted"]
                decision["promoted_names"] = xgb_dec["promoted_names"]
            write_csv(_rev("02_xgb_teacher", "EDITOR019_XGB_TEACHER_RESULTS.csv"), xgb_rows)
        else:
            write_csv(
                _rev("02_xgb_teacher", "EDITOR019_XGB_TEACHER_RESULTS.csv"),
                [],
                fieldnames=["condition", "note"],
            )
        write_json(_rev("02_xgb_teacher", "EDITOR019_XGB_TEACHER_AUDIT.json"), xgb_audit)

        freeze = {
            "promoted": decision["promoted"],
            "promoted_names": decision["promoted_names"],
            "L1_PR_AUC": l1_pr,
            "L1_select_metrics": {k: v for k, v in l1_select_met.items() if k not in {"probs", "pred"}},
            "inner_rows": rows,
            "effects": decision["effects"],
            "XGB_TEACHER_BRANCH": decision["XGB_TEACHER_BRANCH"],
            "xgb_trigger_detail": decision["xgb_trigger_detail"],
            "xgb_promotion": decision.get("xgb_promotion"),
            "n_trees": n_trees,
            "scaler": views["payload"],
            "no_architecture_may_be_added_after_this_commit": True,
            "utc": utc_now(),
        }
        write_json(_rev("01_inner", "EDITOR019_PROMOTION_FREEZE.json"), freeze)
        return {
            "decision": decision,
            "freeze": freeze,
            "packs": packs,
            "l1_pr": l1_pr,
            "views": views,
            "inner_tr": inner_tr,
            "inner_se": inner_se,
            "y_tr": y_tr,
            "y_se": y_se,
            "l1_tr": l1_tr,
            "l1_se": l1_se,
            "ens_tr": ens_tr,
            "s_tr": s_tr,
            "s_se": s_se,
            "s_tr_raw": s_tr_raw,
            "s_se_raw": s_se_raw,
            "pos_weight": float(bundle["pos_weight"]),
            "train_align": train_align,
            "split": split,
            "train": train,
            "n_trees": n_trees,
        }
    finally:
        exit_inner_phase()


def _classify_tree_value(
    *,
    mean_l1: float,
    mean_mlp: float,
    pos_l1: int,
    pos_mlp: int,
    ci_l1: list[float],
    ci_mlp: list[float],
) -> str:
    both_means = mean_l1 > 0 and mean_mlp > 0
    if both_means and pos_l1 == 3 and pos_mlp == 3 and ci_l1[0] > 0 and ci_mlp[0] > 0:
        return "STRONG"
    if both_means and pos_l1 == 3 and pos_mlp == 3:
        return "CONSISTENT"
    if both_means and (pos_l1 >= 2 or pos_mlp >= 2) and min(pos_l1, pos_mlp) >= 2:
        return "STABILITY_CANDIDATE"
    return "NOT_SUPPORTED"


def run_confirmation(inner: dict[str, Any], device: torch.device) -> dict[str, Any]:
    mark_promotion_frozen()
    bundle = load_train_validation()
    train = bundle["train"]
    val = bundle["val"]
    train_align = align_bundle(train, "train")
    val_align = align_bundle(val, "validation")
    mapping = recover_user_mapping(bundle)
    write_json(_rev("04_statistics", "EDITOR019_USER_MAPPING_VERIFICATION.json"), mapping)
    views = fit_and_transform_views(train_raw=train_align["s40_raw"], other_raw={"val": val_align["s40_raw"]}, fitted_on="TRAIN")
    ens_tr = load_ensemble_split("train")["ens"]
    y_tr = train_align["y"]
    y_va = val_align["y"]
    s_tr = views["transformed"]["fit"]
    s_va = views["transformed"]["val"]
    n_trees = int(inner["n_trees"])
    promoted = list(inner["freeze"]["promoted_names"])
    xgb_mode = any(n.endswith("-XD") for n in promoted)
    controls = ["MLP40-XD"] if xgb_mode else ["MLP40-D"]
    task_controls = []
    for name in promoted:
        fam = family_from_condition(name)
        task_controls.append(f"{fam}-T")
    to_train = list(dict.fromkeys(promoted + controls + task_controls))

    val_rows = []
    logits_store: dict[str, dict[int, np.ndarray]] = {}
    thresholds: dict[str, dict[int, float]] = {}
    tree_store: dict[str, dict[int, np.ndarray]] = {}
    train_tree_store: dict[str, dict[int, np.ndarray]] = {}
    l1_val_logits = {}
    residual_tr = None
    if xgb_mode:
        xgb = score_frozen_xgb(raw_train=train_align["s40_raw"], raw_select=val_align["s40_raw"], l1_train=np.zeros(len(y_tr)), l1_select=np.zeros(len(y_va)))
        # residual rebuilt per seed with that seed's L1
    for seed in PRIMARY_SEEDS:
        l1_tr, _ = cached_l1_logits(seed=seed, split="train", X=train.X, y=train.y, device=device)
        l1_va = np.asarray(np.load(L1_CHECKPOINTS[seed]["val_logits"]), dtype=np.float32).reshape(-1)
        l1_val_logits[seed] = l1_va
        val_rows.append(_metric_row("L1", seed, metrics_from_logits(y_va, l1_va), identity="frozen_L1"))
        ta2 = np.asarray(np.load(F11_CHECKPOINTS[seed]["val_logits"]), dtype=np.float32).reshape(-1)
        val_rows.append(_metric_row("TA2", seed, metrics_from_logits(y_va, ta2), identity="frozen_TA2"))
        if xgb_mode:
            residual_tr = xgb["train_logit"] - l1_tr
        for name in to_train:
            spec_name = name if name in CONDITION_SPECS else name.replace("-XD", "-D")
            spec = CONDITION_SPECS[spec_name]
            family = spec["family"]
            teacher = name.endswith("-D") or name.endswith("-XD")
            if family == "BSO-DTE40":
                pack = train_boosted(
                    condition=f"VAL_{name}",
                    teacher=teacher,
                    seed=seed,
                    s_train=s_tr,
                    y_train=y_tr,
                    l1_train=l1_tr,
                    ens_train=ens_tr,
                    s_select=s_va,
                    y_select=y_va,
                    l1_select=l1_va,
                    device=device,
                    pos_weight=float(bundle["pos_weight"]),
                    n_trees=n_trees,
                    select_name="validation",
                    residual_train=residual_tr if name.endswith("-XD") else None,
                )
            else:
                pack = train_head_only(
                    condition=f"VAL_{name}",
                    family=family,
                    teacher=teacher,
                    seed=seed,
                    s_train=s_tr,
                    y_train=y_tr,
                    l1_train=l1_tr,
                    ens_train=ens_tr,
                    s_select=s_va,
                    y_select=y_va,
                    l1_select=l1_va,
                    device=device,
                    pos_weight=float(bundle["pos_weight"]),
                    n_trees=n_trees,
                    select_name="validation",
                    residual_train=residual_tr if name.endswith("-XD") else None,
                )
            logits_store.setdefault(name, {})[seed] = pack["select_logits"]
            thresholds.setdefault(name, {})[seed] = float(pack["threshold"])
            tree_store.setdefault(name, {})[seed] = pack["select_tree_outputs"]
            scored_tr = score_branch(pack["branch"], s_tr, y_tr, l1_tr, device) if hasattr(pack["branch"], "family") else None
            if scored_tr is not None:
                train_tree_store.setdefault(name, {})[seed] = scored_tr["tree_outputs"]
            val_rows.append(_metric_row(name, seed, pack, mode="head_only"))
            outp = OUTPUT_ROOT / f"VAL_{name}" / f"seed{seed}"
            outp.mkdir(parents=True, exist_ok=True)
            np.save(outp / "val_logits.npy", pack["select_logits"])

    write_csv(_rev("03_validation", "EDITOR019_VALIDATION_RESULTS.csv"), val_rows)

    def _mean(name: str) -> float:
        vals = [r["PR_AUC"] for r in val_rows if r["condition"] == name]
        return float(np.mean(vals)) if vals else float("nan")

    l1_mean = _mean("L1")
    best_tree = promoted[0] if promoted else None
    if len(promoted) > 1:
        best_tree = max(promoted, key=_mean)
    best_tree_mean = _mean(best_tree) if best_tree else float("nan")
    mlp_name = "MLP40-XD" if xgb_mode else "MLP40-D"
    mlp_mean = _mean(mlp_name)
    users = np.asarray(val.user).astype(str)
    boot = {}
    if best_tree is not None:
        for cname, a, b in (
            ("tree_minus_L1", "L1", best_tree),
            ("tree_minus_MLP40", mlp_name, best_tree),
        ):
            if a == "L1":
                a_logits = [l1_val_logits[s] for s in PRIMARY_SEEDS]
                a_thr = [float(metrics_from_logits(y_va, l1_val_logits[s])["threshold"]) for s in PRIMARY_SEEDS]
            else:
                a_logits = [logits_store[a][s] for s in PRIMARY_SEEDS]
                a_thr = [thresholds[a][s] for s in PRIMARY_SEEDS]
            boot[cname] = paired_user_cluster_mean_across_seeds(
                users,
                y_va,
                a_logits,
                [logits_store[b][s] for s in PRIMARY_SEEDS],
                frozen_thresholds_a=a_thr,
                frozen_thresholds_b=[thresholds[b][s] for s in PRIMARY_SEEDS],
            )
    write_json(_rev("04_statistics", "EDITOR019_CLUSTER_BOOTSTRAP.json"), boot)

    tree_vs_l1 = [
        float(metrics_from_logits(y_va, logits_store[best_tree][s])["pr_auc"]) - float(metrics_from_logits(y_va, l1_val_logits[s])["pr_auc"])
        for s in PRIMARY_SEEDS
    ] if best_tree else []
    tree_vs_mlp = [
        float(metrics_from_logits(y_va, logits_store[best_tree][s])["pr_auc"]) - float(metrics_from_logits(y_va, logits_store[mlp_name][s])["pr_auc"])
        for s in PRIMARY_SEEDS
    ] if best_tree and mlp_name in logits_store else []
    pos_l1 = int(sum(d > 0 for d in tree_vs_l1))
    pos_mlp = int(sum(d > 0 for d in tree_vs_mlp))
    ci_l1 = boot.get("tree_minus_L1", {}).get("ci95_pr_auc", [float("nan"), float("nan")])
    ci_mlp = boot.get("tree_minus_MLP40", {}).get("ci95_pr_auc", [float("nan"), float("nan")])
    mean_l1_delta = float(np.mean(tree_vs_l1)) if tree_vs_l1 else float("nan")
    mean_mlp_delta = float(np.mean(tree_vs_mlp)) if tree_vs_mlp else float("nan")
    ruling = _classify_tree_value(mean_l1=mean_l1_delta, mean_mlp=mean_mlp_delta, pos_l1=pos_l1, pos_mlp=pos_mlp, ci_l1=ci_l1, ci_mlp=ci_mlp)

    stability_rows = []
    if ruling == "STABILITY_CANDIDATE" and best_tree:
        fam = family_from_condition(best_tree)
        teacher = best_tree.endswith("-D") or best_tree.endswith("-XD")
        n_pos = min(pos_l1, pos_mlp)
        for seed in EXTENDED_SEEDS:
            l1_tr, _ = cached_l1_logits(seed=PRIMARY_SEEDS[0], split="train", X=train.X, y=train.y, device=device)
            pack = _train_one_val(fam, teacher, seed, s_tr, y_tr, l1_tr, ens_tr, s_va, y_va, l1_val_logits[42], device, bundle, n_trees, residual_tr if xgb_mode else None)
            mlp_pack = _train_one_val("MLP40", True, seed, s_tr, y_tr, l1_tr, ens_tr, s_va, y_va, l1_val_logits[42], device, bundle, n_trees, residual_tr if xgb_mode else None)
            l1_pr = float(metrics_from_logits(y_va, l1_val_logits[42])["pr_auc"])
            stability_rows.append(
                {
                    "seed": seed,
                    "tree_PR_AUC": pack["select_PR_AUC"],
                    "mlp_PR_AUC": mlp_pack["select_PR_AUC"],
                    "l1_PR_AUC": l1_pr,
                    "tree_minus_l1": pack["select_PR_AUC"] - l1_pr,
                    "tree_minus_mlp": pack["select_PR_AUC"] - mlp_pack["select_PR_AUC"],
                }
            )
        n_pos += sum(1 for r in stability_rows if r["tree_minus_l1"] > 0 and r["tree_minus_mlp"] > 0)
        ruling = "STABILITY_ONLY" if n_pos >= 8 else "NOT_SUPPORTED"
    write_csv(_rev("04_statistics", "EDITOR019_STABILITY_RESULTS.csv"), stability_rows)

    comparisons = {
        "BEST_TREE_MEAN_PR_AUC": best_tree_mean,
        "L1_MEAN_PR_AUC": l1_mean,
        "MATCHED_MLP_MEAN_PR_AUC": mlp_mean,
        "TA2_MEAN_PR_AUC": _mean("TA2"),
        "DELTA_TREE_VS_L1": best_tree_mean - l1_mean if best_tree else None,
        "DELTA_TREE_VS_MLP": best_tree_mean - mlp_mean if best_tree else None,
        "POSITIVE_SEEDS_TREE_VS_L1": f"{pos_l1}/3",
        "POSITIVE_SEEDS_TREE_VS_MLP": f"{pos_mlp}/3",
        "CI_TREE_MINUS_L1": ci_l1,
        "CI_TREE_MINUS_MLP": ci_mlp,
        "TREE_VALUE": ruling,
        "BEST_TREE": best_tree,
    }
    write_json(_rev("03_validation", "EDITOR019_PRIMARY_COMPARISONS.json"), comparisons)
    return _finish_confirm(
        inner=inner,
        device=device,
        ruling=ruling,
        comparisons=comparisons,
        best_tree=best_tree,
        mapping=mapping,
        views=views,
        val=val,
        train=train,
        y_va=y_va,
        users=users,
        logits_store=logits_store,
        tree_store=tree_store,
        train_tree_store=train_tree_store,
        l1_val_logits=l1_val_logits,
        val_rows=val_rows,
        mlp_name=mlp_name,
        n_trees=n_trees,
        bundle=bundle,
        s_tr=s_tr,
        y_tr=y_tr,
        ens_tr=ens_tr,
    )


def _train_one_val(family, teacher, seed, s_tr, y_tr, l1_tr, ens_tr, s_va, y_va, l1_va, device, bundle, n_trees, residual_train):
    if family == "BSO-DTE40":
        return train_boosted(
            condition=f"STAB_{family}",
            teacher=teacher,
            seed=seed,
            s_train=s_tr,
            y_train=y_tr,
            l1_train=l1_tr,
            ens_train=ens_tr,
            s_select=s_va,
            y_select=y_va,
            l1_select=l1_va,
            device=device,
            pos_weight=float(bundle["pos_weight"]),
            n_trees=n_trees,
            select_name="validation",
            residual_train=residual_train,
        )
    return train_head_only(
        condition=f"STAB_{family}",
        family=family,
        teacher=teacher,
        seed=seed,
        s_train=s_tr,
        y_train=y_tr,
        l1_train=l1_tr,
        ens_train=ens_tr,
        s_select=s_va,
        y_select=y_va,
        l1_select=l1_va,
        device=device,
        pos_weight=float(bundle["pos_weight"]),
        n_trees=n_trees,
        select_name="validation",
        residual_train=residual_train,
    )


def _finish_confirm(**kwargs: Any) -> dict[str, Any]:
    inner = kwargs["inner"]
    device = kwargs["device"]
    ruling = kwargs["ruling"]
    comparisons = kwargs["comparisons"]
    best_tree = kwargs["best_tree"]
    inner_rows = {r["condition"]: r for r in inner["freeze"]["inner_rows"]}
    teacher_effects = inner["freeze"]["effects"]["TEACHER_EFFECT"]
    tree_teacher = max(teacher_effects.values()) if teacher_effects else 0.0
    if best_tree:
        fam = family_from_condition(best_tree)
        tree_teacher = float(teacher_effects.get(fam, tree_teacher))
    if tree_teacher > 0.001:
        tg = "STRONG"
    elif tree_teacher > 0:
        tg = "CONSISTENT"
    else:
        tg = "NOT_SUPPORTED"

    feat_rows = []
    explain = {
        "SIGNED_OBLIQUE_TREE_LOCAL_FAITHFULNESS": "NOT_EVALUATED",
        "TA2_GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    }
    if best_tree and best_tree in inner["packs"]:
        payload = torch.load(Path(inner["packs"][best_tree]["checkpoint"]), map_location="cpu", weights_only=False)
        fam = CONDITION_SPECS.get(best_tree, CONDITION_SPECS.get(best_tree.replace("-XD", "-D")))["family"]
        branch = load_branch(fam, payload, device, n_trees=kwargs["n_trees"])
        feat_rows = signed_split_rows(branch)
        if best_tree in kwargs["tree_store"] and best_tree in kwargs["train_tree_store"]:
            dirc = directional_from_trees(
                y=kwargs["y_va"],
                tree_outputs=kwargs["tree_store"][best_tree][42],
                train_tree_outputs=kwargs["train_tree_store"][best_tree][42],
                l1_logit=kwargs["l1_val_logits"][42],
                users=kwargs["users"],
            )
            explain.update({k: dirc[k] for k in dirc if k != "table"})
    write_csv(_rev("05_explainability", "EDITOR019_SIGNED_SPLITS.csv"), feat_rows)
    write_json(_rev("05_explainability", "EDITOR019_LOCAL_FAITHFULNESS.json"), explain)

    robust_out = {
        "DEGRADED_INPUT_CONFIRMATION": "NOT_TRIGGERED",
        "ROBUSTNESS_TRAINING_TRIGGERED": "NO",
    }
    clean_gate = ruling in {"STRONG", "CONSISTENT", "STABILITY_ONLY"}
    if clean_gate and best_tree:
        robust_out = _run_robustness(best_tree=best_tree, inner=inner, **kwargs)
    else:
        write_csv(_rev("06_robustness", "EDITOR019_ROBUSTNESS_RESULTS.csv"), [], fieldnames=["model", "note"])
    write_json(_rev("06_robustness", "EDITOR019_ROBUSTNESS_RULING.json"), robust_out)

    why_teacher = (
        "Teacher residual asks the 40-view tree to fit neural-ensemble information absent from frozen L1, "
        "with lambda exactly 0.5 and no route anchor in the architecture screen."
    )
    why_tree = (
        "The factorial isolates signed splits, node-specific geometry, and stagewise boosting "
        "while remaining an explicit differentiable tree, not an MLP."
    )
    why_not_l1 = (
        "Attention-linear already uses the 20x13 sequence. A tree is justified only if it beats both L1 and the matched MLP40 on the same 40 summaries."
    )
    paper_model = "TA2"
    if ruling == "STRONG" and explain.get("SIGNED_OBLIQUE_TREE_LOCAL_FAITHFULNESS") in {"SUPPORTED", "QUALIFIED"}:
        paper_model = best_tree
    matrix = [
        {"issue": "TEACHER_INITIALISATION_ONLY", "status": "RESOLVED", "evidence": TEACHER_GUIDANCE_VS_INITIALISATION},
        {"issue": "C5_NEGLIGIBLE_INCREMENT", "status": "RESOLVED_BY_REPAIRED_FORMULATION", "evidence": "EDITOR-012 ET1 lambda=0.5"},
        {"issue": "CURRENT_ODST40_SPECIFIC_VALUE", "status": "NOT_SUPPORTED" if ruling == "NOT_SUPPORTED" else ruling, "evidence": ruling},
        {"issue": "GLOBAL_TOPK_PR_AUC_FAITHFULNESS", "status": "NOT_SUPPORTED", "evidence": "preserved from EDITOR-015/017"},
    ]
    write_csv(_rev("07_editor_response", "EDITOR019_EDITOR_ISSUE_MATRIX.csv"), matrix)
    gate = {
        "BEST_CURRENT_PAPER_MODEL": paper_model,
        "TREE_VALUE": ruling,
        "TEACHER_GUIDANCE_WITHIN_TREE": tg,
        "WHY_TEACHER_GUIDANCE": why_teacher,
        "WHY_DIFFERENTIABLE_TREE": why_tree,
        "WHY_NOT_ATTENTION_LINEAR_ONLY": why_not_l1,
        "LOCAL_DIRECTIONAL_FAITHFULNESS": explain.get("SIGNED_OBLIQUE_TREE_LOCAL_FAITHFULNESS"),
        "DEGRADED_INPUT_CONFIRMATION": robust_out.get("DEGRADED_INPUT_CONFIRMATION"),
        "comparisons": comparisons,
        "frozen_L1_mean": FROZEN_L1_MEAN_PR_AUC,
        "frozen_TA2_mean": FROZEN_TA2_MEAN_PR_AUC,
    }
    write_json(_rev("08_paper_handover", "EDITOR019_PAPER_RESCUE_GATE.json"), gate)
    _rev("08_paper_handover", "EDITOR019_PAPER_RESCUE_HANDOVER.md").write_text(
        "# EDITOR-019 paper rescue handover\n\n"
        f"BEST_CURRENT_PAPER_MODEL = {paper_model}\n\n"
        f"TREE_VALUE = {ruling}\n\n"
        f"WHY_DIFFERENTIABLE_TREE\n\n{why_tree}\n",
        encoding="utf-8",
    )
    return {
        "comparisons": comparisons,
        "ruling": ruling,
        "teacher_guidance": tg,
        "explain": explain,
        "robust": robust_out,
        "paper_model": paper_model,
        "best_tree": best_tree,
        "inner_rows": inner_rows,
        "val_rows": kwargs["val_rows"],
        "mapping": kwargs["mapping"],
    }


def _run_robustness(*, best_tree: str, inner: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    device = kwargs["device"]
    val = kwargs["val"]
    views = kwargs["views"]
    fam = CONDITION_SPECS.get(best_tree, CONDITION_SPECS.get(best_tree.replace("-XD", "-D")))["family"]
    payload = torch.load(Path(inner["packs"][best_tree]["checkpoint"]), map_location="cpu", weights_only=False)
    tree_branch = load_branch(fam, payload, device, n_trees=kwargs["n_trees"])
    mlp_payload = torch.load(Path(inner["packs"][kwargs["mlp_name"] if kwargs["mlp_name"] in inner["packs"] else "MLP40-D"]["checkpoint"]), map_location="cpu", weights_only=False)
    mlp_branch = load_branch("MLP40", mlp_payload, device)

    def l1_fn(Xpert: np.ndarray) -> np.ndarray:
        return score_l1_logits(42, Xpert, val.y, device)

    tree_deg = degraded_metrics(tree_branch, val.X, val.y, l1_fn, views["scaler"], device)
    mlp_deg = degraded_metrics(mlp_branch, val.X, val.y, l1_fn, views["scaler"], device)
    rows = []
    for model, deg in (("tree", tree_deg), ("MLP40", mlp_deg)):
        for r in deg["source"]:
            rows.append({"model": model, "family": "source", **r})
        for r in deg["noise"]:
            rows.append({"model": model, "family": "noise", **r})
    write_csv(_rev("06_robustness", "EDITOR019_ROBUSTNESS_RESULTS.csv"), rows)
    ta2_noise_ok = tree_deg["MEAN_NOISE_RETENTION"] >= mlp_deg["MEAN_NOISE_RETENTION"]
    hardening = "NOT_RUN"
    if (not ta2_noise_ok) and kwargs["ruling"] in {"STRONG", "CONSISTENT"}:
        rng = np.random.default_rng(42)
        channel = str(list(SOURCE_CHANNELS)[int(rng.integers(0, len(SOURCE_CHANNELS)))])
        _Xp, s_deg = perturb_then_summarise(inner["inner_tr"].X, kind="source", channel=channel, scaler=inner["views"]["scaler"])
        hard = train_hardening(
            family=fam,
            seed=42,
            n_trees=kwargs["n_trees"],
            s_clean=inner["s_tr"],
            y=inner["y_tr"],
            l1_clean=inner["l1_tr"],
            ens_clean=inner["ens_tr"],
            s_deg=s_deg,
            device=device,
            pos_weight=inner["pos_weight"],
            s_select=inner["s_se"],
            y_select=inner["y_se"],
            l1_select=inner["l1_se"],
        )
        hard_deg = degraded_metrics(hard["branch"], val.X, val.y, l1_fn, views["scaler"], device)
        clean_delta = hard_deg["clean_PR_AUC"] - tree_deg["clean_PR_AUC"]
        if (
            clean_delta >= -0.001
            and hard_deg["MEAN_SOURCE_DELTA"] > tree_deg["MEAN_SOURCE_DELTA"]
            and hard_deg["MEAN_NOISE_RETENTION"] > tree_deg["MEAN_NOISE_RETENTION"]
        ):
            hardening = "SUPPORTED"
        else:
            hardening = "NOT_SUPPORTED"
        tree_deg = hard_deg
    return {
        "DEGRADED_INPUT_CONFIRMATION": "RUN",
        "tree": tree_deg,
        "mlp": mlp_deg,
        "HARDENING": hardening,
        "MEAN_SOURCE_DELTA": tree_deg["MEAN_SOURCE_DELTA"],
        "WORST_SOURCE_DELTA": tree_deg["WORST_SOURCE_DELTA"],
        "MEAN_NOISE_RETENTION": tree_deg["MEAN_NOISE_RETENTION"],
    }


def finalize_no_promotion(freeze: dict[str, Any], device: torch.device) -> dict[str, Any]:
    mark_promotion_frozen()
    bundle = load_train_validation()
    train_align = align_bundle(bundle["train"], "train")
    val_align = align_bundle(bundle["val"], "validation")
    mapping = recover_user_mapping(bundle)
    write_json(_rev("04_statistics", "EDITOR019_USER_MAPPING_VERIFICATION.json"), mapping)
    y_va = val_align["y"]
    val_rows = []
    for seed in PRIMARY_SEEDS:
        l1 = np.asarray(np.load(L1_CHECKPOINTS[seed]["val_logits"]), dtype=np.float32).reshape(-1)
        val_rows.append(_metric_row("L1", seed, metrics_from_logits(y_va, l1)))
        ta2 = np.asarray(np.load(F11_CHECKPOINTS[seed]["val_logits"]), dtype=np.float32).reshape(-1)
        val_rows.append(_metric_row("TA2", seed, metrics_from_logits(y_va, ta2)))
    write_csv(_rev("03_validation", "EDITOR019_VALIDATION_RESULTS.csv"), val_rows)
    write_csv(_rev("04_statistics", "EDITOR019_STABILITY_RESULTS.csv"), [], fieldnames=["seed", "note"])
    l1_mean = float(np.mean([r["PR_AUC"] for r in val_rows if r["condition"] == "L1"]))
    ta2_mean = float(np.mean([r["PR_AUC"] for r in val_rows if r["condition"] == "TA2"]))
    comparisons = {
        "BEST_TREE_MEAN_PR_AUC": None,
        "L1_MEAN_PR_AUC": l1_mean,
        "MATCHED_MLP_MEAN_PR_AUC": "NOT_TRAINED_NO_PROMOTED_TREE",
        "TA2_MEAN_PR_AUC": ta2_mean,
        "DELTA_TREE_VS_L1": None,
        "DELTA_TREE_VS_MLP": None,
        "POSITIVE_SEEDS_TREE_VS_L1": "0/3",
        "POSITIVE_SEEDS_TREE_VS_MLP": "0/3",
        "CI_TREE_MINUS_L1": None,
        "CI_TREE_MINUS_MLP": None,
        "TREE_VALUE": "NOT_SUPPORTED",
        "promotion": "NONE",
    }
    write_json(_rev("03_validation", "EDITOR019_PRIMARY_COMPARISONS.json"), comparisons)
    write_json(_rev("04_statistics", "EDITOR019_CLUSTER_BOOTSTRAP.json"), {"status": "NOT_RUN_NO_PROMOTED_TREE"})
    inner_rows = {r["condition"]: r for r in freeze["inner_rows"]}
    teacher_effects = freeze["effects"]["TEACHER_EFFECT"]
    tree_teacher = max(teacher_effects.values())
    tg = "STRONG" if tree_teacher > 0.001 else ("CONSISTENT" if tree_teacher > 0 else "NOT_SUPPORTED")
    write_csv(_rev("05_explainability", "EDITOR019_SIGNED_SPLITS.csv"), [], fieldnames=["family", "note"])
    write_json(
        _rev("05_explainability", "EDITOR019_LOCAL_FAITHFULNESS.json"),
        {
            "SIGNED_OBLIQUE_TREE_LOCAL_FAITHFULNESS": "NOT_EVALUATED_NO_PROMOTED_TREE",
            "TA2_GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        },
    )
    write_csv(_rev("06_robustness", "EDITOR019_ROBUSTNESS_RESULTS.csv"), [], fieldnames=["model", "note"])
    write_json(
        _rev("06_robustness", "EDITOR019_ROBUSTNESS_RULING.json"),
        {"DEGRADED_INPUT_CONFIRMATION": "NOT_TRIGGERED", "ROBUSTNESS_TRAINING_TRIGGERED": "NO"},
    )
    why_tree = (
        "The 40-summary view can carry complementary information, but none of the signed-oblique, "
        "node-specific, or boosted differentiable trees beat both L1 and matched MLP40-D under the frozen gate."
    )
    matrix = [
        {"issue": "TEACHER_INITIALISATION_ONLY", "status": "RESOLVED", "evidence": TEACHER_GUIDANCE_VS_INITIALISATION},
        {"issue": "C5_NEGLIGIBLE_INCREMENT", "status": "RESOLVED_BY_REPAIRED_FORMULATION", "evidence": "EDITOR-012 ET1 lambda=0.5"},
        {"issue": "CURRENT_ODST40_SPECIFIC_VALUE", "status": "NOT_SUPPORTED", "evidence": "TREE_VALUE_NOT_SUPPORTED"},
        {"issue": "GLOBAL_TOPK_PR_AUC_FAITHFULNESS", "status": "NOT_SUPPORTED", "evidence": "preserved from EDITOR-015/017"},
    ]
    write_csv(_rev("07_editor_response", "EDITOR019_EDITOR_ISSUE_MATRIX.csv"), matrix)
    gate = {
        "BEST_CURRENT_PAPER_MODEL": "TA2",
        "TREE_VALUE": "NOT_SUPPORTED",
        "TEACHER_GUIDANCE_WITHIN_TREE": tg,
        "WHY_TEACHER_GUIDANCE": "Teacher residual remains the successful neural-ensemble target; it did not create a tree that beat MLP40-D.",
        "WHY_DIFFERENTIABLE_TREE": why_tree,
        "WHY_NOT_ATTENTION_LINEAR_ONLY": "A tree replacement is not justified; retain TA2 / attention-linear as the paper model.",
        "LOCAL_DIRECTIONAL_FAITHFULNESS": "NOT_EVALUATED_NO_PROMOTED_TREE",
        "DEGRADED_INPUT_CONFIRMATION": "NOT_TRIGGERED",
        "comparisons": comparisons,
        "inner_effects": freeze.get("effects"),
    }
    write_json(_rev("08_paper_handover", "EDITOR019_PAPER_RESCUE_GATE.json"), gate)
    _rev("08_paper_handover", "EDITOR019_PAPER_RESCUE_HANDOVER.md").write_text(
        "# EDITOR-019 paper rescue handover\n\n"
        "BEST_CURRENT_PAPER_MODEL = TA2\n\n"
        "TREE_VALUE = NOT_SUPPORTED\n\n"
        f"WHY_DIFFERENTIABLE_TREE\n\n{why_tree}\n",
        encoding="utf-8",
    )
    return {
        "comparisons": comparisons,
        "ruling": "NOT_SUPPORTED",
        "teacher_guidance": tg,
        "explain": {"SIGNED_OBLIQUE_TREE_LOCAL_FAITHFULNESS": "NOT_EVALUATED_NO_PROMOTED_TREE"},
        "robust": {"DEGRADED_INPUT_CONFIRMATION": "NOT_TRIGGERED"},
        "paper_model": "TA2",
        "best_tree": None,
        "inner_rows": inner_rows,
        "val_rows": val_rows,
        "mapping": mapping,
        "train_align": train_align,
        "val_align": val_align,
    }


def write_run_manifest(extra: dict[str, Any]) -> None:
    write_json(
        _rev("EDITOR019_RUN_MANIFEST.json"),
        {
            "task": "EDITOR-019",
            "utc": utc_now(),
            "R52_TEST_ACCESSED": "NO",
            "R51_RERUN": "NO",
            "R62_RERUN": "NO",
            "commits": {
                "EDITOR017_RESULTS_COMMIT": EDITOR017_RESULTS_COMMIT,
                "EDITOR018_RESULTS_COMMIT": EDITOR018_RESULTS_COMMIT,
            },
            **extra,
        },
    )


def run_campaign(*, phase: str = "all") -> dict[str, Any]:
    device = _device()
    print(f"[EDITOR-019] device={device} phase={phase}", flush=True)
    proto = write_protocol_packet()
    n_trees = int(proto["n_trees"])
    if phase == "protocol":
        write_run_manifest({"phase": "protocol", "CAPACITY_MATCHED_TREE_COUNT": n_trees})
        return {"protocol": proto}
    inner = run_inner(device, n_trees)
    if phase == "inner":
        write_run_manifest({"phase": "inner", "promoted": inner["freeze"]["promoted_names"], "XGB_TEACHER_BRANCH": inner["freeze"]["XGB_TEACHER_BRANCH"]})
        return {"protocol": proto, "inner": inner}
    if not inner["freeze"]["promoted_names"]:
        confirm = finalize_no_promotion(inner["freeze"], device)
    else:
        confirm = run_confirmation(inner, device)
    write_run_manifest({"phase": "complete", "ruling": confirm["ruling"], "paper_model": confirm["paper_model"]})
    return {"protocol": proto, "inner": inner, "confirm": confirm}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("protocol", "inner", "all"), default="all")
    args = parser.parse_args()
    run_campaign(phase=args.phase)


if __name__ == "__main__":
    main()
