#!/usr/bin/env python3
"""Smoke and numerical checks for fragmented hybrid baseline."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from models.sequence_ensemble import SequenceEnsembleModel  # noqa: E402
from run_fragmented_hybrid_baseline import (  # noqa: E402
    choose_threshold_f1,
    extract_representations,
    load_pretrained_encoder,
    metrics_at_threshold,
    select_rf_on_validation,
    select_xgb_on_validation,
)


class TestFragmentedHybridHelpers(unittest.TestCase):
    def test_metrics_and_threshold_finite(self) -> None:
        y = np.array([0, 0, 1, 1, 0, 1])
        p = np.array([0.1, 0.2, 0.8, 0.7, 0.3, 0.9])
        thr, f1 = choose_threshold_f1(y, p)
        m = metrics_at_threshold(y, p, thr)
        self.assertTrue(np.isfinite(m["pr_auc"]))
        self.assertTrue(np.isfinite(m["f1"]))
        self.assertGreaterEqual(m["tp"], 0)

    def test_representation_extraction_shape(self) -> None:
        model = SequenceEnsembleModel(
            input_dim=13,
            hidden_size=16,
            dropout=0.0,
            attention_dim=8,
            classification_head="linear",
            temporal_aggregation="attention",
        )
        model.eval()
        for p in model.lstm.parameters():
            p.requires_grad = False
        for p in model.attention.parameters():
            p.requires_grad = False
        x = torch.randn(8, 20, 13)
        y = torch.zeros(8)
        loader = DataLoader(TensorDataset(x, y), batch_size=4)
        z, y_out = extract_representations(model, loader, torch.device("cpu"))
        self.assertEqual(z.shape, (8, 32))
        self.assertTrue(np.isfinite(z).all())
        self.assertEqual(len(y_out), 8)

    def test_encoder_checkpoint_load_and_freeze(self) -> None:
        model = SequenceEnsembleModel(
            input_dim=13,
            hidden_size=16,
            dropout=0.0,
            attention_dim=8,
            classification_head="linear",
            temporal_aggregation="attention",
        )
        payload = {
            "model_state_dict": model.state_dict(),
            "best_epoch": 1,
            "best_val_pr_auc": 0.5,
            "config": {"hidden_size": 16, "dropout": 0.0, "attention_dim": 8},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "best.pt"
            torch.save(payload, path)
            loaded, report = load_pretrained_encoder(path, torch.device("cpu"))
        self.assertTrue(report["encoder_frozen"])
        self.assertEqual(report["representation_dim"], 32)
        for p in loaded.lstm.parameters():
            self.assertFalse(p.requires_grad)
        for p in loaded.attention.parameters():
            self.assertFalse(p.requires_grad)

    def test_tree_selection_smoke(self) -> None:
        rng = np.random.default_rng(0)
        x_train = rng.normal(size=(120, 16)).astype(np.float32)
        y_train = (rng.random(120) > 0.9).astype(np.int8)
        x_val = rng.normal(size=(40, 16)).astype(np.float32)
        y_val = (rng.random(40) > 0.85).astype(np.int8)
        rf, rf_cfg = select_rf_on_validation(x_train, y_train, x_val, y_val, 42, smoke=True)
        xgb, xgb_cfg = select_xgb_on_validation(x_train, y_train, x_val, y_val, 42, smoke=True)
        p_rf = rf.predict_proba(x_val)[:, 1]
        p_xgb = xgb.predict_proba(x_val)[:, 1]
        self.assertTrue(np.isfinite(p_rf).all())
        self.assertTrue(np.isfinite(p_xgb).all())
        self.assertIn("validation_pr_auc", rf_cfg)
        self.assertIn("validation_pr_auc", xgb_cfg)


if __name__ == "__main__":
    unittest.main()
