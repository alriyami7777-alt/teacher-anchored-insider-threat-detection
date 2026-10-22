"""Cascade efficiency. Same GPU/batch/warm-up/timed-batch protocol as EDITOR-014."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch

from editor013_odst_value.models import editor013_forward

from .constants import (
    LATENCY_BATCH_SIZE,
    LATENCY_ROUNDS,
    LATENCY_TIMED_BATCHES,
    LATENCY_WARMUP_BATCHES,
    SCREENING_SEED,
)
from .models import editor016_forward
from .safety import Editor016Blocked
from .train import load_l1_pair, load_trained_specialist


def _latency_round(fn, x: torch.Tensor, device: torch.device) -> list[float]:
    n_batches = max(LATENCY_WARMUP_BATCHES + LATENCY_TIMED_BATCHES, 1)
    times: list[float] = []
    for i in range(n_batches):
        if device.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        fn(x)
        if device.type == "cuda":
            torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        if i >= LATENCY_WARMUP_BATCHES:
            times.append(dt)
    return times


def _summarise(fn, x: torch.Tensor, device: torch.device) -> dict[str, Any]:
    rounds = []
    for r in range(LATENCY_ROUNDS):
        times = _latency_round(fn, x, device)
        rounds.append(
            {
                "round": r + 1,
                "n_timed": len(times),
                "median_s": float(np.median(times)),
                "iqr_s": float(np.subtract(*np.percentile(times, [75, 25]))),
                "mean_s": float(np.mean(times)),
            }
        )
    medians = [row["median_s"] for row in rounds]
    median = float(np.median(medians))
    return {
        "rounds": rounds,
        "median_latency_s": median,
        "iqr_latency_s": float(np.median([row["iqr_s"] for row in rounds])),
        "throughput_sequences_per_s": float(LATENCY_BATCH_SIZE / max(median, 1e-12)),
        "warmup_batches": LATENCY_WARMUP_BATCHES,
        "timed_batches": LATENCY_TIMED_BATCHES,
        "independent_rounds": LATENCY_ROUNDS,
        "batch_size": LATENCY_BATCH_SIZE,
        "cuda_synchronize": True,
        "validation_tensor": True,
        "descriptive_only": True,
    }


def measure_cascade_efficiency(
    device: torch.device,
    val_x: np.ndarray,
    *,
    specialist_ckpt: str | None,
    head: str,
    coverage: float,
    gate: np.ndarray | None,
) -> dict[str, Any]:
    if device.type != "cuda":
        raise Editor016Blocked("EDITOR-016 latency benchmark requires the same GPU as EDITOR-014")
    x = torch.from_numpy(np.asarray(val_x[:LATENCY_BATCH_SIZE], dtype=np.float32)).to(device)
    l1_student, l1_mods, _ = load_l1_pair(SCREENING_SEED, device)

    def l1_fn(xb):
        return editor013_forward(l1_student, xb, l1_mods)

    with torch.no_grad():
        l1_lat = _summarise(l1_fn, x, device)

    out: dict[str, Any] = {
        "L1": l1_lat,
        "specialist_coverage": float(coverage),
        "protocol": "EDITOR-014 identical GPU/batch/warm-up/timed-batch/synchronisation",
    }
    if specialist_ckpt is None:
        out["specialist"] = None
        out["cascade"] = None
        out["expected_cascade_latency_s"] = l1_lat["median_latency_s"]
        return out

    student, modules = load_trained_specialist(specialist_ckpt, device, head=head)
    student.eval()
    modules.eval()
    g = torch.ones(x.size(0), device=device)
    if gate is not None:
        g = torch.from_numpy(np.asarray(gate[: LATENCY_BATCH_SIZE], dtype=np.float32)).to(device)

    def spec_fn(xb):
        return editor016_forward(student, xb, modules, gate=g, use_source_l1=False)

    def cascade_fn(xb):
        l1_out = editor013_forward(l1_student, xb, l1_mods)
        routed = g.reshape(-1) >= 0.5
        if bool(routed.any()):
            return editor016_forward(student, xb, modules, gate=g, use_source_l1=False)
        return l1_out

    with torch.no_grad():
        spec_lat = _summarise(spec_fn, x, device)
        casc_lat = _summarise(cascade_fn, x, device)
    incremental = max(spec_lat["median_latency_s"] - l1_lat["median_latency_s"], 0.0)
    expected = l1_lat["median_latency_s"] + float(coverage) * incremental
    out.update(
        {
            "specialist": spec_lat,
            "cascade": casc_lat,
            "specialist_incremental_latency_s": incremental,
            "expected_cascade_latency_s": expected,
            "implemented_cascade_latency_s": casc_lat["median_latency_s"],
            "implemented_cascade_throughput": casc_lat["throughput_sequences_per_s"],
        }
    )
    return out
