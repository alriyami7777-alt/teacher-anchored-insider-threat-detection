"""Forward-only model loaders and predictors (no training)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import torch
from xgboost import XGBClassifier

from evaluate_locked_objective2 import load_sequence_ensemble
from objective2_r52_same_information_baselines.models import ShallowMLP
from objective2_teacher_anchored_odst.models import (
    build_model,
    load_checkpoint_into,
    student_forward_with_routing,
)

from .constants import (
    ATTENTION_LINEAR,
    BATCH_SIZE,
    FLAT_MODELS,
    SEEDS,
    SOURCE_AL,
    SOURCE_SAME_INFO,
    SOURCE_TA,
    STATUS_PROVENANCE,
    TEACHER_ANCHORED,
)
from .safety import TemporalBlockedError, assert_path_allowed_for_read, sha256_file
from .transforms import flatten_sequences


@dataclass
class LoadedModel:
    model_id: str
    seed: int
    kind: str  # sequence | flat
    threshold: float
    expected_pr_auc: float | None
    expected_f1: float | None
    path: str
    sha256: str
    predict_seq: Callable[[np.ndarray], np.ndarray] | None
    predict_flat: Callable[[np.ndarray], np.ndarray] | None
    param_hash0: str | None
    device: str
    notes: str = ""


def _state_hash_torch(model: torch.nn.Module) -> str:
    import hashlib

    h = hashlib.sha256()
    for k, v in sorted(model.state_dict().items()):
        h.update(k.encode())
        h.update(v.detach().cpu().numpy().tobytes())
    return h.hexdigest()


@torch.inference_mode()
def _predict_ta(model: torch.nn.Module, X: np.ndarray, device: torch.device) -> np.ndarray:
    model.eval()
    probs = []
    for i in range(0, len(X), BATCH_SIZE):
        xb = torch.from_numpy(X[i : i + BATCH_SIZE]).to(device)
        out = student_forward_with_routing(model, xb)
        logit = out["logit"]
        if logit.requires_grad:
            raise RuntimeError("unexpected grad")
        probs.append(torch.sigmoid(logit).detach().cpu().numpy())
    return np.concatenate(probs).astype(np.float64)


@torch.inference_mode()
def _predict_al(model: torch.nn.Module, X: np.ndarray, device: torch.device) -> np.ndarray:
    model.eval()
    probs = []
    for i in range(0, len(X), BATCH_SIZE):
        xb = torch.from_numpy(X[i : i + BATCH_SIZE]).to(device)
        logits, _extras = model(xb)
        if logits.requires_grad:
            raise RuntimeError("unexpected grad")
        probs.append(torch.sigmoid(logits.reshape(-1)).detach().cpu().numpy())
    return np.concatenate(probs).astype(np.float64)


@torch.inference_mode()
def _predict_mlp(model: torch.nn.Module, scaler, X_flat: np.ndarray, device: torch.device) -> np.ndarray:
    model.eval()
    Xs = scaler.transform(X_flat).astype(np.float32)
    probs = []
    for i in range(0, len(Xs), BATCH_SIZE):
        xb = torch.from_numpy(Xs[i : i + BATCH_SIZE]).to(device)
        logits = model(xb)
        if logits.requires_grad:
            raise RuntimeError("unexpected grad")
        probs.append(torch.sigmoid(logits).detach().cpu().numpy())
    return np.concatenate(probs).astype(np.float64)


def _load_threshold_summary(path: Path) -> tuple[float, float | None, float | None]:
    s = json.loads(path.read_text(encoding="utf-8"))
    if "best_threshold" in s:
        return float(s["best_threshold"]), float(s.get("best_pr_auc")) if s.get("best_pr_auc") is not None else None, float(s.get("best_f1")) if s.get("best_f1") is not None else None
    if "validation_metrics" in s:
        m = s["validation_metrics"]
        return float(m["threshold"]), float(m["pr_auc"]), float(m["f1"])
    if "selected_threshold" in s:
        return float(s["selected_threshold"]), float(s.get("pr_auc")) if s.get("pr_auc") is not None else None, float(s.get("f1")) if s.get("f1") is not None else None
    raise TemporalBlockedError(STATUS_PROVENANCE, f"no threshold in {path}")


def load_all_models(repo_root: Path, device: torch.device) -> list[LoadedModel]:
    loaded: list[LoadedModel] = []

    # Teacher-anchored
    for seed in SEEDS:
        meta = TEACHER_ANCHORED[seed]
        ckpt = repo_root / SOURCE_TA / meta["ckpt_rel"]
        assert_path_allowed_for_read(ckpt, context="ta_ckpt")
        sha = sha256_file(ckpt)
        if sha != meta["expected_sha256"]:
            raise TemporalBlockedError(STATUS_PROVENANCE, f"TA seed{seed} hash mismatch")
        summary_path = repo_root / SOURCE_TA / meta["summary_rel"]
        thr, exp_pr, exp_f1 = _load_threshold_summary(summary_path)
        model = build_model()
        load_checkpoint_into(model, ckpt)
        model.eval()
        for p in model.parameters():
            p.requires_grad = False
        model.to(device)
        h0 = _state_hash_torch(model)

        def make_pred(m=model, d=device):
            return lambda X: _predict_ta(m, X, d)

        loaded.append(
            LoadedModel(
                model_id="teacher_anchored_odst_seq",
                seed=seed,
                kind="sequence",
                threshold=thr,
                expected_pr_auc=exp_pr if exp_pr is not None else meta.get("expected_pr_auc"),
                expected_f1=exp_f1 if exp_f1 is not None else meta.get("expected_f1"),
                path=str(ckpt),
                sha256=sha,
                predict_seq=make_pred(),
                predict_flat=None,
                param_hash0=h0,
                device=str(device),
                notes="teacher_anchored_student_forward_only",
            )
        )

    # Attention-linear
    for seed in SEEDS:
        meta = ATTENTION_LINEAR[seed]
        d = repo_root / SOURCE_AL / meta["dir_rel"]
        ckpt = d / "best.pt"
        assert_path_allowed_for_read(ckpt, context="al_ckpt")
        sha = sha256_file(ckpt)
        if meta.get("expected_sha256") and sha != meta["expected_sha256"]:
            raise TemporalBlockedError(STATUS_PROVENANCE, f"AL seed{seed} hash mismatch")
        thr, exp_pr, exp_f1 = _load_threshold_summary(d / "summary.json")
        payload = torch.load(ckpt, map_location="cpu", weights_only=False)
        cfg = dict(payload.get("config") or {})
        cfg.setdefault("classification_head", "linear")
        cfg.setdefault("temporal_aggregation", "attention")
        cfg.setdefault("n_trees", 5)
        cfg.setdefault("tree_depth", 4)
        model = load_sequence_ensemble(ckpt, cfg, device)
        for p in model.parameters():
            p.requires_grad = False
        h0 = _state_hash_torch(model)

        def make_pred(m=model, d=device):
            return lambda X: _predict_al(m, X, d)

        loaded.append(
            LoadedModel(
                model_id="attention_linear_seq",
                seed=seed,
                kind="sequence",
                threshold=thr,
                expected_pr_auc=exp_pr,
                expected_f1=exp_f1,
                path=str(ckpt),
                sha256=sha,
                predict_seq=make_pred(),
                predict_flat=None,
                param_hash0=h0,
                device=str(device),
                notes="attention_linear_sequence_ensemble_forward_only",
            )
        )

    # Flat models
    hash_csv = repo_root / SOURCE_SAME_INFO / "baseline_model_hashes.csv"
    hash_map: dict[str, str] = {}
    if hash_csv.exists():
        import pandas as pd

        hdf = pd.read_csv(hash_csv)
        hash_map = {str(r["path"]).replace("\\", "/"): str(r["sha256"]) for _, r in hdf.iterrows()}

    for seed in SEEDS:
        # XGB
        rel = f"xgboost_seed{seed}/model.json"
        path = repo_root / SOURCE_SAME_INFO / rel
        assert_path_allowed_for_read(path, context="xgb")
        sha = sha256_file(path)
        if hash_map.get(rel) and hash_map[rel] != sha:
            raise TemporalBlockedError(STATUS_PROVENANCE, f"XGB hash mismatch seed{seed}")
        thr, exp_pr, exp_f1 = _load_threshold_summary(repo_root / SOURCE_SAME_INFO / f"xgboost_seed{seed}/threshold.json")
        clf = XGBClassifier()
        clf.load_model(str(path))
        loaded.append(
            LoadedModel(
                model_id="xgboost_flat260",
                seed=seed,
                kind="flat",
                threshold=thr,
                expected_pr_auc=exp_pr,
                expected_f1=exp_f1,
                path=str(path),
                sha256=sha,
                predict_seq=None,
                predict_flat=lambda Xf, c=clf: c.predict_proba(Xf)[:, 1].astype(np.float64),
                param_hash0=None,
                device="cpu",
                notes="xgboost_flat_unscaled",
            )
        )

        # RF
        rel = f"random_forest_seed{seed}/model.joblib"
        path = repo_root / SOURCE_SAME_INFO / rel
        assert_path_allowed_for_read(path, context="rf")
        sha = sha256_file(path)
        if hash_map.get(rel) and hash_map[rel] != sha:
            raise TemporalBlockedError(STATUS_PROVENANCE, f"RF hash mismatch seed{seed}")
        thr, exp_pr, exp_f1 = _load_threshold_summary(repo_root / SOURCE_SAME_INFO / f"random_forest_seed{seed}/threshold.json")
        rf = joblib.load(path)
        loaded.append(
            LoadedModel(
                model_id="random_forest_flat260",
                seed=seed,
                kind="flat",
                threshold=thr,
                expected_pr_auc=exp_pr,
                expected_f1=exp_f1,
                path=str(path),
                sha256=sha,
                predict_seq=None,
                predict_flat=lambda Xf, c=rf: c.predict_proba(Xf)[:, 1].astype(np.float64),
                param_hash0=None,
                device="cpu",
                notes="random_forest_flat_unscaled",
            )
        )

        # MLP
        rel = f"mlp_seed{seed}/model.pt"
        path = repo_root / SOURCE_SAME_INFO / rel
        scaler_path = repo_root / SOURCE_SAME_INFO / f"mlp_seed{seed}/scaler.joblib"
        assert_path_allowed_for_read(path, context="mlp")
        sha = sha256_file(path)
        if hash_map.get(rel) and hash_map[rel] != sha:
            raise TemporalBlockedError(STATUS_PROVENANCE, f"MLP hash mismatch seed{seed}")
        thr, exp_pr, exp_f1 = _load_threshold_summary(repo_root / SOURCE_SAME_INFO / f"mlp_seed{seed}/threshold.json")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        mlp = ShallowMLP(in_dim=260, hidden=[128, 64], dropout=0.2)
        mlp.load_state_dict(payload["state_dict"])
        mlp.eval()
        for p in mlp.parameters():
            p.requires_grad = False
        mlp.to(device)
        scaler = joblib.load(scaler_path)
        h0 = _state_hash_torch(mlp)

        def make_pred(m=mlp, sc=scaler, d=device):
            return lambda Xf: _predict_mlp(m, sc, Xf, d)

        loaded.append(
            LoadedModel(
                model_id="mlp_flat260",
                seed=seed,
                kind="flat",
                threshold=thr,
                expected_pr_auc=exp_pr,
                expected_f1=exp_f1,
                path=str(path),
                sha256=sha,
                predict_seq=None,
                predict_flat=make_pred(),
                param_hash0=h0,
                device=str(device),
                notes="mlp_flat_train_scaler",
            )
        )

    # Optional logistic for supplementary machine-readable only
    for seed in SEEDS:
        rel = f"logistic_regression_seed{seed}/model.joblib"
        path = repo_root / SOURCE_SAME_INFO / rel
        if not path.exists():
            continue
        sha = sha256_file(path)
        thr, exp_pr, exp_f1 = _load_threshold_summary(repo_root / SOURCE_SAME_INFO / f"logistic_regression_seed{seed}/threshold.json")
        lr = joblib.load(path)
        scaler = joblib.load(repo_root / SOURCE_SAME_INFO / f"logistic_regression_seed{seed}/scaler.joblib")

        def make_pred(c=lr, sc=scaler):
            def _f(Xf: np.ndarray) -> np.ndarray:
                Xs = sc.transform(Xf)
                if hasattr(c, "predict_proba"):
                    return c.predict_proba(Xs)[:, 1].astype(np.float64)
                scores = c.decision_function(Xs).astype(np.float64)
                return 1.0 / (1.0 + np.exp(-scores))

            return _f

        loaded.append(
            LoadedModel(
                model_id="logistic_regression_flat260",
                seed=seed,
                kind="flat",
                threshold=thr,
                expected_pr_auc=exp_pr,
                expected_f1=exp_f1,
                path=str(path),
                sha256=sha,
                predict_seq=None,
                predict_flat=make_pred(),
                param_hash0=None,
                device="cpu",
                notes="supplementary_only",
            )
        )

    return loaded


def predict_for_condition(lm: LoadedModel, X_seq: np.ndarray) -> np.ndarray:
    if lm.kind == "sequence":
        assert lm.predict_seq is not None
        return lm.predict_seq(X_seq)
    assert lm.predict_flat is not None
    return lm.predict_flat(flatten_sequences(X_seq))
