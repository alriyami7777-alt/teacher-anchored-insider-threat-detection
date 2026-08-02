"""Forward-pass evaluation helpers (no training)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score
from sklearn.metrics import confusion_matrix

from objective2_teacher_anchored_odst.models import build_model, load_checkpoint_into, student_forward_with_routing
from prototype_v3_node.train import metrics_at_threshold

from .safety import assert_path_allowed_for_read, refuse_test_loader


def sha256_file(path: Path) -> str:
    assert_path_allowed_for_read(path, context="hash")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def state_dict_sha256(state: dict[str, torch.Tensor]) -> str:
    h = hashlib.sha256()
    for k in sorted(state.keys()):
        h.update(k.encode())
        h.update(state[k].detach().cpu().numpy().tobytes())
    return h.hexdigest()


def load_npz(path: Path) -> dict[str, Any]:
    refuse_test_loader(path.name)
    assert_path_allowed_for_read(path, context="npz")
    data = np.load(path, allow_pickle=True)
    X = np.asarray(data["X"], dtype=np.float32)
    y = np.asarray(data["y"], dtype=np.int64).reshape(-1)
    meta = {
        "sequence_id": np.asarray(data["sequence_id"]) if "sequence_id" in data.files else None,
        "user": np.asarray(data["user"]) if "user" in data.files else None,
        "start_date": np.asarray(data["start_date"]) if "start_date" in data.files else None,
        "end_date": np.asarray(data["end_date"]) if "end_date" in data.files else None,
        "keys": list(data.files),
    }
    return {"X": X, "y": y, **meta}


def load_student(ckpt: Path, device: torch.device) -> tuple[torch.nn.Module, dict[str, Any], str]:
    assert_path_allowed_for_read(ckpt, context="checkpoint")
    model = build_model()
    info = load_checkpoint_into(model, ckpt)
    model.eval()
    for p in model.parameters():
        p.requires_grad = False
    model.to(device)
    sha = sha256_file(ckpt)
    return model, info, sha


@torch.inference_mode()
def predict_probs(
    model: torch.nn.Module,
    X: np.ndarray,
    device: torch.device,
    batch_size: int = 1024,
) -> np.ndarray:
    """Forward-only probabilities. No optimiser, no backward."""
    model.eval()
    probs = []
    n = X.shape[0]
    for i in range(0, n, batch_size):
        xb = torch.from_numpy(X[i : i + batch_size]).to(device)
        out = student_forward_with_routing(model, xb)
        logit = out["logit"]
        if logit.requires_grad:
            raise RuntimeError("Logits unexpectedly require grad")
        probs.append(torch.sigmoid(logit).detach().cpu().numpy())
    return np.concatenate(probs, axis=0).astype(np.float64)


def score_condition(
    y: np.ndarray,
    probs: np.ndarray,
    threshold: float,
    clean_probs: np.ndarray,
    clean_pred: np.ndarray,
) -> dict[str, Any]:
    met = metrics_at_threshold(y, probs, threshold)
    pred = (probs >= threshold).astype(int)
    y_i = y.astype(int)
    mal = y_i == 1
    nor = y_i == 0
    return {
        **met,
        "prediction_agreement_with_clean": float((pred == clean_pred).mean()),
        "mean_abs_score_change": float(np.abs(probs - clean_probs).mean()),
        "malicious_mean_score_change": float((probs[mal] - clean_probs[mal]).mean()) if mal.any() else float("nan"),
        "normal_mean_score_change": float((probs[nor] - clean_probs[nor]).mean()) if nor.any() else float("nan"),
        "n_malicious_detected": int(((pred == 1) & mal).sum()),
        "n_malicious": int(mal.sum()),
        "malicious_detection_rate": float(((pred == 1) & mal).sum() / max(int(mal.sum()), 1)),
        "probs": probs,
        "pred": pred,
    }


def assert_no_training_hooks(model: torch.nn.Module) -> None:
    if any(p.requires_grad for p in model.parameters()):
        raise RuntimeError("Model parameters require_grad=True; training hooks forbidden")
    # Ensure we never attach an optimiser in this study (caller must not create one).
