#!/usr/bin/env python3
"""CERT r4.2 validation-only native explanation pilot helpers (Obj3 / Chapter 3).

Selected models only: ODST + attention–linear (seed 42). Soft forest unused.
No faithfulness, robustness, IG/SHAP/LIME, threshold retuning, or training.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from objective3_locked_common import SAFE_FEATURES, SEQ_LEN, N_FEATURES, sha256_file
from objective3_model_interface import (
    load_objective3_model,
    objective3_inference,
    parameter_digest,
)
from objective3_model_registry import (
    NEURAL_REFERENCE_ARCHITECTURE,
    PRIMARY_ARCHITECTURE,
    ProtectedPartitionError,
    get_registry_entry,
)
from objective3_odst_loader import repo_root, resolve_checkpoint_path

SAMPLING_SEED = 20260724
MAX_PER_STRATUM = 5
MAX_PER_USER = 2
PROTOCOL_ID = "obj3_native_explanation_pilot_r42_validation_seed42"
VALIDATION_TENSOR_REL = "data/processed/tensors/r42_T20_s1_validation.npz"
FORBIDDEN_PARTITION_MARKERS = (
    "r52_T20_s1_test",
    "r5.2_test",
    "r62",
    "r6.2",
    "r42_T20_s1_test",
)


class ProtocolVerificationError(RuntimeError):
    """Raised when protocol identity cannot be verified."""


@dataclass(frozen=True)
class FrozenThresholds:
    odst: float
    attention_linear: float
    odst_path: str
    attention_linear_path: str


def stable_selection_hash(sequence_id: str, sampling_seed: int = SAMPLING_SEED) -> str:
    payload = f"{int(sampling_seed)}|{sequence_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def selection_sort_key(sequence_id: str, sampling_seed: int = SAMPLING_SEED) -> str:
    return stable_selection_hash(sequence_id, sampling_seed)


def load_frozen_threshold(path: Path) -> float:
    if not path.exists():
        raise ProtocolVerificationError(f"Missing frozen threshold file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "selected_threshold" not in payload:
        raise ProtocolVerificationError(
            f"Threshold file missing selected_threshold: {path}"
        )
    return float(payload["selected_threshold"])


def verify_protocol(
    *,
    dataset_version: str,
    partition: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Verify r4.2 validation protocol identity; raise if unsafe/uncertain."""
    root = root or repo_root()
    ds = str(dataset_version).strip().lower().replace("cert ", "")
    part = str(partition).strip().lower()

    if ds not in {"r4.2", "4.2", "r42"}:
        raise ProtocolVerificationError(
            f"This pilot requires --dataset-version r4.2; got {dataset_version!r}"
        )
    if part != "validation":
        raise ProtocolVerificationError(
            f"This pilot requires --partition validation; got {partition!r}. "
            "r5.2 test / r6.2 / unspecified partitions are rejected."
        )

    tensor_path = (root / VALIDATION_TENSOR_REL).resolve()
    if not tensor_path.exists():
        raise ProtocolVerificationError(f"Validation tensor missing: {tensor_path}")
    text_path = str(tensor_path).replace("\\", "/").lower()
    for marker in FORBIDDEN_PARTITION_MARKERS:
        if marker in text_path and "validation" not in Path(text_path).name:
            raise ProtocolVerificationError(
                f"Refusing tensor path containing protected marker {marker}: {tensor_path}"
            )
    if "r42_t20_s1_test" in text_path:
        raise ProtocolVerificationError("Refusing r4.2 test tensor for this pilot")

    # Feature order is locked to SAFE_FEATURES used by create_sequence_tensors.py
    feature_order = list(SAFE_FEATURES)
    if len(feature_order) != N_FEATURES:
        raise ProtocolVerificationError("Feature order length mismatch")

    odst_entry = get_registry_entry(PRIMARY_ARCHITECTURE, "r4.2", 42)
    lin_entry = get_registry_entry(NEURAL_REFERENCE_ARCHITECTURE, "r4.2", 42)
    odst_ckpt = resolve_checkpoint_path(odst_entry.checkpoint_path, root=root)
    lin_ckpt = resolve_checkpoint_path(lin_entry.checkpoint_path, root=root)
    odst_hash = sha256_file(odst_ckpt)
    lin_hash = sha256_file(lin_ckpt)
    if odst_hash != odst_entry.checkpoint_sha256:
        raise ProtocolVerificationError(
            f"ODST checkpoint hash mismatch: {odst_hash} != {odst_entry.checkpoint_sha256}"
        )
    if lin_hash != lin_entry.checkpoint_sha256:
        raise ProtocolVerificationError(
            f"Attention–linear checkpoint hash mismatch: {lin_hash} != {lin_entry.checkpoint_sha256}"
        )

    odst_thr_path = resolve_checkpoint_path(
        odst_entry.threshold_metadata_path or "", root=root
    )
    lin_thr_path = resolve_checkpoint_path(
        lin_entry.threshold_metadata_path or "", root=root
    )
    odst_thr = load_frozen_threshold(odst_thr_path)
    lin_thr = load_frozen_threshold(lin_thr_path)

    z = np.load(tensor_path, allow_pickle=True, mmap_mode="r")
    required = {"X", "y", "sequence_id", "user", "start_date", "end_date"}
    missing = required - set(z.files)
    if missing:
        raise ProtocolVerificationError(f"Validation tensor missing keys: {sorted(missing)}")
    x_shape = tuple(z["X"].shape)
    if x_shape[1] != SEQ_LEN or x_shape[2] != N_FEATURES:
        raise ProtocolVerificationError(f"Unexpected validation X shape: {x_shape}")

    scaler_path = root / "data/processed/tensors/r42_T20_s1_train_scaler_stats.json"
    scaler_status = "present" if scaler_path.exists() else "missing_on_disk_but_train_only_scaling_documented"

    protocol = {
        "protocol_identifier": PROTOCOL_ID,
        "dataset_version": "r4.2",
        "partition": "validation",
        "partition_role": "r42_development",
        "validation_dataset_path": VALIDATION_TENSOR_REL,
        "validation_sequence_manifest_fields": [
            "sequence_id",
            "user",
            "start_date",
            "end_date",
            "y",
        ],
        "validation_tensor_sha256": sha256_file(tensor_path),
        "n_sequences": int(x_shape[0]),
        "sequence_length": SEQ_LEN,
        "feature_count": N_FEATURES,
        "feature_order": feature_order,
        "feature_order_source": "scripts/create_sequence_tensors.py::SAFE_FEATURES",
        "scaler_or_transform_metadata": {
            "path": str(scaler_path.relative_to(root)).replace("\\", "/")
            if scaler_path.exists()
            else None,
            "status": scaler_status,
            "documented_rule": "TrainOnlyStandardScaler fitted on train daily rows only",
        },
        "user_identifier_field": "user",
        "window_start_field": "start_date",
        "window_end_field": "end_date",
        "timestep_to_date_mapping": "calendar_date[t] = start_date + t days (t=0..19)",
        "ground_truth_label_field": "y",
        "models": {
            PRIMARY_ARCHITECTURE: {
                "seed": 42,
                "checkpoint_path": odst_entry.checkpoint_path,
                "checkpoint_sha256": odst_hash,
                "threshold": odst_thr,
                "threshold_path": str(odst_thr_path.relative_to(root)).replace("\\", "/"),
                "registry_key": odst_entry.registry_key,
                "loader_type": "odst",
            },
            NEURAL_REFERENCE_ARCHITECTURE: {
                "seed": 42,
                "checkpoint_path": lin_entry.checkpoint_path,
                "checkpoint_sha256": lin_hash,
                "threshold": lin_thr,
                "threshold_path": str(lin_thr_path.relative_to(root)).replace("\\", "/"),
                "registry_key": lin_entry.registry_key,
                "loader_type": "attention_linear",
            },
        },
        "sampling_seed": SAMPLING_SEED,
        "max_per_stratum": MAX_PER_STRATUM,
        "max_per_user": MAX_PER_USER,
        "forbidden": {
            "r42_test": True,
            "r52_test": True,
            "r62": True,
            "threshold_reselection": True,
            "training": True,
            "faithfulness": True,
            "robustness_perturbations": True,
        },
        "verified_at": datetime.utcnow().isoformat() + "Z",
    }
    return protocol


