from __future__ import annotations

from editor006b_harness.contracts import load_freeze_bundle, validate_contracts
from editor006b_harness.model_loaders import load_neural_checkpoint, load_rf, load_xgb


def test_t14_t18_strict_load_all_families():
    bundle = load_freeze_bundle()
    validated = validate_contracts(bundle)
    deny = set(validated["deny_hashes"])
    allow = {str(a["expected_sha256"]) for a in validated["artefacts"]}
    for art in validated["artefacts"]:
        family, seed = art["family"], int(art["seed"])
        if family in {"teacher_frozen_odst", "C2", "C5_original_paper", "attention_linear"}:
            loaded = load_neural_checkpoint(
                family=family,
                seed=seed,
                path=art["path"],
                expected_sha256=art["expected_sha256"],
                deny_hashes=deny,
                allow_hashes=allow,
            )
            assert loaded["missing_keys"] == []
            assert loaded["unexpected_keys"] == []
            assert loaded["requires_grad_any"] is False
        elif family == "RF_40":
            load_rf(
                seed=seed,
                path=art["path"],
                expected_sha256=art["expected_sha256"],
                deny_hashes=deny,
                allow_hashes=allow,
            )
        elif family == "XGBoost_40":
            load_xgb(
                seed=seed,
                path=art["path"],
                expected_sha256=art["expected_sha256"],
                deny_hashes=deny,
                allow_hashes=allow,
            )
        else:
            raise AssertionError(family)
