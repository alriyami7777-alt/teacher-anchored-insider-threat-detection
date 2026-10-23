"""End-to-end r5.2 calibration + operational alert-burden pipeline (no training)."""

from __future__ import annotations

import shutil
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .alert_burden import (
    alerted_user_summary,
    episode_tables,
    fixed_budget_results,
    frozen_threshold_burden,
    incident_level_analysis,
    user_level_aggregation,
)
from .calibration import classify_odst_temperature, run_calibration_for_bundle
from .comparison import build_claim_register, decide_final_status, paired_user_cluster_bootstrap
from .constants import (
    BASE_COMMIT,
    BOOTSTRAP_SEED,
    BRANCH,
    BUDGETS,
    EXPECTED_VAL_SHA256,
    METHOD_TEMP,
    N_BOOTSTRAP_MAX_ATTEMPTS,
    N_BOOTSTRAP_TARGET,
    N_FOLDS,
    OUTPUT_REL,
    RANK_SPEARMAN_MIN,
    RECORDED_REL,
    SEEDS,
    STATUS_INCOMPLETE,
    STATUS_PROVENANCE,
    STATUS_SAFETY,
    VAL_REL,
)
from .evidence import load_all_predictions
from .figures import write_figures
from .reports import write_reports
from .safety import (
    AuditBlockedError,
    OpenedFilesRegister,
    ProtectedDataAccessError,
    assert_output_namespace,
    assert_path_allowed_for_read,
    environment_metadata,
    refuse_test_loader,
    refuse_training,
    sha256_file,
    write_csv_atomic,
    write_json_atomic,
)


def _flush(msg: str) -> None:
    print(msg, flush=True)


def _git_head(repo_root: Path) -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_root), text=True)
            .strip()
        )
    except Exception:
        return "unknown"


def _mirror(out_dir: Path, repo_root: Path) -> None:
    dest = repo_root / RECORDED_REL
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.md", "*.csv", "*.json"):
        for p in out_dir.glob(pattern):
            shutil.copy2(p, dest / p.name)
    for sub in ("figure_sources", "figures"):
        src = out_dir / sub
        if src.exists():
            d2 = dest / sub
            d2.mkdir(parents=True, exist_ok=True)
            for p in src.glob("*"):
                if p.is_file():
                    shutil.copy2(p, d2 / p.name)


