"""Inference helpers for the armed one-pass r5.2 test evaluator.

Imported only after preflight succeeds. Does not select thresholds or calibrate.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from xgboost import XGBClassifier

from .data import aggregate_common13_windows
from .safety import ProtocolAccessError, path_looks_like_r42_test, path_looks_like_r62, sha256_file

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


class _SeqDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray) -> None:
        self.X = np.asarray(X, dtype=np.float32)
        self.y = np.asarray(y, dtype=np.float32)

    def __len__(self) -> int:
        return int(self.X.shape[0])

    def __getitem__(self, idx: int):
        return torch.from_numpy(self.X[idx]), torch.tensor(self.y[idx], dtype=torch.float32)


def load_r52_test_once(
    tensor_dir: Path,
    *,
    armed: bool,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Load the r5.2 test tensor exactly once after guards have armed the evaluator."""
    if not armed:
        raise ProtocolAccessError("REFUSED: test loader called while evaluator is not armed")
    path = Path(tensor_dir) / "r52_T20_s1_test.npz"
    if path_looks_like_r62(path) or path_looks_like_r42_test(path):
        raise ProtocolAccessError(f"REFUSED: prohibited corpus path for test loader: {path}")
    if path.name.lower() != "r52_t20_s1_test.npz":
        raise ProtocolAccessError(f"REFUSED: unexpected test tensor name: {path.name}")
    if not path.exists():
        raise ProtocolAccessError(f"REFUSED: missing r5.2 test tensor: {path}")
    # Open only the explicit r5.2 test file after arming.
    z = np.load(path, allow_pickle=True, mmap_mode="r")
    X = np.asarray(z["X"], dtype=np.float32)
    y = np.asarray(z["y"])
    meta = {
        "path": str(path),
        "sha256": sha256_file(path),
        "shape": list(X.shape),
        "n": int(X.shape[0]),
        "files": list(z.files),
        # Do not summarise label counts in intermediate prints; stored only in execution record.
        "n_positives": int(np.asarray(y).astype(int).sum()),
    }
    return X, y, meta


def predict_classical(model_name: str, model_path: Path, X_agg: np.ndarray) -> np.ndarray:
    if model_name == "xgboost":
        model = XGBClassifier()
        model.load_model(str(model_path))
        return np.asarray(model.predict_proba(X_agg)[:, 1], dtype=np.float64)
    if model_name == "random_forest":
        model = joblib.load(model_path)
        return np.asarray(model.predict_proba(X_agg)[:, 1], dtype=np.float64)
    raise ProtocolAccessError(f"Unknown classical model: {model_name}")


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


@torch.no_grad()
def predict_attention_linear(model_path: Path, config: dict[str, Any], X_seq: np.ndarray) -> np.ndarray:
    from models.sequence_ensemble import SequenceEnsembleModel

    device = _device()
    model = SequenceEnsembleModel(
        input_dim=int(config.get("feature_dim", 13)),
        hidden_size=int(config["hidden_size"]),
        dropout=float(config["dropout"]),
        attention_dim=int(config["attention_dim"]),
        n_trees=5,
        tree_depth=4,
        classification_head="linear",
        temporal_aggregation="attention",
    ).to(device)
    payload = torch.load(model_path, map_location="cpu", weights_only=False)
    state = payload["model_state_dict"] if isinstance(payload, dict) and "model_state_dict" in payload else payload
    model.load_state_dict(state)
    model.eval()
    loader = DataLoader(_SeqDataset(X_seq, np.zeros(len(X_seq), dtype=np.float32)), batch_size=int(config.get("batch_size", 1024)), shuffle=False)
    probs: list[np.ndarray] = []
    for xb, _ in loader:
        out = model(xb.to(device))
        logits = out[0] if isinstance(out, tuple) else out
        probs.append(torch.sigmoid(logits).detach().cpu().numpy())
    return np.concatenate(probs).astype(np.float64)


@torch.no_grad()
def predict_odst(model_path: Path, config: dict[str, Any], X_seq: np.ndarray) -> np.ndarray:
    from prototype_v3_node.architecture import AttentionNodeEnsemble

    device = _device()
    model = AttentionNodeEnsemble(
        input_dim=int(config.get("feature_dim", 13)),
        hidden_size=int(config.get("encoder_hidden_size", 64)),
        dropout=float(config.get("encoder_dropout", 0.2)),
        attention_dim=int(config.get("encoder_attention_dim", 64)),
        fusion_variant=str(config.get("fusion_variant", "sparsemax_sigmoid_odst")),
        node_num_layers=int(config.get("node_num_layers", 2)),
        node_n_trees=int(config.get("n_trees", 8)),
        node_depth=int(config.get("tree_depth", 4)),
        node_tree_dim=int(config.get("node_tree_dim", 1)),
        node_temperature=float(config.get("node_temperature_init", 1.0)),
    ).to(device)
    payload = torch.load(model_path, map_location="cpu", weights_only=False)
    state = payload["model_state_dict"] if isinstance(payload, dict) and "model_state_dict" in payload else payload
    model.load_state_dict(state)
    model.eval()
    loader = DataLoader(
        _SeqDataset(X_seq, np.zeros(len(X_seq), dtype=np.float32)),
        batch_size=int(config.get("batch_size", 1024)),
        shuffle=False,
    )
    probs: list[np.ndarray] = []
    for xb, _ in loader:
        out = model(xb.to(device))
        logits = out[0] if isinstance(out, tuple) else out
        probs.append(torch.sigmoid(logits).detach().cpu().numpy())
    return np.concatenate(probs).astype(np.float64)


def prepare_test_matrices(X_seq: np.ndarray) -> tuple[np.ndarray, list[str]]:
    return aggregate_common13_windows(X_seq)


def predict_one(
    *,
    model: str,
    model_path: Path,
    config_path: Path | None,
    X_seq: np.ndarray,
    X_agg: np.ndarray,
) -> np.ndarray:
    if model in {"xgboost", "random_forest"}:
        return predict_classical(model, model_path, X_agg)
    import json

    if config_path is None or not config_path.exists():
        raise ProtocolAccessError(f"Missing config for neural model at {config_path}")
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if model == "attention_linear":
        return predict_attention_linear(model_path, cfg, X_seq)
    if model == "odst":
        return predict_odst(model_path, cfg, X_seq)
    raise ProtocolAccessError(f"Unexpected model for inference: {model}")
