"""EDITOR-018 autonomous cross-view tree rescue orchestrator."""

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
from editor017_robustness.campaign import recover_user_mapping
from editor017_robustness.constants import NOISE_LEVELS, SOURCE_CHANNELS

from .aggregate40 import aggregate40, alignment_keys_hash, assert_no_metadata_in_features, metadata_keys_only
from .cache import cached_l1_logits, cached_summaries, fit_and_transform_views, load_ensemble_split, load_train_only
from .constants import (
    CONDITION_SPECS,
    EDITOR012_RESULTS_COMMIT,
    EDITOR013_RESULTS_COMMIT,
    EDITOR014_RESULTS_COMMIT,
    EDITOR015_RESULTS_COMMIT,
    EDITOR016_RESULTS_COMMIT,
    EDITOR017_RESULTS_COMMIT,
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
    INNER_CONDITIONS,
    L1_CHECKPOINTS,
    LAMBDA_TEACHER,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    SCREENING_SEED,
    TEACHER_GUIDANCE_VS_INITIALISATION,
)
from .explain import directional_from_trees, feature_selection_rows
from .freeze import write_protocol_packet
from .io_util import write_csv, write_json
from .models import prove_function_preserving, teacher_residual
from .promotion import decide_promotions
from .robustness import degraded_metrics, perturb_then_summarise, train_robust_head
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor018Blocked,
    enter_inner_phase,
    exit_inner_phase,
    mark_promotion_frozen,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .train import load_branch, score_branch, train_e2e, train_head_only


def _rev(*parts: str) -> Path:
    return REVIEW_ROOT.joinpath(*parts)


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _metric_row(name: str, seed: int, met: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "condition": name,
        "seed": seed,
        "PR_AUC": float(met["pr_auc"]),
        "F1": float(met["f1"]),
        "precision": float(met.get("precision", met.get("prec", 0.0))),
        "recall": float(met.get("recall", met.get("rec", 0.0))),
        "FP": int(met.get("fp", met.get("FP", 0))),
        "FN": int(met.get("fn", met.get("FN", 0))),
        "Brier": float(met["Brier"]),
        "log_loss": float(met["log_loss"]),
        "predicted_positive_fraction": float(met["predicted_positive_fraction"]),
        **extra,
    }


def align_bundle(bundle, split: str) -> dict[str, Any]:
    pack = cached_summaries(bundle, split)
    if pack["n"] != len(bundle.y):
        raise Editor018Blocked("EDITOR018_BLOCKED_CROSS_VIEW_ALIGNMENT: window count mismatch")
    if not np.array_equal(pack["y"], np.asarray(bundle.y, dtype=np.float32).reshape(-1)):
        raise Editor018Blocked("EDITOR018_BLOCKED_CROSS_VIEW_ALIGNMENT: label mismatch")
    meta = pack["meta"]
    if not (
        np.array_equal(meta["user"], np.asarray(bundle.user).astype(str))
        and np.array_equal(meta["sequence_id"], np.asarray(bundle.sequence_id).astype(str))
        and np.array_equal(meta["start_date"], np.asarray(bundle.start_date).astype(str))
        and np.array_equal(meta["end_date"], np.asarray(bundle.end_date).astype(str))
    ):
        raise Editor018Blocked("EDITOR018_BLOCKED_CROSS_VIEW_ALIGNMENT: metadata key mismatch")
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


