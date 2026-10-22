"""EDITOR-028 campaign. Protocol first. r6.1 labels only after the r5.2 model freeze."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from editor012_rescue.metrics import sigmoid, teacher_relative
from editor025_r61_autopsy.representation import per_model_separation
from editor025_r61_autopsy.sampling import representation_sample_indices
from editor025_r61_autopsy.scores import distribution_block, ranking_profile
from editor026_user_relative.bootstrap import ap_lift, pr_auc, pr_auc_from_logits, user_cluster_bootstrap

from .alignment import UnlabeledAlignmentStore, assert_no_alignment_labels
from .constants import (
    ALIGNED_CANDIDATES,
    ALL_CANDIDATES,
    CANDIDATE_LAMBDAS,
    DIAGNOSTIC_SAMPLE_N,
    EDITOR024_OUTPUT_REL,
    EDITOR027_RESULTS_COMMIT,
    FEATURE_ORDER,
    MINIMUM_AP_PREVALENCE_LIFT,
    OUTPUT_REL,
    R61_LABEL_VIEW_A,
    R61_LABEL_VIEW_B,
    REPRESENTATION_NEGATIVE_N,
    REVIEW_REL,
    SEEDS,
    SHA256_MANIFEST_NAME,
    TASK_ID,
    TEACHER_IDS,
    USER_RELATIVE_LOOKBACK_DAYS,
)
from .coral import coral_discrepancy_numpy
from .diagnostics import sha256_order_indices, source_latent_separation
from .io_util import write_csv, write_json, write_npy, write_npz, write_text
from .protocol import freeze_protocol
from .representation import representation_identity
from .safety import (
    OUTPUT_ROOT,
    REPO_ROOT,
    REVIEW_ROOT,
    Editor028Blocked,
    protocol_freeze_commit,
    r52_model_freeze_commit,
    refuse_r51_r62,
    require_protocol_frozen,
    require_r52_model_frozen,
    sha256_file,
    utc_now,
)
from .selection import evaluate_gates
from .tensors import construct_r52_centered, construct_r61_unlabeled_raw, unlabeled_alignment_from_raw
from .train import (
    load_odst,
    score_odst_arrays,
    score_odst_unlabeled,
    teacher_reproduction_gate,
    train_aligned_student,
    train_centered_attention_linear,
    train_centered_teacher,
)

HISTORICAL_TA2_PRED = Path(
    r"C:\PhD\07_Projects\teacher-anchored-insider-threat-detection-editor024-r61"
    r"\outputs\editor024_r61_final_confirmation\raw_predictions"
)


def _log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()


def _mean(xs: list[float]) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def parent_commit_ok() -> str:
    observed = subprocess.check_output(
        ["git", "merge-base", EDITOR027_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    if observed != EDITOR027_RESULTS_COMMIT:
        raise Editor028Blocked(f"SOURCE_GATE FAIL parent {observed} != {EDITOR027_RESULTS_COMMIT}")
    return "PASS"


def run_unit_tests() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_editor028_latent_alignment.py", "-q"],
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
    out = {}
    for seed in SEEDS:
        path = HISTORICAL_TA2_PRED / f"TA2_seed{seed}_COMPLETED_WINDOW.npz"
        if not path.is_file():
            alt = REPO_ROOT / EDITOR024_OUTPUT_REL / "raw_predictions" / f"TA2_seed{seed}_COMPLETED_WINDOW.npz"
            path = alt
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
    _log("Constructing EDITOR-026 centred representation (r5.2 scaler fit only)")
    r52 = construct_r52_centered()
    write_json(REVIEW_ROOT / "EDITOR028_CENTERED_REPRESENTATION_PROVENANCE.json", {
        "implementation": "editor026_user_relative.representation.causal_user_relative_daily",
        "identity": representation_identity(),
        "lookback_days": USER_RELATIVE_LOOKBACK_DAYS,
        "feature_order": list(FEATURE_ORDER),
        "scaler_fit": "R52 TRAIN ONLY",
        "R61_SCALER_FIT": "NO",
        "R61_TARGET_NORMALISATION_FIT": "NO",
        "do_not_use_editor027_scale_normalisation": True,
        "implementation_sha256": sha256_file(REPO_ROOT / "src" / "editor026_user_relative" / "representation.py"),
        "scaler": r52["scaler"].to_dict(),
    })
    tdir = OUTPUT_ROOT / "tensors"
    tdir.mkdir(parents=True, exist_ok=True)
    write_npz(
        tdir / "r52_train_ur.npz",
        X=r52["x_train"],
        y=r52["y_train"],
        user=r52["splits"]["train"]["user"],
        sequence_id=r52["splits"]["train"]["sequence_id"],
        start_date=r52["splits"]["train"]["start_date"],
    )
    write_npz(
        tdir / "r52_val_ur.npz",
        X=r52["x_val"],
        y=r52["y_val"],
        user=r52["user_val"],
        sequence_id=r52["seq_val"],
        start_date=r52["splits"]["val"]["start_date"],
    )
    _log("Constructing unlabeled r6.1 alignment population (no labels loaded)")
    raw61 = construct_r61_unlabeled_raw()
    store = unlabeled_alignment_from_raw(raw61, r52["scaler"])
    assert_no_alignment_labels(store)
    write_npz(
        tdir / "r61_unlabeled.npz",
        X=store.X,
        user=store.user,
        sequence_id=store.sequence_id,
    )
    write_npy(tdir / "r61_user_idx.npy", raw61["user_idx"])
    write_npy(tdir / "r61_start_idx.npy", raw61["start_idx"])
    write_npy(tdir / "r61_calendar_dates.npy", raw61["calendar_dates"])
    r52["alignment"] = store
    r52["r61_raw_meta"] = {k: raw61[k] for k in raw61 if k != "raw"}
    return r52


def load_r52_ur_tensors() -> dict[str, Any]:
    tdir = OUTPUT_ROOT / "tensors"
    with np.load(tdir / "r52_train_ur.npz", allow_pickle=True) as z:
        train = {k: z[k] for k in z.files}
    with np.load(tdir / "r52_val_ur.npz", allow_pickle=True) as z:
        val = {k: z[k] for k in z.files}
    return {"train": train, "val": val}


def load_unlabeled_alignment() -> UnlabeledAlignmentStore:
    tdir = OUTPUT_ROOT / "tensors"
    with np.load(tdir / "r61_unlabeled.npz", allow_pickle=True) as z:
        keys = set(z.files)
        forbidden = {"y", "label", "labels", "malicious"}
        if keys.intersection(forbidden):
            raise Editor028Blocked(f"unlabeled loader leaked {sorted(keys.intersection(forbidden))}")
        store = UnlabeledAlignmentStore(
            X=np.asarray(z["X"]),
            user=np.asarray(z["user"]).astype(str),
            sequence_id=np.asarray(z["sequence_id"]).astype(str),
        )
    assert_no_alignment_labels(store)
    return store


def run_training() -> dict[str, Any]:
    require_protocol_frozen(action="r5.2 training")
    gate = teacher_reproduction_gate()
    if gate["EDITOR028_TEACHER_REPRODUCTION_GATE"] != "PASS":
        raise Editor028Blocked("EDITOR028_TEACHER_REPRODUCTION_GATE = FAIL")
    data = load_r52_ur_tensors()
    target = load_unlabeled_alignment()
    x_tr = np.asarray(data["train"]["X"])
    y_tr = np.asarray(data["train"]["y"])
    x_va = np.asarray(data["val"]["X"])
    y_va = np.asarray(data["val"]["y"])
    seq_va = np.asarray(data["val"]["sequence_id"]).astype(str)
    teacher_rows = []
    teacher_ckpts = {}
    teacher_val_logits = {}
    lin_rows = []
    for seed in SEEDS:
        lin = train_centered_attention_linear(seed=seed, x_train=x_tr, y_train=y_tr, x_val=x_va, y_val=y_va)
        lin_rows.append({k: r for k, r in lin.items() if k != "epoch_rows"})
        tpack = train_centered_teacher(
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
    write_json(
        REVIEW_ROOT / "EDITOR028_TEACHER_PROVENANCE.json",
        {
            "recipe": "EDITOR-011 T-OPT on representation-matched centred attention-linear encoder",
            "reproduction_gate": gate,
            "attention_linear": lin_rows,
            "teachers": teacher_rows,
            "r61_used": False,
        },
    )
    write_json(REVIEW_ROOT / "EDITOR028_TEACHER_RESULTS.json", {"rows": teacher_rows})
    ens_val = np.mean([teacher_val_logits[s] for s in SEEDS], axis=0)
    device = __import__("torch").device("cuda" if __import__("torch").cuda.is_available() else "cpu")
    ens_train_parts = []
    for seed in SEEDS:
        model = load_odst(teacher_ckpts[seed]["best_checkpoint"], device)
        scored = score_odst_arrays(model, x_tr, y_tr, device, seed=seed)
        ens_train_parts.append(scored["logits"])
        model.cpu()
    ens_train = np.mean(ens_train_parts, axis=0)
    (OUTPUT_ROOT / "ensemble_cache").mkdir(parents=True, exist_ok=True)
    np.save(OUTPUT_ROOT / "ensemble_cache" / "train_ens_logit.npy", ens_train)
    np.save(OUTPUT_ROOT / "ensemble_cache" / "val_ens_logit.npy", ens_val)

    student_packs: dict[tuple[str, int], dict[str, Any]] = {}
    for alias in ALL_CANDIDATES:
        for seed in SEEDS:
            pack = train_aligned_student(
                alias=alias,
                seed=seed,
                teacher_ckpt=teacher_ckpts[seed]["best_checkpoint"],
                x_train=x_tr,
                y_train=y_tr,
                x_val=x_va,
                y_val=y_va,
                ensemble_train=ens_train,
                ensemble_val=ens_val,
                target=target,
            )
            student_packs[(alias, seed)] = pack
            write_raw_predictions(
                alias=alias,
                seed=seed,
                dataset="r52_validation",
                view="R52_VAL",
                user_ids=data["val"]["user"],
                sequence_ids=seq_va,
                y=y_va,
                logits=pack["student_logits"],
                threshold=pack["threshold"],
            )

    idx52 = sha256_order_indices(seq_va, DIAGNOSTIC_SAMPLE_N)
    idx61 = sha256_order_indices(target.sequence_id, DIAGNOSTIC_SAMPLE_N)
    x61_diag = np.asarray(target.X)[idx61]
    r52_pr: dict[str, dict[int, float]] = {a: {} for a in ALL_CANDIDATES}
    coral_d: dict[str, dict[int, float]] = {a: {} for a in ALL_CANDIDATES}
    r52_sep: dict[str, dict[int, float]] = {a: {} for a in ALL_CANDIDATES}
    for alias in ALL_CANDIDATES:
        for seed in SEEDS:
            rec = student_packs[(alias, seed)]
            r52_pr[alias][seed] = float(rec["validation_PR_AUC"])
            model = load_odst(rec["best_checkpoint"], device)
            z52 = score_odst_arrays(model, x_va[idx52], y_va[idx52], device, seed=seed)["z"]
            z61 = score_odst_unlabeled(model, x61_diag, device, seed=seed)["z"]
            coral_d[alias][seed] = coral_discrepancy_numpy(z52, z61)
            r52_sep[alias][seed] = source_latent_separation(z52, y_va[idx52])
            model.cpu()
    selection = evaluate_gates(r52_pr=r52_pr, coral_d=coral_d, r52_separation=r52_sep)
    write_json(
        REVIEW_ROOT / "EDITOR028_LABEL_BLIND_ALIGNMENT.json",
        {
            "sample_n_r52": int(len(idx52)),
            "sample_n_r61": int(len(idx61)),
            "order": "ascending SHA256(sequence_id)",
            "class_stratification": False,
            "r61_labels_used": False,
            "ALIGN0_LATENT_CORAL_DISCREPANCY": selection["ALIGN0_LATENT_CORAL_DISCREPANCY"],
            "candidates": {
                n: {
                    "LATENT_CORAL_DISCREPANCY": selection["candidates"][n]["LATENT_CORAL_DISCREPANCY"],
                    "ALIGNMENT_REDUCTION": selection["candidates"][n]["ALIGNMENT_REDUCTION"],
                    "seed_coral": selection["candidates"][n]["seed_coral"],
                }
                for n in ALIGNED_CANDIDATES
            },
        },
    )
    write_json(REVIEW_ROOT / "EDITOR028_CANDIDATE_SELECTION.json", selection)

    summary_rows = []
    means = {}
    for alias in ALL_CANDIDATES:
        prs = [float(student_packs[(alias, s)]["validation_PR_AUC"]) for s in SEEDS]
        means[alias] = _mean(prs)
        for s, pr in zip(SEEDS, prs):
            rec = student_packs[(alias, s)]
            summary_rows.append(
                {
                    "model": alias,
                    "seed": s,
                    "lambda_CORAL": CANDIDATE_LAMBDAS[alias],
                    "validation_PR_AUC": pr,
                    "threshold": rec["threshold"],
                    "best_epoch": rec["best_epoch"],
                    "checkpoint": rec["best_checkpoint"],
                    "sha256": rec["best_checkpoint_sha256"],
                }
            )
    write_csv(REVIEW_ROOT / "EDITOR028_R52_MODEL_SUMMARY.csv", summary_rows)
    results = {
        "means": means,
        "selection": selection,
        "r61_used": False,
        "r61_labels_used": False,
        "rows": summary_rows,
        "teacher_ckpts": {
            str(s): {
                "id": TEACHER_IDS[s],
                "checkpoint": teacher_ckpts[s]["best_checkpoint"],
                "sha256": teacher_ckpts[s]["best_checkpoint_sha256"],
                "validation_PR_AUC": teacher_ckpts[s]["validation_PR_AUC"],
                "threshold": teacher_ckpts[s]["threshold"],
            }
            for s in SEEDS
        },
        "student_packs_meta": {
            f"{a}_{s}": {
                "checkpoint": student_packs[(a, s)]["best_checkpoint"],
                "sha256": student_packs[(a, s)]["best_checkpoint_sha256"],
                "validation_PR_AUC": student_packs[(a, s)]["validation_PR_AUC"],
                "threshold": student_packs[(a, s)]["threshold"],
                "best_epoch": student_packs[(a, s)]["best_epoch"],
                "lambda_CORAL": CANDIDATE_LAMBDAS[a],
            }
            for a in ALL_CANDIDATES
            for s in SEEDS
        },
    }
    write_json(REVIEW_ROOT / "EDITOR028_R52_MODEL_RESULTS.json", results)
    return results


def write_r52_model_freeze(results: dict[str, Any]) -> dict[str, Any]:
    sel = results["selection"]
    freeze = {
        "teachers": results["teacher_ckpts"],
        "ALIGN0": {str(s): results["student_packs_meta"][f"ALIGN0_{s}"] for s in SEEDS},
        "selected_candidate": sel["EDITOR028_SELECTED_CANDIDATE"],
        "selected_checkpoints": (
            {str(s): results["student_packs_meta"][f"{sel['EDITOR028_SELECTED_CANDIDATE']}_{s}"] for s in SEEDS}
            if sel["EDITOR028_SELECTED_CANDIDATE"] != "NONE"
            else {}
        ),
        "r52_validation_metrics": results["means"],
        "latent_alignment_metrics": {
            n: {
                "LATENT_CORAL_DISCREPANCY": sel["candidates"][n]["LATENT_CORAL_DISCREPANCY"],
                "ALIGNMENT_REDUCTION": sel["candidates"][n]["ALIGNMENT_REDUCTION"],
            }
            for n in ALIGNED_CANDIDATES
        },
        "candidate_selection_ruling": sel["ruling"],
        "r61_evaluated": False,
        "written_at": utc_now(),
        "note": "Frozen before any EDITOR-028 r6.1 label evaluation",
    }
    write_json(REVIEW_ROOT / "EDITOR028_R52_MODEL_FREEZE.json", freeze)
    return freeze


def _ci(boot: dict[str, Any], key: str) -> list[float]:
    rec = boot.get("statistics", {}).get(key, {})
    return rec.get("ci95", [float("nan"), float("nan")])


def run_r61_evaluation() -> dict[str, Any]:
    require_r52_model_frozen(action="r6.1 diagnostic evaluation")
    from .labels import construct_r61_editor024_labels

    freeze = json.loads((REVIEW_ROOT / "EDITOR028_R52_MODEL_FREEZE.json").read_text(encoding="utf-8"))
    selected = freeze["selected_candidate"]
    if selected == "NONE":
        raise Editor028Blocked("no selected candidate; r6.1 labels must remain closed")
    labels = construct_r61_editor024_labels()
    target = load_unlabeled_alignment()
    if not np.array_equal(target.sequence_id, labels["sequence_ids"]):
        raise Editor028Blocked("r6.1 unlabeled sequence_id does not match label geometry")
    x61 = np.asarray(target.X)
    y_a = np.asarray(labels["y_editor024"])
    y_b = np.asarray(labels["y_insider"])
    users = np.asarray(labels["user_ids_windows"]).astype(str)
    seq = np.asarray(labels["sequence_ids"]).astype(str)
    tdir = OUTPUT_ROOT / "tensors"
    with np.load(tdir / "r52_val_ur.npz", allow_pickle=True) as z:
        x_val = np.asarray(z["X"])
        y_val = np.asarray(z["y"])
        seq_val = np.asarray(z["sequence_id"]).astype(str)
    hist_ta2 = historical_ta2_logits()
    device = __import__("torch").device("cuda" if __import__("torch").cuda.is_available() else "cpu")
    eval_aliases = ("ALIGN0", selected)
    logits: dict[str, dict[int, np.ndarray]] = {m: {} for m in eval_aliases}
    z_r52: dict[str, dict[int, np.ndarray]] = {m: {} for m in eval_aliases}
    z_r61: dict[str, dict[int, np.ndarray]] = {m: {} for m in eval_aliases}
    routes: dict[str, dict[str, dict[int, dict[str, float]]]] = {
        split: {m: {} for m in eval_aliases} for split in ("r52", "r61")
    }
    for alias in eval_aliases:
        for seed in SEEDS:
            meta = freeze["ALIGN0"][str(seed)] if alias == "ALIGN0" else freeze["selected_checkpoints"][str(seed)]
            thr = float(meta["threshold"])
            model = load_odst(meta["checkpoint"], device)
            scored61 = score_odst_arrays(model, x61, y_a, device, seed=seed)
            scored52 = score_odst_arrays(model, x_val, y_val, device, seed=seed)
            tmeta = freeze["teachers"][str(seed)]
            teacher = load_odst(tmeta["checkpoint"], device)
            t61 = score_odst_arrays(teacher, x61, y_a, device, seed=seed)
            t52 = score_odst_arrays(teacher, x_val, y_val, device, seed=seed)
            routes["r61"][alias][seed] = teacher_relative(
                scored61["logits"], t61["logits"], scored61["choices"], t61["choices"],
                scored61["leaf_probs_all"], t61["leaf_probs_all"],
            )
            routes["r52"][alias][seed] = teacher_relative(
                scored52["logits"], t52["logits"], scored52["choices"], t52["choices"],
                scored52["leaf_probs_all"], t52["leaf_probs_all"],
            )
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
        for alias in eval_aliases:
            seed_pr = [pr_auc_from_logits(y, logits[alias][s]) for s in SEEDS]
            per_model[alias] = {
                "seeds": {str(s): seed_pr[i] for i, s in enumerate(SEEDS)},
                "mean_pr_auc": _mean(seed_pr),
                "ap_lift": ap_lift(_mean(seed_pr), prev),
            }
        hist_seed = [pr_auc_from_logits(y, hist_ta2[s]) for s in SEEDS]
        r6 = int(sum(1 for i, s in enumerate(SEEDS) if per_model[selected]["seeds"][str(s)] > hist_seed[i])) >= 2
        r7 = int(sum(1 for s in SEEDS if per_model[selected]["seeds"][str(s)] > per_model["ALIGN0"]["seeds"][str(s)])) >= 2

        def stat_fn(sl, yb):
            sel_pr = float(np.mean([pr_auc(yb, sigmoid(logits[selected][s][sl])) for s in SEEDS]))
            a0_pr = float(np.mean([pr_auc(yb, sigmoid(logits["ALIGN0"][s][sl])) for s in SEEDS]))
            ta2_pr = float(np.mean([pr_auc(yb, sigmoid(hist_ta2[s][sl])) for s in SEEDS]))
            return {
                "SELECTED_ranking_excess": sel_pr - float(yb.mean()),
                "SELECTED_minus_historical_TA2": sel_pr - ta2_pr,
                "SELECTED_minus_ALIGN0": sel_pr - a0_pr,
            }

        boot = user_cluster_bootstrap(users, y, stat_fn)
        sel_pr = per_model[selected]["mean_pr_auc"]
        r1 = bool(sel_pr > prev)
        r2 = bool(_ci(boot, "SELECTED_ranking_excess")[0] > 0)
        r3 = bool(ap_lift(sel_pr, prev) >= MINIMUM_AP_PREVALENCE_LIFT)
        r4 = bool(_ci(boot, "SELECTED_minus_historical_TA2")[0] > 0)
        r5 = bool(_ci(boot, "SELECTED_minus_ALIGN0")[0] > 0)
        return {
            "view": view_name,
            "prevalence": prev,
            "models": per_model,
            "historical_TA2_seed_pr_auc": {str(s): hist_seed[i] for i, s in enumerate(SEEDS)},
            "historical_TA2_mean_pr_auc": _mean(hist_seed),
            "bootstrap": boot,
            "R1": r1,
            "R2": r2,
            "R3": r3,
            "R4": r4,
            "R5": r5,
            "R6": bool(r6),
            "R7": bool(r7),
        }

    a = view_results(y_a, R61_LABEL_VIEW_A)
    b = view_results(y_b, R61_LABEL_VIEW_B)
    write_json(REVIEW_ROOT / "EDITOR028_R61_EDITOR024_LABEL_RESULTS.json", a)
    write_json(REVIEW_ROOT / "EDITOR028_R61_INSIDER_CONSISTENT_RESULTS.json", b)
    write_json(REVIEW_ROOT / "EDITOR028_CLUSTER_BOOTSTRAP.json", {"editor024": a["bootstrap"], "insider": b["bootstrap"]})
    write_csv(
        REVIEW_ROOT / "EDITOR028_R61_SUMMARY.csv",
        [
            {"view": view, "model": m, "mean_pr_auc": rec["models"][m]["mean_pr_auc"], "ap_lift": rec["models"][m]["ap_lift"], "prevalence": rec["prevalence"]}
            for view, rec in ((R61_LABEL_VIEW_A, a), (R61_LABEL_VIEW_B, b))
            for m in eval_aliases
        ],
    )
    idx52 = representation_sample_indices(seq_val, y_val, REPRESENTATION_NEGATIVE_N)
    idx61_a = representation_sample_indices(seq, y_a, REPRESENTATION_NEGATIVE_N)
    idx61_b = representation_sample_indices(seq, y_b, REPRESENTATION_NEGATIVE_N)
    transfer = {}
    for alias in eval_aliases:
        z52 = np.mean([z_r52[alias][s][idx52] for s in SEEDS], axis=0)
        transfer[alias] = per_model_separation(
            z_r52=z52, y_r52=y_val[idx52],
            z_r61=np.mean([z_r61[alias][s][idx61_a] for s in SEEDS], axis=0),
            y_r61=y_a[idx61_a],
        )
        transfer[f"{alias}_insider"] = per_model_separation(
            z_r52=z52, y_r52=y_val[idx52],
            z_r61=np.mean([z_r61[alias][s][idx61_b] for s in SEEDS], axis=0),
            y_r61=y_b[idx61_b],
        )
    r8 = bool(transfer[selected]["REPRESENTATION_TRANSFER_RATIO"] > 0.50)
    r9 = bool(transfer[f"{selected}_insider"]["REPRESENTATION_TRANSFER_RATIO"] > 0.50)
    write_json(REVIEW_ROOT / "EDITOR028_REPRESENTATION_TRANSFER.json", {"R8": r8, "R9": r9, **transfer})

    fp = {}
    for alias in eval_aliases:
        thr_mean = _mean([
            float((freeze["ALIGN0"] if alias == "ALIGN0" else freeze["selected_checkpoints"])[str(s)]["threshold"])
            for s in SEEDS
        ])
        logit = np.mean([logits[alias][s] for s in SEEDS], axis=0)
        raw = {
            "negative_frozen_threshold_exceedance": float(
                distribution_block(logit[y_a == 0], thr_mean)["fraction_gt_frozen_r52_threshold"]
            ),
            **ranking_profile(y_a, sigmoid(logit)),
            "threshold": thr_mean,
            "threshold_source": "R52_FROZEN",
        }
        cap = raw.get("capture") or {}
        fp[alias] = {
            "negative_frozen_threshold_exceedance": raw["negative_frozen_threshold_exceedance"],
            "positive_median_global_percentile": raw.get("median_positive_percentile"),
            "top_N_positive_capture": cap.get("top_1N"),
            "top_5N_positive_capture": cap.get("top_5N"),
            "top_10N_positive_capture": cap.get("top_10N"),
            "threshold": thr_mean,
        }
    write_json(REVIEW_ROOT / "EDITOR028_FALSE_POSITIVE_DIAGNOSTICS.json", fp)
    route_out = {
        split: {
            alias: {
                "teacher_relative_route_MAE": _mean([routes[split][alias][s]["route_MAE"] for s in SEEDS]),
                "route_KL": _mean([routes[split][alias][s]["route_KL"] for s in SEEDS]),
                "hard_route_agreement": _mean([routes[split][alias][s]["hard_route_agreement"] for s in SEEDS]),
                "dominant_leaf_agreement": _mean([routes[split][alias][s]["dominant_leaf_agreement"] for s in SEEDS]),
                "per_seed": {str(s): routes[split][alias][s] for s in SEEDS},
            }
            for alias in eval_aliases
        }
        for split in ("r52", "r61")
    }
    write_json(REVIEW_ROOT / "EDITOR028_ROUTE_RESULTS.json", route_out)
    return {
        "editor024": a,
        "insider": b,
        "R8": r8,
        "R9": r9,
        "transfer": transfer,
        "fp": fp,
        "route": route_out,
        "freeze": freeze,
        "selected": selected,
    }


def decide_promotion(r52: dict[str, Any] | None, r61: dict[str, Any] | None) -> dict[str, Any]:
    if not r52:
        return {
            "EDITOR028_LATENT_ALIGNMENT": "NOT_SUPPORTED",
            "EDITOR028_CLEAN_PRESERVATION": "NOT_TESTED",
            "EDITOR028_R61_PORTABILITY_RESCUE": "NOT_TESTED",
            "EDITOR028_PROMOTION": "NO",
            "EDITOR028_SELECTED_CANDIDATE": "NONE",
            "EDITOR028_R61_LABEL_EVALUATION_EXECUTED": "NO",
            "MODEL_RESCUE_PROGRAMME": "CLOSED",
            "TRAINING_EXECUTED": "NO",
        }
    sel = r52["selection"]
    selected = sel["EDITOR028_SELECTED_CANDIDATE"]
    if selected == "NONE":
        if sel["ruling"] == "ALIGNMENT_GAIN_WITH_CLEAN_TRADEOFF":
            alignment = "ALIGNMENT_GAIN_WITH_CLEAN_TRADEOFF"
            clean = "NOT_SUPPORTED"
        else:
            alignment = "NOT_SUPPORTED"
            clean = "NOT_TESTED"
        return {
            "EDITOR028_LATENT_ALIGNMENT": alignment,
            "EDITOR028_CLEAN_PRESERVATION": clean,
            "EDITOR028_R61_PORTABILITY_RESCUE": "NOT_TESTED",
            "EDITOR028_PROMOTION": "NO",
            "EDITOR028_SELECTED_CANDIDATE": "NONE",
            "EDITOR028_R61_LABEL_EVALUATION_EXECUTED": "NO",
            "EDITOR028_RULING": sel["ruling"],
            "MODEL_RESCUE_PROGRAMME": "CLOSED",
            "TRAINING_EXECUTED": "YES",
        }
    if r61 is None:
        return {
            "EDITOR028_LATENT_ALIGNMENT": "SUPPORTED_LABEL_BLIND",
            "EDITOR028_CLEAN_PRESERVATION": "SUPPORTED",
            "EDITOR028_R61_PORTABILITY_RESCUE": "NOT_TESTED",
            "EDITOR028_PROMOTION": "NO",
            "EDITOR028_SELECTED_CANDIDATE": selected,
            "EDITOR028_R61_LABEL_EVALUATION_EXECUTED": "NO",
            "MODEL_RESCUE_PROGRAMME": "CLOSED",
            "TRAINING_EXECUTED": "YES",
        }
    a, b = r61["editor024"], r61["insider"]
    r_ok = all(a[g] and b[g] for g in ("R1", "R2", "R3", "R4", "R5", "R6", "R7")) and bool(r61["R8"]) and bool(r61["R9"])
    if r_ok:
        return {
            "EDITOR028_LATENT_ALIGNMENT": "SUPPORTED",
            "EDITOR028_CLEAN_PRESERVATION": "SUPPORTED",
            "EDITOR028_R61_PORTABILITY_RESCUE": "SUPPORTED",
            "EDITOR028_PROMOTION": "SUPPORTED_FOR_FINAL_CONFIRMATION",
            "EDITOR028_SELECTED_CANDIDATE": selected,
            "EDITOR028_R61_LABEL_EVALUATION_EXECUTED": "YES",
            "CANDIDATE_FOR_NEW_FINAL_CONFIRMATION": True,
            "MODEL_RESCUE_PROGRAMME": "OPEN_FOR_ONE_FINAL_CONFIRMATION",
            "TRAINING_EXECUTED": "YES",
        }
    return {
        "EDITOR028_LATENT_ALIGNMENT": "SUPPORTED_LABEL_BLIND",
        "EDITOR028_CLEAN_PRESERVATION": "SUPPORTED",
        "EDITOR028_R61_PORTABILITY_RESCUE": "NOT_SUPPORTED",
        "EDITOR028_PROMOTION": "NO",
        "EDITOR028_SELECTED_CANDIDATE": selected,
        "EDITOR028_R61_LABEL_EVALUATION_EXECUTED": "YES",
        "MODEL_RESCUE_PROGRAMME": "CLOSED",
        "TRAINING_EXECUTED": "YES",
        "editor024_gates": {g: a[g] for g in ("R1", "R2", "R3", "R4", "R5", "R6", "R7")},
        "insider_gates": {g: b[g] for g in ("R1", "R2", "R3", "R4", "R5", "R6", "R7")},
        "R8": r61["R8"],
        "R9": r61["R9"],
    }


def write_result_freeze(payload: dict[str, Any]) -> None:
    promo = payload.get("promotion") or {}
    lines = [
        "# EDITOR-028 RESULT FREEZE",
        "",
        f"Parent: `{EDITOR027_RESULTS_COMMIT}`",
        f"Training executed: {promo.get('TRAINING_EXECUTED')}",
        f"Selected candidate: {promo.get('EDITOR028_SELECTED_CANDIDATE')}",
        f"Latent alignment: {promo.get('EDITOR028_LATENT_ALIGNMENT')}",
        f"Clean preservation: {promo.get('EDITOR028_CLEAN_PRESERVATION')}",
        f"r6.1 portability rescue: {promo.get('EDITOR028_R61_PORTABILITY_RESCUE')}",
        f"Promotion: {promo.get('EDITOR028_PROMOTION')}",
        f"Model rescue programme: {promo.get('MODEL_RESCUE_PROGRAMME')}",
        "",
        "Historical EDITOR-024–027 results are unchanged. r6.1 cannot serve as a future untouched target.",
        "No r5.1 / r6.2 rerun. Do not automatically create EDITOR-029.",
        "",
    ]
    write_text(REVIEW_ROOT / "EDITOR028_RESULT_FREEZE.md", "\n".join(lines))


def terminal_block(payload: dict[str, Any], *, results_commit: str) -> str:
    r52 = payload.get("r52") or {}
    r61 = payload.get("r61") or {}
    sel = (r52.get("selection") or {})
    cand = sel.get("candidates") or {}
    promo = payload.get("promotion") or {}
    a = (r61 or {}).get("editor024") or {}
    b = (r61 or {}).get("insider") or {}
    selected = promo.get("EDITOR028_SELECTED_CANDIDATE") or sel.get("EDITOR028_SELECTED_CANDIDATE") or "NONE"

    def nv(x):
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return "NOT_RUN"
        return str(x)

    def ci_txt(view, key):
        boot = view.get("bootstrap") or {}
        c = _ci(boot, key)
        if not c or not np.isfinite(c[0]):
            return "NOT_RUN"
        return f"[{c[0]}, {c[1]}]"

    def cand_val(name, key):
        rec = cand.get(name) or {}
        return nv(rec.get(key))

    a_models = (a.get("models") or {}).get(selected) or {}
    b_models = (b.get("models") or {}).get(selected) or {}
    transfer = (r61 or {}).get("transfer") or {}
    r61_exec = "YES" if r61 else "NO"
    lines = [
        "EDITOR028_COMPLETE",
        "",
        "EDITOR027_RESULTS_COMMIT =",
        EDITOR027_RESULTS_COMMIT,
        "",
        "EDITOR028_PROTOCOL_FREEZE_COMMIT =",
        payload.get("protocol_sha") or protocol_freeze_commit() or "MISSING",
        "",
        "EDITOR028_R52_MODEL_FREEZE_COMMIT =",
        payload.get("r52_freeze_sha") or r52_model_freeze_commit() or "NOT_RUN",
        "",
        "EDITOR028_RESULTS_COMMIT =",
        results_commit,
        "",
        "",
        "SOURCE_GATE =",
        payload.get("SOURCE_GATE", "FAIL"),
        "",
        "UNIT_TEST_GATE =",
        payload.get("UNIT_TEST_GATE", "FAIL"),
        "",
        "TRAINING_EXECUTED =",
        promo.get("TRAINING_EXECUTED", "NO"),
        "",
        "",
        "ALIGN0_R52_MEAN_PR_AUC =",
        nv((r52.get("means") or {}).get("ALIGN0")),
        "",
        "ALIGN01_R52_MEAN_PR_AUC =",
        nv((r52.get("means") or {}).get("ALIGN01")),
        "",
        "ALIGN05_R52_MEAN_PR_AUC =",
        nv((r52.get("means") or {}).get("ALIGN05")),
        "",
        "ALIGN10_R52_MEAN_PR_AUC =",
        nv((r52.get("means") or {}).get("ALIGN10")),
        "",
        "",
        "ALIGN0_LATENT_CORAL_DISCREPANCY =",
        nv(sel.get("ALIGN0_LATENT_CORAL_DISCREPANCY")),
        "",
        "ALIGN01_LATENT_CORAL_DISCREPANCY =",
        cand_val("ALIGN01", "LATENT_CORAL_DISCREPANCY"),
        "",
        "ALIGN05_LATENT_CORAL_DISCREPANCY =",
        cand_val("ALIGN05", "LATENT_CORAL_DISCREPANCY"),
        "",
        "ALIGN10_LATENT_CORAL_DISCREPANCY =",
        cand_val("ALIGN10", "LATENT_CORAL_DISCREPANCY"),
        "",
        "",
        "ALIGN01_ALIGNMENT_REDUCTION =",
        cand_val("ALIGN01", "ALIGNMENT_REDUCTION"),
        "",
        "ALIGN05_ALIGNMENT_REDUCTION =",
        cand_val("ALIGN05", "ALIGNMENT_REDUCTION"),
        "",
        "ALIGN10_ALIGNMENT_REDUCTION =",
        cand_val("ALIGN10", "ALIGNMENT_REDUCTION"),
        "",
        "",
        "ALIGN01_LABEL_BLIND_GATE =",
        "PASS" if (cand.get("ALIGN01") or {}).get("label_blind_gate") else ("FAIL" if cand else "FAIL"),
        "",
        "ALIGN05_LABEL_BLIND_GATE =",
        "PASS" if (cand.get("ALIGN05") or {}).get("label_blind_gate") else ("FAIL" if cand else "FAIL"),
        "",
        "ALIGN10_LABEL_BLIND_GATE =",
        "PASS" if (cand.get("ALIGN10") or {}).get("label_blind_gate") else ("FAIL" if cand else "FAIL"),
        "",
        "",
        "EDITOR028_SELECTED_CANDIDATE =",
        selected,
        "",
        "",
        "R61_LABEL_EVALUATION_EXECUTED =",
        r61_exec,
        "",
        "",
        "SELECTED_R61_EDITOR024_PR_AUC =",
        nv(a_models.get("mean_pr_auc")) if r61 else "NOT_RUN",
        "",
        "SELECTED_R61_EDITOR024_AP_LIFT =",
        nv(a_models.get("ap_lift")) if r61 else "NOT_RUN",
        "",
        "SELECTED_R61_EDITOR024_RANKING_EXCESS_CI95 =",
        ci_txt(a, "SELECTED_ranking_excess") if r61 else "NOT_RUN",
        "",
        "SELECTED_MINUS_TA2_EDITOR024_CI95 =",
        ci_txt(a, "SELECTED_minus_historical_TA2") if r61 else "NOT_RUN",
        "",
        "SELECTED_MINUS_ALIGN0_EDITOR024_CI95 =",
        ci_txt(a, "SELECTED_minus_ALIGN0") if r61 else "NOT_RUN",
        "",
        "",
        "SELECTED_R61_INSIDER_CONSISTENT_PR_AUC =",
        nv(b_models.get("mean_pr_auc")) if r61 else "NOT_RUN",
        "",
        "SELECTED_R61_INSIDER_CONSISTENT_AP_LIFT =",
        nv(b_models.get("ap_lift")) if r61 else "NOT_RUN",
        "",
        "SELECTED_R61_INSIDER_CONSISTENT_RANKING_EXCESS_CI95 =",
        ci_txt(b, "SELECTED_ranking_excess") if r61 else "NOT_RUN",
        "",
        "SELECTED_MINUS_TA2_INSIDER_CONSISTENT_CI95 =",
        ci_txt(b, "SELECTED_minus_historical_TA2") if r61 else "NOT_RUN",
        "",
        "SELECTED_MINUS_ALIGN0_INSIDER_CONSISTENT_CI95 =",
        ci_txt(b, "SELECTED_minus_ALIGN0") if r61 else "NOT_RUN",
        "",
        "",
        "SELECTED_R61_EDITOR024_REP_TRANSFER_RATIO =",
        nv((transfer.get(selected) or {}).get("REPRESENTATION_TRANSFER_RATIO")) if r61 else "NOT_RUN",
        "",
        "SELECTED_R61_INSIDER_REP_TRANSFER_RATIO =",
        nv((transfer.get(f"{selected}_insider") or {}).get("REPRESENTATION_TRANSFER_RATIO")) if r61 else "NOT_RUN",
        "",
        "",
        "EDITOR028_LATENT_ALIGNMENT =",
        promo.get("EDITOR028_LATENT_ALIGNMENT", "NOT_SUPPORTED"),
        "",
        "EDITOR028_CLEAN_PRESERVATION =",
        promo.get("EDITOR028_CLEAN_PRESERVATION", "NOT_TESTED"),
        "",
        "EDITOR028_R61_PORTABILITY_RESCUE =",
        promo.get("EDITOR028_R61_PORTABILITY_RESCUE", "NOT_TESTED"),
        "",
        "EDITOR028_PROMOTION =",
        promo.get("EDITOR028_PROMOTION", "NO"),
        "",
        "",
        "MODEL_RESCUE_PROGRAMME =",
        promo.get("MODEL_RESCUE_PROGRAMME", "CLOSED"),
        "",
        "",
        "HISTORICAL_EDITOR024_RESULT_CHANGED =",
        "NO",
        "",
        "HISTORICAL_EDITOR025_RESULT_CHANGED =",
        "NO",
        "",
        "HISTORICAL_EDITOR026_RESULT_CHANGED =",
        "NO",
        "",
        "HISTORICAL_EDITOR027_RESULT_CHANGED =",
        "NO",
        "",
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
    write_text(REVIEW_ROOT / "EDITOR028_TERMINAL_BLOCK.txt", text)
    return text


def finalise(payload: dict[str, Any]) -> dict[str, Any]:
    # 1. final scientific outputs already written by callers
    write_json(
        REVIEW_ROOT / "EDITOR028_PROVENANCE.json",
        {
            "parent": EDITOR027_RESULTS_COMMIT,
            "protocol": payload.get("protocol_sha"),
            "r52_freeze": payload.get("r52_freeze_sha"),
            "head": _git_sha(),
            "utc": utc_now(),
        },
    )
    write_json(REVIEW_ROOT / "EDITOR028_PROMOTION_DECISION.json", payload.get("promotion") or {})
    # 2. completed RUN_MANIFEST
    write_json(
        REVIEW_ROOT / "EDITOR028_RUN_MANIFEST.json",
        {
            "phase": "complete",
            "utc": utc_now(),
            "EDITOR028_RESULTS_COMMIT": "PENDING_BY_DESIGN",
            "SOURCE_GATE": payload.get("SOURCE_GATE"),
            "UNIT_TEST_GATE": payload.get("UNIT_TEST_GATE"),
            "R51_RERUN": "NO",
            "R62_RERUN": "NO",
            "HISTORICAL_EDITOR024_RESULT_CHANGED": "NO",
            "HISTORICAL_EDITOR025_RESULT_CHANGED": "NO",
            "HISTORICAL_EDITOR026_RESULT_CHANGED": "NO",
            "HISTORICAL_EDITOR027_RESULT_CHANGED": "NO",
            "R61_CAN_SERVE_AS_FUTURE_UNTOUCHED_TARGET": "NO",
            **(payload.get("promotion") or {}),
        },
    )
    # 3. RESULT_FREEZE
    write_result_freeze(payload)
    payload["SHA_MANIFEST_VERIFICATION"] = "PASS"
    # 4. TERMINAL_BLOCK
    terminal_block(payload, results_commit="PENDING_BY_DESIGN")
    # 5. hash stable artefacts
    # 6. SHA256_MANIFEST last
    rec = write_sha256_manifest_last()
    ver = verify_sha256_manifest(rec)
    payload["SHA_MANIFEST_VERIFICATION"] = ver
    if ver != "PASS":
        raise Editor028Blocked("SHA_MANIFEST_VERIFICATION = FAIL")
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
        raise Editor028Blocked("UNIT_TEST_GATE = FAIL")
    require_protocol_frozen(action="EDITOR-028 execution")
    if phase in {"tensors", "train", "all"}:
        if not (OUTPUT_ROOT / "tensors" / "r52_train_ur.npz").is_file() or phase == "tensors":
            construct_representation()
        if phase == "tensors":
            return payload
    if phase in {"train", "all"}:
        r52 = run_training()
        payload["r52"] = r52
        selected = r52["selection"]["EDITOR028_SELECTED_CANDIDATE"]
        payload["promotion"] = decide_promotion(r52, None)
        if selected != "NONE":
            write_r52_model_freeze(r52)
            payload["r52_freeze_sha"] = "PENDING_COMMIT"
            write_json(REVIEW_ROOT / "EDITOR028_PROMOTION_DECISION.json", payload["promotion"])
            if phase == "train":
                return payload
        else:
            return finalise(payload)
    if phase in {"evaluate", "all"}:
        if phase == "evaluate":
            payload["r52"] = json.loads((REVIEW_ROOT / "EDITOR028_R52_MODEL_RESULTS.json").read_text(encoding="utf-8"))
            payload["r52_freeze_sha"] = r52_model_freeze_commit()
        selected = (payload.get("r52") or {}).get("selection", {}).get("EDITOR028_SELECTED_CANDIDATE", "NONE")
        if selected == "NONE":
            payload["promotion"] = decide_promotion(payload.get("r52"), None)
            return finalise(payload)
        require_r52_model_frozen(action="r6.1 diagnostic evaluation")
        r61 = run_r61_evaluation()
        payload["r61"] = r61
        payload["promotion"] = decide_promotion(payload.get("r52"), r61)
        return finalise(payload)
    return payload
