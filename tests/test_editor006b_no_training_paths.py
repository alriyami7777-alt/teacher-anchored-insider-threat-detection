from __future__ import annotations

from editor006b_harness.manifests import scan_harness_source


def test_t30_t32_forbidden_training_and_search_absent():
    result = scan_harness_source()
    assert result["status"] == "PASS"
    assert result["hits"] == []
