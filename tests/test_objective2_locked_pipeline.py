#!/usr/bin/env python3
"""Unit tests for Objective 2 final locked consolidation / evaluation / reporting."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from objective2_locked_common import (  # noqa: E402
    DISPLAY_NAMES,
    hash_artefact,
    paired_seed_differences,
    sha256_file,
    summarise_numeric,
    verify_artefact_hash,
    write_json,
)
import consolidate_objective2_final as consol  # noqa: E402
import evaluate_locked_objective2 as eval_mod  # noqa: E402
import generate_objective2_report_assets as report_mod  # noqa: E402


def _write_minimal_run_tree(root: Path) -> None:
    """Create a tiny synthetic artefact tree sufficient for consolidation unit tests."""
    seeds = (42, 52, 62)

    # Bi-LSTM
    for seed in seeds:
        d = root / "outputs" / "objective2" / f"bilstm_seed{seed}"
        d.mkdir(parents=True)
        (d / "best.pt").write_bytes(b"bilstm-ckpt-" + str(seed).encode())
        cfg = {
            "architecture": {"type": "BiLSTMClassifier", "input_dim": 13, "hidden_size": 64, "dropout": 0.2},
            "seed": seed,
            "batch_size": 1024,
            "learning_rate": 0.001,
            "max_epochs": 20,
            "patience": 4,
            "pos_weight_train": 100.0,
            "early_stopping_metric": "validation_pr_auc",
            "threshold_selection": "maximum_validation_f1",
        }
        (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        thr = {
            "selected_threshold": 0.8 + seed / 1000.0,
            "best_epoch": 3,
            "validation_metrics": {
                "threshold": 0.8,
                "precision": 0.9,
                "recall": 0.8,
                "f1": 0.85,
                "pr_auc": 0.7 + seed / 1000.0,
                "roc_auc": 0.99,
                "fpr": 0.001,
                "fnr": 0.2,
                "tn": 30000,
                "fp": 10 + seed % 10,
                "fn": 20,
                "tp": 200,
            },
        }
        (d / "threshold.json").write_text(json.dumps(thr), encoding="utf-8")
        pd.DataFrame(
            [
                {
                    "model": "bilstm",
                    "split": "validation",
                    "threshold_rule": "selected_val_f1",
                    "seed": seed,
                    "best_epoch": 3,
                    "training_time_sec": 50.0 + seed,
                    "threshold": thr["selected_threshold"],
                    **thr["validation_metrics"],
                }
            ]
        ).to_csv(d / "validation_metrics.csv", index=False)

    # Attention-linear + joint
    ens = root / "outputs" / "baselines" / "sequence_ensemble"
    pretrain = {
        42: "stage11_A_attn_linear",
        52: "pretrain_attn_linear_seed52",
        62: "pretrain_attn_linear_seed62",
    }
    joint = {
        42: "stage11_D_pretrained_seed42_best",
        52: "stage11_D_pretrained_seed52_best",
        62: "stage11_D_pretrained_seed62_best",
    }
    for seed in seeds:
        for dirname, head, pr in (
            (pretrain[seed], "linear", 0.75 + seed / 10000.0),
            (joint[seed], "soft_forest", 0.80 + seed / 10000.0),
        ):
            d = ens / dirname
            d.mkdir(parents=True)
            (d / "best.pt").write_bytes(b"ens-" + dirname.encode())
            cfg = {
                "classification_head": head,
                "temporal_aggregation": "attention",
                "hidden_size": 64,
                "dropout": 0.2,
                "attention_dim": 64,
                "n_trees": 5,
                "tree_depth": 4,
                "learning_rate": 0.0003 if head == "soft_forest" else 0.001,
                "weight_decay": 0.0,
                "batch_size": 1024,
                "max_epochs": 15,
                "patience": 4,
                "seed": seed,
                "base_pos_weight": 100.0,
                "pos_weight_multiplier": 0.25 if head == "soft_forest" else 1.0,
                "effective_pos_weight": 25.0 if head == "soft_forest" else 100.0,
                "encoder_checkpoint": str((ens / pretrain[seed] / "best.pt").resolve())
                if head == "soft_forest"
                else None,
            }
            (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            thr = {
                "selected_threshold": 0.7,
                "best_epoch": 4,
                "validation_metrics": {
                    "precision": 0.8,
                    "recall": 0.75,
                    "f1": 0.77,
                    "pr_auc": pr,
                    "roc_auc": 0.98,
                    "fpr": 0.001,
                    "fnr": 0.25,
                    "tn": 30000,
                    "fp": 30,
                    "fn": 40,
                    "tp": 180,
                },
            }
            (d / "threshold.json").write_text(json.dumps(thr), encoding="utf-8")
            pd.DataFrame(
                [{"epoch": i, "epoch_time_sec": 10.0, "val_pr_auc": pr} for i in range(1, 5)]
            ).to_csv(d / "training_history.csv", index=False)
            pd.DataFrame(
                [{"epoch": i, "attention_mean_entropy": 1.5} for i in range(1, 5)]
            ).to_csv(d / "validation_diagnostics.csv", index=False)

    # Fragmented hybrids
    for seed in seeds:
        parent = root / "outputs" / "objective2" / f"fragmented_hybrid_seed{seed}"
        parent.mkdir(parents=True)
        enc = ens / pretrain[seed] / "best.pt"
        (parent / "config.json").write_text(
            json.dumps(
                {
                    "seed": seed,
                    "encoder_checkpoint": str(enc.resolve()),
                    "encoder_frozen": True,
                    "representation_dim": 128,
                }
            ),
            encoding="utf-8",
        )
        (parent / "validation_summary.json").write_text(
            json.dumps(
                {
                    "seed": seed,
                    "elapsed_sec": 100.0,
                    "random_forest": {},
                    "xgboost": {},
                }
            ),
            encoding="utf-8",
        )
        repr_dir = parent / "representations"
        repr_dir.mkdir()
        np.save(repr_dir / "test_repr.npy", np.zeros((20, 8), dtype=np.float32))
        np.save(repr_dir / "validation_repr.npy", np.zeros((10, 8), dtype=np.float32))
        np.save(repr_dir / "test_y.npy", np.zeros(20, dtype=np.int8))
        for name, fname in (("random_forest", "model.joblib"), ("xgboost", "model.json")):
            d = parent / name
            d.mkdir()
            (d / fname).write_bytes(b"clf-" + name.encode() + str(seed).encode())
            cfg = {
                "classifier": name,
                "model_hyperparameters": {"n_estimators": 10},
                "selected_threshold": 0.5,
                "threshold_selection": "maximum_validation_f1",
            }
            (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            thr = {
                "selected_threshold": 0.5,
                "validation_metrics": {
                    "precision": 0.7,
                    "recall": 0.7,
                    "f1": 0.7,
                    "pr_auc": 0.72 + (0.01 if name == "random_forest" else 0.0),
                    "roc_auc": 0.97,
                    "fpr": 0.002,
                    "fnr": 0.3,
                    "tn": 30000,
                    "fp": 40,
                    "fn": 50,
                    "tp": 170,
                },
            }
            (d / "threshold.json").write_text(json.dumps(thr), encoding="utf-8")

    # Soft forest reference
    for seed in seeds:
        d = root / "outputs" / "baselines" / "soft_decision_forest" / f"seed_{seed}"
        d.mkdir(parents=True)
        (d / "sdf_T20_s1_checkpoint.pt").write_bytes(b"sdf-" + str(seed).encode())
        cfg = {
            "architecture": {"n_trees": 5, "tree_depth": 4},
            "seed": seed,
            "batch_size": 4096,
            "learning_rate": 0.001,
            "max_epochs": 40,
            "early_stopping_patience": 10,
            "n_features": 40,
            "pos_weight_train": 100.0,
            "training_time_sec": 200.0,
            "best_epoch": 5,
        }
        (d / "sdf_T20_s1_config.json").write_text(json.dumps(cfg), encoding="utf-8")
        thr = {
            "selected_threshold": 0.6,
            "validation_metrics_selected": {
                "precision": 0.5,
                "recall": 0.5,
                "f1": 0.5,
                "pr_auc": 0.4,
                "fp": 60,
                "fn": 60,
                "tp": 100,
                "tn": 30000,
            },
        }
        # Use selected_threshold key expected by collector; metrics from CSV.
        (d / "sdf_T20_s1_threshold.json").write_text(
            json.dumps({"selected_threshold": 0.6}), encoding="utf-8"
        )
        pd.DataFrame(
            [
                {
                    "model": "soft_decision_forest",
                    "split": "validation",
                    "threshold_rule": "selected_val_f1",
                    "threshold": 0.6,
                    "precision": 0.5,
                    "recall": 0.5,
                    "f1": 0.5,
                    "pr_auc": 0.4,
                    "roc_auc": 0.9,
                    "fpr": 0.01,
                    "fnr": 0.5,
                    "tn": 30000,
                    "fp": 60,
                    "fn": 60,
                    "tp": 100,
                    "training_time_sec": np.nan,
                    "test_inference_time_sec": np.nan,
                    "best_epoch": np.nan,
                    "seed": np.nan,
                },
                {
                    "model": "soft_decision_forest",
                    "split": "test",
                    "threshold_rule": "selected_val_f1",
                    "threshold": 0.6,
                    "precision": 0.2,
                    "recall": 0.5,
                    "f1": 0.3,
                    "pr_auc": 0.3,
                    "roc_auc": 0.9,
                    "fpr": 0.01,
                    "fnr": 0.5,
                    "tn": 30000,
                    "fp": 70,
                    "fn": 40,
                    "tp": 40,
                    "training_time_sec": 200.0,
                    "test_inference_time_sec": 1.0,
                    "best_epoch": 5,
                    "seed": seed,
                },
            ]
        ).to_csv(d / "sdf_T20_s1_metrics.csv", index=False)

    # Classical baselines
    base = root / "outputs" / "baselines"
    base.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "model": "random_forest",
                "split": "validation",
                "threshold": 0.26,
                "accuracy": 0.99,
                "precision": 0.9,
                "recall": 0.9,
                "f1": 0.9,
                "pr_auc": 0.95,
                "roc_auc": 0.99,
                "false_positive_rate": 0.001,
                "false_negative_rate": 0.1,
                "training_time_sec": 40.0,
                "inference_time_sec": 0.4,
            },
            {
                "model": "xgboost",
                "split": "validation",
                "threshold": 0.74,
                "accuracy": 0.99,
                "precision": 1.0,
                "recall": 0.88,
                "f1": 0.93,
                "pr_auc": 0.97,
                "roc_auc": 0.99,
                "false_positive_rate": 0.0,
                "false_negative_rate": 0.12,
                "training_time_sec": 12.0,
                "inference_time_sec": 0.1,
            },
        ]
    ).to_csv(base / "r42_T20_s1_baseline_metrics.csv", index=False)
    pd.DataFrame(
        [
            {
                "model": "random_forest",
                "selected_threshold": 0.26,
                "selection_criterion": "max_validation_f1",
                "validation_f1_at_selected_threshold": 0.9,
                "training_time_sec": 40.0,
                "inference_time_sec_val_plus_test": 0.4,
            },
            {
                "model": "xgboost",
                "selected_threshold": 0.74,
                "selection_criterion": "max_validation_f1",
                "validation_f1_at_selected_threshold": 0.93,
                "training_time_sec": 12.0,
                "inference_time_sec_val_plus_test": 0.1,
            },
        ]
    ).to_csv(base / "r42_T20_s1_selected_thresholds.csv", index=False)
    pd.DataFrame(
        [
            {"model": "random_forest", "split": "validation", "threshold": 0.26, "tn": 30732, "fp": 16, "fn": 14, "tp": 238},
            {"model": "xgboost", "split": "validation", "threshold": 0.74, "tn": 30748, "fp": 0, "fn": 31, "tp": 221},
        ]
    ).to_csv(base / "r42_T20_s1_confusion_matrices.csv", index=False)

    # Scratch ablation history for report figure (optional).
    scratch = ens / "stage11_C_attn_sf_pw025_lr3e4"
    scratch.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"epoch": 1, "val_pr_auc": 0.2}, {"epoch": 2, "val_pr_auc": 0.19}]).to_csv(
        scratch / "training_history.csv", index=False
    )
    (scratch / "threshold.json").write_text(
        json.dumps(
            {
                "selected_threshold": 0.79,
                "validation_metrics": {
                    "pr_auc": 0.19,
                    "f1": 0.44,
                    "precision": 0.3,
                    "recall": 0.8,
                    "fp": 400,
                    "fn": 40,
                },
            }
        ),
        encoding="utf-8",
    )


class TestHashHelpers(unittest.TestCase):
    def test_sha256_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "a.bin"
            p.write_bytes(b"abc")
            entry = hash_artefact(root, p, "checkpoint")
            self.assertEqual(entry["sha256"], sha256_file(p))
            verify_artefact_hash(root, entry)
            p.write_bytes(b"abcd")
            with self.assertRaises(ValueError):
                verify_artefact_hash(root, entry)


class TestManifestCreation(unittest.TestCase):
    def test_consolidation_writes_manifest_and_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_run_tree(root)
            out = root / "outputs" / "objective2"
            with mock.patch.object(consol, "repo_root", return_value=root):
                with mock.patch("sys.argv", ["consolidate_objective2_final.py", "--output-dir", str(out)]):
                    consol.main()
            self.assertTrue((out / "objective2_validation_model_comparison.csv").exists())
            self.assertTrue((out / "objective2_validation_model_summary.csv").exists())
            self.assertTrue((out / "objective2_paired_seed_differences.csv").exists())
            man_path = out / "objective2_final_locked_manifest.json"
            self.assertTrue(man_path.exists())
            man = json.loads(man_path.read_text(encoding="utf-8"))
            self.assertIs(man["test_evaluated"], False)
            self.assertGreaterEqual(len(man["artefacts"]), 10)
            self.assertTrue(any(a["role"] == "checkpoint" for a in man["artefacts"]))
            comp = pd.read_csv(out / "objective2_validation_model_comparison.csv")
            self.assertIn("Standalone Bi-LSTM", set(comp["model_name"]))
            self.assertIn("Classical RF", set(comp["model_name"]))
            self.assertTrue(comp.loc[comp["model_id"] == "classical_rf", "is_reference_baseline"].all())


class TestMissingFileRefusal(unittest.TestCase):
    def test_audit_refuses_missing_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_run_tree(root)
            out = root / "outputs" / "objective2"
            with mock.patch.object(consol, "repo_root", return_value=root):
                with mock.patch("sys.argv", ["consolidate_objective2_final.py", "--output-dir", str(out)]):
                    consol.main()
            man = json.loads((out / "objective2_final_locked_manifest.json").read_text(encoding="utf-8"))
            entry = next(
                e
                for e in man["models"]
                if e["model_id"] == "standalone_bilstm" and e["seed"] == 42
            )
            ckpt = root / entry["paths"]["checkpoint"]
            ckpt.unlink()
            with self.assertRaises(eval_mod.LockedEvaluationError):
                eval_mod.audit_model_entry(root, entry, {a["path"]: a for a in man["artefacts"]})


class TestChangedThresholdRefusal(unittest.TestCase):
    def test_threshold_file_mismatch_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_run_tree(root)
            out = root / "outputs" / "objective2"
            with mock.patch.object(consol, "repo_root", return_value=root):
                with mock.patch("sys.argv", ["consolidate_objective2_final.py", "--output-dir", str(out)]):
                    consol.main()
            man = json.loads((out / "objective2_final_locked_manifest.json").read_text(encoding="utf-8"))
            entry = next(
                e
                for e in man["models"]
                if e["model_id"] == "standalone_bilstm" and e["seed"] == 42
            )
            thr_path = root / entry["paths"]["threshold"]
            thr = json.loads(thr_path.read_text(encoding="utf-8"))
            thr["selected_threshold"] = float(thr["selected_threshold"]) + 0.11
            thr_path.write_text(json.dumps(thr), encoding="utf-8")
            # Keep hashes current so the explicit threshold-value guard is exercised.
            new_digest = sha256_file(thr_path)
            entry["hashes"]["threshold"] = new_digest
            artefacts = {a["path"]: a for a in man["artefacts"]}
            artefacts[entry["paths"]["threshold"]]["sha256"] = new_digest
            with self.assertRaises(eval_mod.LockedEvaluationError) as ctx:
                eval_mod.audit_model_entry(root, entry, artefacts)
            self.assertIn("Threshold mismatch", str(ctx.exception))


class TestDryRunDoesNotReadTestLabels(unittest.TestCase):
    def test_dry_run_never_opens_test_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_run_tree(root)
            out = root / "outputs" / "objective2"
            with mock.patch.object(consol, "repo_root", return_value=root):
                with mock.patch("sys.argv", ["consolidate_objective2_final.py", "--output-dir", str(out)]):
                    consol.main()

            # Provide dummy test tensor path referenced by manifest.
            tensor = root / "data" / "processed" / "tensors" / "r42_T20_s1_test.npz"
            tensor.parent.mkdir(parents=True, exist_ok=True)
            np.savez(tensor, X=np.zeros((4, 20, 13), np.float32), y=np.array([0, 1, 0, 1]))

            opened: list[str] = []
            real_load = np.load

            def tracking_load(path, *args, **kwargs):
                opened.append(str(path))
                return real_load(path, *args, **kwargs)

            with mock.patch.object(eval_mod, "repo_root", return_value=root):
                with mock.patch("numpy.load", side_effect=tracking_load):
                    rc = eval_mod.main(
                        [
                            "--manifest",
                            str(out / "objective2_final_locked_manifest.json"),
                            "--output-dir",
                            str(out),
                            "--dry-run",
                        ]
                    )
            self.assertEqual(rc, 0)
            # Dry-run must not load test npz / test_y.npy contents.
            self.assertFalse(any("r42_T20_s1_test.npz" in p for p in opened))
            self.assertFalse(any("test_y.npy" in p for p in opened))
            self.assertFalse((out / "objective2_test_seed_results.csv").exists())


class TestPreventRepeatedTestEvaluation(unittest.TestCase):
    def test_second_evaluation_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "outputs" / "objective2"
            out.mkdir(parents=True)
            man = {
                "test_evaluated": False,
                "models": [],
                "artefacts": [],
                "tensor_files": {"test": "data/processed/tensors/r42_T20_s1_test.npz"},
            }
            write_json(out / "objective2_final_locked_manifest.json", man)
            write_json(out / "objective2_test_evaluation_manifest.json", {"status": "done"})
            with mock.patch.object(eval_mod, "repo_root", return_value=root):
                with self.assertRaises(SystemExit) as ctx:
                    eval_mod.main(
                        [
                            "--manifest",
                            str(out / "objective2_final_locked_manifest.json"),
                            "--output-dir",
                            str(out),
                            "--confirm-test-evaluation",
                        ]
                    )
            self.assertIn("already exists", str(ctx.exception))


class TestReportGenerationSynthetic(unittest.TestCase):
    def test_report_from_synthetic_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_run_tree(root)
            obj = root / "outputs" / "objective2"
            with mock.patch.object(consol, "repo_root", return_value=root):
                with mock.patch("sys.argv", ["consolidate_objective2_final.py", "--output-dir", str(obj)]):
                    consol.main()
            out = obj / "report_assets"
            with mock.patch.object(report_mod, "repo_root", return_value=root):
                with mock.patch(
                    "sys.argv",
                    [
                        "generate_objective2_report_assets.py",
                        "--objective2-dir",
                        str(obj),
                        "--output-dir",
                        str(out),
                    ],
                ):
                    report_mod.main()
            self.assertTrue((out / "table_validation_model_comparison.csv").exists())
            self.assertTrue((out / "table_ablation.csv").exists())
            self.assertTrue((out / "table_repeated_seed_stability.csv").exists())
            self.assertTrue((out / "table_training_inference_time.csv").exists())
            self.assertTrue((out / "fig_validation_pr_auc_mean_error.png").exists())
            self.assertTrue((out / "fig_validation_f1_mean_error.png").exists())
            self.assertTrue((out / "fig_precision_recall_tradeoff.png").exists())
            self.assertTrue((out / "fig_fp_fn_comparison.png").exists())
            self.assertTrue((out / "fig_validation_training_curves.png").exists())
            self.assertTrue((out / "fig_from_scratch_vs_pretrained.png").exists())


class TestPairedDifferences(unittest.TestCase):
    def test_paired_seed_diff_sign(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "model_id": "standalone_bilstm",
                    "model_name": DISPLAY_NAMES["standalone_bilstm"],
                    "seed": 42,
                    "validation_pr_auc": 0.8,
                    "validation_precision": 0.9,
                    "validation_recall": 0.7,
                    "validation_f1": 0.8,
                    "validation_fp": 10,
                    "validation_fn": 20,
                },
                {
                    "model_id": "attention_linear",
                    "model_name": DISPLAY_NAMES["attention_linear"],
                    "seed": 42,
                    "validation_pr_auc": 0.7,
                    "validation_precision": 0.8,
                    "validation_recall": 0.6,
                    "validation_f1": 0.7,
                    "validation_fp": 20,
                    "validation_fn": 30,
                },
            ]
        )
        paired = paired_seed_differences(
            df,
            metric_cols=["validation_pr_auc"],
            model_ids=("standalone_bilstm", "attention_linear"),
        )
        row = paired.iloc[0]
        self.assertAlmostEqual(row["difference_a_minus_b"], 0.1)


if __name__ == "__main__":
    unittest.main()
