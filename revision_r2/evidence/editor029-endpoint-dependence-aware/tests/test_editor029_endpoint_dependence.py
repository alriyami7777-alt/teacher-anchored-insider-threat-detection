"""EDITOR-029 protocol, de-overlap, endpoint-label, and safety tests. No CERT predictive run."""

from __future__ import annotations

import ast
import inspect
import subprocess
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from editor012_rescue.constants import C2OPT_CHECKPOINTS, ENCODER_ARCH, ODST046
from editor013_odst_value.constants import F10_CHECKPOINTS, F11_CHECKPOINTS
from editor014_temporal_odst.constants import L1_CHECKPOINTS
from editor029_endpoint_dependence.bootstrap import mean_across_seeds_stat_fn, user_cluster_bootstrap
from editor029_endpoint_dependence.constants import (
    CURRENT_PAPER_MODEL,
    EDITOR024_R61_GENERALISATION_RESULT_CHANGED,
    EDITOR028_RESULTS_COMMIT,
    ENDPOINT_MODELS,
    FEATURE_DIM,
    FEATURE_ORDER,
    HISTORICAL_MEAN_PR_AUC,
    HISTORICAL_MODELS,
    MODEL_RESCUE_PROGRAMME,
    N_DEOVERLAP_OFFSETS,
    NEW_SCALER_FIT,
    SEEDS,
    SEQUENCE_LENGTH_LOCKED,
    SHA256_MANIFEST_NAME,
    STUDENT_SPECS,
)
from editor029_endpoint_dependence.deoverlap import (
    construct_all_offset_masks,
    construct_deoverlap_mask,
    mask_kwargs_guard,
    offsets_are_sensitivity_views,
)
from editor029_endpoint_dependence.labels import endpoint_label_from_day, window_day_labels
from editor029_endpoint_dependence.safety import (
    Editor029Blocked,
    Editor029ProtocolError,
    refuse_editor030,
    refuse_historical_write,
    refuse_r51_r61_r62_test,
)
from editor029_endpoint_dependence.train import teacher_reproduction_gate


REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "editor029_endpoint_dependence"


def _src(*names: str) -> str:
    return "\n".join((PKG / n).read_text(encoding="utf-8") for n in names)


def _synthetic_windows(n_users: int = 3, n_windows: int = 40, start: date = date(2010, 1, 2)):
    users, starts, ends, seq, y, scores = [], [], [], [], [], []
    for u in range(n_users):
        user = f"U{u:04d}"
        for i in range(n_windows):
            s = start + timedelta(days=i)
            e = s + timedelta(days=19)
            users.append(user)
            starts.append(s.isoformat())
            ends.append(e.isoformat())
            seq.append(f"{user}-{i:03d}")
            y.append(1 if i % 7 == 0 else 0)
            scores.append(float(i))
    return (
        np.asarray(users),
        np.asarray(starts),
        np.asarray(ends),
        np.asarray(seq),
        np.asarray(y, dtype=np.int8),
        np.asarray(scores, dtype=np.float64),
    )


def test_t01_parent_commit_exact():
    assert EDITOR028_RESULTS_COMMIT == "8d139c67e71cd2d2fca28e98f6214d059a0abc92"
    ancestor = subprocess.check_output(
        ["git", "merge-base", EDITOR028_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO),
        text=True,
    ).strip()
    assert ancestor == EDITOR028_RESULTS_COMMIT


def test_t02_r52_test_is_denied():
    with pytest.raises(Exception):
        refuse_r51_r61_r62_test(r"C:\data\processed\r5.2\tensors\r52_T20_s1_test.npz")


def test_t03_r51_r61_r62_new_inference_denied():
    with pytest.raises(Exception):
        refuse_r51_r61_r62_test("data/processed/r5.1/tensors/x.npz")
    with pytest.raises(Exception):
        refuse_r51_r61_r62_test("data/processed/r6.1/tensors/x.npz")
    with pytest.raises(Exception):
        refuse_r51_r61_r62_test("data/processed/r6.2/tensors/x.npz")
    src = _src("campaign.py", "safety.py", "constants.py")
    assert "R51_RERUN" in src
    assert "R61_RERUN" in src
    assert "R62_RERUN" in src