def timestep_calendar_dates(start_date: str, seq_len: int = SEQ_LEN) -> list[str]:
    start = datetime.strptime(str(start_date)[:10], "%Y-%m-%d")
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(seq_len)]


def predict_validation_probabilities(
    model_id: str,
    *,
    x: np.ndarray,
    threshold: float,
    batch_size: int = 1024,
    root: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, str]:
    """Return (probs, preds, param_digest_before==after)."""
    loaded = load_objective3_model(
        model_id,
        "r4.2",
        42,
        device="cpu",
        partition_role="r42_development",
        root=root,
    )
    before = parameter_digest(loaded.model)
    probs: list[np.ndarray] = []
    model = loaded.model
    model.eval()
    with torch.no_grad():
        for start in range(0, len(x), batch_size):
            xb = torch.from_numpy(np.asarray(x[start : start + batch_size], dtype=np.float32))
            logits, _ = model(xb)
            probs.append(torch.sigmoid(logits).cpu().numpy())
    after = parameter_digest(loaded.model)
    if before != after:
        raise RuntimeError(f"Parameter mutation during prediction for {model_id}")
    p = np.concatenate(probs, axis=0).astype(np.float64)
    pred = (p >= float(threshold)).astype(np.int8)
    return p, pred, before


def assign_joint_strata(
    y: np.ndarray, pred_odst: np.ndarray, pred_lin: np.ndarray
) -> np.ndarray:
    y = np.asarray(y).astype(int)
    po = np.asarray(pred_odst).astype(int)
    pl = np.asarray(pred_lin).astype(int)
    strata = np.full(len(y), "", dtype=object)
    mal = y == 1
    ben = y == 0
    strata[mal & (po == 1) & (pl == 1)] = "A_malicious_detected_both"
    strata[mal & ~((po == 1) & (pl == 1))] = "B_malicious_missed_at_least_one"
    strata[ben & ((po == 1) | (pl == 1))] = "C_benign_false_flag_at_least_one"
    strata[ben & (po == 0) & (pl == 0)] = "D_benign_correct_both"
    if (strata == "").any():
        raise RuntimeError("Unassigned joint strata remain")
    return strata


