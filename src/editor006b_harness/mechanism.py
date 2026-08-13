"""Optional C2-vs-C5 mechanism summaries using frozen ablation metric definitions.

Does not select thresholds. Does not import training runners or optimisers.
Paper-facing external analysis may include only EXACT_FROZEN metrics.
PROXY metrics are forbidden in the paper-facing registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from .model_loaders import ODST_ARCH, _ensure_producing_paths
from .safety import BATCH_SIZE_FROZEN, FEAS_SCRIPTS, HarnessProtocolError, SEEDS, sha256_file

ROUTE_EPS = 1e-6
LOGIT_VAR_EPS = 1e-6

STATUS_EXACT = "EXACT_FROZEN"
STATUS_DISABLED = "DISABLED_NOT_REPRODUCIBLE"

_TRAIN_PY = FEAS_SCRIPTS / "objective2_teacher_anchored_odst" / "train.py"
_MODELS_PY = FEAS_SCRIPTS / "objective2_teacher_anchored_odst" / "models.py"
_DIAG_PY = FEAS_SCRIPTS / "prototype_v3_node" / "diagnostics.py"


def live_odst_forward(node_head: nn.Module, h: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Copied from frozen teacher-anchored models.py (inference fragment only)."""
    if getattr(node_head, "readout", None) != "canonical_tree_average":
        raise HarnessProtocolError("MECHANISM_MODULE_NOT_REPRODUCIBLE: readout mismatch")
    x = h
    live_choices: list[torch.Tensor] = []
    tree_bags: list[torch.Tensor] = []
    leaf_all: list[torch.Tensor] = []
    first_leaf = None
    for layer in node_head.layers:
        feature_probs = layer.feature_selection_probs()
        selected = torch.einsum("bf,tdf->btd", x, feature_probs)
        choice = layer.split_choice(selected)
        batch = x.size(0)
        c = choice.unsqueeze(2).expand(batch, layer.n_trees, layer.n_leaves, layer.depth)
        codes = layer.leaf_codes.view(1, 1, layer.n_leaves, layer.depth)
        log_c = torch.log(c.clamp(1e-8, 1.0 - 1e-8))
        log_1mc = torch.log((1.0 - c).clamp(1e-8, 1.0))
        leaf_probs = torch.exp((codes * log_c + (1.0 - codes) * log_1mc).sum(dim=-1))
        response = torch.einsum("btl,tlu->btu", leaf_probs, layer.leaf_responses)
        out = response.reshape(batch, layer.n_trees * layer.tree_dim)
        live_choices.append(choice)
        tree_bags.append(out)
        leaf_all.append(leaf_probs)
        if first_leaf is None:
            first_leaf = leaf_probs
        x = torch.cat([x, out], dim=-1)
    logit = torch.cat(tree_bags, dim=-1).mean(dim=-1)
    choices = torch.cat(live_choices, dim=1)
    leaves_all = torch.cat(leaf_all, dim=1)
    assert first_leaf is not None
    return logit, choices, first_leaf, leaves_all


def logit_consistency(student_logit: torch.Tensor, teacher_logit: torch.Tensor) -> torch.Tensor:
    diff = (student_logit - teacher_logit.detach()).pow(2).mean()
    var = teacher_logit.detach().var(unbiased=False) + LOGIT_VAR_EPS
    return diff / var


def route_kl(student_p: torch.Tensor, teacher_p: torch.Tensor, eps: float = ROUTE_EPS) -> torch.Tensor:
    p_t = teacher_p.detach().clamp(0.0, 1.0)
    p_s = student_p.clamp(0.0, 1.0)
    term = p_t * torch.log((p_t + eps) / (p_s + eps)) + (1.0 - p_t) * torch.log(
        (1.0 - p_t + eps) / (1.0 - p_s + eps)
    )
    return term.mean()


