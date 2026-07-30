# IEEE Access Submission Readiness

## Status definitions

- `READY`: complete and verified.
- `IN PROGRESS`: actively being prepared.
- `BLOCKED`: depends on missing or unresolved evidence.
- `NOT REQUIRED`: confirmed unnecessary for this submission.

## Manuscript package

| Item | Status | Repository location | Notes |
|---|---|---|---|
| Current Overleaf source checkpoint | READY | `paper/manuscript/source/` | Working checkpoint; not submission-ready |
| Matching compiled PDF | READY | `paper/manuscript/snapshots/` | Dated working checkpoint |
| Abstract | IN PROGRESS | `paper/manuscript/source/access.tex` | Requires final evidence-alignment review |
| Introduction | IN PROGRESS | `paper/manuscript/source/01_introduction.tex` | Under active revision |
| Related Work | IN PROGRESS | `paper/manuscript/source/02_related_work.tex` | References require final verification |
| Methodology | IN PROGRESS | `paper/manuscript/source/03_methodology.tex` | Must remain aligned with frozen implementation |
| Results | IN PROGRESS | `paper/manuscript/source/04_experimental_results.tex` | Numerical claims require provenance checks |
| Discussion | IN PROGRESS | `paper/manuscript/source/05_discussion.tex` | Superiority and scope claims require review |
| Conclusion | IN PROGRESS | `paper/manuscript/source/06_conclusion.tex` | Must match supported contributions |
| References | IN PROGRESS | `paper/manuscript/source/references.bib` | DOI and publication metadata audit pending |
| Author biographies | IN PROGRESS | `paper/manuscript/source/07_back_matter.tex` | Final factual check pending |

## Figures and tables

| Item | Status | Notes |
|---|---|---|
| Figure inventory | IN PROGRESS | Every figure needs source, producing run, and hash |
| Table inventory | IN PROGRESS | Every numerical table needs canonical source data |
| Figure captions | IN PROGRESS | Must state partition, seed, and evidence role where relevant |
| Table captions and notes | IN PROGRESS | Must distinguish validation, guarded test, sensitivity, and post-hoc evidence |
| Graphical abstract | IN PROGRESS | Prepare only after the main message is stable |

## Evidence and reproducibility

| Item | Status | Notes |
|---|---|---|
| Claim-to-evidence matrix | IN PROGRESS | Created in `review/CLAIM_EVIDENCE_MATRIX.csv` |
| Paper artefact register | IN PROGRESS | Created in `manifests/PAPER_ARTIFACT_REGISTER.csv` |
| Supplementary-material register | IN PROGRESS | Created in `manifests/SUPPLEMENTARY_MATERIAL_REGISTER.csv` |
| Producing-run provenance | IN PROGRESS | Must identify source branch, commit, configuration, and outputs |
| Result-table verification | IN PROGRESS | Manuscript numbers must match verified tables |
| Figure-data verification | IN PROGRESS | Generated plots require source CSV or frozen artefact |
| Code availability scope | BLOCKED | Repository code is not yet sufficient for the current broad manuscript statement |
| Data availability statement | IN PROGRESS | Raw CERT data must not be redistributed |
| Reproduction instructions | IN PROGRESS | Must reflect only the code and artefacts actually released |

## Submission-facing material

| Item | Status | Notes |
|---|---|---|
| Supplementary-material package | IN PROGRESS | Build progressively from verified paper-facing artefacts |
| Graphical abstract | IN PROGRESS | Finalise after manuscript structure stabilises |
| Author metadata | IN PROGRESS | Names, affiliations, ORCID, emails and correspondence details |
| Keywords/index terms | IN PROGRESS | Final consistency check required |
| Conflict-of-interest statement | IN PROGRESS | Confirm final wording |
| Funding statement | IN PROGRESS | Confirm whether required |
| Reviewer response template | NOT REQUIRED | Activate after peer review |
| Final submission archive | BLOCKED | Created only after all readiness gates pass |

## Important interpretation controls

- Final teacher-anchored students are supported by CERT r5.2 train/validation evidence.
- Earlier guarded-test results must not be assigned to the final students.
- Attention–linear remains the stronger efficiency- and raw-calibration-oriented neural reference.
- ODST is an explanation-oriented differentiable head, not an overall predictively superior classifier.
- Routes and reached leaves are traceable internal evidence but are not independently proven faithful.
- Source ablation and Gaussian noise are degraded-input analyses, not adversarial-robustness experiments.
- Temporal partitions contain the same users and do not test entirely unseen-user generalisation.
- Overlapping sequence windows are correlated observations, not independent incidents.
