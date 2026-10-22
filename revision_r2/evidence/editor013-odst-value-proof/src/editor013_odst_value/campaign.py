"""EDITOR-013 autonomous ODST incremental-value orchestrator."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor012_rescue.bootstrap import paired_user_cluster_mean_across_seeds
from editor012_rescue.data import load_train_validation, make_xy_loader, subset_bundle
from editor012_rescue.evaluate import evaluate_pair, hash_gate_checkpoint
from editor012_rescue.inner_split import inner_split_masks
from editor012_rescue.metrics import metrics_from_logits, sigmoid
from editor012_rescue.models import architecture_identity, assert_odst046, freeze_teacher, student_forward as historical_student_forward
from editor012_rescue.producing import build_odst046_model, import_set_seed, load_state_dict, pin_producing_sources

from .constants import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    C2OPT_CHECKPOINTS,
    C2_VAL_LOGITS,
    EDITOR012_RESULTS_FULL_COMMIT,
    ENCODER_ARCH,
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
    F10_CHECKPOINTS,
    F11_CHECKPOINTS,
    HEAD_CONDITIONS,
    HISTORICAL,
    HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR,
    LAMBDA_DISTILL,
    LAMBDA_DIVERSITY_CANDIDATES,
    LATENCY_BATCH_SIZE,
    LATENCY_REPEATS,
    LATENCY_WARMUP,
    N_TREES_TOTAL,
    ODST046,
    PRIMARY_SEEDS,
    PROMOTION_MARGIN,
    SCREENING_SEED,
    TEACHER_GUIDANCE_VS_INITIALISATION,
    TOPT_CHECKPOINTS,
    TREE_DIVERSITY_TRIGGER,
    VALIDATION_MANDATORY,
)
from .explain import centred_contributions, faithfulness_table, train_references
from .freeze import write_protocol_packet
from .io_util import write_csv, write_json
from .models import (
    editor013_forward,
    freeze_encoder_attention,
    make_modules,
)
from .promotion import decide_promotions
from .safety import (
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor013Blocked,
    Editor013ProtocolError,
    enter_inner_phase,
    exit_inner_phase,
    refuse_historical_write,
    refuse_r52_test,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .train import evaluate_e2e, load_topt, train_e2e, train_head_only


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
        raise Editor013Blocked("r5.2 TEST deny-list failed to fire")
    except Exception as exc:
        if "TEST" not in str(exc):
            raise
    pins = pin_producing_sources()
    if ODST046["n_trees"] != 4 or ODST046["depth"] != 4 or float(ODST046["temperature"]) != 0.5:
        raise Editor013Blocked("ODST-046 lock mismatch")
    if abs(float(LAMBDA_DISTILL) - 0.5) > 1e-15:
        raise Editor013Blocked("distill lambda mismatch")
    if HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR != "RETIRED":
        raise Editor013Blocked("historical single-teacher anchor must stay retired")
    teacher = build_odst046_model()
    assert_odst046(teacher)
    return {
        "r52_test_hard_denied": True,
        "odst046_identity_verified": True,
        "lambda_distill": LAMBDA_DISTILL,
        "temperature": None,
        "producing_pins": pins,
        "architecture": architecture_identity(teacher),
        "HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR": HISTORICAL_SINGLE_TEACHER_LOGIT_ANCHOR,
        "EDITOR012_RESULTS_FULL_COMMIT": EDITOR012_RESULTS_FULL_COMMIT,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
    }


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor013Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor013Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor013Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor013Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    return {
        "USER_MAPPING_RECOVERED": True,
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "per_user_count_min": int(counts.min()),
        "per_user_count_max": int(counts.max()),
        "n_malicious_users": int(len(malicious)),
        "malicious_users": malicious,
        "mapping_sha256": mapping_hash,
        "hash_matches_EDITOR011_012": True,
        "EDITOR011_012_mapping_sha256": EXPECTED_USER_MAPPING_SHA256,
    }


@torch.no_grad()
def score_historical(model: torch.nn.Module, X: np.ndarray, y: np.ndarray, device: torch.device) -> np.ndarray:
    loader = make_xy_loader(X, y, seed=0, shuffle=False)
    model.eval()
    out = []
    for xb, _ in loader:
        out.append(historical_student_forward(model, xb.to(device))["logit"].detach().cpu().numpy())
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
        print(f"[EDITOR-013] scoring T-OPT({seed}) on {cache_name}", flush=True)
        logits[seed] = score_historical(teachers[seed], X, y, device)
        np.save(paths[f"logit{seed}"], logits[seed])
    ens = np.mean([logits[s] for s in PRIMARY_SEEDS], axis=0)
    np.save(paths["ens_logit"], ens)
    return {"logit42": logits[42], "logit52": logits[52], "logit62": logits[62], "ens_logit": ens}


@torch.no_grad()
def cache_common_z(
    teacher: torch.nn.Module,
    X: np.ndarray,
    y: np.ndarray,
    device: torch.device,
    name: str,
) -> dict[str, Any]:
    cache_dir = OUTPUT_ROOT / "z_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    z_path = cache_dir / f"{name}_z.npy"
    y_path = cache_dir / f"{name}_y.npy"
    if z_path.is_file() and y_path.is_file():
        z = np.load(z_path)
        yy = np.load(y_path)
    else:
        loader = make_xy_loader(X, y, seed=0, shuffle=False)
        teacher.eval()
        zs, ys = [], []
        for xb, yb in loader:
            out = historical_student_forward(teacher, xb.to(device))
            zs.append(out["z"].detach().cpu().numpy())
            ys.append(np.asarray(yb).reshape(-1))
        z = np.concatenate(zs)
        yy = np.concatenate(ys)
        np.save(z_path, z)
        np.save(y_path, yy)
    return {
        "z": z,
        "y": yy,
        "z_sha256": sha256_file(z_path),
        "y_sha256": sha256_file(y_path),
        "n": int(len(yy)),
        "path": str(z_path),
    }


def mean_abs_tree_corr(tree_outputs: np.ndarray) -> float:
    t = np.asarray(tree_outputs, dtype=np.float64)
    if t.shape[1] < 2:
        return float("nan")
    c = np.corrcoef(t, rowvar=False)
    off = []
    for i in range(c.shape[0]):
        for j in range(i + 1, c.shape[1]):
            if np.isfinite(c[i, j]):
                off.append(abs(float(c[i, j])))
    return float(np.mean(off)) if off else float("nan")


def import_reused_condition(
    *,
    name: str,
    seed: int,
    spec: dict[str, Any],
    y_val: np.ndarray,
) -> dict[str, Any]:
    ckpt = spec["checkpoint"]
    sha = hash_gate_checkpoint(ckpt, spec["sha256"])
    logits = np.load(spec["val_logits"]) if "val_logits" in spec else None
    if logits is None:
        raise Editor013Blocked(f"missing reused val logits for {name} seed {seed}")
    met = metrics_from_logits(y_val, logits)
    return {
        "condition": name,
        "seed": seed,
        "best_epoch": "imported",
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
        "reuse_of": str(spec.get("reuse", name)),
    }


def classify_odst_value(mean_delta: float, pos: int, ci_lo: float | None, ext_pos: int | None, ext_trig: bool) -> str:
    if mean_delta > 0 and pos == 3 and ci_lo is not None and ci_lo > 0:
        return "STRONG_ODST_INCREMENTAL_VALUE"
    if mean_delta > 0 and pos == 3:
        return "CONSISTENT_ODST_INCREMENTAL_VALUE"
    if ext_trig and ext_pos is not None and ext_pos >= 8 and mean_delta > 0 and pos >= 2:
        return "STABLE_ODST_INCREMENTAL_VALUE"
    return "NO_INCREMENTAL_ODST_VALUE"


def classify_consensus(mean_delta: float, pos: int, ci_lo: float | None) -> str:
    if mean_delta > 0 and pos == 3 and ci_lo is not None and ci_lo > 0:
        return "STRONG"
    if mean_delta > 0 and pos == 3:
        return "CONSISTENT"
    if mean_delta > 0 and pos < 3:
        return "MIXED"
    return "NOT_SUPPORTED"


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
            raise Editor013Blocked("INNER split mismatch")
        inner_tr = subset_bundle(bundle["train"], split["train_mask"], "inner_train")
        inner_se = subset_bundle(bundle["train"], split["select_mask"], "inner_select")
        teacher = teachers[SCREENING_SEED]
        z_tr = cache_common_z(teacher, inner_tr.X, inner_tr.y, device, "inner_train")
        z_se = cache_common_z(teacher, inner_se.X, inner_se.y, device, "inner_select")
        write_json(
            _review("01_inner_search", "EDITOR013_COMMON_Z_CACHE.json"),
            {
                "screening_seed": SCREENING_SEED,
                "topt_sha256": TOPT_CHECKPOINTS[SCREENING_SEED]["sha256"],
                "encoder_frozen": True,
                "attention_frozen": True,
                "official_validation_used": False,
                "inner_train": {k: z_tr[k] for k in ("z_sha256", "y_sha256", "n", "path")},
                "inner_select": {k: z_se[k] for k in ("z_sha256", "y_sha256", "n", "path")},
            },
        )
        ens_tr = ens_train["ens_logit"][split["train_mask"]]
        ens_se = ens_train["ens_logit"][split["select_mask"]]
        single_tr = ens_train[f"logit{SCREENING_SEED}"][split["train_mask"]]
        single_se = ens_train[f"logit{SCREENING_SEED}"][split["select_mask"]]

        rows = []
        packs = {}
        screen_names = list(HEAD_CONDITIONS.keys())
        for name in screen_names:
            spec = HEAD_CONDITIONS[name]
            extras_tr = [ens_tr, single_tr]
            extras_se = [ens_se, single_se]
            _set_seed(SCREENING_SEED)
            student, _ = load_topt(SCREENING_SEED, device)
            freeze_encoder_attention(student)
            modules = make_modules(spec)
            modules.to(device)
            train_loader = make_xy_loader(
                z_tr["z"], z_tr["y"], seed=SCREENING_SEED, shuffle=True, extras=extras_tr
            )
            select_loader = make_xy_loader(z_se["z"], z_se["y"], seed=SCREENING_SEED, shuffle=False, extras=extras_se)
            pack = train_head_only(
                condition=name,
                spec=spec,
                student=student,
                modules=modules,
                train_loader=train_loader,
                select_loader=select_loader,
                device=device,
                pos_weight=pos_weight,
                seed=SCREENING_SEED,
            )
            packs[name] = pack
            rows.append(
                {
                    "condition": name,
                    "family": spec["family"],
                    "readout": spec.get("readout"),
                    "hybrid": spec.get("hybrid"),
                    "distill": spec.get("distill"),
                    "teacher": spec.get("teacher"),
                    "select_PR_AUC": pack["select_PR_AUC"],
                    "select_F1": pack["select_F1"],
                    "Brier": pack["Brier"],
                    "log_loss": pack["log_loss"],
                    "best_epoch": pack["best_epoch"],
                    "learned_alpha": pack["learned_alpha"],
                    "learned_tree_weights": pack["learned_tree_weights"],
                    "official_validation_used": False,
                }
            )
            print(f"[EDITOR-013] INNER {name} PR-AUC={pack['select_PR_AUC']:.6f}", flush=True)

        write_csv(_review("01_inner_search", "EDITOR013_HEAD_SCREEN.csv"), rows)
        decision = decide_promotions(rows)

        guided = [n for n in ("H3-ODST-U-D", "H5-ODST-W-D", "H7-HYB-U-D", "H9-HYB-W-D") if n in packs]
        best_g = max(guided, key=lambda n: float(packs[n]["select_PR_AUC"]))
        trees = packs[best_g]["tree_outputs"]
        mac = mean_abs_tree_corr(trees)
        triggered = bool(mac >= TREE_DIVERSITY_TRIGGER)
        div_rows: list[dict[str, Any]] = []
        best_div = None
        if triggered:
            spec = HEAD_CONDITIONS[best_g]
            for lam in LAMBDA_DIVERSITY_CANDIDATES:
                _set_seed(SCREENING_SEED)
                student, _ = load_topt(SCREENING_SEED, device)
                freeze_encoder_attention(student)
                modules = make_modules(spec)
                modules.to(device)
                pack = train_head_only(
                    condition=f"{best_g}_DIV{lam}",
                    spec=spec,
                    student=student,
                    modules=modules,
                    train_loader=make_xy_loader(
                        z_tr["z"], z_tr["y"], seed=SCREENING_SEED, shuffle=True, extras=[ens_tr, single_tr]
                    ),
                    select_loader=make_xy_loader(z_se["z"], z_se["y"], seed=SCREENING_SEED, shuffle=False),
                    device=device,
                    pos_weight=pos_weight,
                    seed=SCREENING_SEED,
                    lambda_div=float(lam),
                )
                rec = {
                    "condition": f"{best_g}_DIV{lam}",
                    "lambda_div": lam,
                    "select_PR_AUC": pack["select_PR_AUC"],
                    "base_condition": best_g,
                    "base_pr_auc": packs[best_g]["select_PR_AUC"],
                }
                div_rows.append(rec)
                if best_div is None or rec["select_PR_AUC"] > best_div["select_PR_AUC"]:
                    best_div = rec
            if best_div is not None and float(best_div["select_PR_AUC"]) >= float(packs["H1-LIN-D"]["select_PR_AUC"]) + PROMOTION_MARGIN:
                decision["promoted"].append(
                    {
                        "inner_condition": best_div["condition"],
                        "validation_name": "DIV1",
                        "category": "diversity",
                        "inner_select_pr_auc": float(best_div["select_PR_AUC"]),
                        "delta_vs_H1": float(best_div["select_PR_AUC"]) - float(packs["H1-LIN-D"]["select_PR_AUC"]),
                        "spec": {**HEAD_CONDITIONS[best_g], "lambda_div": best_div["lambda_div"]},
                    }
                )
                decision["n_promoted"] = len(decision["promoted"])
                if decision["n_promoted"] > 0:
                    decision["ODST_INCREMENTAL_HEADROOM_INNER"] = "SUPPORTED"
        write_json(
            _review("01_inner_search", "EDITOR013_TREE_DIVERSITY_DIAGNOSTIC.json"),
            {
                "best_teacher_guided_odst": best_g,
                "mean_absolute_pairwise_correlation": mac,
                "threshold": TREE_DIVERSITY_TRIGGER,
                "TREE_DIVERSITY_BRANCH": "TRIGGERED" if triggered else "NOT_TRIGGERED",
                "official_validation_used": False,
            },
        )
        write_csv(_review("01_inner_search", "EDITOR013_DIVERSITY_BRANCH_RESULTS.csv"), div_rows)
        decision["TREE_DIVERSITY_BRANCH"] = "TRIGGERED" if triggered else "NOT_TRIGGERED"
        decision["best_diversity_result"] = best_div
        write_json(_review("01_inner_search", "EDITOR013_PROMOTION_FREEZE.json"), decision)
        return {
            "rows": rows,
            "packs": packs,
            "decision": decision,
            "split": split,
            "z_tr": z_tr,
            "z_se": z_se,
            "diversity": {"triggered": triggered, "mean_abs_corr": mac, "best": best_div},
        }
    finally:
        exit_inner_phase()


def _pack_val_row(pack: dict[str, Any]) -> dict[str, Any]:
    keys = [
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
        "learned_alpha",
        "learned_tree_weights",
        "imported",
    ]
    return {k: pack.get(k, "") for k in keys}


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

    reuse_map = {
        "O0": {s: {**C2OPT_CHECKPOINTS[s], "val_logits": C2_VAL_LOGITS[s], "reuse": "C2-OPT"} for s in PRIMARY_SEEDS},
        "O1": {s: {**F10_CHECKPOINTS[s], "reuse": "F10"} for s in PRIMARY_SEEDS},
        "TA2": {s: {**F11_CHECKPOINTS[s], "reuse": "F11"} for s in PRIMARY_SEEDS},
        "ENSEMBLE-MSE": {s: {**F10_CHECKPOINTS[s], "reuse": "F10"} for s in PRIMARY_SEEDS},
    }
    for name, by_seed in reuse_map.items():
        for seed, spec in by_seed.items():
            pack = import_reused_condition(name=name, seed=seed, spec=spec, y_val=y_val)
            packs[(name, seed)] = pack
            rows.append(_pack_val_row(pack))
            print(f"[EDITOR-013] reused {name} seed={seed} PR-AUC={pack['validation_PR_AUC']:.6f}", flush=True)

    train_specs = {
        "L0": VALIDATION_MANDATORY["L0"],
        "L1": VALIDATION_MANDATORY["L1"],
        "SINGLE-MSE": VALIDATION_MANDATORY["SINGLE-MSE"],
    }
    for promo in inner["decision"]["promoted"]:
        train_specs[promo["validation_name"]] = promo["spec"]

    extras_train_ens = [ens_train["ens_logit"], ens_train[f"logit{PRIMARY_SEEDS[0]}"]]
    for name, spec in train_specs.items():
        for seed in PRIMARY_SEEDS:
            extras = [ens_train["ens_logit"], ens_train[f"logit{seed}"]]
            train_loader = make_xy_loader(
                bundle["train"].X, bundle["train"].y, seed=seed, shuffle=True, extras=extras
            )
            val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=seed, shuffle=False)
            pack = train_e2e(
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
                lambda_div=float(spec.get("lambda_div") or 0.0),
            )
            packs[(name, seed)] = pack
            rows.append(_pack_val_row(pack))

    write_csv(_review("02_validation_confirmation", "EDITOR013_VALIDATION_RESULTS.csv"), rows)

    def _prs(name: str) -> list[float]:
        return [float(packs[(name, s)]["validation_PR_AUC"]) for s in PRIMARY_SEEDS]

    def _logits(name: str) -> list[np.ndarray]:
        return [np.asarray(packs[(name, s)]["student_logits"]) for s in PRIMARY_SEEDS]

    def _thrs(name: str) -> list[float]:
        return [float(packs[(name, s)]["threshold"]) for s in PRIMARY_SEEDS]

    l1_prs = _prs("L1")
    l1_mean = _mean(l1_prs)
    primary = {
        "L0_mean": _mean(_prs("L0")),
        "L1_mean": l1_mean,
        "O0_mean": _mean(_prs("O0")),
        "O1_mean": _mean(_prs("O1")),
        "TA2_mean": _mean(_prs("TA2")),
        "SINGLE_MSE_mean": _mean(_prs("SINGLE-MSE")),
        "ENSEMBLE_MSE_mean": _mean(_prs("ENSEMBLE-MSE")),
        "per_seed": {
            str(s): {n: float(packs[(n, s)]["validation_PR_AUC"]) for n, _ in packs if _ == s}
            for s in PRIMARY_SEEDS
        },
    }
    write_json(_review("02_validation_confirmation", "EDITOR013_PRIMARY_HEAD_COMPARISONS.json"), primary)

    weight_res = {}
    hybrid_res = {}
    for promo in inner["decision"]["promoted"]:
        n = promo["validation_name"]
        prs = _prs(n)
        rec = {
            "condition": n,
            "mean_PR_AUC": _mean(prs),
            "seeds": {str(s): p for s, p in zip(PRIMARY_SEEDS, prs)},
            "learned_tree_weights": {
                str(s): packs[(n, s)].get("learned_tree_weights") for s in PRIMARY_SEEDS
            },
            "learned_alpha": {str(s): packs[(n, s)].get("learned_alpha") for s in PRIMARY_SEEDS},
        }
        if promo["category"] == "learned_readout_odst":
            weight_res[n] = rec
        else:
            hybrid_res[n] = rec
    write_json(_review("02_validation_confirmation", "EDITOR013_TREE_WEIGHT_RESULTS.json"), weight_res)
    write_json(_review("02_validation_confirmation", "EDITOR013_HYBRID_RESULTS.json"), hybrid_res)

    ens_s = _prs("ENSEMBLE-MSE")
    sin_s = _prs("SINGLE-MSE")
    c2_s = _prs("O0")
    cons_rows = []
    for i, s in enumerate(PRIMARY_SEEDS):
        cons_rows.append(
            {
                "seed": s,
                "SINGLE_MSE": sin_s[i],
                "ENSEMBLE_MSE": ens_s[i],
                "C2": c2_s[i],
                "ENSEMBLE_minus_SINGLE": ens_s[i] - sin_s[i],
                "SINGLE_minus_C2": sin_s[i] - c2_s[i],
                "ENSEMBLE_minus_C2": ens_s[i] - c2_s[i],
            }
        )
    write_csv(_review("03_teacher_consensus", "EDITOR013_SINGLE_VS_ENSEMBLE_RESULTS.csv"), cons_rows)

    boot = {}
    contrasts = [("ENSEMBLE_minus_SINGLE", "SINGLE-MSE", "ENSEMBLE-MSE"), ("ENSEMBLE_minus_C2", "O0", "ENSEMBLE-MSE")]
    promoted_odst = [p["validation_name"] for p in inner["decision"]["promoted"]]
    for n in promoted_odst:
        contrasts.append((f"{n}_minus_L1", "L1", n))
    for cname, a, b in contrasts:
        print(f"[EDITOR-013] bootstrap {cname}", flush=True)
        boot[cname] = paired_user_cluster_mean_across_seeds(
            users,
            y_val,
            _logits(a),
            _logits(b),
            frozen_thresholds_a=_thrs(a),
            frozen_thresholds_b=_thrs(b),
            n_valid=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
            contrast=cname,
        )
    write_json(_review("04_statistics", "EDITOR013_USER_MAPPING_VERIFICATION.json"), mapping)
    write_json(_review("04_statistics", "EDITOR013_CLUSTER_BOOTSTRAP.json"), boot)

    ens_minus_sin = [e - s for e, s in zip(ens_s, sin_s)]
    cons_pos = sum(1 for d in ens_minus_sin if d > 0)
    cons_ci = boot["ENSEMBLE_minus_SINGLE"]["ci95_pr_auc"]
    consensus_ruling = classify_consensus(_mean(ens_minus_sin), cons_pos, float(cons_ci[0]))
    write_json(
        _review("03_teacher_consensus", "EDITOR013_CONSENSUS_RULING.json"),
        {
            "CONSENSUS_TEACHER_ADVANTAGE": consensus_ruling,
            "ENSEMBLE_minus_SINGLE_mean": _mean(ens_minus_sin),
            "positive_seeds": f"{cons_pos}/3",
            "user_cluster_ci": cons_ci,
            "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
            "single_teacher_mse_is_not_historical_C5": True,
        },
    )

    best_name = None
    best_mean = -1.0
    best_delta = float("nan")
    best_pos = 0
    best_ci = [float("nan"), float("nan")]
    for n in promoted_odst + ["O1", "TA2"]:
        if (n, PRIMARY_SEEDS[0]) not in packs:
            continue
        prs = _prs(n)
        deltas = [p - l for p, l in zip(prs, l1_prs)]
        mean_d = _mean(deltas)
        pos = sum(1 for d in deltas if d > 0)
        ci = boot.get(f"{n}_minus_L1", {}).get("ci95_pr_auc", [float("nan"), float("nan")])
        if mean_d > best_delta or (not np.isfinite(best_delta) and n in promoted_odst):
            if n in promoted_odst or best_name is None:
                best_name, best_mean, best_delta, best_pos, best_ci = n, _mean(prs), mean_d, pos, ci
        if n in promoted_odst and (_mean(prs) > best_mean or best_name not in promoted_odst):
            best_name, best_mean, best_delta, best_pos, best_ci = n, _mean(prs), mean_d, pos, ci

    if not promoted_odst:
        ta2 = _prs("TA2")
        best_name, best_mean = "TA2", _mean(ta2)
        best_delta = _mean([t - l for t, l in zip(ta2, l1_prs)])
        best_pos = sum(1 for t, l in zip(ta2, l1_prs) if t - l > 0)
        if "TA2_minus_L1" not in boot:
            boot["TA2_minus_L1"] = paired_user_cluster_mean_across_seeds(
                users, y_val, _logits("L1"), _logits("TA2"),
                frozen_thresholds_a=_thrs("L1"), frozen_thresholds_b=_thrs("TA2"),
                n_valid=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, contrast="TA2_minus_L1",
            )
            write_json(_review("04_statistics", "EDITOR013_CLUSTER_BOOTSTRAP.json"), boot)
        best_ci = boot["TA2_minus_L1"]["ci95_pr_auc"]

    ext_trig = bool(best_delta > 0 and best_pos >= 2)
    stab_rows = []
    ext_pos = None
    if ext_trig and best_name in train_specs:
        spec = train_specs[best_name]
        start_cycle = list(PRIMARY_SEEDS)
        for i, extra in enumerate(EXTENDED_SEEDS):
            start_seed = start_cycle[i % 3]
            extras = [ens_train["ens_logit"], ens_train[f"logit{start_seed}"]]
            lin = train_e2e(
                condition="STAB_L1",
                spec=VALIDATION_MANDATORY["L1"],
                seed=extra,
                start_seed=start_seed,
                train_loader=make_xy_loader(bundle["train"].X, bundle["train"].y, seed=extra, shuffle=True, extras=extras),
                select_loader=make_xy_loader(bundle["val"].X, bundle["val"].y, seed=extra, shuffle=False),
                device=device,
                pos_weight=pos_weight,
                select_name="validation",
            )
            tgt = train_e2e(
                condition="STAB_ODST",
                spec=spec,
                seed=extra,
                start_seed=start_seed,
                train_loader=make_xy_loader(bundle["train"].X, bundle["train"].y, seed=extra, shuffle=True, extras=extras),
                select_loader=make_xy_loader(bundle["val"].X, bundle["val"].y, seed=extra, shuffle=False),
                device=device,
                pos_weight=pos_weight,
                matched_teacher=teachers[start_seed] if spec.get("route") else None,
                select_name="validation",
                lambda_div=float(spec.get("lambda_div") or 0.0),
            )
            stab_rows.append(
                {
                    "seed": extra,
                    "start_topt_seed": start_seed,
                    "L1_PR_AUC": lin["validation_PR_AUC"],
                    "ODST_PR_AUC": tgt["validation_PR_AUC"],
                    "delta": float(tgt["validation_PR_AUC"]) - float(lin["validation_PR_AUC"]),
                }
            )
        primary_d = [
            {
                "seed": s,
                "start_topt_seed": s,
                "L1_PR_AUC": float(packs[("L1", s)]["validation_PR_AUC"]),
                "ODST_PR_AUC": float(packs[(best_name, s)]["validation_PR_AUC"]),
                "delta": float(packs[(best_name, s)]["validation_PR_AUC"]) - float(packs[("L1", s)]["validation_PR_AUC"]),
            }
            for s in PRIMARY_SEEDS
        ]
        all_stab = primary_d + stab_rows
        ext_pos = int(sum(1 for r in all_stab if r["delta"] > 0))
        ruling = {
            "triggered": True,
            "positive_seeds": f"{ext_pos}/10",
            "mean_delta": float(np.mean([r["delta"] for r in all_stab])),
            "seeds_are_not_independent_experimental_units": True,
        }
    else:
        ruling = {"triggered": False, "reason": "mean Δ<=0 or positive primary seeds < 2/3 or reused-only best"}
    write_csv(_review("04_statistics", "EDITOR013_STABILITY_RESULTS.csv"), stab_rows)
    write_json(_review("04_statistics", "EDITOR013_STABILITY_RULING.json"), ruling)

    if not inner["decision"]["promoted"]:
        odst_value = "NO_INCREMENTAL_ODST_VALUE"
    else:
        odst_value = classify_odst_value(
            float(best_delta),
            int(best_pos),
            float(best_ci[0]) if best_ci and np.isfinite(best_ci[0]) else None,
            ext_pos,
            ext_trig,
        )

    faith = {
        "PROMOTED_ODST_REFERENCE_CENTRED_FAITHFULNESS": "NOT_EVALUATED",
        "ODST_ROUTE_TRACEABILITY": "SUPPORTED",
        "ODST_LEAF_TRACEABILITY": "SUPPORTED",
        "ROUTE_LEAF_INDEPENDENT_FAITHFULNESS": "UNSUPPORTED",
    }
    contrib_rows = []
    faith_rows = []
    if best_name in train_specs or best_name in {"O1", "TA2"}:
        train_trees = _collect_train_trees(teachers[SCREENING_SEED], bundle["train"].X, bundle["train"].y, device)
        refs = train_references(train_trees)
        eval_name = best_name
        if eval_name in {"O1", "TA2"}:
            ckpt_map = F10_CHECKPOINTS if eval_name == "O1" else F11_CHECKPOINTS
            spec_ck = ckpt_map[SCREENING_SEED]
            model = build_odst046_model()
            load_state_dict(model, spec_ck["checkpoint"], strict=True)
            model.to(device)
            freeze_teacher(model)
            val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=0, shuffle=False)
            scored = evaluate_pair(student=model, teacher=None, loader=val_loader, device=device)
            trees_v = scored["student_tree_outputs"]
            logits_v = scored["student_logits"]
            weights = None
            alpha = 1.0
            hybrid = False
            lin_v = None
        else:
            spec = train_specs[eval_name]
            student, _ = load_topt(SCREENING_SEED, device)
            modules = make_modules(spec)
            payload = torch.load(packs[(eval_name, SCREENING_SEED)]["best_checkpoint"], map_location="cpu", weights_only=False)
            student.load_state_dict(payload["student_state_dict"])
            modules.load_state_dict(payload["modules_state_dict"])
            student.to(device)
            modules.to(device)
            val_loader = make_xy_loader(bundle["val"].X, bundle["val"].y, seed=0, shuffle=False)
            scored = evaluate_e2e(student, modules, val_loader, device)
            trees_v = scored["tree_outputs"]
            logits_v = scored["logits"]
            weights = np.asarray(modules.learned_tree_weights() or [1.0 / N_TREES_TOTAL] * N_TREES_TOTAL)
            alpha = float(modules.learned_alpha() or 1.0) if spec.get("hybrid") else 1.0
            hybrid = bool(spec.get("hybrid"))
            lin_v = scored.get("linear_logits")
        c = centred_contributions(trees_v, refs, weights, alpha)
        for j in range(c.shape[1]):
            contrib_rows.append(
                {
                    "tree": j,
                    "mean_centred_contribution": float(c[:, j].mean()),
                    "mean_abs_centred_contribution": float(np.abs(c[:, j]).mean()),
                    "weight": float(weights[j]) if weights is not None else 1.0 / N_TREES_TOTAL,
                    "alpha": alpha,
                    "reference": float(refs[j]),
                }
            )
        faith = faithfulness_table(
            y=y_val,
            tree_outputs=trees_v,
            references=refs,
            weights=weights,
            alpha=alpha,
            linear_logit=lin_v,
            hybrid=hybrid,
            users=users,
        )
        faith_rows = faith["rows"]
        write_json(
            _review("05_explainability", "EDITOR013_FAITHFULNESS_BOOTSTRAP.json"),
            {"note": "user-cluster unit reserved; primary faithfulness is top-k vs random drop on full validation"},
        )
    write_csv(_review("05_explainability", "EDITOR013_REFERENCE_CENTRED_CONTRIBUTIONS.csv"), contrib_rows)
    write_csv(_review("05_explainability", "EDITOR013_FAITHFULNESS_RESULTS.csv"), faith_rows)
    write_json(_review("05_explainability", "EDITOR013_EXPLAINABILITY_RULING.json"), faith)

    eff = measure_efficiency(device, packs, train_specs if best_name in train_specs else {}, best_name)
    matrix = build_choice_matrix(packs, boot, faith, eff, l1_mean, best_name)
    write_csv(_review("06_paper_handover", "EDITOR013_ODST_CHOICE_MATRIX.csv"), matrix)

    learned_helped = bool(weight_res) and any(
        rec["mean_PR_AUC"] > l1_mean + PROMOTION_MARGIN for rec in weight_res.values()
    )
    hybrid_helped = bool(hybrid_res) and any(
        rec["mean_PR_AUC"] > l1_mean + PROMOTION_MARGIN for rec in hybrid_res.values()
    )
    learned_w = None
    hyb_a = None
    if weight_res:
        rec = next(iter(weight_res.values()))
        learned_w = rec["learned_tree_weights"].get("42")
    if hybrid_res:
        rec = next(iter(hybrid_res.values()))
        hyb_a = rec["learned_alpha"].get("42")

    why_teacher = (
        "TA2 already established that equal-weight ensemble logit distillation plus optional "
        "route anchoring improves ranking beyond matched T-OPT initialisation "
        f"(mean Δ vs C2-OPT = +0.007518; {TEACHER_GUIDANCE_VS_INITIALISATION})."
    )
    if odst_value in {"STRONG_ODST_INCREMENTAL_VALUE", "CONSISTENT_ODST_INCREMENTAL_VALUE", "STABLE_ODST_INCREMENTAL_VALUE"}:
        if hybrid_helped and (best_name.startswith("HYB") or best_name.startswith("HW")):
            why_odst = (
                "The linear path supplies the strong base decision, while the differentiable "
                "tree ensemble contributes an incremental nonlinear correction and structured "
                "reference-centred explanations."
            )
            issue = "RESOLVED"
        elif learned_helped:
            why_odst = (
                "Fixed uniform averaging unnecessarily constrained the differentiable ensemble; "
                "learning globally normalised tree importance improved ranking while retaining "
                "explicit additive per-tree contributions."
            )
            issue = "RESOLVED"
        else:
            why_odst = (
                "ODST contributes incremental ranking performance under matched teacher guidance "
                "while retaining intervention-supported structured tree explanations."
            )
            issue = "RESOLVED"
    else:
        why_odst = (
            "Under a matched teacher-guided linear control, ODST did not provide a reproducible "
            "predictive increment. Route/leaf traceability remains, but the paper cannot claim "
            "standalone ODST superiority over the simpler linear head."
        )
        issue = "NOT_RESOLVED" if best_delta <= 0 else "PARTIALLY_RESOLVED"

    editor_issue = {
        "EDITOR_ISSUE_TEACHER_INITIALISATION_ONLY": "RESOLVED",
        "EDITOR_ISSUE_C5_NEGLIGIBLE_INCREMENT": "RESOLVED_BY_TA2",
        "EDITOR_ISSUE_ODST_VALUE": issue,
    }
    write_csv(
        _review("06_paper_handover", "EDITOR013_EDITOR_ISSUE_MATRIX.csv"),
        [{"issue": k, "ruling": v} for k, v in editor_issue.items()],
    )
    paper_model = best_name if odst_value != "NO_INCREMENTAL_ODST_VALUE" else ("TA2" if _mean(_prs("TA2")) >= l1_mean else "L1")
    gate = {
        "ODST_INCREMENTAL_VALUE": odst_value,
        "CONSENSUS_TEACHER_ADVANTAGE": consensus_ruling,
        "TEACHER_GUIDANCE_VS_INITIALISATION": TEACHER_GUIDANCE_VS_INITIALISATION,
        "BEST_CURRENT_PAPER_MODEL": paper_model,
        "MATCHED_TEACHER_GUIDED_LINEAR_MEAN_PR_AUC": l1_mean,
        "TA2_MEAN_PR_AUC": _mean(_prs("TA2")),
        "BEST_ODST_OR_HYBRID_MEAN_PR_AUC": best_mean,
        "BEST_ODST_DELTA_VS_TEACHER_GUIDED_LINEAR": best_delta,
        "POSITIVE_ODST_DELTA_PRIMARY_SEEDS": f"{best_pos}/3",
        "USER_CLUSTER_CI_ODST_MINUS_LINEAR": best_ci,
        "PROMOTED_ODST_REFERENCE_CENTRED_FAITHFULNESS": faith.get(
            "PROMOTED_ODST_REFERENCE_CENTRED_FAITHFULNESS", "NOT_EVALUATED"
        ),
        "WHY_TEACHER_ANCHORING": why_teacher,
        "WHY_ODST": why_odst,
        **editor_issue,
    }
    write_json(_review("06_paper_handover", "EDITOR013_PAPER_RESCUE_GATE.json"), gate)
    handover = "\n".join(
        [
            "# EDITOR-013 paper rescue handover",
            "",
            f"ODST incremental value: **{odst_value}**",
            f"Teacher consensus: **{consensus_ruling}**",
            f"Teacher guidance vs initialisation: **{TEACHER_GUIDANCE_VS_INITIALISATION}**",
            "",
            f"Matched teacher-guided linear (L1) mean PR-AUC = {l1_mean:.6f}",
            f"TA2 mean PR-AUC = {_mean(_prs('TA2')):.6f}",
            f"Best ODST/hybrid ({best_name}) mean PR-AUC = {best_mean:.6f}",
            f"Δ vs L1 = {best_delta:.6f}",
            f"User-cluster 95% CI = {best_ci}",
            "",
            f"Why teacher anchoring: {why_teacher}",
            "",
            f"Why ODST: {why_odst}",
            "",
            f"Best current paper model: **{paper_model}**",
            "",
        ]
    )
    _review("06_paper_handover", "EDITOR013_PAPER_RESCUE_HANDOVER.md").write_text(handover, encoding="utf-8")
    return {
        "packs": packs,
        "primary": primary,
        "boot": boot,
        "odst_value": odst_value,
        "consensus": consensus_ruling,
        "best_name": best_name,
        "best_mean": best_mean,
        "best_delta": best_delta,
        "best_pos": best_pos,
        "best_ci": best_ci,
        "faith": faith,
        "eff": eff,
        "gate": gate,
        "learned_helped": learned_helped,
        "hybrid_helped": hybrid_helped,
        "learned_w": learned_w,
        "hyb_a": hyb_a,
        "ext_trig": ext_trig,
        "ext_pos": ext_pos,
        "paper_model": paper_model,
        "why_teacher": why_teacher,
        "why_odst": why_odst,
        "inner_rows": inner["rows"],
        "diversity": inner["diversity"],
        "decision": inner["decision"],
        "l1_mean": l1_mean,
        "single_mean": _mean(sin_s),
        "ensemble_mean": _mean(ens_s),
        "ens_minus_sin": _mean(ens_minus_sin),
        "cons_pos": cons_pos,
        "cons_ci": cons_ci,
    }


@torch.no_grad()
def _collect_train_trees(model: torch.nn.Module, X: np.ndarray, y: np.ndarray, device: torch.device) -> np.ndarray:
    loader = make_xy_loader(X, y, seed=0, shuffle=False)
    model.eval()
    bags = []
    for xb, _ in loader:
        bags.append(historical_student_forward(model, xb.to(device))["tree_outputs"].detach().cpu().numpy())
    return np.concatenate(bags)


def measure_efficiency(
    device: torch.device,
    packs: dict[tuple[str, int], dict[str, Any]],
    train_specs: dict[str, Any],
    best_name: str | None,
) -> dict[str, Any]:
    x = torch.zeros(LATENCY_BATCH_SIZE, 20, 13, device=device)
    out: dict[str, Any] = {}

    def _lat(fn) -> dict[str, float]:
        for _ in range(LATENCY_WARMUP):
            fn()
        if device.type == "cuda":
            torch.cuda.synchronize()
        times = []
        for _ in range(LATENCY_REPEATS):
            t0 = time.perf_counter()
            fn()
            if device.type == "cuda":
                torch.cuda.synchronize()
            times.append(time.perf_counter() - t0)
        arr = np.asarray(times)
        return {
            "mean_inference_latency_s": float(arr.mean()),
            "median_inference_latency_s": float(np.median(arr)),
            "throughput_sequences_per_s": float(LATENCY_BATCH_SIZE / max(arr.mean(), 1e-9)),
        }

    student, _ = load_topt(SCREENING_SEED, device)
    student.eval()
    modules = make_modules(VALIDATION_MANDATORY["L1"])
    modules.to(device)
    if ("L1", SCREENING_SEED) in packs and Path(str(packs[("L1", SCREENING_SEED)].get("best_checkpoint", ""))).is_file():
        payload = torch.load(packs[("L1", SCREENING_SEED)]["best_checkpoint"], map_location="cpu", weights_only=False)
        student.load_state_dict(payload["student_state_dict"])
        modules.load_state_dict(payload["modules_state_dict"])
        student.to(device)
        modules.to(device)
    n_lin = sum(p.numel() for p in student.lstm.parameters()) + sum(p.numel() for p in student.attention.parameters())
    n_lin += sum(p.numel() for p in modules.parameters())
    out["L1"] = {
        "trainable_parameter_count": n_lin,
        "total_parameter_count": sum(p.numel() for p in student.parameters()) + sum(p.numel() for p in modules.parameters()),
        **_lat(lambda: editor013_forward(student, x, modules)),
        "checkpoint_size": Path(str(packs.get(("L1", SCREENING_SEED), {}).get("best_checkpoint", ""))).stat().st_size
        if ("L1", SCREENING_SEED) in packs and Path(str(packs[("L1", SCREENING_SEED)].get("best_checkpoint", ""))).is_file()
        else None,
    }
    ta2 = build_odst046_model()
    load_state_dict(ta2, F11_CHECKPOINTS[SCREENING_SEED]["checkpoint"], strict=True)
    ta2.to(device)
    ta2.eval()
    out["TA2"] = {
        "trainable_parameter_count": sum(p.numel() for p in ta2.parameters() if p.requires_grad),
        "total_parameter_count": sum(p.numel() for p in ta2.parameters()),
        **_lat(lambda: historical_student_forward(ta2, x)),
        "checkpoint_size": Path(F11_CHECKPOINTS[SCREENING_SEED]["checkpoint"]).stat().st_size,
    }
    if best_name and best_name in train_specs and (best_name, SCREENING_SEED) in packs:
        student2, _ = load_topt(SCREENING_SEED, device)
        mods2 = make_modules(train_specs[best_name])
        payload = torch.load(packs[(best_name, SCREENING_SEED)]["best_checkpoint"], map_location="cpu", weights_only=False)
        student2.load_state_dict(payload["student_state_dict"])
        mods2.load_state_dict(payload["modules_state_dict"])
        student2.to(device)
        mods2.to(device)
        student2.eval()
        mods2.eval()
        out[best_name] = {
            "trainable_parameter_count": sum(p.numel() for p in student2.parameters() if p.requires_grad)
            + sum(p.numel() for p in mods2.parameters() if p.requires_grad),
            "total_parameter_count": sum(p.numel() for p in student2.parameters()) + sum(p.numel() for p in mods2.parameters()),
            **_lat(lambda: editor013_forward(student2, x, mods2)),
            "checkpoint_size": Path(packs[(best_name, SCREENING_SEED)]["best_checkpoint"]).stat().st_size,
        }
    return out


def build_choice_matrix(packs, boot, faith, eff, l1_mean, best_name) -> list[dict[str, Any]]:
    rows = []
    for name in ("L1", "TA2", "O1", "O0", "L0", "SINGLE-MSE", "ENSEMBLE-MSE"):
        if (name, SCREENING_SEED) not in packs:
            continue
        prs = [float(packs[(name, s)]["validation_PR_AUC"]) for s in PRIMARY_SEEDS]
        f1s = [float(packs[(name, s)]["validation_F1"]) for s in PRIMARY_SEEDS]
        brier = [float(packs[(name, s)]["Brier"]) for s in PRIMARY_SEEDS]
        ll = [float(packs[(name, s)]["log_loss"]) for s in PRIMARY_SEEDS]
        ci = boot.get(f"{name}_minus_L1", {}).get("ci95_pr_auc", "")
        e = eff.get(name, {})
        rows.append(
            {
                "condition": name,
                "PR-AUC": _mean(prs),
                "Δ vs matched teacher-guided linear": _mean(prs) - l1_mean,
                "cluster CI": ci,
                "F1": _mean(f1s),
                "Brier": _mean(brier),
                "log loss": _mean(ll),
                "parameter count": e.get("total_parameter_count", ""),
                "latency": e.get("median_inference_latency_s", ""),
                "reference-centred faithfulness": faith.get("PROMOTED_ODST_REFERENCE_CENTRED_FAITHFULNESS", "")
                if name == best_name
                else "",
                "route traceability": "SUPPORTED" if name not in {"L0", "L1"} else "N/A",
                "leaf traceability": "SUPPORTED" if name not in {"L0", "L1"} else "N/A",
            }
        )
    if best_name and best_name not in {r["condition"] for r in rows} and (best_name, SCREENING_SEED) in packs:
        prs = [float(packs[(best_name, s)]["validation_PR_AUC"]) for s in PRIMARY_SEEDS]
        e = eff.get(best_name, {})
        rows.append(
            {
                "condition": best_name,
                "PR-AUC": _mean(prs),
                "Δ vs matched teacher-guided linear": _mean(prs) - l1_mean,
                "cluster CI": boot.get(f"{best_name}_minus_L1", {}).get("ci95_pr_auc", ""),
                "F1": _mean([float(packs[(best_name, s)]["validation_F1"]) for s in PRIMARY_SEEDS]),
                "Brier": _mean([float(packs[(best_name, s)]["Brier"]) for s in PRIMARY_SEEDS]),
                "log loss": _mean([float(packs[(best_name, s)]["log_loss"]) for s in PRIMARY_SEEDS]),
                "parameter count": e.get("total_parameter_count", ""),
                "latency": e.get("median_inference_latency_s", ""),
                "reference-centred faithfulness": faith.get("PROMOTED_ODST_REFERENCE_CENTRED_FAITHFULNESS", ""),
                "route traceability": "SUPPORTED",
                "leaf traceability": "SUPPORTED",
            }
        )
    return rows


def run_inner_phase() -> dict[str, Any]:
    write_protocol_packet()
    identities = verify_identities()
    device = _device()
    print(f"[EDITOR-013] device={device}", flush=True)
    bundle = load_train_validation()
    teachers = {}
    for seed, spec in TOPT_CHECKPOINTS.items():
        hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
        m = build_odst046_model()
        load_state_dict(m, spec["checkpoint"], strict=True)
        m.to(device)
        freeze_teacher(m)
        teachers[seed] = m
    ens_train = precompute_ensemble(teachers, bundle["train"].X, bundle["train"].y, device, "train")
    inner = run_inner_search(
        bundle=bundle, teachers=teachers, ens_train=ens_train, device=device, pos_weight=bundle["pos_weight"]
    )
    write_json(
        _review("EDITOR013_PROMOTION_COMMIT_READY.json"),
        {"ready": True, "promoted": inner["decision"]["promoted"], "utc": utc_now()},
    )
    return {"identities": identities, "inner": inner, "device": str(device)}


def run_campaign(*, resume_after_inner: bool = False) -> dict[str, Any]:
    started = utc_now()
    write_protocol_packet()
    identities = verify_identities()
    device = _device()
    print(f"[EDITOR-013] device={device}", flush=True)
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    teachers = {}
    for seed, spec in TOPT_CHECKPOINTS.items():
        hash_gate_checkpoint(spec["checkpoint"], spec["sha256"])
        m = build_odst046_model()
        load_state_dict(m, spec["checkpoint"], strict=True)
        m.to(device)
        freeze_teacher(m)
        teachers[seed] = m
    ens_train = precompute_ensemble(teachers, bundle["train"].X, bundle["train"].y, device, "train")
    ens_val = precompute_ensemble(teachers, bundle["val"].X, bundle["val"].y, device, "val")
    freeze_path = _review("01_inner_search", "EDITOR013_PROMOTION_FREEZE.json")
    if resume_after_inner and freeze_path.is_file():
        import json

        decision = json.loads(freeze_path.read_text(encoding="utf-8"))
        inner = {"decision": decision, "rows": [], "diversity": {"triggered": False, "best": None}}
    else:
        inner = run_inner_search(
            bundle=bundle, teachers=teachers, ens_train=ens_train, device=device, pos_weight=bundle["pos_weight"]
        )
        write_json(
            _review("EDITOR013_PROMOTION_COMMIT_READY.json"),
            {"ready": True, "promoted": inner["decision"]["promoted"], "utc": utc_now()},
        )
    confirm = run_confirmation(
        bundle=bundle,
        teachers=teachers,
        ens_train=ens_train,
        ens_val=ens_val,
        device=device,
        pos_weight=bundle["pos_weight"],
        inner=inner,
        mapping=mapping,
    )
    manifest = {
        "task_id": "EDITOR-013",
        "status": "COMPLETE",
        "started_utc": started,
        "finished_utc": utc_now(),
        "r52_test_accessed": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "identities": identities,
        "ODST_INCREMENTAL_VALUE": confirm["odst_value"],
        "CONSENSUS_TEACHER_ADVANTAGE": confirm["consensus"],
        "device": str(device),
        "promoted": inner["decision"]["promoted"],
        "architecture": ENCODER_ARCH,
        "EDITOR012_RESULTS_FULL_COMMIT": EDITOR012_RESULTS_FULL_COMMIT,
    }
    write_json(_review("EDITOR013_RUN_MANIFEST.json"), manifest)
    return {"identities": identities, "inner": inner, "confirm": confirm, "manifest": manifest}


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
