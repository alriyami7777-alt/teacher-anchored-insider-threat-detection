"""Markdown interpretation and paper-facing reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .safety import assert_output_namespace


def _w(path: Path, text: str) -> None:
    assert_output_namespace(path)
    path.write_text(text, encoding="utf-8")


def write_reports(
    *,
    out_dir: Path,
    status: str,
    summary_a: pd.DataFrame,
    engineered: pd.DataFrame,
    pairwise: pd.DataFrame,
    bootstrap: pd.DataFrame,
    config: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    a = summary_a.set_index("model") if not summary_a.empty else summary_a

    def m(model: str, col: str) -> str:
        if model not in a.index:
            return "n/a"
        v = a.loc[model, col]
        return "n/a" if pd.isna(v) else f"{float(v):.4f}"

    interp = f"""# Same-information baseline interpretation

**Status:** `{status}`
**Comparison label:** `r5.2 validation comparison` (not independent test confirmation)

## Completed same-information results

Panel A models received identical underlying sequence information (20×13), with non-sequential models using the fixed chronological flatten to 260 ordered values.

| Model | Mean PR-AUC | Mean F1 |
|---|---:|---:|
| Logistic regression (260) | {m('logistic_regression_flat260','pr_auc_mean')} | {m('logistic_regression_flat260','f1_mean')} |
| MLP (260) | {m('mlp_flat260','pr_auc_mean')} | {m('mlp_flat260','f1_mean')} |
| Random Forest (260) | {m('random_forest_flat260','pr_auc_mean')} | {m('random_forest_flat260','f1_mean')} |
| XGBoost (260) | {m('xgboost_flat260','pr_auc_mean')} | {m('xgboost_flat260','f1_mean')} |
| Bi-LSTM–attention–linear (20×13) | {m('attention_linear_seq','pr_auc_mean')} | {m('attention_linear_seq','f1_mean')} |
| Teacher-anchored ODST (20×13) | {m('teacher_anchored_odst_seq','pr_auc_mean')} | {m('teacher_anchored_odst_seq','f1_mean')} |

## Engineered-feature context

Panel B retains historical engineered 40-feature RF/XGBoost results as operational context. **Panel B inputs are not identical** to Panel A.

## Supported conclusions

Supported conclusions are restricted to identical-information (Panel A) comparisons and are listed in `same_information_claim_register.csv` and pairwise deltas in `same_information_pairwise_comparisons.csv`.

## Qualified conclusions

- Feature-engineering effect (A2) is an **association** between engineered-40 and flat-260 tree performance, not causal proof.
- Temporal / sequential value (A3) and ODST-head value (A4) are qualified by validation-only thresholding and seed variability.
- Complexity trade-offs (A5) may favour temporal/explanation capability even when predictive deltas are small.

## Unsupported conclusions

Do **not** claim:

- RF/XGBoost are unfair baselines;
- neural superiority unless measured;
- independent test confirmation;
- cross-version test generalisation;
- external operational effectiveness;
- state-of-the-art performance.

## Bootstrap uncertainty

User-grouped paired bootstrap results are in `same_information_bootstrap_comparisons.csv` where valid. Sliding windows were not treated as independent observations.
"""
    _w(out_dir / "SAME_INFORMATION_INTERPRETATION.md", interp)

    paper_results = f"""# Paper notes — baseline fairness results (Objective 2)

Comparison type: **r5.2 validation comparison** under locked same-information protocol.

Primary ranking metric: **PR-AUC** (threshold-independent).
Operating points: validation max-F1 thresholds (reported, not used as primary rank).

See:

- `same_information_seed_metrics.csv`
- `same_information_model_summary.csv`
- `same_information_pairwise_comparisons.csv`
- figures 1–4 in this output namespace

Authoritative frozen references:

- Final r4.2 candidate tag `{config.get('candidate_tag')}`
- r5.2 teacher-anchored stamp `{config.get('r52_ta_stamp_commit')}`

Status: `{status}`
"""
    _w(out_dir / "PAPER_BASELINE_FAIRNESS_RESULTS.md", paper_results)

    paper_disc = f"""# Paper notes — baseline fairness discussion

This study isolates classifier effects from engineered window-summary features by giving RF, XGBoost, logistic regression, MLP, attention–linear, and teacher-anchored ODST the same underlying 20×13 daily sequence information.

Discussion should keep Panel A (identical information) separate from Panel B (engineered-feature operational context). Panel B must not be ranked as if inputs were identical.

Complexity should be discussed honestly: if predictive gains are small, justification may rest on temporal modelling or explanation capability rather than raw PR-AUC alone.

Manifest status: `{manifest.get('status', status)}`
"""
    _w(out_dir / "PAPER_BASELINE_FAIRNESS_DISCUSSION.md", paper_disc)

    defence = f"""# Objective 2 defence explanation — same-information baselines

## Purpose

Answer how much of the observed RF/XGBoost advantage is associated with the classifier versus the richer engineered representation.

## Protocol locks

- No architecture or hyperparameter search
- Teacher-anchored model not modified or retrained
- Original engineered RF/XGBoost retained as Panel B context only
- r5.2 test blocked at path level
- Config frozen in `same_information_config.json` before results

## Defence-facing answer structure

1. Same-information classifier comparison (Panel A)
2. Feature-engineering association (Panel A vs Panel B)
3. Sequential modelling value among same values
4. ODST head incremental value vs attention–linear
5. Complexity versus measured performance

Status: `{status}`
"""
    _w(out_dir / "OBJECTIVE2_BASELINE_DEFENCE_EXPLANATION.md", defence)

    handover = f"""# Experimental handover — r5.2 same-information baselines

## Worktree / branch

- Worktree: `public repository package: objective2_r52_same_information_baselines`
- Branch: `objective2-r52-same-information-baselines`
- Base stamp: `{config.get('r52_ta_stamp_commit')}`

## Output namespace

`outputs/objective2/r52_same_information_baselines_v1/`

## Status

`{status}`

## Do not

- Merge to `main`
- Open r5.2 test
- Retune models
- Modify teacher-anchored checkpoints
- Create/move model tags

## Next review

Inspect Panel A rankings, Panel B context deltas, bootstrap CIs, and claim register before any manuscript wording.
"""
    _w(out_dir / "EXPERIMENTAL_HANDOVER.md", handover)

    # pairwise / bootstrap already written as CSV by pipeline; keep markdown pointers light
    _ = pairwise, bootstrap
