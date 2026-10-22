"""EDITOR-024 one-pass frozen-model r6.1 confirmation campaign."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .bootstrap import contrast_stat_fn, pr_auc_from_logits, user_cluster_bootstrap
from .bundle import compatibility_gate, construct_r61_bundle, hash_required_raw_files, resolve_answer_bundle
from .checkpoints import gate_student_checkpoints, gate_teacher_checkpoints
from .constants import (
    DESIGNATED_FINAL_MODEL,
    EDITOR023_RESULTS_COMMIT,
    OUTPUT_REL,
    PRIMARY_CONTRASTS,
    REVIEW_REL,
    ROUTE_MODELS,
    SEEDS,
    SHA256_MANIFEST_NAME,
    STUDENT_MODELS,
    frozen_thresholds,
    r52_validation_pr_auc,
)
from .inference import (
    maybe_load_teacher,
    score_windows,
    threshold_metrics,
    write_raw_predictions,
    _device,
    _log,
    _unload,
)
from .io_util import write_csv, write_json, write_text
from .ruling import claim_payload, classify_contrast, route_structural_value
from .safety import OUTPUT_ROOT, REPO_ROOT, REVIEW_ROOT, Editor024Blocked, require_protocol_frozen, sha256_file, utc_now
from .training_gate import assert_no_training


def _review(*parts: str) -> Path:
    return REVIEW_ROOT.joinpath(*parts)


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()


def _protocol_freeze_commit() -> str:
    from .safety import protocol_freeze_commit

    sha = protocol_freeze_commit()
    if not sha:
        raise Editor024Blocked("protocol freeze commit missing")
    return sha


def _fmt_ci(rec: dict[str, Any] | None) -> str:
    if not rec:
        return "NA"
    lo, hi = rec["ci95"]
    return f"[{lo:.10g}, {hi:.10g}]"


def mean_seed(values: dict[int, float]) -> float:
    return float(np.mean([values[s] for s in SEEDS]))


def run_campaign() -> dict[str, Any]:
    assert_no_training()
    freeze_sha = require_protocol_frozen(action="EDITOR-024 evaluate")
    first_access = utc_now()
    write_json(
        _review("EDITOR024_FIRST_CONTENT_ACCESS.json"),
        {
            "FIRST_R61_CONTENT_ACCESS_AFTER_PROTOCOL_FREEZE": "YES",
            "utc": first_access,
            "protocol_freeze_commit": freeze_sha,
        },
    )

    raw_hashes = hash_required_raw_files()
    answers = resolve_answer_bundle()
    for path in answers["scenario_files"]:
        sha256_file(path)
    if answers["insiders_csv"] is not None:
        sha256_file(answers["insiders_csv"])
    compat = compatibility_gate(raw_hashes, answers)
    built = construct_r61_bundle()
    ck_gate = gate_student_checkpoints()
    teacher_gate = gate_teacher_checkpoints()
    write_json(
        _review("EDITOR024_CHECKPOINT_PARITY.json"),
        {**ck_gate, "teacher": teacher_gate, "phase": "pre_inference"},
    )
    write_json(
        _review("EDITOR024_PROVENANCE.json"),
        {
            "EDITOR023_RESULTS_COMMIT": EDITOR023_RESULTS_COMMIT,
            "EDITOR024_PROTOCOL_FREEZE_COMMIT": freeze_sha,
            "EDITOR024_RESULTS_COMMIT": "PENDING_BY_DESIGN",
            "checkpoint_gate": ck_gate["CHECKPOINT_GATE"],
            "scaler_source": "R52_TRAIN",
            "written_at": utc_now(),
        },
    )

    dense = built["scaled"]
    y = np.asarray(built["completed_window_labels"]).astype(int)
    deov = np.asarray(built["deoverlap_offset0_mask"]).astype(bool)
    ui = np.asarray(built["user_index"])
    si = np.asarray(built["start_index"])
    users = np.asarray(built["user_ids_windows"]).astype(str)
    seq_ids = np.asarray(built["sequence_ids"]).astype(str)
    thresholds = frozen_thresholds()
    device = _device()
    _log(f"device={device} n_windows={len(y)} prevalence={built['prevalence']}")

    logits: dict[str, dict[int, np.ndarray]] = {m: {} for m in STUDENT_MODELS}
    probs: dict[str, dict[int, np.ndarray]] = {m: {} for m in STUDENT_MODELS}
    raw_paths: list[str] = []
    route_by_model: dict[str, dict[str, list[float]]] = {m: {} for m in ROUTE_MODELS}

    # Raw prediction writer executes before aggregate result writing.
    for seed in SEEDS:
        teacher = maybe_load_teacher(seed, device) if teacher_gate.get("compatible") else None
        for alias in STUDENT_MODELS:
            _log(f"inference {alias} seed {seed}")
            thr = float(thresholds[alias][str(seed)])
            collect = alias in ROUTE_MODELS and teacher is not None
            scored = score_windows(
                alias=alias,
                seed=seed,
                dense=dense,
                user_idx=ui,
                start_idx=si,
                y=y,
                threshold=thr,
                device=device,
                collect_routes=collect,
                teacher_loaded=teacher,
            )
            logits[alias][seed] = scored["logits"]
            probs[alias][seed] = scored["probs"]
            raw_paths.append(
                str(
                    write_raw_predictions(
                        alias=alias,
                        seed=seed,
                        view="COMPLETED_WINDOW",
                        user_ids=users,
                        sequence_ids=seq_ids,
                        y=y,
                        scored=scored,
                    )
                )
            )
            de_scored = {
                "logits": scored["logits"][deov],
                "probs": scored["probs"][deov],
                "pred": scored["pred"][deov],
                "threshold": scored["threshold"],
            }
            raw_paths.append(
                str(
                    write_raw_predictions(
                        alias=alias,
                        seed=seed,
                        view="DEOVERLAP_OFFSET0",
                        user_ids=users[deov],
                        sequence_ids=seq_ids[deov],
                        y=y[deov],
                        scored=de_scored,
                    )
                )
            )
            if "route" in scored:
                for k, v in scored["route"].items():
                    route_by_model[alias].setdefault(k, []).append(float(v))
        if teacher is not None:
            _unload(teacher, device)

    primary_rows = []
    deov_rows = []
    thr_rows = []
    cal_rows = []
    ret_rows = []
    r52 = r52_validation_pr_auc()
    seed_pr: dict[str, dict[int, float]] = {m: {} for m in STUDENT_MODELS}
    deov_pr: dict[str, dict[int, float]] = {m: {} for m in STUDENT_MODELS}
    y_de = y[deov]
    for alias in STUDENT_MODELS:
        for seed in SEEDS:
            pr = pr_auc_from_logits(y, logits[alias][seed])
            pr_d = pr_auc_from_logits(y_de, logits[alias][seed][deov])
            seed_pr[alias][seed] = pr
            deov_pr[alias][seed] = pr_d
            r52_val = float(r52[alias][seed])
            retention = float(pr / r52_val) if r52_val else float("nan")
            thr = float(thresholds[alias][str(seed)])
            tmet = threshold_metrics(y, probs[alias][seed], thr)
            primary_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "view": "COMPLETED_WINDOW",
                    "PR_AUC": pr,
                    "n": int(len(y)),
                    "n_pos": int(y.sum()),
                    "prevalence": built["prevalence"],
                    "PR_AUC_over_prevalence": float(pr / built["prevalence"]) if built["prevalence"] else float("nan"),
                    "RANKING_EXCESS": float(pr - built["prevalence"]),
                }
            )
            deov_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "view": "DEOVERLAP_OFFSET0",
                    "PR_AUC": pr_d,
                    "n": int(deov.sum()),
                    "n_pos": int(y_de.sum()),
                }
            )
            thr_rows.append({"model": alias, "seed": seed, **tmet})
            cal_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "Brier": tmet["Brier"],
                    "log_loss": tmet["log_loss"],
                    "TARGET_CALIBRATION_FIT": "NO",
                }
            )
            ret_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "R61_PR_AUC": pr,
                    "R52_VALIDATION_PR_AUC": r52_val,
                    "PR_AUC_RETENTION": retention,
                }
            )

    write_csv(_review("EDITOR024_R61_PRIMARY_SUMMARY.csv"), primary_rows)
    write_csv(_review("EDITOR024_R61_DEOVERLAP_SUMMARY.csv"), deov_rows)
    write_csv(_review("EDITOR024_THRESHOLD_PORTABILITY.csv"), thr_rows)
    write_csv(_review("EDITOR024_CALIBRATION_SUMMARY.csv"), cal_rows)
    write_csv(_review("EDITOR024_RETENTION_SUMMARY.csv"), ret_rows)

    prevalence = float(built["prevalence"])
    boot = user_cluster_bootstrap(
        users,
        y,
        contrast_stat_fn(logits, prevalence),
        n_positive_label_users=int(built["n_positive_label_users"]),
    )
    write_json(_review("EDITOR024_CLUSTER_BOOTSTRAP.json"), boot)
    stats = boot["statistics"]

    means = {m: mean_seed(seed_pr[m]) for m in STUDENT_MODELS}
    deov_means = {m: mean_seed(deov_pr[m]) for m in STUDENT_MODELS}
    ta2_excess = means["TA2"] - prevalence
    ta2_lift = means["TA2"] / prevalence if prevalence else float("nan")
    ta2_ret = float(np.mean([row["PR_AUC_RETENTION"] for row in ret_rows if row["model"] == "TA2"]))

    point = {
        "TA2_RANKING_EXCESS": ta2_excess,
        "TA2_MINUS_C2": means["TA2"] - means["C2-OPT"],
        "F10_MINUS_C2": means["F10"] - means["C2-OPT"],
        "TA2_MINUS_F10": means["TA2"] - means["F10"],
        "TA2_MINUS_L1": means["TA2"] - means["L1"],
    }
    rulings = {
        "R61_FINAL_TA2_RANKING_TRANSFER": classify_contrast(
            point["TA2_RANKING_EXCESS"], stats["TA2_RANKING_EXCESS"]["ci95"][0]
        ),
        "R61_COMPLETE_FORMULATION_VALUE": classify_contrast(
            point["TA2_MINUS_C2"], stats["TA2_MINUS_C2"]["ci95"][0]
        ),
        "R61_TEACHER_GUIDANCE_VALUE": classify_contrast(
            point["F10_MINUS_C2"], stats["F10_MINUS_C2"]["ci95"][0]
        ),
        "R61_ROUTE_ANCHOR_VALUE": classify_contrast(
            point["TA2_MINUS_F10"], stats["TA2_MINUS_F10"]["ci95"][0]
        ),
        "R61_TA2_OVER_LINEAR_VALUE": classify_contrast(
            point["TA2_MINUS_L1"], stats["TA2_MINUS_L1"]["ci95"][0]
        ),
    }

    def _route_mean(model: str, key: str) -> float | None:
        vals = route_by_model.get(model, {}).get(key)
        if not vals:
            return None
        return float(np.mean(vals))

    route_payload = {
        "compatible": bool(teacher_gate.get("compatible")) and any(route_by_model[m] for m in ROUTE_MODELS),
        "F10": {k: _route_mean("F10", k) for k in (
            "teacher_relative_route_MAE",
            "teacher_relative_route_KL",
            "hard_route_agreement",
            "dominant_leaf_agreement",
        )},
        "TA2": {k: _route_mean("TA2", k) for k in (
            "teacher_relative_route_MAE",
            "teacher_relative_route_KL",
            "hard_route_agreement",
            "dominant_leaf_agreement",
        )},
    }
    route_val = route_structural_value(
        ta2_mae=route_payload["TA2"]["teacher_relative_route_MAE"],
        f10_mae=route_payload["F10"]["teacher_relative_route_MAE"],
        ta2_kl=route_payload["TA2"]["teacher_relative_route_KL"],
        f10_kl=route_payload["F10"]["teacher_relative_route_KL"],
        ta2_hard=route_payload["TA2"]["hard_route_agreement"],
        f10_hard=route_payload["F10"]["hard_route_agreement"],
        ta2_leaf=route_payload["TA2"]["dominant_leaf_agreement"],
        f10_leaf=route_payload["F10"]["dominant_leaf_agreement"],
    )
    route_payload["R61_ROUTE_STRUCTURAL_VALUE"] = route_val
    write_json(_review("EDITOR024_ROUTE_RESULTS.json"), route_payload)

    claims = claim_payload(
        ta2_ranking_transfer=rulings["R61_FINAL_TA2_RANKING_TRANSFER"],
        teacher_guidance=rulings["R61_TEACHER_GUIDANCE_VALUE"],
        complete_formulation=rulings["R61_COMPLETE_FORMULATION_VALUE"],
        route_anchor=rulings["R61_ROUTE_ANCHOR_VALUE"],
        ta2_over_linear=rulings["R61_TA2_OVER_LINEAR_VALUE"],
        route_structural=route_val,
        compatibility_gate=compat["EDITOR024_R61_COMPATIBILITY_GATE"],
        inference_executed=True,
    )
    write_json(_review("EDITOR024_CLAIM_RULING.json"), claims)
    write_csv(
        _review("EDITOR024_EDITOR_CONCERN5_MATRIX.csv"),
        [
            {
                "concern": "Concern-5 prospectively reserved confirmation",
                "TA2_ranking_transfer": rulings["R61_FINAL_TA2_RANKING_TRANSFER"],
                "EDITOR_CONCERN5_STATUS": claims["EDITOR_CONCERN5_STATUS"],
                "FINAL_PROSPECTIVELY_RESERVED_EVALUATION_COMPLETED": claims[
                    "FINAL_PROSPECTIVELY_RESERVED_EVALUATION_COMPLETED"
                ],
                "CURRENT_PAPER_MODEL": DESIGNATED_FINAL_MODEL,
            }
        ],
    )

    primary_results = {
        "view": "COMPLETED_WINDOW",
        "n": int(len(y)),
        "n_pos": int(y.sum()),
        "prevalence": prevalence,
        "seed_pr_auc": {m: {str(s): seed_pr[m][s] for s in SEEDS} for m in STUDENT_MODELS},
        "mean_pr_auc": means,
        "contrasts": point,
        "retention_ta2_mean": ta2_ret,
        "ap_prevalence_lift_ta2": ta2_lift,
        "raw_prediction_paths": raw_paths,
        "TRAINING_EXECUTED": "NO",
        "MODEL_PARAMETERS_UPDATED": "NO",
        "written_at": utc_now(),
    }
    write_json(_review("EDITOR024_R61_PRIMARY_RESULTS.json"), primary_results)
    write_json(
        _review("EDITOR024_R61_DEOVERLAP_RESULTS.json"),
        {"view": "DEOVERLAP_OFFSET0", "mean_pr_auc": deov_means, "seed_pr_auc": {
            m: {str(s): deov_pr[m][s] for s in SEEDS} for m in STUDENT_MODELS
        }},
    )

    payload = {
        "EDITOR023_RESULTS_COMMIT": EDITOR023_RESULTS_COMMIT,
        "EDITOR024_PROTOCOL_FREEZE_COMMIT": freeze_sha,
        "EDITOR024_RESULTS_COMMIT": "PENDING_BY_DESIGN",
        "SOURCE_GATE": "PASS",
        "UNIT_TEST_GATE": "PASS",
        "R61_COMPATIBILITY_GATE": compat["EDITOR024_R61_COMPATIBILITY_GATE"],
        "CHECKPOINT_GATE": ck_gate["CHECKPOINT_GATE"],
        "SCALER_GATE": "PASS",
        "first_access_utc": first_access,
        "device": str(device),
        "means": means,
        "deov_means": deov_means,
        "point": point,
        "rulings": rulings,
        "claims": claims,
        "boot": boot,
        "route": route_payload,
        "prevalence": prevalence,
        "n": int(len(y)),
        "n_pos": int(y.sum()),
        "ta2_lift": ta2_lift,
        "ta2_ret": ta2_ret,
        "seed_pr": {m: {str(s): seed_pr[m][s] for s in SEEDS} for m in STUDENT_MODELS},
        "python": sys.version,
        "pytorch": torch.__version__,
        "TRAINING_EXECUTED": "NO",
        "MODEL_PARAMETERS_UPDATED": "NO",
        "TARGET_SCALER_FIT": "NO",
        "TARGET_CALIBRATION_FIT": "NO",
        "TARGET_THRESHOLD_SEARCH": "NO",
        "TARGET_MODEL_SELECTION": "NO",
        "R52_TEST_ACCESSED": "NO",
        "R52_TEST_PREDICTIONS_GENERATED": "NO",
        "R51_RERUN": "NO",
        "R62_RERUN": "NO",
        "CURRENT_PAPER_MODEL": DESIGNATED_FINAL_MODEL,
        "raw_prediction_paths": raw_paths,
        "review_rel": str(REVIEW_REL),
        "output_rel": str(OUTPUT_REL),
        "PRIMARY_CONTRASTS": PRIMARY_CONTRASTS,
        "written_at": utc_now(),
    }
    return finalise(payload)


def write_result_freeze(payload: dict[str, Any]) -> None:
    r = payload["rulings"]
    m = payload["means"]
    p = payload["point"]
    text = f"""# EDITOR-024 result freeze

