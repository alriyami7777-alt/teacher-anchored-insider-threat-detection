#!/usr/bin/env python3
"""Focused unit tests for Stage 1 / 1.1 sequence–ensemble model."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import torch
import torch.nn as nn

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from models.sequence_ensemble import (  # noqa: E402
    SequenceEnsembleModel,
    SoftDecisionForest,
    TemporalAttention,
    assert_component_gradients,
    assert_model_outputs,
    compute_validation_diagnostics,
    load_encoder_checkpoint,
)


class TestTemporalAttention(unittest.TestCase):
    def test_weights_nonneg_and_sum_to_one(self) -> None:
        attn = TemporalAttention(hidden_dim=8, attention_dim=4)
        h = torch.randn(5, 20, 8)
        z, w = attn(h)
        self.assertEqual(tuple(z.shape), (5, 8))
        self.assertEqual(tuple(w.shape), (5, 20))
        self.assertTrue((w >= 0).all())
        self.assertTrue(torch.allclose(w.sum(dim=1), torch.ones(5), atol=1e-5))


class TestSoftDecisionForest(unittest.TestCase):
    def test_forest_logit_shape_and_routing(self) -> None:
        forest = SoftDecisionForest(in_dim=16, n_trees=3, depth=2)
        x = torch.randn(7, 16)
        logit, routing = forest(x)
        self.assertEqual(tuple(logit.shape), (7,))
        self.assertEqual(len(routing), 3)
        for r in routing:
            self.assertTrue(torch.isfinite(r["p_left"]).all())
            self.assertTrue(
                torch.allclose(r["p_left"] + r["p_right"], torch.ones_like(r["p_left"]), atol=1e-5)
            )
            leaf_sum = r["leaf_probs"].sum(dim=1)
            self.assertTrue(torch.allclose(leaf_sum, torch.ones_like(leaf_sum), atol=1e-4))


class TestHeadsAndAggregation(unittest.TestCase):
    def _forward(self, head: str, agg: str) -> tuple[torch.Tensor, dict]:
        model = SequenceEnsembleModel(
            input_dim=13,
            hidden_size=16,
            dropout=0.0,
            attention_dim=8,
            n_trees=2,
            tree_depth=2,
            classification_head=head,
            temporal_aggregation=agg,
        )
        x = torch.randn(4, 20, 13)
        return model(x)

    def test_soft_forest_and_linear_heads(self) -> None:
        for head in ("soft_forest", "linear"):
            logits, extras = self._forward(head, "attention")
            self.assertEqual(tuple(logits.shape), (4,))
            self.assertEqual(extras["classification_head"], head)
            if head == "soft_forest":
                self.assertGreater(len(extras["routing"]), 0)
            else:
                self.assertEqual(extras["routing"], [])
            assert_model_outputs(logits, extras, batch_size=4, seq_len=20)

    def test_attention_and_last_aggregation(self) -> None:
        logits_a, extras_a = self._forward("soft_forest", "attention")
        logits_l, extras_l = self._forward("soft_forest", "last")
        self.assertEqual(extras_a["temporal_aggregation"], "attention")
        self.assertEqual(extras_l["temporal_aggregation"], "last")
        # Last aggregation uses a one-hot on the final timestep.
        self.assertTrue(torch.allclose(extras_l["attention_weights"][:, -1], torch.ones(4)))
        self.assertTrue(torch.allclose(extras_l["attention_weights"][:, :-1], torch.zeros(4, 19)))
        assert_model_outputs(logits_a, extras_a, batch_size=4, seq_len=20)
        assert_model_outputs(logits_l, extras_l, batch_size=4, seq_len=20)

    def test_gradients_for_ablations(self) -> None:
        for head, agg in (("soft_forest", "attention"), ("linear", "last"), ("linear", "attention")):
            model = SequenceEnsembleModel(
                input_dim=13,
                hidden_size=16,
                dropout=0.0,
                attention_dim=8,
                n_trees=2,
                tree_depth=2,
                classification_head=head,
                temporal_aggregation=agg,
            )
            x = torch.randn(4, 20, 13)
            y = torch.tensor([0.0, 1.0, 0.0, 1.0])
            model.zero_grad(set_to_none=True)
            logits, _ = model(x)
            nn.BCEWithLogitsLoss()(logits, y).backward()
            msgs = assert_component_gradients(model)
            self.assertGreaterEqual(len(msgs), 2)


class TestPosWeightMultiplier(unittest.TestCase):
    def test_effective_pos_weight(self) -> None:
        base = 136.2972972972973
        for mult in (0.25, 0.5, 1.0):
            effective = base * mult
            pw = torch.tensor([effective], dtype=torch.float32)
            criterion = nn.BCEWithLogitsLoss(pos_weight=pw)
            logits = torch.tensor([0.1, -0.2], dtype=torch.float32)
            y = torch.tensor([1.0, 0.0], dtype=torch.float32)
            loss = criterion(logits, y)
            self.assertTrue(torch.isfinite(loss))
            self.assertAlmostEqual(float(pw.item()), base * mult, places=5)


class TestEncoderCheckpointLoading(unittest.TestCase):
    def test_compatible_encoder_load(self) -> None:
        # Mimic standalone Bi-LSTM checkpoint keys.
        src_lstm = nn.LSTM(13, 16, batch_first=True, bidirectional=True)
        fc = nn.Linear(32, 1)
        src_sd = {f"lstm.{k}": v for k, v in src_lstm.state_dict().items()}
        src_sd["fc.weight"] = fc.weight.detach().clone()
        src_sd["fc.bias"] = fc.bias.detach().clone()

        model = SequenceEnsembleModel(
            input_dim=13,
            hidden_size=16,
            dropout=0.0,
            attention_dim=8,
            n_trees=2,
            tree_depth=2,
            classification_head="soft_forest",
            temporal_aggregation="attention",
        )
        before = {k: v.detach().clone() for k, v in model.lstm.state_dict().items()}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bilstm_ckpt.pt"
            torch.save({"model_state_dict": src_sd, "epoch": 1}, path)
            report = load_encoder_checkpoint(model, path)

        self.assertGreater(report["n_loaded"], 0)
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["skipped_standalone_head"], ["fc.weight", "fc.bias"])
        self.assertFalse(report["encoder_frozen"])
        after = model.lstm.state_dict()
        for k in before:
            self.assertTrue(torch.equal(after[k], src_sd[f"lstm.{k}"]))
        # Encoder remains trainable.
        for p in model.lstm.parameters():
            self.assertTrue(p.requires_grad)

    def test_shape_mismatch_reported(self) -> None:
        model = SequenceEnsembleModel(hidden_size=16, n_trees=1, tree_depth=2, dropout=0.0)
        bad = {"lstm.weight_ih_l0": torch.zeros(1, 1), "fc.weight": torch.zeros(1, 1)}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.pt"
            torch.save({"model_state_dict": bad}, path)
            report = load_encoder_checkpoint(model, path)
        self.assertEqual(report["n_loaded"], 0)
        self.assertTrue(any("shape" in s for s in report["incompatible"]))


class TestDiagnostics(unittest.TestCase):
    def test_finite_diagnostic_outputs(self) -> None:
        model = SequenceEnsembleModel(
            input_dim=13,
            hidden_size=16,
            dropout=0.0,
            attention_dim=8,
            n_trees=2,
            tree_depth=2,
            classification_head="soft_forest",
            temporal_aggregation="attention",
        )
        x = torch.randn(6, 20, 13)
        y = torch.tensor([0.0, 1.0, 0.0, 1.0, 0.0, 0.0])
        logits, extras = model(x)
        diag = compute_validation_diagnostics(
            model, logits, extras, y, grad_norms={"grad_norm_bilstm": 0.5}
        )
        self.assertIn("attention_mean_entropy", diag)
        self.assertIn("attention_mean_max_weight", diag)
        self.assertIn("attention_pos00_mean", diag)
        self.assertIn("mean_routing_entropy", diag)
        self.assertIn("n_unused_leaves_total", diag)
        self.assertIn("logit_mean", diag)
        self.assertIn("mean_prob_positive", diag)
        self.assertIn("mean_prob_negative", diag)
        for k, v in diag.items():
            if isinstance(v, float):
                self.assertTrue(v == v or v != v)  # allow NaN
                if v == v:
                    self.assertTrue(abs(v) < float("inf"), msg=k)

    def test_linear_last_diagnostics(self) -> None:
        model = SequenceEnsembleModel(
            classification_head="linear",
            temporal_aggregation="last",
            hidden_size=16,
            attention_dim=8,
            dropout=0.0,
        )
        x = torch.randn(4, 20, 13)
        y = torch.tensor([1.0, 0.0, 1.0, 0.0])
        logits, extras = model(x)
        diag = compute_validation_diagnostics(model, logits, extras, y)
        self.assertTrue(abs(diag["attention_mean_max_weight"] - 1.0) < 1e-5)
        self.assertTrue(diag["mean_routing_entropy"] != diag["mean_routing_entropy"])  # NaN


class TestSequenceEnsembleModel(unittest.TestCase):
    def setUp(self) -> None:
        self.model = SequenceEnsembleModel(
            input_dim=13,
            hidden_size=16,
            dropout=0.0,
            attention_dim=8,
            n_trees=2,
            tree_depth=2,
        )

    def test_forward_shapes_and_validity(self) -> None:
        x = torch.randn(4, 20, 13)
        logits, extras = self.model(x)
        msgs = assert_model_outputs(logits, extras, batch_size=4, seq_len=20)
        self.assertTrue(any("attention" in m for m in msgs))

    def test_end_to_end_gradients(self) -> None:
        x = torch.randn(4, 20, 13)
        y = torch.tensor([0.0, 1.0, 0.0, 1.0])
        self.model.zero_grad(set_to_none=True)
        logits, _ = self.model(x)
        nn.BCEWithLogitsLoss()(logits, y).backward()
        msgs = assert_component_gradients(self.model)
        self.assertEqual(len(msgs), 3)

    def test_parameter_count_components(self) -> None:
        counts = self.model.component_parameter_counts()
        self.assertEqual(
            counts["total"],
            counts["bilstm_encoder"] + counts["attention"] + counts["soft_forest"],
        )


if __name__ == "__main__":
    unittest.main()
