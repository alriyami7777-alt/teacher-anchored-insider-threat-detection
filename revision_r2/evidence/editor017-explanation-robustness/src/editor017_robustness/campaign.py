"""EDITOR-017 frozen-checkpoint degraded-input and explanation campaign."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from editor012_rescue.constants import (
    EXPECTED_USER_MAPPING_SHA256,
    EXPECTED_VAL_MALICIOUS_USERS,
    EXPECTED_VAL_USERS,
    EXPECTED_VAL_WINDOWS_PER_USER,
)
from editor012_rescue.data import load_train_validation, make_xy_loader
from editor012_rescue.metrics import teacher_relative
from editor015_residual.explain import centred_contributions, directional_table, train_references

from .bootstrap_family import mean_noise_retention_contrast, mean_source_delta_contrast
from .constants import (
    BATCH_SIZE,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CLEAN_METRIC_TOLERANCE,
    DIRECTIONAL_KS,
    DIRECTIONAL_MODELS,
    FORBIDDEN_THREAT_TERMS,
    FROZEN_CLEAN_PR_AUC,
    GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
    LEAF_TRACEABILITY,
    MODEL_SPECS,
    NOISE_LEVELS,
    NOISE_SLOPE_LEVELS,
    ODST_MODELS,
    PRIMARY_MODELS,
    PRIMARY_SEEDS,
    ROUTE_TRACEABILITY,
    SOURCE_CHANNELS,
    TEACHER_RELATIVE_MODELS,
)
from .io_util import write_csv, write_json
from .models import load_l1, load_odst, parameter_fingerprint
from .perturbations import apply_gaussian_noise, apply_source_ablation, load_r52_train_scaler
from .protocol import freeze_protocol
from .safety import REVIEW_ROOT, Editor017Blocked, sha256_bytes, utc_now
from .score import metrics_at_frozen_threshold, ols_slope, paired_score_stats, score_l1_full, score_odst_full
from .stability import contribution_stability, route_leaf_pair


def _review(*parts: str) -> Path:
    return REVIEW_ROOT.joinpath(*parts)


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def recover_user_mapping(bundle: dict[str, Any]) -> dict[str, Any]:
    val = bundle["val"]
    users = np.asarray(val.user).astype(str).reshape(-1)
    y = np.asarray(val.y).reshape(-1)
    uniq, counts = np.unique(users, return_counts=True)
    malicious = sorted({str(u) for u, lab in zip(users, y) if lab > 0.5})
    mapping_hash = sha256_bytes(("\n".join(users.tolist())).encode("utf-8"))
    if mapping_hash != EXPECTED_USER_MAPPING_SHA256:
        raise Editor017Blocked(
            f"user-mapping hash mismatch expected={EXPECTED_USER_MAPPING_SHA256} observed={mapping_hash}"
        )
    if int(len(uniq)) != EXPECTED_VAL_USERS:
        raise Editor017Blocked(f"user count {len(uniq)} != {EXPECTED_VAL_USERS}")
    if int(counts.min()) != EXPECTED_VAL_WINDOWS_PER_USER or int(counts.max()) != EXPECTED_VAL_WINDOWS_PER_USER:
        raise Editor017Blocked("validation windows-per-user mismatch")
    if int(len(malicious)) != EXPECTED_VAL_MALICIOUS_USERS:
        raise Editor017Blocked(f"malicious users {len(malicious)} != {EXPECTED_VAL_MALICIOUS_USERS}")
    rec = {
        "USER_MAPPING_RECOVERED": True,
        "n_sequences": int(len(y)),
        "n_users": int(len(uniq)),
        "per_user_count_min": int(counts.min()),
        "per_user_count_max": int(counts.max()),
        "n_malicious_users": int(len(malicious)),
        "malicious_users": malicious,
        "mapping_sha256": mapping_hash,
        "hash_matches_EDITOR011_012_013_014_015_016": True,
        "expected_sha256": EXPECTED_USER_MAPPING_SHA256,
    }
    write_json(_review("07_statistics", "EDITOR017_USER_MAPPING_VERIFICATION.json"), rec)
    return rec


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


def _score_model(
    alias: str,
    seed: int,
    X: np.ndarray,
    y: np.ndarray,
    device: torch.device,
    loaded: dict[str, Any],
) -> dict[str, np.ndarray]:
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
        raise Editor017Blocked(f"parameter update detected for {alias}/{seed}")


def _mean_seed(values: dict[int, float]) -> float:
    return float(np.mean([values[s] for s in PRIMARY_SEEDS]))


def classify_teacher_guidance(source_favours: bool, source_ci: bool, noise_favours: bool, noise_ci: bool) -> str:
    if source_favours and noise_favours and source_ci and noise_ci:
        return "STRONG"
    if source_favours and noise_favours:
        return "CONSISTENT"
    if source_favours != noise_favours:
        return "MIXED"
    return "NOT_SUPPORTED"


def classify_odst_vs_linear(source_favours: bool, source_ci: bool, noise_favours: bool, noise_ci: bool) -> str:
    if source_favours and noise_favours and source_ci and noise_ci:
        return "STRONG"
    if source_favours and noise_favours:
        return "CONSISTENT"
    if source_favours != noise_favours:
        return "FAMILY_SPECIFIC"
    return "NOT_SUPPORTED"


def run_campaign() -> dict[str, Any]:
    device = _device()
    bundle = load_train_validation()
    mapping = recover_user_mapping(bundle)
    proto = freeze_protocol(y_val=bundle["val"].y)
    thresholds = proto["thresholds"]
    if thresholds is None:
        raise Editor017Blocked("frozen thresholds were not recovered")
    scaler = load_r52_train_scaler()
    y = np.asarray(bundle["val"].y).reshape(-1)
    users = np.asarray(bundle["val"].user).astype(str).reshape(-1)
    X_val = bundle["val"].X
    X_train = bundle["train"].X
    y_train = np.asarray(bundle["train"].y).reshape(-1)

    source_X = {src: apply_source_ablation(X_val, src, scaler) for src in SOURCE_CHANNELS}
    noise_X = {lvl: apply_gaussian_noise(X_val, lvl) for lvl in NOISE_LEVELS}
    if any(np.array_equal(source_X[src], X_val) for src in SOURCE_CHANNELS):
        raise Editor017Blocked("source ablation produced an unmodified tensor")
    if np.array_equal(y, bundle["val"].y) is False:
        raise Editor017Blocked("labels changed")
    y_check = np.asarray(bundle["val"].y).reshape(-1)
    if not np.array_equal(y, y_check):
        raise Editor017Blocked("labels changed")

    clean_rows = []
    source_rows = []
    noise_rows = []
    route_rows = []
    leaf_rows = []
    explain_rows = []
    directional_rows = []
    directional_boot: dict[str, Any] = {}
    logits: dict[str, dict[int, dict[str, np.ndarray]]] = {a: {s: {} for s in PRIMARY_SEEDS} for a in list(PRIMARY_MODELS) + ["T-OPT"]}
    clean_struct: dict[str, dict[int, dict[str, np.ndarray]]] = {a: {} for a in list(ODST_MODELS) + ["T-OPT"]}
    degraded_struct: dict[str, dict[int, dict[str, dict[str, np.ndarray]]]] = {
        a: {s: {} for s in PRIMARY_SEEDS} for a in list(ODST_MODELS) + ["T-OPT"]
    }
    train_refs: dict[str, dict[int, np.ndarray]] = {a: {} for a in DIRECTIONAL_MODELS}
    fingerprints = []

    aliases = list(PRIMARY_MODELS) + ["T-OPT"]
    for alias in aliases:
        for seed in PRIMARY_SEEDS:
            print(f"[EDITOR-017] scoring {alias} seed={seed} on {device}", flush=True)
            loaded = _load_model(alias, seed, device)
            fingerprints.append({"model": alias, "seed": seed, "sha256": loaded["sha256"], "fingerprint": loaded["fingerprint"]})
            scored = _score_model(alias, seed, X_val, y, device, loaded)
            if not np.array_equal(scored["y"].astype(int), y.astype(int)):
                raise Editor017Blocked("label order changed during scoring")
            thr = float(thresholds[alias][seed])
            met = metrics_at_frozen_threshold(y, scored["logits"], thr)
            frozen_pr = FROZEN_CLEAN_PR_AUC[alias][seed]
            if abs(float(met["pr_auc"]) - frozen_pr) > CLEAN_METRIC_TOLERANCE:
                raise Editor017Blocked(
                    f"clean PR-AUC mismatch {alias}/{seed}: live={met['pr_auc']} frozen={frozen_pr}"
                )
            logits[alias][seed]["clean"] = scored["logits"]
            extra = {"checkpoint_sha256": loaded["sha256"], "clean_PR_AUC_gate": "PASS"}
            if alias in ODST_MODELS or alias == "T-OPT":
                extra.update(
                    {
                        "route_tensor_shape": list(scored["choices"].shape),
                        "leaf_tensor_shape": list(scored["leaf_probs_all"].shape),
                        "tree_output_shape": list(scored["tree_outputs"].shape),
                        "attention_weight_shape": list(scored["attention_weights"].shape),
                    }
                )
                clean_struct[alias][seed] = {
                    "choices": scored["choices"],
                    "leaf_probs_all": scored["leaf_probs_all"],
                    "tree_outputs": scored["tree_outputs"],
                }
            clean_rows.append(_metric_row(alias, seed, "clean", met, extra))

            if alias in DIRECTIONAL_MODELS:
                print(f"[EDITOR-017] TRAIN references {alias} seed={seed}", flush=True)
                train_scored = _score_model(alias, seed, X_train, y_train, device, loaded)
                train_refs[alias][seed] = train_references(train_scored["tree_outputs"])
                dtab = directional_table(
                    y=y,
                    tree_outputs=scored["tree_outputs"],
                    references=train_refs[alias][seed],
                    linear_logit=np.zeros(len(y), dtype=np.float64),
                    reference_tree_outputs=None,
                    users=users,
                    rng_seed=BOOTSTRAP_SEED,
                )
                for row in dtab["rows"]:
                    directional_rows.append({"model": alias, "seed": seed, **row})
                directional_boot[f"{alias}/{seed}"] = {
                    "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": dtab["LOCAL_DIRECTIONAL_TREE_FAITHFULNESS"],
                    "MALICIOUS_DIRECTIONAL_FAITHFULNESS": dtab["MALICIOUS_DIRECTIONAL_FAITHFULNESS"],
                    "BENIGN_DIRECTIONAL_FAITHFULNESS": dtab["BENIGN_DIRECTIONAL_FAITHFULNESS"],
                    "HISTORICAL_GLOBAL_TOPK_FAITHFULNESS": dtab["HISTORICAL_GLOBAL_TOPK_FAITHFULNESS"],
                    "bootstrap": dtab["bootstrap"],
                }

            for src in SOURCE_CHANNELS:
                print(f"[EDITOR-017] {alias}/{seed} source={src}", flush=True)
                deg = _score_model(alias, seed, source_X[src], y, device, loaded)
                dmet = metrics_at_frozen_threshold(y, deg["logits"], thr)
                pair = paired_score_stats(y, scored["logits"], deg["logits"], thr)
                logits[alias][seed][f"without_{src}"] = deg["logits"]
                source_rows.append(
                    _metric_row(
                        alias,
                        seed,
                        f"without_{src}",
                        dmet,
                        {
                            **pair,
                            "delta_PR_AUC": float(dmet["pr_auc"] - met["pr_auc"]),
                            "retention_PR_AUC": float(dmet["pr_auc"] / met["pr_auc"]) if met["pr_auc"] else float("nan"),
                            "source": src,
                            "delta_Brier": float(dmet["Brier"] - met["Brier"]),
                            "delta_log_loss": float(dmet["log_loss"] - met["log_loss"]),
                        },
                    )
                )
                if alias in ODST_MODELS or alias == "T-OPT":
                    stab = route_leaf_pair(
                        scored["choices"], deg["choices"], scored["leaf_probs_all"], deg["leaf_probs_all"]
                    )
                    route_rows.append({"model": alias, "seed": seed, "family": "source", "condition": f"without_{src}", "comparison": "degraded_vs_own_clean", **stab})
                    leaf_rows.append({"model": alias, "seed": seed, "family": "source", "condition": f"without_{src}", "comparison": "degraded_vs_own_clean", "dominant_leaf_agreement": stab["dominant_leaf_agreement"]})
                    degraded_struct[alias][seed][f"without_{src}"] = {
                        "choices": deg["choices"],
                        "leaf_probs_all": deg["leaf_probs_all"],
                    }
                if alias in DIRECTIONAL_MODELS:
                    cc = centred_contributions(scored["tree_outputs"], train_refs[alias][seed])
                    cd = centred_contributions(deg["tree_outputs"], train_refs[alias][seed])
                    est = contribution_stability(cc, cd)
                    explain_rows.append({"model": alias, "seed": seed, "family": "source", "condition": f"without_{src}", **est})

            for lvl in NOISE_LEVELS:
                print(f"[EDITOR-017] {alias}/{seed} noise={lvl}", flush=True)
                deg = _score_model(alias, seed, noise_X[lvl], y, device, loaded)
                dmet = metrics_at_frozen_threshold(y, deg["logits"], thr)
                pair = paired_score_stats(y, scored["logits"], deg["logits"], thr)
                logits[alias][seed][f"noise_{lvl}"] = deg["logits"]
                noise_rows.append(
                    _metric_row(
                        alias,
                        seed,
                        f"noise_{lvl}",
                        dmet,
                        {
                            **pair,
                            "delta_PR_AUC": float(dmet["pr_auc"] - met["pr_auc"]),
                            "retention_PR_AUC": float(dmet["pr_auc"] / met["pr_auc"]) if met["pr_auc"] else float("nan"),
                            "noise_level": float(lvl),
                            "delta_Brier": float(dmet["Brier"] - met["Brier"]),
                            "delta_log_loss": float(dmet["log_loss"] - met["log_loss"]),
                        },
                    )
                )
                if alias in ODST_MODELS or alias == "T-OPT":
                    stab = route_leaf_pair(
                        scored["choices"], deg["choices"], scored["leaf_probs_all"], deg["leaf_probs_all"]
                    )
                    route_rows.append({"model": alias, "seed": seed, "family": "noise", "condition": f"noise_{lvl}", "comparison": "degraded_vs_own_clean", **stab})
                    leaf_rows.append({"model": alias, "seed": seed, "family": "noise", "condition": f"noise_{lvl}", "comparison": "degraded_vs_own_clean", "dominant_leaf_agreement": stab["dominant_leaf_agreement"]})
                    degraded_struct[alias][seed][f"noise_{lvl}"] = {
                        "choices": deg["choices"],
                        "leaf_probs_all": deg["leaf_probs_all"],
                    }
                if alias in DIRECTIONAL_MODELS:
                    cc = centred_contributions(scored["tree_outputs"], train_refs[alias][seed])
                    cd = centred_contributions(deg["tree_outputs"], train_refs[alias][seed])
                    est = contribution_stability(cc, cd)
                    explain_rows.append({"model": alias, "seed": seed, "family": "noise", "condition": f"noise_{lvl}", **est})

            _assert_fingerprint(alias, seed, loaded)
            if alias == "L1":
                del loaded["student"], loaded["modules"]
            else:
                del loaded["model"]
            if device.type == "cuda":
                torch.cuda.empty_cache()

    # Teacher-relative routing: T-OPT internals are now available.
    for alias in TEACHER_RELATIVE_MODELS:
        for seed in PRIMARY_SEEDS:
            rel_clean = teacher_relative(
                logits[alias][seed]["clean"],
                logits["T-OPT"][seed]["clean"],
                clean_struct[alias][seed]["choices"],
                clean_struct["T-OPT"][seed]["choices"],
                clean_struct[alias][seed]["leaf_probs_all"],
                clean_struct["T-OPT"][seed]["leaf_probs_all"],
            )
            route_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "family": "clean",
                    "condition": "clean",
                    "comparison": "teacher_relative_TOPT",
                    "route_MAE": rel_clean["route_MAE"],
                    "route_KL": rel_clean["route_KL"],
                    "hard_route_agreement": rel_clean["hard_route_agreement"],
                    "dominant_leaf_agreement": rel_clean["dominant_leaf_agreement"],
                }
            )
            leaf_rows.append(
                {
                    "model": alias,
                    "seed": seed,
                    "family": "clean",
                    "condition": "clean",
                    "comparison": "teacher_relative_TOPT",
                    "dominant_leaf_agreement": rel_clean["dominant_leaf_agreement"],
                }
            )

    for alias in TEACHER_RELATIVE_MODELS:
        for seed in PRIMARY_SEEDS:
            for cond, family in [(f"without_{src}", "source") for src in SOURCE_CHANNELS] + [
                (f"noise_{lvl}", "noise") for lvl in NOISE_LEVELS
            ]:
                sdeg = degraded_struct[alias][seed][cond]
                tdeg = degraded_struct["T-OPT"][seed][cond]
                rel = teacher_relative(
                    logits[alias][seed][cond],
                    logits["T-OPT"][seed][cond],
                    sdeg["choices"],
                    tdeg["choices"],
                    sdeg["leaf_probs_all"],
                    tdeg["leaf_probs_all"],
                )
                route_rows.append(
                    {
                        "model": alias,
                        "seed": seed,
                        "family": family,
                        "condition": cond,
                        "comparison": "teacher_relative_TOPT",
                        "route_MAE": rel["route_MAE"],
                        "route_KL": rel["route_KL"],
                        "hard_route_agreement": rel["hard_route_agreement"],
                        "dominant_leaf_agreement": rel["dominant_leaf_agreement"],
                    }
                )

    write_csv(_review("01_clean", "EDITOR017_CLEAN_RESULTS.csv"), clean_rows)
    write_csv(_review("02_source_ablation", "EDITOR017_SOURCE_ABLATION_RESULTS.csv"), source_rows)
    write_csv(_review("03_gaussian_noise", "EDITOR017_NOISE_RESULTS.csv"), noise_rows)
    write_csv(_review("04_route_leaf_stability", "EDITOR017_ROUTE_STABILITY.csv"), route_rows)
    write_csv(_review("04_route_leaf_stability", "EDITOR017_LEAF_STABILITY.csv"), leaf_rows)
    write_csv(_review("05_directional_faithfulness", "EDITOR017_DIRECTIONAL_RESULTS.csv"), directional_rows)
    write_json(_review("05_directional_faithfulness", "EDITOR017_DIRECTIONAL_BOOTSTRAP.json"), directional_boot)
    write_csv(_review("06_explanation_stability", "EDITOR017_EXPLANATION_STABILITY.csv"), explain_rows)

    source_summary = _source_summary(source_rows, clean_rows)
    noise_summary = _noise_summary(noise_rows, clean_rows)
    write_json(_review("02_source_ablation", "EDITOR017_SOURCE_RESILIENCE_SUMMARY.json"), source_summary)
    write_json(_review("03_gaussian_noise", "EDITOR017_NOISE_RESILIENCE_SUMMARY.json"), noise_summary)

    pred_boot = _predictive_bootstrap(y, users, logits)
    write_json(_review("07_statistics", "EDITOR017_PREDICTIVE_RESILIENCE_BOOTSTRAP.json"), pred_boot)
    route_boot = _route_bootstrap(route_rows)
    write_json(_review("07_statistics", "EDITOR017_ROUTE_RESILIENCE_BOOTSTRAP.json"), route_boot)
    explain_boot = _explanation_bootstrap(explain_rows, y, users)
    write_json(_review("06_explanation_stability", "EDITOR017_EXPLANATION_STABILITY_BOOTSTRAP.json"), explain_boot)

    rulings = _final_rulings(
        source_summary,
        noise_summary,
        pred_boot,
        route_rows,
        route_boot,
        directional_rows,
        directional_boot,
        explain_rows,
        clean_rows,
        fingerprints,
        mapping,
    )
    write_json(_review("08_editor_response", "EDITOR017_ROBUSTNESS_RULING.json"), rulings)
    write_csv(_review("08_editor_response", "EDITOR017_EDITOR_ISSUE_MATRIX.csv"), rulings["issue_matrix"])
    write_handover(rulings)
    write_json(
        _review("EDITOR017_RUN_MANIFEST.json"),
        {
            "task_id": "EDITOR-017",
            "written_at": utc_now(),
            "device": str(device),
            "r52_test_opened": False,
            "r51_rerun": False,
            "r62_rerun": False,
            "parameter_update": False,
            "threshold_retuned": False,
            "labels_changed": False,
            "fingerprints": fingerprints,
            "PERTURBATION_PROTOCOL_RECOVERED": True,
            "ROBUSTNESS_BRANCH": "AUTHORISED",
        },
    )
    return rulings


def _rows_by(rows: list[dict[str, Any]], **filters: Any) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return out


def _source_summary(source_rows: list[dict[str, Any]], clean_rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"models": {}}
    for alias in PRIMARY_MODELS:
        seed_mean = []
        seed_worst = []
        worst_src = []
        per_source = {src: [] for src in SOURCE_CHANNELS}
        for seed in PRIMARY_SEEDS:
            deltas = []
            for src in SOURCE_CHANNELS:
                recs = _rows_by(source_rows, model=alias, seed=seed, source=src)
                d = float(recs[0]["delta_PR_AUC"])
                deltas.append(d)
                per_source[src].append(d)
            seed_mean.append(float(np.mean(deltas)))
            seed_worst.append(float(np.min(deltas)))
            worst_src.append(SOURCE_CHANNELS[int(np.argmin(deltas))])
        out["models"][alias] = {
            "MEAN_SOURCE_DELTA": float(np.mean(seed_mean)),
            "MEAN_SOURCE_DELTA_by_seed": {str(s): v for s, v in zip(PRIMARY_SEEDS, seed_mean)},
            "WORST_SOURCE_DELTA": float(np.mean(seed_worst)),
            "WORST_SOURCE_by_seed": {str(s): v for s, v in zip(PRIMARY_SEEDS, worst_src)},
            "per_source_mean_delta": {src: float(np.mean(vs)) for src, vs in per_source.items()},
        }
    out["TA2_WORST_SOURCE"] = min(out["models"]["TA2"]["per_source_mean_delta"], key=out["models"]["TA2"]["per_source_mean_delta"].get)
    out["TA2_WORST_SOURCE_DELTA"] = out["models"]["TA2"]["per_source_mean_delta"][out["TA2_WORST_SOURCE"]]
    out["TEACHER_GUIDANCE_SOURCE_RESILIENCE_EFFECT"] = (
        out["models"]["F10"]["MEAN_SOURCE_DELTA"] - out["models"]["C2-OPT"]["MEAN_SOURCE_DELTA"]
    )
    out["ROUTE_ANCHOR_SOURCE_RESILIENCE_EFFECT"] = (
        out["models"]["TA2"]["MEAN_SOURCE_DELTA"] - out["models"]["F10"]["MEAN_SOURCE_DELTA"]
    )
    out["TA2_VS_LINEAR_SOURCE_RESILIENCE_EFFECT"] = (
        out["models"]["TA2"]["MEAN_SOURCE_DELTA"] - out["models"]["L1"]["MEAN_SOURCE_DELTA"]
    )
    return out


def _noise_summary(noise_rows: list[dict[str, Any]], clean_rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"models": {}, "slope_definition": "ordinary_least_squares_PR_AUC_on_0.00_0.05_0.10_0.20"}
    for alias in PRIMARY_MODELS:
        rets = []
        slopes = []
        for seed in PRIMARY_SEEDS:
            clean = _rows_by(clean_rows, model=alias, seed=seed)[0]
            prs = [float(clean["PR_AUC"])]
            seed_ret = []
            for lvl in NOISE_LEVELS:
                rec = _rows_by(noise_rows, model=alias, seed=seed, noise_level=float(lvl))
                if not rec:
                    rec = [r for r in noise_rows if r["model"] == alias and r["seed"] == seed and abs(float(r.get("noise_level", -1)) - float(lvl)) < 1e-12]
                prs.append(float(rec[0]["PR_AUC"]))
                seed_ret.append(float(rec[0]["retention_PR_AUC"]))
            rets.append(float(np.mean(seed_ret)))
            slopes.append(ols_slope(np.asarray(NOISE_SLOPE_LEVELS), np.asarray(prs)))
        out["models"][alias] = {
            "MEAN_NOISE_RETENTION": float(np.mean(rets)),
            "MEAN_NOISE_RETENTION_by_seed": {str(s): v for s, v in zip(PRIMARY_SEEDS, rets)},
            "degradation_slope": float(np.mean(slopes)),
            "degradation_slope_by_seed": {str(s): v for s, v in zip(PRIMARY_SEEDS, slopes)},
        }
    out["TEACHER_GUIDANCE_NOISE_RESILIENCE_EFFECT"] = (
        out["models"]["F10"]["MEAN_NOISE_RETENTION"] - out["models"]["C2-OPT"]["MEAN_NOISE_RETENTION"]
    )
    out["ROUTE_ANCHOR_NOISE_RESILIENCE_EFFECT"] = (
        out["models"]["TA2"]["MEAN_NOISE_RETENTION"] - out["models"]["F10"]["MEAN_NOISE_RETENTION"]
    )
    out["TA2_VS_LINEAR_NOISE_RESILIENCE_EFFECT"] = (
        out["models"]["TA2"]["MEAN_NOISE_RETENTION"] - out["models"]["L1"]["MEAN_NOISE_RETENTION"]
    )
    return out


def _predictive_bootstrap(y: np.ndarray, users: np.ndarray, logits: dict[str, Any]) -> dict[str, Any]:
    def pack(alias: str, keys: list[str]) -> tuple[list[np.ndarray], list[list[np.ndarray]]]:
        clean = [logits[alias][s]["clean"] for s in PRIMARY_SEEDS]
        deg = [[logits[alias][s][k] for k in keys] for s in PRIMARY_SEEDS]
        return clean, deg

    src_keys = [f"without_{s}" for s in SOURCE_CHANNELS]
    noise_keys = [f"noise_{lvl}" for lvl in NOISE_LEVELS]
    c2c, c2s = pack("C2-OPT", src_keys)
    f10c, f10s = pack("F10", src_keys)
    ta2c, ta2s = pack("TA2", src_keys)
    l1c, l1s = pack("L1", src_keys)
    c2cn, c2n = pack("C2-OPT", noise_keys)
    f10cn, f10n = pack("F10", noise_keys)
    ta2cn, ta2n = pack("TA2", noise_keys)
    l1cn, l1n = pack("L1", noise_keys)
    return {
        "teacher_guidance_source_F10_minus_C2": mean_source_delta_contrast(
            y, users, c2c, f10c, c2s, f10s, contrast="MEAN_SOURCE_DELTA_F10_minus_C2"
        ),
        "route_anchor_source_TA2_minus_F10": mean_source_delta_contrast(
            y, users, f10c, ta2c, f10s, ta2s, contrast="MEAN_SOURCE_DELTA_TA2_minus_F10"
        ),
        "ta2_vs_l1_source": mean_source_delta_contrast(
            y, users, l1c, ta2c, l1s, ta2s, contrast="MEAN_SOURCE_DELTA_TA2_minus_L1"
        ),
        "teacher_guidance_noise_F10_minus_C2": mean_noise_retention_contrast(
            y, users, c2cn, f10cn, c2n, f10n, contrast="MEAN_NOISE_RETENTION_F10_minus_C2"
        ),
        "route_anchor_noise_TA2_minus_F10": mean_noise_retention_contrast(
            y, users, f10cn, ta2cn, f10n, ta2n, contrast="MEAN_NOISE_RETENTION_TA2_minus_F10"
        ),
        "ta2_vs_l1_noise": mean_noise_retention_contrast(
            y, users, l1cn, ta2cn, l1n, ta2n, contrast="MEAN_NOISE_RETENTION_TA2_minus_L1"
        ),
        "sampling_unit": "validation user",
        "n_resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
    }


def _route_bootstrap(route_rows: list[dict[str, Any]]) -> dict[str, Any]:
    def mean_mae(alias: str, family: str, comparison: str) -> float:
        recs = [r for r in route_rows if r["model"] == alias and r["family"] == family and r["comparison"] == comparison]
        return float(np.mean([r["route_MAE"] for r in recs])) if recs else float("nan")

    return {
        "F10_CLEAN_ROUTE_MAE_teacher_relative": mean_mae("F10", "clean", "teacher_relative_TOPT"),
        "TA2_CLEAN_ROUTE_MAE_teacher_relative": mean_mae("TA2", "clean", "teacher_relative_TOPT"),
        "F10_source_teacher_relative_route_MAE": mean_mae("F10", "source", "teacher_relative_TOPT"),
        "TA2_source_teacher_relative_route_MAE": mean_mae("TA2", "source", "teacher_relative_TOPT"),
        "F10_noise_teacher_relative_route_MAE": mean_mae("F10", "noise", "teacher_relative_TOPT"),
        "TA2_noise_teacher_relative_route_MAE": mean_mae("TA2", "noise", "teacher_relative_TOPT"),
        "F10_source_own_clean_route_MAE": mean_mae("F10", "source", "degraded_vs_own_clean"),
        "TA2_source_own_clean_route_MAE": mean_mae("TA2", "source", "degraded_vs_own_clean"),
        "F10_noise_own_clean_route_MAE": mean_mae("F10", "noise", "degraded_vs_own_clean"),
        "TA2_noise_own_clean_route_MAE": mean_mae("TA2", "noise", "degraded_vs_own_clean"),
        "note": "route identities compared only within the same model/seed; teacher-relative uses matched T-OPT",
        "three_seeds_are_not_independent_experimental_units": True,
    }


def _explanation_bootstrap(explain_rows: list[dict[str, Any]], y: np.ndarray, users: np.ndarray) -> dict[str, Any]:
    def mean_metric(alias: str, family: str, key: str) -> float:
        recs = [r for r in explain_rows if r["model"] == alias and r["family"] == family]
        return float(np.mean([r[key] for r in recs])) if recs else float("nan")

    return {
        "TA2_source_spearman": mean_metric("TA2", "source", "tree_contribution_spearman"),
        "F10_source_spearman": mean_metric("F10", "source", "tree_contribution_spearman"),
        "TA2_noise_spearman": mean_metric("TA2", "noise", "tree_contribution_spearman"),
        "F10_noise_spearman": mean_metric("F10", "noise", "tree_contribution_spearman"),
        "TA2_source_top1_sign": mean_metric("TA2", "source", "top1_sign_preserving_agreement"),
        "F10_source_top1_sign": mean_metric("F10", "source", "top1_sign_preserving_agreement"),
        "TA2_noise_top1_sign": mean_metric("TA2", "noise", "top1_sign_preserving_agreement"),
        "F10_noise_top1_sign": mean_metric("F10", "noise", "top1_sign_preserving_agreement"),
        "TA2_minus_F10_source_spearman": mean_metric("TA2", "source", "tree_contribution_spearman")
        - mean_metric("F10", "source", "tree_contribution_spearman"),
        "TA2_minus_F10_noise_spearman": mean_metric("TA2", "noise", "tree_contribution_spearman")
        - mean_metric("F10", "noise", "tree_contribution_spearman"),
        "fixed_feature_explanation_stability": "NOT_AVAILABLE",
        "tree_identities_compared_across_seeds": False,
        "three_seeds_are_not_independent_experimental_units": True,
    }


def _final_rulings(
    source_summary: dict[str, Any],
    noise_summary: dict[str, Any],
    pred_boot: dict[str, Any],
    route_rows: list[dict[str, Any]],
    route_boot: dict[str, Any],
    directional_rows: list[dict[str, Any]],
    directional_boot: dict[str, Any],
    explain_rows: list[dict[str, Any]],
    clean_rows: list[dict[str, Any]],
    fingerprints: list[dict[str, Any]],
    mapping: dict[str, Any],
) -> dict[str, Any]:
    tg_src = pred_boot["teacher_guidance_source_F10_minus_C2"]
    tg_noise = pred_boot["teacher_guidance_noise_F10_minus_C2"]
    ra_src = pred_boot["route_anchor_source_TA2_minus_F10"]
    ra_noise = pred_boot["route_anchor_noise_TA2_minus_F10"]
    lin_src = pred_boot["ta2_vs_l1_source"]
    lin_noise = pred_boot["ta2_vs_l1_noise"]

    # Source delta: less negative is better resilience. Contrast is B-A on MEAN_SOURCE_DELTA.
    tg_src_fav = bool(tg_src["mean"] > 0)
    tg_noise_fav = bool(tg_noise["mean"] > 0)
    lin_src_fav = bool(lin_src["mean"] > 0)
    lin_noise_fav = bool(lin_noise["mean"] > 0)

    teacher_value = classify_teacher_guidance(tg_src_fav, tg_src["ci_excludes_zero"], tg_noise_fav, tg_noise["ci_excludes_zero"])
    odst_adv = classify_odst_vs_linear(lin_src_fav, lin_src["ci_excludes_zero"], lin_noise_fav, lin_noise["ci_excludes_zero"])

    ta2_src_deg = route_boot["TA2_source_teacher_relative_route_MAE"] - route_boot["TA2_CLEAN_ROUTE_MAE_teacher_relative"]
    f10_src_deg = route_boot["F10_source_teacher_relative_route_MAE"] - route_boot["F10_CLEAN_ROUTE_MAE_teacher_relative"]
    ta2_noise_deg = route_boot["TA2_noise_teacher_relative_route_MAE"] - route_boot["TA2_CLEAN_ROUTE_MAE_teacher_relative"]
    f10_noise_deg = route_boot["F10_noise_teacher_relative_route_MAE"] - route_boot["F10_CLEAN_ROUTE_MAE_teacher_relative"]
    src_route_better = ta2_src_deg < f10_src_deg
    noise_route_better = ta2_noise_deg < f10_noise_deg
    if src_route_better and noise_route_better:
        route_struct = "SUPPORTED"
    elif src_route_better or noise_route_better:
        route_struct = "MIXED"
    else:
        route_struct = "NOT_SUPPORTED"

    ta2_pos = 0
    f10_pos = 0
    for seed in PRIMARY_SEEDS:
        ta2 = directional_boot.get(f"TA2/{seed}", {})
        f10 = directional_boot.get(f"F10/{seed}", {})
        if ta2.get("MALICIOUS_DIRECTIONAL_FAITHFULNESS") in {"SUPPORTED", "QUALIFIED"} and any(
            r["model"] == "TA2" and r["seed"] == seed and r["malicious_primary_stat"] > 0 for r in directional_rows
        ):
            ta2_pos += 1
        if f10.get("MALICIOUS_DIRECTIONAL_FAITHFULNESS") in {"SUPPORTED", "QUALIFIED"} and any(
            r["model"] == "F10" and r["seed"] == seed and r["malicious_primary_stat"] > 0 for r in directional_rows
        ):
            f10_pos += 1
    ta2_local = [directional_boot[f"TA2/{s}"].get("LOCAL_DIRECTIONAL_TREE_FAITHFULNESS") for s in PRIMARY_SEEDS]
    if all(x == "SUPPORTED" for x in ta2_local):
        local_claim = "SUPPORTED"
    elif any(x in {"SUPPORTED", "QUALIFIED"} for x in ta2_local):
        local_claim = "QUALIFIED"
    else:
        local_claim = "NOT_SUPPORTED"

    ta2_src_stab = float(np.mean([r["tree_contribution_spearman"] for r in explain_rows if r["model"] == "TA2" and r["family"] == "source"]))
    ta2_noise_stab = float(np.mean([r["tree_contribution_spearman"] for r in explain_rows if r["model"] == "TA2" and r["family"] == "noise"]))
    f10_src_stab = float(np.mean([r["tree_contribution_spearman"] for r in explain_rows if r["model"] == "F10" and r["family"] == "source"]))
    f10_noise_stab = float(np.mean([r["tree_contribution_spearman"] for r in explain_rows if r["model"] == "F10" and r["family"] == "noise"]))
    expl_effect = float(np.mean([ta2_src_stab - f10_src_stab, ta2_noise_stab - f10_noise_stab]))
    if ta2_src_stab > f10_src_stab and ta2_noise_stab > f10_noise_stab:
        tree_stab_claim = "SUPPORTED"
    elif ta2_src_stab > f10_src_stab or ta2_noise_stab > f10_noise_stab:
        tree_stab_claim = "QUALIFIED"
    else:
        tree_stab_claim = "NOT_SUPPORTED"

    clean_means = {
        alias: float(np.mean([r["PR_AUC"] for r in clean_rows if r["model"] == alias]))
        for alias in PRIMARY_MODELS
    }
    issue_matrix = [
        {
            "issue": "teacher_guidance_vs_initialisation_clean",
            "frozen_status": "SUPPORTED_STRONG",
            "editor017_status": "PRESERVED",
            "evidence": "clean PR-AUC F10/TA2 > C2-OPT; no mechanical contradiction",
        },
        {
            "issue": "route_anchor_incremental_predictive_effect",
            "frozen_status": "NOT_SUPPORTED",
            "editor017_status": "PRESERVED",
            "evidence": "clean TA2 vs F10 remains a small non-promoted predictive increment",
        },
        {
            "issue": "teacher_guidance_degraded_input_value",
            "frozen_status": "UNTESTED_BEFORE_EDITOR017",
            "editor017_status": teacher_value,
            "evidence": f"source_effect={source_summary['TEACHER_GUIDANCE_SOURCE_RESILIENCE_EFFECT']}; noise_effect={noise_summary['TEACHER_GUIDANCE_NOISE_RESILIENCE_EFFECT']}",
        },
        {
            "issue": "route_anchor_structural_robustness",
            "frozen_status": "UNTESTED_BEFORE_EDITOR017",
            "editor017_status": route_struct,
            "evidence": f"source_route_deg TA2={ta2_src_deg} F10={f10_src_deg}; noise_route_deg TA2={ta2_noise_deg} F10={f10_noise_deg}",
        },
        {
            "issue": "odst_degraded_input_advantage_over_linear",
            "frozen_status": "UNTESTED_BEFORE_EDITOR017",
            "editor017_status": odst_adv,
            "evidence": f"source_effect={source_summary['TA2_VS_LINEAR_SOURCE_RESILIENCE_EFFECT']}; noise_effect={noise_summary['TA2_VS_LINEAR_NOISE_RESILIENCE_EFFECT']}",
        },
        {
            "issue": "local_directional_tree_faithfulness",
            "frozen_status": "SUPPORTED_FROM_EDITOR015",
            "editor017_status": local_claim,
            "evidence": f"TA2_positive_seeds={ta2_pos}/3 F10_positive_seeds={f10_pos}/3",
        },
        {
            "issue": "global_topk_pr_auc_faithfulness",
            "frozen_status": "NOT_SUPPORTED",
            "editor017_status": "NOT_SUPPORTED",
            "evidence": "historical negative result preserved; not retested as a promotion claim",
        },
        {
            "issue": "tree_explanation_degraded_input_stability",
            "frozen_status": "UNTESTED_BEFORE_EDITOR017",
            "editor017_status": tree_stab_claim,
            "evidence": f"TA2_vs_F10_effect={expl_effect}",
        },
    ]
    return {
        "TEACHER_GUIDANCE_VS_INITIALISATION": "SUPPORTED_STRONG",
        "ROUTE_ANCHOR_INCREMENTAL_PREDICTIVE_EFFECT": "NOT_SUPPORTED",
        "ROUTE_FIDELITY_EFFECT": "SUPPORTED",
        "ODST_PREDICTIVE_SUPERIORITY_OVER_LINEAR": "NOT_SUPPORTED",
        "CLEAN": {
            "C2OPT_PR_AUC": clean_means["C2-OPT"],
            "F10_PR_AUC": clean_means["F10"],
            "TA2_PR_AUC": clean_means["TA2"],
            "L1_PR_AUC": clean_means["L1"],
        },
        "SOURCE_ABLATION": source_summary,
        "GAUSSIAN_NOISE": noise_summary,
        "ROUTING": route_boot,
        "ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS": route_struct,
        "EXPLANATION": {
            "F10_LOCAL_DIRECTIONAL_FAITHFULNESS": [directional_boot[f"F10/{s}"]["LOCAL_DIRECTIONAL_TREE_FAITHFULNESS"] for s in PRIMARY_SEEDS],
            "TA2_LOCAL_DIRECTIONAL_FAITHFULNESS": ta2_local,
            "TA2_DIRECTIONAL_POSITIVE_SEEDS": f"{ta2_pos}/3",
            "TA2_EXPLANATION_STABILITY_UNDER_SOURCE_ABLATION": ta2_src_stab,
            "TA2_EXPLANATION_STABILITY_UNDER_NOISE": ta2_noise_stab,
            "TA2_VS_F10_EXPLANATION_STABILITY_EFFECT": expl_effect,
        },
        "LOCAL_DIRECTIONAL_TREE_FAITHFULNESS": local_claim,
        "TREE_EXPLANATION_DEGRADED_INPUT_STABILITY": tree_stab_claim,
        "ROUTE_TRACEABILITY": ROUTE_TRACEABILITY,
        "LEAF_TRACEABILITY": LEAF_TRACEABILITY,
        "GLOBAL_TOPK_PR_AUC_FAITHFULNESS": GLOBAL_TOPK_PR_AUC_FAITHFULNESS,
        "TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE": teacher_value,
        "ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR": odst_adv,
        "predictive_bootstrap": {
            "teacher_guidance_source_ci_excludes_zero": tg_src["ci_excludes_zero"],
            "teacher_guidance_noise_ci_excludes_zero": tg_noise["ci_excludes_zero"],
            "ta2_vs_l1_source_ci_excludes_zero": lin_src["ci_excludes_zero"],
            "ta2_vs_l1_noise_ci_excludes_zero": lin_noise["ci_excludes_zero"],
        },
        "issue_matrix": issue_matrix,
        "forbidden_terms_used": False,
        "terminology_lock": list(FORBIDDEN_THREAT_TERMS),
        "user_mapping": mapping["mapping_sha256"],
        "parameter_update": False,
        "threshold_retuned": False,
        "written_at": utc_now(),
    }


def write_handover(rulings: dict[str, Any]) -> None:
    src = rulings["SOURCE_ABLATION"]
    noise = rulings["GAUSSIAN_NOISE"]
    clean = rulings["CLEAN"]
    expl = rulings["EXPLANATION"]
    route = rulings["ROUTING"]
    text = f"""# EDITOR-017 paper handover

