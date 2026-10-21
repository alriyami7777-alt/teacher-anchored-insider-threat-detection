"""Hash-gated loaders. Adapters around frozen producing implementations.

Does not edit producing source. Does not import training runners.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import torch
from sklearn.ensemble import RandomForestClassifier  # noqa: F401  # pin sklearn.tree DLLs before path mutation

from .hash_gate import gate_one
from .safety import (
    BATCH_SIZE_FROZEN,
    CHECKPOINT_STATE_KEY,
    EXPECTED_AGGREGATOR_SHA256,
    EXPECTED_ARCHITECTURE_SHA256,
    EXPECTED_ODST_SHA256,
    EXPECTED_SEQUENCE_ENSEMBLE_SHA256,
    FEAS_SCRIPTS,
    LOCKED_SCRIPTS,
    REGISTER,
    HarnessProtocolError,
    sha256_file,
)

NEURAL_FAMILIES = {"teacher_frozen_odst", "C2", "C5_original_paper", "attention_linear"}
CLASSICAL_FAMILIES = {"RF_40", "XGBoost_40"}

ODST_ARCH = {
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


def require_source_hash(
    *,
    component: str,
    path: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    """Abort before architecture/model construction on source SHA mismatch."""
    path = Path(path)
    if not path.is_file():
        raise HarnessProtocolError(
            f"SOURCE HASH GATE ABORT BEFORE ARCHITECTURE CONSTRUCTION: "
            f"missing {component} at {path}"
        )
    observed = sha256_file(path)
    row = {
        "component": component,
        "source_path": str(path),
        "expected_sha256": expected_sha256,
        "observed_sha256": observed,
        "status": "MATCH" if observed == expected_sha256 else "MISMATCH",
    }
    if observed != expected_sha256:
        raise HarnessProtocolError(
            "SOURCE HASH GATE ABORT BEFORE ARCHITECTURE CONSTRUCTION: "
            f"component={component} expected={expected_sha256} observed={observed} path={path}"
        )
    return row


def producing_source_paths() -> dict[str, Path]:
    return {
        "teacher_c2_c5_architecture": FEAS_SCRIPTS / "prototype_v3_node" / "architecture.py",
        "odst_implementation": FEAS_SCRIPTS / "prototype_v3_node" / "odst.py",
        "attention_linear": FEAS_SCRIPTS / "models" / "sequence_ensemble.py",
        "rf_xgb_aggregator": LOCKED_SCRIPTS / "r52_locked_baselines" / "data.py",
    }


def producing_source_expected_hashes() -> dict[str, str]:
    return {
        "teacher_c2_c5_architecture": EXPECTED_ARCHITECTURE_SHA256,
        "odst_implementation": EXPECTED_ODST_SHA256,
        "attention_linear": EXPECTED_SEQUENCE_ENSEMBLE_SHA256,
        "rf_xgb_aggregator": EXPECTED_AGGREGATOR_SHA256,
    }


def producing_source_preflight() -> dict[str, Any]:
    """Hash the exact files that will be imported. Fail closed before construction."""
    rows = []
    paths = producing_source_paths()
    expected = producing_source_expected_hashes()
    for component, path in paths.items():
        rows.append(
            require_source_hash(
                component=component,
                path=path,
                expected_sha256=expected[component],
            )
        )
    return {"status": "PASS", "components": rows}


def construct_if_source_hash_ok(
    *,
    component: str,
    path: Path,
    expected_sha256: str,
    construct: Callable[[], Any],
) -> Any:
    require_source_hash(component=component, path=path, expected_sha256=expected_sha256)
    return construct()


def _ensure_producing_paths() -> None:
    feas = str(FEAS_SCRIPTS)
    locked = str(LOCKED_SCRIPTS)
    # Producing scripts first so paper-support copies cannot shadow them.
    for p in (feas, locked):
        if p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, locked)
    sys.path.insert(0, feas)
    # Drop previously imported paper-support copies of the same top-level packages.
    drop_prefixes = ("prototype_v3_node", "r52_locked_baselines")
    for name in list(sys.modules):
        if name == "models.sequence_ensemble" or any(
            name == prefix or name.startswith(prefix + ".") for prefix in drop_prefixes
        ):
            mod = sys.modules.get(name)
            filename = (getattr(mod, "__file__", "") or "").replace("\\", "/")
            allowed = ("cert-r42-feasibility/scripts", "cert-r52-locked-baselines/scripts")
            if filename and not any(token in filename for token in allowed):
                del sys.modules[name]



def architecture_pins() -> dict[str, Any]:
    preflight = producing_source_preflight()
    arch = FEAS_SCRIPTS / "prototype_v3_node" / "architecture.py"
    odst = FEAS_SCRIPTS / "prototype_v3_node" / "odst.py"
    seq = FEAS_SCRIPTS / "models" / "sequence_ensemble.py"
    data = LOCKED_SCRIPTS / "r52_locked_baselines" / "data.py"
    return {
        "source_hash_preflight": preflight,
        "teacher_c2_c5": {
            "source_file": str(arch),
            "source_sha256": sha256_file(arch),
            "expected_sha256": EXPECTED_ARCHITECTURE_SHA256,
            "supporting_file": str(odst),
            "supporting_sha256": sha256_file(odst),
            "supporting_expected_sha256": EXPECTED_ODST_SHA256,
            "class": "AttentionNodeEnsemble",
            "configuration": dict(ODST_ARCH),
            "checkpoint_schema": {
                "torch_load": "weights_only=True",
                "state_key": CHECKPOINT_STATE_KEY,
                "load_state_dict": "strict=True",
            },
        },
        "attention_linear": {
            "source_file": str(seq),
            "source_sha256": sha256_file(seq),
            "expected_sha256": EXPECTED_SEQUENCE_ENSEMBLE_SHA256,
            "class": "SequenceEnsembleModel",
            "configuration": dict(ATTN_ARCH),
            "checkpoint_schema": {
                "torch_load": "weights_only=True",
                "state_key": CHECKPOINT_STATE_KEY,
                "load_state_dict": "strict=True",
            },
        },
        "rf_xgb_aggregator": {
            "source_file": str(data),
            "source_sha256": sha256_file(data),
            "function": "aggregate_common13_windows",
            "expected_sha256": EXPECTED_AGGREGATOR_SHA256,
        },
    }


def import_aggregate_common13_windows() -> Callable[[np.ndarray], tuple[np.ndarray, list[str]]]:
    producing_source_preflight()
    data_py = LOCKED_SCRIPTS / "r52_locked_baselines" / "data.py"
    require_source_hash(
        component="rf_xgb_aggregator",
        path=data_py,
        expected_sha256=EXPECTED_AGGREGATOR_SHA256,
    )
    _ensure_producing_paths()
    from r52_locked_baselines.data import aggregate_common13_windows  # noqa: WPS433

    return aggregate_common13_windows


def _extract_state_dict(payload: Any) -> dict[str, torch.Tensor]:
    if not isinstance(payload, dict):
        raise HarnessProtocolError("Checkpoint is not a dict; refusing heuristic unwrap")
    if CHECKPOINT_STATE_KEY not in payload:
        raise HarnessProtocolError(
            f"Checkpoint missing required key {CHECKPOINT_STATE_KEY!r}; "
            "refusing to search alternate keys"
        )
    state = payload[CHECKPOINT_STATE_KEY]
    if not isinstance(state, dict):
        raise HarnessProtocolError("model_state_dict is not a mapping")
    return state


def _freeze_eval(model: torch.nn.Module) -> torch.nn.Module:
    model.eval()
    for param in model.parameters():
        param.requires_grad = False
    if any(p.requires_grad for p in model.parameters()):
        raise HarnessProtocolError("Parameter still requires_grad after freeze")
    return model


def state_hash(model: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in model.state_dict().items():
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        arr = tensor.detach().cpu().contiguous().numpy().tobytes()
        digest.update(arr)
    return digest.hexdigest()


def load_neural_checkpoint(
    *,
    family: str,
    seed: int,
    path: str | Path,
    expected_sha256: str,
    deny_hashes: set[str],
    allow_hashes: set[str],
) -> dict[str, Any]:
    gate = gate_one(
        family=family,
        seed=seed,
        path=path,
        expected_sha256=expected_sha256,
        deny_hashes=deny_hashes,
        allow_hashes=allow_hashes,
    )
    REGISTER.note(path, f"model_{family}_{seed}")
    producing_source_preflight()
    _ensure_producing_paths()
    try:
        payload = torch.load(Path(path), map_location="cpu", weights_only=True)
    except Exception as exc:  # noqa: BLE001
        raise HarnessProtocolError(
            f"torch.load(weights_only=True) failed; refusing unsafe fallback: {exc}"
        ) from exc
    state = _extract_state_dict(payload)
    if family == "attention_linear":
        from models.sequence_ensemble import SequenceEnsembleModel  # noqa: WPS433

        model = SequenceEnsembleModel(**ATTN_ARCH)
    elif family in {"teacher_frozen_odst", "C2", "C5_original_paper"}:
        from prototype_v3_node.architecture import AttentionNodeEnsemble  # noqa: WPS433

        model = AttentionNodeEnsemble(**ODST_ARCH)
    else:
        raise HarnessProtocolError(f"Not a neural family: {family}")
    incompatible = model.load_state_dict(state, strict=True)
    missing = list(getattr(incompatible, "missing_keys", []) or [])
    unexpected = list(getattr(incompatible, "unexpected_keys", []) or [])
    if missing or unexpected:
        raise HarnessProtocolError(
            f"strict=True load failed family={family} seed={seed} "
            f"missing={missing} unexpected={unexpected}"
        )
    model = _freeze_eval(model)
    return {
        "family": family,
        "seed": seed,
        "path": str(path),
        "model": model,
        "gate": gate,
        "n_state_keys": len(state),
        "missing_keys": missing,
        "unexpected_keys": unexpected,
        "requires_grad_any": any(p.requires_grad for p in model.parameters()),
        "state_hash": state_hash(model),
        "payload_keys": sorted(str(k) for k in payload.keys()),
    }


def load_rf(
    *,
    seed: int,
    path: str | Path,
    expected_sha256: str,
    deny_hashes: set[str],
    allow_hashes: set[str],
) -> dict[str, Any]:
    gate = gate_one(
        family="RF_40",
        seed=seed,
        path=path,
        expected_sha256=expected_sha256,
        deny_hashes=deny_hashes,
        allow_hashes=allow_hashes,
    )
    REGISTER.note(path, f"model_RF_40_{seed}")
    before = sha256_file(Path(path))
    model = joblib.load(Path(path))
    after = sha256_file(Path(path))
    if before != after:
        raise HarnessProtocolError("RF artefact mutated on load")
    return {"family": "RF_40", "seed": seed, "path": str(path), "model": model, "gate": gate, "file_sha256": after}


def load_xgb(
    *,
    seed: int,
    path: str | Path,
    expected_sha256: str,
    deny_hashes: set[str],
    allow_hashes: set[str],
) -> dict[str, Any]:
    from xgboost import XGBClassifier

    gate = gate_one(
        family="XGBoost_40",
        seed=seed,
        path=path,
        expected_sha256=expected_sha256,
        deny_hashes=deny_hashes,
        allow_hashes=allow_hashes,
    )
    REGISTER.note(path, f"model_XGBoost_40_{seed}")
    before = sha256_file(Path(path))
    model = XGBClassifier()
    model.load_model(str(path))
    after = sha256_file(Path(path))
    if before != after:
        raise HarnessProtocolError("XGBoost artefact mutated on load")
    return {
        "family": "XGBoost_40",
        "seed": seed,
        "path": str(path),
        "model": model,
        "gate": gate,
        "file_sha256": after,
    }


@torch.inference_mode()
def infer_neural(model: torch.nn.Module, x: np.ndarray, *, batch_size: int = BATCH_SIZE_FROZEN) -> np.ndarray:
    device = torch.device("cpu")
    model = model.to(device)
    model.eval()
    n = int(x.shape[0])
    out = np.empty((n,), dtype=np.float64)
    for lo in range(0, n, batch_size):
        hi = min(n, lo + batch_size)
        xb = torch.from_numpy(np.ascontiguousarray(x[lo:hi], dtype=np.float32)).to(device)
        result = model(xb)
        logits = result[0] if isinstance(result, tuple) else result
        out[lo:hi] = torch.sigmoid(logits).detach().cpu().numpy().reshape(-1)
    return out


def infer_classical(
    *,
    family: str,
    model: Any,
    x_seq: np.ndarray,
    aggregate_fn: Callable[[np.ndarray], tuple[np.ndarray, list[str]]],
) -> np.ndarray:
    feat, names = aggregate_fn(x_seq)
    if feat.shape[1] != 40:
        raise HarnessProtocolError(f"Aggregator produced {feat.shape[1]} features")
    if family == "RF_40":
        return np.asarray(model.predict_proba(feat)[:, 1], dtype=np.float64)
    if family == "XGBoost_40":
        return np.asarray(model.predict_proba(feat)[:, 1], dtype=np.float64)
    raise HarnessProtocolError(f"Not classical: {family}")