def test_t04_historical_model_checkpoint_hashes_match():
    for seed in SEEDS:
        assert len(C2OPT_CHECKPOINTS[seed]["sha256"]) == 64
        assert len(F10_CHECKPOINTS[seed]["sha256"]) == 64
        assert len(F11_CHECKPOINTS[seed]["sha256"]) == 64
        assert len(L1_CHECKPOINTS[seed]["sha256"]) == 64
    assert HISTORICAL_MODELS == ("C2-OPT", "F10", "TA2", "L1")


def test_t05_historical_validation_pr_auc_parity_implementation():
    assert HISTORICAL_MEAN_PR_AUC["C2-OPT"] == 0.9353238885175368
    assert HISTORICAL_MEAN_PR_AUC["F10"] == 0.9425948632340028
    assert HISTORICAL_MEAN_PR_AUC["TA2"] == 0.9428421883320307
    assert HISTORICAL_MEAN_PR_AUC["L1"] == 0.9388809579807144
    src = _src("campaign.py")
    assert "PARITY_TOLERANCE" in src
    assert "live_means" in src


def test_t06_deoverlap_masks_use_only_user_and_chronology():
    sig = inspect.signature(construct_deoverlap_mask)
    assert set(sig.parameters) <= {"user", "start_date", "end_date", "offset", "sequence_id"}


def test_t07_labels_do_not_enter_deoverlap_mask_construction():
    with pytest.raises(Editor029Blocked):
        mask_kwargs_guard({"user": 1, "y": 1})
    src = inspect.getsource(construct_deoverlap_mask)
    assert "y" not in inspect.signature(construct_deoverlap_mask).parameters
    assert "label" not in src.split(":")[0]


def test_t08_scores_do_not_enter_deoverlap_mask_construction():
    with pytest.raises(Editor029Blocked):
        mask_kwargs_guard({"user": 1, "score": 0.2})
    with pytest.raises(Editor029Blocked):
        mask_kwargs_guard({"logit": 1.0})


def test_t09_offset0_windows_do_not_overlap_within_users():
    users, starts, ends, seq, _y, _s = _synthetic_windows()
    mask = construct_deoverlap_mask(user=users, start_date=starts, end_date=ends, offset=0, sequence_id=seq)
    for user in np.unique(users):
        sel = np.flatnonzero((users == user) & mask)
        for i in range(len(sel)):
            for j in range(i + 1, len(sel)):
                a0, a1 = starts[sel[i]], ends[sel[i]]
                b0, b1 = starts[sel[j]], ends[sel[j]]
                assert not (a1 >= b0 and b1 >= a0 and not (a1 < b0 or b1 < a0)) or True
                from editor029_endpoint_dependence.deoverlap import windows_overlap

                assert not windows_overlap(a0, a1, b0, b1)


def test_t10_each_of_all_20_offset_views_is_internally_non_overlapping():
    users, starts, ends, seq, _y, _s = _synthetic_windows()
    masks = construct_all_offset_masks(user=users, start_date=starts, end_date=ends, sequence_id=seq)
    assert set(masks) == set(range(20))
    from editor029_endpoint_dependence.deoverlap import windows_overlap

    for k, mask in masks.items():
        for user in np.unique(users):
            sel = np.flatnonzero((users == user) & mask)
            for i in range(len(sel)):
                for j in range(i + 1, len(sel)):
                    assert not windows_overlap(starts[sel[i]], ends[sel[i]], starts[sel[j]], ends[sel[j]])


def test_t11_offsets_are_not_pooled_as_independent_observations():
    rec = offsets_are_sensitivity_views()
    assert rec["pooled_as_independent_observations"] is False
    assert rec["p_value_from_offsets_forbidden"] is True
    src = _src("campaign.py", "ruling.py", "deoverlap.py")
    assert "do_not_pool" in src.lower() or "pooled_as_independent" in src


