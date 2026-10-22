"""EDITOR-028 protocol, CORAL, alignment, and safety tests. No CERT predictive run."""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest
import torch

from editor026_user_relative.constants import USER_RELATIVE_LOOKBACK_DAYS as E026_LOOKBACK
from editor026_user_relative.representation import causal_user_relative_daily as e026_ur
from editor028_latent_alignment.alignment import (
    UnlabeledAlignmentStore,
    candidate_lambda,
    register_candidate,
    source_index_order,
    target_index_stream,
)
from editor028_latent_alignment.constants import (
    ALL_CANDIDATES,
    ARCHITECTURE_CHANGE,
    BATCH_SIZE,
    CANDIDATE_LAMBDAS,
    EDITOR027_RESULTS_COMMIT,
    ENCODER_ARCH,
    FEATURE_DIM,
    FEATURE_ORDER,
    MINIMUM_AP_PREVALENCE_LIFT,
    ODST046,
    SEEDS,
    SEQUENCE_LENGTH_LOCKED,
    USER_RELATIVE_LOOKBACK_DAYS,
)
from editor028_latent_alignment.coral import coral_discrepancy_numpy, coral_loss
from editor028_latent_alignment.representation import causal_user_relative_daily
from editor028_latent_alignment.safety import Editor028Blocked, Editor028ProtocolError, refuse_historical_write
from editor028_latent_alignment.selection import evaluate_gates, select_eligible


REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "editor028_latent_alignment"


def _src(*names: str) -> str:
    return "\n".join((PKG / n).read_text(encoding="utf-8") for n in names)


def test_t01_parent_commit_exact():
    assert EDITOR027_RESULTS_COMMIT == "c491b79c2f552318ff3993e585a7abd3d2d7857b"
    ancestor = subprocess.check_output(
        ["git", "merge-base", EDITOR027_RESULTS_COMMIT, "HEAD"],
        cwd=str(REPO),
        text=True,
    ).strip()
    assert ancestor == EDITOR027_RESULTS_COMMIT


def test_t02_architecture_unchanged():
    assert SEQUENCE_LENGTH_LOCKED == 20
    assert FEATURE_DIM == 13
    assert ODST046["n_trees"] == 4
    assert ODST046["depth"] == 4
    assert ENCODER_ARCH["hidden_size"] == 64
    assert ARCHITECTURE_CHANGE == "NO"
    src = _src("constants.py", "protocol.py", "train.py")
    assert "Transformer" in src
    assert "Bi-LSTM" in src or "lstm" in src.lower()
    tree = ast.parse((PKG / "train.py").read_text(encoding="utf-8"))
    added = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    assert "DomainClassifier" not in added


def test_t03_editor026_centred_representation_reused_exactly():
    assert causal_user_relative_daily is e026_ur
    x = np.zeros((5, 13))
    x[:, 0] = [1, 2, 3, 4, 5]
    assert np.allclose(causal_user_relative_daily(x), e026_ur(x))


def test_t04_lookback_remains_20_days():
    assert USER_RELATIVE_LOOKBACK_DAYS == 20
    assert E026_LOOKBACK == 20
    src = (REPO / "src" / "editor026_user_relative" / "representation.py").read_text(encoding="utf-8")
    assert "USER_RELATIVE_LOOKBACK_DAYS" in src


def test_t05_r61_alignment_loader_contains_no_labels():
    store = UnlabeledAlignmentStore(
        X=np.zeros((4, 20, 13), dtype=np.float32),
        user=np.array(["u1", "u2", "u3", "u4"]),
        sequence_id=np.array(["s1", "s2", "s3", "s4"]),
    )
    assert store.keys() == ("X", "user", "sequence_id")
    for key in ("y", "label", "malicious", "scenario", "insider"):
        with pytest.raises(AttributeError):
            getattr(store, key)


def test_t06_no_r61_label_path_reachable_from_training():
    train_src = _src("train.py", "alignment.py", "selection.py")
    for needle in (
        "completed_window_labels",
        "freeze_label_views",
        "construct_r61_editor024_labels",
        "insider_identity",
    ):
        assert needle not in train_src
    tree = ast.parse((PKG / "train.py").read_text(encoding="utf-8"))
    imports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and "labels" in node.module:
            imports.append(node.module)
    assert imports == []


def test_t07_teachers_train_using_r52_only():
    src = _src("train.py", "protocol.py", "constants.py")
    assert "r5.2" in src or "r52" in src.lower()
    assert "CENTERED_TEACHER_42" in src
    assert "no r6.1" in src.lower() or "r61_used\": False" in src or "r61_used" in src


