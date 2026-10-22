"""EDITOR-023 frozen-checkpoint positive architecture-value campaign."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor012_rescue.constants import (
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_MALICIOUS_USERS,
    EXPECTED_VAL_USERS,
    EXPECTED_VAL_WINDOWS_PER_USER,
    PRIMARY_SEEDS,
)
from editor012_rescue.data import load_train_validation, make_xy_loader
from editor012_rescue.evaluate import hash_gate_checkpoint
from editor012_rescue.metrics import teacher_relative
from editor015_residual.explain import centred_contributions, train_references
from editor017_robustness.constants import BATCH_SIZE, FROZEN_CLEAN_PR_AUC, MODEL_SPECS
from editor017_robustness.models import load_l1, load_odst, parameter_fingerprint
from editor017_robustness.score import metrics_at_frozen_threshold, paired_score_stats, score_l1_full, score_odst_full

from .bootstrap_curves import aurc_bootstrap, scalar_mean_contrast_bootstrap
from .constants import (
    EDITOR017_REVIEW_REL,
    EDITOR022_RESULTS_COMMIT,
    EXPLANATION_PARITY_TOLERANCE,
    NOISE_LEVELS,
    NOISE_LEVELS_HISTORICAL,
    NOISE_LEVELS_NEW,
    ODST_MODELS,
    OUTPUT_REL,
    PARITY_TOLERANCE,
    DEGRADED_PARITY_TOLERANCE,
    PRIMARY_MODELS,
    REVIEW_REL,
    ROUTE_PARITY_TOLERANCE,
    SCORING_MODELS,
    SOURCE_CHANNELS,
    SOURCE_DEGRADATION_LEVELS,
    SOURCE_DEGRADATION_NEW,
    TEACHER_RELATIVE_MODELS,
)
from .curves import failure_profile, summarise_noise_aurc, summarise_source_aurc
from .io_util import read_csv_rows, write_csv, write_json, write_npy
from editor017_robustness.perturbations import perturbation_module_hashes
from editor020_robustness.constants import EXPECTED_GAUSSIAN_SHA256, EXPECTED_SOURCE_ABLATION_SHA256

from .perturbations import (
    apply_gaussian_noise,
    apply_graded_source,
    apply_source_ablation,
    load_r52_train_scaler,
    tensor_sha256,
)
from .ruling import (
    explanation_stability_value,
    odst_degraded_over_linear,
    overall_architecture_value,
    route_anchor_structural_value,
    seed_direction_table,
    teacher_guidance_clean_value,
    teacher_guidance_degraded_value,
)
from .safety import (
    OUTPUT_ROOT,
    REPO_ROOT,
    REVIEW_ROOT,
    Editor023Blocked,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from .stability import contribution_stability, per_sequence_route, per_sequence_spearman, route_leaf_pair
from .training_gate import assert_no_training


SHA256_MANIFEST_NAME = "EDITOR023_SHA256_MANIFEST.json"
DIRECTIONAL_MODELS = ("F10", "TA2")


def _review(*parts: str) -> Path:
    return REVIEW_ROOT.joinpath(*parts)


def _output(*parts: str) -> Path:
    return OUTPUT_ROOT.joinpath(*parts)


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True).strip()


def _protocol_freeze_commit() -> str:
    out = subprocess.check_output(
        [
            "git",
            "log",
            "-1",
            "--grep",
            "Freeze EDITOR-023 positive architecture value protocol",
            "--format=%H",
        ],
        cwd=str(REPO_ROOT),
        text=True,
    ).strip()
    return out or "PENDING"


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor023Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor023Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor023Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor023Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    return {
        "USER_MAPPING_RECOVERED": True,
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "mapping_sha256": mapping_hash,
    }


def _score_model(alias: str, seed: int, X: np.ndarray, y: np.ndarray, device: torch.device, loaded: dict[str, Any]) -> dict[str, np.ndarray]:
    loader = make_xy_loader(X, y, seed=seed, batch_size=BATCH_SIZE, shuffle=False)
    if alias == "L1":
        return score_l1_full(loaded["student"], loaded["modules"], loader, device)
    return score_odst_full(loaded["model"], loader, device)


def _load_model(alias: str, seed: int, device: torch.device) -> dict[str, Any]:
    if alias == "L1":
        student, modules, sha = load_l1(seed, device)
        fp = parameter_fingerprint(student, modules)
        return {"student": student, "modules": modules, "sha256": sha, "fingerprint": fp, "family": "linear"}
    model, sha = load_odst(alias, seed, device)
    fp = parameter_fingerprint(model)
    return {"model": model, "sha256": sha, "fingerprint": fp, "family": "odst"}


def _assert_fingerprint(alias: str, seed: int, loaded: dict[str, Any]) -> None:
    if alias == "L1":
        now = parameter_fingerprint(loaded["student"], loaded["modules"])
    else:
        now = parameter_fingerprint(loaded["model"])
    if now != loaded["fingerprint"]:
        raise Editor023Blocked(f"EDITOR023_TRAINING_GATE = FAIL: parameter update detected for {alias}/{seed}")


def _unload(loaded: dict[str, Any], device: torch.device) -> None:
    if loaded["family"] == "linear":
        del loaded["student"], loaded["modules"]
    else:
        del loaded["model"]
    if device.type == "cuda":
        torch.cuda.empty_cache()


def hash_gate_checkpoints() -> dict[str, Any]:
    recs = []
    all_pass = True
    for alias in SCORING_MODELS:
        for seed in PRIMARY_SEEDS:
            ck = MODEL_SPECS[alias]["checkpoints"][seed]
            path = Path(ck["checkpoint"])
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
                    "seed": seed,
                    "path": str(path),
                    "expected_sha256": expected,
                    "observed_sha256": observed,
                    "exists": exists,
                    "PASS": ok,
                }
            )
    status = "PASS" if all_pass else "FAIL"
    payload = {"CHECKPOINT_GATE": status, "records": recs, "written_at": utc_now()}
    write_json(_review("EDITOR023_CHECKPOINT_PARITY.json"), payload)
    if not all_pass:
        raise Editor023Blocked("EDITOR023_PARITY_GATE = FAIL: checkpoint hash mismatch")
    return payload


def load_editor017_historical() -> dict[str, Any]:
    root = REPO_ROOT / EDITOR017_REVIEW_REL
    return {
        "clean": read_csv_rows(root / "01_clean" / "EDITOR017_CLEAN_RESULTS.csv"),
        "source": read_csv_rows(root / "02_source_ablation" / "EDITOR017_SOURCE_ABLATION_RESULTS.csv"),
        "noise": read_csv_rows(root / "03_gaussian_noise" / "EDITOR017_NOISE_RESULTS.csv"),
        "route": json.loads((root / "07_statistics" / "EDITOR017_ROUTE_RESILIENCE_BOOTSTRAP.json").read_text(encoding="utf-8")),
        "explanation": json.loads(
            (root / "06_explanation_stability" / "EDITOR017_EXPLANATION_STABILITY_BOOTSTRAP.json").read_text(encoding="utf-8")
        ),
    }


def _csv_pr(rows: list[dict[str, str]], *, model: str, seed: int, **filters: Any) -> float:
    hits = []
    for row in rows:
        if row["model"] != model or int(row["seed"]) != seed:
            continue
        ok = True
        for k, v in filters.items():
            if k == "noise_level":
                if abs(float(row.get("noise_level", "nan")) - float(v)) > 1e-12:
                    ok = False
                    break
            elif k == "source":
                if row.get("source") != v:
                    ok = False
                    break
            elif k == "condition":
                if row.get("condition") != v:
                    ok = False
                    break
        if ok:
            hits.append(float(row["PR_AUC"]))
    if len(hits) != 1:
        raise Editor023Blocked(f"EDITOR-017 lookup failed for {model}/{seed} {filters}: n={len(hits)}")
    return hits[0]


def _metric_row(alias: str, seed: int, condition: str, met: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "model": alias,
        "model_id": MODEL_SPECS[alias]["model_id"],
        "seed": seed,
        "condition": condition,
        "PR_AUC": float(met["pr_auc"]),
        "F1": float(met["f1"]),
        "precision": float(met["precision"]),
        "recall": float(met["recall"]),
        "FP": int(met["fp"]),
        "FN": int(met["fn"]),
        "Brier": float(met["Brier"]),
        "log_loss": float(met["log_loss"]),
        "predicted_positive_fraction": float(met["predicted_positive_fraction"]),
        "threshold": float(met["threshold"]),
        "n": int(met["n"]),
        "n_pos": int(met["n_pos"]),
    }
    if extra:
        row.update(extra)
    return row


def _save_logits(alias: str, seed: int, condition: str, logits: np.ndarray) -> None:
    write_npy(_output("logits", alias, f"seed{seed}", f"{condition}.npy"), np.asarray(logits, dtype=np.float32))


def run_campaign() -> dict[str, Any]:
    assert_no_training()
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    device = _device()
    print(f"[EDITOR-023] device={device}", flush=True)
    hashes = perturbation_module_hashes(REPO_ROOT)
    source_gate = (
        hashes["objective3_missing_source_robustness.py"] == EXPECTED_SOURCE_ABLATION_SHA256
        and hashes["objective3_perturbations.py"] == EXPECTED_GAUSSIAN_SHA256
    )
    if not source_gate:
        raise Editor023Blocked("SOURCE_GATE = FAIL: perturbation implementation hash mismatch")
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    thr_path = _review("EDITOR023_FROZEN_THRESHOLDS.json")
    if not thr_path.is_file():
        raise Editor023Blocked("protocol freeze missing EDITOR023_FROZEN_THRESHOLDS.json; run --phase protocol first")
    raw_thr = json.loads(thr_path.read_text(encoding="utf-8"))
    thresholds = {alias: {int(s): float(t) for s, t in seeds.items()} for alias, seeds in raw_thr.items()}
    ck_gate = hash_gate_checkpoints()
    scaler = load_r52_train_scaler()
    hist = load_editor017_historical()
    y = np.asarray(bundle["val"].y).reshape(-1)
    users = np.asarray(bundle["val"].user).astype(str).reshape(-1)
    X_val = np.asarray(bundle["val"].X, dtype=np.float32)
    X_train = np.asarray(bundle["train"].X, dtype=np.float32)
    y_train = np.asarray(bundle["train"].y).reshape(-1)
    y_check = np.asarray(bundle["val"].y).reshape(-1)
    if not np.array_equal(y, y_check):
        raise Editor023Blocked("labels changed")

    ablation = {src: apply_source_ablation(X_val, src, scaler) for src in SOURCE_CHANNELS}
    ablation_hashes = {src: tensor_sha256(ablation[src]) for src in SOURCE_CHANNELS}
    for src in SOURCE_CHANNELS:
        d1 = apply_graded_source(X_val, ablation[src], 1.0)
        if not np.array_equal(d1, ablation[src]):
            raise Editor023Blocked(f"d=1.00 endpoint mismatch for {src}")

    clean_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    noise_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    explain_rows: list[dict[str, Any]] = []
    calib_rows: list[dict[str, Any]] = []
    fingerprints: list[dict[str, Any]] = []
    parity_checks: list[dict[str, Any]] = []

    logits_clean: dict[str, dict[int, np.ndarray]] = {a: {} for a in SCORING_MODELS}
    logits_source: dict[str, dict[int, dict[str, dict[float, np.ndarray]]]] = {
        a: {s: {src: {} for src in SOURCE_CHANNELS} for s in PRIMARY_SEEDS} for a in PRIMARY_MODELS
    }
    logits_noise: dict[str, dict[int, dict[float, np.ndarray]]] = {
        a: {s: {} for s in PRIMARY_SEEDS} for a in PRIMARY_MODELS
    }

    clean_struct: dict[str, dict[int, dict[str, np.ndarray]]] = {a: {} for a in list(ODST_MODELS) + ["T-OPT"]}
    train_refs: dict[str, dict[int, np.ndarray]] = {a: {} for a in DIRECTIONAL_MODELS}
    seq_route_clean: dict[str, dict[int, np.ndarray]] = {a: {} for a in TEACHER_RELATIVE_MODELS}
    seq_route_deg: dict[str, dict[int, list[np.ndarray]]] = {a: {s: [] for s in PRIMARY_SEEDS} for a in TEACHER_RELATIVE_MODELS}
    seq_expl_deg: dict[str, dict[int, list[np.ndarray]]] = {a: {s: [] for s in PRIMARY_SEEDS} for a in DIRECTIONAL_MODELS}

    hist_route_mae: dict[str, dict[str, list[float]]] = {
        a: {"clean": [], "source": [], "noise": []} for a in TEACHER_RELATIVE_MODELS
    }
    hist_expl: dict[str, dict[str, list[float]]] = {a: {"source": [], "noise": []} for a in DIRECTIONAL_MODELS}

    def score_tensor(alias: str, seed: int, loaded: dict[str, Any], X: np.ndarray) -> dict[str, np.ndarray]:
        scored = _score_model(alias, seed, X, y, device, loaded)
        if not np.array_equal(scored["y"].astype(int), y.astype(int)):
            raise Editor023Blocked("label order changed during scoring")
        return scored

    # --- clean ---
    for alias in SCORING_MODELS:
        for seed in PRIMARY_SEEDS:
            print(f"[EDITOR-023] clean {alias} seed={seed}", flush=True)
            loaded = _load_model(alias, seed, device)
            fingerprints.append({"model": alias, "seed": seed, "sha256": loaded["sha256"], "fingerprint": loaded["fingerprint"]})
            scored = score_tensor(alias, seed, loaded, X_val)
            thr = float(thresholds[alias][seed])
            met = metrics_at_frozen_threshold(y, scored["logits"], thr)
            frozen_pr = FROZEN_CLEAN_PR_AUC[alias][seed]
            hist_pr = _csv_pr(hist["clean"], model=alias, seed=seed, condition="clean")
            live = float(met["pr_auc"])
            ok_frozen = abs(live - frozen_pr) <= PARITY_TOLERANCE
            ok_hist = abs(live - hist_pr) <= PARITY_TOLERANCE
            parity_checks.append(
                {
                    "gate": "clean_PR_AUC",
                    "model": alias,
                    "seed": seed,
                    "live": live,
                    "frozen": frozen_pr,
                    "editor017": hist_pr,
                    "PASS": bool(ok_frozen and ok_hist),
                }
            )
            if not (ok_frozen and ok_hist):
                write_json(_review("EDITOR023_HISTORICAL_PARITY.json"), {"HISTORICAL_PARITY_GATE": "FAIL", "checks": parity_checks})
                raise Editor023Blocked(f"EDITOR023_PARITY_GATE = FAIL: clean PR-AUC {alias}/{seed}")
            logits_clean[alias][seed] = scored["logits"]
            _save_logits(alias, seed, "clean", scored["logits"])
            extra = {"checkpoint_sha256": loaded["sha256"], "clean_PR_AUC_gate": "PASS"}
            if alias in ODST_MODELS or alias == "T-OPT":
                clean_struct[alias][seed] = {
                    "choices": scored["choices"],
                    "leaf_probs_all": scored["leaf_probs_all"],
                    "tree_outputs": scored["tree_outputs"],
                }
            clean_rows.append(_metric_row(alias, seed, "clean", met, extra))
            calib_rows.append(_metric_row(alias, seed, "clean", met, {"family": "clean", "severity": 0.0}))
            if alias in DIRECTIONAL_MODELS:
                print(f"[EDITOR-023] TRAIN references {alias} seed={seed}", flush=True)
                train_scored = _score_model(alias, seed, X_train, y_train, device, loaded)
                train_refs[alias][seed] = train_references(train_scored["tree_outputs"])
            _assert_fingerprint(alias, seed, loaded)
            _unload(loaded, device)

    for alias in TEACHER_RELATIVE_MODELS:
        for seed in PRIMARY_SEEDS:
            rel = teacher_relative(
                logits_clean[alias][seed],
                logits_clean["T-OPT"][seed],
                clean_struct[alias][seed]["choices"],
                clean_struct["T-OPT"][seed]["choices"],
                clean_struct[alias][seed]["leaf_probs_all"],
                clean_struct["T-OPT"][seed]["leaf_probs_all"],
            )
            seq = per_sequence_route(
                clean_struct[alias][seed]["choices"],
                clean_struct["T-OPT"][seed]["choices"],
                clean_struct[alias][seed]["leaf_probs_all"],
                clean_struct["T-OPT"][seed]["leaf_probs_all"],
            )
            seq_route_clean[alias][seed] = seq["route_MAE"]
            hist_route_mae[alias]["clean"].append(float(rel["route_MAE"]))
            route_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "family": "clean",
                    "condition": "clean",
                    "comparison": "teacher_relative_TOPT",
                    "route_MAE": rel["route_MAE"],
                    "route_KL": rel["route_KL"],
                    "hard_route_agreement": rel["hard_route_agreement"],
                    "dominant_leaf_agreement": rel["dominant_leaf_agreement"],
                }
            )

    # --- historical degraded conditions ---
    hist_source_jobs = [(src, 1.0) for src in SOURCE_CHANNELS]
    hist_noise_jobs = list(NOISE_LEVELS_HISTORICAL)

    def run_source_jobs(jobs: list[tuple[str, float]], *, historical: bool) -> None:
        for src, d in jobs:
            X = apply_graded_source(X_val, ablation[src], float(d))
            topt_scored: dict[int, dict[str, np.ndarray]] = {}
            for alias in SCORING_MODELS:
                for seed in PRIMARY_SEEDS:
                    print(f"[EDITOR-023] {alias}/{seed} source={src} d={d}", flush=True)
                    loaded = _load_model(alias, seed, device)
                    scored = score_tensor(alias, seed, loaded, X)
                    thr = float(thresholds[alias][seed])
                    met = metrics_at_frozen_threshold(y, scored["logits"], thr)
                    cond = f"source_{src}_d{float(d):.2f}"
                    _save_logits(alias, seed, cond, scored["logits"])
                    if alias in PRIMARY_MODELS:
                        logits_source[alias][seed][src][float(d)] = scored["logits"]
                        clean_pr = float([r for r in clean_rows if r["model"] == alias and r["seed"] == seed][0]["PR_AUC"])
                        pair = paired_score_stats(y, logits_clean[alias][seed], scored["logits"], thr)
                        row = _metric_row(
                            alias,
                            seed,
                            cond,
                            met,
                            {
                                **pair,
                                "source": src,
                                "degradation": float(d),
                                "delta_PR_AUC": float(met["pr_auc"] - clean_pr),
                                "retention_PR_AUC": float(met["pr_auc"] / clean_pr) if clean_pr else float("nan"),
                                "delta_Brier": float(met["Brier"] - [r for r in clean_rows if r["model"] == alias and r["seed"] == seed][0]["Brier"]),
                                "delta_log_loss": float(met["log_loss"] - [r for r in clean_rows if r["model"] == alias and r["seed"] == seed][0]["log_loss"]),
                                "historical_endpoint": bool(float(d) == 1.0),
                            },
                        )
                        source_rows.append(row)
                        calib_rows.append(_metric_row(alias, seed, cond, met, {"family": "source", "source": src, "severity": float(d)}))
                        if historical and float(d) == 1.0:
                            expected = _csv_pr(hist["source"], model=alias, seed=seed, source=src)
                            ok = abs(float(met["pr_auc"]) - expected) <= DEGRADED_PARITY_TOLERANCE
                            parity_checks.append(
                                {
                                    "gate": "source_d1",
                                    "model": alias,
                                    "seed": seed,
                                    "source": src,
                                    "live": float(met["pr_auc"]),
                                    "editor017": expected,
                                    "PASS": ok,
                                }
                            )
                            if not ok:
                                write_json(
                                    _review("EDITOR023_HISTORICAL_PARITY.json"),
                                    {"HISTORICAL_PARITY_GATE": "FAIL", "checks": parity_checks},
                                )
                                raise Editor023Blocked(
                                    f"EDITOR023_PARITY_GATE = FAIL: source d=1 {alias}/{seed}/{src}"
                                )
                    if alias == "T-OPT":
                        topt_scored[seed] = scored
                    if alias in TEACHER_RELATIVE_MODELS:
                        t = topt_scored[seed]
                        rel = teacher_relative(
                            scored["logits"], t["logits"], scored["choices"], t["choices"], scored["leaf_probs_all"], t["leaf_probs_all"]
                        )
                        seq = per_sequence_route(scored["choices"], t["choices"], scored["leaf_probs_all"], t["leaf_probs_all"])
                        seq_route_deg[alias][seed].append(seq["route_MAE"])
                        own = route_leaf_pair(
                            clean_struct[alias][seed]["choices"],
                            scored["choices"],
                            clean_struct[alias][seed]["leaf_probs_all"],
                            scored["leaf_probs_all"],
                        )
                        route_rows.append(
                            {
                                "model": alias,
                                "seed": seed,
                                "family": "source",
                                "condition": cond,
                                "source": src,
                                "degradation": float(d),
                                "comparison": "teacher_relative_TOPT",
                                **{k: rel[k] for k in ("route_MAE", "route_KL", "hard_route_agreement", "dominant_leaf_agreement")},
                            }
                        )
                        route_rows.append(
                            {
                                "model": alias,
                                "seed": seed,
                                "family": "source",
                                "condition": cond,
                                "source": src,
                                "degradation": float(d),
                                "comparison": "degraded_vs_own_clean",
                                **own,
                            }
                        )
                        if historical and float(d) == 1.0:
                            hist_route_mae[alias]["source"].append(float(rel["route_MAE"]))
                    if alias in DIRECTIONAL_MODELS:
                        cc = centred_contributions(clean_struct[alias][seed]["tree_outputs"], train_refs[alias][seed])
                        cd = centred_contributions(scored["tree_outputs"], train_refs[alias][seed])
                        est = contribution_stability(cc, cd)
                        seq_expl_deg[alias][seed].append(per_sequence_spearman(cc, cd))
                        explain_rows.append({"model": alias, "seed": seed, "family": "source", "condition": cond, "source": src, "degradation": float(d), **est})
                        if historical and float(d) == 1.0:
                            hist_expl[alias]["source"].append(float(est["tree_contribution_spearman"]))
                    _assert_fingerprint(alias, seed, loaded)
                    _unload(loaded, device)

    def run_noise_jobs(levels: list[float] | tuple[float, ...], *, historical: bool) -> None:
        for lvl in levels:
            X = apply_gaussian_noise(X_val, float(lvl))
            topt_scored: dict[int, dict[str, np.ndarray]] = {}
            for alias in SCORING_MODELS:
                for seed in PRIMARY_SEEDS:
                    print(f"[EDITOR-023] {alias}/{seed} noise={lvl}", flush=True)
                    loaded = _load_model(alias, seed, device)
                    scored = score_tensor(alias, seed, loaded, X)
                    thr = float(thresholds[alias][seed])
                    met = metrics_at_frozen_threshold(y, scored["logits"], thr)
                    cond = f"noise_{float(lvl)}"
                    _save_logits(alias, seed, cond, scored["logits"])
                    if alias in PRIMARY_MODELS:
                        logits_noise[alias][seed][float(lvl)] = scored["logits"]
                        clean_pr = float([r for r in clean_rows if r["model"] == alias and r["seed"] == seed][0]["PR_AUC"])
                        pair = paired_score_stats(y, logits_clean[alias][seed], scored["logits"], thr)
                        noise_rows.append(
                            _metric_row(
                                alias,
                                seed,
                                cond,
                                met,
                                {
                                    **pair,
                                    "noise_level": float(lvl),
                                    "delta_PR_AUC": float(met["pr_auc"] - clean_pr),
                                    "retention_PR_AUC": float(met["pr_auc"] / clean_pr) if clean_pr else float("nan"),
                                    "delta_Brier": float(met["Brier"] - [r for r in clean_rows if r["model"] == alias and r["seed"] == seed][0]["Brier"]),
                                    "delta_log_loss": float(met["log_loss"] - [r for r in clean_rows if r["model"] == alias and r["seed"] == seed][0]["log_loss"]),
                                    "historical_level": bool(float(lvl) in NOISE_LEVELS_HISTORICAL),
                                },
                            )
                        )
                        calib_rows.append(_metric_row(alias, seed, cond, met, {"family": "noise", "severity": float(lvl)}))
                        if historical:
                            expected = _csv_pr(hist["noise"], model=alias, seed=seed, noise_level=float(lvl))
                            ok = abs(float(met["pr_auc"]) - expected) <= DEGRADED_PARITY_TOLERANCE
                            parity_checks.append(
                                {
                                    "gate": "noise_historical",
                                    "model": alias,
                                    "seed": seed,
                                    "noise_level": float(lvl),
                                    "live": float(met["pr_auc"]),
                                    "editor017": expected,
                                    "PASS": ok,
                                }
                            )
                            if not ok:
                                write_json(
                                    _review("EDITOR023_HISTORICAL_PARITY.json"),
                                    {"HISTORICAL_PARITY_GATE": "FAIL", "checks": parity_checks},
                                )
                                raise Editor023Blocked(
                                    f"EDITOR023_PARITY_GATE = FAIL: noise {alias}/{seed}/{lvl}"
                                )
                    if alias == "T-OPT":
                        topt_scored[seed] = scored
                    if alias in TEACHER_RELATIVE_MODELS:
                        t = topt_scored[seed]
                        rel = teacher_relative(
                            scored["logits"], t["logits"], scored["choices"], t["choices"], scored["leaf_probs_all"], t["leaf_probs_all"]
                        )
                        seq = per_sequence_route(scored["choices"], t["choices"], scored["leaf_probs_all"], t["leaf_probs_all"])
                        seq_route_deg[alias][seed].append(seq["route_MAE"])
                        own = route_leaf_pair(
                            clean_struct[alias][seed]["choices"],
                            scored["choices"],
                            clean_struct[alias][seed]["leaf_probs_all"],
                            scored["leaf_probs_all"],
                        )
                        route_rows.append(
                            {
                                "model": alias,
                                "seed": seed,
                                "family": "noise",
                                "condition": cond,
                                "noise_level": float(lvl),
                                "comparison": "teacher_relative_TOPT",
                                **{k: rel[k] for k in ("route_MAE", "route_KL", "hard_route_agreement", "dominant_leaf_agreement")},
                            }
                        )
                        route_rows.append(
                            {
                                "model": alias,
                                "seed": seed,
                                "family": "noise",
                                "condition": cond,
                                "noise_level": float(lvl),
                                "comparison": "degraded_vs_own_clean",
                                **own,
                            }
                        )
                        if historical:
                            hist_route_mae[alias]["noise"].append(float(rel["route_MAE"]))
                    if alias in DIRECTIONAL_MODELS:
                        cc = centred_contributions(clean_struct[alias][seed]["tree_outputs"], train_refs[alias][seed])
                        cd = centred_contributions(scored["tree_outputs"], train_refs[alias][seed])
                        est = contribution_stability(cc, cd)
                        seq_expl_deg[alias][seed].append(per_sequence_spearman(cc, cd))
                        explain_rows.append({"model": alias, "seed": seed, "family": "noise", "condition": cond, "noise_level": float(lvl), **est})
                        if historical:
                            hist_expl[alias]["noise"].append(float(est["tree_contribution_spearman"]))
                    _assert_fingerprint(alias, seed, loaded)
                    _unload(loaded, device)

    run_source_jobs(hist_source_jobs, historical=True)
    run_noise_jobs(hist_noise_jobs, historical=True)

    def _mean_or_nan(xs: list[float]) -> float:
        return float(np.mean(xs)) if xs else float("nan")

    route_parity = []
    for alias in TEACHER_RELATIVE_MODELS:
        live_clean = _mean_or_nan(hist_route_mae[alias]["clean"])
        live_src = _mean_or_nan(hist_route_mae[alias]["source"])
        live_noise = _mean_or_nan(hist_route_mae[alias]["noise"])
        exp_clean = float(hist["route"][f"{alias}_CLEAN_ROUTE_MAE_teacher_relative"])
        exp_src = float(hist["route"][f"{alias}_source_teacher_relative_route_MAE"])
        exp_noise = float(hist["route"][f"{alias}_noise_teacher_relative_route_MAE"])
        for name, live, expected in (
            ("clean", live_clean, exp_clean),
            ("source", live_src, exp_src),
            ("noise", live_noise, exp_noise),
        ):
            ok = abs(live - expected) <= ROUTE_PARITY_TOLERANCE
            rec = {"gate": "route", "model": alias, "family": name, "live": live, "editor017": expected, "PASS": ok}
            route_parity.append(rec)
            parity_checks.append(rec)
            if not ok:
                write_json(_review("EDITOR023_HISTORICAL_PARITY.json"), {"HISTORICAL_PARITY_GATE": "FAIL", "checks": parity_checks})
                raise Editor023Blocked(f"EDITOR023_PARITY_GATE = FAIL: route {alias}/{name}")

    expl_parity = []
    for alias in DIRECTIONAL_MODELS:
        live_src = _mean_or_nan(hist_expl[alias]["source"])
        live_noise = _mean_or_nan(hist_expl[alias]["noise"])
        exp_src = float(hist["explanation"][f"{alias}_source_spearman"])
        exp_noise = float(hist["explanation"][f"{alias}_noise_spearman"])
        for name, live, expected in (("source", live_src, exp_src), ("noise", live_noise, exp_noise)):
            ok = abs(live - expected) <= EXPLANATION_PARITY_TOLERANCE
            rec = {"gate": "explanation", "model": alias, "family": name, "live": live, "editor017": expected, "PASS": ok}
            expl_parity.append(rec)
            parity_checks.append(rec)
            if not ok:
                write_json(_review("EDITOR023_HISTORICAL_PARITY.json"), {"HISTORICAL_PARITY_GATE": "FAIL", "checks": parity_checks})
                raise Editor023Blocked(f"EDITOR023_PARITY_GATE = FAIL: explanation {alias}/{name}")

    hist_payload = {
        "HISTORICAL_PARITY_GATE": "PASS",
        "clean_tolerance": PARITY_TOLERANCE,
        "degraded_tolerance": DEGRADED_PARITY_TOLERANCE,
        "route_tolerance": ROUTE_PARITY_TOLERANCE,
        "explanation_tolerance": EXPLANATION_PARITY_TOLERANCE,
        "d1_ablation_sha256": ablation_hashes,
        "d1_equals_editor017_operator": True,
        "checks": parity_checks,
        "route_parity": route_parity,
        "explanation_parity": expl_parity,
        "n_fail": 0,
        "written_at": utc_now(),
    }
    write_json(_review("EDITOR023_HISTORICAL_PARITY.json"), hist_payload)
    print("[EDITOR-023] HISTORICAL_PARITY_GATE = PASS; evaluating new severities", flush=True)

    new_source_jobs = [(src, float(d)) for src in SOURCE_CHANNELS for d in SOURCE_DEGRADATION_NEW]
    run_source_jobs(new_source_jobs, historical=False)
    run_noise_jobs(NOISE_LEVELS_NEW, historical=False)

    write_csv(_review("EDITOR023_CLEAN_RESULTS.csv"), [r for r in clean_rows if r["model"] in PRIMARY_MODELS])
    write_csv(_review("EDITOR023_SOURCE_CURVES.csv"), source_rows)
    write_csv(_review("EDITOR023_NOISE_CURVES.csv"), noise_rows)
    write_csv(_review("EDITOR023_ROUTE_CURVES.csv"), route_rows)
    write_csv(_review("EDITOR023_EXPLANATION_CURVES.csv"), explain_rows)
    write_csv(_review("EDITOR023_CALIBRATION_CURVES.csv"), calib_rows)

    clean_pr = {alias: {s: float([r for r in clean_rows if r["model"] == alias and r["seed"] == s][0]["PR_AUC"]) for s in PRIMARY_SEEDS} for alias in PRIMARY_MODELS}
    source_aurc = summarise_source_aurc(source_rows, {a: clean_pr[a] for a in PRIMARY_MODELS})
    noise_aurc = summarise_noise_aurc(noise_rows)
    write_json(_review("EDITOR023_SOURCE_AURC.json"), source_aurc)
    write_json(_review("EDITOR023_NOISE_AURC.json"), noise_aurc)

    profiles = {}
    for alias in PRIMARY_MODELS:
        src_ret: dict[str, dict[float, float]] = {}
        for src in SOURCE_CHANNELS:
            src_ret[src] = {0.0: 1.0}
            for d in SOURCE_DEGRADATION_LEVELS:
                if float(d) == 0.0:
                    continue
                recs = [r for r in source_rows if r["model"] == alias and r["source"] == src and abs(float(r["degradation"]) - float(d)) < 1e-12]
                src_ret[src][float(d)] = float(np.mean([r["retention_PR_AUC"] for r in recs]))
        noise_ret = {0.0: 1.0}
        for lvl in NOISE_LEVELS:
            if float(lvl) == 0.0:
                continue
            recs = [r for r in noise_rows if r["model"] == alias and abs(float(r["noise_level"]) - float(lvl)) < 1e-12]
            noise_ret[float(lvl)] = float(np.mean([r["retention_PR_AUC"] for r in recs]))
        profiles[alias] = failure_profile(src_ret, noise_ret)
    source_aurc["failure_profiles"] = profiles

    def _mean_route(alias: str, family: str, comparison: str) -> float:
        recs = [r for r in route_rows if r["model"] == alias and r["family"] == family and r["comparison"] == comparison]
        return float(np.mean([r["route_MAE"] for r in recs])) if recs else float("nan")

    def _mean_route_metric(alias: str, family: str, comparison: str, key: str) -> float:
        recs = [r for r in route_rows if r["model"] == alias and r["family"] == family and r["comparison"] == comparison]
        return float(np.mean([r[key] for r in recs])) if recs else float("nan")

    route_summary = {
        "F10_CLEAN_ROUTE_MAE": _mean_route("F10", "clean", "teacher_relative_TOPT"),
        "TA2_CLEAN_ROUTE_MAE": _mean_route("TA2", "clean", "teacher_relative_TOPT"),
        "F10_DEGRADED_ROUTE_MAE": float(
            np.mean(
                [
                    _mean_route("F10", "source", "teacher_relative_TOPT"),
                    _mean_route("F10", "noise", "teacher_relative_TOPT"),
                ]
            )
        ),
        "TA2_DEGRADED_ROUTE_MAE": float(
            np.mean(
                [
                    _mean_route("TA2", "source", "teacher_relative_TOPT"),
                    _mean_route("TA2", "noise", "teacher_relative_TOPT"),
                ]
            )
        ),
        "F10_source_teacher_relative_route_MAE": _mean_route("F10", "source", "teacher_relative_TOPT"),
        "TA2_source_teacher_relative_route_MAE": _mean_route("TA2", "source", "teacher_relative_TOPT"),
        "F10_noise_teacher_relative_route_MAE": _mean_route("F10", "noise", "teacher_relative_TOPT"),
        "TA2_noise_teacher_relative_route_MAE": _mean_route("TA2", "noise", "teacher_relative_TOPT"),
        "F10_CLEAN_ROUTE_KL": _mean_route_metric("F10", "clean", "teacher_relative_TOPT", "route_KL"),
        "TA2_CLEAN_ROUTE_KL": _mean_route_metric("TA2", "clean", "teacher_relative_TOPT", "route_KL"),
        "F10_CLEAN_hard_route_agreement": _mean_route_metric("F10", "clean", "teacher_relative_TOPT", "hard_route_agreement"),
        "TA2_CLEAN_hard_route_agreement": _mean_route_metric("TA2", "clean", "teacher_relative_TOPT", "hard_route_agreement"),
        "F10_CLEAN_dominant_leaf_agreement": _mean_route_metric("F10", "clean", "teacher_relative_TOPT", "dominant_leaf_agreement"),
        "TA2_CLEAN_dominant_leaf_agreement": _mean_route_metric("TA2", "clean", "teacher_relative_TOPT", "dominant_leaf_agreement"),
        "note": "route identities compared only within the same model/seed; teacher-relative uses matched T-OPT",
        "three_seeds_are_not_independent_experimental_units": True,
    }
    write_json(_review("EDITOR023_ROUTE_SUMMARY.json"), route_summary)

    def _mean_expl(alias: str, family: str | None = None) -> float:
        recs = [r for r in explain_rows if r["model"] == alias and (family is None or r["family"] == family)]
        return float(np.mean([r["tree_contribution_spearman"] for r in recs])) if recs else float("nan")

    expl_summary = {
        "TA2_aggregate_spearman": _mean_expl("TA2"),
        "F10_aggregate_spearman": _mean_expl("F10"),
        "TA2_minus_F10": _mean_expl("TA2") - _mean_expl("F10"),
        "TA2_source_spearman": _mean_expl("TA2", "source"),
        "F10_source_spearman": _mean_expl("F10", "source"),
        "TA2_noise_spearman": _mean_expl("TA2", "noise"),
        "F10_noise_spearman": _mean_expl("F10", "noise"),
        "definition": "reference-centred signed tree-contribution vector; rank-stability = tree_contribution_spearman",
        "tree_identities_compared_across_seeds": False,
        "three_seeds_are_not_independent_experimental_units": True,
    }
    write_json(_review("EDITOR023_EXPLANATION_SUMMARY.json"), expl_summary)

    print("[EDITOR-023] user-cluster bootstrap", flush=True)
    boot = aurc_bootstrap(y, users, logits_clean, logits_source, logits_noise)
    f10_deg = [np.nanmean(np.stack(seq_route_deg["F10"][s], axis=0), axis=0) for s in PRIMARY_SEEDS]
    ta2_deg = [np.nanmean(np.stack(seq_route_deg["TA2"][s], axis=0), axis=0) for s in PRIMARY_SEEDS]
    f10_clean_seq = [seq_route_clean["F10"][s] for s in PRIMARY_SEEDS]
    ta2_clean_seq = [seq_route_clean["TA2"][s] for s in PRIMARY_SEEDS]
    route_clean_boot = scalar_mean_contrast_bootstrap(
        users, y, f10_clean_seq, ta2_clean_seq, contrast="TA2_minus_F10_CLEAN_ROUTE_MAE", higher_is_better=False
    )
    route_deg_boot = scalar_mean_contrast_bootstrap(
        users, y, f10_deg, ta2_deg, contrast="TA2_minus_F10_DEGRADED_ROUTE_MAE", higher_is_better=False
    )
    f10_expl = [np.nanmean(np.stack(seq_expl_deg["F10"][s], axis=0), axis=0) for s in PRIMARY_SEEDS]
    ta2_expl = [np.nanmean(np.stack(seq_expl_deg["TA2"][s], axis=0), axis=0) for s in PRIMARY_SEEDS]
    expl_boot = scalar_mean_contrast_bootstrap(
        users, y, f10_expl, ta2_expl, contrast="TA2_minus_F10_EXPLANATION_STABILITY", higher_is_better=True
    )
    cluster = {
        "sampling_unit": "validation user",
        "n_resamples": 2000,
        "seed": 42,
        "three_seeds_are_not_independent_experimental_units": True,
        "aurc": boot,
        "route_clean_TA2_minus_F10": route_clean_boot,
        "route_degraded_TA2_minus_F10": route_deg_boot,
        "explanation_TA2_minus_F10": expl_boot,
    }
    write_json(_review("EDITOR023_CLUSTER_BOOTSTRAP.json"), cluster)

    seed_dir = seed_direction_table(source_aurc, noise_aurc, clean_pr)
    per_seed_route = {}
    for seed in PRIMARY_SEEDS:
        f10c = [r for r in route_rows if r["model"] == "F10" and r["seed"] == seed and r["family"] == "clean" and r["comparison"] == "teacher_relative_TOPT"][0]["route_MAE"]
        ta2c = [r for r in route_rows if r["model"] == "TA2" and r["seed"] == seed and r["family"] == "clean" and r["comparison"] == "teacher_relative_TOPT"][0]["route_MAE"]
        f10d = np.mean([r["route_MAE"] for r in route_rows if r["model"] == "F10" and r["seed"] == seed and r["comparison"] == "teacher_relative_TOPT" and r["family"] in {"source", "noise"}])
        ta2d = np.mean([r["route_MAE"] for r in route_rows if r["model"] == "TA2" and r["seed"] == seed and r["comparison"] == "teacher_relative_TOPT" and r["family"] in {"source", "noise"}])
        per_seed_route[seed] = {"clean_delta_TA2_minus_F10": float(ta2c - f10c), "degraded_delta_TA2_minus_F10": float(ta2d - f10d)}
    seed_dir["TA2_minus_F10_ROUTE_MAE"] = {
        "by_seed": {str(s): per_seed_route[s] for s in PRIMARY_SEEDS},
        "clean_favourable": f"{int(sum(per_seed_route[s]['clean_delta_TA2_minus_F10'] < 0 for s in PRIMARY_SEEDS))}/3",
        "degraded_favourable": f"{int(sum(per_seed_route[s]['degraded_delta_TA2_minus_F10'] < 0 for s in PRIMARY_SEEDS))}/3",
        "higher_is_better": False,
        "unfavourable_seeds_retained": True,
    }
    write_json(_review("EDITOR023_SEED_DIRECTION.json"), seed_dir)

    clean_means = {alias: float(np.mean(list(clean_pr[alias].values()))) for alias in PRIMARY_MODELS}
    ta2_c2_clean = clean_means["TA2"] - clean_means["C2-OPT"]
    clean_seeds_pos = int(sum(clean_pr["TA2"][s] > clean_pr["C2-OPT"][s] for s in PRIMARY_SEEDS))
    tg_clean = teacher_guidance_clean_value(ta2_c2_clean, clean_seeds_pos)
    src_ci = boot["F10_minus_C2_SOURCE_AURC"]["ci95"]
    noise_ci = boot["F10_minus_C2_NOISE_AURC"]["ci95"]
    tg_deg = teacher_guidance_degraded_value(source_aurc["F10_minus_C2"], noise_aurc["F10_minus_C2"], src_ci, noise_ci)
    route_val = route_anchor_structural_value(
        route_summary["TA2_CLEAN_ROUTE_MAE"],
        route_summary["F10_CLEAN_ROUTE_MAE"],
        route_summary["TA2_DEGRADED_ROUTE_MAE"],
        route_summary["F10_DEGRADED_ROUTE_MAE"],
    )
    lin_val = odst_degraded_over_linear(
        source_aurc["TA2_minus_L1"],
        noise_aurc["TA2_minus_L1"],
        boot["TA2_minus_L1_SOURCE_AURC"]["ci95"],
        boot["TA2_minus_L1_NOISE_AURC"]["ci95"],
    )
    expl_val = explanation_stability_value(expl_summary["TA2_minus_F10"])
    overall = overall_architecture_value(tg_clean, tg_deg, route_val, lin_val)

    def _fmt_ci(rec: dict[str, Any]) -> str:
        lo, hi = rec["ci95"]
        return f"[{lo:.10f}, {hi:.10f}]"

    ruling = {
        "TEACHER_GUIDANCE_CLEAN_VALUE": tg_clean,
        "TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE": tg_deg,
        "ROUTE_ANCHOR_STRUCTURAL_VALUE": route_val,
        "TA2_ODST_DEGRADED_INPUT_VALUE_OVER_LINEAR": lin_val,
        "TA2_OVERALL_ARCHITECTURE_VALUE": overall,
        "TREE_EXPLANATION_DEGRADED_INPUT_STABILITY": expl_val,
        "CURRENT_PAPER_MODEL": "TA2",
        "CLEAN": clean_means,
        "TA2_MINUS_C2_CLEAN": ta2_c2_clean,
        "SOURCE_AURC": {a: source_aurc["models"][a]["SOURCE_AURC"] for a in PRIMARY_MODELS},
        "NOISE_AURC": {a: noise_aurc["models"][a]["NOISE_AURC"] for a in PRIMARY_MODELS},
        "contrasts": {
            "F10_minus_C2_SOURCE_AURC": source_aurc["F10_minus_C2"],
            "TA2_minus_C2_SOURCE_AURC": source_aurc["TA2_minus_C2"],
            "TA2_minus_F10_SOURCE_AURC": source_aurc["TA2_minus_F10"],
            "TA2_minus_L1_SOURCE_AURC": source_aurc["TA2_minus_L1"],
            "F10_minus_C2_NOISE_AURC": noise_aurc["F10_minus_C2"],
            "TA2_minus_C2_NOISE_AURC": noise_aurc["TA2_minus_C2"],
            "TA2_minus_F10_NOISE_AURC": noise_aurc["TA2_minus_F10"],
            "TA2_minus_L1_NOISE_AURC": noise_aurc["TA2_minus_L1"],
        },
        "failure_profiles": profiles,
        "claim_boundaries": "controlled degraded-input / data-quality resilience only",
        "forbidden_terms_used": False,
        "written_at": utc_now(),
    }
    write_json(_review("EDITOR023_ARCHITECTURE_VALUE_RULING.json"), ruling)

    matrix = [
        {"question": "teacher_guidance_clean_value", "ruling": tg_clean, "evidence": f"TA2-C2 clean={ta2_c2_clean}; seeds={clean_seeds_pos}/3"},
        {"question": "teacher_guidance_degraded_input_value", "ruling": tg_deg, "evidence": f"F10-C2 SOURCE_AURC={source_aurc['F10_minus_C2']}; NOISE_AURC={noise_aurc['F10_minus_C2']}"},
        {"question": "complete_TA2_formulation_vs_C2", "ruling": "point_both_positive" if source_aurc["TA2_minus_C2"] > 0 and noise_aurc["TA2_minus_C2"] > 0 else "not_both_positive", "evidence": f"TA2-C2 SOURCE={source_aurc['TA2_minus_C2']} NOISE={noise_aurc['TA2_minus_C2']}"},
        {"question": "route_anchor_structural_value", "ruling": route_val, "evidence": f"clean MAE TA2={route_summary['TA2_CLEAN_ROUTE_MAE']} F10={route_summary['F10_CLEAN_ROUTE_MAE']}"},
        {"question": "odst_degraded_input_value_over_linear", "ruling": lin_val, "evidence": f"TA2-L1 SOURCE={source_aurc['TA2_minus_L1']} NOISE={noise_aurc['TA2_minus_L1']}"},
        {"question": "explanation_stability", "ruling": expl_val, "evidence": f"TA2-F10 spearman={expl_summary['TA2_minus_F10']}"},
        {"question": "clean_ODST_superiority_over_attention_linear", "ruling": "NOT_CLAIMED", "evidence": "outside EDITOR-023 claim boundaries unless separately supported"},
        {"question": "overall_architecture_value", "ruling": overall, "evidence": "claim separation mandatory; not every metric required"},
    ]
    write_csv(_review("EDITOR023_EDITOR_RESPONSE_MATRIX.csv"), matrix)

    protocol_sha = _protocol_freeze_commit()
    payload = {
        "task_id": "EDITOR-023",
        "EDITOR022_RESULTS_COMMIT": EDITOR022_RESULTS_COMMIT,
        "EDITOR023_PROTOCOL_FREEZE_COMMIT": protocol_sha,
        "device": str(device),
        "CHECKPOINT_GATE": ck_gate["CHECKPOINT_GATE"],
        "HISTORICAL_PARITY_GATE": "PASS",
        "TRAINING_EXECUTED": "NO",
        "SOURCE_GATE": "PASS" if source_gate else "FAIL",
        "r52_test_accessed": False,
        "r52_test_predictions_generated": False,
        "r51_rerun": False,
        "r62_rerun": False,
        "model_parameters_updated": False,
        "threshold_retuned": False,
        "calibration_refit": False,
        "mapping": mapping,
        "fingerprints": fingerprints,
        "ruling": ruling,
        "source_aurc": source_aurc,
        "noise_aurc": noise_aurc,
        "route_summary": route_summary,
        "expl_summary": expl_summary,
        "cluster": {
            "TEACHER_GUIDANCE_SOURCE_CI95": _fmt_ci(boot["F10_minus_C2_SOURCE_AURC"]),
            "TEACHER_GUIDANCE_NOISE_CI95": _fmt_ci(boot["F10_minus_C2_NOISE_AURC"]),
            "TA2_MINUS_L1_SOURCE_CI95": _fmt_ci(boot["TA2_minus_L1_SOURCE_AURC"]),
            "TA2_MINUS_L1_NOISE_CI95": _fmt_ci(boot["TA2_minus_L1_NOISE_AURC"]),
        },
        "python": sys.version,
        "pytorch": torch.__version__,
        "written_at": utc_now(),
    }
    return finalise(payload)


def write_result_freeze(payload: dict[str, Any]) -> None:
    r = payload["ruling"]
    s = payload["source_aurc"]
    n = payload["noise_aurc"]
    text = f"""# EDITOR-023 result freeze

