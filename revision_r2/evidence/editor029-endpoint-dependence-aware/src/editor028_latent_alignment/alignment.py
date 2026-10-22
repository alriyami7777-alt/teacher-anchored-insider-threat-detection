"""Unlabeled r6.1 alignment store and matched target sampling. Labels are inaccessible."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import torch
from torch.utils.data import DataLoader

from editor012_rescue.data import make_xy_loader
from editor012_rescue.constants import BATCH_SIZE

from .constants import ALL_CANDIDATES, CANDIDATE_LAMBDAS, TARGET_SAMPLER_SEED_OFFSET
from .safety import Editor028Blocked


FORBIDDEN_ALIGNMENT_KEYS = (
    "y",
    "label",
    "labels",
    "malicious",
    "malicious_flag",
    "answer",
    "scenario",
    "insider",
)


@dataclass(frozen=True)
class UnlabeledAlignmentStore:
    """r6.1 alignment population. Contains only X and provenance identifiers."""

    X: np.ndarray
    user: np.ndarray
    sequence_id: np.ndarray

    def __post_init__(self) -> None:
        x = np.asarray(self.X)
        if x.ndim != 3:
            raise Editor028Blocked(f"alignment X must be (N, T, F), got {x.shape}")
        n = int(x.shape[0])
        if len(self.user) != n or len(self.sequence_id) != n:
            raise Editor028Blocked("alignment identifier length mismatch")

    def __getattribute__(self, name: str):
        if name in FORBIDDEN_ALIGNMENT_KEYS:
            raise AttributeError("r6.1 labels are inaccessible on the unlabeled alignment store")
        return super().__getattribute__(name)

    def keys(self) -> tuple[str, ...]:
        return ("X", "user", "sequence_id")

    def as_dict(self) -> dict[str, np.ndarray]:
        return {"X": self.X, "user": self.user, "sequence_id": self.sequence_id}

    def __len__(self) -> int:
        return int(np.asarray(self.X).shape[0])


def assert_no_alignment_labels(store: UnlabeledAlignmentStore) -> None:
    for key in FORBIDDEN_ALIGNMENT_KEYS:
        if key in store.__dict__:
            raise Editor028Blocked(f"alignment store contains forbidden key {key}")
        try:
            getattr(store, key)
        except AttributeError:
            continue
        raise Editor028Blocked(f"alignment store exposed forbidden attribute {key}")


def target_stream_seed(source_seed: int) -> int:
    return int(source_seed) + int(TARGET_SAMPLER_SEED_OFFSET)


def candidate_lambda(name: str) -> float:
    if name not in CANDIDATE_LAMBDAS:
        raise Editor028Blocked("candidate set cannot expand")
    return float(CANDIDATE_LAMBDAS[name])


def register_candidate(name: str, lambda_coral: float) -> None:
    raise Editor028Blocked("candidate set cannot expand")


def source_index_order(n: int, seed: int, batch_size: int = BATCH_SIZE) -> list[np.ndarray]:
    """Reproduce make_xy_loader shuffle so candidates share source batch order."""
    g = torch.Generator()
    g.manual_seed(int(seed))
    perm = torch.randperm(int(n), generator=g).numpy()
    batches = []
    for start in range(0, int(n), int(batch_size)):
        batches.append(perm[start : start + int(batch_size)])
    return batches


def target_epoch_seed(source_seed: int, epoch: int) -> int:
    return target_stream_seed(source_seed) + int(epoch) * 100_003


def target_index_stream(
    n_target: int,
    source_batch_sizes: list[int],
    *,
    seed: int,
    epoch: int = 1,
) -> list[np.ndarray]:
    """Outcome-independent uniform shuffle. No labels enter the sampler."""
    if n_target < 1:
        raise Editor028Blocked("empty r6.1 alignment population")
    rng = np.random.default_rng(target_epoch_seed(seed, epoch))
    pool = rng.permutation(int(n_target))
    cursor = 0
    out: list[np.ndarray] = []
    for bs in source_batch_sizes:
        need = int(bs)
        if cursor + need > len(pool):
            leftover = pool[cursor:]
            pool = np.concatenate([leftover, rng.permutation(int(n_target))])
            cursor = 0
        out.append(np.asarray(pool[cursor : cursor + need], dtype=np.int64))
        cursor += need
    return out


def make_source_loader(
    x: np.ndarray,
    y: np.ndarray,
    ensemble: np.ndarray,
    *,
    seed: int,
    shuffle: bool,
) -> DataLoader:
    return make_xy_loader(x, y, seed=seed, shuffle=shuffle, extras=[ensemble])


def iter_matched_batches(
    source_loader: DataLoader,
    target: UnlabeledAlignmentStore,
    *,
    seed: int,
    epoch: int = 1,
) -> Iterator[tuple[tuple, np.ndarray, np.ndarray]]:
    """Yield (source_batch, target_X, target_idx). Target labels do not exist."""
    assert_no_alignment_labels(target)
    x_t = np.asarray(target.X)
    n_t = int(x_t.shape[0])
    rng = np.random.default_rng(target_epoch_seed(seed, epoch))
    pool = rng.permutation(n_t)
    cursor = 0
    for batch in source_loader:
        bs = int(batch[0].shape[0])
        if cursor + bs > len(pool):
            leftover = pool[cursor:]
            pool = np.concatenate([leftover, rng.permutation(n_t)])
            cursor = 0
        idx = np.asarray(pool[cursor : cursor + bs], dtype=np.int64)
        cursor += bs
        yield batch, x_t[idx], idx


def frozen_candidate_names() -> tuple[str, ...]:
    return ALL_CANDIDATES
