"""Secondary mechanism measurements. These do not determine promotion."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn

from editor012_rescue.data import make_xy_loader
from editor012_rescue.metrics import teacher_relative
from editor012_rescue.models import student_forward
from editor017_robustness.constants import NOISE_LEVELS, SOURCE_CHANNELS
from editor020_robustness.explain import explanation_stability_packet

from .constants import BATCH_SIZE, COSINE_EPS


def _cos(a: np.ndarray, b: np.ndarray, eps: float = COSINE_EPS) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    num = np.sum(a * b, axis=-1)
    den = np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1)
    return float(np.mean(num / np.clip(den, eps, None)))


@torch.no_grad()
def collect_clean_tensors(
    student: nn.Module,
    reference: nn.Module,
    teacher: nn.Module,
    X: np.ndarray,
    y: np.ndarray,
    device: torch.device,
) -> dict[str, np.ndarray]:
    student.eval()
    reference.eval()
    teacher.eval()
    loader = make_xy_loader(X, y, seed=0, batch_size=BATCH_SIZE, shuffle=False)
    s_logit, r_logit, t_logit = [], [], []
    s_z, r_z = [], []
    s_ch, t_ch, s_lf, t_lf, s_tr = [], [], [], [], []
    for xb, _yb in loader:
        xb = xb.to(device)
        s = student_forward(student, xb)
        r = student_forward(reference, xb)
        t = student_forward(teacher, xb)
        s_logit.append(s["logit"].cpu().numpy())
        r_logit.append(r["logit"].cpu().numpy())
        t_logit.append(t["logit"].cpu().numpy())
        s_z.append(s["z"].cpu().numpy())
        r_z.append(r["z"].cpu().numpy())
        s_ch.append(s["choices"].cpu().numpy())
        t_ch.append(t["choices"].cpu().numpy())
        s_lf.append(s["leaf_probs_all"].cpu().numpy())
        t_lf.append(t["leaf_probs_all"].cpu().numpy())
        s_tr.append(s["tree_outputs"].cpu().numpy())
    return {
        "student_logit": np.concatenate(s_logit),
        "ref_logit": np.concatenate(r_logit),
        "teacher_logit": np.concatenate(t_logit),
        "student_z": np.concatenate(s_z),
        "ref_z": np.concatenate(r_z),
        "student_choices": np.concatenate(s_ch),
        "teacher_choices": np.concatenate(t_ch),
        "student_leaves": np.concatenate(s_lf),
        "teacher_leaves": np.concatenate(t_lf),
        "student_trees": np.concatenate(s_tr),
    }


def mechanism_from_tensors(
    pack: dict[str, np.ndarray],
    *,
    degraded_student_z: dict[str, np.ndarray] | None = None,
    scored: dict[str, Any] | None = None,
    references: np.ndarray | None = None,
) -> dict[str, Any]:
    sl = pack["student_logit"]
    rl = pack["ref_logit"]
    rec: dict[str, Any] = {
        "clean_logit_mse_to_starting_ta2": float(np.mean((sl - rl) ** 2)),
        "clean_logit_mae_to_starting_ta2": float(np.mean(np.abs(sl - rl))),
        "clean_student_reference_repr_cosine": _cos(pack["student_z"], pack["ref_z"]),
        **teacher_relative(
            sl,
            pack["teacher_logit"],
            pack["student_choices"],
            pack["teacher_choices"],
            pack["student_leaves"],
            pack["teacher_leaves"],
        ),
    }
    if degraded_student_z:
        rec["degraded_student_clean_reference_repr_cosine"] = {
            k: _cos(v, pack["ref_z"]) for k, v in degraded_student_z.items()
        }
    if scored is not None and references is not None:
        deg_trees = {f"source_{ch}": scored["source"][ch]["tree_outputs"] for ch in SOURCE_CHANNELS}
        deg_trees.update({f"noise_{lv:.2f}": scored["noise"][float(lv)]["tree_outputs"] for lv in NOISE_LEVELS})
        deg_ch = {f"source_{ch}": scored["source"][ch]["choices"] for ch in SOURCE_CHANNELS}
        deg_ch.update({f"noise_{lv:.2f}": scored["noise"][float(lv)]["choices"] for lv in NOISE_LEVELS})
        deg_lf = {f"source_{ch}": scored["source"][ch]["leaf_probs_all"] for ch in SOURCE_CHANNELS}
        deg_lf.update({f"noise_{lv:.2f}": scored["noise"][float(lv)]["leaf_probs_all"] for lv in NOISE_LEVELS})
        rec["explanation_stability"] = explanation_stability_packet(
            clean_trees=scored["clean"]["tree_outputs"],
            degraded=deg_trees,
            references=references,
            clean_choices=scored["clean"]["choices"],
            degraded_choices=deg_ch,
            clean_leaves=scored["clean"]["leaf_probs_all"],
            degraded_leaves=deg_lf,
        )
        rec["signed_tree_contribution_spearman_note"] = (
            "stability only; not an independent faithfulness claim; global top-k PR-AUC faithfulness remains NOT_SUPPORTED"
        )
    return rec