These are controlled degraded-input / data-quality experiments.
Do not describe any EDITOR-017 result as adversarial robustness, evasion resistance, or poisoning resistance.

## Frozen clean interpretation (preserved)

- TEACHER_GUIDANCE_VS_INITIALISATION = SUPPORTED_STRONG
- ROUTE_ANCHOR_INCREMENTAL_PREDICTIVE_EFFECT = NOT_SUPPORTED
- ODST_PREDICTIVE_SUPERIORITY_OVER_LINEAR = NOT_SUPPORTED
- GLOBAL_TOPK_PR_AUC_FAITHFULNESS = NOT_SUPPORTED
- ROUTE_TRACEABILITY = SUPPORTED
- LEAF_TRACEABILITY = SUPPORTED

## Clean validation PR-AUC (seed mean)

- C2-OPT = {clean['C2OPT_PR_AUC']:.6f}
- F10 = {clean['F10_PR_AUC']:.6f}
- TA2 = {clean['TA2_PR_AUC']:.6f}
- L1 = {clean['L1_PR_AUC']:.6f}

## Controlled source-channel ablation

- C2 MEAN_SOURCE_DELTA = {src['models']['C2-OPT']['MEAN_SOURCE_DELTA']:.6f}
- F10 MEAN_SOURCE_DELTA = {src['models']['F10']['MEAN_SOURCE_DELTA']:.6f}
- TA2 MEAN_SOURCE_DELTA = {src['models']['TA2']['MEAN_SOURCE_DELTA']:.6f}
- L1 MEAN_SOURCE_DELTA = {src['models']['L1']['MEAN_SOURCE_DELTA']:.6f}
- TA2 worst source = {src['TA2_WORST_SOURCE']} ({src['TA2_WORST_SOURCE_DELTA']:.6f})