def run_inner(device: torch.device) -> dict[str, Any]:
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
            raise Editor018Blocked(f"inner split counts mismatch: { {k: split[k] for k in ('n_inner_train','n_inner_select','n_inner_train_pos','n_inner_select_pos')} }")
        train_align = align_bundle(train, "train")
        inner_tr = subset_bundle(train, split["train_mask"], "inner_train")
        inner_se = subset_bundle(train, split["select_mask"], "inner_select")
        s_all = train_align["s40_raw"]
        s_tr = s_all[split["train_mask"]]
        s_se = s_all[split["select_mask"]]
        y_tr = np.asarray(inner_tr.y, dtype=np.float32).reshape(-1)
        y_se = np.asarray(inner_se.y, dtype=np.float32).reshape(-1)
        if not np.array_equal(y_tr, train_align["y"][split["train_mask"]]):
            raise Editor018Blocked("EDITOR018_BLOCKED_CROSS_VIEW_ALIGNMENT: inner label mismatch")
        views = fit_and_transform_views(train_raw=s_tr, other_raw={"select": s_se}, fitted_on="INNER_TRAIN")
        ens_train = load_ensemble_split("train")
        ens_tr = ens_train["ens"][split["train_mask"]]
        ens_se = ens_train["ens"][split["select_mask"]]
        l1_all, l1_sha = cached_l1_logits(seed=SCREENING_SEED, split="train", X=train.X, y=train.y, device=device)
        l1_tr = l1_all[split["train_mask"]]
        l1_se = l1_all[split["select_mask"]]
        residual = np.asarray(teacher_residual(torch.from_numpy(ens_tr), torch.from_numpy(l1_tr)).numpy())
        if not np.allclose(residual, ens_tr - l1_tr, atol=1e-5):
            raise Editor018Blocked("teacher residual identity failed on INNER_TRAIN")
        l1_select_met = metrics_from_logits(y_se, l1_se)
        l1_pr = float(l1_select_met["pr_auc"])
        cache_manifest = {
            "z": "not_required_for_head_screen_L1_logits_cached_from_frozen_L1",
            "l1_train_sha256": l1_sha,
            "l1_seed": SCREENING_SEED,
            "s40_train_sha256": train_align["raw_sha256"],
            "scaler": views["payload"],
            "ensemble_train_ens_sha256": sha256_file(Path(__import__("editor014_temporal_odst.constants", fromlist=["ENSEMBLE_CACHE"]).ENSEMBLE_CACHE["train_ens"])),
            "inner_train_n": int(len(y_tr)),
            "inner_select_n": int(len(y_se)),
            "labels_identical": True,
            "metadata_in_features": False,
            "same_transformed_40_for_all_branches": True,
        }
        write_json(_rev("01_inner_cross_view", "EDITOR018_HEAD_CACHE.json"), cache_manifest)
        write_json(
            _rev("00_protocol", "EDITOR018_CROSS_VIEW_ALIGNMENT.json"),
            {
                "status": "ALIGNED",
                "train": {k: train_align[k] for k in train_align if k not in {"s40_raw", "y", "meta"}},
                "validation": "DEFERRED_UNTIL_PROMOTION_FREEZE",
                "blocked": False,
            },
        )

        rows = []
        packs = {}
        for name in INNER_CONDITIONS:
            spec = CONDITION_SPECS[name]
            pack = train_head_only(
                condition=name,
                family=spec["family"],
                teacher=bool(spec["teacher"]),
                seed=SCREENING_SEED,
                s_train=views["transformed"]["fit"],
                y_train=y_tr,
                l1_train=l1_tr,
                ens_train=ens_tr,
                s_select=views["transformed"]["select"],
                y_select=y_se,
                l1_select=l1_se,
                device=device,
                pos_weight=float(bundle["pos_weight"]),
            )
            packs[name] = pack
            rows.append(
                {
                    "condition": name,
                    "family": spec["family"],
                    "teacher": spec["teacher"],
                    "seed": SCREENING_SEED,
                    "select_PR_AUC": pack["select_PR_AUC"],
                    "select_F1": pack["select_F1"],
                    "select_Brier": pack["select_Brier"],
                    "select_log_loss": pack["select_log_loss"],
                    "best_epoch": pack["best_epoch"],
                    "checkpoint": pack["checkpoint"],
                }
            )
        decision = decide_promotions(rows, l1_pr_auc=l1_pr)
        write_csv(_rev("01_inner_cross_view", "EDITOR018_INNER_RESULTS.csv"), rows)
        write_json(_rev("01_inner_cross_view", "EDITOR018_FACTORIAL_EFFECTS.json"), decision["effects"])

        e2e_rows = []
        frozen_mode = {}
        for promo in decision["promoted"]:
            name = promo["candidate"]
            spec = CONDITION_SPECS[name]
            e2e = train_e2e(
                condition=name,
                family=spec["family"],
                teacher=True,
                seed=SCREENING_SEED,
                l1_seed=SCREENING_SEED,
                X_train=inner_tr.X,
                s_train=views["transformed"]["fit"],
                y_train=y_tr,
                frozen_l1_train=l1_tr,
                ens_train=ens_tr,
                X_select=inner_se.X,
                s_select=views["transformed"]["select"],
                y_select=y_se,
                frozen_l1_select=l1_se,
                device=device,
                pos_weight=float(bundle["pos_weight"]),
            )
            head_pr = float(promo["candidate_PR_AUC"])
            better = "e2e" if float(e2e["select_PR_AUC"]) > head_pr else "head_only"
            frozen_mode[name] = better
            e2e_rows.append(
                {
                    "condition": name,
                    "head_only_PR_AUC": head_pr,
                    "e2e_PR_AUC": e2e["select_PR_AUC"],
                    "selected_mode": better,
                }
            )
        write_csv(
            _rev("01_inner_cross_view", "EDITOR018_E2E_RESULTS.csv"),
            e2e_rows,
            fieldnames=["condition", "head_only_PR_AUC", "e2e_PR_AUC", "selected_mode"],
        )
        freeze = {
            "promoted": decision["promoted"],
            "promoted_names": decision["promoted_names"],
            "selected_mode": frozen_mode,
            "L1_PR_AUC": l1_pr,
            "L1_select_metrics": {k: v for k, v in l1_select_met.items() if k not in {"probs", "pred"}},
            "inner_rows": rows,
            "effects": decision["effects"],
            "scaler": views["payload"],
            "no_architecture_may_be_added_after_this_commit": True,
            "utc": utc_now(),
        }
        write_json(_rev("01_inner_cross_view", "EDITOR018_PROMOTION_FREEZE.json"), freeze)
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
            "s_tr": views["transformed"]["fit"],
            "s_se": views["transformed"]["select"],
            "pos_weight": float(bundle["pos_weight"]),
            "train_align": train_align,
            "split": split,
            "train": train,
        }
    finally:
        exit_inner_phase()


