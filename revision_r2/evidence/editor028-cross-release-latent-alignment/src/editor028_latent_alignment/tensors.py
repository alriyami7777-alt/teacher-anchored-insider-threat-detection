"""EDITOR-026 centred tensors plus an unlabeled r6.1 alignment population."""

from __future__ import annotations

import csv
from typing import Any

import numpy as np

from editor024_r61.cert_parse import CSV_FIELD_LIMIT, build_dense_daily, scan_source
from editor024_r61.constants import RAW_R61_ROOT, SOURCE_TYPES
from editor024_r61.scaler import load_r52_train_scaler, transform_only
from editor025_r61_autopsy.feature_shift import inverse_scale
from editor026_user_relative.tensors import (
    build_r52_ur_windows,
    fit_ur_scaler,
    load_frozen_r52_splits,
    load_r52_dense_raw,
    scale_by_user,
    transform_r52_user_relative,
)
from editor026_user_relative.windows import r61_gather_windows

from .alignment import UnlabeledAlignmentStore, assert_no_alignment_labels
from .constants import SEQUENCE_LENGTH_LOCKED
from .representation import causal_user_relative_panel
from .safety import Editor028Blocked


def construct_r52_centered(splits: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fit the network scaler on r5.2 TRAIN only after the EDITOR-026 transform."""
    splits = splits or load_frozen_r52_splits()
    dense = load_r52_dense_raw()
    ur_by_user = transform_r52_user_relative(dense)
    train_start = min(str(x) for x in splits["train"]["start_date"])
    train_end = max(str(x) for x in splits["train"]["end_date"])
    scaler = fit_ur_scaler(ur_by_user, dense["dates_by_user"], train_start, train_end)
    if scaler.fitted_on != "R52 TRAIN ONLY":
        raise Editor028Blocked("R61_SCALER_FIT must remain NO")
    scaled = scale_by_user(ur_by_user, scaler)
    x_train = build_r52_ur_windows(
        scaled_by_user=scaled, dates_by_user=dense["dates_by_user"], split=splits["train"]
    )
    x_val = build_r52_ur_windows(
        scaled_by_user=scaled, dates_by_user=dense["dates_by_user"], split=splits["val"]
    )
    return {
        "splits": splits,
        "dense": dense,
        "ur_by_user": ur_by_user,
        "scaler": scaler,
        "x_train": x_train,
        "x_val": x_val,
        "y_train": splits["train"]["y"],
        "y_val": splits["val"]["y"],
        "user_val": splits["val"]["user"],
        "seq_val": splits["val"]["sequence_id"],
        "train_start": train_start,
        "train_end": train_end,
        "R61_SCALER_FIT": "NO",
        "R61_TARGET_NORMALISATION_FIT": "NO",
    }


def construct_r61_unlabeled_raw() -> dict[str, Any]:
    """Build r6.1 completed windows from raw events. Answer files are not opened."""
    csv.field_size_limit(CSV_FIELD_LIMIT)
    user_index: dict[str, int] = {}
    user_list: list[str] = []
    active: dict[tuple[int, int], list[int]] = {}
    empty_answers: dict[str, set[str]] = {s: set() for s in SOURCE_TYPES}
    id_to_bit: dict[str, int] = {}
    match_counts: dict[str, int] = {}
    for source in SOURCE_TYPES:
        path = RAW_R61_ROOT / f"{source}.csv"
        if not path.is_file():
            raise Editor028Blocked(f"missing unlabeled r6.1 source {path}")
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            rec = scan_source(
                source,
                handle,
                source_answer_ids=empty_answers[source],
                id_to_bit=id_to_bit,
                match_counts=match_counts,
                active=active,
                user_index=user_index,
                user_list=user_list,
            )
        if not rec["header_ok"]:
            raise Editor028Blocked(f"r6.1 {source} header incompatible")
    built = build_dense_daily(user_list=user_list, active=active)
    orig = load_r52_train_scaler()
    # Inverse of the frozen original scaler is not required: we have raw counts.
    raw = np.asarray(built["raw"], dtype=np.float64)
    # Drop every label-bearing array before returning.
    return {
        "raw": raw,
        "user_idx": np.asarray(built["user_index"]),
        "start_idx": np.asarray(built["start_index"]),
        "user_ids_sorted": np.asarray(built["user_ids_sorted"], dtype=str),
        "user_ids_windows": np.asarray(built["user_ids_windows"]).astype(str),
        "sequence_ids": np.asarray(built["sequence_ids"]).astype(str),
        "calendar_dates": np.asarray(built["calendar_iso"]).astype(str),
        "original_scaler_sha256": orig["sha256"],
        "n_users": int(built["n_users"]),
        "n_days": int(built["n_days"]),
        "n_windows": int(built["n_windows"]),
    }


def unlabeled_alignment_from_raw(raw_pack: dict[str, Any], scaler) -> UnlabeledAlignmentStore:
    """Apply EDITOR-026 centred transform and the r5.2-train scaler. No labels."""
    forbidden = {"y", "malicious_day_labels", "day_bits"}
    leaked = forbidden.intersection(raw_pack)
    if leaked:
        raise Editor028Blocked(f"unlabeled raw pack leaked {sorted(leaked)}")
    ur_raw = causal_user_relative_panel(raw_pack["raw"], dates=raw_pack["calendar_dates"])
    ur_scaled = scaler.transform(ur_raw)
    x = r61_gather_windows(
        scaled_panel=ur_scaled,
        user_index=raw_pack["user_idx"],
        start_index=raw_pack["start_idx"],
        sequence_length=SEQUENCE_LENGTH_LOCKED,
    )
    store = UnlabeledAlignmentStore(
        X=np.asarray(x, dtype=np.float32),
        user=np.asarray(raw_pack["user_ids_windows"]).astype(str),
        sequence_id=np.asarray(raw_pack["sequence_ids"]).astype(str),
    )
    assert_no_alignment_labels(store)
    return store


def r61_raw_from_editor024_scaled_if_present(scaled: np.ndarray) -> np.ndarray:
    """Optional inverse of the frozen original scaler. Unused by the unlabeled path."""
    orig = load_r52_train_scaler()
    return inverse_scale(np.asarray(scaled), orig["mean"], orig["scale"])


def transform_only_original(raw: np.ndarray) -> np.ndarray:
    orig = load_r52_train_scaler()
    return transform_only(raw, orig)