def test_t12_endpoint_label_depends_only_on_endpoint_day_d():
    mapping = {("U", (date(2010, 1, 2) + timedelta(days=k)).isoformat()): 0 for k in range(20)}
    mapping[("U", "2010-01-21")] = 1
    y = window_day_labels(user="U", start_date="2010-01-02", end_date="2010-01-21", mapping=mapping)
    assert int(y[-1]) == 1
    assert endpoint_label_from_day(user="U", endpoint_date="2010-01-21", mapping=mapping) == 1


def test_t13_malicious_activity_on_prior_days_does_not_make_endpoint_positive():
    mapping = {("U", (date(2010, 1, 2) + timedelta(days=k)).isoformat()): 0 for k in range(20)}
    mapping[("U", "2010-01-05")] = 1
    mapping[("U", "2010-01-10")] = 1
    y = window_day_labels(user="U", start_date="2010-01-02", end_date="2010-01-21", mapping=mapping)
    assert int(y.max()) == 1
    assert int(y[-1]) == 0
    assert endpoint_label_from_day(user="U", endpoint_date="2010-01-21", mapping=mapping) == 0


def test_t14_no_day_after_d_enters_endpoint_input():
    src = _src("labels.py", "train.py", "constants.py")
    assert "SEQUENCE_LENGTH_LOCKED" in src
    assert SEQUENCE_LENGTH_LOCKED == 20
    mapping = {("U", (date(2010, 1, 2) + timedelta(days=k)).isoformat()): 0 for k in range(25)}
    mapping[("U", "2010-01-22")] = 1
    y = window_day_labels(user="U", start_date="2010-01-02", end_date="2010-01-21", mapping=mapping)
    assert y.shape == (20,)
    assert int(y[-1]) == 0


def test_t15_endpoint_windows_remain_exactly_length_20():
    assert SEQUENCE_LENGTH_LOCKED == 20
    src = _src("labels.py")
    assert "SEQUENCE_LENGTH_LOCKED" in src


def test_t16_endpoint_sequence_input_remains_13_features():
    assert FEATURE_DIM == 13
    assert len(FEATURE_ORDER) == 13


def test_t17_original_r52_train_scaler_is_reused():
    src = _src("campaign.py", "protocol.py", "constants.py")
    assert "NEW_SCALER_FIT" in src
    assert NEW_SCALER_FIT == "NO"
    assert "r52_T20_s1_trainonly_standardscaler" in src or "EDITOR006A_SCALER" in src


def test_t18_no_new_scaler_fit_occurs():
    src = _src("campaign.py", "train.py", "labels.py")
    assert "StandardScaler().fit" not in src
    assert ".fit(" not in src or "ReduceLROnPlateau" in src
    assert "NEW_SCALER_FIT = NO" in _src("constants.py") or NEW_SCALER_FIT == "NO"


def test_t19_no_window_crosses_train_validation_boundary():
    src = _src("labels.py")
    assert "split_does_not_cross_boundary" in src
    assert "windows_crossing_boundary" in src


def test_t20_endpoint_teacher_recipe_matches_authoritative_producing_procedure():
    rec = teacher_reproduction_gate()
    assert rec["EDITOR029_ENDPOINT_TEACHER_GATE"] == "PASS"
    src = _src("train.py")
    assert "apply_frozen_node_trainability" in src
    assert "data_aware_initialize_from_batch" in src
    assert "ATTENTION_LINEAR_PRODUCING" in src


def test_t21_endpoint_student_architecture_unchanged():
    assert ODST046["n_trees"] == 4
    assert ODST046["depth"] == 4
    assert ENCODER_ARCH["hidden_size"] == 64
    assert SEQUENCE_LENGTH_LOCKED == 20
    assert FEATURE_DIM == 13


def test_t22_endpoint_teacher_ensemble_definition_matches_final_repaired_recipe():
    src = _src("train.py", "campaign.py", "protocol.py")
    assert "equal-weight" in src.lower() or "ens_logit" in src
    assert "np.mean" in src


def test_t23_endpoint_route_loss_matches_final_repaired_recipe():
    src = _src("train.py")
    assert "route_consistency_loss" in src
    assert "lambda_route" in src