def select_pilot_sample(
    *,
    sequence_id: np.ndarray,
    user: np.ndarray,
    start_date: np.ndarray,
    end_date: np.ndarray,
    y: np.ndarray,
    strata: np.ndarray,
    p_odst: np.ndarray,
    p_lin: np.ndarray,
    pred_odst: np.ndarray,
    pred_lin: np.ndarray,
    thr_odst: float,
    thr_lin: float,
    sampling_seed: int = SAMPLING_SEED,
    max_per_stratum: int = MAX_PER_STRATUM,
    max_per_user: int = MAX_PER_USER,
) -> pd.DataFrame:
    """Deterministic stratified sample; no confidence/explanation ranking."""
    rows: list[dict[str, Any]] = []
    shortages: list[str] = []
    used_global: set[str] = set()

    stratum_order = [
        "A_malicious_detected_both",
        "B_malicious_missed_at_least_one",
        "C_benign_false_flag_at_least_one",
        "D_benign_correct_both",
    ]
    for stratum in stratum_order:
        idxs = np.where(strata == stratum)[0]
        # Deterministic sort by selection hash, then sequence_id
        keyed = sorted(
            idxs,
            key=lambda i: (
                selection_sort_key(str(sequence_id[i]), sampling_seed),
                str(sequence_id[i]),
            ),
        )
        selected: list[int] = []
        user_counts: dict[str, int] = {}
        relaxed = False

        def try_pick(allow_relax: bool) -> None:
            nonlocal selected, user_counts
            selected_set = set(selected)
            for i in keyed:
                if i in selected_set:
                    continue
                sid = str(sequence_id[i])
                if sid in used_global:
                    continue
                uid = str(user[i])
                if not allow_relax and user_counts.get(uid, 0) >= max_per_user:
                    continue
                selected.append(i)
                selected_set.add(i)
                user_counts[uid] = user_counts.get(uid, 0) + 1
                if len(selected) >= max_per_stratum:
                    return

        try_pick(allow_relax=False)
        if len(selected) < max_per_stratum:
            # Relax user cap after documenting shortage intent
            relaxed = True
            try_pick(allow_relax=True)
        if len(selected) < max_per_stratum:
            shortages.append(
                f"{stratum}: available={len(idxs)} selected={len(selected)} "
                f"(requested={max_per_stratum})"
            )

        for rank, i in enumerate(selected, start=1):
            sid = str(sequence_id[i])
            used_global.add(sid)
            uid = str(user[i])
            po = int(pred_odst[i])
            pl = int(pred_lin[i])
            agree = "agree" if po == pl else "disagree"
            rows.append(
                {
                    "sample_id": f"S{len(rows)+1:02d}",
                    "sequence_id": sid,
                    "user_id": uid,
                    "window_start": str(start_date[i])[:10],
                    "window_end": str(end_date[i])[:10],
                    "ground_truth": int(y[i]),
                    "joint_stratum": stratum,
                    "ODST_probability": float(p_odst[i]),
                    "ODST_frozen_threshold": float(thr_odst),
                    "ODST_predicted_class": po,
                    "attention_linear_probability": float(p_lin[i]),
                    "attention_linear_frozen_threshold": float(thr_lin),
                    "attention_linear_predicted_class": pl,
                    "model_agreement": agree,
                    "selection_hash": stable_selection_hash(sid, sampling_seed),
                    "selection_rank": rank,
                    "inclusion_reason": (
                        f"first_{rank}_by_stable_hash_seed_{sampling_seed}"
                        + ("_user_cap_relaxed" if relaxed and user_counts.get(uid, 0) > max_per_user else "")
                    ),
                    "duplicate_user_flag": int(user_counts.get(uid, 0) > 1),
                    "validation_row_index": int(i),
                    "user_cap_relaxed_in_stratum": int(relaxed),
                }
            )

    manifest = pd.DataFrame(rows)
    # Freeze sample_id order as selection order across strata
    if not manifest.empty:
        manifest["sample_id"] = [f"S{i:02d}" for i in range(1, len(manifest) + 1)]
        user_freq = manifest["user_id"].value_counts()
        manifest["duplicate_user_flag"] = manifest["user_id"].map(lambda u: int(user_freq[u] > 1))
    manifest.attrs["shortages"] = shortages
    return manifest


