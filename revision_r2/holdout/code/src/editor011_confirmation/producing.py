"""Hash-gated import of producing feasibility architecture."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .constants import ENCODER_ARCH
from .safety import (
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SEQUENCE_ENSEMBLE_SHA256,
    FEAS_SCRIPTS,
    Editor011ProtocolError,
    require_hash,
)


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
    for name in list(sys.modules):
        if name == "models.sequence_ensemble" or name == "prototype_v3_node" or name.startswith(
            "prototype_v3_node."
        ):
            mod = sys.modules.get(name)
            filename = (getattr(mod, "__file__", "") or "").replace("\\", "/")
            if filename and "cert-r42-feasibility/scripts" not in filename:
                del sys.modules[name]


def import_attention_node_ensemble():
    _ensure_producing_paths()
    from prototype_v3_node.architecture import AttentionNodeEnsemble  # noqa: WPS433

    return AttentionNodeEnsemble


def import_set_seed():
    _ensure_producing_paths()
    from prototype_v3_node.train import set_seed  # noqa: WPS433

    return set_seed


def import_threshold_fns():
    _ensure_producing_paths()
    from prototype_v3_node.train import choose_threshold_f1, metrics_at_threshold  # noqa: WPS433

    return choose_threshold_f1, metrics_at_threshold


def import_load_v1():
    _ensure_producing_paths()
    from prototype_v3_node.architecture import load_v1_attention_linear_checkpoint  # noqa: WPS433

    return load_v1_attention_linear_checkpoint


def build_odst046_model(**kwargs: Any):
    AttentionNodeEnsemble = import_attention_node_ensemble()
    cfg = dict(ENCODER_ARCH)
    cfg.update(kwargs)
    if int(cfg["node_n_trees"]) != 4 or int(cfg["node_depth"]) != 4:
        raise Editor011ProtocolError("ODST-046 identity mismatch in constructor")
    if float(cfg["node_temperature"]) != 0.5:
        raise Editor011ProtocolError("ODST-046 temperature mismatch")
    return AttentionNodeEnsemble(**cfg)


def load_state_dict(model, path: str | Path, *, strict: bool = True) -> dict[str, Any]:
    import torch

    path = Path(path)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict) or "model_state_dict" not in payload:
        raise Editor011ProtocolError(f"checkpoint missing model_state_dict: {path}")
    missing, unexpected = model.load_state_dict(payload["model_state_dict"], strict=strict)
    return {"missing_keys": list(missing), "unexpected_keys": list(unexpected)}
