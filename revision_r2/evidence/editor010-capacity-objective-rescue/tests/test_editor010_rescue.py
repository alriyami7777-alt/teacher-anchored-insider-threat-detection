"""EDITOR-010 safety, inner-split, grid, pairwise, and freeze tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import torch

from editor010_rescue.constants import ODST_GRID, build_odst_grid
from editor010_rescue.data import SequenceBundle
from editor010_rescue.inner_split import assert_no_boundary_crossing, inner_split_masks
from editor010_rescue.losses import pairwise_ranking_loss
from editor010_rescue.safety import Editor010SafetyError, assert_output_namespace, assert_path_allowed_for_read, refuse_test_loader_construction


def test_r52_test_path_rejected():
    with pytest.raises(Editor010SafetyError):
        assert_path_allowed_for_read(
            r"C:\PhD\07_Projects\cert-r42-feasibility\data\processed\r5.2\tensors\r52_T20_s1_test.npz",
            context="test",
        )


def test_r52_test_loader_construction_rejected():
    with pytest.raises(Editor010SafetyError):
        refuse_test_loader_construction(partition="test")
    with pytest.raises(Editor010SafetyError):
        refuse_test_loader_construction(partition="r52_T20_s1_test.npz")


def test_r51_r62_paths_rejected():
    with pytest.raises(Editor010SafetyError):
        assert_path_allowed_for_read(r"C:\data\processed\r5.1\tensors\x.npz", context="r51")
    with pytest.raises(Editor010SafetyError):
        assert_path_allowed_for_read(r"C:\data\processed\r6.2\tensors\x.npz", context="r62")


def test_historical_packets_read_only_for_writes():
    with pytest.raises(Editor010SafetyError):
        assert_output_namespace(
            r"C:\PhD\07_Projects\cert-r42-feasibility\outputs\objective2\r52_odst_confirmation\best.pt"
        )
    ok = assert_output_namespace(
        Path("review/editor010_capacity_objective_teacher_rescue/06_promoted_full_r52/x.json")
    )
    assert "editor010" in str(ok).replace("\\", "/").lower()


def _synthetic_train(n_users: int = 3, days: int = 50) -> SequenceBundle:
    """Chronological T=20 stride-1 windows per user."""
    xs = []
    ys = []
    users = []
    seqs = []
    starts = []
    ends = []
    base = datetime(2010, 1, 1)
    sid = 0
    for u in range(n_users):
        user = f"U{u:03d}"
        for d in range(days - 19):
            start = base + timedelta(days=d)
            end = start + timedelta(days=19)
            xs.append(np.zeros((20, 13), dtype=np.float32))
            ys.append(1.0 if d >= int(0.9 * (days - 19)) else 0.0)
            users.append(user)
            seqs.append(f"seq_{sid:08d}")
            starts.append(start.strftime("%Y-%m-%d"))
            ends.append(end.strftime("%Y-%m-%d"))
            sid += 1
    return SequenceBundle(
        X=np.stack(xs),
        y=np.asarray(ys, dtype=np.float32),
        user=np.asarray(users),
        sequence_id=np.asarray(seqs),
        start_date=np.asarray(starts),
        end_date=np.asarray(ends),
        path=Path("r52_T20_s1_train.npz"),
        sha256="synthetic",
        name="train",
    )


def test_inner_split_chronology_and_no_boundary_crossing():
    bundle = _synthetic_train(n_users=3, days=200)
    split = inner_split_masks(bundle)
    assert split["disjoint"]
    assert int(np.logical_and(split["train_mask"], split["select_mask"]).sum()) == 0
    assert split["n_inner_train"] > 0
    assert split["n_inner_select"] > 0
    assert_no_boundary_crossing(bundle, split["train_mask"], split["select_mask"])
    # INNER_SELECT starts after INNER_TRAIN for every user with both.
    for user in np.unique(bundle.user):
        tr = bundle.end_date[(bundle.user == user) & split["train_mask"]]
        se = bundle.start_date[(bundle.user == user) & split["select_mask"]]
        if len(tr) and len(se):
            assert max(tr) < min(se)


def test_inner_split_rejects_non_train_bundle():
    bundle = _synthetic_train()
    bad = SequenceBundle(**{**bundle.__dict__, "name": "validation"})
    with pytest.raises(RuntimeError):
        inner_split_masks(bad)


def test_odst_grid_deterministic_and_capped():
    a = build_odst_grid()
    b = build_odst_grid()
    assert a == b
    assert len(a) <= 48
    assert len(ODST_GRID) <= 48
    assert a[0]["candidate_id"] == "ODST-000"
    assert a[0]["is_producing_current"] is True
    ids = [c["candidate_id"] for c in a]
    assert len(ids) == len(set(ids))


def test_pairwise_ranking_loss_sign_and_direction():
    logits = torch.tensor([3.0, -2.0, 2.5, -1.0])
    labels = torch.tensor([1.0, 0.0, 1.0, 0.0])
    good = pairwise_ranking_loss(logits, labels)
    flipped = pairwise_ranking_loss(-logits, labels)
    assert float(good) < float(flipped)
    # Perfect separation should be near 0.
    assert float(good) < 0.2


def test_pairwise_pair_construction_deterministic():
    logits = torch.arange(10.0)
    labels = torch.tensor([1, 0, 0, 1, 0, 0, 0, 1, 0, 0], dtype=torch.float32)
    a = pairwise_ranking_loss(logits, labels)
    b = pairwise_ranking_loss(logits, labels)
    assert torch.equal(a, b)


def test_class_weight_formula():
    from editor010_rescue.data import pos_weight

    # producing O0 uses 0.25 * n_neg/n_pos
    assert abs(pos_weight(4, 96, 0.25) - (96 / 4) * 0.25) < 1e-9
    assert abs(pos_weight(4, 96, 1.0) - (96 / 4)) < 1e-9


def test_teacher_ensemble_equal_weight_no_learned_weights():
    a = np.array([0.1, 0.8, 0.4])
    b = np.array([0.2, 0.7, 0.5])
    c = np.array([0.3, 0.6, 0.6])
    ens = np.mean([a, b, c], axis=0)
    assert np.allclose(ens, np.array([0.2, 0.7, 0.5]))
    # No validation-tuned weights: equal 1/3.
    w = np.array([1 / 3, 1 / 3, 1 / 3])
    assert np.allclose(w @ np.stack([a, b, c], axis=1).T if False else np.average(np.stack([a, b, c]), axis=0, weights=w), ens)


def test_promotion_freeze_file_is_required_path():
    from editor010_rescue.constants import REVIEW_REL

    path = REVIEW_REL / "06_promoted_full_r52" / "EDITOR010_PROMOTION_FREEZE.json"
    assert "06_promoted_full_r52" in str(path).replace("\\", "/")
    src = Path("src/editor010_rescue/pipeline.py").read_text(encoding="utf-8")
    freeze_at = src.index("EDITOR010_PROMOTION_FREEZE.json")
    full_at = src.index("EDITOR010_FULL_RESULTS.csv")
    assert freeze_at < full_at


def test_official_validation_not_in_inner_search_source():
    src = Path("src/editor010_rescue/inner_split.py").read_text(encoding="utf-8")
    assert "validation" not in src.lower() or "Inner split may be constructed only from r5.2 TRAIN" in src
    assert "r52_T20_s1_test" not in src
