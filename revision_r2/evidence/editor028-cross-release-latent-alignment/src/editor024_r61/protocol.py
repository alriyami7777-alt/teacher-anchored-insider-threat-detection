"""Write the EDITOR-024 protocol freeze artefacts. No r6.1 content access."""

from __future__ import annotations

from typing import Any

from editor006b_harness.safety import EXPECTED_SCALER_SHA256

from .checkpoints import gate_student_checkpoints
from .constants import (
    ANSWER_BUNDLE_CANDIDATES,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    COMPARATORS,
    COMPARATOR_SET,
    DESIGNATED_FINAL_MODEL,
    EDITOR023_RESULTS_COMMIT,
    EXPERIMENT_TYPE,
    FEATURE_ORDER,
    H1,
    LABEL_RULE,
    LABEL_SEMANTICS,
    MODEL_TRAINING,
    PREPROCESSING_PROVENANCE,
    PRIMARY_CONTRASTS,
    PRIMARY_METRIC,
    PRIMARY_VIEW,
    RAW_R61_ROOT,
    R61_UNTOUCHED_ELIGIBILITY,
    REVIEW_REL,
    SCALER_JSON_REL,
    SECONDARY_VIEW,
    SEEDS,
    SEQUENCE_LENGTH,
    STRIDE_PRIMARY,
    STUDENT_MODELS,
    TARGET_RELEASE,
    TARGET_STATUS,
    TASK_ID,
    TASK_NAME,
    UNTOUCHEDNESS_FACTS,
    frozen_thresholds,
    r52_validation_pr_auc,
    student_checkpoint_records,
)
from .io_util import write_json, write_text
from .safety import REPO_ROOT, REVIEW_ROOT, utc_now
from .scaler import load_r52_train_scaler
from .training_gate import assert_no_training