@torch.inference_mode()
def _forward_routing(model: nn.Module, x: np.ndarray, batch_size: int) -> dict[str, torch.Tensor]:
    device = torch.device("cpu")
    model = model.to(device)
    model.eval()
    logits = []
    choices = []
    leaves0 = []
    leaves_all = []
    z_list = []
    for lo in range(0, int(x.shape[0]), batch_size):
        hi = min(int(x.shape[0]), lo + batch_size)
        xb = torch.from_numpy(np.ascontiguousarray(x[lo:hi], dtype=np.float32)).to(device)
        z, _enc = model.encode_attention_h(xb)
        logit, ch, leaf0, leaf_all = live_odst_forward(model.node_head, z)
        logits.append(logit.cpu())
        choices.append(ch.cpu())
        leaves0.append(leaf0.cpu())
        leaves_all.append(leaf_all.cpu())
        z_list.append(z.cpu())
    return {
        "logit": torch.cat(logits),
        "choices": torch.cat(choices),
        "leaf0": torch.cat(leaves0),
        "leaf_all": torch.cat(leaves_all),
        "z": torch.cat(z_list),
    }


def compare_student_teacher(
    *,
    student: nn.Module,
    teacher: nn.Module,
    x: np.ndarray,
    batch_size: int = BATCH_SIZE_FROZEN,
) -> dict[str, Any]:
    s = _forward_routing(student, x, batch_size)
    t = _forward_routing(teacher, x, batch_size)
    sl, tl = s["logit"], t["logit"]
    sc, tc = s["choices"], t["choices"]
    s_dom = s["leaf_all"].argmax(dim=-1)
    t_dom = t["leaf_all"].argmax(dim=-1)
    per_seq = {
        "logit_abs_dev": (sl - tl).abs().cpu().numpy().astype(np.float64),
        "route_mae_seq": (sc - tc).abs().mean(dim=tuple(range(1, sc.ndim))).cpu().numpy().astype(np.float64),
    }
    return {
        "student_teacher_logit_deviation": float(logit_consistency(sl, tl).item()),
        "route_mae": float((sc - tc).abs().mean().item()),
        "route_kl": float(route_kl(sc, tc).item()),
        "hard_route_agreement": float(((sc > 0.5) == (tc > 0.5)).float().mean().item()),
        "dominant_leaf_agreement": float((s_dom == t_dom).float().mean().item()),
        "unused_leaf_fraction": "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE",
        "tree_contribution_rho": "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE",
        "per_sequence_summaries_only": True,
        "n": int(x.shape[0]),
        "mean_logit_abs_dev": float(per_seq["logit_abs_dev"].mean()),
        "mean_route_mae_seq": float(per_seq["route_mae_seq"].mean()),
        "paper_facing_core": (
            "logit deviation",
            "route MAE",
            "route KL",
            "hard-route agreement",
        ),
        "no_c5_external_superiority_claim": True,
        "no_tree_ranking_monotonicity_claim": True,
    }


def _sha_or_missing(path: Path) -> str:
    if not path.is_file():
        return "SOURCE_FILE_MISSING"
    return sha256_file(path)


