"""Write protocol locks from authoritative r4.2 baseline sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from . import OUTPUT_NAMESPACE, RANDOM_FOREST_LOCKED, XGBOOST_LOCKED
from .data import LOCKED_AGG_FEATURES
from .safety import ProtocolAccessError, assert_output_namespace, refuse_overwrite, sha256_file, software_versions, write_json_atomic


def lock_configs(root: Path) -> dict[str, Any]:
    out = assert_output_namespace(root / OUTPUT_NAMESPACE, root)
    out.mkdir(parents=True, exist_ok=True)

    source_script = root / "scripts" / "run_baseline_evaluation.py"
    feature_list = root / "outputs" / "baselines" / "r42_T20_s1_baseline_feature_list.csv"
    metrics_csv = root / "outputs" / "baselines" / "r42_T20_s1_baseline_metrics.csv"
    thr_csv = root / "outputs" / "baselines" / "r42_T20_s1_selected_thresholds.csv"
    summary_md = root / "outputs" / "baselines" / "r42_T20_s1_baseline_summary.md"

    for p in (source_script, feature_list):
        if not p.exists():
            raise ProtocolAccessError(f"protocol_blocked: missing authoritative source {p}")

    feat_names = pd.read_csv(feature_list)["feature_name"].tolist()
    if feat_names != LOCKED_AGG_FEATURES:
        raise ProtocolAccessError(
            "protocol_blocked: r4.2 feature list does not match locked aggregation schema"
        )

    # Confirm source script contains locked hyperparameters (no inference from memory alone).
    src = source_script.read_text(encoding="utf-8")
    required_snippets = [
        'n_estimators=200',
        'max_depth=20',
        'min_samples_leaf=2',
        'class_weight="balanced_subsample"',
        'n_estimators=300',
        'max_depth=6',
        'learning_rate=0.1',
        'subsample=0.8',
        'colsample_bytree=0.8',
        'reg_lambda=1.0',
        'objective="binary:logistic"',
        'eval_metric="aucpr"',
        'tree_method="hist"',
        "scale_pos_weight",
        "max_validation_f1",
        "np.linspace(0.01, 0.99, 99)",
    ]
    missing = [s for s in required_snippets if s not in src]
    if missing:
        raise ProtocolAccessError(
            f"protocol_blocked: source script missing locked snippets: {missing}"
        )

    protocol_lock = {
        "status": "locked",
        "task": "r52_locked_conventional_baselines",
        "release": "CERT r5.2",
        "source_release_for_config": "CERT r4.2",
        "representation": {
            "sequence_length_T": 20,
            "raw_feature_dim_F": 13,
            "model_input": "locked_window_aggregates",
            "model_input_dim": 40,
            "not_used": "flattened_260",
            "feature_order": LOCKED_AGG_FEATURES,
            "preprocessing": "none beyond aggregation; no scaler fitted",
            "fit_scope": "aggregation is deterministic per sequence; scale_pos_weight from r5.2 train labels only",
        },
        "threshold_selection": {
            "criterion": "max_validation_f1",
            "candidates": "linspace(0.01,0.99,99) union quantile(p_val, linspace(0.01,0.99,50))",
            "primary_metric": "PR-AUC",
            "operational_metric_at_threshold": "F1 / confusion matrix",
        },
        "seeds": [42, 52, 62],
        "prohibited": [
            "r5.2_test",
            "r4.2_test_evaluation",
            "r6.2",
            "hyperparameter_search",
            "architecture_search",
        ],
        "software_versions": software_versions(),
    }

    xgb_lock = {
        "model": "xgboost",
        "source_script": str(source_script.relative_to(root)).replace("\\", "/"),
        "source_script_sha256": sha256_file(source_script),
        "feature_list_path": str(feature_list.relative_to(root)).replace("\\", "/"),
        "feature_list_sha256": sha256_file(feature_list),
        "hyperparameters": dict(XGBOOST_LOCKED),
        "random_state_procedure": "vary only random_state among {42,52,62}; all other params fixed",
        "class_weighting": XGBOOST_LOCKED["class_weight_mode"],
        "serialisation": "xgboost.Booster.save_model JSON via XGBClassifier.save_model(.json)",
        "validation_metric_primary": "PR-AUC",
        "threshold_procedure": protocol_lock["threshold_selection"],
        "r42_output_artefacts": {
            "metrics_csv": str(metrics_csv.relative_to(root)).replace("\\", "/") if metrics_csv.exists() else None,
            "thresholds_csv": str(thr_csv.relative_to(root)).replace("\\", "/") if thr_csv.exists() else None,
            "summary_md": str(summary_md.relative_to(root)).replace("\\", "/") if summary_md.exists() else None,
        },
    }

    rf_lock = {
        "model": "random_forest",
        "source_script": str(source_script.relative_to(root)).replace("\\", "/"),
        "source_script_sha256": sha256_file(source_script),
        "feature_list_path": str(feature_list.relative_to(root)).replace("\\", "/"),
        "feature_list_sha256": sha256_file(feature_list),
        "hyperparameters": dict(RANDOM_FOREST_LOCKED),
        "random_state_procedure": "vary only random_state among {42,52,62}; all other params fixed",
        "class_weighting": RANDOM_FOREST_LOCKED["class_weight"],
        "serialisation": "joblib.dump(.joblib)",
        "validation_metric_primary": "PR-AUC",
        "threshold_procedure": protocol_lock["threshold_selection"],
        "r42_output_artefacts": xgb_lock["r42_output_artefacts"],
    }

    source_manifest = {
        "authoritative_r42_baseline_script": {
            "path": xgb_lock["source_script"],
            "sha256": xgb_lock["source_script_sha256"],
        },
        "authoritative_feature_list": {
            "path": xgb_lock["feature_list_path"],
            "sha256": xgb_lock["feature_list_sha256"],
            "n_features": len(feat_names),
        },
        "authoritative_r42_outputs_present": {
            "metrics_csv": metrics_csv.exists(),
            "thresholds_csv": thr_csv.exists(),
            "summary_md": summary_md.exists(),
        },
        "hashes": {
            "metrics_csv": sha256_file(metrics_csv) if metrics_csv.exists() else None,
            "thresholds_csv": sha256_file(thr_csv) if thr_csv.exists() else None,
            "summary_md": sha256_file(summary_md) if summary_md.exists() else None,
        },
        "software_versions": software_versions(),
    }

    paths = {
        "protocol_lock.json": protocol_lock,
        "xgboost_config_lock.json": xgb_lock,
        "random_forest_config_lock.json": rf_lock,
        "source_manifest.json": source_manifest,
    }
    written = []
    for name, payload in paths.items():
        p = out / name
        refuse_overwrite(p)
        write_json_atomic(p, payload)
        written.append(str(p))
    return {"output_dir": str(out), "written": written, "status": "locked"}