def protocol_markdown(payload: dict[str, Any]) -> str:
    ck_rows = "\n".join(
        f"- {r['model']} seed {r['seed']}: `{r['path']}` SHA256 `{r['expected_sha256']}`"
        for r in payload["student_checkpoints"]
    )
    thr = payload["frozen_thresholds"]
    thr_lines = "\n".join(
        f"- {m} seed {s}: {thr[m][str(s)]}" for m in STUDENT_MODELS for s in SEEDS
    )
    return f"""# EDITOR-024 protocol freeze

Frozen **before** any CERT r6.1 file content is read.

## Identity

- TASK_ID = {TASK_ID}
- TASK_NAME = {TASK_NAME}
- EXPERIMENT_TYPE = {EXPERIMENT_TYPE}
- TARGET_RELEASE = {TARGET_RELEASE}
- TARGET_STATUS = {TARGET_STATUS}
- EDITOR023_RESULTS_COMMIT = {EDITOR023_RESULTS_COMMIT}
- MODEL_TRAINING = {MODEL_TRAINING}
- MODEL_SELECTION = PROHIBITED
- TARGET_ADAPTATION = PROHIBITED
- RESULT_STATUS_AT_START = UNSEEN
- CURRENT_PAPER_MODEL = {DESIGNATED_FINAL_MODEL}

This task supersedes the previously proposed r5.1/r6.2 EDITOR-024 protocol, which was never started.
Do not evaluate r5.1 or r6.2 in EDITOR-024.

## Untouchedness

R61_UNTOUCHED_ELIGIBILITY = {R61_UNTOUCHED_ELIGIBILITY}

Prior knowledge was limited to CERT r6.1 existence, directory/file names, file sizes/timestamps,
answer-bundle filenames, and planned or forbidden code references. No empirical content was examined.

{chr(10).join(f"- {k} = {v}" for k, v in UNTOUCHEDNESS_FACTS.items())}

## Role of CERT r6.1

From this freeze onward, CERT r6.1 is the FINAL_PROSPECTIVELY_RESERVED_CONFIRMATION_TARGET.
It must not become training, validation, hyperparameter-selection, threshold-selection,
calibration, feature-selection, or debugging-by-outcome data.

Scientific hierarchy:

- CERT r5.2 = development, optimisation and validation
- CERT r5.1 = previously observed cross-version diagnostic evidence
- CERT r6.2 = previously observed severe generation-shift stress evidence
- CERT r6.1 = prospectively reserved final confirmation target

Do not use r5.1 or r6.2 results to alter EDITOR-024 after freeze.

## Designated final model

TA2 remains the designated final paper model (final ensemble-guided, route-anchored student)
regardless of r6.1 PR-AUC or comparisons with C2-OPT, F10, or L1.

Internal identifiers (not reader-facing architecture names):

- C2-OPT = teacher-initialised task-only control
- F10 = ensemble-guided ODST student with predictive teacher guidance ON and route anchoring OFF
- TA2 = final ensemble-guided, route-anchored ODST student
- L1 = matched attention-linear reference
- ODST = Oblivious Differentiable Sparsemax Tree

## Frozen model set

Evaluate exactly: {", ".join(STUDENT_MODELS)}
Seeds exactly: {", ".join(str(s) for s in SEEDS)}

Do not retrain. Do not replace an unfavourable checkpoint. Do not add RF/XGBoost or another model after seeing results.

### Student checkpoints (from EDITOR023_CHECKPOINT_PARITY.json)

{ck_rows}

## Frozen preprocessing

Do not design an r6.1-specific representation.

- 13 daily behavioural features in frozen order: {", ".join(FEATURE_ORDER)}
- sequence length = {SEQUENCE_LENGTH}
- primary stride = {STRIDE_PRIMARY}
- primary view = {PRIMARY_VIEW}
- secondary view = {SECONDARY_VIEW} (start_day_index % 20 == 0)
- label rule = {LABEL_RULE} / {LABEL_SEMANTICS}

Do not add psychometric, LDAP, decoy-file, or r6.1-specific features.

Scaler: CERT r5.2 TRAIN only, transform-only.
SCALER_SOURCE = R52_TRAIN
TARGET_SCALER_FIT = NO
SHA256 = {EXPECTED_SCALER_SHA256}
path = {SCALER_JSON_REL}

Raw root (content access only after this freeze): `{RAW_R61_ROOT}`
Answer-bundle candidates (resolved after freeze by filename glob `r6.1-*.csv`):
{chr(10).join(f"- `{p}`" for p in ANSWER_BUNDLE_CANDIDATES)}

### Reused implementations

- event parsing / daily aggregation / completed-window / de-overlap: `scripts/run_editor007b_r51_bundle.py` and `review/editor006c_r62_input_bundle/run_editor006c_r62_input_bundle.py` at parent {EDITOR023_RESULTS_COMMIT}
- window gather / identifiers: `src/editor006b_harness/input_bundle.py`
- scaler transform: `src/editor006b_harness/input_bundle.py::apply_persisted_scaler`
- label contract: `review/editor006a_preinference_freeze/EDITOR006A_R62_LABEL_CONTRACT.json`

## Frozen thresholds (secondary metrics only)

THRESHOLD_SOURCE = R52_FROZEN
TARGET_THRESHOLD_SEARCH = NO

{thr_lines}

PR-AUC is primary and requires no threshold.

## Primary hypothesis H1

{H1["statement"]}

Primary statistic: {H1["statistic"]}

Classification (do not change after results):

- SUPPORTED = point estimate > 0 AND user-cluster 95% CI lower bound > 0
- CONSISTENT = point estimate > 0 but CI lower bound <= 0
- NOT_SUPPORTED = point estimate <= 0

## Mechanistic comparisons

{chr(10).join(f"- {k}: {v}" for k, v in PRIMARY_CONTRASTS.items())}

Same SUPPORTED / CONSISTENT / NOT_SUPPORTED rule. These comparisons do not select the final model.

## Uncertainty

- sampling unit = r6.1 user
- 2000 valid paired bootstrap replicates
- bootstrap seed = {BOOTSTRAP_SEED}
- matched-model contrasts use the same resampled users within each replicate
- discard replicates where PR-AUC cannot be calculated because only one class is present

## Prohibitions

TRAINING_EXECUTED = NO
MODEL_PARAMETERS_UPDATED = NO
TARGET_SCALER_FIT = NO
TARGET_CALIBRATION_FIT = NO
TARGET_THRESHOLD_SEARCH = NO
TARGET_MODEL_SELECTION = NO
TARGET_FEATURE_SELECTION = NO
TARGET_NORMALISATION_FIT = NO
R52_TEST_ACCESSED = NO
R51_RERUN = NO
R62_RERUN = NO

No adversarial-robustness, evasion, poisoning, physical-sensor-failure, or automatic unseen-user-generalisation claims.

The paper may say: cross-release confirmation on a prospectively reserved CERT release.

## Concern-5 ruling (after compatible inference)

- TA2 ranking-transfer SUPPORTED → RESOLVED_WITH_PROSPECTIVELY_RESERVED_CONFIRMATION
- CONSISTENT → PARTIALLY_RESOLVED_WITH_PROSPECTIVELY_RESERVED_CONFIRMATION
- NOT_SUPPORTED → PROSPECTIVELY_TESTED_BUT_GENERALISATION_LIMITED

## Result-chasing prohibition

Once r6.1 content is first opened, no changes to architecture, checkpoints, features, sequence length,
stride, scaler, labels, model set, seeds, metrics, views, thresholds, bootstrap, or claim rules.

A prediction-affecting defect after content access yields EDITOR024_ENGINEERING_BLOCKED_AFTER_TARGET_ACCESS.

## Finalisation order

1. all scientific outputs final
2. completed RUN_MANIFEST
3. RESULT_FREEZE
4. TERMINAL_BLOCK
5. hash all stable target files
6. SHA256_MANIFEST written LAST (does not hash itself)

EDITOR024_RESULTS_COMMIT = PENDING_BY_DESIGN inside frozen files.
"""


