# Phase 3 frozen-model explanation evidence

Run `run_phase3.py` with the existing Python 3.11 interpreter. The worker polls
the Phase 2 report every 600 seconds and does not use the GPU or load original
CERT tensors until the exact freeze marker is the final line. No model training
or Git operations are present. Original repositories are imported read only,
with bytecode writes disabled. CPU threads are limited to two.

The original r5.2 validation population is 64,000 windows / 2,000 users, as
clarified by Claude. The 484 / 151 cohort belongs to r4.2 and is not used.
All outputs use pseudonyms. Never print raw dataset arrays or identifiers.

The original validation tensors are evaluated only with the six original frozen
models. Phase 2 HOLDOUT files, models and identities are not read by this worker,
apart from the required model-freeze report gate. HOLDOUT scoring is a separate,
explicit future step.

`test_phase3.py` uses synthetic data on CPU. `phase3_smoke.py` uses two synthetic
inputs, CPU-only original-model loaders and frozen hashes. The HOLDOUT scoring
script is parsed for syntax but must not be run during Phase 3, including help.

The holdout script requires a hash-bound manifest and training-derived references
at future authorised scoring time. Its dependency hashes are in CODE_HASHES.json.

Output: C:/PhD/04_Journal_Papers/Latest IEEE Access Paper July 2026/R2_revision/explanation/
