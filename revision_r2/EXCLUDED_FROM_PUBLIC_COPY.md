# Files withheld from the public copy of the evidence-branch code

The code under `src/`, `tests/`, `configs/` and `scripts/` was copied unchanged from `editor015-residual-complementarity` @ `d8e1d04`, except for the files below. They embed literal CERT insider identifiers as test fixtures or frozen constants. They remain on the historical branch.

- `tests/test_dataset_readiness.py`
- `tests/test_editor007b_r51_secondary_stress.py`
- `tests/test_editor007c1_r51_result_freeze.py`
- `scripts/run_editor007b_r51_bundle.py`

One comment in `src/cert_ground_truth.py` had an example filename containing an identifier; it was replaced by `<USERID>`. No code was changed.