def spearman_corr(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    if a.size != b.size or a.size < 2:
        return float("nan")
    ra = pd.Series(a).rank(method="average").to_numpy()
    rb = pd.Series(b).rank(method="average").to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def pearson_corr(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    if a.size != b.size or a.size < 2:
        return float("nan")
    if np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    return float(len(a & b) / len(u)) if u else float("nan")


def top_k_indices(weights: np.ndarray, k: int) -> list[int]:
    w = np.asarray(weights, dtype=np.float64)
    k = min(k, w.size)
    # Stable: highest weight first; ties broken by earlier timestep
    order = np.lexsort((np.arange(w.size), -w))
    return [int(i) for i in order[:k]]


def attention_entropy(weights: np.ndarray, eps: float = 1e-12) -> float:
    w = np.asarray(weights, dtype=np.float64)
    w = np.clip(w, eps, None)
    return float(-(w * np.log(w)).sum())


def normalised_attention_entropy(weights: np.ndarray, n_valid: int | None = None) -> float:
    w = np.asarray(weights, dtype=np.float64)
    n = int(n_valid if n_valid is not None else w.size)
    if n <= 1:
        return 0.0
    return float(attention_entropy(w) / np.log(n))


def section_masses(weights: np.ndarray) -> dict[str, float]:
    w = np.asarray(weights, dtype=np.float64)
    return {
        "early_mass_t1_7": float(w[0:7].sum()),
        "middle_mass_t8_14": float(w[7:14].sum()),
        "late_mass_t15_20": float(w[14:20].sum()),
    }


def run_sample_inference(
    model_id: str,
    *,
    x_sample: np.ndarray,
    threshold: float,
    root: Path | None = None,
) -> dict[str, Any]:
    loaded = load_objective3_model(
        model_id,
        "r4.2",
        42,
        device="cpu",
        partition_role="r42_development",
        root=root,
    )
    before = parameter_digest(loaded.model)
    result = objective3_inference(
        loaded,
        torch.from_numpy(np.asarray(x_sample, dtype=np.float32)),
        threshold=threshold,
        return_explanations=True,
        require_gradients=False,
    )
    after = parameter_digest(loaded.model)
    return {
        "loaded": loaded,
        "result": result,
        "param_digest_before": before,
        "param_digest_after": after,
        "params_unchanged": before == after,
    }


def summarise_descriptive(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {
            "count": 0,
            "mean": float("nan"),
            "std": float("nan"),
            "median": float("nan"),
            "min": float("nan"),
            "max": float("nan"),
        }
    return {
        "count": int(arr.size),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        "median": float(np.median(arr)),
        "min": float(arr.min()),
        "max": float(arr.max()),
    }


__all__ = [
    "MAX_PER_STRATUM",
    "MAX_PER_USER",
    "PROTOCOL_ID",
    "ProtocolVerificationError",
    "ProtectedPartitionError",
    "SAMPLING_SEED",
    "assign_joint_strata",
    "attention_entropy",
    "jaccard",
    "load_frozen_threshold",
    "normalised_attention_entropy",
    "pearson_corr",
    "predict_validation_probabilities",
    "run_sample_inference",
    "section_masses",
    "select_pilot_sample",
    "spearman_corr",
    "stable_selection_hash",
    "summarise_descriptive",
    "timestep_calendar_dates",
    "top_k_indices",
    "verify_protocol",
]
