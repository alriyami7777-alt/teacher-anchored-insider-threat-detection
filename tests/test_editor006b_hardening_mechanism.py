from __future__ import annotations

from editor006b_harness.mechanism import (
    STATUS_DISABLED,
    STATUS_EXACT,
    mechanism_registry,
    paper_facing_mechanism_names,
)


def test_h10_h12_mechanism_registry_no_proxy():
    reg = mechanism_registry()
    paper = [m for m in reg["metrics"] if m.get("paper_facing")]
    assert all(m["status"] == STATUS_EXACT for m in paper)
    assert all("proxy" not in m["metric_name"].lower() for m in paper)
    assert all(m["status"] != "PROXY" for m in reg["metrics"])
    names = paper_facing_mechanism_names()
    assert "tree_contribution_pearson_proxy" not in names
    assert not any("proxy" in m["metric_name"].lower() for m in reg["metrics"])


def test_h11_unused_leaf_disabled_not_mean_mass():
    reg = mechanism_registry()
    unused = next(m for m in reg["metrics"] if m["metric_name"] == "unused_leaf_fraction")
    assert unused["status"] == STATUS_DISABLED
    assert unused["paper_facing"] is False
    assert unused["definition"] == "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE"
    assert unused["disabled_reason"] == "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE"
    assert "mean leaf mass" in str(unused["required_reference_artefact"]).lower() or "mean" in str(
        unused["required_reference_artefact"]
    ).lower()


def test_h12_tree_contribution_rho_disabled():
    reg = mechanism_registry()
    rho = next(m for m in reg["metrics"] if m["metric_name"] == "tree_contribution_rho")
    assert rho["status"] == STATUS_DISABLED
    assert rho["paper_facing"] is False
    assert rho["definition"] == "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE"
    assert rho["disabled_reason"] == "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE"
    core = set(reg["primary_incremental_anchoring"])
    assert core == {
        "student_teacher_logit_deviation",
        "route_mae",
        "route_kl",
        "hard_route_agreement",
    }
    for name in core:
        row = next(m for m in reg["metrics"] if m["metric_name"] == name)
        assert row["status"] == STATUS_EXACT
        assert row["paper_facing"] is True
    dom = next(m for m in reg["metrics"] if m["metric_name"] == "dominant_leaf_agreement")
    assert dom["status"] == STATUS_EXACT
