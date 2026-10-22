"""Per-user chronological inner split of r5.2 TRAIN. No official validation. No TEST."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np

from .constants import INNER_TRAIN_FRACTION, SEQUENCE_LENGTH
from .data import SequenceBundle
from .safety import refuse_test_loader_construction


def _parse_day(value: str) -> datetime:
    return datetime.strptime(str(value)[:10], "%Y-%m-%d")


def _window_days(start: str, end: str) -> list[str]:
    a = _parse_day(start)
    b = _parse_day(end)
    if (b - a).days + 1 != SEQUENCE_LENGTH:
        # Still enumerate inclusive range; length mismatch is recorded by caller.
        pass
    out: list[str] = []
    cur = a
    while cur <= b:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def inner_split_masks(bundle: SequenceBundle) -> dict[str, Any]:
    """Build INNER_TRAIN / INNER_SELECT masks from TRAIN calendar days only."""
    refuse_test_loader_construction(partition=bundle.name)
    if bundle.name not in {"train"}:
        raise RuntimeError("Inner split may be constructed only from r5.2 TRAIN")

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
                "inner_train_day_min": ordered[0] if ordered else "",
                "inner_select_day_max": ordered[-1] if ordered else "",
                "cut_day_first_select": sorted(select_days)[0] if select_days else "",
            }
        )

    overlap = int(np.logical_and(train_mask, select_mask).sum())
    if overlap != 0:
        raise RuntimeError(f"INNER_TRAIN ∩ INNER_SELECT is not empty: {overlap} sequences")
    if int((train_mask | select_mask | dropped_mask).sum()) != n:
        raise RuntimeError("Inner split failed to assign every TRAIN sequence")
    n_inner_train = int(train_mask.sum())
    n_inner_select = int(select_mask.sum())
    if n_inner_select < 1 or n_inner_train < 1:
        raise RuntimeError("Inner split produced an empty partition")

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
    }


def assert_no_boundary_crossing(bundle: SequenceBundle, train_mask: np.ndarray, select_mask: np.ndarray) -> None:
    users = np.unique(bundle.user[np.logical_or(train_mask, select_mask)])
    for user in users:
        tr = np.flatnonzero((bundle.user == user) & train_mask)
        se = np.flatnonzero((bundle.user == user) & select_mask)
        if len(tr) == 0 or len(se) == 0:
            continue
        train_days: set[str] = set()
        select_days: set[str] = set()
        for i in tr:
            train_days.update(_window_days(bundle.start_date[i], bundle.end_date[i]))
        for i in se:
            select_days.update(_window_days(bundle.start_date[i], bundle.end_date[i]))
        if train_days & select_days:
            raise RuntimeError(f"Boundary-crossing calendar days for user={user}")
        last_tr = max(train_days)
        first_se = min(select_days)
        if last_tr >= first_se:
            raise RuntimeError(f"Inner split chronology violated for user={user}: {last_tr} >= {first_se}")
