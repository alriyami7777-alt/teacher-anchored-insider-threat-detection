#!/usr/bin/env python3
"""Unit and smoke checks for standalone Bi-LSTM baseline runner."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_bilstm_baseline import (  # noqa: E402
    BiLSTMClassifier,
    build_checkpoint,
    choose_threshold_f1,
    default_output_dir,
    metrics_at_threshold,
    set_seed,
)


class TestBiLSTMArchitecture(unittest.TestCase):
    def test_architecture_locked(self) -> None:
        model = BiLSTMClassifier(input_dim=13, hidden_size=64, dropout=0.2)
        self.assertEqual(model.lstm.num_layers, 1)
        self.assertTrue(model.lstm.bidirectional)
        self.assertEqual(model.lstm.hidden_size, 64)
        self.assertIsInstance(model.fc, nn.Linear)
        self.assertEqual(model.fc.in_features, 128)
        self.assertEqual(model.fc.out_features, 1)

    def test_forward_shape(self) -> None:
        model = BiLSTMClassifier(input_dim=13, hidden_size=64, dropout=0.0)
        model.eval()
        x = torch.randn(4, 20, 13)
        logits = model(x)
        self.assertEqual(tuple(logits.shape), (4,))
        self.assertTrue(torch.isfinite(logits).all())


class TestBiLSTMHelpers(unittest.TestCase):
    def test_metrics_and_threshold_finite(self) -> None:
        y = np.array([0, 0, 1, 1, 0, 1])
        p = np.array([0.1, 0.2, 0.8, 0.7, 0.3, 0.9])
        thr, f1 = choose_threshold_f1(y, p)
        m = metrics_at_threshold(y, p, thr)
        self.assertTrue(np.isfinite(m["pr_auc"]))
        self.assertTrue(np.isfinite(m["f1"]))
        self.assertGreaterEqual(m["tp"], 0)
        self.assertGreaterEqual(f1, 0.0)

    def test_checkpoint_contains_metadata(self) -> None:
        model = BiLSTMClassifier(input_dim=13, hidden_size=16, dropout=0.0)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        config = {"seed": 42, "patience": 4}
        ckpt = build_checkpoint(model, optimizer, 1, 1, 0.5, 3, config, [])
        self.assertIn("model_state_dict", ckpt)
        self.assertIn("optimizer_state_dict", ckpt)
        self.assertEqual(ckpt["architecture"], "BiLSTMClassifier")
        self.assertEqual(ckpt["seed"], 42)

    def test_default_output_dir_per_seed(self) -> None:
        root = Path("/repo")
        self.assertEqual(
            default_output_dir(root, 52),
            Path("/repo/outputs/objective2/bilstm_seed52"),
        )

    def test_set_seed_deterministic_mode(self) -> None:
        set_seed(42)
        self.assertTrue(torch.backends.cudnn.deterministic)
        self.assertFalse(torch.backends.cudnn.benchmark)


class TestBiLSTMResume(unittest.TestCase):
    def test_checkpoint_roundtrip(self) -> None:
        model = BiLSTMClassifier(input_dim=13, hidden_size=16, dropout=0.0)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        config = {"seed": 42, "patience": 4}
        ckpt = build_checkpoint(model, optimizer, 2, 1, 0.75, 2, config, [{"epoch": 1}])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "last.pt"
            torch.save(ckpt, path)
            loaded = torch.load(path, map_location="cpu", weights_only=False)
        model2 = BiLSTMClassifier(input_dim=13, hidden_size=16, dropout=0.0)
        model2.load_state_dict(loaded["model_state_dict"])
        x = torch.randn(2, 20, 13)
        with torch.no_grad():
            self.assertTrue(torch.allclose(model(x), model2(x), atol=1e-6))


if __name__ == "__main__":
    unittest.main()