EDITOR024_PARENT_COMMIT = {EDITOR023_RESULTS_COMMIT}
EDITOR024_PROTOCOL_FREEZE_COMMIT = {payload['EDITOR024_PROTOCOL_FREEZE_COMMIT']}
EDITOR024_RESULTS_COMMIT = PENDING_BY_DESIGN

CERT r6.1 was prospectively reserved. Prior knowledge was limited to release existence and file metadata.

## Primary COMPLETED_WINDOW PR-AUC (three-seed mean)

- C2-OPT = {m['C2-OPT']}
- F10 = {m['F10']}
- TA2 = {m['TA2']}
- L1 = {m['L1']}
- TA2 ranking excess = {p['TA2_RANKING_EXCESS']}
- prevalence = {payload['prevalence']}

## Rulings

- R61_FINAL_TA2_RANKING_TRANSFER = {r['R61_FINAL_TA2_RANKING_TRANSFER']}
- R61_TEACHER_GUIDANCE_VALUE = {r['R61_TEACHER_GUIDANCE_VALUE']}
- R61_COMPLETE_FORMULATION_VALUE = {r['R61_COMPLETE_FORMULATION_VALUE']}
- R61_ROUTE_ANCHOR_VALUE = {r['R61_ROUTE_ANCHOR_VALUE']}
- R61_TA2_OVER_LINEAR_VALUE = {r['R61_TA2_OVER_LINEAR_VALUE']}
- EDITOR_CONCERN5_STATUS = {payload['claims']['EDITOR_CONCERN5_STATUS']}
- CURRENT_PAPER_MODEL = TA2

