#!/usr/bin/env python
"""Forward-pass temporal-value and partial-history evaluation (no training)."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from objective2_temporal_value_analysis.constants import (  # noqa: E402
    BATCH_SIZE,
    CLEAN_F1_ATOL,
    CLEAN_PR_AUC_ATOL,
    ORDER_PR_AUC_DROP_MARGIN,
    OUTPUT_REL,
    R42_OPTIONAL,
    R42_TRAIN_REL,
    R42_VAL_REL,
    R52_STUDENTS,
    R52_TRAIN_REL,
    R52_VAL_REL,
    SHUFFLE_SEED,
    T0_T6_PROB_ATOL,
)
from objective2_temporal_value_analysis.eval import (  # noqa: E402
    assert_no_training_hooks,
    load_student,
    load_npz,
    predict_probs,
    score_condition,
    sha256_file,
    state_dict_sha256,
)
from objective2_temporal_value_analysis.reports import make_figures, write_reports  # noqa: E402
from objective2_temporal_value_analysis.safety import (  # noqa: E402
    ProtectedDataAccessError,
    assert_output_namespace,
    assert_path_allowed_for_read,
    refuse_test_loader,
)
from objective2_temporal_value_analysis.transforms import (  # noqa: E402
    apply_condition,
    condition_metadata,
    fixed_shuffle_permutation,
    train_feature_medians,
)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    assert_output_namespace(path)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in keys})


def classify_status(
    *,
    clean_parity_ok: bool,
    safety_failure: bool,
    incomplete: bool,
    order_advantage: bool,
) -> str:
    if safety_failure:
        return "objective2_temporal_value_stopped_safety_failure"
    if not clean_parity_ok:
        return "objective2_temporal_value_blocked_clean_parity"
    if incomplete:
        return "objective2_temporal_value_incomplete"
    if order_advantage:
        return "objective2_temporal_value_complete"
    return "objective2_temporal_value_complete_no_order_advantage"


def run_seed_conditions(
    *,
    root: Path,
    dataset: str,
    seed: int,
    ckpt: Path,
    threshold: float,
    expected: dict[str, Any] | None,
    conditions: tuple[str, ...],
    X_val: np.ndarray,
    y_val: np.ndarray,
    medians: np.ndarray,
    perm: np.ndarray,
    device: torch.device,
) -> dict[str, Any]:
    model, load_info, ckpt_sha = load_student(ckpt, device)
    assert_no_training_hooks(model)
    state0 = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    hash0 = state_dict_sha256(state0)

    results: dict[str, dict[str, Any]] = {}
    # Always need T0 clean first among requested (or compute for parity)
    need = list(conditions)
    if "T0" not in need:
        need = ["T0"] + need

    for cid in need:
        Xc = apply_condition(X_val, condition=cid, perm=perm, medians=medians)
        probs = predict_probs(model, Xc, device, batch_size=BATCH_SIZE)
        results[cid] = {"probs": probs}

    # Parameter integrity after all forwards
    hash1 = state_dict_sha256(model.state_dict())
    if hash0 != hash1:
        raise RuntimeError("Model parameters changed during forward-only evaluation")

    clean_probs = results["T0"]["probs"]
    clean_pred = (clean_probs >= threshold).astype(int)
    clean_metrics = score_condition(y_val, clean_probs, threshold, clean_probs, clean_pred)

    parity = {
        "dataset": dataset,
        "seed": seed,
        "checkpoint": str(ckpt),
        "checkpoint_sha256": ckpt_sha,
        "expected_sha256": expected.get("expected_sha256") if expected else "",
        "hash_ok": (ckpt_sha == expected["expected_sha256"]) if expected and "expected_sha256" in expected else True,
        "threshold": threshold,
        "clean_pr_auc": clean_metrics["pr_auc"],
        "clean_f1": clean_metrics["f1"],
        "clean_fp": clean_metrics["fp"],
        "clean_fn": clean_metrics["fn"],
        "expected_pr_auc": expected.get("expected_pr_auc") if expected else "",
        "expected_f1": expected.get("expected_f1") if expected else "",
        "pr_auc_ok": True,
        "f1_ok": True,
        "param_hash_before": hash0,
        "param_hash_after": hash1,
        "params_unchanged": hash0 == hash1,
        "requires_grad_any": any(p.requires_grad for p in model.parameters()),
        "load_missing_keys": len(load_info.get("missing_keys") or []),
    }
    if expected and "expected_pr_auc" in expected:
        parity["pr_auc_ok"] = abs(clean_metrics["pr_auc"] - float(expected["expected_pr_auc"])) <= CLEAN_PR_AUC_ATOL
        parity["f1_ok"] = abs(clean_metrics["f1"] - float(expected["expected_f1"])) <= CLEAN_F1_ATOL
        if "expected_fp" in expected:
            parity["fp_ok"] = int(clean_metrics["fp"]) == int(expected["expected_fp"])
            parity["fn_ok"] = int(clean_metrics["fn"]) == int(expected["expected_fn"])

    # T0 vs T6 parity if both present
    t0_t6 = {}
    if "T6" in results:
        d = np.abs(results["T0"]["probs"] - results["T6"]["probs"]).max()
        t0_t6 = {
            "t0_t6_max_abs_prob_diff": float(d),
            "t0_t6_parity_ok": bool(d <= T0_T6_PROB_ATOL),
        }
        parity.update(t0_t6)

    scored = {}
    for cid in conditions:
        scored[cid] = score_condition(
            y_val, results[cid]["probs"], threshold, clean_probs, clean_pred
        )
        scored[cid]["condition"] = cid

    return {
        "parity": parity,
        "scored": scored,
        "clean_probs": clean_probs,
        "clean_pred": clean_pred,
        "all_probs": {k: v["probs"] for k, v in results.items()},
        "threshold": threshold,
        "ckpt_sha": ckpt_sha,
    }


def partial_history_rows(
    *,
    dataset: str,
    seed: int,
    y: np.ndarray,
    scored: dict[str, dict[str, Any]],
    threshold: float,
) -> list[dict[str, Any]]:
    """Per-sample first threshold crossing across history lengths 1/5/10/20."""
    if not all(c in scored for c in ("T3", "T4", "T5", "T6")):
        return []
    rows = []
    hist_map = [("T3", 1), ("T4", 5), ("T5", 10), ("T6", 20)]
    n = len(y)
    for i in range(n):
        first = None
        for cid, h in hist_map:
            if scored[cid]["pred"][i] == 1:
                first = h
                break
        rows.append(
            {
                "dataset": dataset,
                "seed": seed,
                "index": i,
                "y_true": int(y[i]),
                "clean_prob_T6": float(scored["T6"]["probs"][i]),
                "prob_1d": float(scored["T3"]["probs"][i]),
                "prob_5d": float(scored["T4"]["probs"][i]),
                "prob_10d": float(scored["T5"]["probs"][i]),
                "prob_20d": float(scored["T6"]["probs"][i]),
                "alert_1d": int(scored["T3"]["pred"][i]),
                "alert_5d": int(scored["T4"]["pred"][i]),
                "alert_10d": int(scored["T5"]["pred"][i]),
                "alert_20d": int(scored["T6"]["pred"][i]),
                "first_alert_history_days": first if first is not None else "",
                "threshold": threshold,
                "interpretation": "partial_history_detection_not_calendar_lead_time",
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--skip-r42", action="store_true")
    args = parser.parse_args()
    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    out_dir = assert_output_namespace(root / OUTPUT_REL)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.device == "cpu":
        device = torch.device("cpu")
    elif args.device == "cuda":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    start_head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    branch = subprocess.check_output(["git", "-C", str(root), "branch", "--show-current"], text=True).strip()

    perm = fixed_shuffle_permutation()
    cfg = {
        "study": "temporal_value_analysis_v1",
        "forward_pass_only": True,
        "shuffle_seed": SHUFFLE_SEED,
        "permutation": perm.tolist(),
        "seeds": {str(k): v for k, v in R52_STUDENTS.items()},
        "r42_optional": R42_OPTIONAL,
        "order_pr_auc_drop_margin": ORDER_PR_AUC_DROP_MARGIN,
        "clean_pr_auc_atol": CLEAN_PR_AUC_ATOL,
        "output_namespace": str(OUTPUT_REL).replace("\\", "/"),
        "device": str(device),
    }
    (out_dir / "temporal_value_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _write_csv(out_dir / "temporal_value_conditions.csv", condition_metadata(perm))

    try:
        refuse_test_loader("validation")
        refuse_test_loader("train")
        train_path = root / R52_TRAIN_REL
        val_path = root / R52_VAL_REL
        assert_path_allowed_for_read(train_path)
        assert_path_allowed_for_read(val_path)
        # Hash train/val without opening test
        train_sha = sha256_file(train_path)
        val_sha = sha256_file(val_path)
        train = load_npz(train_path)
        val = load_npz(val_path)
        medians = train_feature_medians(train["X"])
        # Confirm medians from train only
        assert medians.shape == (13,)

        parity_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []
        agree_rows: list[dict[str, Any]] = []
        seed_compare_rows: list[dict[str, Any]] = []
        ph_rows: list[dict[str, Any]] = []
        seed_bundle: dict[int, dict[str, Any]] = {}

        for seed, meta in R52_STUDENTS.items():
            ckpt = root / meta["relative_ckpt"]
            if not ckpt.is_file():
                raise FileNotFoundError(ckpt)
            got = sha256_file(ckpt)
            if got != meta["expected_sha256"]:
                raise RuntimeError(f"Checkpoint hash mismatch seed={seed}: {got}")
            print(f"[temporal] r52 seed={seed} conditions={meta['conditions']} device={device}", flush=True)
            bundle = run_seed_conditions(
                root=root,
                dataset="r52",
                seed=seed,
                ckpt=ckpt,
                threshold=float(meta["threshold"]),
                expected=meta,
                conditions=tuple(meta["conditions"]),
                X_val=val["X"],
                y_val=val["y"],
                medians=medians,
                perm=perm,
                device=device,
            )
            seed_bundle[seed] = bundle
            parity_rows.append(bundle["parity"])
            for cid, sc in bundle["scored"].items():
                metric_rows.append(
                    {
                        "dataset": "r52",
                        "seed": seed,
                        "condition": cid,
                        "threshold": meta["threshold"],
                        "pr_auc": sc["pr_auc"],
                        "precision": sc["precision"],
                        "recall": sc["recall"],
                        "f1": sc["f1"],
                        "fp": sc["fp"],
                        "fn": sc["fn"],
                        "tp": sc["tp"],
                        "tn": sc["tn"],
                        "prediction_agreement_with_clean": sc["prediction_agreement_with_clean"],
                        "mean_abs_score_change": sc["mean_abs_score_change"],
                        "malicious_mean_score_change": sc["malicious_mean_score_change"],
                        "normal_mean_score_change": sc["normal_mean_score_change"],
                        "n_malicious_detected": sc["n_malicious_detected"],
                        "n_malicious": sc["n_malicious"],
                        "malicious_detection_rate": sc["malicious_detection_rate"],
                        "history_days": {"T3": 1, "T4": 5, "T5": 10, "T0": 20, "T1": 20, "T2": 20, "T6": 20}[cid],
                    }
                )
                agree_rows.append(
                    {
                        "dataset": "r52",
                        "seed": seed,
                        "condition": cid,
                        "prediction_agreement_with_clean": sc["prediction_agreement_with_clean"],
                        "mean_abs_score_change": sc["mean_abs_score_change"],
                        "malicious_mean_score_change": sc["malicious_mean_score_change"],
                        "normal_mean_score_change": sc["normal_mean_score_change"],
                    }
                )
            ph_rows.extend(
                partial_history_rows(
                    dataset="r52",
                    seed=seed,
                    y=val["y"],
                    scored=bundle["scored"],
                    threshold=float(meta["threshold"]),
                )
            )

        # Optional r4.2 seed 42 original vs shuffled
        r42_done = False
        if not args.skip_r42:
            r42_ckpt = root / R42_OPTIONAL["relative_ckpt"]
            r42_train_p = root / R42_TRAIN_REL
            r42_val_p = root / R42_VAL_REL
            if r42_ckpt.is_file() and r42_train_p.is_file() and r42_val_p.is_file():
                print("[temporal] optional r4.2 seed42 T0/T2", flush=True)
                r42_train = load_npz(r42_train_p)
                r42_val = load_npz(r42_val_p)
                r42_med = train_feature_medians(r42_train["X"])
                # threshold from seed summary if available
                summary = root / "outputs/objective2/teacher_anchored_odst/seed42/seed_summary.json"
                thr = 0.5
                exp = None
                if summary.is_file():
                    s42 = json.loads(summary.read_text(encoding="utf-8"))
                    thr = float(s42.get("best_threshold", 0.5))
                    exp = {
                        "expected_pr_auc": s42.get("best_pr_auc"),
                        "expected_f1": s42.get("best_f1"),
                        "expected_sha256": sha256_file(r42_ckpt),  # self-hash ok for optional
                    }
                    # For optional, hash_ok compares to itself — record actual hash only
                    exp["expected_sha256"] = sha256_file(r42_ckpt)
                bundle = run_seed_conditions(
                    root=root,
                    dataset="r42",
                    seed=42,
                    ckpt=r42_ckpt,
                    threshold=thr,
                    expected=exp,
                    conditions=tuple(R42_OPTIONAL["conditions"]),
                    X_val=r42_val["X"],
                    y_val=r42_val["y"],
                    medians=r42_med,
                    perm=perm,
                    device=device,
                )
                parity_rows.append(bundle["parity"])
                for cid, sc in bundle["scored"].items():
                    metric_rows.append(
                        {
                            "dataset": "r42",
                            "seed": 42,
                            "condition": cid,
                            "threshold": thr,
                            "pr_auc": sc["pr_auc"],
                            "precision": sc["precision"],
                            "recall": sc["recall"],
                            "f1": sc["f1"],
                            "fp": sc["fp"],
                            "fn": sc["fn"],
                            "tp": sc["tp"],
                            "tn": sc["tn"],
                            "prediction_agreement_with_clean": sc["prediction_agreement_with_clean"],
                            "mean_abs_score_change": sc["mean_abs_score_change"],
                            "malicious_mean_score_change": sc["malicious_mean_score_change"],
                            "normal_mean_score_change": sc["normal_mean_score_change"],
                            "n_malicious_detected": sc["n_malicious_detected"],
                            "n_malicious": sc["n_malicious"],
                            "malicious_detection_rate": sc["malicious_detection_rate"],
                            "history_days": 20,
                        }
                    )
                r42_done = True
                seed_compare_rows.append(
                    {
                        "comparison": "r42_vs_r52_seed42_original_vs_shuffled",
                        "r42_T0_pr_auc": bundle["scored"]["T0"]["pr_auc"],
                        "r42_T2_pr_auc": bundle["scored"]["T2"]["pr_auc"],
                        "r42_delta_T0_minus_T2": bundle["scored"]["T0"]["pr_auc"] - bundle["scored"]["T2"]["pr_auc"],
                        "r52_T0_pr_auc": seed_bundle[42]["scored"]["T0"]["pr_auc"],
                        "r52_T2_pr_auc": seed_bundle[42]["scored"]["T2"]["pr_auc"],
                        "r52_delta_T0_minus_T2": seed_bundle[42]["scored"]["T0"]["pr_auc"]
                        - seed_bundle[42]["scored"]["T2"]["pr_auc"],
                    }
                )

        # Seed 42 vs 62 comparison on shared conditions
        shared = ("T0", "T2", "T4", "T6")
        for cid in shared:
            seed_compare_rows.append(
                {
                    "comparison": "r52_seed42_vs_seed62",
                    "condition": cid,
                    "seed42_pr_auc": seed_bundle[42]["scored"][cid]["pr_auc"],
                    "seed62_pr_auc": seed_bundle[62]["scored"][cid]["pr_auc"],
                    "seed42_f1": seed_bundle[42]["scored"][cid]["f1"],
                    "seed62_f1": seed_bundle[62]["scored"][cid]["f1"],
                    "seed42_agreement": seed_bundle[42]["scored"][cid]["prediction_agreement_with_clean"],
                    "seed62_agreement": seed_bundle[62]["scored"][cid]["prediction_agreement_with_clean"],
                }
            )

        clean_parity_ok = all(
            bool(r.get("pr_auc_ok", True))
            and bool(r.get("f1_ok", True))
            and bool(r.get("hash_ok", True))
            and bool(r.get("params_unchanged", True))
            and not r.get("requires_grad_any", False)
            and bool(r.get("t0_t6_parity_ok", True))
            for r in parity_rows
            if r.get("dataset") == "r52"
        )

        s42 = seed_bundle[42]["scored"]
        d1 = float(s42["T0"]["pr_auc"] - s42["T1"]["pr_auc"])
        d2 = float(s42["T0"]["pr_auc"] - s42["T2"]["pr_auc"])
        order_advantage = bool(d1 >= ORDER_PR_AUC_DROP_MARGIN or d2 >= ORDER_PR_AUC_DROP_MARGIN)
        if order_advantage:
            interpretation = (
                "Chronological order contributes measurable predictive value on r5.2 validation seed 42 "
                f"(ΔPR-AUC T0−T1={d1:.4f}, T0−T2={d2:.4f}; margin={ORDER_PR_AUC_DROP_MARGIN})."
            )
        else:
            interpretation = (
                "On r5.2 validation seed 42 the model is largely order-insensitive under reverse and fixed shuffle "
                f"(ΔPR-AUC T0−T1={d1:.4f}, T0−T2={d2:.4f}; both below margin {ORDER_PR_AUC_DROP_MARGIN})."
            )
        order_summary = {
            "order_advantage": order_advantage,
            "delta_pr_t1": d1,
            "delta_pr_t2": d2,
            "interpretation": interpretation,
        }

        timing_note = (
            "Validation tensors provide sequence-level start_date/end_date and labels, but not day-level "
            "incident boundaries inside the 20-day window. Therefore early_warning_analysis.csv is omitted "
            "and threshold crossings are reported as partial-history detection only."
        )

        status = classify_status(
            clean_parity_ok=clean_parity_ok,
            safety_failure=False,
            incomplete=False,
            order_advantage=order_advantage,
        )

        _write_csv(out_dir / "temporal_value_clean_parity.csv", parity_rows)
        _write_csv(out_dir / "temporal_value_metrics.csv", metric_rows)
        _write_csv(out_dir / "temporal_value_prediction_agreement.csv", agree_rows)
        _write_csv(out_dir / "temporal_value_seed_comparison.csv", seed_compare_rows)
        if ph_rows:
            # Aggregate summary + keep a compact malicious-only detail for figures
            mal = [r for r in ph_rows if r["y_true"] == 1]
            # Write full malicious partial-history table (728 rows) — manageable
            _write_csv(out_dir / "partial_history_detection.csv", mal)
            # Crossing summary
            cross_summary = []
            for seed in (42, 62):
                sub = [r for r in mal if r["seed"] == seed]
                if not sub:
                    continue
                for h in (1, 5, 10, 20):
                    n_first = sum(1 for r in sub if r["first_alert_history_days"] == h)
                    cross_summary.append(
                        {
                            "seed": seed,
                            "first_alert_history_days": h,
                            "n_malicious_first_cross": n_first,
                            "proportion": n_first / max(len(sub), 1),
                        }
                    )
                n_never = sum(1 for r in sub if r["first_alert_history_days"] == "")
                cross_summary.append(
                    {
                        "seed": seed,
                        "first_alert_history_days": "never",
                        "n_malicious_first_cross": n_never,
                        "proportion": n_never / max(len(sub), 1),
                    }
                )
            _write_csv(out_dir / "partial_history_crossing_summary.csv", cross_summary)

        # Explicitly do not write early_warning_analysis.csv
        (out_dir / "EARLY_WARNING_METADATA_NOTE.md").write_text(
            timing_note + "\n", encoding="utf-8"
        )

        metrics_df = pd.DataFrame(metric_rows)
        make_figures(out_dir, metrics_df)
        write_reports(
            out_dir,
            status=status,
            meta={"worktree": str(root), "branch": branch, "head": start_head},
            order_summary=order_summary,
            timing_note=timing_note,
        )

        # Snapshot medians for audit
        np.save(out_dir / "train_feature_medians.npy", medians)
        (out_dir / "train_feature_medians.json").write_text(
            json.dumps({"medians": medians.tolist(), "source": str(R52_TRAIN_REL).replace("\\", "/")}, indent=2),
            encoding="utf-8",
        )

        manifest = {
            "status": status,
            "forward_pass_only": True,
            "device": str(device),
            "branch": branch,
            "head": start_head,
            "train_sha256": train_sha,
            "val_sha256": val_sha,
            "shuffle_seed": SHUFFLE_SEED,
            "permutation": perm.tolist(),
            "clean_parity_ok": clean_parity_ok,
            "order_advantage": order_advantage,
            "order_summary": order_summary,
            "r42_optional_executed": r42_done,
            "early_warning_analysis_written": False,
            "r52_test_accessed": False,
            "seeds_executed": sorted(seed_bundle.keys()),
            "output_dir": str(out_dir),
        }
        (out_dir / "temporal_value_manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(manifest, indent=2, default=str))

    except ProtectedDataAccessError as exc:
        status = "objective2_temporal_value_stopped_safety_failure"
        manifest = {"status": status, "error": str(exc)}
        (out_dir / "temporal_value_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        raise
    except Exception as exc:
        status = "objective2_temporal_value_incomplete"
        if "parity" in str(exc).lower() or "hash" in str(exc).lower():
            status = "objective2_temporal_value_blocked_clean_parity"
        manifest = {"status": status, "error": str(exc)}
        (out_dir / "temporal_value_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        raise


if __name__ == "__main__":
    main()
