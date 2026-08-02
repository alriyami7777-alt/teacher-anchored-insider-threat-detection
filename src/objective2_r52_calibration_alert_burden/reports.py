"""Markdown reports for calibration + alert-burden audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .constants import PREFERRED_FRAMING
from .safety import write_text_atomic


def _md_table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df is None or len(df) == 0:
        return "_(empty)_"
    view = df.head(max_rows)
    cols = list(view.columns)
    lines = [
        "| " + " | ".join(str(c) for c in cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in view.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_… {len(df) - max_rows} additional rows omitted._")
    return "\n".join(lines)


def write_reports(
    out_dir: Path,
    *,
    status: str,
    cal_class: str,
    metrics: pd.DataFrame,
    params: pd.DataFrame,
    burden: pd.DataFrame,
    episodes: pd.DataFrame,
    budgets: pd.DataFrame,
    paired: pd.DataFrame,
    claims: pd.DataFrame,
    checks: dict[str, bool],
    git_commit: str,
    xgb_loaded: bool,
) -> None:
    checks_df = pd.DataFrame([{"check": k, "ok": v} for k, v in checks.items()])
    common = dict(
        status=status,
        cal_class=cal_class,
        metrics=metrics,
        params=params,
        burden=burden,
        episodes=episodes,
        budgets=budgets,
        paired=paired,
        claims=claims,
        checks_df=checks_df,
        git_commit=git_commit,
        xgb_loaded=xgb_loaded,
    )
    write_text_atomic(out_dir / "R52_CALIBRATION_RESULTS.md", _calibration(**common))
    write_text_atomic(out_dir / "R52_OPERATIONAL_ALERT_BURDEN.md", _burden(**common))
    write_text_atomic(
        out_dir / "ODST_ATTENTION_LINEAR_OPERATIONAL_COMPARISON.md", _comparison(**common)
    )
    write_text_atomic(out_dir / "PAPER_CALIBRATION_ALERT_RESULTS.md", _paper_results(**common))
    write_text_atomic(out_dir / "PAPER_CALIBRATION_ALERT_DISCUSSION.md", _paper_disc(**common))
    write_text_atomic(out_dir / "CHAPTER3_CALIBRATION_ALERT_METHOD.md", _ch3())
    write_text_atomic(out_dir / "CHAPTER4_CALIBRATION_ALERT_NOTES.md", _ch4(cal_class, status))
    write_text_atomic(out_dir / "CALIBRATION_ALERT_DEFENCE.md", _defence(**common))
    write_text_atomic(out_dir / "EXPERIMENTAL_HANDOVER.md", _handover(**common))


def _calibration(**kw: Any) -> str:
    return f"""# R5.2 calibration results

## Status

- Final status: `{kw['status']}`
- Calibration classification: `{kw['cal_class']}`
- Primary method: grouped out-of-fold temperature scaling
- Secondary sensitivity: Platt scaling with a > 0

{PREFERRED_FRAMING}

## Safety checks

{_md_table(kw['checks_df'])}

## Calibration parameters (per fold)

{_md_table(kw['params'])}

## Calibration metrics

{_md_table(kw['metrics'])}

## Notes

- Teacher never loaded.
- PR-AUC must remain unchanged under monotonic calibration within numerical tolerance.
- XGBoost tree-margin logits are reconstructed from probabilities when included; treat as operational reference only ({'loaded' if kw['xgb_loaded'] else 'not loaded'}).
"""


def _burden(**kw: Any) -> str:
    return f"""# R5.2 operational alert burden

## Status

- Final status: `{kw['status']}`

{PREFERRED_FRAMING}

## Frozen-threshold burden

{_md_table(kw['burden'])}

## Alert-episode consolidation

Episodes are analytical consolidations: consecutive alerted sequence end dates with gap ≤ 1 day stay in the same episode; gap > 1 day starts a new episode.

{_md_table(kw['episodes'])}

## Fixed alert budgets

{_md_table(kw['budgets'])}

## Restrictions

Do not interpret these quantities as analyst usefulness, deployment readiness, or real-world alert cost.
"""


def _comparison(**kw: Any) -> str:
    return f"""# ODST versus attention–linear operational comparison

## Status

- Final status: `{kw['status']}`
- Calibration classification: `{kw['cal_class']}`

## Paired user-cluster bootstrap

{_md_table(kw['paired'])}

## Claim register

{_md_table(kw['claims'])}

{PREFERRED_FRAMING}
"""


def _paper_results(**kw: Any) -> str:
    return f"""# Paper: calibration and alert-burden results

{PREFERRED_FRAMING}

## Calibration metrics (excerpt)

{_md_table(kw['metrics'])}

## Frozen-threshold burden (excerpt)

{_md_table(kw['burden'])}

## Budgeted detection (excerpt)

{_md_table(kw['budgets'])}
"""


def _paper_disc(**kw: Any) -> str:
    return f"""# Paper: calibration and alert-burden discussion

{PREFERRED_FRAMING}

Calibration classification `{kw['cal_class']}` summarises whether temperature scaling improved probability quality for teacher-anchored ODST without changing ranking. Alert-burden tables quantify how overlapping 20-day windows inflate sequence-level alert counts relative to unique users and consolidated episodes.

No claim is made of analyst usefulness or deployment readiness.
"""


def _ch3() -> str:
    return f"""# Chapter 3 method notes — calibration and alert burden

## Design

- Validation predictions only (r5.2).
- User-grouped GroupKFold(5) for out-of-fold calibration.
- Temperature scaling primary; Platt (a>0) secondary.
- Frozen thresholds; no retuning.
- Episode consolidation by sequence end-date gap > 1 day.

{PREFERRED_FRAMING}
"""


def _ch4(cal_class: str, status: str) -> str:
    return f"""# Chapter 4 notes — calibration and alert burden

- Status: `{status}`
- Calibration class: `{cal_class}`

{PREFERRED_FRAMING}

Interpretation should separate ranking performance from probability quality and from threshold-specific workload proxies.
"""


def _defence(**kw: Any) -> str:
    return f"""# Defence explanation — calibration and alert burden

## What was asked

Whether simple post-hoc calibration improves ODST probability quality without changing ranking, and how sequence alerts translate into users and episodes relative to attention–linear.

## What was done

- Saved validation predictions only; no neural re-inference; teacher never loaded.
- Grouped temperature scaling with OOF predictions; Platt secondary.
- Frozen-threshold burden, episode consolidation, fixed budgets, user-level aggregation.
- Paired user-cluster bootstrap for ODST vs attention–linear deltas.

## Status

- `{kw['status']}` / `{kw['cal_class']}`

{PREFERRED_FRAMING}

## Claim register

{_md_table(kw['claims'])}
"""


def _handover(**kw: Any) -> str:
    return f"""# Experimental handover — calibration and alert burden

- Git commit at run: `{kw['git_commit']}`
- Final status: `{kw['status']}`
- Calibration class: `{kw['cal_class']}`
- XGBoost reference loaded: `{kw['xgb_loaded']}`

## Outputs

All artefacts under `outputs/objective2/r52_calibration_alert_burden_v1/` with mirrors in `scripts/objective2_r52_calibration_alert_burden/recorded_results/`.

## Stop rules

Do not retune thresholds, access r5.2 test or r6.2, load the teacher, or launch further calibrators from this package without a new study brief.

{PREFERRED_FRAMING}
"""
