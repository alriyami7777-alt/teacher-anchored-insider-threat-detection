"""Locked CERT r5.2 conventional baselines (XGBoost + Random Forest)."""

OUTPUT_NAMESPACE = "outputs/objective2/r52_locked_baselines"
SEEDS = (42, 52, 62)

COMMON_13_FEATURES = [
    "total_events",
    "logon_count",
    "device_count",
    "file_count",
    "email_count",
    "http_count",
    "active_duration_minutes",
    "has_logon_activity",
    "has_device_activity",
    "has_file_activity",
    "has_email_activity",
    "has_http_activity",
    "is_active_day",
]

NUMERIC_FEATURES = COMMON_13_FEATURES[:7]
BINARY_FEATURES = COMMON_13_FEATURES[7:]

# Authoritative r4.2 classical hyperparameters from scripts/run_baseline_evaluation.py
XGBOOST_LOCKED = {
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "objective": "binary:logistic",
    "eval_metric": "aucpr",
    "n_jobs": -1,
    "tree_method": "hist",
    "class_weight_mode": "scale_pos_weight = n_neg/n_pos on training labels only",
}

RANDOM_FOREST_LOCKED = {
    "n_estimators": 200,
    "max_depth": 20,
    "min_samples_leaf": 2,
    "n_jobs": -1,
    "class_weight": "balanced_subsample",
}