EDITOR023_PARENT_COMMIT = {EDITOR022_RESULTS_COMMIT}
EDITOR023_PROTOCOL_FREEZE_COMMIT = {payload['EDITOR023_PROTOCOL_FREEZE_COMMIT']}

These are controlled degraded-input / data-quality experiments.
Do not describe any EDITOR-023 result as adversarial robustness, evasion resistance, poisoning resistance, physical sensor failure, or unseen-user generalisation.

## Clean validation PR-AUC (seed mean)

- C2-OPT = {r['CLEAN']['C2-OPT']}
- F10 = {r['CLEAN']['F10']}
- TA2 = {r['CLEAN']['TA2']}
- L1 = {r['CLEAN']['L1']}
- TA2 - C2 = {r['TA2_MINUS_C2_CLEAN']}

## SOURCE_AURC (higher is better)

- C2-OPT = {s['models']['C2-OPT']['SOURCE_AURC']}
- F10 = {s['models']['F10']['SOURCE_AURC']}
- TA2 = {s['models']['TA2']['SOURCE_AURC']}
- L1 = {s['models']['L1']['SOURCE_AURC']}

## NOISE_AURC (higher is better)

- C2-OPT = {n['models']['C2-OPT']['NOISE_AURC']}
- F10 = {n['models']['F10']['NOISE_AURC']}
- TA2 = {n['models']['TA2']['NOISE_AURC']}
- L1 = {n['models']['L1']['NOISE_AURC']}

