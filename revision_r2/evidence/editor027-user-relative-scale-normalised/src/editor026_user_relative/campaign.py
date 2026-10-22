"""EDITOR-026 campaign. Stage-0 first. Training only after both Stage-0 gates pass."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from editor012_rescue.metrics import metrics_from_logits, sigmoid
from editor017_robustness.constants import FROZEN_CLEAN_PR_AUC
from editor025_r61_autopsy.representation import per_model_separation
from editor025_r61_autopsy.sampling import representation_sample_indices
from editor025_r61_autopsy.scores import distribution_block, ranking_profile

from .bootstrap import ap_lift, pr_auc, pr_auc_from_logits, user_cluster_bootstrap
from .constants import (
    EDITOR024_OUTPUT_REL,
    EDITOR025_RESULTS_COMMIT,
    FEATURE_ORDER,
    G1_UR_FINAL_R52_MIN,
    G2_N_SEEDS_MIN,
    G2_UR_FINAL_SEED_MIN,
    G8_REPRESENTATION_TRANSFER_MIN,
    HISTORICAL_C2OPT_R52_MEAN_PR_AUC,
    MINIMUM_AP_PREVALENCE_LIFT,
    OUTPUT_REL,
    R61_LABEL_VIEW_A,
    R61_LABEL_VIEW_B,
    REPRESENTATION_NEGATIVE_N,
    REVIEW_REL,
    SEEDS,
    SHA256_MANIFEST_NAME,
    STUDENT_MODELS,
    TASK_ID,
    repo_root,
)
from .io_util import write_csv, write_json, write_npy, write_npz, write_text
from .labels import freeze_label_views
from .protocol import freeze_protocol
from .safety import (
    OUTPUT_ROOT,
    REPO_ROOT,
    REVIEW_ROOT,
    Editor026Blocked,
    protocol_freeze_commit,
    r52_model_freeze_commit,
    refuse_r51_r62,
    require_protocol_frozen,
    require_r52_model_frozen,
    require_stage0_pass,
    sha256_file,
    utc_now,
)
from .stage0 import feature_shift_rows, input_signal_packet, reduction_metrics
from .tensors import (
    build_r52_ur_windows,
    build_r61_ur,
    fit_ur_scaler,
    load_frozen_r52_splits,
    load_r52_dense_raw,
    load_r61_bundle_raw,
    scale_by_user,
    transform_r52_user_relative,
)
from .train import (
    load_ur_linear,
    load_ur_odst,
    score_linear_arrays,
    score_odst_arrays,
    train_attention_linear,
    train_ur_linear_student,
    train_ur_odst_student,
    train_ur_teacher,
)


def _log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()


def _mean(xs: list[float]) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def parent_commit_ok() -> str:
    observed = subprocess.check_output(
        ["git", "merge-base", EDITOR025_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    if observed != EDITOR025_RESULTS_COMMIT:
        raise Editor026Blocked(f"SOURCE_GATE FAIL parent {observed} != {EDITOR025_RESULTS_COMMIT}")
    return "PASS"


def run_unit_tests() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_editor026_user_relative.py", "-q"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
    return "PASS" if proc.returncode == 0 else "FAIL"


def sha256_manifest(paths: list[Path], *, repo_root: Path | None = None) -> dict[str, str]:
    root = repo_root or REPO_ROOT
    out: dict[str, str] = {}
    files = [p for p in paths if p.exists() and p.is_file() and p.name != SHA256_MANIFEST_NAME]
    files.sort(key=lambda p: str(p.relative_to(root)).replace("\\", "/"))
    for p in files:
        out[str(p.relative_to(root)).replace("\\", "/")] = sha256_file(p)
    return out


def write_sha256_manifest_last() -> dict[str, str]:
    targets = list(REVIEW_ROOT.rglob("*")) + list(OUTPUT_ROOT.rglob("*"))
    rec = sha256_manifest(targets, repo_root=REPO_ROOT)
    write_json(REVIEW_ROOT / SHA256_MANIFEST_NAME, rec)
    return rec


def verify_sha256_manifest(rec: dict[str, str]) -> str:
    for rel, expected in rec.items():
        if sha256_file(REPO_ROOT / rel) != expected:
            return "FAIL"
    if SHA256_MANIFEST_NAME in rec:
        return "FAIL"
    if any(Path(k).name == SHA256_MANIFEST_NAME for k in rec):
        return "FAIL"
    return "PASS"


def historical_ta2_logits() -> dict[int, np.ndarray]:
    pred = REPO_ROOT / EDITOR024_OUTPUT_REL / "raw_predictions"
    out = {}
    for seed in SEEDS:
        path = pred / f"TA2_seed{seed}_COMPLETED_WINDOW.npz"
        with np.load(path) as z:
            out[int(seed)] = np.asarray(z["logit"], dtype=np.float64)
    return out


def write_raw_predictions(
    *,
    alias: str,
    seed: int,
    dataset: str,
    view: str,
    user_ids: np.ndarray,
    sequence_ids: np.ndarray,
    y: np.ndarray,
    logits: np.ndarray,
    threshold: float,
) -> Path:
    dest = OUTPUT_ROOT / "raw_predictions"
    dest.mkdir(parents=True, exist_ok=True)
    probs = sigmoid(np.asarray(logits, dtype=np.float64))
    pred = (probs >= float(threshold)).astype(np.int8)
    path = dest / f"{alias}_seed{seed}_{dataset}_{view}.npz"
    write_npz(
        path,
        user_id=np.asarray(user_ids).astype(str),
        sequence_id=np.asarray(sequence_ids).astype(str),
        label=np.asarray(y).astype(np.int8),
        logit=np.asarray(logits, dtype=np.float64),
        probability=probs,
        frozen_threshold=np.array([float(threshold)], dtype=np.float64),
        thresholded_prediction=pred,
    )
    return path


def construct_representation() -> dict[str, Any]:
    _log("Constructing causal user-relative representation")
    splits = load_frozen_r52_splits()
    dense = load_r52_dense_raw()
    ur_by_user = transform_r52_user_relative(dense)
    train_start = min(str(x) for x in splits["train"]["start_date"])
    train_end = max(str(x) for x in splits["train"]["end_date"])
    scaler = fit_ur_scaler(ur_by_user, dense["dates_by_user"], train_start, train_end)
    write_json(REVIEW_ROOT / "EDITOR026_UR_SCALER.json", scaler.to_dict())
    write_json(REVIEW_ROOT / "EDITOR026_REPRESENTATION_DEFINITION.json", {
        "lookback_days": 20,
        "train_calendar_start": train_start[:10],
        "train_calendar_end": train_end[:10],
        "scaler_fit": "R52 TRAIN ONLY",
        "n_r52_users": dense["n_users"],
        "feature_order": list(FEATURE_ORDER),
        "split_notes": {
            "validation_may_use_earlier_same_user_history": True,
            "windows_retain_frozen_split": True,
            "labels_never_enter_baseline": True,
        },
    })
    scaled = scale_by_user(ur_by_user, scaler)
    x_train = build_r52_ur_windows(
        scaled_by_user=scaled, dates_by_user=dense["dates_by_user"], split=splits["train"]
    )
    x_val = build_r52_ur_windows(
        scaled_by_user=scaled, dates_by_user=dense["dates_by_user"], split=splits["val"]
    )
    tdir = OUTPUT_ROOT / "tensors"
    tdir.mkdir(parents=True, exist_ok=True)
    write_npz(
        tdir / "r52_train_ur.npz",
        X=x_train,
        y=splits["train"]["y"],
        user=splits["train"]["user"],
        sequence_id=splits["train"]["sequence_id"],
        start_date=splits["train"]["start_date"],
    )
    write_npz(
        tdir / "r52_val_ur.npz",
        X=x_val,
        y=splits["val"]["y"],
        user=splits["val"]["user"],
        sequence_id=splits["val"]["sequence_id"],
        start_date=splits["val"]["start_date"],
    )
    bundle = load_r61_bundle_raw()
    r61 = build_r61_ur(bundle, scaler)
    write_npy(tdir / "r61_ur_scaled_daily.npy", r61["ur_scaled_daily"])
    write_npy(tdir / "r61_ur_windows.npy", r61["X"])
    labels = freeze_label_views(
        bundle_y_editor024=bundle["y"],
        user_ids_windows=bundle["user_ids_windows"],
        start_index=bundle["start_idx"],
        calendar_dates=bundle["calendar_dates"],
    )
    y_b = labels["views"][R61_LABEL_VIEW_B]["y"]
    if y_b is None:
        raise Editor026Blocked("insider-consistent view unavailable; scenario 4 remains not invented")
    write_npy(tdir / "r61_y_editor024.npy", labels["views"][R61_LABEL_VIEW_A]["y"])
    write_npy(tdir / "r61_y_insider.npy", y_b)
    train_ur_daily = []
    for u, arr in ur_by_user.items():
        mask = (dense["dates_by_user"][u] >= train_start[:10]) & (dense["dates_by_user"][u] <= train_end[:10])
        if mask.any():
            train_ur_daily.append(arr[mask])
    train_ur_raw = np.concatenate(train_ur_daily, axis=0)
    return {
        "splits": splits,
        "scaler": scaler,
        "x_train": x_train,
        "x_val": x_val,
        "y_train": splits["train"]["y"],
        "y_val": splits["val"]["y"],
        "user_val": splits["val"]["user"],
        "seq_val": splits["val"]["sequence_id"],
        "train_ur_raw": train_ur_raw,
        "train_ur_scaled_flat": scaler.transform(train_ur_raw),
        "r61": r61,
        "bundle": bundle,
        "labels": labels,
        "y_r61_a": labels["views"][R61_LABEL_VIEW_A]["y"],
        "y_r61_b": y_b,
    }


def run_stage0() -> dict[str, Any]:
    require_protocol_frozen(action="Stage-0 diagnostics")
    pack = construct_representation()
    rows = feature_shift_rows(
        r52_train_scaled=pack["x_train"].reshape(-1, 13),
        r61_scaled=np.reshape(pack["r61"]["ur_scaled_daily"], (-1, 13)),
        r52_train_ur_raw=pack["train_ur_raw"],
        r61_ur_raw=np.reshape(pack["r61"]["ur_raw"], (-1, 13)),
    )
    red = reduction_metrics(rows)
    write_csv(REVIEW_ROOT / "EDITOR026_STAGE0_SHIFT_FEATURES.csv", rows)
    write_json(REVIEW_ROOT / "EDITOR026_STAGE0_SHIFT_RESULTS.json", {"rows": rows, **red})
    signal = input_signal_packet(
        x_train=pack["x_train"],
        y_train=pack["y_train"],
        x_val=pack["x_val"],
        y_val=pack["y_val"],
        x_r61=pack["r61"]["X"],
        y_r61_editor024=pack["y_r61_a"],
        y_r61_insider=pack["y_r61_b"],
    )
    write_json(REVIEW_ROOT / "EDITOR026_STAGE0_INPUT_SIGNAL.json", signal)
    dist_gate = red["EDITOR026_REPRESENTATION_DISTRIBUTION_GATE"]
    sig_gate = signal["EDITOR026_INPUT_SIGNAL_GATE"]
    training_ok = dist_gate == "PASS" and sig_gate == "PASS"
    gate = {
        **red,
        **{k: signal[k] for k in (
            "R52_INPUT_SEPARATION",
            "R61_EDITOR024_INPUT_TRANSFER_RATIO",
            "R61_INSIDER_CONSISTENT_INPUT_TRANSFER_RATIO",
            "G0D",
            "G0E",
            "G0F",
            "EDITOR026_INPUT_SIGNAL_GATE",
        )},
        "EDITOR026_REPRESENTATION_DISTRIBUTION_GATE": dist_gate,
        "EDITOR026_TRAINING_AUTHORISED": "YES" if training_ok else "NO",
        "EDITOR026_TRAINING_EXECUTED": "NO",
        "written_at": utc_now(),
    }
    if not training_ok:
        gate["EDITOR026_RULING"] = "USER_RELATIVE_REPRESENTATION_NOT_SUPPORTED"
        gate["EDITOR026_USER_RELATIVE_REPRESENTATION"] = "NOT_SUPPORTED"
        gate["EDITOR026_REMEDY_PROMOTION"] = "NO"
    write_json(REVIEW_ROOT / "EDITOR026_STAGE0_GATE.json", gate)
    pack["stage0"] = gate
    pack["shift_rows"] = rows
    pack["signal"] = signal
    return pack


def load_r52_ur_tensors() -> dict[str, Any]:
    tdir = OUTPUT_ROOT / "tensors"
    with np.load(tdir / "r52_train_ur.npz", allow_pickle=True) as z:
        train = {k: z[k] for k in z.files}
    with np.load(tdir / "r52_val_ur.npz", allow_pickle=True) as z:
        val = {k: z[k] for k in z.files}
    return {"train": train, "val": val}


def run_training() -> dict[str, Any]:
    require_protocol_frozen(action="r5.2 training")
    require_stage0_pass(action="r5.2 training")
    data = load_r52_ur_tensors()
    x_tr = np.asarray(data["train"]["X"])
    y_tr = np.asarray(data["train"]["y"])
    x_va = np.asarray(data["val"]["X"])
    y_va = np.asarray(data["val"]["y"])
    if "r61" in str(x_tr.dtype).lower():
        raise Editor026Blocked("r6.1 leaked into training tensors")
    teacher_rows = []
    teacher_ckpts = {}
    teacher_val_logits = {}
    lin_rows = []
    for seed in SEEDS:
        lin = train_attention_linear(seed=seed, x_train=x_tr, y_train=y_tr, x_val=x_va, y_val=y_va)
        lin_rows.append(lin)
        tpack = train_ur_teacher(
            seed=seed,
            encoder_ckpt=lin["best_checkpoint"],
            x_train=x_tr,
            y_train=y_tr,
            x_val=x_va,
            y_val=y_va,
        )
        teacher_rows.append({k: tpack[k] for k in tpack if k not in {"model", "student_logits", "y_val", "epoch_rows"}})
        teacher_ckpts[seed] = tpack
        teacher_val_logits[seed] = np.asarray(tpack["student_logits"])
        tpack["model"].cpu()
    write_json(REVIEW_ROOT / "EDITOR026_TEACHER_PROVENANCE.json", {
        "recipe": "EDITOR-011 T-OPT on representation-matched UR attention-linear encoder",
        "attention_linear": [{k: r[k] for k in r if k != "epoch_rows"} for r in lin_rows],
        "teachers": teacher_rows,
        "r61_used": False,
    })
    write_json(REVIEW_ROOT / "EDITOR026_TEACHER_RESULTS.json", {"rows": teacher_rows})
    ens_val = np.mean([teacher_val_logits[s] for s in SEEDS], axis=0)
    device = __import__("torch").device("cuda" if __import__("torch").cuda.is_available() else "cpu")
    ens_train_parts = []
    for seed in SEEDS:
        model = load_ur_odst(teacher_ckpts[seed]["best_checkpoint"], device)
        scored = score_odst_arrays(model, x_tr, y_tr, device, seed=seed)
        ens_train_parts.append(scored["logits"])
        model.cpu()
    ens_train = np.mean(ens_train_parts, axis=0)
    (OUTPUT_ROOT / "ensemble_cache").mkdir(parents=True, exist_ok=True)
    np.save(OUTPUT_ROOT / "ensemble_cache" / "train_ens_logit.npy", ens_train)
    np.save(OUTPUT_ROOT / "ensemble_cache" / "val_ens_logit.npy", ens_val)

    student_packs: dict[tuple[str, int], dict[str, Any]] = {}
    for alias in ("UR_C2", "UR_F10", "UR_FINAL"):
        spec_guide = alias != "UR_C2"
        for seed in SEEDS:
            pack = train_ur_odst_student(
                alias=alias,
                seed=seed,
                teacher_ckpt=teacher_ckpts[seed]["best_checkpoint"],
                x_train=x_tr,
                y_train=y_tr,
                x_val=x_va,
                y_val=y_va,
                ensemble_train=ens_train if spec_guide else None,
                ensemble_val=ens_val if spec_guide else None,
            )
            student_packs[(alias, seed)] = pack
            write_raw_predictions(
                alias=alias,
                seed=seed,
                dataset="r52_validation",
                view="R52_VAL",
                user_ids=data["val"]["user"],
                sequence_ids=data["val"]["sequence_id"],
                y=y_va,
                logits=pack["student_logits"],
                threshold=pack["threshold"],
            )
    for seed in SEEDS:
        pack = train_ur_linear_student(
            seed=seed,
            teacher_ckpt=teacher_ckpts[seed]["best_checkpoint"],
            x_train=x_tr,
            y_train=y_tr,
            x_val=x_va,
            y_val=y_va,
            ensemble_train=ens_train,
            ensemble_val=ens_val,
        )
        student_packs[("UR_LINEAR", seed)] = pack
        write_raw_predictions(
            alias="UR_LINEAR",
            seed=seed,
            dataset="r52_validation",
            view="R52_VAL",
            user_ids=data["val"]["user"],
            sequence_ids=data["val"]["sequence_id"],
            y=y_va,
            logits=pack["student_logits"],
            threshold=pack["threshold"],
        )
    summary_rows = []
    means = {}
    for alias in STUDENT_MODELS:
        prs = [float(student_packs[(alias, s)]["validation_PR_AUC"]) for s in SEEDS]
        means[alias] = _mean(prs)
        for s, pr in zip(SEEDS, prs):
            rec = student_packs[(alias, s)]
            summary_rows.append(
                {
                    "model": alias,
                    "seed": s,
                    "validation_PR_AUC": pr,
                    "threshold": rec["threshold"],
                    "best_epoch": rec["best_epoch"],
                    "checkpoint": rec["best_checkpoint"],
                    "sha256": rec["best_checkpoint_sha256"],
                }
            )
    write_csv(REVIEW_ROOT / "EDITOR026_R52_MODEL_SUMMARY.csv", summary_rows)
    ur_final_prs = [float(student_packs[("UR_FINAL", s)]["validation_PR_AUC"]) for s in SEEDS]
    g1 = bool(means["UR_FINAL"] >= G1_UR_FINAL_R52_MIN)
    g2 = bool(sum(1 for p in ur_final_prs if p >= G2_UR_FINAL_SEED_MIN) >= G2_N_SEEDS_MIN)
    results = {
        "means": means,
        "G1": g1,
        "G2": g2,
        "EDITOR026_CLEAN_PRESERVATION": "SUPPORTED" if (g1 and g2) else "NOT_SUPPORTED",
        "deltas": {
            "UR_F10_minus_UR_C2": means["UR_F10"] - means["UR_C2"],
            "UR_FINAL_minus_UR_C2": means["UR_FINAL"] - means["UR_C2"],
            "UR_FINAL_minus_UR_F10": means["UR_FINAL"] - means["UR_F10"],
            "UR_FINAL_minus_UR_LINEAR": means["UR_FINAL"] - means["UR_LINEAR"],
        },
        "historical_C2OPT_mean": HISTORICAL_C2OPT_R52_MEAN_PR_AUC,
        "historical_TA2_clean": FROZEN_CLEAN_PR_AUC["TA2"],
        "r61_used": False,
        "rows": summary_rows,
        "teacher_ckpts": {str(s): {
            "checkpoint": teacher_ckpts[s]["best_checkpoint"],
            "sha256": teacher_ckpts[s]["best_checkpoint_sha256"],
            "validation_PR_AUC": teacher_ckpts[s]["validation_PR_AUC"],
            "threshold": teacher_ckpts[s]["threshold"],
        } for s in SEEDS},
        "student_packs_meta": {
            f"{a}_{s}": {
                "checkpoint": student_packs[(a, s)]["best_checkpoint"],
                "sha256": student_packs[(a, s)]["best_checkpoint_sha256"],
                "validation_PR_AUC": student_packs[(a, s)]["validation_PR_AUC"],
                "threshold": student_packs[(a, s)]["threshold"],
                "best_epoch": student_packs[(a, s)]["best_epoch"],
            }
            for a in STUDENT_MODELS
            for s in SEEDS
        },
    }
    write_json(REVIEW_ROOT / "EDITOR026_R52_MODEL_RESULTS.json", results)
    return results


def write_r52_model_freeze(results: dict[str, Any]) -> dict[str, Any]:
    freeze = {
        "teachers": results["teacher_ckpts"],
        "students": results["student_packs_meta"],
        "r52_validation_metrics": results["means"],
        "r52_thresholds": {
            f"{a}_{s}": results["student_packs_meta"][f"{a}_{s}"]["threshold"]
            for a in STUDENT_MODELS
            for s in SEEDS
        },
        "r61_evaluated": False,
        "written_at": utc_now(),
        "note": "Frozen before any EDITOR-026 r6.1 model evaluation",
    }
    write_json(REVIEW_ROOT / "EDITOR026_R52_MODEL_FREEZE.json", freeze)
    return freeze


def _ci(boot: dict[str, Any], key: str) -> list[float]:
    rec = boot.get("statistics", {}).get(key, {})
    return rec.get("ci95", [float("nan"), float("nan")])


def run_r61_evaluation() -> dict[str, Any]:
    require_r52_model_frozen(action="r6.1 diagnostic evaluation")
    freeze = json.loads((REVIEW_ROOT / "EDITOR026_R52_MODEL_FREEZE.json").read_text(encoding="utf-8"))
    tdir = OUTPUT_ROOT / "tensors"
    x61 = np.load(tdir / "r61_ur_windows.npy")
    y_a = np.load(tdir / "r61_y_editor024.npy")
    y_b = np.load(tdir / "r61_y_insider.npy")
    bundle_dir = REPO_ROOT / EDITOR024_OUTPUT_REL / "bundle"
    users = np.load(bundle_dir / "user_ids_windows.npy", allow_pickle=True).astype(str)
    seq = np.load(bundle_dir / "sequence_ids.npy", allow_pickle=True).astype(str)
    with np.load(tdir / "r52_val_ur.npz", allow_pickle=True) as z:
        x_val = np.asarray(z["X"])
        y_val = np.asarray(z["y"])
        seq_val = np.asarray(z["sequence_id"]).astype(str)
    hist_ta2 = historical_ta2_logits()
    device = __import__("torch").device("cuda" if __import__("torch").cuda.is_available() else "cpu")
    logits: dict[str, dict[int, np.ndarray]] = {m: {} for m in STUDENT_MODELS}
    z_r52: dict[str, dict[int, np.ndarray]] = {m: {} for m in STUDENT_MODELS}
    z_r61: dict[str, dict[int, np.ndarray]] = {m: {} for m in STUDENT_MODELS}
    routes_r61: dict[str, dict[int, dict[str, float]]] = {m: {} for m in ("UR_F10", "UR_FINAL")}
    for alias in STUDENT_MODELS:
        for seed in SEEDS:
            meta = freeze["students"][f"{alias}_{seed}"]
            thr = float(meta["threshold"])
            if alias == "UR_LINEAR":
                student, modules = load_ur_linear(meta["checkpoint"], device)
                scored61 = score_linear_arrays(student, modules, x61, y_a, device, seed=seed)
                scored52 = score_linear_arrays(student, modules, x_val, y_val, device, seed=seed)
                student.cpu()
                modules.cpu()
            else:
                model = load_ur_odst(meta["checkpoint"], device)
                scored61 = score_odst_arrays(model, x61, y_a, device, seed=seed)
                scored52 = score_odst_arrays(model, x_val, y_val, device, seed=seed)
                if alias in ("UR_F10", "UR_FINAL"):
                    tmeta = freeze["teachers"][str(seed)]
                    teacher = load_ur_odst(tmeta["checkpoint"], device)
                    t61 = score_odst_arrays(teacher, x61, y_a, device, seed=seed)
                    from editor012_rescue.metrics import teacher_relative

                    rel = teacher_relative(
                        scored61["logits"],
                        t61["logits"],
                        scored61["choices"],
                        t61["choices"],
                        scored61["leaf_probs_all"],
                        t61["leaf_probs_all"],
                    )
                    routes_r61[alias][seed] = rel
                    teacher.cpu()
                model.cpu()
            logits[alias][seed] = np.asarray(scored61["logits"])
            z_r61[alias][seed] = np.asarray(scored61["z"])
            z_r52[alias][seed] = np.asarray(scored52["z"])
            write_raw_predictions(
                alias=alias, seed=seed, dataset="r61", view="EDITOR024",
                user_ids=users, sequence_ids=seq, y=y_a,
                logits=scored61["logits"], threshold=thr,
            )
            write_raw_predictions(
                alias=alias, seed=seed, dataset="r61", view="INSIDER_CONSISTENT",
                user_ids=users, sequence_ids=seq, y=y_b,
                logits=scored61["logits"], threshold=thr,
            )

    def view_results(y: np.ndarray, view_name: str) -> dict[str, Any]:
        prev = float(np.mean(y))
        per_model = {}
        for alias in STUDENT_MODELS:
            seed_pr = [pr_auc_from_logits(y, logits[alias][s]) for s in SEEDS]
            per_model[alias] = {
                "seeds": {str(s): seed_pr[i] for i, s in enumerate(SEEDS)},
                "mean_pr_auc": _mean(seed_pr),
                "ap_lift": ap_lift(_mean(seed_pr), prev),
            }
        hist_seed = [pr_auc_from_logits(y, hist_ta2[s]) for s in SEEDS]
        g7 = int(sum(1 for i, s in enumerate(SEEDS) if per_model["UR_FINAL"]["seeds"][str(s)] > hist_seed[i])) >= 2
        urf = np.mean([sigmoid(logits["UR_FINAL"][s]) for s in SEEDS], axis=0)
        ta2m = np.mean([sigmoid(hist_ta2[s]) for s in SEEDS], axis=0)

        def stat_fn(sl, yb):
            rec = {}
            ur_pr = float(np.mean([pr_auc(yb, sigmoid(logits["UR_FINAL"][s][sl])) for s in SEEDS]))
            rec["UR_FINAL_ranking_excess"] = ur_pr - float(yb.mean())
            rec["UR_FINAL_minus_historical_TA2"] = ur_pr - float(
                np.mean([pr_auc(yb, sigmoid(hist_ta2[s][sl])) for s in SEEDS])
            )
            rec["UR_FINAL_minus_UR_C2"] = ur_pr - float(
                np.mean([pr_auc(yb, sigmoid(logits["UR_C2"][s][sl])) for s in SEEDS])
            )
            rec["UR_F10_minus_UR_C2"] = float(
                np.mean([pr_auc(yb, sigmoid(logits["UR_F10"][s][sl])) for s in SEEDS])
            ) - float(np.mean([pr_auc(yb, sigmoid(logits["UR_C2"][s][sl])) for s in SEEDS]))
            rec["UR_FINAL_minus_UR_F10"] = ur_pr - float(
                np.mean([pr_auc(yb, sigmoid(logits["UR_F10"][s][sl])) for s in SEEDS])
            )
            rec["UR_FINAL_minus_UR_LINEAR"] = ur_pr - float(
                np.mean([pr_auc(yb, sigmoid(logits["UR_LINEAR"][s][sl])) for s in SEEDS])
            )
            return rec

        boot = user_cluster_bootstrap(users, y, stat_fn)
        ur_pr = per_model["UR_FINAL"]["mean_pr_auc"]
        g3 = bool(ur_pr > prev)
        g4 = bool(_ci(boot, "UR_FINAL_ranking_excess")[0] > 0)
        g5 = bool(ap_lift(ur_pr, prev) >= MINIMUM_AP_PREVALENCE_LIFT)
        g6 = bool(_ci(boot, "UR_FINAL_minus_historical_TA2")[0] > 0)
        return {
            "view": view_name,
            "prevalence": prev,
            "models": per_model,
            "historical_TA2_seed_pr_auc": {str(s): hist_seed[i] for i, s in enumerate(SEEDS)},
            "historical_TA2_mean_pr_auc": _mean(hist_seed),
            "bootstrap": boot,
            "G3": g3,
            "G4": g4,
            "G5": g5,
            "G6": g6,
            "G7": bool(g7),
            "mean_seed_prob_UR_FINAL": urf,
            "mean_seed_prob_TA2": ta2m,
        }

    a = view_results(y_a, R61_LABEL_VIEW_A)
    b = view_results(y_b, R61_LABEL_VIEW_B)
    write_json(REVIEW_ROOT / "EDITOR026_R61_EDITOR024_LABEL_RESULTS.json", {k: v for k, v in a.items() if k not in {"mean_seed_prob_UR_FINAL", "mean_seed_prob_TA2", "bootstrap"}} | {"bootstrap": a["bootstrap"]})
    write_json(REVIEW_ROOT / "EDITOR026_R61_INSIDER_CONSISTENT_RESULTS.json", {k: v for k, v in b.items() if k not in {"mean_seed_prob_UR_FINAL", "mean_seed_prob_TA2", "bootstrap"}} | {"bootstrap": b["bootstrap"]})
    write_json(REVIEW_ROOT / "EDITOR026_CLUSTER_BOOTSTRAP.json", {"editor024": a["bootstrap"], "insider": b["bootstrap"]})
    write_csv(
        REVIEW_ROOT / "EDITOR026_R61_SUMMARY.csv",
        [
            {"view": R61_LABEL_VIEW_A, "model": m, "mean_pr_auc": a["models"][m]["mean_pr_auc"], "ap_lift": a["models"][m]["ap_lift"], "prevalence": a["prevalence"]}
            for m in STUDENT_MODELS
        ]
        + [
            {"view": R61_LABEL_VIEW_B, "model": m, "mean_pr_auc": b["models"][m]["mean_pr_auc"], "ap_lift": b["models"][m]["ap_lift"], "prevalence": b["prevalence"]}
            for m in STUDENT_MODELS
        ],
    )

    idx52 = representation_sample_indices(seq_val, y_val, REPRESENTATION_NEGATIVE_N)
    idx61_a = representation_sample_indices(seq, y_a, REPRESENTATION_NEGATIVE_N)
    transfer = {}
    for alias in STUDENT_MODELS:
        z52 = np.mean([z_r52[alias][s][idx52] for s in SEEDS], axis=0)
        z61 = np.mean([z_r61[alias][s][idx61_a] for s in SEEDS], axis=0)
        transfer[alias] = per_model_separation(
            z_r52=z52, y_r52=y_val[idx52], z_r61=z61, y_r61=y_a[idx61_a]
        )
        idx61_b = representation_sample_indices(seq, y_b, REPRESENTATION_NEGATIVE_N)
        transfer[f"{alias}_insider"] = per_model_separation(
            z_r52=z52, y_r52=y_val[idx52], z_r61=np.mean([z_r61[alias][s][idx61_b] for s in SEEDS], axis=0), y_r61=y_b[idx61_b]
        )
    g8 = bool(transfer["UR_FINAL"]["REPRESENTATION_TRANSFER_RATIO"] > G8_REPRESENTATION_TRANSFER_MIN)
    write_json(REVIEW_ROOT / "EDITOR026_REPRESENTATION_TRANSFER.json", {"G8": g8, **transfer})

    thr_mean = _mean([float(freeze["students"][f"UR_FINAL_{s}"]["threshold"]) for s in SEEDS])
    urf_logit = np.mean([logits["UR_FINAL"][s] for s in SEEDS], axis=0)
    fp = {
        "negative_frozen_threshold_exceedance": float(distribution_block(urf_logit[y_a == 0], thr_mean)["fraction_gt_frozen_r52_threshold"]),
        **ranking_profile(y_a, sigmoid(urf_logit)),
        "threshold": thr_mean,
        "threshold_source": "R52_FROZEN_UR_FINAL",
    }
    fp_out = {k: v for k, v in fp.items() if k != "positive_percentiles"}
    fp_out["median_positive_percentile"] = fp.get("median_positive_percentile")
    cap = fp.get("capture") or {}
    fp_out["top_N_positive_capture"] = cap.get("top_1N")
    fp_out["top_5N_positive_capture"] = cap.get("top_5N")
    fp_out["top_10N_positive_capture"] = cap.get("top_10N")
    write_json(REVIEW_ROOT / "EDITOR026_FALSE_POSITIVE_DIAGNOSTICS.json", fp_out)

    route = {
        "UR_F10_R61_ROUTE_MAE": _mean([routes_r61["UR_F10"][s]["route_MAE"] for s in SEEDS]) if routes_r61["UR_F10"] else float("nan"),
        "UR_FINAL_R61_ROUTE_MAE": _mean([routes_r61["UR_FINAL"][s]["route_MAE"] for s in SEEDS]) if routes_r61["UR_FINAL"] else float("nan"),
        "per_seed": {a: {str(s): routes_r61[a][s] for s in routes_r61[a]} for a in routes_r61},
    }
    write_json(REVIEW_ROOT / "EDITOR026_ROUTE_RESULTS.json", route)
    return {
        "editor024": a,
        "insider": b,
        "G8": g8,
        "transfer": transfer,
        "fp": fp_out,
        "route": route,
        "freeze": freeze,
    }


def decide_promotion(stage0: dict[str, Any], r52: dict[str, Any] | None, r61: dict[str, Any] | None) -> dict[str, Any]:
    if stage0.get("EDITOR026_TRAINING_AUTHORISED") != "YES":
        return {
            "EDITOR026_USER_RELATIVE_REPRESENTATION": "NOT_SUPPORTED",
            "EDITOR026_CLEAN_PRESERVATION": "NOT_TESTED",
            "EDITOR026_R61_PORTABILITY_RESCUE": "NOT_TESTED",
            "EDITOR026_REMEDY_PROMOTION": "NO",
            "EDITOR026_TRAINING_EXECUTED": "NO",
        }
    clean = r52["EDITOR026_CLEAN_PRESERVATION"] if r52 else "NOT_TESTED"
    if r61 is None:
        return {
            "EDITOR026_USER_RELATIVE_REPRESENTATION": "SUPPORTED",
            "EDITOR026_CLEAN_PRESERVATION": clean,
            "EDITOR026_R61_PORTABILITY_RESCUE": "NOT_TESTED",
            "EDITOR026_REMEDY_PROMOTION": "NO",
            "EDITOR026_TRAINING_EXECUTED": "YES",
        }
    a, b = r61["editor024"], r61["insider"]
    port_ok = all(a[g] and b[g] for g in ("G3", "G4", "G5", "G6", "G7")) and bool(r61["G8"])
    g12 = r52["G1"] and r52["G2"]
    if g12 and port_ok:
        promo = "SUPPORTED_FOR_FURTHER_CONFIRMATION"
        rescue = "SUPPORTED"
    elif (not g12) and port_ok:
        promo = "NO"
        rescue = "SUPPORTED"
    else:
        promo = "NO"
        rescue = "NOT_SUPPORTED"
    return {
        "EDITOR026_USER_RELATIVE_REPRESENTATION": "SUPPORTED",
        "EDITOR026_CLEAN_PRESERVATION": clean,
        "EDITOR026_R61_PORTABILITY_RESCUE": rescue,
        "EDITOR026_REMEDY_PROMOTION": promo,
        "EDITOR026_TRAINING_EXECUTED": "YES",
        "G1": r52["G1"],
        "G2": r52["G2"],
        "G8": r61["G8"],
        "editor024_gates": {g: a[g] for g in ("G3", "G4", "G5", "G6", "G7")},
        "insider_gates": {g: b[g] for g in ("G3", "G4", "G5", "G6", "G7")},
        "CANDIDATE_FOR_NEW_FINAL_CONFIRMATION": promo == "SUPPORTED_FOR_FURTHER_CONFIRMATION",
        "do_not_replace_historical_TA2_immediately": True,
    }


def write_result_freeze(payload: dict[str, Any]) -> None:
    lines = [
        "# EDITOR-026 RESULT FREEZE",
        "",
        f"Parent: `{EDITOR025_RESULTS_COMMIT}`",
        f"Training executed: {payload.get('EDITOR026_TRAINING_EXECUTED')}",
        f"User-relative representation: {payload.get('EDITOR026_USER_RELATIVE_REPRESENTATION')}",
        f"Clean preservation: {payload.get('EDITOR026_CLEAN_PRESERVATION')}",
        f"r6.1 portability rescue: {payload.get('EDITOR026_R61_PORTABILITY_RESCUE')}",
        f"Promotion: {payload.get('EDITOR026_REMEDY_PROMOTION')}",
        "",
        "Historical EDITOR-024 result is unchanged. r6.1 cannot serve as a future untouched target.",
        "No r5.1 / r6.2 rerun. No automatic EDITOR-027. No alternative lookback.",
        "",
    ]
    write_text(REVIEW_ROOT / "EDITOR026_RESULT_FREEZE.md", "\n".join(lines))


def terminal_block(payload: dict[str, Any], *, results_commit: str) -> str:
    s0 = payload.get("stage0") or {}
    r52 = payload.get("r52") or {}
    r61 = payload.get("r61") or {}
    a = (r61 or {}).get("editor024") or {}
    b = (r61 or {}).get("insider") or {}
    fp = (r61 or {}).get("fp") or {}
    route = (r61 or {}).get("route") or {}
    means = r52.get("means") or {}
    promo = payload.get("promotion") or {}

    def nv(x, digits=None):
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return "NOT_RUN"
        if digits is None:
            return str(x)
        return f"{float(x):.{digits}g}" if isinstance(x, (float, int)) else str(x)

    def ci_txt(view, key):
        boot = view.get("bootstrap") or {}
        c = _ci(boot, key)
        if not c or not np.isfinite(c[0]):
            return "NOT_RUN"
        return f"[{c[0]}, {c[1]}]"

    lines = [
        "EDITOR026_COMPLETE",
        "",
        f"EDITOR025_RESULTS_COMMIT =",
        EDITOR025_RESULTS_COMMIT,
        "",
        f"EDITOR026_PROTOCOL_FREEZE_COMMIT =",
        payload.get("protocol_sha") or protocol_freeze_commit() or "MISSING",
        "",
        f"EDITOR026_R52_MODEL_FREEZE_COMMIT =",
        payload.get("r52_freeze_sha") or r52_model_freeze_commit() or "NOT_RUN",
        "",
        f"EDITOR026_RESULTS_COMMIT =",
        results_commit,
        "",
        "",
        f"SOURCE_GATE =",
        payload.get("SOURCE_GATE", "FAIL"),
        "",
        f"UNIT_TEST_GATE =",
        payload.get("UNIT_TEST_GATE", "FAIL"),
        "",
        "",
        f"STAGE0_MEAN_ABS_SHIFT_REDUCTION =",
        nv(s0.get("MEAN_ABS_SHIFT_REDUCTION")),
        "",
        f"STAGE0_MEAN_PSI_REDUCTION =",
        nv(s0.get("MEAN_PSI_REDUCTION")),
        "",
        f"STAGE0_FEATURES_WITH_LOWER_PSI =",
        f"{s0.get('N_FEATURES_WITH_LOWER_PSI', 'NOT_RUN')}/13",
        "",
        f"EDITOR026_REPRESENTATION_DISTRIBUTION_GATE =",
        s0.get("EDITOR026_REPRESENTATION_DISTRIBUTION_GATE", "FAIL"),
        "",
        "",
        f"R52_INPUT_SEPARATION =",
        nv(s0.get("R52_INPUT_SEPARATION")),
        "",
        f"R61_EDITOR024_INPUT_TRANSFER_RATIO =",
        nv(s0.get("R61_EDITOR024_INPUT_TRANSFER_RATIO")),
        "",
        f"R61_INSIDER_CONSISTENT_INPUT_TRANSFER_RATIO =",
        nv(s0.get("R61_INSIDER_CONSISTENT_INPUT_TRANSFER_RATIO")),
        "",
        f"EDITOR026_INPUT_SIGNAL_GATE =",
        s0.get("EDITOR026_INPUT_SIGNAL_GATE", "FAIL"),
        "",
        "",
        f"EDITOR026_TRAINING_EXECUTED =",
        promo.get("EDITOR026_TRAINING_EXECUTED", s0.get("EDITOR026_TRAINING_EXECUTED", "NO")),
        "",
        "",
        f"UR_C2_R52_MEAN_PR_AUC =",
        nv(means.get("UR_C2")),
        "",
        f"UR_F10_R52_MEAN_PR_AUC =",
        nv(means.get("UR_F10")),
        "",
        f"UR_FINAL_R52_MEAN_PR_AUC =",
        nv(means.get("UR_FINAL")),
        "",
        f"UR_LINEAR_R52_MEAN_PR_AUC =",
        nv(means.get("UR_LINEAR")),
        "",
        f"EDITOR026_CLEAN_PRESERVATION =",
        promo.get("EDITOR026_CLEAN_PRESERVATION", "NOT_TESTED"),
        "",
        "",
        f"R61_EDITOR024_PREVALENCE =",
        nv(a.get("prevalence")),
        "",
        f"UR_FINAL_R61_EDITOR024_PR_AUC =",
        nv((a.get("models") or {}).get("UR_FINAL", {}).get("mean_pr_auc")),
        "",
        f"UR_FINAL_R61_EDITOR024_AP_LIFT =",
        nv((a.get("models") or {}).get("UR_FINAL", {}).get("ap_lift")),
        "",
        f"UR_FINAL_R61_EDITOR024_RANKING_EXCESS_CI95 =",
        ci_txt(a, "UR_FINAL_ranking_excess"),
        "",
        f"UR_FINAL_MINUS_HISTORICAL_TA2_EDITOR024 =",
        nv(((a.get("bootstrap") or {}).get("statistics") or {}).get("UR_FINAL_minus_historical_TA2", {}).get("mean")),
        "",
        f"UR_FINAL_MINUS_HISTORICAL_TA2_EDITOR024_CI95 =",
        ci_txt(a, "UR_FINAL_minus_historical_TA2"),
        "",
        "",
        f"R61_INSIDER_CONSISTENT_PREVALENCE =",
        nv(b.get("prevalence")),
        "",
        f"UR_FINAL_R61_INSIDER_CONSISTENT_PR_AUC =",
        nv((b.get("models") or {}).get("UR_FINAL", {}).get("mean_pr_auc")),
        "",
        f"UR_FINAL_R61_INSIDER_CONSISTENT_AP_LIFT =",
        nv((b.get("models") or {}).get("UR_FINAL", {}).get("ap_lift")),
        "",
        f"UR_FINAL_R61_INSIDER_CONSISTENT_RANKING_EXCESS_CI95 =",
        ci_txt(b, "UR_FINAL_ranking_excess"),
        "",
        f"UR_FINAL_MINUS_HISTORICAL_TA2_INSIDER_CONSISTENT =",
        nv(((b.get("bootstrap") or {}).get("statistics") or {}).get("UR_FINAL_minus_historical_TA2", {}).get("mean")),
        "",
        f"UR_FINAL_MINUS_HISTORICAL_TA2_INSIDER_CONSISTENT_CI95 =",
        ci_txt(b, "UR_FINAL_minus_historical_TA2"),
        "",
        "",
        f"UR_FINAL_R61_REPRESENTATION_TRANSFER_RATIO =",
        nv(((r61.get("transfer") or {}).get("UR_FINAL") or {}).get("REPRESENTATION_TRANSFER_RATIO")),
        "",
        "",
        f"UR_FINAL_NEGATIVE_THRESHOLD_EXCEEDANCE =",
        nv(fp.get("negative_frozen_threshold_exceedance")),
        "",
        f"UR_FINAL_POSITIVE_MEDIAN_GLOBAL_PERCENTILE =",
        nv(fp.get("median_positive_percentile")),
        "",
        f"UR_FINAL_TOP_N_POSITIVE_CAPTURE =",
        nv(fp.get("top_N_positive_capture")),
        "",
        "",
        f"UR_F10_R61_ROUTE_MAE =",
        nv(route.get("UR_F10_R61_ROUTE_MAE")),
        "",
        f"UR_FINAL_R61_ROUTE_MAE =",
        nv(route.get("UR_FINAL_R61_ROUTE_MAE")),
        "",
        "",
        f"EDITOR026_USER_RELATIVE_REPRESENTATION =",
        promo.get("EDITOR026_USER_RELATIVE_REPRESENTATION", s0.get("EDITOR026_USER_RELATIVE_REPRESENTATION", "NOT_SUPPORTED")),
        "",
        f"EDITOR026_R61_PORTABILITY_RESCUE =",
        promo.get("EDITOR026_R61_PORTABILITY_RESCUE", "NOT_TESTED"),
        "",
        f"EDITOR026_REMEDY_PROMOTION =",
        promo.get("EDITOR026_REMEDY_PROMOTION", "NO"),
        "",
        "",
        "HISTORICAL_EDITOR024_RESULT_CHANGED =",
        "NO",
        "",
        "R61_CAN_SERVE_AS_FUTURE_UNTOUCHED_TARGET =",
        "NO",
        "",
        "R51_RERUN =",
        "NO",
        "",
        "R62_RERUN =",
        "NO",
        "",
        "",
        "SHA_MANIFEST_VERIFICATION =",
        payload.get("SHA_MANIFEST_VERIFICATION", "PENDING"),
        "",
    ]
    text = "\n".join(lines) + "\n"
    write_text(REVIEW_ROOT / "EDITOR026_TERMINAL_BLOCK.txt", text)
    return text


def finalise(payload: dict[str, Any]) -> dict[str, Any]:
    write_json(
        REVIEW_ROOT / "EDITOR026_PROVENANCE.json",
        {
            "parent": EDITOR025_RESULTS_COMMIT,
            "protocol": payload.get("protocol_sha"),
            "r52_freeze": payload.get("r52_freeze_sha"),
            "head": _git_sha(),
            "utc": utc_now(),
        },
    )
    write_json(
        REVIEW_ROOT / "EDITOR026_PROMOTION_DECISION.json",
        payload.get("promotion") or {},
    )
    write_json(
        REVIEW_ROOT / "EDITOR026_RUN_MANIFEST.json",
        {
            "phase": "complete",
            "utc": utc_now(),
            "EDITOR026_RESULTS_COMMIT": "PENDING_BY_DESIGN",
            "SOURCE_GATE": payload.get("SOURCE_GATE"),
            "UNIT_TEST_GATE": payload.get("UNIT_TEST_GATE"),
            "R51_RERUN": "NO",
            "R62_RERUN": "NO",
            "HISTORICAL_EDITOR024_RESULT_CHANGED": "NO",
            "R61_CAN_SERVE_AS_FUTURE_UNTOUCHED_TARGET": "NO",
            **(payload.get("promotion") or {}),
        },
    )
    write_result_freeze(payload)
    payload["SHA_MANIFEST_VERIFICATION"] = "PASS"
    terminal_block(payload, results_commit="PENDING_BY_DESIGN")
    rec = write_sha256_manifest_last()
    ver = verify_sha256_manifest(rec)
    payload["SHA_MANIFEST_VERIFICATION"] = ver
    if ver != "PASS":
        raise Editor026Blocked("SHA_MANIFEST_VERIFICATION = FAIL")
    return payload


def run_campaign(*, phase: str = "all") -> dict[str, Any]:
    refuse_r51_r62(str(REPO_ROOT / REVIEW_REL))
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if phase == "protocol":
        return freeze_protocol()
    payload: dict[str, Any] = {
        "SOURCE_GATE": parent_commit_ok(),
        "UNIT_TEST_GATE": run_unit_tests(),
        "protocol_sha": protocol_freeze_commit(),
    }
    if payload["UNIT_TEST_GATE"] != "PASS":
        raise Editor026Blocked("UNIT_TEST_GATE = FAIL")
    require_protocol_frozen(action="EDITOR-026 execution")
    if phase in {"stage0", "all", "train", "evaluate"}:
        if not (REVIEW_ROOT / "EDITOR026_STAGE0_GATE.json").is_file() or phase == "stage0":
            pack = run_stage0()
            payload["stage0"] = pack["stage0"]
            payload["signal"] = pack["signal"]
        else:
            payload["stage0"] = json.loads((REVIEW_ROOT / "EDITOR026_STAGE0_GATE.json").read_text(encoding="utf-8"))
    if payload.get("stage0", {}).get("EDITOR026_TRAINING_AUTHORISED") != "YES":
        payload["promotion"] = decide_promotion(payload.get("stage0") or {}, None, None)
        if phase in {"all", "stage0"}:
            return finalise(payload)
        return payload
    if phase == "stage0":
        return payload
    if phase in {"train", "all"}:
        r52 = run_training()
        payload["r52"] = r52
        write_r52_model_freeze(r52)
        payload["r52_freeze_sha"] = "PENDING_COMMIT"
        payload["promotion"] = decide_promotion(payload["stage0"], r52, None)
        if phase == "train":
            write_json(REVIEW_ROOT / "EDITOR026_PROMOTION_DECISION.json", payload["promotion"])
            return payload
    if phase in {"evaluate", "all"}:
        if phase == "evaluate":
            payload["r52"] = json.loads((REVIEW_ROOT / "EDITOR026_R52_MODEL_RESULTS.json").read_text(encoding="utf-8"))
            payload["r52_freeze_sha"] = r52_model_freeze_commit()
        r61 = run_r61_evaluation()
        payload["r61"] = r61
        payload["promotion"] = decide_promotion(payload.get("stage0") or {}, payload.get("r52"), r61)
        return finalise(payload)
    return payload
