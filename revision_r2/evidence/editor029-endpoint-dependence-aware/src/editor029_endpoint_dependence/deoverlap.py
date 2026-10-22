"""Score-blind, label-blind de-overlap masks. Offsets are sensitivity views, not experiments."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np

from .constants import DEOVERLAP_STEP, N_DEOVERLAP_OFFSETS, SEQUENCE_LENGTH_LOCKED
from .safety import Editor029Blocked, Editor029ProtocolError


ALLOWED_MASK_KEYS = frozenset({"user", "start_date", "end_date", "sequence_id"})
FORBIDDEN_MASK_KEYS = frozenset(
    {
        "y",
        "label",
        "score",
        "logit",
        "probability",
        "pred",
        "prediction",
        "malicious",
        "scenario",
        "insider",
    }
)


def parse_iso_date(value: str) -> date:
    text = str(value).strip()[:10]
    return datetime.strptime(text, "%Y-%m-%d").date()


def calendar_span_days(start: str, end: str) -> int:
    return (parse_iso_date(end) - parse_iso_date(start)).days


def assert_window_calendar_span(start_dates: np.ndarray, end_dates: np.ndarray) -> None:
    starts = np.asarray(start_dates).astype(str).reshape(-1)
    ends = np.asarray(end_dates).astype(str).reshape(-1)
    if starts.size != ends.size:
        raise Editor029ProtocolError("start/end date length mismatch")
    for s, e in zip(starts, ends):
        if calendar_span_days(s, e) != SEQUENCE_LENGTH_LOCKED - 1:
            raise Editor029ProtocolError(
                f"window calendar span {(parse_iso_date(e) - parse_iso_date(s)).days} "
                f"!= {SEQUENCE_LENGTH_LOCKED - 1} for {s}..{e}"
            )


def _sort_user_positions(
    users: np.ndarray,
    start_dates: np.ndarray,
    end_dates: np.ndarray,
) -> dict[str, np.ndarray]:
    users = np.asarray(users).astype(str).reshape(-1)
    starts = np.asarray(start_dates).astype(str).reshape(-1)
    ends = np.asarray(end_dates).astype(str).reshape(-1)
    grouped: dict[str, np.ndarray] = {}
    for user in np.unique(users):
        sel = np.flatnonzero(users == user)
        # Chronological: start date, then endpoint date, then original index.
        start_key = starts[sel]
        end_key = ends[sel]
        ranked = sel[np.lexsort((sel, end_key, start_key))]
        grouped[str(user)] = ranked.astype(np.int64)
    return grouped


def windows_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    a0 = parse_iso_date(start_a)
    a1 = parse_iso_date(end_a)
    b0 = parse_iso_date(start_b)
    b1 = parse_iso_date(end_b)
    return not (a1 < b0 or b1 < a0)


def assert_selected_non_overlapping(
    selected: np.ndarray,
    start_dates: np.ndarray,
    end_dates: np.ndarray,
) -> None:
    starts = np.asarray(start_dates).astype(str).reshape(-1)
    ends = np.asarray(end_dates).astype(str).reshape(-1)
    idx = np.asarray(selected, dtype=np.int64).reshape(-1)
    for i in range(len(idx)):
        for j in range(i + 1, len(idx)):
            if windows_overlap(starts[idx[i]], ends[idx[i]], starts[idx[j]], ends[idx[j]]):
                raise Editor029ProtocolError(
                    f"overlapping selected windows {idx[i]} and {idx[j]}"
                )


def construct_deoverlap_mask(
    *,
    user: np.ndarray,
    start_date: np.ndarray,
    end_date: np.ndarray,
    offset: int,
    sequence_id: np.ndarray | None = None,
) -> np.ndarray:
    """Deterministic per-user positional de-overlap. Labels and scores are not arguments."""
    if offset < 0 or offset >= N_DEOVERLAP_OFFSETS:
        raise Editor029ProtocolError(f"offset {offset} not in 0..{N_DEOVERLAP_OFFSETS - 1}")
    users = np.asarray(user).astype(str).reshape(-1)
    starts = np.asarray(start_date).astype(str).reshape(-1)
    ends = np.asarray(end_date).astype(str).reshape(-1)
    if sequence_id is not None:
        seq = np.asarray(sequence_id).astype(str).reshape(-1)
        if seq.size != users.size:
            raise Editor029ProtocolError("sequence_id length mismatch")
    assert_window_calendar_span(starts, ends)
    n = users.size
    mask = np.zeros(n, dtype=bool)
    grouped = _sort_user_positions(users, starts, ends)
    for _user, ranked in grouped.items():
        selected = ranked[int(offset) :: DEOVERLAP_STEP]
        mask[selected] = True
        assert_selected_non_overlapping(selected, starts, ends)
    return mask


def construct_all_offset_masks(
    *,
    user: np.ndarray,
    start_date: np.ndarray,
    end_date: np.ndarray,
    sequence_id: np.ndarray | None = None,
) -> dict[int, np.ndarray]:
    return {
        k: construct_deoverlap_mask(
            user=user,
            start_date=start_date,
            end_date=end_date,
            offset=k,
            sequence_id=sequence_id,
        )
        for k in range(N_DEOVERLAP_OFFSETS)
    }


def mask_kwargs_guard(kwargs: dict[str, Any]) -> None:
    keys = {str(k).lower() for k in kwargs}
    bad = keys & {k.lower() for k in FORBIDDEN_MASK_KEYS}
    if bad:
        raise Editor029Blocked(f"de-overlap mask must not depend on {sorted(bad)}")
    extra = keys - {k.lower() for k in ALLOWED_MASK_KEYS} - {"offset"}
    if extra:
        raise Editor029ProtocolError(f"unexpected de-overlap kwargs {sorted(extra)}")


def offsets_are_sensitivity_views() -> dict[str, Any]:
    """Offsets must not be pooled as independent observations."""
    return {
        "n_offsets": N_DEOVERLAP_OFFSETS,
        "pooled_as_independent_observations": False,
        "p_value_from_offsets_forbidden": True,
        "role": "sensitivity_views",
        "primary_offset": 0,
        "selection_rule": "within each user, chronological positions k, k+20, k+40, ...",
        "mask_depends_on": ["user identity", "chronological sequence position", "window dates"],
        "mask_forbidden": ["label", "model score", "prediction", "malicious scenario"],
    }


def quantile(values: np.ndarray, q: float) -> float:
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(np.quantile(arr, q))