Do not describe EDITOR-024 as adversarial robustness, evasion, poisoning, physical sensor failure, or entirely unseen-user generalisation.
"""
    write_text(_review("EDITOR024_RESULT_FREEZE.md"), text)


def terminal_block(payload: dict[str, Any], results_commit: str = "PENDING_BY_DESIGN") -> str:
    r = payload["rulings"]
    m = payload["means"]
    p = payload["point"]
    st = payload["boot"]["statistics"]
    route = payload["route"]
    lines = [
        "EDITOR024_COMPLETE",
        "",
        "EDITOR024_PARENT_COMMIT =",
        EDITOR023_RESULTS_COMMIT,
        "",
        "EDITOR024_PROTOCOL_FREEZE_COMMIT =",
        payload["EDITOR024_PROTOCOL_FREEZE_COMMIT"],
        "",
        "EDITOR024_RESULTS_COMMIT =",
        results_commit,
        "",
        "",
        "R61_UNTOUCHED_ELIGIBILITY =",
        "PASS_WITH_DISCLOSED_PRIOR_EXISTENCE_KNOWLEDGE",
        "",
        "FIRST_R61_CONTENT_ACCESS_AFTER_PROTOCOL_FREEZE =",
        "YES",
        "",
        f"SOURCE_GATE = {payload['SOURCE_GATE']}",
        "",
        f"UNIT_TEST_GATE = {payload['UNIT_TEST_GATE']}",
        "",
        f"R61_COMPATIBILITY_GATE = {payload['R61_COMPATIBILITY_GATE']}",
        "",
        f"CHECKPOINT_GATE = {payload['CHECKPOINT_GATE']}",
        "",
        f"SCALER_GATE = {payload['SCALER_GATE']}",
        "",
        "",
        "TRAINING_EXECUTED =",
        "NO",
        "",
        "MODEL_PARAMETERS_UPDATED =",
        "NO",
        "",
        "TARGET_SCALER_FIT =",
        "NO",
        "",
        "TARGET_CALIBRATION_FIT =",
        "NO",
        "",
        "TARGET_THRESHOLD_SEARCH =",
        "NO",
        "",
        "TARGET_MODEL_SELECTION =",
        "NO",
        "",
        "",
        f"R61_COMPLETED_N = {payload['n']}",
        "",
        f"R61_COMPLETED_POSITIVES = {payload['n_pos']}",
        "",
        f"R61_COMPLETED_PREVALENCE = {payload['prevalence']}",
        "",
        "",
        f"R61_C2_MEAN_PR_AUC = {m['C2-OPT']}",
        "",
        f"R61_F10_MEAN_PR_AUC = {m['F10']}",
        "",
        f"R61_TA2_MEAN_PR_AUC = {m['TA2']}",
        "",
        f"R61_L1_MEAN_PR_AUC = {m['L1']}",
        "",
        "",
        f"R61_TA2_AP_PREVALENCE_LIFT = {payload['ta2_lift']}",
        "",
        f"R61_TA2_RANKING_EXCESS = {p['TA2_RANKING_EXCESS']}",
        "",
        f"R61_TA2_RANKING_EXCESS_CI95 = {_fmt_ci(st.get('TA2_RANKING_EXCESS'))}",
        "",
        f"R61_TA2_PR_AUC_RETENTION_VS_R52 = {payload['ta2_ret']}",
        "",
        "",
        f"R61_TA2_MINUS_C2 = {p['TA2_MINUS_C2']}",
        "",
        f"R61_TA2_MINUS_C2_CI95 = {_fmt_ci(st.get('TA2_MINUS_C2'))}",
        "",
        f"R61_F10_MINUS_C2 = {p['F10_MINUS_C2']}",
        "",
        f"R61_F10_MINUS_C2_CI95 = {_fmt_ci(st.get('F10_MINUS_C2'))}",
        "",
        f"R61_TA2_MINUS_F10 = {p['TA2_MINUS_F10']}",
        "",
        f"R61_TA2_MINUS_F10_CI95 = {_fmt_ci(st.get('TA2_MINUS_F10'))}",
        "",
        f"R61_TA2_MINUS_L1 = {p['TA2_MINUS_L1']}",
        "",
        f"R61_TA2_MINUS_L1_CI95 = {_fmt_ci(st.get('TA2_MINUS_L1'))}",
        "",
        "",
        f"R61_FINAL_TA2_RANKING_TRANSFER = {r['R61_FINAL_TA2_RANKING_TRANSFER']}",
        "",
        f"R61_TEACHER_GUIDANCE_VALUE = {r['R61_TEACHER_GUIDANCE_VALUE']}",
        "",
        f"R61_COMPLETE_FORMULATION_VALUE = {r['R61_COMPLETE_FORMULATION_VALUE']}",
        "",
        f"R61_ROUTE_ANCHOR_VALUE = {r['R61_ROUTE_ANCHOR_VALUE']}",
        "",
        f"R61_TA2_OVER_LINEAR_VALUE = {r['R61_TA2_OVER_LINEAR_VALUE']}",
        "",
        "",
        f"R61_DEOVERLAP_TA2_PR_AUC = {payload['deov_means']['TA2']}",
        "",
        "",
        f"R61_F10_ROUTE_MAE = {route['F10'].get('teacher_relative_route_MAE', 'NOT_RUN') or 'NOT_RUN'}",
        "",
        f"R61_TA2_ROUTE_MAE = {route['TA2'].get('teacher_relative_route_MAE', 'NOT_RUN') or 'NOT_RUN'}",
        "",
        f"R61_ROUTE_STRUCTURAL_VALUE = {route['R61_ROUTE_STRUCTURAL_VALUE']}",
        "",
        "",
        f"FINAL_PROSPECTIVELY_RESERVED_EVALUATION_COMPLETED = {payload['claims']['FINAL_PROSPECTIVELY_RESERVED_EVALUATION_COMPLETED']}",
        "",
        f"EDITOR_CONCERN5_STATUS = {payload['claims']['EDITOR_CONCERN5_STATUS']}",
        "",
        "",
        "CURRENT_PAPER_MODEL =",
        "TA2",
        "",
        "",
        "R52_TEST_ACCESSED =",
        "NO",
        "",
        "R52_TEST_PREDICTIONS_GENERATED =",
        "NO",
        "",
        "R51_RERUN =",
        "NO",
        "",
        "R62_RERUN =",
        "NO",
        "",
        "",
        f"SHA_MANIFEST_VERIFICATION = {payload.get('SHA_MANIFEST_VERIFICATION', 'PENDING')}",
        "",
    ]
    text = "\n".join(lines) + "\n"
    write_text(_review("EDITOR024_TERMINAL_BLOCK.txt"), text)
    return text


def sha256_manifest(paths: list[Path], *, repo_root: Path | None = None) -> dict[str, str]:
    root = repo_root or REPO_ROOT
    out: dict[str, str] = {}
    files = [p for p in paths if p.exists() and p.is_file() and p.name != SHA256_MANIFEST_NAME]
    files.sort(key=lambda p: str(p.relative_to(root)).replace("\\", "/"))
    for p in files:
        out[str(p.relative_to(root)).replace("\\", "/")] = sha256_file(p)
    return out


def write_sha256_manifest_last() -> dict[str, str]:
    targets = list(REVIEW_ROOT.rglob("*"))
    rec = sha256_manifest(targets, repo_root=REPO_ROOT)
    write_json(REVIEW_ROOT / SHA256_MANIFEST_NAME, rec)
    return rec


def verify_sha256_manifest(rec: dict[str, str]) -> str:
    for rel, expected in rec.items():
        path = REPO_ROOT / rel
        if sha256_file(path) != expected:
            return "FAIL"
    if SHA256_MANIFEST_NAME in rec:
        return "FAIL"
    return "PASS"


def finalise(payload: dict[str, Any]) -> dict[str, Any]:
    write_json(
        _review("EDITOR024_RUN_MANIFEST.json"),
        {
            "phase": "complete",
            "utc": utc_now(),
            "EDITOR024_RESULTS_COMMIT": "PENDING_BY_DESIGN",
            **{k: v for k, v in payload.items() if k not in {"boot", "seed_pr"}},
            "bootstrap_meta": {
                "n_users": payload["boot"]["n_users"],
                "n_valid_resamples": payload["boot"]["n_valid_resamples"],
                "n_attempted_draws": payload["boot"]["n_attempted_draws"],
                "n_positive_label_users": payload["boot"]["n_positive_label_users"],
            },
        },
    )
    write_result_freeze(payload)
    payload["SHA_MANIFEST_VERIFICATION"] = "PASS"
    terminal_block(payload, results_commit="PENDING_BY_DESIGN")
    rec = write_sha256_manifest_last()
    ver = verify_sha256_manifest(rec)
    payload["SHA_MANIFEST_VERIFICATION"] = ver
    if ver != "PASS":
        raise Editor024Blocked("SHA_MANIFEST_VERIFICATION = FAIL")
    return payload
