from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from editor006b_harness.contracts import load_freeze_bundle, validate_contracts
from editor006b_harness.input_bundle import build_synthetic_bundle, gather_windows
from editor006b_harness.metrics import analyse_views
from editor006b_harness.safety import HarnessProtocolError
from editor006b_harness.scoring import require_score_complete, write_scores_phase


def test_t25_t26_raw_scores_before_metrics(tmp_path: Path):
    bundle = load_freeze_bundle()
    validated = validate_contracts(bundle)
    deny = set(validated["deny_hashes"])
    syn = build_synthetic_bundle()
    x = gather_windows(syn["bundle"].scaled_dense_daily, syn["user_index"], syn["start_index"])
    with pytest.raises(HarnessProtocolError, match="SCORE_COMPLETE"):
        require_score_complete(tmp_path / "empty", expected_n=syn["n_sequences"])
    write_scores_phase(
        artefacts=validated["artefacts"],
        deny_hashes=deny,
        x=x,
        out_dir=tmp_path,
        identifiers_sha256=syn["identifiers_sha256"],
        input_bundle_sha256="0" * 64,
        thresholds=validated["thresholds"],
        identifiers=syn["identifiers"],
    )
    man = require_score_complete(tmp_path, expected_n=syn["n_sequences"])
    assert man["complete"] is True
    assert len(man["scores"]) == 18
    protocol = analyse_views(out_dir=tmp_path, identifiers=syn["identifiers"], expected_n=syn["n_sequences"])
    assert protocol["not_scientific_results"] is True
    assert protocol["score_complete_validated"] is True
    assert protocol["sequence_metadata"] is not None
    assert len(protocol["sequence_metadata"]["records"]) == syn["n_sequences"]
    # finite / [0,1]
    for rec in man["scores"]:
        arr = np.load(rec["path"])
        assert np.all(np.isfinite(arr))
        assert np.all(arr >= 0.0) and np.all(arr <= 1.0)
        assert arr.shape[0] == syn["n_sequences"]
