from __future__ import annotations

import numpy as np

from editor006b_harness.input_bundle import (
    build_synthetic_bundle,
    completed_and_endpoint_from_days,
    identifiers_sha,
)


def test_t24_t27_t28_t29_identifiers_and_views():
    syn = build_synthetic_bundle()
    assert identifiers_sha(syn["identifiers"]) == syn["identifiers_sha256"]
    mal = syn["bundle"].malicious_day_labels
    for row, s, u in zip(syn["identifiers"], syn["start_index"], syn["user_index"], strict=True):
        completed, endpoint = completed_and_endpoint_from_days(mal[int(u)], int(s))
        assert completed == row.completed_window_label
        assert endpoint == row.endpoint_label
        assert row.deoverlap_offset0_flag == int(int(s) % 20 == 0)
        assert row.sequence_id.startswith("seq_")
        assert row.user_id == syn["bundle"].user_ids[int(u)]
        assert row.decision_date == row.window_end_date
    mask = np.asarray([r.deoverlap_offset0_flag == 1 for r in syn["identifiers"]])
    offsets = {int(s) % 20 for s in syn["start_index"][mask]}
    assert offsets == {0}