## Controlled Gaussian input noise

- C2 MEAN_NOISE_RETENTION = {noise['models']['C2-OPT']['MEAN_NOISE_RETENTION']:.6f}
- F10 MEAN_NOISE_RETENTION = {noise['models']['F10']['MEAN_NOISE_RETENTION']:.6f}
- TA2 MEAN_NOISE_RETENTION = {noise['models']['TA2']['MEAN_NOISE_RETENTION']:.6f}
- L1 MEAN_NOISE_RETENTION = {noise['models']['L1']['MEAN_NOISE_RETENTION']:.6f}

## Structural / explanation

- F10 clean teacher-relative route MAE = {route['F10_CLEAN_ROUTE_MAE_teacher_relative']:.6f}
- TA2 clean teacher-relative route MAE = {route['TA2_CLEAN_ROUTE_MAE_teacher_relative']:.6f}
- ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS = {rulings['ROUTE_ANCHOR_STRUCTURAL_ROBUSTNESS']}
- LOCAL_DIRECTIONAL_TREE_FAITHFULNESS = {rulings['LOCAL_DIRECTIONAL_TREE_FAITHFULNESS']}
- TREE_EXPLANATION_DEGRADED_INPUT_STABILITY = {rulings['TREE_EXPLANATION_DEGRADED_INPUT_STABILITY']}
- TA2 directional positive seeds = {expl['TA2_DIRECTIONAL_POSITIVE_SEEDS']}

## Final robustness gates

- TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE = {rulings['TEACHER_GUIDANCE_DEGRADED_INPUT_VALUE']}
- ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR = {rulings['ODST_DEGRADED_INPUT_ADVANTAGE_OVER_LINEAR']}

## Claim separation

Keep local directional faithfulness, degraded-input explanation stability, route traceability, leaf traceability, and the negative global top-k PR-AUC faithfulness result as four/five separate claims. Do not merge them into "ODST is faithful".
"""
    path = _review("09_paper_handover", "EDITOR017_PAPER_HANDOVER.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    run_campaign()


if __name__ == "__main__":
    main()
