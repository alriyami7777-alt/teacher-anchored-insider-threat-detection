"""Hash-gated import of producing feasibility architecture. Paper-support copies are not used."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .safety import (
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SEQUENCE_ENSEMBLE_SHA256,
    FEAS_SCRIPTS,
    Editor009ProtocolError,
    require_hash,
)

ARCHITECTURE = {
    "input_dim": 13,
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "fusion_variant": "sparsemax_sigmoid_odst",
    "node_num_layers": 2,
    "node_n_trees": 8,
    "node_depth": 4,
    "node_tree_dim": 1,
    "node_temperature": 1.0,
    "node_dropout": 0.0,
    "leaf_init_std": 0.05,
    "gate_hidden_dim": 32,
}

ATTN_ARCH = {
    "input_dim": 13,
    "hidden_size": 64,
    "dropout": 0.2,
    "attention_dim": 64,
    "n_trees": 5,
    "tree_depth": 4,
    "classification_head": "linear",
    "temporal_aggregation": "attention",
}


def pin_producing_sources() -> dict[str, str]:
    arch = FEAS_SCRIPTS / "prototype_v3_node" / "architecture.py"
    odst = FEAS_SCRIPTS / "prototype_v3_node" / "odst.py"
    seq = FEAS_SCRIPTS / "models" / "sequence_ensemble.py"
    return {
        "architecture": require_hash(arch, EXPECTED_ARCHITECTURE_SHA256, role="architecture"),
        "odst": require_hash(odst, EXPECTED_ODST_SHA256, role="odst"),
        "sequence_ensemble": require_hash(
            seq, EXPECTED_SEQUENCE_ENSEMBLE_SHA256, role="sequence_ensemble"
        ),
    }


def _ensure_producing_paths() -> None:
    pin_producing_sources()
    feas = str(FEAS_SCRIPTS)
    if feas in sys.path:
        sys.path.remove(feas)
    sys.path.insert(0, feas)
    drop_prefixes = ("prototype_v3_node",)
    for name in list(sys.modules):
        if name == "models.sequence_ensemble" or any(
            name == prefix or name.startswith(prefix + ".") for prefix in drop_prefixes
        ):
            mod = sys.modules.get(name)
            filename = (getattr(mod, "__file__", "") or "").replace("\\", "/")
            if filename and "cert-r42-feasibility/scripts" not in filename:
                del sys.modules[name]


def import_attention_node_ensemble():
    _ensure_producing_paths()
    from prototype_v3_node.architecture import AttentionNodeEnsemble  # noqa: WPS433

    return AttentionNodeEnsemble


def import_sequence_ensemble_model():
    _ensure_producing_paths()
    from models.sequence_ensemble import SequenceEnsembleModel  # noqa: WPS433

    return SequenceEnsembleModel


def import_set_seed():
    _ensure_producing_paths()
    from prototype_v3_node.train import set_seed  # noqa: WPS433

    return set_seed


def import_threshold_fns():
    _ensure_producing_paths()
    from prototype_v3_node.train import choose_threshold_f1, metrics_at_threshold  # noqa: WPS433

    return choose_threshold_f1, metrics_at_threshold


def build_odst_model(**kwargs: Any):
    AttentionNodeEnsemble = import_attention_node_ensemble()
    cfg = dict(ARCHITECTURE)
    cfg.update(kwargs)
    return AttentionNodeEnsemble(**cfg)


def build_attention_linear(**kwargs: Any):
    SequenceEnsembleModel = import_sequence_ensemble_model()
    cfg = dict(ATTN_ARCH)
    cfg.update(kwargs)
    return SequenceEnsembleModel(**cfg)


def load_state_dict(model, path: str | Path, *, strict: bool = True) -> dict[str, Any]:
    import torch

    path = Path(path)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict) or "model_state_dict" not in payload:
        raise Editor009ProtocolError(f"checkpoint missing model_state_dict: {path}")
    missing, unexpected = model.load_state_dict(payload["model_state_dict"], strict=strict)
    return {"missing_keys": list(missing), "unexpected_keys": list(unexpected)}