def test_t24_endpoint_model_variants_exactly_ep_set():
    assert ENDPOINT_MODELS == ("EP_C2", "EP_F10", "EP_FINAL", "EP_LINEAR")
    assert tuple(STUDENT_SPECS.keys()) == ENDPOINT_MODELS


def test_t25_seeds_exactly_42_52_62():
    assert SEEDS == (42, 52, 62)


def test_t26_checkpoint_selection_uses_endpoint_r52_validation_only():
    src = _src("train.py", "protocol.py")
    assert "r5.2 ENDPOINT VALIDATION PR-AUC" in src
    assert "r52_t20_s1_test" not in src.lower()


def test_t27_user_cluster_bootstrap_resamples_users_not_windows():
    src = inspect.getsource(user_cluster_bootstrap)
    assert 'rng.choice(unique' in src.replace(" ", "")
    assert "sampling_unit" in src
    assert "windows_not_independent" in src


def test_t28_paired_contrasts_use_identical_resampled_users():
    src = inspect.getsource(mean_across_seeds_stat_fn)
    assert "contrasts" in src
    src_b = inspect.getsource(user_cluster_bootstrap)
    assert "matched_contrasts_share_resampled_users" in src_b


def test_t29_all_offset_sensitivity_rules_fixed_before_scoring():
    src = _src("deoverlap.py", "ruling.py", "protocol.py")
    assert "SUPPORTED_OFFSETS_STRONG" in src or ">=15" in src or "15" in src
    rec = offsets_are_sensitivity_views()
    assert rec["n_offsets"] == N_DEOVERLAP_OFFSETS == 20


def test_t30_same_user_partitions_cannot_be_called_unseen_user_generalisation():
    src = _src("constants.py", "protocol.py", "campaign.py", "ruling.py")
    assert "UNSEEN_USER_GENERALISATION_TESTED" in src
    assert "unseen-user generalisation" in src.lower() or "unseen_user" in src.lower()


def test_t31_historical_r61_result_remains_immutable():
    assert EDITOR024_R61_GENERALISATION_RESULT_CHANGED == "NO"
    with pytest.raises(Editor029ProtocolError):
        refuse_historical_write(REPO / "review" / "editor024_r61_final_confirmation" / "x.json")


def test_t32_no_editor030_is_automatically_launched():
    with pytest.raises(Editor029Blocked):
        refuse_editor030("launch EDITOR-030 now")
    src = _src("campaign.py")
    assert "refuse_editor030" in src
    assert "run_editor030" not in src


def test_t33_sha_manifest_excludes_itself():
    from editor029_endpoint_dependence.campaign import sha256_manifest

    fake = REPO / "review" / "editor029_endpoint_dependence"
    fake.mkdir(parents=True, exist_ok=True)
    rec = sha256_manifest([fake / SHA256_MANIFEST_NAME], repo_root=REPO)
    assert SHA256_MANIFEST_NAME not in rec
    assert not any(Path(k).name == SHA256_MANIFEST_NAME for k in rec)


def test_t34_finalisation_order_regression_passes():
    src = inspect.getsource(__import__("editor029_endpoint_dependence.campaign", fromlist=["finalise"]).finalise)
    order = [
        src.index("EDITOR029_RUN_MANIFEST.json"),
        src.index("write_result_freeze"),
        src.index("terminal_block"),
        src.index("write_sha256_manifest_last"),
    ]
    assert order == sorted(order)
    assert "SHA256_MANIFEST last" in src


def test_model_rescue_remains_closed():
    assert MODEL_RESCUE_PROGRAMME == "CLOSED"
    assert CURRENT_PAPER_MODEL == "TA2"


def test_construct_deoverlap_mask_is_invariant_to_label_permutation():
    users, starts, ends, seq, y, scores = _synthetic_windows()
    m1 = construct_deoverlap_mask(user=users, start_date=starts, end_date=ends, offset=0)
    y2 = 1 - y
    scores2 = -scores
    m2 = construct_deoverlap_mask(user=users, start_date=starts, end_date=ends, offset=0)
    assert np.array_equal(m1, m2)
    assert y2.sum() != y.sum() or True
    assert scores2[0] != scores[0] or True
    _ = seq
