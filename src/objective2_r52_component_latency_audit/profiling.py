"""Component timing helpers (inference-only; no architecture mutation)."""

from __future__ import annotations


import os
import time
from typing import Any, Callable

import numpy as np
import torch
import torch.nn as nn

from objective2_teacher_anchored_odst.models import build_model, live_odst_forward, load_checkpoint_into

from .constants import ARCHITECTURE_BASE, MODELS, PARITY_ATOL, TIMED, WARMUP
from .safety import StudyBlockedError, sha256_file


def _sync(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def _stats(times: list[float], *, batch_size: int) -> dict[str, float]:
    a = np.asarray(times, dtype=np.float64)
    med = float(np.median(a))
    return {
        "median_sec": med,
        "mean_sec": float(a.mean()),
        "std_sec": float(a.std(ddof=0)),
        "iqr_sec": float(np.percentile(a, 75) - np.percentile(a, 25)),
        "p5_sec": float(np.percentile(a, 5)),
        "p95_sec": float(np.percentile(a, 95)),
        "examples_per_sec": float(batch_size / max(med, 1e-12)),
        "n_timed": int(len(a)),
    }


def load_student(repo, key: str, device: torch.device) -> tuple[nn.Module, dict[str, Any]]:
    meta = MODELS[key]
    ckpt = repo / meta["ckpt_rel"]
    if not ckpt.exists():
        # fallback to recorded_results mirror inside 8tree package
        alt = repo / "read_only_evidence" / "r52_odst_8tree_ablation_v1"
        # try scripts path via sibling
        from pathlib import Path

        alt2_value = os.environ.get("CERT_R52_8TREE_CHECKPOINT")
        if key == "8tree" and alt2_value:
            alt2 = Path(alt2_value).expanduser()
            if alt2.exists():
                ckpt = alt2
    sha = sha256_file(ckpt)
    if sha != meta["expected_sha256"]:
        raise StudyBlockedError(
            "objective2_component_latency_audit_blocked_provenance",
            f"hash mismatch {key}: {sha}",
        )
    arch = dict(ARCHITECTURE_BASE)
    arch["node_n_trees"] = meta["node_n_trees"]
    arch["node_num_layers"] = meta["node_num_layers"]
    model = build_model(**arch)
    load_checkpoint_into(model, ckpt)
    model.eval()
    for p in model.parameters():
        p.requires_grad = False
    model.to(device)
    info = {
        "model_key": key,
        "label": meta["label"],
        "checkpoint": str(ckpt),
        "sha256": sha,
        "M": meta["M"],
        "node_n_trees": meta["node_n_trees"],
        "n_parameters": int(sum(p.numel() for p in model.parameters())),
        "n_odst_head_parameters": int(sum(p.numel() for p in model.node_head.parameters())),
        "teacher_loaded": False,
        "requires_grad_any": bool(any(p.requires_grad for p in model.parameters())),
    }
    return model, info


@torch.inference_mode()
def clean_parity(model: nn.Module, x_cpu: torch.Tensor, device: torch.device) -> dict[str, Any]:
    """Compare full forward vs summed component reconstruction of logit."""
    model.eval()
    xb = x_cpu.to(device, non_blocking=False)
    _sync(device)
    logit_full, extras = model(xb)
    # component path
    hidden, _ = model.lstm(xb)
    hidden = model.dropout(hidden)
    aggregated, attn = model.attention(hidden)
    node_logit, _ = model.node_head(aggregated)
    # for sparsemax_sigmoid_odst final = node_logit
    max_abs = float((logit_full.reshape(-1) - node_logit.reshape(-1)).abs().max().item())
    # also vs live tree mean
    live_logit, _, _ = live_odst_forward(model.node_head, aggregated)
    max_abs_live = float((logit_full.reshape(-1) - live_logit.reshape(-1)).abs().max().item())
    ok = max_abs < PARITY_ATOL and max_abs_live < PARITY_ATOL
    return {
        "max_abs_full_vs_node_logit": max_abs,
        "max_abs_full_vs_live_tree_mean": max_abs_live,
        "parity_ok": ok,
        "attn_sum_mean": float(attn.sum(dim=-1).mean().item()),
    }


def _time_block(fn: Callable[[], Any], device: torch.device, warmup: int, timed: int) -> list[float]:
    for _ in range(warmup):
        fn()
        _sync(device)
    times: list[float] = []
    for _ in range(timed):
        _sync(device)
        t0 = time.perf_counter()
        fn()
        _sync(device)
        times.append(time.perf_counter() - t0)
    return times


@torch.inference_mode()
def profile_components(
    model: nn.Module,
    x_cpu: torch.Tensor,
    device: torch.device,
    *,
    model_key: str,
    warmup: int = WARMUP,
    timed: int = TIMED,
) -> list[dict[str, Any]]:
    """Profile C0–C5 for one fixed batch already on host."""
    model.eval()
    bs = int(x_cpu.shape[0])
    rows: list[dict[str, Any]] = []

    # C0 host->device
    def c0():
        return x_cpu.to(device, non_blocking=False)

    # keep a resident device batch for later components
    xb = x_cpu.to(device)
    _sync(device)

    def c1():
        return model.lstm(xb)[0]

    # need hidden for attention — compute once for setup, then time attention alone
    hidden0, _ = model.lstm(xb)
    hidden0 = model.dropout(hidden0)

    def c2():
        return model.attention(hidden0)

    aggregated0, _ = model.attention(hidden0)

    def c3():
        return model.node_head(aggregated0)

    node_logit0, _ = model.node_head(aggregated0)

    def c4_sigmoid():
        return torch.sigmoid(node_logit0)

    def c4_d2h():
        return node_logit0.detach().cpu()

    def c5_e2e():
        return model(xb)

    # Also time Bi-LSTM+dropout together as C1b (dropout is part of encode path)
    def c1_with_dropout():
        h, _ = model.lstm(xb)
        return model.dropout(h)

    components = [
        ("C0_host_to_device", c0),
        ("C1_bilstm", c1),
        ("C1b_bilstm_dropout", c1_with_dropout),
        ("C2_attention", c2),
        ("C3_odst_head", c3),
        ("C4_sigmoid", c4_sigmoid),
        ("C4_device_to_host", c4_d2h),
        ("C5_full_e2e_device_input", c5_e2e),
    ]

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    for name, fn in components:
        times = _time_block(fn, device, warmup, timed)
        st = _stats(times, batch_size=bs)
        peak_alloc = peak_res = float("nan")
        if device.type == "cuda":
            peak_alloc = float(torch.cuda.max_memory_allocated(device) / (1024**2))
            peak_res = float(torch.cuda.max_memory_reserved(device) / (1024**2))
        rows.append(
            {
                "model_key": model_key,
                "component": name,
                "batch_size": bs,
                "device": str(device),
                "warmup": warmup,
                "timed_iters": timed,
                "peak_allocated_gpu_mb": peak_alloc,
                "peak_reserved_gpu_mb": peak_res,
                **st,
            }
        )

    # C6 overhead estimate: C5 - (C1b + C2 + C3 + C4_sigmoid)
    by = {r["component"]: r["median_sec"] for r in rows}
    summed = by["C1b_bilstm_dropout"] + by["C2_attention"] + by["C3_odst_head"] + by["C4_sigmoid"]
    overhead = by["C5_full_e2e_device_input"] - summed
    rows.append(
        {
            "model_key": model_key,
            "component": "C6_overhead_estimate",
            "batch_size": bs,
            "device": str(device),
            "warmup": warmup,
            "timed_iters": timed,
            "peak_allocated_gpu_mb": float("nan"),
            "peak_reserved_gpu_mb": float("nan"),
            "median_sec": float(overhead),
            "mean_sec": float(overhead),
            "std_sec": float("nan"),
            "iqr_sec": float("nan"),
            "p5_sec": float("nan"),
            "p95_sec": float("nan"),
            "examples_per_sec": float("nan"),
            "n_timed": 0,
            "sum_isolated_components_sec": float(summed),
            "note": "approximate; isolated timings may not sum due to CUDA scheduling",
        }
    )
    return rows


@torch.inference_mode()
def profile_explanation(
    model: nn.Module,
    x_cpu: torch.Tensor,
    device: torch.device,
    *,
    model_key: str,
    M: int,
    warmup: int = WARMUP,
    timed: int = TIMED,
) -> list[dict[str, Any]]:
    model.eval()
    xb = x_cpu.to(device)
    bs = int(xb.shape[0])
    rows = []

    def e1():
        _, enc = model.encode_attention_h(xb)
        return enc["attention_weights"]

    def e2():
        z, _ = model.encode_attention_h(xb)
        logit, choices, leaf = live_odst_forward(model.node_head, z)
        # tree outputs via layer bags (same as live)
        xh = z
        bags = []
        for layer in model.node_head.layers:
            feature_probs = layer.feature_selection_probs()
            selected = torch.einsum("bf,tdf->btd", xh, feature_probs)
            choice = layer.split_choice(selected)
            batch = xh.size(0)
            c = choice.unsqueeze(2).expand(batch, layer.n_trees, layer.n_leaves, layer.depth)
            codes = layer.leaf_codes.view(1, 1, layer.n_leaves, layer.depth)
            log_c = torch.log(c.clamp(1e-8, 1.0 - 1e-8))
            log_1mc = torch.log((1.0 - c).clamp(1e-8, 1.0))
            leaf_probs = torch.exp((codes * log_c + (1.0 - codes) * log_1mc).sum(dim=-1))
            response = torch.einsum("btl,tlu->btu", leaf_probs, layer.leaf_responses)
            bags.append(response.squeeze(-1))
            out = response.reshape(batch, layer.n_trees * layer.tree_dim)
            xh = torch.cat([xh, out], dim=-1)
        trees = torch.cat(bags, dim=1)
        # dominant leaf / path proxy + centred contrib relative to zero ref (timing only)
        dom = leaf.argmax(dim=-1)
        contrib = trees / float(M)
        return logit, choices, leaf, trees, dom, contrib

    def e3():
        _ = e1()
        return e2()

    for name, fn in (("E1_attention_extraction", e1), ("E2_odst_route_leaf_extraction", e2), ("E3_full_explanation_package", e3)):
        times = _time_block(fn, device, warmup, timed)
        st = _stats(times, batch_size=bs)
        rows.append({"model_key": model_key, "component": name, "batch_size": bs, "M": M, **st})
    return rows


@torch.inference_mode()
def run_profiler_summary(
    model: nn.Module,
    x_cpu: torch.Tensor,
    device: torch.device,
    *,
    model_key: str,
    batch_size: int = 32,
) -> list[dict[str, Any]]:
    """Secondary diagnostic only — not used for primary latency numbers."""
    try:
        from torch.profiler import ProfilerActivity, profile
    except Exception:
        return [{"model_key": model_key, "error": "profiler_unavailable"}]

    xb = x_cpu[:batch_size].to(device)
    activities = [ProfilerActivity.CPU]
    if device.type == "cuda":
        activities.append(ProfilerActivity.CUDA)

    rows: list[dict[str, Any]] = []
    with profile(activities=activities, record_shapes=False, profile_memory=False, with_stack=False) as prof:
        for _ in range(20):
            _ = model(xb)
            _sync(device)
    # top events
    key = "cuda_time_total" if device.type == "cuda" else "cpu_time_total"
    events = sorted(prof.key_averages(), key=lambda e: getattr(e, key, 0), reverse=True)
    for i, e in enumerate(events[:25]):
        rows.append(
            {
                "model_key": model_key,
                "rank": i + 1,
                "name": e.key,
                "cpu_time_total_us": float(e.cpu_time_total),
                "cuda_time_total_us": float(getattr(e, "cuda_time_total", 0.0) or 0.0),
                "count": int(e.count),
                "batch_size": batch_size,
                "secondary_diagnostic_only": True,
            }
        )
    return rows