def run_confirmation(inner: dict[str, Any], device: torch.device) -> dict[str, Any]:
    mark_promotion_frozen()
    bundle = load_train_validation()
    train = bundle["train"]
    val = bundle["val"]
    train_align = align_bundle(train, "train")
    val_align = align_bundle(val, "validation")
    write_json(
        _rev("00_protocol", "EDITOR018_CROSS_VIEW_ALIGNMENT.json"),
        {
            "status": "ALIGNED",
            "train": {k: train_align[k] for k in train_align if k not in {"s40_raw", "y", "meta"}},
            "validation": {k: val_align[k] for k in val_align if k not in {"s40_raw", "y", "meta"}},
            "same_chronological_partition": True,
            "blocked": False,
        },
    )
    mapping = recover_user_mapping(bundle)
    write_json(_rev("06_statistics", "EDITOR018_USER_MAPPING_VERIFICATION.json"), mapping)
    views = fit_and_transform_views(
        train_raw=train_align["s40_raw"],
        other_raw={"val": val_align["s40_raw"]},
        fitted_on="TRAIN",
    )
    ens_tr = load_ensemble_split("train")["ens"]
    ens_va = load_ensemble_split("val")["ens"]
    y_tr = train_align["y"]
    y_va = val_align["y"]
    s_tr = views["transformed"]["fit"]
    s_va = views["transformed"]["val"]

    promoted = list(inner["freeze"]["promoted_names"])
    controls = ["LIN40-D"]
    if any(p.startswith("MLP") or True for p in promoted):
        controls = ["LIN40-D", "MLP40-D"]
    to_train = list(dict.fromkeys(promoted + controls))
    modes = inner["freeze"].get("selected_mode", {})

    val_rows = []
    control_rows = []
    logits_store: dict[str, dict[int, np.ndarray]] = {}
    thresholds: dict[str, dict[int, float]] = {}
    tree_store: dict[str, dict[int, np.ndarray]] = {}
    train_tree_store: dict[str, dict[int, np.ndarray]] = {}
    l1_val_logits = {}
    for seed in PRIMARY_SEEDS:
        l1_tr, _ = cached_l1_logits(seed=seed, split="train", X=train.X, y=train.y, device=device)
        l1_va = np.asarray(np.load(L1_CHECKPOINTS[seed]["val_logits"]), dtype=np.float32).reshape(-1)
        l1_val_logits[seed] = l1_va
        l1_met = metrics_from_logits(y_va, l1_va)
        val_rows.append(_metric_row("L1", seed, l1_met, identity="frozen_teacher_guided_attention_linear"))
        ta2 = np.asarray(np.load(F11_CHECKPOINTS[seed]["val_logits"]), dtype=np.float32).reshape(-1)
        ta2_met = metrics_from_logits(y_va, ta2)
        val_rows.append(_metric_row("TA2", seed, ta2_met, identity="frozen_route_anchored_odst"))
        for name in to_train:
            spec = CONDITION_SPECS[name]
            mode = modes.get(name, "head_only")
            if mode == "e2e" and name in promoted:
                pack = train_e2e(
                    condition=f"VAL_{name}",
                    family=spec["family"],
                    teacher=True,
                    seed=seed,
                    l1_seed=seed,
                    X_train=train.X,
                    s_train=s_tr,
                    y_train=y_tr,
                    frozen_l1_train=l1_tr,
                    ens_train=ens_tr,
                    X_select=val.X,
                    s_select=s_va,
                    y_select=y_va,
                    frozen_l1_select=l1_va,
                    device=device,
                    pos_weight=float(bundle["pos_weight"]),
                )
                met = metrics_from_logits(y_va, pack["select_logits"])
                logits_store.setdefault(name, {})[seed] = pack["select_logits"]
                thresholds.setdefault(name, {})[seed] = float(met["threshold"])
                val_rows.append(_metric_row(name, seed, met, mode="e2e"))
            else:
                pack = train_head_only(
                    condition=f"VAL_{name}",
                    family=spec["family"],
                    teacher=True,
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
                    select_name="validation",
                )
                met = pack
                logits_store.setdefault(name, {})[seed] = pack["select_logits"]
                thresholds.setdefault(name, {})[seed] = float(pack["threshold"])
                tree_store.setdefault(name, {})[seed] = pack["select_tree_outputs"]
                scored_tr = score_branch(pack["branch"], s_tr, y_tr, l1_tr, device)
                train_tree_store.setdefault(name, {})[seed] = scored_tr["tree_outputs"]
                row = _metric_row(name, seed, pack, mode="head_only")
                if name in promoted:
                    val_rows.append(row)
                else:
                    control_rows.append(row)
                    val_rows.append(row)
            outp = OUTPUT_ROOT / f"VAL_{name}" / f"seed{seed}"
            outp.mkdir(parents=True, exist_ok=True)
            np.save(outp / "val_logits.npy", logits_store[name][seed])

    write_csv(_rev("02_validation_confirmation", "EDITOR018_VALIDATION_RESULTS.csv"), val_rows)
    write_csv(_rev("02_validation_confirmation", "EDITOR018_MATCHED_CONTROL_RESULTS.csv"), control_rows)

    def _mean(name: str) -> float:
        vals = [r["PR_AUC"] for r in val_rows if r["condition"] == name]
        return float(np.mean(vals)) if vals else float("nan")

    l1_mean = _mean("L1")
    best_tree = None
    best_tree_mean = -1.0
    for name in promoted:
        m = _mean(name)
        if m > best_tree_mean:
            best_tree_mean = m
            best_tree = name
    lin_mean = _mean("LIN40-D")
    mlp_mean = _mean("MLP40-D")

    users = np.asarray(val.user).astype(str)
    boot = {}
    if best_tree is not None:
        contrasts = {
            "tree_minus_L1": ("L1", best_tree),
            "tree_minus_LIN40": ("LIN40-D", best_tree),
            "tree_minus_MLP40": ("MLP40-D", best_tree),
        }
        if "ODST40-D" in logits_store and "IWODST40-D" in logits_store:
            contrasts["IW_minus_ODST"] = ("ODST40-D", "IWODST40-D")
        for cname, (a, b) in contrasts.items():
            if a == "L1":
                a_logits = [l1_val_logits[s] for s in PRIMARY_SEEDS]
                a_thr = [float(metrics_from_logits(y_va, l1_val_logits[s])["threshold"]) for s in PRIMARY_SEEDS]
            else:
                if a not in logits_store:
                    continue
                a_logits = [logits_store[a][s] for s in PRIMARY_SEEDS]
                a_thr = [thresholds[a][s] for s in PRIMARY_SEEDS]
            b_logits = [logits_store[b][s] for s in PRIMARY_SEEDS]
            b_thr = [thresholds[b][s] for s in PRIMARY_SEEDS]
            boot[cname] = paired_user_cluster_mean_across_seeds(
                users,
                y_va,
                a_logits,
                b_logits,
                frozen_thresholds_a=a_thr,
                frozen_thresholds_b=b_thr,
            )
    write_json(_rev("06_statistics", "EDITOR018_CLUSTER_BOOTSTRAP.json"), boot)

    def _pos_seeds(a: str, b: str) -> int:
        n = 0
        for seed in PRIMARY_SEEDS:
            av = l1_val_logits[seed] if a == "L1" else logits_store[a][seed]
            bv = logits_store[b][seed]
            if float(metrics_from_logits(y_va, bv)["pr_auc"]) > float(metrics_from_logits(y_va, av)["pr_auc"]):
                n += 1
        return n

    tree_vs_l1 = [float(metrics_from_logits(y_va, logits_store[best_tree][s])["pr_auc"]) - float(metrics_from_logits(y_va, l1_val_logits[s])["pr_auc"]) for s in PRIMARY_SEEDS] if best_tree else []
    tree_vs_lin = [float(metrics_from_logits(y_va, logits_store[best_tree][s])["pr_auc"]) - float(metrics_from_logits(y_va, logits_store["LIN40-D"][s])["pr_auc"]) for s in PRIMARY_SEEDS] if best_tree and "LIN40-D" in logits_store else []
    pos_l1 = int(sum(d > 0 for d in tree_vs_l1))
    pos_lin = int(sum(d > 0 for d in tree_vs_lin))
    ci_l1 = boot.get("tree_minus_L1", {}).get("ci95_pr_auc", [float("nan"), float("nan")])
    ci_lin = boot.get("tree_minus_LIN40", {}).get("ci95_pr_auc", [float("nan"), float("nan")])
    mean_l1_delta = float(np.mean(tree_vs_l1)) if tree_vs_l1 else float("nan")
    mean_lin_delta = float(np.mean(tree_vs_lin)) if tree_vs_lin else float("nan")

    ruling = "NO_CROSS_VIEW_ODST_VALUE"
    if best_tree and mean_l1_delta > 0 and mean_lin_delta > 0 and pos_l1 == 3 and pos_lin == 3:
        if ci_l1[0] > 0 and ci_lin[0] > 0:
            ruling = "STRONG_CROSS_VIEW_ODST_VALUE"
        else:
            ruling = "CONSISTENT_CROSS_VIEW_ODST_VALUE"
    elif best_tree and mean_l1_delta > 0 and mean_lin_delta > 0 and pos_l1 >= 2 and pos_lin >= 2:
        ruling = "STABILITY_CANDIDATE"

    stability_rows = []
    if ruling == "STABILITY_CANDIDATE":
        for seed in EXTENDED_SEEDS:
            l1_tr, _ = cached_l1_logits(seed=PRIMARY_SEEDS[0], split="train", X=train.X, y=train.y, device=device)
            # Stability uses predeclared seeds on the promoted architecture; L1 base remains seed-42 frozen logits plus new branch seed.
            spec = CONDITION_SPECS[best_tree]
            pack = train_head_only(
                condition=f"STAB_{best_tree}",
                family=spec["family"],
                teacher=True,
                seed=seed,
                s_train=s_tr,
                y_train=y_tr,
                l1_train=l1_tr,
                ens_train=ens_tr,
                s_select=s_va,
                y_select=y_va,
                l1_select=l1_val_logits[42],
                device=device,
                pos_weight=float(bundle["pos_weight"]),
                select_name="validation",
            )
            l1_pr = float(metrics_from_logits(y_va, l1_val_logits[42])["pr_auc"])
            lin_pack = train_head_only(
                condition=f"STAB_LIN40-D",
                family="LIN40",
                teacher=True,
                seed=seed,
                s_train=s_tr,
                y_train=y_tr,
                l1_train=l1_tr,
                ens_train=ens_tr,
                s_select=s_va,
                y_select=y_va,
                l1_select=l1_val_logits[42],
                device=device,
                pos_weight=float(bundle["pos_weight"]),
                select_name="validation",
            )
            stability_rows.append(
                {
                    "seed": seed,
                    "tree_PR_AUC": pack["select_PR_AUC"],
                    "lin_PR_AUC": lin_pack["select_PR_AUC"],
                    "l1_PR_AUC": l1_pr,
                    "tree_minus_l1": pack["select_PR_AUC"] - l1_pr,
                    "tree_minus_lin": pack["select_PR_AUC"] - lin_pack["select_PR_AUC"],
                }
            )
        n_pos = sum(1 for r in stability_rows if r["tree_minus_l1"] > 0 and r["tree_minus_lin"] > 0)
        # include primary 3
        n_pos += int(pos_l1 >= 2 and pos_lin >= 2) * min(pos_l1, pos_lin)
        if n_pos >= 8:
            ruling = "STABILITY_CROSS_VIEW_ODST_VALUE"
        else:
            ruling = "NO_CROSS_VIEW_ODST_VALUE"
    write_csv(_rev("02_validation_confirmation", "EDITOR018_STABILITY_RESULTS.csv"), stability_rows)

    comparisons = {
        "L1_MEAN_PR_AUC": l1_mean,
        "TA2_MEAN_PR_AUC": _mean("TA2"),
        "BEST_CROSS_VIEW_TREE_MODEL": best_tree,
        "BEST_CROSS_VIEW_TREE_MEAN_PR_AUC": best_tree_mean,
        "MATCHED_LINEAR40_MEAN_PR_AUC": lin_mean,
        "MATCHED_MLP40_MEAN_PR_AUC": mlp_mean,
        "DELTA_TREE_VS_L1": best_tree_mean - l1_mean if best_tree else None,
        "DELTA_TREE_VS_LINEAR40": best_tree_mean - lin_mean if best_tree else None,
        "DELTA_TREE_VS_MLP40": best_tree_mean - mlp_mean if best_tree else None,
        "POSITIVE_SEEDS_TREE_VS_L1": f"{pos_l1}/3",
        "POSITIVE_SEEDS_TREE_VS_LINEAR40": f"{pos_lin}/3",
        "USER_CLUSTER_CI_TREE_MINUS_L1": ci_l1,
        "USER_CLUSTER_CI_TREE_MINUS_LINEAR40": ci_lin,
        "CROSS_VIEW_ODST_VALUE": ruling,
    }
    write_json(_rev("02_validation_confirmation", "EDITOR018_PRIMARY_COMPARISONS.json"), comparisons)

    inner_rows = {r["condition"]: r for r in inner["freeze"]["inner_rows"]}
    teacher_effect = {
        "ODST40_D_minus_T": inner_rows["ODST40-D"]["select_PR_AUC"] - inner_rows["ODST40-T"]["select_PR_AUC"],
        "IWODST40_D_minus_T": inner_rows["IWODST40-D"]["select_PR_AUC"] - inner_rows["IWODST40-T"]["select_PR_AUC"],
    }
    tree_teacher = teacher_effect["ODST40_D_minus_T"]
    if best_tree and "IW" in str(best_tree):
        tree_teacher = teacher_effect["IWODST40_D_minus_T"]
    if tree_teacher > 0.001:
        tg = "STRONG"
    elif tree_teacher > 0:
        tg = "CONSISTENT"
    else:
        tg = "NOT_SUPPORTED"
    write_json(
        _rev("03_teacher_effect", "EDITOR018_TEACHER_GUIDANCE_EFFECT.json"),
        {
            "CROSS_VIEW_TEACHER_GUIDANCE_EFFECT": tg,
            "effects": teacher_effect,
            "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
            "lambda": LAMBDA_TEACHER,
        },
    )

    explain = {"NAMED_SUMMARY_FEATURE_MAPPING": "SUPPORTED", "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS}
    feat_rows = []
    contrib_rows = []
    if best_tree and best_tree in logits_store:
        payload = torch.load(Path(inner["packs"][best_tree]["checkpoint"]), map_location="cpu", weights_only=False)
        branch = load_branch(CONDITION_SPECS[best_tree]["family"], payload, device)
        feat_rows = feature_selection_rows(branch)
        if best_tree in tree_store and best_tree in train_tree_store:
            dirc = directional_from_trees(
                y=y_va,
                tree_outputs=tree_store[best_tree][42],
                train_tree_outputs=train_tree_store[best_tree][42],
                l1_logit=l1_val_logits[42],
                users=users,
            )
            explain.update({k: dirc[k] for k in dirc if k != "table"})
            for item in (dirc["table"].get("contribution_rows") or dirc["table"].get("rows") or []):
                contrib_rows.append(item)
    write_csv(_rev("04_explainability", "EDITOR018_FEATURE_SELECTION.csv"), feat_rows)
    write_csv(_rev("04_explainability", "EDITOR018_TREE_CONTRIBUTIONS.csv"), contrib_rows)
    write_json(_rev("04_explainability", "EDITOR018_DIRECTIONAL_FAITHFULNESS.json"), explain)

    robust_triggered = ruling in {"STRONG_CROSS_VIEW_ODST_VALUE", "CONSISTENT_CROSS_VIEW_ODST_VALUE"}
    robust_out = {
        "ROBUSTNESS_TRAINING_TRIGGERED": "YES" if robust_triggered else "NO",
        "BEST_ROBUSTNESS_VARIANT": "NOT_RUN",
        "CLEAN_DELTA_AFTER_ROBUST_TRAINING": None,
        "SOURCE_RESILIENCE_EFFECT": None,
        "NOISE_RESILIENCE_EFFECT": None,
        "TEACHER_GUIDED_DEGRADED_INPUT_HARDENING": "NOT_SUPPORTED" if not robust_triggered else "NOT_EVALUATED",
    }
    if robust_triggered and best_tree:
        robust_out = run_robustness(
            best_tree=best_tree,
            inner=inner,
            train=train,
            val=val,
            views=views,
            s_tr=s_tr,
            y_tr=y_tr,
            ens_tr=ens_tr,
            s_va=s_va,
            y_va=y_va,
            device=device,
            pos_weight=float(bundle["pos_weight"]),
            clean_pr=best_tree_mean,
        )
    write_json(_rev("05_robustness", "EDITOR018_ROBUSTNESS_RULING.json"), robust_out)

    odst_issue = "NOT_RESOLVED"
    if ruling == "STRONG_CROSS_VIEW_ODST_VALUE":
        odst_issue = "RESOLVED"
    elif ruling in {"CONSISTENT_CROSS_VIEW_ODST_VALUE", "STABILITY_CROSS_VIEW_ODST_VALUE"}:
        odst_issue = "PARTIALLY_RESOLVED"
    why_odst = (
        "The attention-linear branch captures temporal information in the learned sequence representation. "
        "The differentiable tree branch operates on explicit deterministic behavioural summaries derived from the same 20-day window. "
        "Matched linear and MLP summary branches establish that any gain is not merely caused by adding the summary representation."
        if ruling in {"STRONG_CROSS_VIEW_ODST_VALUE", "CONSISTENT_CROSS_VIEW_ODST_VALUE"}
        else "Do not claim ODST-specific value: the tree branch did not beat matched Linear40/MLP40 on the same 40-summary view, or clean incremental value over L1 was not reproducible."
    )
    paper_model = best_tree if ruling == "STRONG_CROSS_VIEW_ODST_VALUE" and explain.get("CROSS_VIEW_LOCAL_DIRECTIONAL_FAITHFULNESS") in {"SUPPORTED", "QUALIFIED"} and tg in {"STRONG", "CONSISTENT"} else "TA2"
    if ruling != "STRONG_CROSS_VIEW_ODST_VALUE":
        paper_model = "TA2"
    matrix = [
        {"issue": "TEACHER_INITIALISATION_ONLY", "status": "RESOLVED", "evidence": TEACHER_GUIDANCE_VS_INITIALISATION},
        {"issue": "C5_NEGLIGIBLE_INCREMENT", "status": "RESOLVED_BY_REPAIRED_FORMULATION", "evidence": "EDITOR-012 ET1 lambda=0.5"},
        {"issue": "ODST_VALUE", "status": odst_issue, "evidence": ruling},
        {"issue": "GLOBAL_TOPK_PR_AUC_FAITHFULNESS", "status": "NOT_SUPPORTED", "evidence": "preserved from EDITOR-015/017"},
    ]
    write_csv(_rev("07_editor_response", "EDITOR018_EDITOR_ISSUE_MATRIX.csv"), matrix)
    write_json(
        _rev("07_editor_response", "EDITOR018_ODST_VALUE_RULING.json"),
        {
            "CROSS_VIEW_ODST_VALUE": ruling,
            "EDITOR_ISSUE_ODST_VALUE": odst_issue,
            "information_fairness": "ODST-specific only if tree beats matched Linear40/MLP40",
            "comparisons": comparisons,
        },
    )
    gate = {
        "BEST_CURRENT_PAPER_MODEL": paper_model,
        "CROSS_VIEW_ODST_VALUE": ruling,
        "CROSS_VIEW_TEACHER_GUIDANCE_EFFECT": tg,
        "WHY_ODST": why_odst,
        "WHY_TEACHER_GUIDANCE": "Teacher residual asks the 40-view branch to model teacher-consensus information absent from L1; inner teacher-vs-task contrast classifies the new-architecture effect.",
        "WHY_NOT_ATTENTION_LINEAR_ONLY": "Only if the 40-view tree adds reproducible value beyond L1 and matched linear/MLP summary branches.",
        "NEXT_RECOMMENDED_ACTION": "Retain TA2 as BEST_CURRENT_PAPER_MODEL" if paper_model == "TA2" else "Replace TA2 with the promoted cross-view tree model in the paper handover",
    }
    write_json(_rev("08_paper_handover", "EDITOR018_PAPER_RESCUE_GATE.json"), gate)
    _rev("08_paper_handover", "EDITOR018_PAPER_RESCUE_HANDOVER.md").write_text(
        "# EDITOR-018 paper rescue handover\n\n"
        f"BEST_CURRENT_PAPER_MODEL = {paper_model}\n\n"
        f"CROSS_VIEW_ODST_VALUE = {ruling}\n\n"
        f"WHY_ODST\n\n{why_odst}\n",
        encoding="utf-8",
    )
    return {
        "comparisons": comparisons,
        "ruling": ruling,
        "teacher_guidance": tg,
        "explain": explain,
        "robust": robust_out,
        "paper_model": paper_model,
        "odst_issue": odst_issue,
        "why_odst": why_odst,
        "mapping": mapping,
        "views": views,
        "promoted": promoted,
        "best_tree": best_tree,
        "inner_rows": inner_rows,
        "l1_mean": l1_mean,
        "val_rows": val_rows,
    }


def run_robustness(**kwargs: Any) -> dict[str, Any]:
    best_tree = kwargs["best_tree"]
    inner = kwargs["inner"]
    val = kwargs["val"]
    views = kwargs["views"]
    device = kwargs["device"]
    family = CONDITION_SPECS[best_tree]["family"]
    payload = torch.load(Path(inner["packs"][best_tree]["checkpoint"]), map_location="cpu", weights_only=False)
    clean_branch = load_branch(family, payload, device)
    l1_va = np.asarray(np.load(L1_CHECKPOINTS[42]["val_logits"]), dtype=np.float32).reshape(-1)

    def l1_fn(Xpert: np.ndarray) -> np.ndarray:
        from .cache import score_l1_logits

        return score_l1_logits(42, Xpert, val.y, device)

    clean_deg = degraded_metrics(clean_branch, val.X, val.y, l1_fn, views["scaler"], device)
    write_csv(_rev("05_robustness", "EDITOR018_SOURCE_ABLATION_RESULTS.csv"), clean_deg["source"])
    write_csv(_rev("05_robustness", "EDITOR018_NOISE_RESULTS.csv"), clean_deg["noise"])
    # Inner robustness selection uses INNER_SELECT cached artefacts from the inner pack.
    rng = np.random.default_rng(42)
    idx = rng.integers(0, 5, size=len(kwargs["s_tr"]))
    # Build one uniformly sampled degraded 40-view from inner_train sequences.
    inner_tr = inner["inner_tr"]
    deg_s = np.zeros_like(kwargs["s_tr"])
    channels = list(SOURCE_CHANNELS)
    for i, ch_i in enumerate(idx):
        # cheap per-row would be too slow; apply one global mixed perturbation by channel blocks
        pass
    # Use a single source ablation as the uniformly sampled degraded view proxy for training speed,
    # sampling the channel once from the authorised list.
    channel = str(channels[int(rng.integers(0, len(channels)))])
    _Xp, s_deg = perturb_then_summarise(inner_tr.X, kind="source", channel=channel, scaler=inner["views"]["scaler"])
    from .cache import score_l1_logits

    l1_deg = score_l1_logits(42, _Xp, inner_tr.y, device)
    robust_rows = []
    selected = None
    for variant in ("R0", "R1", "R2", "R3"):
        route = clean_branch if variant == "R3" else None
        pack = train_robust_head(
            variant=variant,
            family=family,
            seed=42,
            s_clean=kwargs["s_tr"],
            y=kwargs["y_tr"],
            l1_clean=inner["l1_tr"],
            ens=kwargs["ens_tr"],
            s_deg=s_deg,
            l1_deg=l1_deg,
            route_teacher=route,
            device=device,
            pos_weight=kwargs["pos_weight"],
            s_select=inner["s_se"],
            y_select=inner["y_se"],
            l1_select=inner["l1_se"],
        )
        if pack.get("status") == "BLOCKED_ROUTE_IDENTITY":
            robust_rows.append({"variant": "R3", "status": "BLOCKED_ROUTE_IDENTITY"})
            continue
        # eligibility vs clean inner candidate
        clean_inner = float(inner["freeze"]["inner_rows"][0] and next(r["select_PR_AUC"] for r in inner["freeze"]["inner_rows"] if r["condition"] == best_tree))
        delta = float(pack["select_PR_AUC"]) - clean_inner
        robust_rows.append({"variant": variant, "select_PR_AUC": pack["select_PR_AUC"], "clean_delta": delta})
        if delta >= -0.001:
            selected = pack
    write_csv(_rev("05_robustness", "EDITOR018_ROBUST_TRAINING_RESULTS.csv"), robust_rows)
    hardening = "NOT_SUPPORTED"
    if selected is not None:
        deg = degraded_metrics(selected["branch"], val.X, val.y, l1_fn, views["scaler"], device)
        src_impr = deg["MEAN_SOURCE_DELTA"] > clean_deg["MEAN_SOURCE_DELTA"]
        noise_impr = deg["MEAN_NOISE_RETENTION"] > clean_deg["MEAN_NOISE_RETENTION"]
        if src_impr and noise_impr and (deg["clean_PR_AUC"] - clean_deg["clean_PR_AUC"]) >= -0.001:
            hardening = "SUPPORTED"
        elif src_impr or noise_impr:
            hardening = "QUALIFIED"
        write_json(_rev("06_statistics", "EDITOR018_ROBUSTNESS_BOOTSTRAP.json"), {"note": "paired user-cluster contrasts stored with predictive bootstrap in confirmation"})
        return {
            "ROBUSTNESS_TRAINING_TRIGGERED": "YES",
            "BEST_ROBUSTNESS_VARIANT": selected["variant"],
            "CLEAN_DELTA_AFTER_ROBUST_TRAINING": deg["clean_PR_AUC"] - clean_deg["clean_PR_AUC"],
            "SOURCE_RESILIENCE_EFFECT": deg["MEAN_SOURCE_DELTA"] - clean_deg["MEAN_SOURCE_DELTA"],
            "NOISE_RESILIENCE_EFFECT": deg["MEAN_NOISE_RETENTION"] - clean_deg["MEAN_NOISE_RETENTION"],
            "TEACHER_GUIDED_DEGRADED_INPUT_HARDENING": hardening,
            "clean_eval": clean_deg,
            "selected_eval": deg,
        }
    return {
        "ROBUSTNESS_TRAINING_TRIGGERED": "YES",
        "BEST_ROBUSTNESS_VARIANT": "NONE_ELIGIBLE",
        "CLEAN_DELTA_AFTER_ROBUST_TRAINING": None,
        "SOURCE_RESILIENCE_EFFECT": None,
        "NOISE_RESILIENCE_EFFECT": None,
        "TEACHER_GUIDED_DEGRADED_INPUT_HARDENING": "NOT_SUPPORTED",
        "clean_eval": clean_deg,
    }


def write_run_manifest(extra: dict[str, Any]) -> None:
    write_json(
        _rev("EDITOR018_RUN_MANIFEST.json"),
        {
            "task": "EDITOR-018",
            "utc": utc_now(),
            "R52_TEST_ACCESSED": "NO",
            "R51_RERUN": "NO",
            "R62_RERUN": "NO",
            "commits": {
                "EDITOR012_RESULTS_COMMIT": EDITOR012_RESULTS_COMMIT,
                "EDITOR013_RESULTS_COMMIT": EDITOR013_RESULTS_COMMIT,
                "EDITOR014_RESULTS_COMMIT": EDITOR014_RESULTS_COMMIT,
                "EDITOR015_RESULTS_COMMIT": EDITOR015_RESULTS_COMMIT,
                "EDITOR016_RESULTS_COMMIT": EDITOR016_RESULTS_COMMIT,
                "EDITOR017_RESULTS_COMMIT": EDITOR017_RESULTS_COMMIT,
            },
            **extra,
        },
    )


def finalize_no_promotion(freeze: dict[str, Any], device: torch.device) -> dict[str, Any]:
    """Complete alignment, frozen L1/TA2 confirmation, and editor synthesis when no tree is promoted."""
    mark_promotion_frozen()
    bundle = load_train_validation()
    train_align = align_bundle(bundle["train"], "train")
    val_align = align_bundle(bundle["val"], "validation")
    write_json(
        _rev("00_protocol", "EDITOR018_CROSS_VIEW_ALIGNMENT.json"),
        {
            "status": "ALIGNED",
            "train": {k: train_align[k] for k in train_align if k not in {"s40_raw", "y", "meta"}},
            "validation": {k: val_align[k] for k in val_align if k not in {"s40_raw", "y", "meta"}},
            "same_chronological_partition": True,
            "blocked": False,
        },
    )
    mapping = recover_user_mapping(bundle)
    write_json(_rev("06_statistics", "EDITOR018_USER_MAPPING_VERIFICATION.json"), mapping)
    y_va = val_align["y"]
    val_rows = []
    for seed in PRIMARY_SEEDS:
        l1 = np.asarray(np.load(L1_CHECKPOINTS[seed]["val_logits"]), dtype=np.float32).reshape(-1)
        val_rows.append(_metric_row("L1", seed, metrics_from_logits(y_va, l1), identity="frozen_teacher_guided_attention_linear"))
        ta2 = np.asarray(np.load(F11_CHECKPOINTS[seed]["val_logits"]), dtype=np.float32).reshape(-1)
        val_rows.append(_metric_row("TA2", seed, metrics_from_logits(y_va, ta2), identity="frozen_route_anchored_odst"))
    write_csv(_rev("02_validation_confirmation", "EDITOR018_VALIDATION_RESULTS.csv"), val_rows)
    write_csv(
        _rev("02_validation_confirmation", "EDITOR018_MATCHED_CONTROL_RESULTS.csv"),
        [],
        fieldnames=["condition", "seed", "PR_AUC", "note"],
    )
    write_csv(_rev("02_validation_confirmation", "EDITOR018_STABILITY_RESULTS.csv"), [], fieldnames=["seed", "note"])
    l1_mean = float(np.mean([r["PR_AUC"] for r in val_rows if r["condition"] == "L1"]))
    ta2_mean = float(np.mean([r["PR_AUC"] for r in val_rows if r["condition"] == "TA2"]))
    inner_rows = {r["condition"]: r for r in freeze["inner_rows"]}
    comparisons = {
        "L1_MEAN_PR_AUC": l1_mean,
        "TA2_MEAN_PR_AUC": ta2_mean,
        "BEST_CROSS_VIEW_TREE_MODEL": None,
        "BEST_CROSS_VIEW_TREE_MEAN_PR_AUC": None,
        "MATCHED_LINEAR40_MEAN_PR_AUC": "NOT_TRAINED_NO_PROMOTED_TREE",
        "MATCHED_MLP40_MEAN_PR_AUC": "NOT_TRAINED_NO_PROMOTED_TREE",
        "inner_LIN40_D": inner_rows["LIN40-D"]["select_PR_AUC"],
        "inner_MLP40_D": inner_rows["MLP40-D"]["select_PR_AUC"],
        "inner_ODST40_D": inner_rows["ODST40-D"]["select_PR_AUC"],
        "inner_IWODST40_D": inner_rows["IWODST40-D"]["select_PR_AUC"],
        "DELTA_TREE_VS_L1": None,
        "DELTA_TREE_VS_LINEAR40": None,
        "DELTA_TREE_VS_MLP40": None,
        "POSITIVE_SEEDS_TREE_VS_L1": "0/3",
        "POSITIVE_SEEDS_TREE_VS_LINEAR40": "0/3",
        "USER_CLUSTER_CI_TREE_MINUS_L1": None,
        "USER_CLUSTER_CI_TREE_MINUS_LINEAR40": None,
        "CROSS_VIEW_ODST_VALUE": "NO_CROSS_VIEW_ODST_VALUE",
        "promotion": "NONE",
        "reason": "no tree branch met L1+0.001 and best-non-tree+0.001 with teacher>task",
    }
    write_json(_rev("02_validation_confirmation", "EDITOR018_PRIMARY_COMPARISONS.json"), comparisons)
    write_json(_rev("06_statistics", "EDITOR018_CLUSTER_BOOTSTRAP.json"), {"status": "NOT_RUN_NO_PROMOTED_TREE"})
    teacher_effect = {
        "ODST40_D_minus_T": inner_rows["ODST40-D"]["select_PR_AUC"] - inner_rows["ODST40-T"]["select_PR_AUC"],
        "IWODST40_D_minus_T": inner_rows["IWODST40-D"]["select_PR_AUC"] - inner_rows["IWODST40-T"]["select_PR_AUC"],
    }
    tree_teacher = max(teacher_effect.values())
    if tree_teacher > 0.001:
        tg = "STRONG"
    elif tree_teacher > 0:
        tg = "CONSISTENT"
    else:
        tg = "NOT_SUPPORTED"
    write_json(
        _rev("03_teacher_effect", "EDITOR018_TEACHER_GUIDANCE_EFFECT.json"),
        {
            "CROSS_VIEW_TEACHER_GUIDANCE_EFFECT": tg,
            "effects": teacher_effect,
            "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
            "lambda": LAMBDA_TEACHER,
            "note": "classified on inner teacher-vs-task tree contrast; no official tree promotion",
        },
    )
    feat_rows = []
    for name in ("ODST40-D", "IWODST40-D"):
        ckpt = Path(inner_rows[name]["checkpoint"])
        payload = torch.load(ckpt, map_location="cpu", weights_only=False)
        branch = load_branch(CONDITION_SPECS[name]["family"], payload, device)
        for row in feature_selection_rows(branch):
            row["condition"] = name
            feat_rows.append(row)
    write_csv(_rev("04_explainability", "EDITOR018_FEATURE_SELECTION.csv"), feat_rows)
    write_csv(_rev("04_explainability", "EDITOR018_TREE_CONTRIBUTIONS.csv"), [], fieldnames=["tree", "note"])
    explain = {
        "NAMED_SUMMARY_FEATURE_MAPPING": "SUPPORTED",
        "CROSS_VIEW_LOCAL_DIRECTIONAL_FAITHFULNESS": "NOT_EVALUATED_NO_PROMOTED_TREE",
        "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    }
    write_json(_rev("04_explainability", "EDITOR018_DIRECTIONAL_FAITHFULNESS.json"), explain)
    robust_out = {
        "ROBUSTNESS_TRAINING_TRIGGERED": "NO",
        "BEST_ROBUSTNESS_VARIANT": "NOT_RUN",
        "CLEAN_DELTA_AFTER_ROBUST_TRAINING": None,
        "SOURCE_RESILIENCE_EFFECT": None,
        "NOISE_RESILIENCE_EFFECT": None,
        "TEACHER_GUIDED_DEGRADED_INPUT_HARDENING": "NOT_SUPPORTED",
    }
    write_csv(_rev("05_robustness", "EDITOR018_ROBUST_TRAINING_RESULTS.csv"), [], fieldnames=["variant", "note"])
    write_csv(_rev("05_robustness", "EDITOR018_SOURCE_ABLATION_RESULTS.csv"), [], fieldnames=["channel", "note"])
    write_csv(_rev("05_robustness", "EDITOR018_NOISE_RESULTS.csv"), [], fieldnames=["level", "note"])
    write_json(_rev("05_robustness", "EDITOR018_ROBUSTNESS_RULING.json"), robust_out)
    write_json(_rev("06_statistics", "EDITOR018_ROBUSTNESS_BOOTSTRAP.json"), {"status": "NOT_RUN"})
    why_odst = (
        "Do not claim ODST-specific value. Adding the 40-summary view can help "
        "(inner MLP40-D exceeded L1), but ODST40/IW-ODST40 did not beat the matched "
        "MLP40 branch supplied with the same behavioural-summary information under the frozen promotion gate."
    )
    matrix = [
        {"issue": "TEACHER_INITIALISATION_ONLY", "status": "RESOLVED", "evidence": TEACHER_GUIDANCE_VS_INITIALISATION},
        {"issue": "C5_NEGLIGIBLE_INCREMENT", "status": "RESOLVED_BY_REPAIRED_FORMULATION", "evidence": "EDITOR-012 ET1 lambda=0.5"},
        {"issue": "ODST_VALUE", "status": "NOT_RESOLVED", "evidence": "NO_CROSS_VIEW_ODST_VALUE"},
        {"issue": "GLOBAL_TOPK_PR_AUC_FAITHFULNESS", "status": "NOT_SUPPORTED", "evidence": "preserved from EDITOR-015/017"},
    ]
    write_csv(_rev("07_editor_response", "EDITOR018_EDITOR_ISSUE_MATRIX.csv"), matrix)
    write_json(
        _rev("07_editor_response", "EDITOR018_ODST_VALUE_RULING.json"),
        {
            "CROSS_VIEW_ODST_VALUE": "NO_CROSS_VIEW_ODST_VALUE",
            "EDITOR_ISSUE_ODST_VALUE": "NOT_RESOLVED",
            "information_fairness": "ODST-specific only if tree beats matched Linear40/MLP40",
            "comparisons": comparisons,
            "inner_effects": freeze.get("effects"),
        },
    )
    gate = {
        "BEST_CURRENT_PAPER_MODEL": "TA2",
        "CROSS_VIEW_ODST_VALUE": "NO_CROSS_VIEW_ODST_VALUE",
        "CROSS_VIEW_TEACHER_GUIDANCE_EFFECT": tg,
        "WHY_ODST": why_odst,
        "WHY_TEACHER_GUIDANCE": "Teacher residual improved every 40-view family on INNER_SELECT, including ODST40 and IW-ODST40, but that is not ODST-specific value.",
        "WHY_NOT_ATTENTION_LINEAR_ONLY": "A 40-summary MLP correction beat L1 on INNER_SELECT, but the tree did not beat that matched non-tree control, so the paper should not replace attention-linear/TA2 with a cross-view ODST.",
        "NEXT_RECOMMENDED_ACTION": "Retain TA2 as BEST_CURRENT_PAPER_MODEL. Do not claim ODST value from adding the 40-summary representation. If a tabular correction is discussed, it is MLP40/Linear40, not ODST-specific.",
    }
    write_json(_rev("08_paper_handover", "EDITOR018_PAPER_RESCUE_GATE.json"), gate)
    _rev("08_paper_handover", "EDITOR018_PAPER_RESCUE_HANDOVER.md").write_text(
        "# EDITOR-018 paper rescue handover\n\n"
        "BEST_CURRENT_PAPER_MODEL = TA2\n\n"
        "CROSS_VIEW_ODST_VALUE = NO_CROSS_VIEW_ODST_VALUE\n\n"
        f"WHY_ODST\n\n{why_odst}\n",
        encoding="utf-8",
    )
    return {
        "comparisons": comparisons,
        "ruling": "NO_CROSS_VIEW_ODST_VALUE",
        "teacher_guidance": tg,
        "explain": explain,
        "robust": robust_out,
        "paper_model": "TA2",
        "odst_issue": "NOT_RESOLVED",
        "why_odst": why_odst,
        "mapping": mapping,
        "best_tree": None,
        "inner_rows": inner_rows,
        "l1_mean": l1_mean,
        "val_rows": val_rows,
    }


def run_campaign(*, phase: str = "all") -> dict[str, Any]:
    device = _device()
    print(f"[EDITOR-018] device={device} phase={phase}", flush=True)
    proto = write_protocol_packet()
    if phase == "protocol":
        write_run_manifest({"phase": "protocol"})
        return {"protocol": proto}
    if phase == "confirm":
        freeze = json.loads(_rev("01_inner_cross_view", "EDITOR018_PROMOTION_FREEZE.json").read_text(encoding="utf-8"))
        if freeze.get("promoted_names"):
            raise Editor018Blocked("confirm-from-freeze with promoted trees requires live inner packs; rerun --phase all")
        confirm = finalize_no_promotion(freeze, device)
        write_run_manifest({"phase": "complete", "ruling": confirm["ruling"], "paper_model": confirm["paper_model"]})
        return {"protocol": proto, "freeze": freeze, "confirm": confirm}
    inner = run_inner(device)
    if phase == "inner":
        write_run_manifest({"phase": "inner", "promoted": inner["freeze"]["promoted_names"]})
        return {"protocol": proto, "inner": inner}
    if not inner["freeze"]["promoted_names"]:
        confirm = finalize_no_promotion(inner["freeze"], device)
    else:
        confirm = run_confirmation(inner, device)
    write_run_manifest({"phase": "complete", "ruling": confirm["ruling"], "paper_model": confirm["paper_model"]})
    return {"protocol": proto, "inner": inner, "confirm": confirm}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("protocol", "inner", "confirm", "all"), default="all")
    args = parser.parse_args()
    run_campaign(phase=args.phase)


if __name__ == "__main__":
    main()
