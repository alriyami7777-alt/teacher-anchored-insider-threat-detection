# Paper Repository Map

## `paper/`

Versioned manuscript source, required LaTeX support files, manuscript figures,
author photographs and dated compiled checkpoints.

## `results/`

Verified paper-facing aggregate tables, figure data, completed analyses and
clearly separated preliminary or planned material.

## `manifests/`

Provenance registers linking manuscript artefacts to producing projects,
branches, commits, configurations, saved outputs and hashes.

## `protocols/`

Frozen paper-facing experimental and evaluation protocols. These documents
describe permitted interpretation and do not replace producing-run evidence.

## `src/`

Only the minimum frozen implementation required for paper reproducibility.
Entire experimental worktrees must not be copied here without review.

## `scripts/`

Paper-facing regeneration, validation, consistency-checking and provenance
scripts.

## `tests/`

Checks for result-table consistency, hashes, figure inputs, references and
reproducibility contracts.

## `review/`

Submission readiness, manuscript changelog, claim-to-evidence audits,
limitations and reviewer-facing preparation.

## `submission/`

Submission-only material such as the graphical abstract, supplementary package,
metadata checklist and final archive preparation.

## `data/`

Documentation and acquisition instructions only. Raw CERT data, user-level
records and event-level extracts must not be committed.
