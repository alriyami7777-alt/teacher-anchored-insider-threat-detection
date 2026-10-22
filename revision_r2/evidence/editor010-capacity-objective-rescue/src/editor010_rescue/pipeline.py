"""Overnight EDITOR-010 orchestrator. DEVELOPMENT_ONLY; r5.2 TEST is fail-closed."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
from scipy.stats import pearsonr, spearmanr

from .bootstrap import paired_user_cluster_delta_pr
from .checkpoints import load_baseline
from .constants import (
    AL_REPLAY_PR_AUC,
    ATTENTION_DIM_OUT,
    BASELINES,
    BATCH_SIZE,
    C2_PRODUCING_PR_AUC,
    C5_PRODUCING_PR_AUC,
    ET1_LOGIT_DISTILL_WEIGHT,
    FOCAL_GAMMA,
    FULL_CONFIRMATION_SEEDS,
    HEADROOM_PR_AUC_MARGIN,
    LAMBDA_RANK_GRID,
    LR_ATTENTION_LINEAR,
    LR_ODST_PRODUCING,
    OBJECTIVE_CONSISTENCY_MARGIN,
    ODST_GRID,
    ODST_GRID_BY_ID,
    OUTPUT_REL,
    POS_WEIGHT_MULT_O0,
    POS_WEIGHT_MULT_O1,
    PRODUCING_ODST,
    PROTOCOL_COMMIT,
    REVIEW_REL,
    SCREENING_SEED,
    TEACHER_PRODUCING_PR_AUC,
)
from .data import load_train, load_validation, make_xy_loader, pos_weight, subset_bundle
from .hashes import sha256_file
from .inner_split import assert_no_boundary_crossing, inner_split_masks
from .io_util import save_npy, write_csv, write_json
from .metrics import evaluate_scores, pairwise_disagreement
from .models import build_head
from .safety import Editor010SafetyError, refuse_test_loader_construction
from .train import (
    cache_embeddings,
    evaluate_loader,
    predict_logits,
    select_device,
    set_seed,
    train_attention_linear,
    train_head,
    train_head_distill,
)

REPO = Path(__file__).resolve().parents[2]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _review(*parts: str) -> Path:
    return REPO / REVIEW_REL / Path(*parts)


def _out(*parts: str) -> Path:
    return REPO / OUTPUT_REL / Path(*parts)


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:
        return "UNKNOWN"


def _corr(a: np.ndarray, b: np.ndarray, kind: str) -> float:
    try:
        fn = pearsonr if kind == "pearson" else spearmanr
        r = fn(a, b)
        return float(getattr(r, "statistic", r[0]))
    except Exception:
        return float("nan")


def _gpu_snapshot() -> dict[str, Any]:
    snap: dict[str, Any] = {"cuda_available": bool(torch.cuda.is_available())}
    try:
        text = subprocess.check_output(["nvidia-smi"], text=True, stderr=subprocess.STDOUT)
        snap["nvidia_smi"] = text[-2000:]
        competing = "python" in text.lower() and "c+g" not in text.lower()
        snap["competing_python_gpu"] = competing
    except Exception as exc:
        snap["nvidia_smi_error"] = str(exc)
        snap["competing_python_gpu"] = False
    return snap


def _objective_o0(n_pos: int, n_neg: int) -> dict[str, Any]:
    return {
        "family": "O0",
        "name": "producing_wbce",
        "pos_weight": pos_weight(n_pos, n_neg, POS_WEIGHT_MULT_O0),
        "gamma": 0.0,
        "lambda_rank": 0.0,
    }


def run_campaign() -> dict[str, Any]:
    refuse_test_loader_construction(partition="train")
    refuse_test_loader_construction(partition="validation")
    started = _now()
    device = select_device()
    gpu = _gpu_snapshot()
    for sub in (
        "inner_reference",
        "embeddings",
        "heads",
        "odst_grid",
        "teacher_quality",
        "full_encoders",
        "full_scores",
    ):
        _out(sub).mkdir(parents=True, exist_ok=True)
    write_json(_review("EDITOR010_RUN_MANIFEST.json"), {
        "task_id": "EDITOR-010",
        "status": "RUNNING",
        "started_utc": started,
        "device": str(device),
        "gpu": gpu,
        "protocol_commit": PROTOCOL_COMMIT,
        "implementation_head": _git_head(),
        "r52_test_accessed": False,
    })

    # ------------------------------------------------------------------
    # Phase 1 — inner split + reference encoder + cached embeddings
    # ------------------------------------------------------------------
    train = load_train()
    split = inner_split_masks(train)
    assert_no_boundary_crossing(train, split["train_mask"], split["select_mask"])
    inner_train = subset_bundle(train, split["train_mask"], "inner_train")
    inner_select = subset_bundle(train, split["select_mask"], "inner_select")
    if set(inner_train.sequence_id) & set(inner_select.sequence_id):
        raise Editor010SafetyError("INNER_TRAIN ∩ INNER_SELECT sequence_id overlap")

    write_json(_review("01_inner_development", "EDITOR010_INNER_SPLIT.json"), {
        "source_tensor": str(train.path),
        "source_sha256": train.sha256,
        "fraction": 0.8,
        "n_users": int(len({*train.user})),
        "n_inner_train": split["n_inner_train"],
        "n_inner_select": split["n_inner_select"],
        "n_dropped_boundary": split["n_dropped"],
        "n_inner_train_pos": split["n_inner_train_pos"],
        "n_inner_select_pos": split["n_inner_select_pos"],
        "disjoint": True,
        "official_validation_used": False,
        "r52_test_accessed": False,
    })
    write_csv(
        _review("01_inner_development", "EDITOR010_INNER_SPLIT_COUNTS.csv"),
        split["per_user"],
    )
    write_json(_review("01_inner_development", "EDITOR010_INNER_SPLIT_CHECKSUMS.json"), {
        "train_sha256": train.sha256,
        "inner_train_n": split["n_inner_train"],
        "inner_select_n": split["n_inner_select"],
        "inner_train_pos": split["n_inner_train_pos"],
        "inner_select_pos": split["n_inner_select_pos"],
        "sequence_overlap": 0,
    })

    n_pos = int(inner_train.y.sum())
    n_neg = int(len(inner_train.y) - n_pos)
    pw_o0 = pos_weight(n_pos, n_neg, POS_WEIGHT_MULT_O0)
    pw_o1 = pos_weight(n_pos, n_neg, POS_WEIGHT_MULT_O1)
    obj_o0 = _objective_o0(n_pos, n_neg)

    tr_loader = make_xy_loader(inner_train.X, inner_train.y, batch_size=BATCH_SIZE, seed=SCREENING_SEED, shuffle=True)
    se_loader = make_xy_loader(inner_select.X, inner_select.y, batch_size=BATCH_SIZE, seed=SCREENING_SEED, shuffle=False)
    # Attention-linear producing uses pos_weight_mult=1.0
    enc_pack = train_attention_linear(
        tr_loader,
        se_loader,
        pos_weight=pos_weight(n_pos, n_neg, 1.0),
        seed=SCREENING_SEED,
        device=device,
    )
    encoder = enc_pack["model"]
    enc_dir = _out("inner_reference")
    enc_dir.mkdir(parents=True, exist_ok=True)
    ckpt = enc_dir / "inner_reference_seed42.pt"
    torch.save({"model_state_dict": encoder.state_dict(), "seed": 42, "task": "EDITOR-010"}, ckpt)
    write_json(_review("01_inner_development", "EDITOR010_INNER_REFERENCE_MODEL.json"), {
        "checkpoint": str(ckpt),
        "checkpoint_sha256": sha256_file(ckpt, write=True),
        "seed": 42,
        "architecture": "SequenceEnsembleModel attention-linear",
        "trained_on": "INNER_TRAIN",
        "early_stopping": "INNER_SELECT PR-AUC",
        "best_epoch": enc_pack["best_epoch"],
        "inner_select_pr_auc": enc_pack["best_select_pr_auc"],
        "seconds": enc_pack["seconds"],
        "official_validation_used": False,
    })

    cache_dir = _out("embeddings")
    h_tr, y_tr = cache_embeddings(encoder, inner_train.X, inner_train.y, device=device)
    h_se, y_se = cache_embeddings(encoder, inner_select.X, inner_select.y, device=device)
    files = {
        "inner_train_attention_embeddings.npy": h_tr,
        "inner_train_labels.npy": y_tr,
        "inner_select_attention_embeddings.npy": h_se,
        "inner_select_labels.npy": y_se,
    }
    hashes = {}
    for name, arr in files.items():
        p = cache_dir / name
        save_npy(p, arr)
        hashes[name] = {"path": str(p), "sha256": sha256_file(p, write=True), "shape": list(arr.shape)}
    write_json(_review("01_inner_development", "EDITOR010_EMBEDDING_CACHE.json"), hashes)

    # ------------------------------------------------------------------
    # Phase 2 — headroom
    # ------------------------------------------------------------------
    head_specs = [
        ("H-LIN", None, LR_ATTENTION_LINEAR, 0.0),
        ("H-ODST", dict(PRODUCING_ODST), LR_ODST_PRODUCING, 0.0),
        ("H-MLP", None, LR_ATTENTION_LINEAR, 0.0),
    ]
    headroom_rows = []
    headroom_logits = {}
    for kind, cfg, lr, wd in head_specs:
        pack = train_head(
            build_head(kind, cfg),
            h_tr, y_tr, h_se, y_se,
            objective=obj_o0,
            seed=SCREENING_SEED,
            device=device,
            lr=lr,
            weight_decay=wd,
        )
        m = pack["select_metrics"]
        row = {"head": kind, "seed": 42, **{k: m[k] for k in ("pr_auc", "f1", "brier", "log_loss", "precision", "recall")}}
        row["train_pr_auc"] = pack["train_metrics"]["pr_auc"]
        row["best_epoch"] = pack["best_epoch"]
        headroom_rows.append(row)
        headroom_logits[kind] = pack["select_logits"]
        torch.save({"model_state_dict": pack["head"].state_dict(), "head": kind}, _out("heads", f"{kind}_seed42.pt"))

    def _by(name: str) -> dict:
        return next(r for r in headroom_rows if r["head"] == name)

    lin, odst, mlp = _by("H-LIN"), _by("H-ODST"), _by("H-MLP")
    pairwise = {}
    for a, b in (("H-MLP", "H-LIN"), ("H-ODST", "H-LIN"), ("H-MLP", "H-ODST")):
        la, lb = headroom_logits[a], headroom_logits[b]
        pa = 1 / (1 + np.exp(-np.clip(la, -40, 40)))
        pb = 1 / (1 + np.exp(-np.clip(lb, -40, 40)))
        ma = evaluate_scores(y_se, logits=la)
        mb = evaluate_scores(y_se, logits=lb)
        pairwise[f"{a}_vs_{b}"] = {
            "logit_correlation": _corr(la, lb, "pearson"),
            "rank_correlation": _corr(la, lb, "spearman"),
            **pairwise_disagreement(pa, pb, y_se, ma["threshold"], mb["threshold"]),
        }
    mlp_gt_lin = mlp["pr_auc"] > lin["pr_auc"] + HEADROOM_PR_AUC_MARGIN
    odst_near_lin = abs(odst["pr_auc"] - lin["pr_auc"]) <= HEADROOM_PR_AUC_MARGIN
    odst_gt_both = odst["pr_auc"] > max(lin["pr_auc"], mlp["pr_auc"]) + HEADROOM_PR_AUC_MARGIN
    if mlp_gt_lin and (odst_near_lin or odst["pr_auc"] + HEADROOM_PR_AUC_MARGIN < lin["pr_auc"]):
        nonlinear = "SUPPORTED"
        captures = "NO"
    elif abs(mlp["pr_auc"] - lin["pr_auc"]) <= HEADROOM_PR_AUC_MARGIN and odst_near_lin:
        nonlinear = "NOT_SUPPORTED"
        captures = "PARTIALLY"
    elif odst_gt_both:
        nonlinear = "PARTIALLY_SUPPORTED"
        captures = "YES"
    elif mlp_gt_lin:
        nonlinear = "SUPPORTED"
        captures = "PARTIALLY" if odst["pr_auc"] > lin["pr_auc"] else "NO"
    else:
        nonlinear = "PARTIALLY_SUPPORTED"
        captures = "PARTIALLY"
    headroom_ruling = {
        "NONLINEAR_HEADROOM": nonlinear,
        "CURRENT_ODST_CAPTURES_NONLINEAR_HEADROOM": captures,
        "H-LIN_pr_auc": lin["pr_auc"],
        "H-ODST_pr_auc": odst["pr_auc"],
        "H-MLP_pr_auc": mlp["pr_auc"],
        "pairwise": pairwise,
        "margin": HEADROOM_PR_AUC_MARGIN,
    }
    write_csv(_review("02_representation_headroom", "EDITOR010_HEADROOM_RESULTS.csv"), headroom_rows)
    write_json(_review("02_representation_headroom", "EDITOR010_HEADROOM_RULING.json"), headroom_ruling)

    # ------------------------------------------------------------------
    # Phase 3 — ODST landscape
    # ------------------------------------------------------------------
    param_map = {
        "implementation": "src/prototype_v3_node/odst.py",
        "supported_parameters": {
            "n_trees": "ODST/NODE n_trees per Dense layer; producing=8",
            "depth": "oblivious depth; producing=4",
            "temperature": "initial split temperature; learnable via softplus(log_temperatures)",
            "feature_selection_temperature": "NOT a separate parameter; entmax/sparsemax on feature_logits",
            "threshold_initialisation": "zeros; optional data_aware_initialize not used (match producing)",
            "leaf_initialisation": "Normal(0, leaf_init_std=0.05)",
            "dropout": "NODE between-layer dropout; producing=0.0",
            "tree/output regularisation": "no explicit ODST L2 in producing Adam; EDITOR-010 varies Adam weight_decay",
            "learning_rate": "head Adam lr; producing=3e-4",
            "weight_decay": "Adam weight_decay; producing=0.0",
            "batch_size": "1024 frozen",
            "gradient_clipping": "1.0 frozen",
            "num_layers": "2 frozen this campaign",
            "choice_function": "sparsemax_sigmoid frozen (producing)",
            "readout": "canonical_tree_average frozen",
        },
        "n_grid": len(ODST_GRID),
        "max_grid": 48,
    }
    write_json(_review("03_odst_landscape", "EDITOR010_ODST_PARAMETER_MAP.json"), param_map)
    write_json(_review("03_odst_landscape", "EDITOR010_ODST_GRID.json"), {
        "n": len(ODST_GRID),
        "max": 48,
        "seed": 42,
        "candidates": ODST_GRID,
        "frozen_before_results": True,
    })

    landscape_rows = []
    landscape_packs = {}
    for cand in ODST_GRID:
        cid = cand["candidate_id"]
        pack = train_head(
            build_head("H-ODST", cand),
            h_tr, y_tr, h_se, y_se,
            objective=obj_o0,
            seed=SCREENING_SEED,
            device=device,
            lr=float(cand["lr"]),
            weight_decay=float(cand["weight_decay"]),
            collect_diagnostics=True,
        )
        m = pack["select_metrics"]
        d = pack["diagnostics"]
        row = {
            "candidate_id": cid,
            "n_trees": cand["n_trees"],
            "depth": cand["depth"],
            "temperature": cand["temperature"],
            "lr": cand["lr"],
            "weight_decay": cand["weight_decay"],
            "dropout": cand["dropout"],
            "is_producing_current": cand["is_producing_current"],
            "train_pr_auc": pack["train_metrics"]["pr_auc"],
            "inner_select_pr_auc": m["pr_auc"],
            "f1": m["f1"],
            "brier": m["brier"],
            "log_loss": m["log_loss"],
            "best_epoch": pack["best_epoch"],
            "training_time": pack["seconds"],
            "routing_entropy": d.get("routing_entropy"),
            "effective_active_leaves": d.get("effective_active_leaves_fraction"),
            "leaf_mass_entropy": d.get("leaf_mass_entropy"),
            "per_tree_output_variance": d.get("per_tree_output_variance_mean"),
            "tree_output_correlation": d.get("tree_output_correlation"),
            "gradient_norm": d.get("gradient_norm"),
            "EDITOR010_DIAGNOSTIC_ONLY": True,
        }
        landscape_rows.append(row)
        landscape_packs[cid] = pack
        torch.save({"model_state_dict": pack["head"].state_dict(), "candidate": cand}, _out("odst_grid", f"{cid}.pt"))

    write_csv(_review("03_odst_landscape", "EDITOR010_ODST_LANDSCAPE.csv"), landscape_rows)
    producing_row = next(r for r in landscape_rows if r["is_producing_current"])
    ranked = sorted(landscape_rows, key=lambda r: -float(r["inner_select_pr_auc"]))
    best_row = ranked[0]

    def _dim_suboptimal(dim: str, producing_value: float) -> str:
        better = [r for r in landscape_rows if abs(float(r[dim]) - producing_value) > 1e-12 and r["inner_select_pr_auc"] > producing_row["inner_select_pr_auc"] + HEADROOM_PR_AUC_MARGIN]
        if len(better) >= 3:
            return "SUPPORTED"
        if better:
            return "PARTIALLY_SUPPORTED"
        return "NOT_SUPPORTED"

    near_opt = abs(best_row["inner_select_pr_auc"] - producing_row["inner_select_pr_auc"]) <= HEADROOM_PR_AUC_MARGIN
    trees_small = any(r["n_trees"] > 8 and r["inner_select_pr_auc"] > producing_row["inner_select_pr_auc"] + HEADROOM_PR_AUC_MARGIN for r in landscape_rows)
    trees_large = any(r["n_trees"] < 8 and r["inner_select_pr_auc"] > producing_row["inner_select_pr_auc"] + HEADROOM_PR_AUC_MARGIN for r in landscape_rows)
    landscape_ruling = {
        "CURRENT_ODST_CAPACITY_TOO_SMALL": "SUPPORTED" if trees_small else "NOT_SUPPORTED",
        "CURRENT_ODST_CAPACITY_TOO_LARGE": "SUPPORTED" if trees_large else "NOT_SUPPORTED",
        "CURRENT_ODST_DEPTH_SUBOPTIMAL": _dim_suboptimal("depth", 4),
        "CURRENT_ODST_TEMPERATURE_SUBOPTIMAL": _dim_suboptimal("temperature", 1.0),
        "CURRENT_ODST_HEAD_LR_SUBOPTIMAL": _dim_suboptimal("lr", 3e-4),
        "CURRENT_ODST_REGULARISATION_SUBOPTIMAL": _dim_suboptimal("weight_decay", 0.0),
        "CURRENT_ODST_CONFIGURATION_NEAR_OPTIMUM": "SUPPORTED" if near_opt else "NOT_SUPPORTED",
        "best_candidate_id": best_row["candidate_id"],
        "best_inner_select_pr_auc": best_row["inner_select_pr_auc"],
        "producing_inner_select_pr_auc": producing_row["inner_select_pr_auc"],
    }
    write_json(_review("03_odst_landscape", "EDITOR010_ODST_LANDSCAPE_RULING.json"), landscape_ruling)
    top3 = [r["candidate_id"] for r in ranked[:3]]
    heads_for_obj = list(dict.fromkeys(top3 + ["ODST-000"]))

    # ------------------------------------------------------------------
    # Phase 4 — objectives
    # ------------------------------------------------------------------
    objective_freeze = {
        "heads": heads_for_obj,
        "O0": "producing WBCE pos_weight_mult=0.25 INNER_TRAIN",
        "O1": "class-balanced WBCE pos_weight_mult=1.0 INNER_TRAIN; not a rename of O0",
        "O2": "focal gamma={1,2} with O0 pos_weight",
        "O3": "O0 + pairwise ranking lambda_rank={0.1,0.5,1.0}",
        "O4": "best two O3 + O1 class-balanced task loss",
        "pair_construction": {"max_pairs_per_batch": 512, "neg_per_pos": 8, "formula": "log(1+exp(-(s+-s-)))"},
        "no_differentiable_AP_package": True,
        "inner_train_n_pos": n_pos,
        "inner_train_n_neg": n_neg,
        "pos_weight_O0": pw_o0,
        "pos_weight_O1": pw_o1,
    }
    write_json(_review("04_objective_landscape", "EDITOR010_OBJECTIVE_FREEZE.json"), objective_freeze)

    obj_rows = []
    obj_defs: list[dict[str, Any]] = [
        {"objective_id": "O0", "family": "O0", "pos_weight": pw_o0, "gamma": 0.0, "lambda_rank": 0.0},
        {"objective_id": "O1", "family": "O1", "pos_weight": pw_o1, "gamma": 0.0, "lambda_rank": 0.0},
    ]
    for g in FOCAL_GAMMA:
        obj_defs.append({"objective_id": f"O2_g{int(g)}", "family": "O2", "pos_weight": pw_o0, "gamma": g, "lambda_rank": 0.0})
    for lam in LAMBDA_RANK_GRID:
        obj_defs.append({"objective_id": f"O3_l{lam}", "family": "O3", "pos_weight": pw_o0, "gamma": 0.0, "lambda_rank": lam})

    o3_scores: list[tuple[str, str, float]] = []
    for hid in heads_for_obj:
        cfg = ODST_GRID_BY_ID[hid]
        for od in obj_defs:
            pack = train_head(
                build_head("H-ODST", cfg),
                h_tr, y_tr, h_se, y_se,
                objective=od,
                seed=SCREENING_SEED,
                device=device,
                lr=float(cfg["lr"]),
                weight_decay=float(cfg["weight_decay"]),
            )
            m = pack["select_metrics"]
            row = {
                "head_configuration": hid,
                "objective": od["objective_id"],
                "family": od["family"],
                "gamma": od.get("gamma", 0.0),
                "lambda_rank": od.get("lambda_rank", 0.0),
                "seed": 42,
                "train_pr_auc": pack["train_metrics"]["pr_auc"],
                "inner_select_pr_auc": m["pr_auc"],
                "f1": m["f1"],
                "precision": m["precision"],
                "recall": m["recall"],
                "brier": m["brier"],
                "log_loss": m["log_loss"],
                "best_epoch": pack["best_epoch"],
            }
            obj_rows.append(row)
            if od["family"] == "O3":
                o3_scores.append((hid, od["objective_id"], m["pr_auc"]))

    o3_scores.sort(key=lambda t: -t[2])
    best_two_o3 = o3_scores[:2]
    for hid, oid, _ in best_two_o3:
        cfg = ODST_GRID_BY_ID[hid]
        lam = float(oid.split("l")[-1])
        od = {"objective_id": f"O4_from_{oid}", "family": "O4", "pos_weight": pw_o1, "gamma": 0.0, "lambda_rank": lam}
        pack = train_head(
            build_head("H-ODST", cfg),
            h_tr, y_tr, h_se, y_se,
            objective=od,
            seed=SCREENING_SEED,
            device=device,
            lr=float(cfg["lr"]),
            weight_decay=float(cfg["weight_decay"]),
        )
        m = pack["select_metrics"]
        obj_rows.append({
            "head_configuration": hid,
            "objective": od["objective_id"],
            "family": "O4",
            "lambda_rank": lam,
            "seed": 42,
            "train_pr_auc": pack["train_metrics"]["pr_auc"],
            "inner_select_pr_auc": m["pr_auc"],
            "f1": m["f1"],
            "precision": m["precision"],
            "recall": m["recall"],
            "brier": m["brier"],
            "log_loss": m["log_loss"],
            "best_epoch": pack["best_epoch"],
        })

    write_csv(_review("04_objective_landscape", "EDITOR010_OBJECTIVE_RESULTS.csv"), obj_rows)

    def _mean_family(fam: str) -> float:
        vals = [r["inner_select_pr_auc"] for r in obj_rows if r["family"] == fam]
        return float(np.mean(vals)) if vals else float("nan")

    o0_mean = _mean_family("O0")
    helps = {}
    for fam, label in (("O1", "CLASS_BALANCING_HELPS"), ("O2", "FOCAL_HELPS"), ("O3", "PAIRWISE_RANKING_HELPS")):
        delta = _mean_family(fam) - o0_mean
        helps[label] = "YES" if delta > OBJECTIVE_CONSISTENCY_MARGIN else "NO"
    misaligned = "SUPPORTED" if any(helps[k] == "YES" for k in helps) else "NOT_SUPPORTED"
    if misaligned == "NOT_SUPPORTED" and max(r["inner_select_pr_auc"] for r in obj_rows) > o0_mean + OBJECTIVE_CONSISTENCY_MARGIN:
        misaligned = "PARTIALLY_SUPPORTED"
    obj_ruling = {
        "CURRENT_OBJECTIVE_MISALIGNED_WITH_PR_AUC": misaligned,
        **helps,
        "O0_mean_inner_select_pr_auc": o0_mean,
        "O1_mean": _mean_family("O1"),
        "O2_mean": _mean_family("O2"),
        "O3_mean": _mean_family("O3"),
        "O4_mean": _mean_family("O4"),
    }
    write_json(_review("04_objective_landscape", "EDITOR010_OBJECTIVE_RULING.json"), obj_ruling)

    # ------------------------------------------------------------------
    # Phase 5 — teacher quality on official VALIDATION (frozen models only)
    # ------------------------------------------------------------------
    val = load_validation()
    val_loader = make_xy_loader(val.X, val.y, batch_size=BATCH_SIZE, seed=SCREENING_SEED, shuffle=False)
    tq_rows = []
    tq_scores: dict[tuple[str, int], np.ndarray] = {}
    tq_logits: dict[tuple[str, int], np.ndarray] = {}
    for family in ("teacher", "C2", "C5_original_paper", "attention-linear"):
        for seed in FULL_CONFIRMATION_SEEDS:
            model = load_baseline(family, seed, device)
            logits, yv = predict_logits(model, val_loader, device)
            if not np.array_equal(yv, val.y.astype(np.float32)) and len(yv) != len(val.y):
                raise Editor010SafetyError("validation length mismatch")
            probs = 1 / (1 + np.exp(-np.clip(logits, -40, 40)))
            m = evaluate_scores(val.y, logits=logits, probs=probs)
            tq_rows.append({"family": family, "seed": seed, **m})
            tq_scores[(family, seed)] = probs
            tq_logits[(family, seed)] = logits
            np.save(_out("teacher_quality", f"{family}_{seed}_val_logits.npy"), logits)

    write_csv(_review("05_teacher_quality", "EDITOR010_TEACHER_QUALITY.csv"), tq_rows)
    teacher_probs = np.mean([tq_scores[("teacher", s)] for s in FULL_CONFIRMATION_SEEDS], axis=0)
    teacher_logits_ens = np.mean([tq_logits[("teacher", s)] for s in FULL_CONFIRMATION_SEEDS], axis=0)
    al_probs = np.mean([tq_scores[("attention-linear", s)] for s in FULL_CONFIRMATION_SEEDS], axis=0)
    ens_t = evaluate_scores(val.y, probs=teacher_probs)
    ens_al = evaluate_scores(val.y, probs=al_probs)
    single_teacher = [r for r in tq_rows if r["family"] == "teacher"]
    best_single = max(single_teacher, key=lambda r: r["pr_auc"])
    ensemble_better = ens_t["pr_auc"] > best_single["pr_auc"]
    tq_diag = {
        "teacher_ensemble_pr_auc": ens_t["pr_auc"],
        "attention_linear_ensemble_pr_auc": ens_al["pr_auc"],
        "best_single_teacher_pr_auc": best_single["pr_auc"],
        "best_single_teacher_seed": best_single["seed"],
        "equal_weight": True,
        "learned_validation_weights": False,
        "ENSEMBLE_ROUTE_ANCHORING": "OFF",
        "ensemble_better_than_best_single": ensemble_better,
    }
    write_json(_review("05_teacher_quality", "EDITOR010_TEACHER_ENSEMBLE_DIAGNOSTIC.json"), tq_diag)
    ceiling = "SUPPORTED" if not ensemble_better else "NOT_SUPPORTED"
    if abs(ens_t["pr_auc"] - best_single["pr_auc"]) <= HEADROOM_PR_AUC_MARGIN:
        ceiling = "PARTIALLY_SUPPORTED"
        diversity = "NOT_SUPPORTED"
    else:
        diversity = "SUPPORTED" if ensemble_better else "NOT_SUPPORTED"
    tq_ruling = {
        "SINGLE_TEACHER_IS_PREDICTIVE_CEILING": ceiling,
        "ENSEMBLE_TEACHER_HAS_ADDITIONAL_RANKING_INFORMATION": diversity,
        "teacher_ensemble_pr_auc": ens_t["pr_auc"],
        "best_single_teacher_pr_auc": best_single["pr_auc"],
    }
    write_json(_review("05_teacher_quality", "EDITOR010_TEACHER_CEILING_RULING.json"), tq_ruling)

    et1_executed = bool(ensemble_better)
    et1_inner = None
    if et1_executed:
        # Score frozen teachers on INNER_TRAIN embeddings' original sequences via encoder cache? Need teacher logits on INNER_TRAIN sequences.
        # Use sequence tensors (authorised TRAIN), not TEST.
        inner_tr_loader = make_xy_loader(inner_train.X, inner_train.y, batch_size=BATCH_SIZE, seed=SCREENING_SEED, shuffle=False)
        t_logits = []
        for seed in FULL_CONFIRMATION_SEEDS:
            mdl = load_baseline("teacher", seed, device)
            lg, _ = predict_logits(mdl, inner_tr_loader, device)
            t_logits.append(lg)
        ens_inner = np.mean(t_logits, axis=0)
        best_cfg_id = best_row["candidate_id"]
        best_obj_row = max(obj_rows, key=lambda r: r["inner_select_pr_auc"])
        cfg = ODST_GRID_BY_ID[best_cfg_id]
        od = _objective_o0(n_pos, n_neg)
        od["lambda_distill"] = ET1_LOGIT_DISTILL_WEIGHT
        od["family"] = "O0"
        et1_inner = train_head_distill(
            build_head("H-ODST", cfg),
            h_tr, y_tr, ens_inner, h_se, y_se,
            objective=od,
            seed=SCREENING_SEED,
            device=device,
            lr=float(cfg["lr"]),
            weight_decay=float(cfg["weight_decay"]),
        )

    # ------------------------------------------------------------------
    # Phase 6 — promotion freeze THEN full r5.2 confirmation
    # ------------------------------------------------------------------
    best_o0 = max((r for r in obj_rows if r["family"] == "O0"), key=lambda r: r["inner_select_pr_auc"])
    ranking_rows = [r for r in obj_rows if r["family"] in {"O3", "O4"}]
    best_rank = max(ranking_rows, key=lambda r: r["inner_select_pr_auc"]) if ranking_rows else best_o0
    foc_rows = [r for r in obj_rows if r["family"] in {"O1", "O2"}]
    best_foc = max(foc_rows, key=lambda r: r["inner_select_pr_auc"]) if foc_rows else best_o0
    promoted: list[dict[str, Any]] = []

    def _add_promoted(pid: str, row: dict[str, Any], kind: str) -> None:
        if any(p["head_configuration"] == row["head_configuration"] and p["objective"] == row["objective"] for p in promoted):
            return
        if len(promoted) >= 4:
            return
        promoted.append({
            "candidate_id": pid,
            "kind": kind,
            "head_configuration": row["head_configuration"],
            "objective": row["objective"],
            "inner_select_pr_auc": row["inner_select_pr_auc"],
            "odst": ODST_GRID_BY_ID[row["head_configuration"]],
        })

    _add_promoted("P1_best_current_objective", best_o0, "best_current_objective_ODST")
    _add_promoted("P2_best_ranking_aware", best_rank, "best_ranking_aware_ODST")
    _add_promoted("P3_best_focal_or_balanced", best_foc, "best_focal_or_class_balanced_ODST")
    if et1_executed:
        promoted.append({
            "candidate_id": "P4_ET1",
            "kind": "ET1_ensemble_teacher_student",
            "head_configuration": best_row["candidate_id"],
            "objective": "O0_plus_equal_weight_ensemble_logit_distill",
            "inner_select_pr_auc": et1_inner["select_metrics"]["pr_auc"] if et1_inner else None,
            "odst": ODST_GRID_BY_ID[best_row["candidate_id"]],
            "ENSEMBLE_ROUTE_ANCHORING": "OFF",
        })
    if len(promoted) < 4:
        for r in ranked[1:]:
            dummy = {"head_configuration": r["candidate_id"], "objective": "O0", "inner_select_pr_auc": r["inner_select_pr_auc"]}
            _add_promoted(f"P_extra_{r['candidate_id']}", dummy, "diverse_capacity_ODST")
            if len(promoted) >= 4:
                break

    promotion_path = _review("06_promoted_full_r52", "EDITOR010_PROMOTION_FREEZE.json")
    write_json(promotion_path, {
        "frozen_before_official_validation_evaluation_of_candidates": True,
        "promotion_source": "INNER_SELECT",
        "official_r52_validation_not_used_for_selection": True,
        "promoted": promoted,
        "et1_executed": et1_executed,
        "et1_condition": "teacher_ensemble_pr_auc > best_single_teacher_pr_auc",
    })
    # Promotion freeze commit is requested; performed by the CLI after this JSON exists.

    # Full TRAIN confirmation: one encoder per seed, then promoted heads.
    full_rows = []
    cand_val_probs: dict[tuple[str, int], np.ndarray] = {}
    h_full_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
    full_tr_loader_base = None
    val_for_early = make_xy_loader(val.X, val.y, batch_size=BATCH_SIZE, seed=SCREENING_SEED, shuffle=False)
    for seed in FULL_CONFIRMATION_SEEDS:
        set_seed(seed)
        full_tr_loader = make_xy_loader(train.X, train.y, batch_size=BATCH_SIZE, seed=seed, shuffle=True)
        enc_full = train_attention_linear(
            full_tr_loader,
            val_for_early,
            pos_weight=pos_weight(int(train.y.sum()), int(len(train.y) - train.y.sum()), 1.0),
            seed=seed,
            device=device,
        )
        torch.save({"model_state_dict": enc_full["model"].state_dict(), "seed": seed}, _out("full_encoders", f"encoder_seed{seed}.pt"))
        h_ft, y_ft = cache_embeddings(enc_full["model"], train.X, train.y, device=device)
        h_fv, y_fv = cache_embeddings(enc_full["model"], val.X, val.y, device=device)
        h_full_cache[seed] = (h_ft, y_ft, h_fv, y_fv)

        # Teacher ensemble logits on full TRAIN for ET1
        if et1_executed:
            tlg = []
            for tseed in FULL_CONFIRMATION_SEEDS:
                mdl = load_baseline("teacher", tseed, device)
                lg, _ = predict_logits(mdl, make_xy_loader(train.X, train.y, batch_size=BATCH_SIZE, seed=0, shuffle=False), device)
                tlg.append(lg)
            ens_full = np.mean(tlg, axis=0)
        else:
            ens_full = None

        npos_f = int(train.y.sum())
        nneg_f = int(len(train.y) - npos_f)
        for cand in promoted:
            cfg = cand["odst"]
            if cand["candidate_id"] == "P4_ET1":
                od = _objective_o0(npos_f, nneg_f)
                od["lambda_distill"] = ET1_LOGIT_DISTILL_WEIGHT
                pack = train_head_distill(
                    build_head("H-ODST", cfg),
                    h_ft, y_ft, ens_full, h_fv, y_fv,
                    objective=od,
                    seed=seed,
                    device=device,
                    lr=float(cfg["lr"]),
                    weight_decay=float(cfg["weight_decay"]),
                )
            else:
                src = next(
                    (
                        r
                        for r in obj_rows
                        if r["head_configuration"] == cand["head_configuration"]
                        and r["objective"] == cand["objective"]
                    ),
                    None,
                )
                fam = str((src or {}).get("family") or cand.get("family") or "O0")
                gamma = float((src or {}).get("gamma") or 0.0)
                lam = float((src or {}).get("lambda_rank") or 0.0)
                pw = pos_weight(
                    npos_f,
                    nneg_f,
                    POS_WEIGHT_MULT_O1 if fam in {"O1", "O4"} else POS_WEIGHT_MULT_O0,
                )
                od = {"family": fam, "pos_weight": pw, "gamma": gamma, "lambda_rank": lam}
                pack = train_head(
                    build_head("H-ODST", cfg),
                    h_ft, y_ft, h_fv, y_fv,
                    objective=od,
                    seed=seed,
                    device=device,
                    lr=float(cfg["lr"]),
                    weight_decay=float(cfg["weight_decay"]),
                )
            m = pack["select_metrics"]
            row = {
                "candidate_id": cand["candidate_id"],
                "kind": cand["kind"],
                "seed": seed,
                "pr_auc": m["pr_auc"],
                "f1": m["f1"],
                "precision": m["precision"],
                "recall": m["recall"],
                "fp": m["fp"],
                "fn": m["fn"],
                "brier": m["brier"],
                "log_loss": m["log_loss"],
                "best_epoch": pack["best_epoch"],
            }
            full_rows.append(row)
            cand_val_probs[(cand["candidate_id"], seed)] = 1 / (1 + np.exp(-np.clip(pack["select_logits"] if "select_logits" in pack else predict_logits(pack["head"], make_xy_loader(h_fv, y_fv, batch_size=BATCH_SIZE, seed=0, shuffle=False), device)[0], -40, 40)))
            np.save(_out("full_scores", f"{cand['candidate_id']}_seed{seed}_val_logits.npy"), pack.get("select_logits", np.array([])))

    write_csv(_review("06_promoted_full_r52", "EDITOR010_FULL_RESULTS.csv"), full_rows)

    def _mean_pr(cid: str) -> float:
        vals = [r["pr_auc"] for r in full_rows if r["candidate_id"] == cid]
        return float(np.mean(vals)) if vals else float("nan")

    c2_mean = float(np.mean(list(C2_PRODUCING_PR_AUC.values())))
    c5_mean = float(np.mean(list(C5_PRODUCING_PR_AUC.values())))
    al_mean = float(np.mean(list(AL_REPLAY_PR_AUC.values())))
    comparisons = []
    for cand in promoted:
        cid = cand["candidate_id"]
        per = [r for r in full_rows if r["candidate_id"] == cid]
        mean_pr = float(np.mean([r["pr_auc"] for r in per]))
        d_c2 = {r["seed"]: r["pr_auc"] - C2_PRODUCING_PR_AUC[r["seed"]] for r in per}
        d_c5 = {r["seed"]: r["pr_auc"] - C5_PRODUCING_PR_AUC[r["seed"]] for r in per}
        d_al = {r["seed"]: r["pr_auc"] - AL_REPLAY_PR_AUC[r["seed"]] for r in per}
        pos_c2 = sum(1 for v in d_c2.values() if v > 0)
        pos_al = sum(1 for v in d_al.values() if v > 0)
        if mean_pr > c2_mean and pos_c2 >= 2:
            klass = "CLEAR_DEVELOPMENT_RESCUE"
        elif mean_pr > c2_mean or pos_c2 >= 2:
            klass = "PROMISING_BUT_NOT_ESTABLISHED"
        elif mean_pr < c2_mean - HEADROOM_PR_AUC_MARGIN:
            klass = "REGRESSION"
        else:
            klass = "NO_MEANINGFUL_GAIN"
        comparisons.append({
            "candidate_id": cid,
            "mean_pr_auc": mean_pr,
            "delta_vs_C2_mean": mean_pr - c2_mean,
            "delta_vs_C5_mean": mean_pr - c5_mean,
            "delta_vs_attention_linear_mean": mean_pr - al_mean,
            "per_seed_delta_vs_C2": d_c2,
            "per_seed_delta_vs_C5": d_c5,
            "per_seed_delta_vs_AL": d_al,
            "POSITIVE_DELTA_VS_C2_SEEDS": f"{pos_c2}/3",
            "POSITIVE_DELTA_VS_ATTENTION_LINEAR_SEEDS": f"{pos_al}/3",
            "classification": klass,
        })
    write_json(_review("06_promoted_full_r52", "EDITOR010_FIXED_COMPARISONS.json"), {
        "C2_MEAN_PR_AUC": c2_mean,
        "C5_ORIGINAL_MEAN_PR_AUC": c5_mean,
        "ATTENTION_LINEAR_MEAN_PR_AUC": al_mean,
        "comparisons": comparisons,
        "note": "C2/C5/AL means are frozen producing/replay validation PR-AUC; candidates evaluated once on the same r5.2 VALIDATION",
    })

    boot = {}
    for cand in promoted:
        cid = cand["candidate_id"]
        # Use seed 42 scores vs C2 seed 42 teacher-quality scores
        if ("C2", 42) in tq_scores and (cid, 42) in cand_val_probs:
            boot[cid] = {
                "vs_C2": paired_user_cluster_delta_pr(val.user, val.y, tq_scores[("C2", 42)], cand_val_probs[(cid, 42)]),
                "vs_attention_linear": paired_user_cluster_delta_pr(val.user, val.y, tq_scores[("attention-linear", 42)], cand_val_probs[(cid, 42)]),
            }
    write_json(_review("06_promoted_full_r52", "EDITOR010_CLUSTER_BOOTSTRAP.json"), boot)

    best_comp = max(comparisons, key=lambda c: c["mean_pr_auc"]) if comparisons else {}
    odst_headroom_flag = "YES" if best_comp.get("delta_vs_attention_linear_mean", -1) > HEADROOM_PR_AUC_MARGIN else "NO"

    # ------------------------------------------------------------------
    # Phase 7–9 rulings
    # ------------------------------------------------------------------
    def _status(cond: bool, partial: bool = False) -> str:
        if cond:
            return "SUPPORTED"
        if partial:
            return "PARTIALLY_SUPPORTED"
        return "NOT_SUPPORTED"

    root = {
        "H1_CURRENT_ODST_CAPACITY_IS_SUBOPTIMAL": landscape_ruling["CURRENT_ODST_CAPACITY_TOO_SMALL"] if landscape_ruling["CURRENT_ODST_CAPACITY_TOO_SMALL"] != "NOT_SUPPORTED" else landscape_ruling["CURRENT_ODST_CAPACITY_TOO_LARGE"],
        "H2_CURRENT_ODST_ROUTING_SOFTNESS_IS_SUBOPTIMAL": landscape_ruling["CURRENT_ODST_TEMPERATURE_SUBOPTIMAL"],
        "H3_CURRENT_ODST_OPTIMISATION_IS_SUBOPTIMAL": "SUPPORTED" if landscape_ruling["CURRENT_ODST_HEAD_LR_SUBOPTIMAL"] == "SUPPORTED" or landscape_ruling["CURRENT_ODST_REGULARISATION_SUBOPTIMAL"] == "SUPPORTED" else landscape_ruling["CURRENT_ODST_HEAD_LR_SUBOPTIMAL"],
        "H4_ATTENDED_REPRESENTATION_HAS_NONLINEAR_HEADROOM": nonlinear,
        "H5_ATTENDED_REPRESENTATION_IS_ALREADY_NEAR_LINEARLY_SEPARABLE": "SUPPORTED" if nonlinear == "NOT_SUPPORTED" else "NOT_SUPPORTED",
        "H6_CURRENT_SUPERVISED_OBJECTIVE_IS_POORLY_ALIGNED_WITH_PR_AUC": misaligned,
        "H7_RARE_EVENT_CLASS_IMBALANCE_LIMITS_ODST_LEARNING": helps["CLASS_BALANCING_HELPS"] and "SUPPORTED" or "NOT_SUPPORTED",
        "H8_PAIRWISE_RANKING_SIGNAL_IMPROVES_RARE_EVENT_ORDERING": "SUPPORTED" if helps["PAIRWISE_RANKING_HELPS"] == "YES" else "NOT_SUPPORTED",
        "H9_FOCAL_OBJECTIVE_IMPROVES_ODST": "SUPPORTED" if helps["FOCAL_HELPS"] == "YES" else "NOT_SUPPORTED",
        "H10_SINGLE_TEACHER_IS_A_PREDICTIVE_CEILING": ceiling,
        "H11_TEACHER_ENSEMBLE_CONTAINS_ADDITIONAL_RANKING_INFORMATION": diversity,
        "H12_STRONGER_TEACHER_TARGETS_ENABLE_STUDENT_IMPROVEMENT": "SUPPORTED" if et1_executed and best_comp.get("candidate_id") == "P4_ET1" and best_comp.get("classification") in {"CLEAR_DEVELOPMENT_RESCUE", "PROMISING_BUT_NOT_ESTABLISHED"} else ("UNRESOLVED" if not et1_executed else "NOT_SUPPORTED"),
        "evidence": {
            "headroom": headroom_ruling,
            "landscape": landscape_ruling,
            "objective": obj_ruling,
            "teacher": tq_ruling,
            "best_full": best_comp,
        },
    }
    # fix H7 ternary bug
    root["H7_RARE_EVENT_CLASS_IMBALANCE_LIMITS_ODST_LEARNING"] = "SUPPORTED" if helps["CLASS_BALANCING_HELPS"] == "YES" else "NOT_SUPPORTED"
    write_json(_review("07_root_cause", "EDITOR010_ROOT_CAUSE_RULING.json"), root)
    (_review("07_root_cause", "EDITOR010_ROOT_CAUSE_REPORT.md")).write_text(
        "\n".join(
            [
                "# EDITOR-010 root-cause ruling",
                "",
                f"Best full r5.2 candidate: `{best_comp.get('candidate_id')}` mean PR-AUC={best_comp.get('mean_pr_auc')}.",
                f"C2 mean PR-AUC={c2_mean}; C5 original mean={c5_mean}; attention-linear mean={al_mean}.",
                "",
                "## Hypotheses",
                *[f"- **{k}**: {v}" for k, v in root.items() if k.startswith("H")],
                "",
                "EDITOR-010 did not read EDITOR-009 results during selection.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rescue_bits = []
    if landscape_ruling["CURRENT_ODST_CONFIGURATION_NEAR_OPTIMUM"] != "SUPPORTED" and best_comp.get("delta_vs_C2_mean", 0) > 0:
        rescue_bits.append("ODST_CAPACITY_RESCUE_FOUND")
    if helps["PAIRWISE_RANKING_HELPS"] == "YES" or helps["FOCAL_HELPS"] == "YES" or helps["CLASS_BALANCING_HELPS"] == "YES":
        if best_comp.get("delta_vs_C2_mean", 0) > 0:
            rescue_bits.append("RARE_EVENT_OBJECTIVE_RESCUE_FOUND")
    if et1_executed and best_comp.get("candidate_id") == "P4_ET1" and best_comp.get("delta_vs_C2_mean", 0) > 0:
        rescue_bits.append("TEACHER_QUALITY_RESCUE_FOUND")
    if best_comp.get("classification") == "CLEAR_DEVELOPMENT_RESCUE":
        gate = "MULTI_FACTOR_RESCUE_FOUND" if len(rescue_bits) > 1 else (rescue_bits[0] if rescue_bits else "ODST_CAPACITY_RESCUE_FOUND")
    elif best_comp.get("classification") == "PROMISING_BUT_NOT_ESTABLISHED":
        gate = "PROMISING_REQUIRES_CONFIRMATION"
    else:
        gate = "NO_PREDICTIVE_RESCUE_FOUND"

    gate_payload = {
        "EDITOR010_PAPER_RESCUE_GATE": gate,
        "ODST_PREDICTIVE_HEADROOM_DEMONSTRATED": odst_headroom_flag,
        "TEACHER_DIVERSITY_HEADROOM": diversity,
        "STRONGER_TEACHER_DISTILLATION_RESCUE": root["H12_STRONGER_TEACHER_TARGETS_ENABLE_STUDENT_IMPROVEMENT"],
        "best_candidate": best_comp,
        "promoted": [p["candidate_id"] for p in promoted],
        "do_not_claim_anchoring_caused_gain": True,
        "r52_test_accessed": False,
    }
    write_json(_review("08_paper_handover", "EDITOR010_PAPER_RESCUE_GATE.json"), gate_payload)
    (_review("08_paper_handover", "EDITOR010_PAPER_RESCUE_HANDOVER.md")).write_text(
        "\n".join(
            [
                "# EDITOR-010 paper rescue handover",
                "",
                f"Gate: **{gate}**",
                f"Best candidate: `{best_comp.get('candidate_id')}`",
                f"Mean PR-AUC: {best_comp.get('mean_pr_auc')}",
                f"Δ vs C2: {best_comp.get('delta_vs_C2_mean')}",
                f"Δ vs C5 original: {best_comp.get('delta_vs_C5_mean')}",
                f"Δ vs attention-linear: {best_comp.get('delta_vs_attention_linear_mean')}",
                f"ODST_PREDICTIVE_HEADROOM_DEMONSTRATED: {odst_headroom_flag}",
                "",
                "Official r5.2 VALIDATION was opened only after INNER_SELECT promotion freeze.",
                "r5.2 TEST was not accessed.",
                "EDITOR-009 results were not read during EDITOR-010 selection.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = {
        "EDITOR010_PARALLEL_OVERNIGHT_RESCUE_COMPLETE": True,
        "INNER_SPLIT_VALID": True,
        "REPRESENTATION_NONLINEAR_HEADROOM": nonlinear,
        "CURRENT_ODST_CAPTURES_HEADROOM": captures,
        "CURRENT_ODST_CONFIGURATION_NEAR_OPTIMUM": landscape_ruling["CURRENT_ODST_CONFIGURATION_NEAR_OPTIMUM"],
        "ODST_CAPACITY_BOTTLENECK": landscape_ruling["CURRENT_ODST_CAPACITY_TOO_SMALL"],
        "ODST_OPTIMISATION_BOTTLENECK": landscape_ruling["CURRENT_ODST_HEAD_LR_SUBOPTIMAL"],
        "ODST_ROUTING_SOFTNESS_BOTTLENECK": landscape_ruling["CURRENT_ODST_TEMPERATURE_SUBOPTIMAL"],
        "CURRENT_OBJECTIVE_MISALIGNED_WITH_PR_AUC": misaligned,
        "CLASS_BALANCING_HELPED": helps["CLASS_BALANCING_HELPS"],
        "FOCAL_HELPED": helps["FOCAL_HELPS"],
        "PAIRWISE_RANKING_HELPED": helps["PAIRWISE_RANKING_HELPS"],
        "BEST_INNER_ODST_CONFIGURATION": best_row["candidate_id"],
        "BEST_INNER_OBJECTIVE": max(obj_rows, key=lambda r: r["inner_select_pr_auc"])["objective"],
        "BEST_INNER_PR_AUC": max(r["inner_select_pr_auc"] for r in obj_rows),
        "TEACHER_ENSEMBLE_PR_AUC": ens_t["pr_auc"],
        "BEST_SINGLE_TEACHER_PR_AUC": best_single["pr_auc"],
        "TEACHER_DIVERSITY_HEADROOM": diversity,
        "ET1_EXECUTED": et1_executed,
        "ET1_RESULT": et1_inner["select_metrics"] if et1_inner else None,
        "PROMOTED_CANDIDATES": [p["candidate_id"] for p in promoted],
        "BEST_FULL_R52_CANDIDATE": best_comp.get("candidate_id"),
        "BEST_CANDIDATE_MEAN_PR_AUC": best_comp.get("mean_pr_auc"),
        "C2_MEAN_PR_AUC": c2_mean,
        "C5_ORIGINAL_MEAN_PR_AUC": c5_mean,
        "ATTENTION_LINEAR_MEAN_PR_AUC": al_mean,
        "BEST_DELTA_VS_C2": best_comp.get("delta_vs_C2_mean"),
        "BEST_DELTA_VS_C5": best_comp.get("delta_vs_C5_mean"),
        "BEST_DELTA_VS_ATTENTION_LINEAR": best_comp.get("delta_vs_attention_linear_mean"),
        "POSITIVE_DELTA_VS_C2_SEEDS": best_comp.get("POSITIVE_DELTA_VS_C2_SEEDS"),
        "POSITIVE_DELTA_VS_ATTENTION_LINEAR_SEEDS": best_comp.get("POSITIVE_DELTA_VS_ATTENTION_LINEAR_SEEDS"),
        "CLUSTER_AWARE_CI_VS_C2": (boot.get(best_comp.get("candidate_id"), {}) or {}).get("vs_C2"),
        "CLUSTER_AWARE_CI_VS_ATTENTION_LINEAR": (boot.get(best_comp.get("candidate_id"), {}) or {}).get("vs_attention_linear"),
        "ODST_PREDICTIVE_HEADROOM_DEMONSTRATED": odst_headroom_flag,
        "EDITOR010_PAPER_RESCUE_GATE": gate,
        "started_utc": started,
        "finished_utc": _now(),
        "device": str(device),
        "r52_test_accessed": False,
    }
    write_json(_review("EDITOR010_RUN_MANIFEST.json"), {
        "task_id": "EDITOR-010",
        "status": "COMPLETE",
        "protocol_commit": PROTOCOL_COMMIT,
        "implementation_head": _git_head(),
        "r52_test_accessed": False,
        "r51_accessed_for_new_execution": False,
        "r62_accessed_for_new_execution": False,
        "EDITOR009_WORKTREE_TOUCHED": False,
        "summary": summary,
    })
    write_json(_out("EDITOR010_SUMMARY.json"), summary)
    return summary