def mechanism_registry() -> dict[str, Any]:
    train_sha = _sha_or_missing(_TRAIN_PY)
    models_sha = _sha_or_missing(_MODELS_PY)
    diag_sha = _sha_or_missing(_DIAG_PY)
    metrics = [
        {
            "metric_name": "student_teacher_logit_deviation",
            "status": STATUS_EXACT,
            "source_file": str(_MODELS_PY),
            "source_hash": models_sha,
            "definition": (
                "logit_consistency_loss: mean((s-t)^2) / (var(t)+1e-6); "
                "train.py val_logit_consistency"
            ),
            "required_reference_artefact": None,
            "paper_facing": True,
        },
        {
            "metric_name": "route_mae",
            "status": STATUS_EXACT,
            "source_file": str(_TRAIN_PY),
            "source_hash": train_sha,
            "definition": "mean absolute deviation of soft Bernoulli route choices (sc vs tc)",
            "required_reference_artefact": None,
            "paper_facing": True,
        },
        {
            "metric_name": "route_kl",
            "status": STATUS_EXACT,
            "source_file": str(_MODELS_PY),
            "source_hash": models_sha,
            "definition": (
                "Bernoulli KL on route choices with eps=1e-6; "
                "equals train.py routing_divergence / route_consistency_loss"
            ),
            "required_reference_artefact": None,
            "paper_facing": True,
        },
        {
            "metric_name": "hard_route_agreement",
            "status": STATUS_EXACT,
            "source_file": str(_TRAIN_PY),
            "source_hash": train_sha,
            "definition": "mean((sc>0.5)==(tc>0.5)) over soft Bernoulli route bits",
            "required_reference_artefact": None,
            "paper_facing": True,
        },
        {
            "metric_name": "dominant_leaf_agreement",
            "status": STATUS_EXACT,
            "source_file": str(_TRAIN_PY),
            "source_hash": train_sha,
            "definition": (
                "fraction of (sample, tree) pairs whose argmax leaf agrees; "
                "computed on all-layer leaf_probs (train.py lines 256-259)"
            ),
            "required_reference_artefact": None,
            "paper_facing": True,
        },
        {
            "metric_name": "unused_leaf_fraction",
            "status": STATUS_DISABLED,
            "source_file": str(_DIAG_PY),
            "source_hash": diag_sha,
            "definition": "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE",
            "required_reference_artefact": (
                "frozen activation threshold and max-over-samples comparison; "
                "not recovered. Producing ablation used mean leaf mass < 1e-4 "
                "(leaf_utilization_stats), which is not the paper unused-leaf definition "
                "max_over_samples(membership) <= activation_threshold. Mean membership "
                "is not substituted."
            ),
            "paper_facing": False,
            "disabled_reason": "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE",
        },
        {
            "metric_name": "tree_contribution_rho",
            "status": STATUS_DISABLED,
            "source_file": str(_TRAIN_PY),
            "source_hash": train_sha,
            "definition": "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE",
            "required_reference_artefact": (
                "16 reference-centred tree-contribution vectors using frozen "
                "training-median per-tree references; not pinned for C2/C5 external "
                "analysis. Ablation train.py used abs(tree_outputs) Spearman without "
                "reference-centring. Scalar-logit Pearson is not the frozen statistic "
                "and is removed (no PROXY)."
            ),
            "paper_facing": False,
            "disabled_reason": "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE",
        },
    ]
    paper_facing = [m for m in metrics if m.get("paper_facing")]
    if any(m["status"] != STATUS_EXACT for m in paper_facing):
        raise HarnessProtocolError("Paper-facing mechanism metric is not EXACT_FROZEN")
    if any("proxy" in m["metric_name"].lower() for m in paper_facing):
        raise HarnessProtocolError("PROXY metric in paper-facing registry")
    if any(m["status"] == "PROXY" for m in metrics):
        raise HarnessProtocolError("PROXY status is forbidden")
    return {
        "schema": "EDITOR006B1_MECHANISM_REGISTRY",
        "primary_incremental_anchoring": [
            "student_teacher_logit_deviation",
            "route_mae",
            "route_kl",
            "hard_route_agreement",
        ],
        "no_c5_external_superiority_claim": True,
        "no_tree_ranking_monotonicity_claim": True,
        "metrics": metrics,
    }


def paper_facing_mechanism_names() -> list[str]:
    return [m["metric_name"] for m in mechanism_registry()["metrics"] if m.get("paper_facing")]


def mechanism_on_fixture(
    *,
    loaded_by_key: dict[tuple[str, int], Any],
    x: np.ndarray,
) -> dict[str, Any]:
    """loaded_by_key maps (family, seed) -> nn.Module for ODST families."""
    _ensure_producing_paths()
    registry = mechanism_registry()
    per_seed: dict[int, Any] = {}
    try:
        for seed in SEEDS:
            teacher = loaded_by_key[("teacher_frozen_odst", seed)]
            c2 = loaded_by_key[("C2", seed)]
            c5 = loaded_by_key[("C5_original_paper", seed)]
            per_seed[seed] = {
                "C2_vs_teacher": compare_student_teacher(student=c2, teacher=teacher, x=x),
                "C5_vs_teacher": compare_student_teacher(student=c5, teacher=teacher, x=x),
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "MECHANISM_MODULE_NOT_REPRODUCIBLE",
            "reason": str(exc),
            "architecture_config": dict(ODST_ARCH),
            "registry": registry,
        }
    return {
        "status": "PASS",
        "definitions_source": (
            "cert-r42-feasibility/scripts/objective2_teacher_anchored_odst/"
            "train.py + models.py (inference fragments only)"
        ),
        "threshold_selection_invoked": False,
        "per_seed": per_seed,
        "kind": "engineering_mechanism_selftest",
        "not_scientific_results": True,
        "registry": registry,
        "unused_leaf": "UNUSED_LEAF_METRIC_NOT_REPRODUCIBLE",
        "tree_contribution_rho": "TREE_CONTRIBUTION_RHO_NOT_REPRODUCIBLE",
    }
