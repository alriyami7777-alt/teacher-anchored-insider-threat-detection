# Teacher-Anchored Differentiable Sequence-Ensemble Learning for Insider Threat Detection

> [!WARNING]
> This repository supports a manuscript under active revision. Results,
> documentation, reproducibility material, and supplementary files are not yet
> submission-final. Frozen implementation evidence takes precedence over
> provisional manuscript wording.

This repository is a compact research and reproducibility companion for a PhD study on insider threat detection in enterprise activity logs. It is deliberately separated from the full experimental workspace.

The repository is intended to share:

- reviewed model and evaluation code;
- experiment protocols and configuration templates;
- result summaries and provenance records;
- explanation and robustness procedures;
- limitations and planned follow-up experiments.

It does **not** distribute CERT datasets, answer files, user identifiers, model checkpoints, large prediction arrays, or private organisational material.

## Research objectives and Chapter 3 phases

| Research objective | Repository area | Chapter 3 phase |
|---|---|---|
| Objective 1: develop time-aware preprocessing that preserves inactivity and behavioural chronology | `src/preprocessing`, `protocols/objective1_*` | Phase 1: data preparation and temporal representation |
| Objective 2: develop and evaluate a unified differentiable sequence–ensemble architecture | `src/models`, `src/training`, `src/evaluation`, `protocols/objective2_*` | Phase 2: model development and comparative evaluation |
| Objective 3: assess explanation evidence and robustness under controlled conditions | `src/explainability`, `src/robustness`, `protocols/objective3_*` | Phase 3: explainability and robustness assessment |

## Architecture

The planned and evaluated architecture uses:

1. 20-day sequences;
2. 13 daily behavioural features;
3. a bidirectional long short-term memory encoder;
4. temporal attention;
5. a differentiable tree head;
6. a binary insider-threat prediction output.

Teacher anchoring is used during training. The student model remains independent at inference.

## Evidence status

### Completed evidence

- CERT r4.2 feasibility and architecture-development experiments.
- CERT r5.2 one-pass independent testing for eligible baselines and the frozen-encoder ODST comparator.
- CERT r5.2 teacher-anchored train/validation reproducibility across seeds 42, 52, and 62.
- Same-information attentionâ€“linear and ODST comparisons.
- Explanation and degraded-input portability analyses on CERT r5.2, with documented limitations.
- ODST component-latency and reduced-tree viability audits.
- CERT r6.2 model-free readiness, provenance, ground-truth package audit, exact-matching strategy, and Stage 2B-1A logon matching.

### Qualified findings

- Teacher anchoring currently supports stabilisation and reproducibility rather than a substantial performance improvement.
- ODST explanation evidence is supported under the documented reference-centred procedure and carries sensitivity limits.
- Missing-source experiments are controlled source-channel ablations rather than complete operational deployment simulations.
- The final teacher-anchored student has not yet been claimed as independently tested on CERT r6.2.

### Planned experiments

- Any outstanding independent evaluation of the final teacher-anchored student.
- Preregistered CERT r6.2 model stress testing.
- Larger GPU experiments after return to Malaysia.

## Repository map

- `STATUS.md` â€” current evidence classification.
- `REPRODUCIBILITY.md` â€” reproducibility requirements.
- `DATA_AVAILABILITY.md` â€” dataset restrictions and expected local layout.
- `KNOWN_LIMITATIONS.md` â€” protocol and interpretation limits.
- `protocols/` â€” objective-linked experimental protocols.
- `manifests/` â€” experiment registry and result provenance.
- `results/tables/` â€” compact manuscript-facing result tables.
- `src/` and `scripts/` â€” reviewed implementation only.

## Important interpretation rule

Results in this repository must be labelled as **completed**, **preliminary or qualified**, **planned**, or **final conclusion**. Planned experiments must not be written as completed evidence.

## Local setup

See `SETUP_WINDOWS.md`.

## Licence

The initial repository uses a temporary all-rights-reserved notice. A public open-source licence should be selected only after the code and data-sharing position have been reviewed.