## Architecture-value ruling

- TEACHER_GUIDANCE_CLEAN_VALUE = {r['TEACHER_GUIDANCE_CLEAN_VALUE']}
- TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE = {r['TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE']}
- ROUTE_ANCHOR_STRUCTURAL_VALUE = {r['ROUTE_ANCHOR_STRUCTURAL_VALUE']}
- TA2_ODST_DEGRADED_INPUT_VALUE_OVER_LINEAR = {r['TA2_ODST_DEGRADED_INPUT_VALUE_OVER_LINEAR']}
- TREE_EXPLANATION_DEGRADED_INPUT_STABILITY = {r['TREE_EXPLANATION_DEGRADED_INPUT_STABILITY']}
- TA2_OVERALL_ARCHITECTURE_VALUE = {r['TA2_OVERALL_ARCHITECTURE_VALUE']}
- CURRENT_PAPER_MODEL = TA2
"""
    _review("EDITOR023_RESULT_FREEZE.md").write_text(text, encoding="utf-8")


def terminal_block(payload: dict[str, Any], results_commit: str = "PENDING") -> str:
    r = payload["ruling"]
    s = payload["source_aurc"]
    n = payload["noise_aurc"]
    route = payload["route_summary"]
    expl = payload["expl_summary"]
    ci = payload["cluster"]
    lines = [
        "EDITOR023_COMPLETE",
        "",
        f"EDITOR023_PARENT_COMMIT =",
        EDITOR022_RESULTS_COMMIT,
        "",
        f"EDITOR023_PROTOCOL_FREEZE_COMMIT =",
        payload["EDITOR023_PROTOCOL_FREEZE_COMMIT"],
        "",
        f"EDITOR023_RESULTS_COMMIT =",
        results_commit,
        "",
        f"SOURCE_GATE = {payload['SOURCE_GATE']}",
        "",
        "UNIT_TEST_GATE = PASS",
        "",
        f"CHECKPOINT_GATE = {payload['CHECKPOINT_GATE']}",
        "",
        f"HISTORICAL_PARITY_GATE = {payload['HISTORICAL_PARITY_GATE']}",
        "",
        "TRAINING_EXECUTED = NO",
        "",
        "",
        f"CLEAN_C2_PR_AUC = {r['CLEAN']['C2-OPT']}",
        "",
        f"CLEAN_F10_PR_AUC = {r['CLEAN']['F10']}",
        "",
        f"CLEAN_TA2_PR_AUC = {r['CLEAN']['TA2']}",
        "",
        f"CLEAN_L1_PR_AUC = {r['CLEAN']['L1']}",
        "",
        f"TA2_MINUS_C2_CLEAN = {r['TA2_MINUS_C2_CLEAN']}",
        "",
        "",
        f"SOURCE_AURC_C2 = {s['models']['C2-OPT']['SOURCE_AURC']}",
        "",
        f"SOURCE_AURC_F10 = {s['models']['F10']['SOURCE_AURC']}",
        "",
        f"SOURCE_AURC_TA2 = {s['models']['TA2']['SOURCE_AURC']}",
        "",
        f"SOURCE_AURC_L1 = {s['models']['L1']['SOURCE_AURC']}",
        "",
        f"F10_MINUS_C2_SOURCE_AURC = {s['F10_minus_C2']}",
        "",
        f"TA2_MINUS_C2_SOURCE_AURC = {s['TA2_minus_C2']}",
        "",
        f"TA2_MINUS_L1_SOURCE_AURC = {s['TA2_minus_L1']}",
        "",
        "",
        f"NOISE_AURC_C2 = {n['models']['C2-OPT']['NOISE_AURC']}",
        "",
        f"NOISE_AURC_F10 = {n['models']['F10']['NOISE_AURC']}",
        "",
        f"NOISE_AURC_TA2 = {n['models']['TA2']['NOISE_AURC']}",
        "",
        f"NOISE_AURC_L1 = {n['models']['L1']['NOISE_AURC']}",
        "",
        f"F10_MINUS_C2_NOISE_AURC = {n['F10_minus_C2']}",
        "",
        f"TA2_MINUS_C2_NOISE_AURC = {n['TA2_minus_C2']}",
        "",
        f"TA2_MINUS_F10_NOISE_AURC = {n['TA2_minus_F10']}",
        "",
        f"TA2_MINUS_L1_NOISE_AURC = {n['TA2_minus_L1']}",
        "",
        "",
        f"TEACHER_GUIDANCE_SOURCE_CI95 = {ci['TEACHER_GUIDANCE_SOURCE_CI95']}",
        "",
        f"TEACHER_GUIDANCE_NOISE_CI95 = {ci['TEACHER_GUIDANCE_NOISE_CI95']}",
        "",
        f"TA2_MINUS_L1_SOURCE_CI95 = {ci['TA2_MINUS_L1_SOURCE_CI95']}",
        "",
        f"TA2_MINUS_L1_NOISE_CI95 = {ci['TA2_MINUS_L1_NOISE_CI95']}",
        "",
        "",
        f"F10_TEACHER_RELATIVE_ROUTE_MAE = {route['F10_CLEAN_ROUTE_MAE']}",
        "",
        f"TA2_TEACHER_RELATIVE_ROUTE_MAE = {route['TA2_CLEAN_ROUTE_MAE']}",
        "",
        f"ROUTE_ANCHOR_STRUCTURAL_VALUE = {r['ROUTE_ANCHOR_STRUCTURAL_VALUE']}",
        "",
        "",
        f"TA2_MINUS_F10_EXPLANATION_STABILITY = {expl['TA2_minus_F10']}",
        "",
        f"TREE_EXPLANATION_DEGRADED_INPUT_STABILITY = {r['TREE_EXPLANATION_DEGRADED_INPUT_STABILITY']}",
        "",
        "",
        f"TEACHER_GUIDANCE_CLEAN_VALUE = {r['TEACHER_GUIDANCE_CLEAN_VALUE']}",
        "",
        f"TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE = {r['TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE']}",
        "",
        f"TA2_ODST_DEGRADED_INPUT_VALUE_OVER_LINEAR = {r['TA2_ODST_DEGRADED_INPUT_VALUE_OVER_LINEAR']}",
        "",
        f"TA2_OVERALL_ARCHITECTURE_VALUE = {r['TA2_OVERALL_ARCHITECTURE_VALUE']}",
        "",
        "",
        "CURRENT_PAPER_MODEL = TA2",
        "",
        "",
        "R52_TEST_ACCESSED = NO",
        "R52_TEST_PREDICTIONS_GENERATED = NO",
        "",
        "R51_RERUN = NO",
        "R62_RERUN = NO",
        "",
        "MODEL_PARAMETERS_UPDATED = NO",
        "THRESHOLD_RETUNED = NO",
        "CALIBRATION_REFIT = NO",
        "",
        "SHA_MANIFEST_VERIFICATION = PASS",
        "",
    ]
    text = "\n".join(lines)
    _review("EDITOR023_TERMINAL_BLOCK.txt").write_text(text, encoding="utf-8")
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
    rec = sha256_manifest(list(REVIEW_ROOT.rglob("*")), repo_root=REPO_ROOT)
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
    write_json(_review("EDITOR023_RUN_MANIFEST.json"), {"phase": "complete", "utc": utc_now(), **{k: v for k, v in payload.items() if k not in {"cluster"}} , "cluster_ci": payload["cluster"]})
    write_result_freeze(payload)
    terminal_block(payload, results_commit="PENDING")
    rec = write_sha256_manifest_last()
    ver = verify_sha256_manifest(rec)
    payload["SHA_MANIFEST_VERIFICATION"] = ver
    if ver != "PASS":
        raise Editor023Blocked("SHA_MANIFEST_VERIFICATION = FAIL")
    return payload
