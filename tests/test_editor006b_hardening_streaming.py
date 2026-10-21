from __future__ import annotations

from pathlib import Path

import numpy as np

from editor006b_harness.input_bundle import DenseDailyWindowProvider, build_synthetic_bundle
from editor006b_harness.model_loaders import import_aggregate_common13_windows
from editor006b_harness.safety import T_WINDOW, N_FEATURES
from editor006b_harness.scoring import stream_scores_from_provider


def _large_memmap_bundle(tmp_path: Path, *, n_users: int = 8, n_days: int = 60):
    syn = build_synthetic_bundle(n_users=n_users, n_days=n_days)
    dense_path = tmp_path / "scaled_dense_daily.dat"
    src = syn["bundle"].scaled_dense_daily
    mm = np.memmap(dense_path, dtype=np.float32, mode="w+", shape=src.shape)
    mm[:] = src
    mm.flush()
    loaded = np.memmap(dense_path, dtype=np.float32, mode="r", shape=src.shape)
    return syn, loaded


def _sigmoid_first(batch: np.ndarray) -> np.ndarray:
    z = batch[:, 0, 0].astype(np.float64)
    return 1.0 / (1.0 + np.exp(-z))


def test_h05_h07_batchwise_provider_no_full_tensor_order_deterministic(tmp_path: Path):
    syn, dense = _large_memmap_bundle(tmp_path)
    n = syn["n_sequences"]
    batch_size = 16
    assert n > batch_size
    provider = DenseDailyWindowProvider(
        dense, syn["user_index"], syn["start_index"], batch_size=batch_size
    )
    s1 = stream_scores_from_provider(
        provider=provider, score_fn=_sigmoid_first, expected_n=n
    )
    provider.assert_never_full_sequence_tensor()
    assert provider.n_batches_yielded >= 2
    assert all(shape[0] <= batch_size for shape in provider.batch_shapes)
    assert all(shape != (n, T_WINDOW, N_FEATURES) for shape in provider.batch_shapes)

    provider2 = DenseDailyWindowProvider(
        dense, syn["user_index"], syn["start_index"], batch_size=batch_size
    )
    s2 = stream_scores_from_provider(
        provider=provider2, score_fn=_sigmoid_first, expected_n=n
    )
    assert np.array_equal(s1, s2)
    assert s1.shape == (n,)
    i0, imid, ilast = 0, n // 2, n - 1
    for i in (i0, imid, ilast):
        u = int(syn["user_index"][i])
        s = int(syn["start_index"][i])
        want = float(1.0 / (1.0 + np.exp(-float(dense[u, s, 0]))))
        assert abs(float(s1[i]) - want) < 1e-12


def test_h06_rf_aggregation_bounded_to_batch(tmp_path: Path):
    syn, dense = _large_memmap_bundle(tmp_path, n_users=6, n_days=50)
    n = syn["n_sequences"]
    batch_size = 8
    assert n > batch_size
    seen: list[int] = []
    aggregate_fn = import_aggregate_common13_windows()

    def tracked(batch: np.ndarray) -> np.ndarray:
        seen.append(int(batch.shape[0]))
        assert batch.shape[0] <= batch_size
        assert batch.shape != (n, T_WINDOW, N_FEATURES)
        feat, _names = aggregate_fn(batch)
        assert feat.shape == (batch.shape[0], 40)
        z = feat[:, 0].astype(np.float64)
        return 1.0 / (1.0 + np.exp(-z))

    provider = DenseDailyWindowProvider(
        dense, syn["user_index"], syn["start_index"], batch_size=batch_size
    )
    scores = stream_scores_from_provider(
        provider=provider, score_fn=tracked, expected_n=n
    )
    assert scores.shape == (n,)
    assert seen
    assert max(seen) <= batch_size
    assert all(v <= batch_size for v in seen)
    provider.assert_never_full_sequence_tensor()
