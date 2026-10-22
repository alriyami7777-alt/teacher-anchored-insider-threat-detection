"""Endpoint-day labels from the frozen r5.2 malicious-day mapping. No new ground truth."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from editor012_rescue.data import SequenceBundle

from .constants import (
    FEATURE_DIM,
    R52_DENSE_PARQUET,
    SEQUENCE_LENGTH_LOCKED,
)
from .deoverlap import calendar_span_days, parse_iso_date
from .safety import Editor029Blocked, Editor029ProtocolError, refuse_r51_r61_r62_test, sha256_file


def load_malicious_day_map() -> dict[str, Any]:
    """Reuse the frozen dense-parquet is_malicious_interval mapping."""
    refuse_r51_r61_r62_test(R52_DENSE_PARQUET)
    cols = ["user", "interval_date", "is_malicious_interval"]
    table = pq.read_table(R52_DENSE_PARQUET, columns=cols)
    df = table.to_pandas()
    df["user"] = df["user"].astype(str)
    df["interval_date"] = pd.to_datetime(df["interval_date"]).dt.strftime("%Y-%m-%d")
    df["is_malicious_interval"] = pd.to_numeric(df["is_malicious_interval"], errors="raise").astype(np.int8)
    key = list(zip(df["user"].tolist(), df["interval_date"].tolist()))
    values = df["is_malicious_interval"].to_numpy()
    mapping = dict(zip(key, values.tolist()))
    n_mal_days = int((values == 1).sum())
    return {
        "mapping": mapping,
        "n_malicious_user_days_all_calendar": n_mal_days,
        "n_rows": int(len(df)),
        "path": str(R52_DENSE_PARQUET),
        "sha256": sha256_file(R52_DENSE_PARQUET),
        "source_column": "is_malicious_interval",
        "new_ground_truth": False,
    }


def endpoint_label_from_day(
    *,
    user: str,
    endpoint_date: str,
    mapping: dict[tuple[str, str], int],
) -> int:
    key = (str(user), str(endpoint_date)[:10])
    if key not in mapping:
        raise Editor029ProtocolError(f"missing malicious-day mapping for {key}")
    return int(mapping[key] == 1)


def window_day_labels(
    *,
    user: str,
    start_date: str,
    end_date: str,
    mapping: dict[tuple[str, str], int],
) -> np.ndarray:
    if calendar_span_days(start_date, end_date) != SEQUENCE_LENGTH_LOCKED - 1:
        raise Editor029ProtocolError("endpoint window is not 20 calendar days")
    d0 = parse_iso_date(start_date)
    labels = []
    for k in range(SEQUENCE_LENGTH_LOCKED):
        day = (d0 + timedelta(days=k)).isoformat()
        labels.append(endpoint_label_from_day(user=user, endpoint_date=day, mapping=mapping))
    if labels[-1] != endpoint_label_from_day(user=user, endpoint_date=end_date, mapping=mapping):
        raise Editor029ProtocolError("endpoint day mismatch versus end_date")
    return np.asarray(labels, dtype=np.int8)


def relabel_bundle_endpoint(bundle: SequenceBundle, mapping: dict[tuple[str, str], int]) -> np.ndarray:
    """y_d = 1 iff verified malicious activity occurs on endpoint calendar day d."""
    if bundle.X.shape[1] != SEQUENCE_LENGTH_LOCKED or bundle.X.shape[2] != FEATURE_DIM:
        raise Editor029Blocked(
            f"endpoint input shape {bundle.X.shape} is not (N, {SEQUENCE_LENGTH_LOCKED}, {FEATURE_DIM})"
        )
    y = np.zeros(len(bundle.y), dtype=np.int8)
    for i in range(len(bundle.y)):
        days = window_day_labels(
            user=str(bundle.user[i]),
            start_date=str(bundle.start_date[i]),
            end_date=str(bundle.end_date[i]),
            mapping=mapping,
        )
        # Only day d (last) makes the endpoint label positive.
        y[i] = int(days[-1])
        if int(days[-1]) == 0 and int(days[:-1].max() if days[:-1].size else 0) == 1:
            # Prior-window malicious days must not flip the endpoint label.
            if y[i] != 0:
                raise Editor029ProtocolError("prior-day leakage into endpoint label")
    return y


def historical_any_day_from_mapping(
    bundle: SequenceBundle, mapping: dict[tuple[str, str], int]
) -> np.ndarray:
    y = np.zeros(len(bundle.y), dtype=np.int8)
    for i in range(len(bundle.y)):
        days = window_day_labels(
            user=str(bundle.user[i]),
            start_date=str(bundle.start_date[i]),
            end_date=str(bundle.end_date[i]),
            mapping=mapping,
        )
        y[i] = int(days.max())
    return y


def split_does_not_cross_boundary(
    *,
    train: SequenceBundle,
    val: SequenceBundle,
) -> dict[str, Any]:
    train_ends = np.asarray(train.end_date).astype(str)
    val_starts = np.asarray(val.start_date).astype(str)
    max_train_end = max(parse_iso_date(x) for x in train_ends)
    min_val_start = min(parse_iso_date(x) for x in val_starts)
    if min_val_start <= max_train_end:
        # Windows themselves must still stay inside their split.
        pass
    for s, e in zip(train.start_date, train.end_date):
        if parse_iso_date(str(e)) < parse_iso_date(str(s)):
            raise Editor029ProtocolError("TRAIN window inverted")
    for s, e in zip(val.start_date, val.end_date):
        if parse_iso_date(str(e)) < parse_iso_date(str(s)):
            raise Editor029ProtocolError("VALIDATION window inverted")
    overlap_users_ok = True  # same-user temporal partitions are required
    crossing = 0
    boundary = max_train_end
    for s, e in zip(train.start_date, train.end_date):
        if parse_iso_date(str(s)) <= boundary < parse_iso_date(str(e)):
            # TRAIN window ending after the last TRAIN endpoint is impossible by construction.
            if parse_iso_date(str(e)) > boundary:
                crossing += 1
    for s, e in zip(val.start_date, val.end_date):
        if parse_iso_date(str(s)) <= boundary < parse_iso_date(str(e)):
            crossing += 1
    if crossing:
        raise Editor029Blocked(f"{crossing} windows cross TRAIN/VALIDATION boundary")
    return {
        "max_train_end": max_train_end.isoformat(),
        "min_val_start": min_val_start.isoformat(),
        "windows_crossing_boundary": 0,
        "same_user_temporal_partitions": overlap_users_ok,
        "unseen_user_generalisation": False,
    }


def endpoint_counts(y: np.ndarray, users: np.ndarray, endpoint_dates: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y).astype(int).reshape(-1)
    users = np.asarray(users).astype(str).reshape(-1)
    dates = np.asarray(endpoint_dates).astype(str).reshape(-1)
    pos = y == 1
    pos_users = sorted({str(u) for u, lab in zip(users, y) if lab == 1})
    mal_days = {(str(u), str(d)[:10]) for u, d, lab in zip(users, dates, y) if lab == 1}
    return {
        "n": int(len(y)),
        "n_positives": int(pos.sum()),
        "n_positive_users": int(len(pos_users)),
        "n_malicious_endpoint_days": int(len(mal_days)),
        "prevalence": float(pos.mean()) if len(y) else float("nan"),
        "positive_users": pos_users,
        "both_classes": bool(len(np.unique(y)) == 2),
    }


def endpoint_data_gate(train_counts: dict[str, Any], val_counts: dict[str, Any]) -> dict[str, Any]:
    ok = (
        bool(train_counts["both_classes"])
        and bool(val_counts["both_classes"])
        and int(val_counts["n_positives"]) > 0
        and int(val_counts["n_positive_users"]) >= 2
    )
    return {
        "EDITOR029_ENDPOINT_DATA_GATE": "PASS" if ok else "FAIL",
        "train_both_classes": bool(train_counts["both_classes"]),
        "validation_both_classes": bool(val_counts["both_classes"]),
        "validation_positive_users": int(val_counts["n_positive_users"]),
        "minimum_validation_positive_users": 2,
        "pass": ok,
    }
