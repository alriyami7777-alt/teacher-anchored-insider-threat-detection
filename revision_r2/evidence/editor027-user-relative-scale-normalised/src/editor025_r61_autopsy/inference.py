"""Frozen-checkpoint forward inference. No parameter update."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch

from editor012_rescue.metrics import sigmoid
from editor012_rescue.models import student_forward
from editor013_odst_value.models import editor013_forward
from editor017_robustness.models import load_l1, load_odst, parameter_fingerprint
from editor024_r61.cert_parse import gather_windows

from .constants import BATCH_SIZE
from .safety import Editor025Blocked, utc_now


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def load_student(alias: str, seed: int, dev: torch.device) -> dict[str, Any]:
    if alias == "L1":
        student, modules, sha = load_l1(seed, dev)
        fp = parameter_fingerprint(student, modules)
        student.eval()
        modules.eval()
        for p in student.parameters():
            p.requires_grad = False
        for p in modules.parameters():
            p.requires_grad = False
        return {
            "student": student,
            "modules": modules,
            "sha256": sha,
            "fingerprint": fp,
            "family": "linear",
        }
    model, sha = load_odst(alias, seed, dev)
    fp = parameter_fingerprint(model)
    model.eval()
    for p in model.parameters():
        p.requires_grad = False
    return {"model": model, "sha256": sha, "fingerprint": fp, "family": "odst"}


def assert_fingerprint(alias: str, seed: int, loaded: dict[str, Any]) -> None:
    if loaded["family"] == "linear":
        now = parameter_fingerprint(loaded["student"], loaded["modules"])
    else:
        now = parameter_fingerprint(loaded["model"])
    if now != loaded["fingerprint"]:
        raise Editor025Blocked(
            f"EDITOR025_TRAINING_GATE = FAIL: parameter update detected for {alias}/{seed}"
        )


def _unload(loaded: dict[str, Any], dev: torch.device) -> None:
    if loaded["family"] == "linear":
        del loaded["student"], loaded["modules"]
    else:
        del loaded["model"]
    if dev.type == "cuda":
        torch.cuda.empty_cache()


@torch.no_grad()
def _forward(loaded: dict[str, Any], xb: torch.Tensor) -> dict[str, np.ndarray]:
    if loaded["family"] == "linear":
        out = editor013_forward(loaded["student"], xb, loaded["modules"])
    else:
        out = student_forward(loaded["model"], xb)
    rec = {
        "logit": out["logit"].detach().cpu().numpy(),
        "z": out["z"].detach().cpu().numpy(),
        "attention_weights": out["attention_weights"].detach().cpu().numpy(),
    }
    return rec


def score_index(
    *,
    alias: str,
    seed: int,
    windows: np.ndarray | None = None,
    dense: np.ndarray | None = None,
    user_idx: np.ndarray | None = None,
    start_idx: np.ndarray | None = None,
    collect_representation: bool = False,
    dev: torch.device | None = None,
) -> dict[str, Any]:
    """Score pre-gathered windows or gather from dense daily. Eval-only. No parameter update."""
    dev = dev or device()
    loaded = load_student(alias, seed, dev)
    if windows is not None:
        x_all = np.ascontiguousarray(windows)
        n = int(x_all.shape[0])

        def _batch(lo: int, hi: int) -> np.ndarray:
            return x_all[lo:hi]
    else:
        if dense is None or user_idx is None or start_idx is None:
            raise ValueError("dense/user_idx/start_idx required when windows is None")
        n = int(len(user_idx))

        def _batch(lo: int, hi: int) -> np.ndarray:
            return gather_windows(dense, user_idx[lo:hi], start_idx[lo:hi])

    logits = np.empty(n, dtype=np.float64)
    z_acc: list[np.ndarray] = []
    a_acc: list[np.ndarray] = []
    for lo in range(0, n, BATCH_SIZE):
        hi = min(n, lo + BATCH_SIZE)
        xb = torch.from_numpy(np.ascontiguousarray(_batch(lo, hi))).to(dev)
        rec = _forward(loaded, xb)
        logits[lo:hi] = rec["logit"].reshape(-1)
        if collect_representation:
            z_acc.append(rec["z"])
            a_acc.append(rec["attention_weights"])
        del xb
    assert_fingerprint(alias, seed, loaded)
    _unload(loaded, dev)
    out: dict[str, Any] = {
        "model": alias,
        "seed": int(seed),
        "logits": logits,
        "probs": sigmoid(logits),
        "fingerprint_unchanged": True,
    }
    if collect_representation:
        out["z"] = np.concatenate(z_acc, axis=0)
        out["attention_weights"] = np.concatenate(a_acc, axis=0)
    return out
