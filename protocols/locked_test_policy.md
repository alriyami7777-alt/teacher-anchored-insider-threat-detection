# Locked Test Policy

1. Freeze preprocessing, model configuration, threshold-selection method, and seed set before test access.
2. Do not inspect test labels during development.
3. Run the approved evaluator once.
4. Preserve prediction, metric, configuration, and commit provenance.
5. Do not retune after observing test outcomes.
6. Clearly identify which model variants were eligible for the locked test.