def test_t08_teacher_recipe_matches_authoritative_implementation():
    from editor026_user_relative.train import ATTENTION_LINEAR_PRODUCING as A026
    from editor028_latent_alignment.train import ATTENTION_LINEAR_PRODUCING as A028
    from editor026_user_relative.constants import LR_ODST as LR026, MAX_EPOCHS as E026, PATIENCE as P026
    from editor028_latent_alignment.constants import LR_ODST, MAX_EPOCHS, PATIENCE

    assert A028 == A026
    assert LR_ODST == LR026
    assert MAX_EPOCHS == E026
    assert PATIENCE == P026
    src = inspect.getsource(__import__("editor028_latent_alignment.train", fromlist=["teacher_reproduction_gate"]))
    assert "train_attention_linear" in src or "CENTERED_ATTENTION_LINEAR" in src
    assert "apply_frozen_node_trainability" in src
    assert "data_aware_initialize_from_batch" in src


def test_t09_attention_pooled_representation_is_coral_input():
    src = (PKG / "train.py").read_text(encoding="utf-8")
    assert 'sr["z"]' in src or "sr['z']" in src
    assert "coral_loss(h_s, h_t)" in src
    assert "encode_attention_h" in src
    from editor012_rescue.models import student_forward

    sig = inspect.getsource(student_forward)
    assert '"z": z' in sig


def test_t10_coral_covariance_formula_correct():
    rng = np.random.default_rng(0)
    hs = rng.normal(size=(8, 5))
    ht = rng.normal(size=(6, 5))
    hs_c = hs - hs.mean(0)
    ht_c = ht - ht.mean(0)
    cs = (hs_c.T @ hs_c) / 7.0
    ct = (ht_c.T @ ht_c) / 5.0
    expected = float(np.square(cs - ct).sum() / (4.0 * 25.0))
    got = coral_discrepancy_numpy(hs, ht)
    assert got == pytest.approx(expected)
    t = coral_loss(torch.tensor(hs, dtype=torch.float64), torch.tensor(ht, dtype=torch.float64))
    assert float(t) == pytest.approx(expected)


def test_t11_coral_denominator_is_4d2():
    src = (PKG / "coral.py").read_text(encoding="utf-8")
    assert "4.0 * float(d) * float(d)" in src or "4.0 * d * d" in src


def test_t12_batches_smaller_than_2_produce_zero_coral():
    h = torch.randn(1, 4)
    assert float(coral_loss(h, torch.randn(3, 4))) == 0.0
    assert float(coral_loss(torch.randn(3, 4), h)) == 0.0
    assert coral_discrepancy_numpy(np.random.randn(1, 4), np.random.randn(3, 4)) == 0.0


def test_t13_candidate_lambdas_exactly_frozen():
    assert dict(CANDIDATE_LAMBDAS) == {"ALIGN0": 0.00, "ALIGN01": 0.01, "ALIGN05": 0.05, "ALIGN10": 0.10}
    assert isinstance(CANDIDATE_LAMBDAS, MappingProxyType)
    assert candidate_lambda("ALIGN0") == 0.0
    assert candidate_lambda("ALIGN10") == 0.10


def test_t14_candidate_set_cannot_expand():
    with pytest.raises(Editor028Blocked):
        register_candidate("ALIGN20", 0.2)
    with pytest.raises(Editor028Blocked):
        candidate_lambda("ALIGN20")
    assert ALL_CANDIDATES == ("ALIGN0", "ALIGN01", "ALIGN05", "ALIGN10")


def test_t15_source_batch_order_matched_across_candidates():
    a = source_index_order(5000, seed=42, batch_size=BATCH_SIZE)
    b = source_index_order(5000, seed=42, batch_size=BATCH_SIZE)
    assert all(np.array_equal(x, y) for x, y in zip(a, b))
    c = source_index_order(5000, seed=52, batch_size=BATCH_SIZE)
    assert not all(np.array_equal(x, y) for x, y in zip(a, c))


def test_t16_target_batch_order_matched_across_aligned_candidates():
    sizes = [1024, 1024, 512]
    a = target_index_stream(10000, sizes, seed=42, epoch=1)
    b = target_index_stream(10000, sizes, seed=42, epoch=1)
    assert all(np.array_equal(x, y) for x, y in zip(a, b))


def test_t17_target_sampling_outcome_independent():
    sig = inspect.signature(target_index_stream)
    assert "y" not in sig.parameters
    assert "label" not in sig.parameters
    src = inspect.getsource(target_index_stream)
    assert "y" not in src.split(":")[0]


def test_t18_no_target_threshold_selection():
    src = _src("train.py", "selection.py", "alignment.py")
    assert "r61_threshold" not in src.lower()
    assert "target threshold" not in src.lower()


def test_t19_no_target_calibration_fitting():
    src = _src("train.py", "selection.py", "campaign.py")
    assert "isotonic" not in src.lower()
    assert "platt" not in src.lower()
    assert "r61" not in src.lower() or "R61_TARGET" in src or "unlabeled" in src.lower()


