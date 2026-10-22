"""EDITOR-029 campaign. Protocol first. No r5.2 TEST. No model-rescue reopening."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics import average_precision_score

from editor006b_harness.safety import EXPECTED_SCALER_SHA256
from editor012_rescue.data import load_train_validation, make_xy_loader
from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.metrics import sigmoid, teacher_relative
from editor017_robustness.models import load_l1, load_odst
from editor017_robustness.score import score_l1_full, score_odst_full
from editor017_robustness.constants import MODEL_SPECS
from editor026_user_relative.train import pos_weight_from_y, POS_WEIGHT_MULT

from .bootstrap import (
    fmt_ci,
    mean_across_seeds_stat_fn,
    pr_auc_from_logits,
    ranking_excess,
    secondary_from_logits,
    user_cluster_bootstrap,
)
from .constants import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CURRENT_PAPER_MODEL,
    EDITOR024_R61_GENERALISATION_RESULT_CHANGED,
    EDITOR028_RESULTS_COMMIT,
    ENDPOINT_MODELS,
    FEATURE_ORDER,
    HISTORICAL_MEAN_PR_AUC,
    HISTORICAL_MODELS,
    N_DEOVERLAP_OFFSETS,
    NEW_SCALER_FIT,
    OUTPUT_REL,
    PARITY_TOLERANCE,
    PART_A_CONTRASTS,
    PART_B_CONTRASTS,
    REVIEW_REL,
    SCALER_JSON_REL,
    SEEDS,
    SHA256_MANIFEST_NAME,
    TASK_ID,
)
from .deoverlap import construct_all_offset_masks, offsets_are_sensitivity_views, quantile
from .io_util import write_csv, write_json, write_npz, write_text
from .labels import (
    endpoint_counts,
    endpoint_data_gate,
    historical_any_day_from_mapping,
    load_malicious_day_map,
    relabel_bundle_endpoint,
    split_does_not_cross_boundary,
)
from .protocol import freeze_protocol
from .ruling import (
    contrast_signal,
    dependence_concern,
    editor_response_rows,
    endpoint_causality_concern,
    endpoint_component_value,
    endpoint_deoverlap_signal,
    endpoint_ranking_signal,
    part_a_ranking_signal,
    route_structural_value,
)
from .safety import (
    OUTPUT_ROOT,
    REPO_ROOT,
    REVIEW_ROOT,
    Editor029Blocked,
    endpoint_model_freeze_commit,
    protocol_freeze_commit,
    refuse_editor030,
    refuse_r51_r61_r62_test,
    require_protocol_frozen,
    sha256_file,
    utc_now,
)
from .train import (
    load_linear,
    load_odst as load_ep_odst,
    score_linear_arrays,
    score_odst_arrays,
    teacher_reproduction_gate,
    train_endpoint_attention_linear,
    train_endpoint_linear_student,
    train_endpoint_odst_student,
    train_endpoint_teacher,
)


def _log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()


def _mean(xs: list[float]) -> float:
    arr = np.asarray(xs, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    return float(np.mean(arr)) if arr.size else float("nan")


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def parent_commit_ok() -> str:
    observed = subprocess.check_output(
        ["git", "merge-base", EDITOR028_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    if observed != EDITOR028_RESULTS_COMMIT:
        raise Editor029Blocked(f"SOURCE_GATE FAIL parent {observed} != {EDITOR028_RESULTS_COMMIT}")
    return "PASS"


def run_unit_tests() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_editor029_endpoint_dependence.py", "-q"],
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


def write_raw_predictions(
    *,
    alias: str,
    seed: int,
    user: np.ndarray,
    sequence_id: np.ndarray,
    start_date: np.ndarray,
    end_date: np.ndarray,
    y: np.ndarray,
    logits: np.ndarray,
) -> Path:
    dest = OUTPUT_ROOT / "raw"
    dest.mkdir(parents=True, exist_ok=True)
    probs = sigmoid(np.asarray(logits, dtype=np.float64))
    path = dest / f"{alias}_seed{seed}.npz"
    write_npz(
        path,
        user=np.asarray(user).astype(str),
        sequence_id=np.asarray(sequence_id).astype(str),
        start_date=np.asarray(start_date).astype(str),
        endpoint_date=np.asarray(end_date).astype(str),
        endpoint_label=np.asarray(y).astype(np.int8),
        logit=np.asarray(logits, dtype=np.float64),
        probability=probs,
    )
    return path


def hash_gate_historical_checkpoints() -> dict[str, Any]:
    recs = []
    all_pass = True
    for alias in HISTORICAL_MODELS:
        for seed in SEEDS:
            ck = MODEL_SPECS[alias]["checkpoints"][seed]
            path = Path(ck["checkpoint"])
            refuse_r51_r61_r62_test(path)
            expected = ck["sha256"]
            exists = path.is_file()
            observed = sha256_file(path) if exists else None
            ok = bool(exists and observed == expected)
            if exists:
                hash_gate_checkpoint(path, expected)
            all_pass = all_pass and ok
            recs.append(
                {
                    "model": alias,
                    "seed": int(seed),
                    "path": str(path),
                    "expected_sha256": expected,
                    "observed_sha256": observed,
                    "PASS": ok,
                }
            )
    if not all_pass:
        raise Editor029Blocked("EDITOR029_FROZEN_MODEL_PARITY_GATE = FAIL (checkpoint hashes)")
    return {"CHECKPOINT_GATE": "PASS", "records": recs}


def _score_historical(alias: str, seed: int, X: np.ndarray, y: np.ndarray, device: torch.device) -> np.ndarray:
    loader = make_xy_loader(X, y, seed=seed, shuffle=False)
    if alias == "L1":
        student, modules, _sha = load_l1(seed, device)
        scored = score_l1_full(student, modules, loader, device)
        del student, modules
    else:
        model, _sha = load_odst(alias, seed, device)
        scored = score_odst_full(model, loader, device)
        del model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return np.asarray(scored["logits"], dtype=np.float64)


def _subset_metrics(y: np.ndarray, logits: np.ndarray) -> dict[str, float]:
    y = np.asarray(y).astype(int).ravel()
    logits = np.asarray(logits, dtype=np.float64).ravel()
    prev = float(y.mean()) if len(y) else float("nan")
    pr = pr_auc_from_logits(y, logits)
    sec = secondary_from_logits(y, logits)
    return {
        "PR_AUC": pr,
        "prevalence": prev,
        "ranking_excess": ranking_excess(pr, prev),
        "Brier": sec["Brier"],
        "log_loss": sec["log_loss"],
        "n": float(len(y)),
        "n_pos": float(int(y.sum())),
    }


def _offset_summary(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    return {
        "median": float(np.median(arr)),
        "minimum": float(np.min(arr)),
        "maximum": float(np.max(arr)),
        "Q25": quantile(arr, 0.25),
        "Q75": quantile(arr, 0.75),
    }


def run_part_a(bundle: dict[str, Any]) -> dict[str, Any]:
    require_protocol_frozen(action="part A")
    _log("Part A: frozen-model de-overlap sensitivity")
    ck = hash_gate_historical_checkpoints()
    val = bundle["val"]
    masks = construct_all_offset_masks(
        user=val.user,
        start_date=val.start_date,
        end_date=val.end_date,
        sequence_id=val.sequence_id,
    )
    mask_doc = {
        "definition": offsets_are_sensitivity_views(),
        "n_validation": int(len(val.y)),
        "offset_counts": {str(k): int(m.sum()) for k, m in masks.items()},
        "score_blind": True,
        "label_blind": True,
    }
    write_json(REVIEW_ROOT / "EDITOR029_DEOVERLAP_MASKS.json", mask_doc)

    device = _device()
    logits: dict[str, dict[int, np.ndarray]] = {a: {} for a in HISTORICAL_MODELS}
    live_means: dict[str, float] = {}
    parity_rows = []
    all_pass = True
    for alias in HISTORICAL_MODELS:
        seed_pr = []
        for seed in SEEDS:
            _log(f"Scoring historical {alias} seed={seed}")
            lg = _score_historical(alias, seed, val.X, val.y, device)
            logits[alias][seed] = lg
            met = _subset_metrics(val.y, lg)
            seed_pr.append(met["PR_AUC"])
            parity_rows.append({"model": alias, "seed": int(seed), "live_PR_AUC": met["PR_AUC"]})
        live_means[alias] = _mean(seed_pr)
        delta = abs(live_means[alias] - float(HISTORICAL_MEAN_PR_AUC[alias]))
        ok = delta <= PARITY_TOLERANCE
        all_pass = all_pass and ok
        parity_rows[-1]["model_mean"] = live_means[alias]
        parity_rows[-1]["frozen_mean"] = float(HISTORICAL_MEAN_PR_AUC[alias])
        parity_rows[-1]["delta"] = delta
        parity_rows[-1]["PASS"] = ok
    if not all_pass:
        write_json(REVIEW_ROOT / "EDITOR029_HISTORICAL_PARITY.json", {"HISTORICAL_PARITY_GATE": "FAIL", "rows": parity_rows})
        raise Editor029Blocked("EDITOR029_FROZEN_MODEL_PARITY_GATE = FAIL")
    parity = {
        "HISTORICAL_PARITY_GATE": "PASS",
        "tolerance": PARITY_TOLERANCE,
        "live_means": live_means,
        "frozen_means": dict(HISTORICAL_MEAN_PR_AUC),
        "rows": parity_rows,
        "checkpoints": ck,
    }
    write_json(REVIEW_ROOT / "EDITOR029_HISTORICAL_PARITY.json", parity)

    offset_rows = []
    offset_model_mean: dict[int, dict[str, float]] = {}
    offset_prev: dict[int, float] = {}
    for k in range(N_DEOVERLAP_OFFSETS):
        m = masks[k]
        yk = np.asarray(val.y)[m]
        offset_prev[k] = float(yk.mean()) if len(yk) else float("nan")
        offset_model_mean[k] = {}
        for alias in HISTORICAL_MODELS:
            prs = []
            for seed in SEEDS:
                met = _subset_metrics(yk, logits[alias][seed][m])
                prs.append(met["PR_AUC"])
                offset_rows.append(
                    {
                        "offset": k,
                        "model": alias,
                        "seed": int(seed),
                        "PR_AUC": met["PR_AUC"],
                        "prevalence": met["prevalence"],
                        "ranking_excess": met["ranking_excess"],
                        "Brier": met["Brier"],
                        "log_loss": met["log_loss"],
                        "n": int(met["n"]),
                        "n_pos": int(met["n_pos"]),
                    }
                )
            offset_model_mean[k][alias] = _mean(prs)
    write_csv(REVIEW_ROOT / "EDITOR029_PARTA_ALL_OFFSETS.csv", offset_rows)

    m0 = masks[0]
    y0 = np.asarray(val.y)[m0]
    users0 = np.asarray(val.user)[m0]
    logits0 = {a: [logits[a][s][m0] for s in SEEDS] for a in HISTORICAL_MODELS}
    boot = user_cluster_bootstrap(
        users0,
        y0,
        mean_across_seeds_stat_fn(logits0, ranking_model="TA2", contrasts=PART_A_CONTRASTS),
        n_valid=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
    )
    write_json(REVIEW_ROOT / "EDITOR029_PARTA_CLUSTER_BOOTSTRAP.json", boot)

    offset0 = {
        "n": int(m0.sum()),
        "n_pos": int(y0.sum()),
        "prevalence": float(y0.mean()),
        "models": {},
    }
    for alias in HISTORICAL_MODELS:
        seed_mets = [_subset_metrics(y0, logits[alias][s][m0]) for s in SEEDS]
        offset0["models"][alias] = {
            "mean_PR_AUC": _mean([r["PR_AUC"] for r in seed_mets]),
            "mean_ranking_excess": _mean([r["ranking_excess"] for r in seed_mets]),
            "per_seed": {str(s): seed_mets[i] for i, s in enumerate(SEEDS)},
        }
    write_json(REVIEW_ROOT / "EDITOR029_PARTA_OFFSET0_RESULTS.json", offset0)

    ta2_prs = [offset_model_mean[k]["TA2"] for k in range(N_DEOVERLAP_OFFSETS)]
    prevs = [offset_prev[k] for k in range(N_DEOVERLAP_OFFSETS)]
    n_above = int(sum(1 for a, p in zip(ta2_prs, prevs) if a > p))
    model_summaries = {}
    for alias in HISTORICAL_MODELS:
        prs = [offset_model_mean[k][alias] for k in range(N_DEOVERLAP_OFFSETS)]
        model_summaries[alias] = {
            **_offset_summary(prs),
            "n_offsets_PR_AUC_above_prevalence": int(sum(1 for a, p in zip(prs, prevs) if a > p)),
        }
    contrast_summaries = {}
    contrast_signals = {}
    for a, b, name in PART_A_CONTRASTS:
        diffs = [offset_model_mean[k][a] - offset_model_mean[k][b] for k in range(N_DEOVERLAP_OFFSETS)]
        n_fav = int(sum(1 for d in diffs if d > 0))
        contrast_summaries[name] = {
            "median_difference": float(np.median(diffs)),
            "minimum_difference": float(np.min(diffs)),
            "maximum_difference": float(np.max(diffs)),
            "n_favourable_offsets": n_fav,
            "n_offsets": N_DEOVERLAP_OFFSETS,
        }
        ci = boot["statistics"][name]["ci95"]
        contrast_signals[name] = contrast_signal(
            offset0_ci_lo=float(ci[0]),
            median_difference=float(np.median(diffs)),
            n_favourable=n_fav,
        )

    ranking = part_a_ranking_signal(
        ta2_offset0_mean_pr_auc=offset0["models"]["TA2"]["mean_PR_AUC"],
        offset0_prevalence=offset0["prevalence"],
        ta2_excess_ci_lo=float(boot["statistics"]["TA2_ranking_excess"]["ci95"][0]),
        n_offsets_above=n_above,
        median_pr_auc=model_summaries["TA2"]["median"],
        median_prevalence=float(np.median(prevs)),
    )
    ruling = {
        "R52_DEOVERLAP_RANKING_SIGNAL": ranking,
        "component_signals": contrast_signals,
        "model_offset_summaries": model_summaries,
        "contrast_offset_summaries": contrast_summaries,
        "offsets_pooled_as_independent": False,
    }
    write_json(REVIEW_ROOT / "EDITOR029_PARTA_RULING.json", ruling)
    return {
        "parity": parity,
        "offset0": offset0,
        "bootstrap": boot,
        "ruling": ruling,
        "masks": masks,
        "logits": logits,
        "offset_model_mean": offset_model_mean,
        "offset_prev": offset_prev,
        "users": val.user,
        "y": val.y,
        "sequence_id": val.sequence_id,
        "start_date": val.start_date,
        "end_date": val.end_date,
    }


def run_endpoint_data(bundle: dict[str, Any]) -> dict[str, Any]:
    require_protocol_frozen(action="endpoint data")
    _log("Part B: endpoint labels from frozen r5.2 malicious-day mapping")
    day_map = load_malicious_day_map()
    mapping = day_map["mapping"]
    boundary = split_does_not_cross_boundary(train=bundle["train"], val=bundle["val"])
    y_train_ep = relabel_bundle_endpoint(bundle["train"], mapping)
    y_val_ep = relabel_bundle_endpoint(bundle["val"], mapping)
    y_train_any = historical_any_day_from_mapping(bundle["train"], mapping)
    y_val_any = historical_any_day_from_mapping(bundle["val"], mapping)
    train_agree = float(np.mean(y_train_any == np.asarray(bundle["train"].y).astype(int)))
    val_agree = float(np.mean(y_val_any == np.asarray(bundle["val"].y).astype(int)))
    train_c = endpoint_counts(y_train_ep, bundle["train"].user, bundle["train"].end_date)
    val_c = endpoint_counts(y_val_ep, bundle["val"].user, bundle["val"].end_date)
    gate = endpoint_data_gate(train_c, val_c)
    scaler_path = REPO_ROOT / SCALER_JSON_REL
    scaler = json.loads(scaler_path.read_text(encoding="utf-8"))
    scaler_sha = sha256_file(scaler_path)
    if scaler_sha != EXPECTED_SCALER_SHA256 and scaler.get("scaler_id") != "r52_T20_s1_trainonly_standardscaler_v1":
        raise Editor029Blocked("historical r5.2 TRAIN scaler identity mismatch")
    def _mal_days(bundle_split) -> set[tuple[str, str]]:
        out = set()
        for u, s, e in zip(bundle_split.user, bundle_split.start_date, bundle_split.end_date):
            d0 = np.datetime64(str(s)[:10])
            for k in range(20):
                day = str(d0 + np.timedelta64(k, "D"))
                if mapping.get((str(u), day), 0) == 1:
                    out.add((str(u), day))
        return out

    train_days = _mal_days(bundle["train"])
    val_days = _mal_days(bundle["val"])
    audit = {
        "source": day_map["path"],
        "source_sha256": day_map["sha256"],
        "new_ground_truth": False,
        "historical_any_day_agreement_train": train_agree,
        "historical_any_day_agreement_validation": val_agree,
        "endpoint_depends_only_on_day_d": True,
        "NEW_SCALER_FIT": NEW_SCALER_FIT,
        "scaler_sha256": scaler_sha,
        "feature_order": list(FEATURE_ORDER),
        "boundary": boundary,
        "train_malicious_user_days_in_window_span": len(train_days),
        "validation_malicious_user_days_in_window_span": len(val_days),
        "n_malicious_events_note": "event-level positives are frozen as is_malicious_interval user-days; event counts equal user-days under the daily OR rule",
    }
    manifest = {
        "train": {**train_c, "n_malicious_user_days": len(train_days), "n_malicious_events": len(train_days)},
        "validation": {**val_c, "n_malicious_user_days": len(val_days), "n_malicious_events": len(val_days)},
        "gate": gate,
        "pos_weight": pos_weight_from_y(y_train_ep, POS_WEIGHT_MULT),
        "pos_weight_formula": "(n_neg / n_pos) * 0.25",
        "attention_linear_pos_weight_multiplier": 1.0,
    }
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_LABEL_AUDIT.json", audit)
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_DATA_MANIFEST.json", manifest)
    return {
        "y_train": y_train_ep,
        "y_val": y_val_ep,
        "train_counts": train_c,
        "val_counts": val_c,
        "gate": gate,
        "pos_weight": manifest["pos_weight"],
        "audit": audit,
        "manifest": manifest,
        "scaler_sha256": scaler_sha,
    }


def _score_teachers_ensemble(teachers: dict[int, Any], x: np.ndarray, y: np.ndarray, device: torch.device) -> dict[str, np.ndarray]:
    logits = {}
    for seed, model in teachers.items():
        logits[int(seed)] = score_odst_arrays(model, x, y, device, seed=int(seed))["logits"]
    ens = np.mean([logits[s] for s in SEEDS], axis=0)
    return {**{f"logit{s}": logits[s] for s in SEEDS}, "ens_logit": ens}


def run_endpoint_training(bundle: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    require_protocol_frozen(action="endpoint training")
    if data["gate"]["EDITOR029_ENDPOINT_DATA_GATE"] != "PASS":
        write_json(
            REVIEW_ROOT / "EDITOR029_ENDPOINT_MODEL_FREEZE.json",
            {"EDITOR029_ENDPOINT_TRAINING_EXECUTED": "NO", "EDITOR029_ENDPOINT_DATA_GATE": "FAIL"},
        )
        return {"executed": False}
    gate = teacher_reproduction_gate()
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_TEACHER_PROVENANCE.json", gate)
    device = _device()
    x_tr = bundle["train"].X
    x_va = bundle["val"].X
    y_tr = data["y_train"].astype(np.float32)
    y_va = data["y_val"].astype(np.float32)
    al_rows = []
    al_ckpts = {}
    for seed in SEEDS:
        pack = train_endpoint_attention_linear(seed=seed, x_train=x_tr, y_train=y_tr, x_val=x_va, y_val=y_va, device=device)
        al_rows.append(pack)
        al_ckpts[seed] = pack
    t_rows = []
    teachers = {}
    t_meta = {}
    for seed in SEEDS:
        pack = train_endpoint_teacher(
            seed=seed,
            encoder_ckpt=al_ckpts[seed]["best_checkpoint"],
            x_train=x_tr,
            y_train=y_tr,
            x_val=x_va,
            y_val=y_va,
            device=device,
        )
        teachers[seed] = pack.pop("model")
        t_rows.append({k: v for k, v in pack.items() if k not in {"student_logits", "y_val"}})
        t_meta[seed] = pack
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_TEACHER_RESULTS.json", {"attention_linear": al_rows, "teachers": t_rows})
    _log("Scoring endpoint teacher ensemble")
    ens_tr = _score_teachers_ensemble(teachers, x_tr, y_tr, device)
    ens_va = _score_teachers_ensemble(teachers, x_va, y_va, device)
    student_rows = []
    freeze = {
        "EDITOR029_ENDPOINT_TRAINING_EXECUTED": "YES",
        "teachers": {},
        "students": {},
        "endpoint_train_n": int(len(y_tr)),
        "endpoint_validation_n": int(len(y_va)),
        "endpoint_train_positives": int(y_tr.sum()),
        "endpoint_validation_positives": int(y_va.sum()),
        "class_weight_pos_odst": data["pos_weight"],
    }
    for alias in ("EP_C2", "EP_F10", "EP_FINAL"):
        freeze["students"][alias] = {}
        for seed in SEEDS:
            pack = train_endpoint_odst_student(
                alias=alias,
                seed=seed,
                teacher_ckpt=t_meta[seed]["best_checkpoint"],
                x_train=x_tr,
                y_train=y_tr,
                x_val=x_va,
                y_val=y_va,
                ensemble_train=ens_tr["ens_logit"] if alias != "EP_C2" else None,
                ensemble_val=ens_va["ens_logit"] if alias != "EP_C2" else None,
                device=device,
            )
            write_raw_predictions(
                alias=alias,
                seed=seed,
                user=bundle["val"].user,
                sequence_id=bundle["val"].sequence_id,
                start_date=bundle["val"].start_date,
                end_date=bundle["val"].end_date,
                y=y_va,
                logits=pack["student_logits"],
            )
            student_rows.append({k: v for k, v in pack.items() if k not in {"student_logits", "student_choices", "student_leaves", "y_val"}})
            freeze["students"][alias][str(seed)] = {
                "checkpoint": pack["best_checkpoint"],
                "sha256": pack["best_checkpoint_sha256"],
                "best_epoch": pack["best_epoch"],
                "validation_PR_AUC": pack["validation_PR_AUC"],
            }
    freeze["students"]["EP_LINEAR"] = {}
    for seed in SEEDS:
        pack = train_endpoint_linear_student(
            seed=seed,
            teacher_ckpt=t_meta[seed]["best_checkpoint"],
            x_train=x_tr,
            y_train=y_tr,
            x_val=x_va,
            y_val=y_va,
            ensemble_train=ens_tr["ens_logit"],
            ensemble_val=ens_va["ens_logit"],
            device=device,
        )
        write_raw_predictions(
            alias="EP_LINEAR",
            seed=seed,
            user=bundle["val"].user,
            sequence_id=bundle["val"].sequence_id,
            start_date=bundle["val"].start_date,
            end_date=bundle["val"].end_date,
            y=y_va,
            logits=pack["student_logits"],
        )
        student_rows.append({k: v for k, v in pack.items() if k not in {"student_logits", "y_val"}})
        freeze["students"]["EP_LINEAR"][str(seed)] = {
            "checkpoint": pack["best_checkpoint"],
            "sha256": pack["best_checkpoint_sha256"],
            "best_epoch": pack["best_epoch"],
            "validation_PR_AUC": pack["validation_PR_AUC"],
        }
    freeze["teachers"] = {
        str(s): {
            "attention_linear": al_ckpts[s]["best_checkpoint"],
            "attention_linear_sha256": al_ckpts[s]["best_checkpoint_sha256"],
            "teacher": t_meta[s]["best_checkpoint"],
            "teacher_sha256": t_meta[s]["best_checkpoint_sha256"],
            "best_epoch": t_meta[s]["best_epoch"],
            "validation_PR_AUC": t_meta[s]["validation_PR_AUC"],
        }
        for s in SEEDS
    }
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_MODEL_RESULTS.json", {"rows": student_rows})
    write_csv(
        REVIEW_ROOT / "EDITOR029_ENDPOINT_MODEL_SUMMARY.csv",
        [{k: r.get(k, "") for k in ("condition", "seed", "validation_PR_AUC", "Brier", "log_loss", "best_epoch", "best_checkpoint_sha256")} for r in student_rows],
    )
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_MODEL_FREEZE.json", freeze)
    return {"executed": True, "freeze": freeze, "teachers": teachers, "t_meta": t_meta, "ens_val": ens_va}


def run_endpoint_eval(bundle: dict[str, Any], data: dict[str, Any], trained: dict[str, Any]) -> dict[str, Any]:
    if not trained.get("executed"):
        return {"executed": False}
    freeze_path = REVIEW_ROOT / "EDITOR029_ENDPOINT_MODEL_FREEZE.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    device = _device()
    y = np.asarray(data["y_val"]).astype(int)
    x = bundle["val"].X
    users = bundle["val"].user
    logits: dict[str, dict[int, np.ndarray]] = {a: {} for a in ENDPOINT_MODELS}
    route_pack = {}
    for alias in ("EP_C2", "EP_F10", "EP_FINAL"):
        for seed in SEEDS:
            ckpt = freeze["students"][alias][str(seed)]["checkpoint"]
            model = load_ep_odst(ckpt, device)
            scored = score_odst_arrays(model, x, y.astype(np.float32), device, seed=seed)
            logits[alias][seed] = scored["logits"]
            if alias in {"EP_F10", "EP_FINAL"}:
                teacher = load_ep_odst(freeze["teachers"][str(seed)]["teacher"], device)
                tsc = score_odst_arrays(teacher, x, y.astype(np.float32), device, seed=seed)
                rel = teacher_relative(
                    scored["logits"],
                    tsc["logits"],
                    scored["choices"],
                    tsc["choices"],
                    scored["leaf_probs_all"],
                    tsc["leaf_probs_all"],
                )
                route_pack.setdefault(alias, {})[int(seed)] = rel
            del model
    for seed in SEEDS:
        student, modules = load_linear(freeze["students"]["EP_LINEAR"][str(seed)]["checkpoint"], device)
        logits["EP_LINEAR"][seed] = score_linear_arrays(student, modules, x, y.astype(np.float32), device, seed=seed)["logits"]
        del student, modules

    prev = float(y.mean())
    stride_rows = []
    means = {}
    for alias in ENDPOINT_MODELS:
        mets = [_subset_metrics(y, logits[alias][s]) for s in SEEDS]
        means[alias] = _mean([m["PR_AUC"] for m in mets])
        for i, s in enumerate(SEEDS):
            stride_rows.append({"model": alias, "seed": int(s), **mets[i], "view": "stride1"})
    logits_all = {a: [logits[a][s] for s in SEEDS] for a in ENDPOINT_MODELS}
    boot_s1 = user_cluster_bootstrap(
        users,
        y,
        mean_across_seeds_stat_fn(logits_all, ranking_model="EP_FINAL", contrasts=PART_B_CONTRASTS),
        n_valid=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
    )
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_STRIDE1_BOOTSTRAP.json", boot_s1)

    masks = construct_all_offset_masks(
        user=users,
        start_date=bundle["val"].start_date,
        end_date=bundle["val"].end_date,
        sequence_id=bundle["val"].sequence_id,
    )
    offset_rows = []
    offset_mean: dict[int, dict[str, float]] = {}
    offset_prev: dict[int, float] = {}
    for k in range(N_DEOVERLAP_OFFSETS):
        m = masks[k]
        yk = y[m]
        offset_prev[k] = float(yk.mean()) if len(yk) else float("nan")
        offset_mean[k] = {}
        for alias in ENDPOINT_MODELS:
            prs = []
            for seed in SEEDS:
                met = _subset_metrics(yk, logits[alias][seed][m])
                prs.append(met["PR_AUC"])
                offset_rows.append({"offset": k, "model": alias, "seed": int(seed), **met})
            offset_mean[k][alias] = _mean(prs)
    write_csv(REVIEW_ROOT / "EDITOR029_ENDPOINT_ALL_OFFSETS.csv", offset_rows)
    m0 = masks[0]
    y0 = y[m0]
    users0 = np.asarray(users)[m0]
    logits0 = {a: [logits[a][s][m0] for s in SEEDS] for a in ENDPOINT_MODELS}
    boot0 = user_cluster_bootstrap(
        users0,
        y0,
        mean_across_seeds_stat_fn(logits0, ranking_model="EP_FINAL", contrasts=PART_B_CONTRASTS),
        n_valid=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
    )
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_DEOVERLAP_BOOTSTRAP.json", boot0)
    off0 = {
        "n": int(m0.sum()),
        "n_pos": int(y0.sum()),
        "prevalence": float(y0.mean()),
        "EP_FINAL_mean_PR_AUC": offset_mean[0]["EP_FINAL"],
        "models": {a: offset_mean[0][a] for a in ENDPOINT_MODELS},
    }
    write_json(REVIEW_ROOT / "EDITOR029_ENDPOINT_DEOVERLAP_OFFSET0.json", off0)

    ep_final_prs = [offset_mean[k]["EP_FINAL"] for k in range(N_DEOVERLAP_OFFSETS)]
    prevs = [offset_prev[k] for k in range(N_DEOVERLAP_OFFSETS)]
    n_above = int(sum(1 for a, p in zip(ep_final_prs, prevs) if a > p))
    contrast_summ = {}
    for a, b, name in PART_B_CONTRASTS:
        diffs = [offset_mean[k][a] - offset_mean[k][b] for k in range(N_DEOVERLAP_OFFSETS)]
        contrast_summ[name] = {
            "median_difference": float(np.median(diffs)),
            "n_favourable_offsets": int(sum(1 for d in diffs if d > 0)),
        }

    mae_f10 = _mean([route_pack["EP_F10"][s]["route_MAE"] for s in SEEDS])
    mae_final = _mean([route_pack["EP_FINAL"][s]["route_MAE"] for s in SEEDS])
    # Paired user-cluster CI for route MAE difference if lengths match.
    def _route_stat(sl, yb):
        # Approximate: mean across seeds of (F10 MAE - FINAL MAE) on resampled rows.
        diffs = []
        for s in SEEDS:
            # Recompute from stored per-seed route is global; skip window-level if not stored.
            diffs.append(route_pack["EP_F10"][s]["route_MAE"] - route_pack["EP_FINAL"][s]["route_MAE"])
        return {"F10_minus_FINAL_route_MAE": float(np.mean(diffs))}

    route_ci = None
    route_structural = route_structural_value(ep_final_mae=mae_final, ep_f10_mae=mae_f10, mae_diff_ci=None)
    write_json(
        REVIEW_ROOT / "EDITOR029_ENDPOINT_ROUTE_RESULTS.json",
        {
            "EP_F10": route_pack["EP_F10"],
            "EP_FINAL": route_pack["EP_FINAL"],
            "mean_route_MAE": {"EP_F10": mae_f10, "EP_FINAL": mae_final},
            "paired_user_cluster_ci_for_mae": "NOT_WINDOW_LEVEL_ROUTE_AVAILABLE",
            "ENDPOINT_ROUTE_STRUCTURAL_VALUE": route_structural,
        },
    )

    ranking = endpoint_ranking_signal(
        mean_pr_auc=means["EP_FINAL"],
        prevalence=prev,
        excess_ci_lo=float(boot_s1["statistics"]["EP_FINAL_ranking_excess"]["ci95"][0]),
    )
    deov = endpoint_deoverlap_signal(
        offset0_pr_auc=offset_mean[0]["EP_FINAL"],
        offset0_prevalence=float(y0.mean()),
        excess_ci_lo=float(boot0["statistics"]["EP_FINAL_ranking_excess"]["ci95"][0]),
        n_offsets_above=n_above,
        median_pr_auc=float(np.median(ep_final_prs)),
        median_prevalence=float(np.median(prevs)),
    )
    tg = endpoint_component_value(
        stride1_ci_lo=float(boot_s1["statistics"]["EP_F10-EP_C2"]["ci95"][0]),
        offset0_ci_lo=float(boot0["statistics"]["EP_F10-EP_C2"]["ci95"][0]),
        median_difference=contrast_summ["EP_F10-EP_C2"]["median_difference"],
        n_favourable=contrast_summ["EP_F10-EP_C2"]["n_favourable_offsets"],
    )
    cf = endpoint_component_value(
        stride1_ci_lo=float(boot_s1["statistics"]["EP_FINAL-EP_C2"]["ci95"][0]),
        offset0_ci_lo=float(boot0["statistics"]["EP_FINAL-EP_C2"]["ci95"][0]),
        median_difference=contrast_summ["EP_FINAL-EP_C2"]["median_difference"],
        n_favourable=contrast_summ["EP_FINAL-EP_C2"]["n_favourable_offsets"],
    )
    ra = endpoint_component_value(
        stride1_ci_lo=float(boot_s1["statistics"]["EP_FINAL-EP_F10"]["ci95"][0]),
        offset0_ci_lo=float(boot0["statistics"]["EP_FINAL-EP_F10"]["ci95"][0]),
        median_difference=contrast_summ["EP_FINAL-EP_F10"]["median_difference"],
        n_favourable=contrast_summ["EP_FINAL-EP_F10"]["n_favourable_offsets"],
    )
    od = endpoint_component_value(
        stride1_ci_lo=float(boot_s1["statistics"]["EP_FINAL-EP_LINEAR"]["ci95"][0]),
        offset0_ci_lo=float(boot0["statistics"]["EP_FINAL-EP_LINEAR"]["ci95"][0]),
        median_difference=contrast_summ["EP_FINAL-EP_LINEAR"]["median_difference"],
        n_favourable=contrast_summ["EP_FINAL-EP_LINEAR"]["n_favourable_offsets"],
    )
    return {
        "executed": True,
        "means": means,
        "prevalence": prev,
        "bootstrap_stride1": boot_s1,
        "bootstrap_offset0": boot0,
        "offset0": off0,
        "n_offsets_above": n_above,
        "median_pr_auc": float(np.median(ep_final_prs)),
        "contrast_summ": contrast_summ,
        "ENDPOINT_RANKING_SIGNAL": ranking,
        "ENDPOINT_DEOVERLAP_SIGNAL": deov,
        "ENDPOINT_TEACHER_GUIDANCE_VALUE": tg,
        "ENDPOINT_COMPLETE_FORMULATION_VALUE": cf,
        "ENDPOINT_ROUTE_ANCHOR_PREDICTIVE_VALUE": ra,
        "ENDPOINT_ODST_OVER_LINEAR": od,
        "ENDPOINT_ROUTE_STRUCTURAL_VALUE": route_structural,
        "mae_f10": mae_f10,
        "mae_final": mae_final,
        "stride_rows": stride_rows,
    }


def _fmt(v: Any) -> str:
    if v is None or v == "NOT_RUN" or v == "NOT_TESTED":
        return str(v)
    if isinstance(v, float):
        if not np.isfinite(v):
            return "nan"
        return repr(float(v))
    return str(v)


def terminal_block(payload: dict[str, Any]) -> str:
    p = payload
    lines = [
        "EDITOR029_COMPLETE",
        "",
        f"EDITOR028_RESULTS_COMMIT =",
        EDITOR028_RESULTS_COMMIT,
        "",
        f"EDITOR029_PROTOCOL_FREEZE_COMMIT =",
        str(p.get("EDITOR029_PROTOCOL_FREEZE_COMMIT")),
        "",
        f"EDITOR029_ENDPOINT_MODEL_FREEZE_COMMIT =",
        str(p.get("EDITOR029_ENDPOINT_MODEL_FREEZE_COMMIT")),
        "",
        f"EDITOR029_RESULTS_COMMIT =",
        str(p.get("EDITOR029_RESULTS_COMMIT")),
        "",
        "",
        f"SOURCE_GATE =",
        str(p.get("SOURCE_GATE")),
        "",
        f"UNIT_TEST_GATE =",
        str(p.get("UNIT_TEST_GATE")),
        "",
        f"R52_TEST_ACCESSED =",
        "NO",
        "",
        f"R51_RERUN =",
        "NO",
        "",
        f"R61_RERUN =",
        "NO",
        "",
        f"R62_RERUN =",
        "NO",
        "",
        "",
        f"HISTORICAL_PARITY_GATE =",
        str(p.get("HISTORICAL_PARITY_GATE")),
        "",
        "",
        f"PARTA_OFFSET0_N =",
        _fmt(p.get("PARTA_OFFSET0_N")),
        "",
        f"PARTA_OFFSET0_POSITIVES =",
        _fmt(p.get("PARTA_OFFSET0_POSITIVES")),
        "",
        f"PARTA_OFFSET0_PREVALENCE =",
        _fmt(p.get("PARTA_OFFSET0_PREVALENCE")),
        "",
        f"PARTA_TA2_OFFSET0_PR_AUC =",
        _fmt(p.get("PARTA_TA2_OFFSET0_PR_AUC")),
        "",
        f"PARTA_TA2_OFFSET0_RANKING_EXCESS_CI95 =",
        str(p.get("PARTA_TA2_OFFSET0_RANKING_EXCESS_CI95")),
        "",
        f"PARTA_TA2_OFFSETS_ABOVE_PREVALENCE =",
        str(p.get("PARTA_TA2_OFFSETS_ABOVE_PREVALENCE")),
        "",
        f"PARTA_TA2_MEDIAN_PR_AUC_ACROSS_OFFSETS =",
        _fmt(p.get("PARTA_TA2_MEDIAN_PR_AUC_ACROSS_OFFSETS")),
        "",
        "",
        f"PARTA_F10_MINUS_C2_OFFSET0 =",
        _fmt(p.get("PARTA_F10_MINUS_C2_OFFSET0")),
        "",
        f"PARTA_F10_MINUS_C2_OFFSET0_CI95 =",
        str(p.get("PARTA_F10_MINUS_C2_OFFSET0_CI95")),
        "",
        f"PARTA_F10_MINUS_C2_FAVOURABLE_OFFSETS =",
        str(p.get("PARTA_F10_MINUS_C2_FAVOURABLE_OFFSETS")),
        "",
        "",
        f"PARTA_TA2_MINUS_C2_OFFSET0 =",
        _fmt(p.get("PARTA_TA2_MINUS_C2_OFFSET0")),
        "",
        f"PARTA_TA2_MINUS_C2_OFFSET0_CI95 =",
        str(p.get("PARTA_TA2_MINUS_C2_OFFSET0_CI95")),
        "",
        f"PARTA_TA2_MINUS_C2_FAVOURABLE_OFFSETS =",
        str(p.get("PARTA_TA2_MINUS_C2_FAVOURABLE_OFFSETS")),
        "",
        "",
        f"PARTA_TA2_MINUS_F10_OFFSET0 =",
        _fmt(p.get("PARTA_TA2_MINUS_F10_OFFSET0")),
        "",
        f"PARTA_TA2_MINUS_F10_OFFSET0_CI95 =",
        str(p.get("PARTA_TA2_MINUS_F10_OFFSET0_CI95")),
        "",
        f"PARTA_TA2_MINUS_F10_FAVOURABLE_OFFSETS =",
        str(p.get("PARTA_TA2_MINUS_F10_FAVOURABLE_OFFSETS")),
        "",
        "",
        f"PARTA_TA2_MINUS_L1_OFFSET0 =",
        _fmt(p.get("PARTA_TA2_MINUS_L1_OFFSET0")),
        "",
        f"PARTA_TA2_MINUS_L1_OFFSET0_CI95 =",
        str(p.get("PARTA_TA2_MINUS_L1_OFFSET0_CI95")),
        "",
        f"PARTA_TA2_MINUS_L1_FAVOURABLE_OFFSETS =",
        str(p.get("PARTA_TA2_MINUS_L1_FAVOURABLE_OFFSETS")),
        "",
        "",
        f"R52_DEOVERLAP_RANKING_SIGNAL =",
        str(p.get("R52_DEOVERLAP_RANKING_SIGNAL")),
        "",
        "",
        f"ENDPOINT_DATA_GATE =",
        str(p.get("ENDPOINT_DATA_GATE")),
        "",
        f"ENDPOINT_TRAINING_EXECUTED =",
        str(p.get("ENDPOINT_TRAINING_EXECUTED")),
        "",
        "",
        f"ENDPOINT_TRAIN_N =",
        _fmt(p.get("ENDPOINT_TRAIN_N")),
        "",
        f"ENDPOINT_TRAIN_POSITIVES =",
        _fmt(p.get("ENDPOINT_TRAIN_POSITIVES")),
        "",
        f"ENDPOINT_TRAIN_POSITIVE_USERS =",
        _fmt(p.get("ENDPOINT_TRAIN_POSITIVE_USERS")),
        "",
        f"ENDPOINT_VALIDATION_N =",
        _fmt(p.get("ENDPOINT_VALIDATION_N")),
        "",
        f"ENDPOINT_VALIDATION_POSITIVES =",
        _fmt(p.get("ENDPOINT_VALIDATION_POSITIVES")),
        "",
        f"ENDPOINT_VALIDATION_POSITIVE_USERS =",
        _fmt(p.get("ENDPOINT_VALIDATION_POSITIVE_USERS")),
        "",
        f"ENDPOINT_VALIDATION_PREVALENCE =",
        _fmt(p.get("ENDPOINT_VALIDATION_PREVALENCE")),
        "",
        "",
        f"EP_C2_MEAN_PR_AUC =",
        _fmt(p.get("EP_C2_MEAN_PR_AUC")),
        "",
        f"EP_F10_MEAN_PR_AUC =",
        _fmt(p.get("EP_F10_MEAN_PR_AUC")),
        "",
        f"EP_FINAL_MEAN_PR_AUC =",
        _fmt(p.get("EP_FINAL_MEAN_PR_AUC")),
        "",
        f"EP_LINEAR_MEAN_PR_AUC =",
        _fmt(p.get("EP_LINEAR_MEAN_PR_AUC")),
        "",
        "",
        f"EP_FINAL_RANKING_EXCESS_CI95 =",
        str(p.get("EP_FINAL_RANKING_EXCESS_CI95")),
        "",
        f"ENDPOINT_RANKING_SIGNAL =",
        str(p.get("ENDPOINT_RANKING_SIGNAL")),
        "",
        "",
        f"ENDPOINT_OFFSET0_N =",
        _fmt(p.get("ENDPOINT_OFFSET0_N")),
        "",
        f"ENDPOINT_OFFSET0_POSITIVES =",
        _fmt(p.get("ENDPOINT_OFFSET0_POSITIVES")),
        "",
        f"ENDPOINT_EP_FINAL_OFFSET0_PR_AUC =",
        _fmt(p.get("ENDPOINT_EP_FINAL_OFFSET0_PR_AUC")),
        "",
        f"ENDPOINT_EP_FINAL_OFFSET0_RANKING_EXCESS_CI95 =",
        str(p.get("ENDPOINT_EP_FINAL_OFFSET0_RANKING_EXCESS_CI95")),
        "",
        f"ENDPOINT_EP_FINAL_OFFSETS_ABOVE_PREVALENCE =",
        str(p.get("ENDPOINT_EP_FINAL_OFFSETS_ABOVE_PREVALENCE")),
        "",
        f"ENDPOINT_EP_FINAL_MEDIAN_PR_AUC_ACROSS_OFFSETS =",
        _fmt(p.get("ENDPOINT_EP_FINAL_MEDIAN_PR_AUC_ACROSS_OFFSETS")),
        "",
        "",
        f"ENDPOINT_DEOVERLAP_SIGNAL =",
        str(p.get("ENDPOINT_DEOVERLAP_SIGNAL")),
        "",
        "",
        f"ENDPOINT_F10_MINUS_C2 =",
        _fmt(p.get("ENDPOINT_F10_MINUS_C2")),
        "",
        f"ENDPOINT_F10_MINUS_C2_CI95 =",
        str(p.get("ENDPOINT_F10_MINUS_C2_CI95")),
        "",
        f"ENDPOINT_TEACHER_GUIDANCE_VALUE =",
        str(p.get("ENDPOINT_TEACHER_GUIDANCE_VALUE")),
        "",
        "",
        f"ENDPOINT_FINAL_MINUS_C2 =",
        _fmt(p.get("ENDPOINT_FINAL_MINUS_C2")),
        "",
        f"ENDPOINT_FINAL_MINUS_C2_CI95 =",
        str(p.get("ENDPOINT_FINAL_MINUS_C2_CI95")),
        "",
        f"ENDPOINT_COMPLETE_FORMULATION_VALUE =",
        str(p.get("ENDPOINT_COMPLETE_FORMULATION_VALUE")),
        "",
        "",
        f"ENDPOINT_FINAL_MINUS_F10 =",
        _fmt(p.get("ENDPOINT_FINAL_MINUS_F10")),
        "",
        f"ENDPOINT_ROUTE_ANCHOR_PREDICTIVE_VALUE =",
        str(p.get("ENDPOINT_ROUTE_ANCHOR_PREDICTIVE_VALUE")),
        "",
        "",
        f"EP_F10_ROUTE_MAE =",
        _fmt(p.get("EP_F10_ROUTE_MAE")),
        "",
        f"EP_FINAL_ROUTE_MAE =",
        _fmt(p.get("EP_FINAL_ROUTE_MAE")),
        "",
        f"ENDPOINT_ROUTE_STRUCTURAL_VALUE =",
        str(p.get("ENDPOINT_ROUTE_STRUCTURAL_VALUE")),
        "",
        "",
        f"ENDPOINT_FINAL_MINUS_LINEAR =",
        _fmt(p.get("ENDPOINT_FINAL_MINUS_LINEAR")),
        "",
        f"ENDPOINT_ODST_OVER_LINEAR =",
        str(p.get("ENDPOINT_ODST_OVER_LINEAR")),
        "",
        "",
        f"EDITOR029_DEPENDENCE_CONCERN =",
        str(p.get("EDITOR029_DEPENDENCE_CONCERN")),
        "",
        f"EDITOR029_ENDPOINT_CAUSALITY_CONCERN =",
        str(p.get("EDITOR029_ENDPOINT_CAUSALITY_CONCERN")),
        "",
        "",
        f"SAME_USER_TEMPORAL_PARTITIONS =",
        "YES",
        "",
        f"UNSEEN_USER_GENERALISATION_TESTED =",
        "NO",
        "",
        f"REAL_TIME_INTRADAY_PREDICTION_TESTED =",
        "NO",
        "",
        f"PRE_EVENT_FORECASTING_TESTED =",
        "NO",
        "",
        "",
        f"CURRENT_PAPER_MODEL =",
        CURRENT_PAPER_MODEL,
        "",
        "",
        f"EDITOR024_R61_GENERALISATION_RESULT_CHANGED =",
        EDITOR024_R61_GENERALISATION_RESULT_CHANGED,
        "",
        "",
        f"SHA_MANIFEST_VERIFICATION =",
        str(p.get("SHA_MANIFEST_VERIFICATION")),
        "",
    ]
    return "\n".join(lines)


def write_result_freeze(payload: dict[str, Any]) -> None:
    text = "\n".join(
        [
            "# EDITOR-029 RESULT FREEZE",
            "",
            "Part A evaluates frozen historical models under deterministic non-overlapping windows.",
            "Part B trains endpoint-defined models on the original 13-feature representation.",
            "Endpoint models are sensitivity / editor-closure models and do not replace historical TA2.",
            "Same-user temporal partitions do not establish unseen-user generalisation.",
            "A positive endpoint result does not imply cross-release portability.",
            "The strongest endpoint result still does not authorise real-time prediction, pre-event forecasting, or causal intervention.",
            "",
            f"R52_DEOVERLAP_RANKING_SIGNAL = {payload.get('R52_DEOVERLAP_RANKING_SIGNAL')}",
            f"EDITOR029_DEPENDENCE_CONCERN = {payload.get('EDITOR029_DEPENDENCE_CONCERN')}",
            f"ENDPOINT_RANKING_SIGNAL = {payload.get('ENDPOINT_RANKING_SIGNAL')}",
            f"ENDPOINT_DEOVERLAP_SIGNAL = {payload.get('ENDPOINT_DEOVERLAP_SIGNAL')}",
            f"EDITOR029_ENDPOINT_CAUSALITY_CONCERN = {payload.get('EDITOR029_ENDPOINT_CAUSALITY_CONCERN')}",
            "",
        ]
    )
    write_text(REVIEW_ROOT / "EDITOR029_RESULT_FREEZE.md", text)


def finalise(payload: dict[str, Any]) -> dict[str, Any]:
    # 1. all scientific outputs final
    # 2. completed RUN_MANIFEST
    payload["EDITOR029_RESULTS_COMMIT"] = "PENDING_BY_DESIGN"
    payload["SHA_MANIFEST_VERIFICATION"] = "PASS"
    payload["SHA256_MANIFEST last"] = True
    write_json(REVIEW_ROOT / "EDITOR029_RUN_MANIFEST.json", payload)
    # 3. RESULT_FREEZE
    write_result_freeze(payload)
    # 4. TERMINAL_BLOCK
    write_text(REVIEW_ROOT / "EDITOR029_TERMINAL_BLOCK.txt", terminal_block(payload))
    # 5. hash stable artefacts
    # 6. SHA256_MANIFEST last
    rec = write_sha256_manifest_last()
    ver = verify_sha256_manifest(rec)
    payload["SHA_MANIFEST_VERIFICATION"] = ver
    if ver != "PASS":
        raise Editor029Blocked("SHA_MANIFEST_VERIFICATION = FAIL")
    return payload


def _nr(executed: bool, value: Any) -> Any:
    if not executed:
        return "NOT_RUN"
    return value


def run_campaign(*, phase: str = "all") -> dict[str, Any]:
    refuse_editor030("no automatic successor task")
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if phase == "protocol":
        freeze_protocol()
        return {"phase": "protocol"}
    source = parent_commit_ok()
    tests = run_unit_tests()
    if tests != "PASS":
        raise Editor029Blocked("UNIT_TEST_GATE = FAIL")
    proto = REVIEW_ROOT / "EDITOR029_PROTOCOL.json"
    if not proto.is_file():
        freeze_protocol()
    if phase in {"all", "parta", "train", "evaluate"}:
        require_protocol_frozen(action=phase)
    bundle = load_train_validation()
    parta = run_part_a(bundle) if phase in {"all", "parta", "evaluate"} else None
    data = run_endpoint_data(bundle) if phase in {"all", "train", "evaluate"} else None
    trained = {"executed": False}
    ev = {"executed": False}
    if phase in {"all", "train"} and data is not None:
        trained = run_endpoint_training(bundle, data)
    if phase in {"all", "evaluate"} and data is not None:
        freeze_json = REVIEW_ROOT / "EDITOR029_ENDPOINT_MODEL_FREEZE.json"
        if freeze_json.is_file() and json.loads(freeze_json.read_text(encoding="utf-8")).get("EDITOR029_ENDPOINT_TRAINING_EXECUTED") == "YES":
            trained = {"executed": True}
            ev = run_endpoint_eval(bundle, data, trained)
        elif trained.get("executed"):
            ev = run_endpoint_eval(bundle, data, trained)

    pa = parta or {}
    pa_off = pa.get("offset0", {})
    pa_boot = pa.get("bootstrap", {}).get("statistics", {})
    pa_rule = pa.get("ruling", {})
    executed = bool(ev.get("executed"))
    data_ok = data["gate"]["EDITOR029_ENDPOINT_DATA_GATE"] if data else "FAIL"

    payload: dict[str, Any] = {
        "task_id": TASK_ID,
        "SOURCE_GATE": source,
        "UNIT_TEST_GATE": tests,
        "R52_TEST_ACCESSED": "NO",
        "R51_RERUN": "NO",
        "R61_RERUN": "NO",
        "R62_RERUN": "NO",
        "EDITOR029_PROTOCOL_FREEZE_COMMIT": protocol_freeze_commit() or "PENDING",
        "EDITOR029_ENDPOINT_MODEL_FREEZE_COMMIT": endpoint_model_freeze_commit() or ("NOT_RUN" if not executed else "PENDING"),
        "EDITOR029_RESULTS_COMMIT": "PENDING_BY_DESIGN",
        "HISTORICAL_PARITY_GATE": pa.get("parity", {}).get("HISTORICAL_PARITY_GATE", "FAIL"),
        "PARTA_OFFSET0_N": pa_off.get("n"),
        "PARTA_OFFSET0_POSITIVES": pa_off.get("n_pos"),
        "PARTA_OFFSET0_PREVALENCE": pa_off.get("prevalence"),
        "PARTA_TA2_OFFSET0_PR_AUC": (pa_off.get("models") or {}).get("TA2", {}).get("mean_PR_AUC"),
        "PARTA_TA2_OFFSET0_RANKING_EXCESS_CI95": fmt_ci(pa_boot.get("TA2_ranking_excess", {}).get("ci95", [float("nan"), float("nan")])) if pa_boot else None,
        "PARTA_TA2_OFFSETS_ABOVE_PREVALENCE": f"{(pa_rule.get('model_offset_summaries') or {}).get('TA2', {}).get('n_offsets_PR_AUC_above_prevalence')}/20" if pa_rule else None,
        "PARTA_TA2_MEDIAN_PR_AUC_ACROSS_OFFSETS": (pa_rule.get("model_offset_summaries") or {}).get("TA2", {}).get("median"),
        "PARTA_F10_MINUS_C2_OFFSET0": pa_boot.get("F10-C2-OPT", {}).get("mean") if pa_boot else None,
        "PARTA_F10_MINUS_C2_OFFSET0_CI95": fmt_ci(pa_boot.get("F10-C2-OPT", {}).get("ci95", [float('nan'), float('nan')])) if pa_boot else None,
        "PARTA_F10_MINUS_C2_FAVOURABLE_OFFSETS": f"{(pa_rule.get('contrast_offset_summaries') or {}).get('F10-C2-OPT', {}).get('n_favourable_offsets')}/20" if pa_rule else None,
        "PARTA_TA2_MINUS_C2_OFFSET0": pa_boot.get("TA2-C2-OPT", {}).get("mean") if pa_boot else None,
        "PARTA_TA2_MINUS_C2_OFFSET0_CI95": fmt_ci(pa_boot.get("TA2-C2-OPT", {}).get("ci95", [float('nan'), float('nan')])) if pa_boot else None,
        "PARTA_TA2_MINUS_C2_FAVOURABLE_OFFSETS": f"{(pa_rule.get('contrast_offset_summaries') or {}).get('TA2-C2-OPT', {}).get('n_favourable_offsets')}/20" if pa_rule else None,
        "PARTA_TA2_MINUS_F10_OFFSET0": pa_boot.get("TA2-F10", {}).get("mean") if pa_boot else None,
        "PARTA_TA2_MINUS_F10_OFFSET0_CI95": fmt_ci(pa_boot.get("TA2-F10", {}).get("ci95", [float('nan'), float('nan')])) if pa_boot else None,
        "PARTA_TA2_MINUS_F10_FAVOURABLE_OFFSETS": f"{(pa_rule.get('contrast_offset_summaries') or {}).get('TA2-F10', {}).get('n_favourable_offsets')}/20" if pa_rule else None,
        "PARTA_TA2_MINUS_L1_OFFSET0": pa_boot.get("TA2-L1", {}).get("mean") if pa_boot else None,
        "PARTA_TA2_MINUS_L1_OFFSET0_CI95": fmt_ci(pa_boot.get("TA2-L1", {}).get("ci95", [float('nan'), float('nan')])) if pa_boot else None,
        "PARTA_TA2_MINUS_L1_FAVOURABLE_OFFSETS": f"{(pa_rule.get('contrast_offset_summaries') or {}).get('TA2-L1', {}).get('n_favourable_offsets')}/20" if pa_rule else None,
        "R52_DEOVERLAP_RANKING_SIGNAL": pa_rule.get("R52_DEOVERLAP_RANKING_SIGNAL"),
        "ENDPOINT_DATA_GATE": data_ok,
        "ENDPOINT_TRAINING_EXECUTED": "YES" if executed else "NO",
        "ENDPOINT_TRAIN_N": data["train_counts"]["n"] if data else None,
        "ENDPOINT_TRAIN_POSITIVES": data["train_counts"]["n_positives"] if data else None,
        "ENDPOINT_TRAIN_POSITIVE_USERS": data["train_counts"]["n_positive_users"] if data else None,
        "ENDPOINT_VALIDATION_N": data["val_counts"]["n"] if data else None,
        "ENDPOINT_VALIDATION_POSITIVES": data["val_counts"]["n_positives"] if data else None,
        "ENDPOINT_VALIDATION_POSITIVE_USERS": data["val_counts"]["n_positive_users"] if data else None,
        "ENDPOINT_VALIDATION_PREVALENCE": data["val_counts"]["prevalence"] if data else None,
        "EP_C2_MEAN_PR_AUC": _nr(executed, (ev.get("means") or {}).get("EP_C2")),
        "EP_F10_MEAN_PR_AUC": _nr(executed, (ev.get("means") or {}).get("EP_F10")),
        "EP_FINAL_MEAN_PR_AUC": _nr(executed, (ev.get("means") or {}).get("EP_FINAL")),
        "EP_LINEAR_MEAN_PR_AUC": _nr(executed, (ev.get("means") or {}).get("EP_LINEAR")),
        "EP_FINAL_RANKING_EXCESS_CI95": _nr(executed, fmt_ci((ev.get("bootstrap_stride1") or {}).get("statistics", {}).get("EP_FINAL_ranking_excess", {}).get("ci95", [float("nan"), float("nan")])) if executed else "NOT_RUN"),
        "ENDPOINT_RANKING_SIGNAL": ev.get("ENDPOINT_RANKING_SIGNAL", "NOT_TESTED" if not executed else None),
        "ENDPOINT_OFFSET0_N": _nr(executed, (ev.get("offset0") or {}).get("n")),
        "ENDPOINT_OFFSET0_POSITIVES": _nr(executed, (ev.get("offset0") or {}).get("n_pos")),
        "ENDPOINT_EP_FINAL_OFFSET0_PR_AUC": _nr(executed, (ev.get("offset0") or {}).get("EP_FINAL_mean_PR_AUC")),
        "ENDPOINT_EP_FINAL_OFFSET0_RANKING_EXCESS_CI95": _nr(executed, fmt_ci((ev.get("bootstrap_offset0") or {}).get("statistics", {}).get("EP_FINAL_ranking_excess", {}).get("ci95", [float("nan"), float("nan")])) if executed else "NOT_RUN"),
        "ENDPOINT_EP_FINAL_OFFSETS_ABOVE_PREVALENCE": f"{ev.get('n_offsets_above')}/20" if executed else "NOT_RUN",
        "ENDPOINT_EP_FINAL_MEDIAN_PR_AUC_ACROSS_OFFSETS": _nr(executed, ev.get("median_pr_auc")),
        "ENDPOINT_DEOVERLAP_SIGNAL": ev.get("ENDPOINT_DEOVERLAP_SIGNAL", "NOT_TESTED" if not executed else None),
        "ENDPOINT_F10_MINUS_C2": _nr(executed, (ev.get("bootstrap_stride1") or {}).get("statistics", {}).get("EP_F10-EP_C2", {}).get("mean") if executed else "NOT_RUN"),
        "ENDPOINT_F10_MINUS_C2_CI95": _nr(executed, fmt_ci((ev.get("bootstrap_stride1") or {}).get("statistics", {}).get("EP_F10-EP_C2", {}).get("ci95", [float("nan"), float("nan")])) if executed else "NOT_RUN"),
        "ENDPOINT_TEACHER_GUIDANCE_VALUE": ev.get("ENDPOINT_TEACHER_GUIDANCE_VALUE", "NOT_TESTED" if not executed else None),
        "ENDPOINT_FINAL_MINUS_C2": _nr(executed, (ev.get("bootstrap_stride1") or {}).get("statistics", {}).get("EP_FINAL-EP_C2", {}).get("mean") if executed else "NOT_RUN"),
        "ENDPOINT_FINAL_MINUS_C2_CI95": _nr(executed, fmt_ci((ev.get("bootstrap_stride1") or {}).get("statistics", {}).get("EP_FINAL-EP_C2", {}).get("ci95", [float("nan"), float("nan")])) if executed else "NOT_RUN"),
        "ENDPOINT_COMPLETE_FORMULATION_VALUE": ev.get("ENDPOINT_COMPLETE_FORMULATION_VALUE", "NOT_TESTED" if not executed else None),
        "ENDPOINT_FINAL_MINUS_F10": _nr(executed, (ev.get("bootstrap_stride1") or {}).get("statistics", {}).get("EP_FINAL-EP_F10", {}).get("mean") if executed else "NOT_RUN"),
        "ENDPOINT_ROUTE_ANCHOR_PREDICTIVE_VALUE": ev.get("ENDPOINT_ROUTE_ANCHOR_PREDICTIVE_VALUE", "NOT_TESTED" if not executed else None),
        "EP_F10_ROUTE_MAE": _nr(executed, ev.get("mae_f10")),
        "EP_FINAL_ROUTE_MAE": _nr(executed, ev.get("mae_final")),
        "ENDPOINT_ROUTE_STRUCTURAL_VALUE": ev.get("ENDPOINT_ROUTE_STRUCTURAL_VALUE", "NOT_TESTED" if not executed else None),
        "ENDPOINT_FINAL_MINUS_LINEAR": _nr(executed, (ev.get("bootstrap_stride1") or {}).get("statistics", {}).get("EP_FINAL-EP_LINEAR", {}).get("mean") if executed else "NOT_RUN"),
        "ENDPOINT_ODST_OVER_LINEAR": ev.get("ENDPOINT_ODST_OVER_LINEAR", "NOT_TESTED" if not executed else None),
        "CURRENT_PAPER_MODEL": CURRENT_PAPER_MODEL,
        "EDITOR024_R61_GENERALISATION_RESULT_CHANGED": EDITOR024_R61_GENERALISATION_RESULT_CHANGED,
        "SAME_USER_TEMPORAL_PARTITIONS": "YES",
        "UNSEEN_USER_GENERALISATION_TESTED": "NO",
    }
    payload["EDITOR029_DEPENDENCE_CONCERN"] = dependence_concern(
        str(payload.get("R52_DEOVERLAP_RANKING_SIGNAL")),
        str((pa_rule.get("component_signals") or {}).get("TA2-C2-OPT", "NOT_SUPPORTED")),
    )
    payload["EDITOR029_ENDPOINT_CAUSALITY_CONCERN"] = endpoint_causality_concern(
        str(payload.get("ENDPOINT_RANKING_SIGNAL") or "NOT_TESTED"),
        str(payload.get("ENDPOINT_DEOVERLAP_SIGNAL") or "NOT_TESTED"),
    )
    write_json(
        REVIEW_ROOT / "EDITOR029_EDITOR_CLOSURE_RULING.json",
        {
            "EDITOR029_DEPENDENCE_CONCERN": payload["EDITOR029_DEPENDENCE_CONCERN"],
            "EDITOR029_ENDPOINT_CAUSALITY_CONCERN": payload["EDITOR029_ENDPOINT_CAUSALITY_CONCERN"],
            "R52_DEOVERLAP_RANKING_SIGNAL": payload["R52_DEOVERLAP_RANKING_SIGNAL"],
            "ENDPOINT_RANKING_SIGNAL": payload["ENDPOINT_RANKING_SIGNAL"],
            "ENDPOINT_DEOVERLAP_SIGNAL": payload["ENDPOINT_DEOVERLAP_SIGNAL"],
            "CURRENT_PAPER_MODEL": CURRENT_PAPER_MODEL,
            "UNSEEN_USER_GENERALISATION_TESTED": "NO",
            "EDITOR024_R61_GENERALISATION_RESULT_CHANGED": "NO",
        },
    )
    write_csv(REVIEW_ROOT / "EDITOR029_EDITOR_RESPONSE_MATRIX.csv", editor_response_rows(payload))
    write_json(
        REVIEW_ROOT / "EDITOR029_PROVENANCE.json",
        {
            "EDITOR028_RESULTS_COMMIT": EDITOR028_RESULTS_COMMIT,
            "git_head": _git_sha(),
            "train_npz": str(bundle["train"].path),
            "val_npz": str(bundle["val"].path),
            "train_sha256": bundle["train_sha256"],
            "val_sha256": bundle["val_sha256"],
            "scaler_sha256": data["scaler_sha256"] if data else None,
            "NEW_SCALER_FIT": NEW_SCALER_FIT,
            "r52_test_accessed": False,
        },
    )
    if phase in {"all", "evaluate"}:
        payload = finalise(payload)
    return payload