def protocol_payload() -> dict[str, Any]:
    assert_no_training()
    scaler = load_r52_train_scaler()
    ck = student_checkpoint_records()
    return {
        "task_id": TASK_ID,
        "task_name": TASK_NAME,
        "experiment_type": EXPERIMENT_TYPE,
        "target_release": TARGET_RELEASE,
        "target_status": TARGET_STATUS,
        "EDITOR023_RESULTS_COMMIT": EDITOR023_RESULTS_COMMIT,
        "model_training": MODEL_TRAINING,
        "model_selection": "PROHIBITED",
        "target_adaptation": "PROHIBITED",
        "result_status_at_start": "UNSEEN",
        "current_paper_model": DESIGNATED_FINAL_MODEL,
        "designated_final_model": DESIGNATED_FINAL_MODEL,
        "designated_final_model_irrespective_of_target_outcome": True,
        "R61_UNTOUCHED_ELIGIBILITY": R61_UNTOUCHED_ELIGIBILITY,
        "untouchedness": UNTOUCHEDNESS_FACTS,
        "models": list(STUDENT_MODELS),
        "comparator_set": list(COMPARATOR_SET),
        "seeds": list(SEEDS),
        "comparators": COMPARATORS,
        "primary_metric": PRIMARY_METRIC,
        "primary_view": PRIMARY_VIEW,
        "secondary_view": SECONDARY_VIEW,
        "label_semantics": LABEL_SEMANTICS,
        "label_rule": LABEL_RULE,
        "feature_order": list(FEATURE_ORDER),
        "n_features": 13,
        "sequence_length": SEQUENCE_LENGTH,
        "stride_primary": STRIDE_PRIMARY,
        "scaler_source": "R52_TRAIN",
        "scaler_sha256": scaler["sha256"],
        "scaler_path": scaler["path"],
        "expected_scaler_sha256": EXPECTED_SCALER_SHA256,
        "TARGET_SCALER_FIT": "NO",
        "TARGET_CALIBRATION_FIT": "NO",
        "TARGET_THRESHOLD_SEARCH": "NO",
        "TARGET_MODEL_SELECTION": "NO",
        "TARGET_FEATURE_SELECTION": "NO",
        "THRESHOLD_SOURCE": "R52_FROZEN",
        "frozen_thresholds": frozen_thresholds(),
        "r52_validation_pr_auc": {
            m: {str(s): v for s, v in seeds.items()} for m, seeds in r52_validation_pr_auc().items()
        },
        "bootstrap": {
            "n_resamples": BOOTSTRAP_RESAMPLES,
            "rng_seed": BOOTSTRAP_SEED,
            "sampling_unit": "r6.1 user",
            "matched_models_share_resampled_users": True,
        },
        "H1": H1,
        "primary_contrasts": PRIMARY_CONTRASTS,
        "claim_rule": {
            "SUPPORTED": "mean > 0 AND user-cluster 95% CI lower bound > 0",
            "CONSISTENT": "mean > 0 but CI lower bound <= 0",
            "NOT_SUPPORTED": "mean <= 0",
        },
        "raw_r61_root": str(RAW_R61_ROOT),
        "answer_bundle_candidates": [str(p) for p in ANSWER_BUNDLE_CANDIDATES],
        "student_checkpoints": ck,
        "preprocessing_provenance": PREPROCESSING_PROVENANCE,
        "partitions": {
            "r52_train": "HISTORICAL_SOURCE_OF_FROZEN_MODELS_AND_SCALER",
            "r52_validation": "HISTORICAL_SOURCE_OF_THRESHOLDS_AND_RETENTION_DENOMINATOR",
            "r52_test": "HARD_DENY",
            "r51": "DO_NOT_RERUN",
            "r62": "DO_NOT_RERUN",
            "r61": "FINAL_PROSPECTIVELY_RESERVED_CONFIRMATION_TARGET",
        },
        "review_rel": str(REVIEW_REL),
        "written_at": utc_now(),
        "content_access_authorised": False,
    }


def freeze_protocol() -> dict[str, Any]:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    payload = protocol_payload()
    write_json(REVIEW_ROOT / "EDITOR024_PROTOCOL.json", payload)
    write_text(REVIEW_ROOT / "EDITOR024_PROTOCOL.md", protocol_markdown(payload))
    write_json(
        REVIEW_ROOT / "EDITOR024_UNTOUCHEDNESS_RECORD.json",
        {
            "R61_UNTOUCHED_ELIGIBILITY": R61_UNTOUCHED_ELIGIBILITY,
            **UNTOUCHEDNESS_FACTS,
            "disclosed_prior_knowledge": [
                "CERT r6.1 existence",
                "directory/file names",
                "file sizes/timestamps",
                "answer-bundle filenames",
                "planned or forbidden code references",
            ],
            "empirical_content_examined": False,
            "written_at": utc_now(),
        },
    )
    gate = gate_student_checkpoints()
    write_json(REVIEW_ROOT / "EDITOR024_CHECKPOINT_PARITY.json", {**gate, "phase": "protocol_freeze"})
    return payload