def run(repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = Path(repo_root or Path.cwd()).resolve()
    out_dir = assert_output_namespace(repo_root / OUTPUT_REL)
    out_dir.mkdir(parents=True, exist_ok=True)
    opened = OpenedFilesRegister()
    checks: dict[str, bool] = {}
    status = STATUS_INCOMPLETE
    cal_class = "incomplete"
    result: dict[str, Any] = {}

    try:
        try:
            refuse_test_loader("test")
            checks["test_loader_refused"] = False
        except ProtectedDataAccessError:
            checks["test_loader_refused"] = True
        try:
            refuse_training()
            checks["training_refused"] = False
        except ProtectedDataAccessError:
            checks["training_refused"] = True
        try:
            assert_path_allowed_for_read(
                repo_root / "data/processed/r5.2/tensors/r52_T20_s1_test.npz"
            )
            checks["test_path_blocked"] = False
        except ProtectedDataAccessError:
            checks["test_path_blocked"] = True
        try:
            assert_path_allowed_for_read(repo_root / "data/processed/r6.2/dummy.npz")
            checks["r62_path_blocked"] = False
        except ProtectedDataAccessError:
            checks["r62_path_blocked"] = True

        val_p = repo_root / VAL_REL
        opened.record(val_p, "validation_sha_check")
        val_sha = sha256_file(val_p)
        checks["validation_sha_ok"] = val_sha == EXPECTED_VAL_SHA256
        if not checks["validation_sha_ok"]:
            raise AuditBlockedError(STATUS_PROVENANCE, "validation tensor hash mismatch")

        git_commit = _git_head(repo_root)
        config = {
            "branch": BRANCH,
            "base_commit": BASE_COMMIT,
            "git_commit": git_commit,
            "seeds": list(SEEDS),
            "n_folds": N_FOLDS,
            "budgets": list(BUDGETS),
            "bootstrap_target": N_BOOTSTRAP_TARGET,
            "bootstrap_max_attempts": N_BOOTSTRAP_MAX_ATTEMPTS,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "primary_calibration": "temperature_scaling",
            "secondary_calibration": "platt_a_gt_0",
            "teacher_loaded": False,
            "threshold_retuning": False,
            "neural_inference": False,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json_atomic(out_dir / "calibration_alert_config.json", config)

        _flush("Loading evidence…")
        bundles, provenance, parity, xgb_loaded = load_all_predictions(repo_root, opened)
        write_csv_atomic(out_dir / "calibration_model_provenance.csv", provenance)
        write_csv_atomic(out_dir / "calibration_clean_parity.csv", parity)
        checks["xgb_loaded"] = xgb_loaded

        metric_parts = []
        param_parts = []
        bin_parts = []
        fold_parts = []
        burden_rows = []
        user_parts = []
        ep_sum_parts = []
        ep_rec_parts = []
        budget_parts = []
        user_agg_parts = []

        _flush("Running grouped calibration and alert-burden analyses…")
        for key, bundle in sorted(bundles.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            _flush(f"  {bundle.model} seed={bundle.seed}")
            m, p, b, _probs, folds = run_calibration_for_bundle(bundle)
            metric_parts.append(m)
            param_parts.append(p)
            bin_parts.append(b)
            fold_parts.append(folds)
            burden_rows.append(frozen_threshold_burden(bundle))
            user_parts.append(alerted_user_summary(bundle))
            ep_sum, ep_rec = episode_tables(bundle)
            ep_sum_parts.append(ep_sum)
            ep_rec_parts.append(ep_rec)
            budget_parts.append(fixed_budget_results(bundle))
            user_agg_parts.append(user_level_aggregation(bundle))

        metrics = pd.concat(metric_parts, ignore_index=True)
        params = pd.concat(param_parts, ignore_index=True)
        bins = pd.concat(bin_parts, ignore_index=True)
        folds = pd.concat(fold_parts, ignore_index=True)
        burden = pd.DataFrame(burden_rows)
        users_df = pd.concat(user_parts, ignore_index=True) if user_parts else pd.DataFrame()
        episodes = pd.concat(ep_sum_parts, ignore_index=True)
        episode_records = (
            pd.concat([e for e in ep_rec_parts if len(e)], ignore_index=True)
            if any(len(e) for e in ep_rec_parts)
            else pd.DataFrame()
        )
        budgets = pd.concat(budget_parts, ignore_index=True)
        user_agg = pd.concat(user_agg_parts, ignore_index=True)

        write_csv_atomic(out_dir / "calibration_metrics.csv", metrics)
        write_csv_atomic(out_dir / "calibration_parameters.csv", params)
        write_csv_atomic(out_dir / "calibration_reliability_bins.csv", bins)
        write_csv_atomic(out_dir / "calibration_group_folds.csv", folds)
        write_csv_atomic(out_dir / "frozen_threshold_alert_burden.csv", burden)
        write_csv_atomic(out_dir / "alerted_user_summary.csv", users_df)
        write_csv_atomic(out_dir / "alert_episode_summary.csv", episodes)
        write_csv_atomic(out_dir / "alert_episode_records.csv", episode_records)
        write_csv_atomic(out_dir / "fixed_alert_budget_results.csv", budgets)
        write_csv_atomic(out_dir / "user_level_aggregation_results.csv", user_agg)

        _flush("Incident-level analysis…")
        incidents = incident_level_analysis(bundles, repo_root, opened)
        write_csv_atomic(out_dir / "incident_level_alert_results.csv", incidents)
        incident_available = (
            "status" in incidents.columns
            and len(incidents)
            and str(incidents.iloc[0].get("status", "")) == "ok"
        ) or ("detected" in incidents.columns)

        cal_class = classify_odst_temperature(metrics)
        _flush(f"Calibration class: {cal_class}")

        temp_m = metrics[metrics.method == METHOD_TEMP]
        oof_rank_limit = bool(
            len(temp_m)
            and "rank_spearman_vs_uncal" in temp_m.columns
            and (temp_m["rank_spearman_vs_uncal"] < RANK_SPEARMAN_MIN).any()
        )
        if oof_rank_limit:
            _flush(
                "Note: global OOF Spearman below guidance for >=1 model-seed "
                "(within-fold ranking remains exact; recorded as study limit)."
            )

        _flush("Paired comparison…")
        paired = paired_user_cluster_bootstrap(bundles, burden, episodes, metrics)
        write_csv_atomic(out_dir / "odst_attention_linear_paired_comparison.csv", paired)

        claims = build_claim_register(
            cal_class=cal_class,
            metrics=metrics,
            burden=burden,
            paired=paired,
            xgb_loaded=xgb_loaded,
            incident_available=bool(incident_available),
        )
        write_csv_atomic(out_dir / "calibration_alert_claim_register.csv", claims)

        status, _limits = decide_final_status(
            cal_class=cal_class,
            xgb_loaded=xgb_loaded,
            incident_available=bool(incident_available),
            checks=checks,
            oof_rank_limit=oof_rank_limit,
        )

        _flush("Writing figures and reports…")
        write_figures(
            out_dir,
            metrics=metrics,
            bins=bins,
            burden=burden,
            episodes=episodes,
            budgets=budgets,
            user_agg=user_agg,
        )
        write_reports(
            out_dir,
            status=status,
            cal_class=cal_class,
            metrics=metrics,
            params=params,
            burden=burden,
            episodes=episodes,
            budgets=budgets,
            paired=paired,
            claims=claims,
            checks=checks,
            git_commit=git_commit,
            xgb_loaded=xgb_loaded,
        )

        write_csv_atomic(out_dir / "opened_files_register.csv", opened.to_dataframe())
        write_json_atomic(out_dir / "environment_metadata.json", environment_metadata())

        manifest = {
            "status": status,
            "calibration_class": cal_class,
            "checks": checks,
            "xgb_loaded": xgb_loaded,
            "incident_available": bool(incident_available),
            "n_models": len({m for m, _ in bundles}),
            "n_seeds": len(SEEDS),
            "git_commit": git_commit,
            "output_dir": str(out_dir),
        }
        write_json_atomic(out_dir / "calibration_alert_manifest.json", manifest)
        _mirror(out_dir, repo_root)

        result = {"status": status, "calibration_class": cal_class, "out_dir": str(out_dir)}
        _flush(f"Done: {status}")
        return result

    except ProtectedDataAccessError as e:
        status = STATUS_SAFETY
        write_json_atomic(
            out_dir / "calibration_alert_manifest.json",
            {"status": status, "error": str(e), "checks": checks},
        )
        raise
    except AuditBlockedError as e:
        status = e.status
        write_json_atomic(
            out_dir / "calibration_alert_manifest.json",
            {"status": status, "error": str(e), "checks": checks},
        )
        return {"status": status, "error": str(e)}
    except Exception as e:
        status = STATUS_INCOMPLETE
        write_json_atomic(
            out_dir / "calibration_alert_manifest.json",
            {
                "status": status,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "checks": checks,
            },
        )
        raise
