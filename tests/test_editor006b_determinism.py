from __future__ import annotations

import numpy as np

from editor006b_harness.contracts import load_freeze_bundle, validate_contracts
from editor006b_harness.input_bundle import build_synthetic_bundle, gather_windows
from editor006b_harness.model_loaders import infer_neural, load_neural_checkpoint, state_hash


def test_t22_t23_determinism_and_immutability():
    bundle = load_freeze_bundle()
    validated = validate_contracts(bundle)
    deny = set(validated["deny_hashes"])
    allow = {str(a["expected_sha256"]) for a in validated["artefacts"]}
    art = next(a for a in validated["artefacts"] if a["family"] == "teacher_frozen_odst" and int(a["seed"]) == 42)
    syn = build_synthetic_bundle()
    x = gather_windows(syn["bundle"].scaled_dense_daily, syn["user_index"], syn["start_index"])
    loaded = load_neural_checkpoint(
        family="teacher_frozen_odst",
        seed=42,
        path=art["path"],
        expected_sha256=art["expected_sha256"],
        deny_hashes=deny,
        allow_hashes=allow,
    )
    before = loaded["state_hash"]
    s1 = infer_neural(loaded["model"], x)
    s2 = infer_neural(loaded["model"], x)
    after = state_hash(loaded["model"])
    assert before == after
    assert np.array_equal(s1, s2)
    assert np.all(np.isfinite(s1))
    assert np.all((s1 >= 0.0) & (s1 <= 1.0))
    assert s1.shape[0] == syn["n_sequences"]
