"""Per-user chronological inner split of r5.2 TRAIN. Official VALIDATION is never used."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np

from .constants import INNER_TRAIN_FRACTION, SEQUENCE_LENGTH
from .data import SequenceBundle
from .safety import Editor012ProtocolError, assert_split_allowed


def _parse_day(value: str) -> datetime:
    return datetime.strptime(str(value)[:10], "%Y-%m-%d")


def _window_days(start: str, end: str) -> list[str]:
    a = _parse_day(start)
    b = _parse_day(end)
    out: list[str] = []
    cur = a
    while cur <= b:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    if SEQUENCE_LENGTH and len(out) != SEQUENCE_LENGTH:
        pass
    return out


def inner_split_masks(bundle: SequenceBundle) -> dict[str, Any]:
    """Build INNER_TRAIN / INNER_SELECT masks from TRAIN calendar days only."""
    assert_split_allowed(bundle.name)
    if bundle.name not in {"train"}:
        raise Editor012ProtocolError("Inner split may be constructed only from r5.2 TRAIN")

    n = len(bundle.y)
    train_mask = np.zeros(n, dtype=bool)
    select_mask = np.zeros(n, dtype=bool)
    dropped_mask = np.zeros(n, dtype=bool)
    per_user: list[dict[str, Any]] = []

    users = np.unique(bundle.user)
    for user in users:
        idx = np.flatnonzero(bundle.user == user)
        day_set: set[str] = set()
        window_days: list[list[str]] = []
        for i in idx:
            days = _window_days(bundle.start_date[i], bundle.end_date[i])
            window_days.append(days)
            day_set.update(days)
        ordered = sorted(day_set)
        n_days = len(ordered)
        n_inner = int(np.floor(INNER_TRAIN_FRACTION * n_days)) if n_days else 0
        if n_days <= 1:
            inner_days = set(ordered)
            select_days: set[str] = set()
        else:
            n_inner = min(max(n_inner, 1), n_days - 1)
            inner_days = set(ordered[:n_inner])
            select_days = set(ordered[n_inner:])
        n_tr = n_sel = n_drop = 0
        for loc, i in enumerate(idx):
            days = set(window_days[loc])
            in_tr = days.issubset(inner_days) and len(days) > 0
            in_sel = days.issubset(select_days) and len(days) > 0
            if in_tr and not in_sel:
                train_mask[i] = True
                n_tr += 1
            elif in_sel and not in_tr:
                select_mask[i] = True
                n_sel += 1
            else:
                dropped_mask[i] = True
                n_drop += 1
        per_user.append(
            {
                "user": str(user),
                "n_calendar_days": n_days,
                "n_inner_train_days": len(inner_days),
                "n_inner_select_days": len(select_days),
                "n_sequences": int(len(idx)),
                "n_inner_train_sequences": n_tr,
                "n_inner_select_sequences": n_sel,
                "n_dropped_boundary_sequences": n_drop,
            }
        )

    overlap = int(np.logical_and(train_mask, select_mask).sum())
    if overlap != 0:
        raise Editor012ProtocolError(f"INNER_TRAIN ∩ INNER_SELECT is not empty: {overlap}")
    if int((train_mask | select_mask | dropped_mask).sum()) != n:
        raise Editor012ProtocolError("Inner split failed to assign every TRAIN sequence")
    if int(train_mask.sum()) < 1 or int(select_mask.sum()) < 1:
        raise Editor012ProtocolError("Inner split produced an empty partition")

    return {
        "train_mask": train_mask,
        "select_mask": select_mask,
        "dropped_mask": dropped_mask,
        "per_user": per_user,
        "n_inner_train": int(train_mask.sum()),
        "n_inner_select": int(select_mask.sum()),
        "n_dropped": int(dropped_mask.sum()),
        "n_inner_train_pos": int(bundle.y[train_mask].sum()),
        "n_inner_select_pos": int(bundle.y[select_mask].sum()),
        "disjoint": overlap == 0,
        "official_validation_used": False,
    }