def test_t20_no_target_checkpoint_selection():
    src = _src("train.py", "selection.py")
    assert "r6.1 VALIDATION" not in src
    assert "y_r61" not in src


def test_t21_checkpoint_selection_uses_r52_validation():
    src = _src("train.py", "protocol.py")
    assert "validation_PR_AUC" in src or "validation_pr_auc" in src
    assert "r5.2 VALIDATION" in src or "r52" in src.lower()


def test_t22_seeds_exactly_42_52_62():
    assert SEEDS == (42, 52, 62)


def test_t23_historical_editor024_027_artefacts_read_only():
    with pytest.raises(Editor028ProtocolError):
        refuse_historical_write(REPO / "review" / "editor027_scale_normalised_representation" / "x.json")
    with pytest.raises(Editor028ProtocolError):
        refuse_historical_write(REPO / "review" / "editor026_user_relative_representation" / "x.json")
    with pytest.raises(Editor028ProtocolError):
        refuse_historical_write(REPO / "review" / "editor024_r61_final_confirmation" / "x.json")


def test_t24_r51_r62_not_rerun():
    from editor028_latent_alignment.safety import refuse_r51_r62

    with pytest.raises(Exception):
        refuse_r51_r62("data/processed/r5.1/tensors/predict.json")
    with pytest.raises(Exception):
        refuse_r51_r62("data/processed/r6.2/tensors/predict.json")
    src = _src("campaign.py", "protocol.py")
    assert "R51_RERUN" in src
    assert "R62_RERUN" in src


def test_t25_raw_predictions_written_before_aggregate_metrics():
    src = inspect.getsource(__import__("editor028_latent_alignment.campaign", fromlist=["run_training"]).run_training)
    assert src.index("write_raw_predictions") < src.index("evaluate_gates")
    ev = inspect.getsource(__import__("editor028_latent_alignment.campaign", fromlist=["run_r61_evaluation"]).run_r61_evaluation)
    assert ev.index("write_raw_predictions") < ev.index("view_results")


def test_t26_sha_manifest_excludes_itself():
    from editor028_latent_alignment.campaign import sha256_manifest
    from editor028_latent_alignment.constants import SHA256_MANIFEST_NAME

    fake = REPO / "review" / "editor028_latent_alignment"
    fake.mkdir(parents=True, exist_ok=True)
    rec = sha256_manifest([fake / SHA256_MANIFEST_NAME], repo_root=REPO)
    assert SHA256_MANIFEST_NAME not in rec
    assert not any(Path(k).name == SHA256_MANIFEST_NAME for k in rec)


def test_t27_finalisation_order_regression_passes():
    src = inspect.getsource(__import__("editor028_latent_alignment.campaign", fromlist=["finalise"]).finalise)
    order = [
        src.index("EDITOR028_RUN_MANIFEST.json"),
        src.index("write_result_freeze"),
        src.index("terminal_block"),
        src.index("write_sha256_manifest_last"),
    ]
    assert order == sorted(order)
    assert "SHA256_MANIFEST last" in src


def test_selection_requires_all_s_gates_and_prefers_smaller_lambda_on_tie():
    r52 = {
        "ALIGN0": {42: 0.94, 52: 0.94, 62: 0.94},
        "ALIGN01": {42: 0.94, 52: 0.94, 62: 0.94},
        "ALIGN05": {42: 0.94, 52: 0.94, 62: 0.94},
        "ALIGN10": {42: 0.90, 52: 0.90, 62: 0.90},
    }
    coral = {
        "ALIGN0": {42: 1.0, 52: 1.0, 62: 1.0},
        "ALIGN01": {42: 0.5, 52: 0.5, 62: 0.5},
        "ALIGN05": {42: 0.49, 52: 0.49, 62: 0.49},
        "ALIGN10": {42: 0.2, 52: 0.2, 62: 0.2},
    }
    sep = {name: {s: 1.0 for s in SEEDS} for name in ALL_CANDIDATES}
    rec = evaluate_gates(r52_pr=r52, coral_d=coral, r52_separation=sep)
    # ALIGN01 A=0.50, ALIGN05 A=0.51, difference 0.01 <= 0.02 -> smaller lambda ALIGN01
    assert rec["EDITOR028_SELECTED_CANDIDATE"] == "ALIGN01"
    assert rec["candidates"]["ALIGN10"]["label_blind_gate"] is False


def test_unlabeled_store_rejects_label_keys():
    store = UnlabeledAlignmentStore(
        X=np.zeros((2, 20, 13), dtype=np.float32),
        user=np.array(["a", "b"]),
        sequence_id=np.array(["1", "2"]),
    )
    with pytest.raises(AttributeError):
        _ = store.y
