"""Reports for matched temporal-learning study."""

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
    claims: pd.DataFrame,
    effects: pd.DataFrame,
    config: dict[str, Any],
) -> None:
    interp = f"""# Matched temporal-learning interpretation

**Status:** `{status}`
**Evidence label:** r5.2 validation forward-pass temporal comparison (not independent test confirmation)

## Completed results

All models received identical intervened 20×13 values (flattened models via chronological 260 remap after intervention).

## User-grouped uncertainty

Paired user-cluster bootstrap intervals are in `matched_temporal_user_bootstrap.csv`.

## Qualified interpretation

Chronology dependence, accumulated-history value, and between-model sequence advantage are classified in `matched_temporal_claim_register.csv` using predeclared bands in `matched_temporal_config.json`.

## Negative / unresolved findings

Report null or uncertain findings without forcing sequence superiority.

## Unsupported claims

Do not claim real-world early-warning lead time, temporal causality, operational superiority, independent test confirmation, or that shuffle degradation alone proves superiority.

Primary source commit: `{config.get('source_same_info_commit')}`
"""
    _w(out_dir / "MATCHED_TEMPORAL_LEARNING_INTERPRETATION.md", interp)

    _w(
        out_dir / "PAPER_MATCHED_TEMPORAL_RESULTS.md",
        f"""# Paper notes — matched temporal results

Status: `{status}`

See `matched_temporal_condition_metrics.csv`, `matched_temporal_effect_sizes.csv`, figures 1–5, and claim register.

Uncertainty is validation paired user-cluster bootstrap uncertainty.
""",
    )

    _w(
        out_dir / "PAPER_MATCHED_TEMPORAL_DISCUSSION.md",
        """# Paper notes — matched temporal discussion

Interpret chronological sensitivity jointly with clean same-information performance and partial-history detection.

ODST versus attention–linear temporal differences should not be forced; report unresolved intervals honestly.
""",
    )

    _w(
        out_dir / "OBJECTIVE2_MATCHED_TEMPORAL_DEFENCE_EXPLANATION.md",
        f"""# Objective 2 defence — matched temporal learning

## Question

Do sequence models use chronological order and accumulated history more effectively than flattened same-information baselines?

## Structure

1. Clean same-information parity
2. Order interventions (reverse / fixed shuffle)
3. Partial-history curves
4. User-grouped uncertainty
5. ODST versus attention–linear temporal incremental value

Status: `{status}`
""",
    )

    _w(
        out_dir / "EXPERIMENTAL_HANDOVER.md",
        f"""# Experimental handover — matched temporal learning Stage 2

## Worktree / branch

- `public repository package: objective2_r52_matched_temporal_learning`
- `objective2-r52-matched-temporal-learning`
- Base: `{config.get('source_same_info_commit')}`

## Status

`{status}`

## Do not

- Run low-and-slow / Stage 3–4
- Open r5.2 test
- Retrain / retune
- Merge to main
- Create tags

## Next

Review claim register and figures before manuscript wording.
""",
    )
    _ = claims, effects
