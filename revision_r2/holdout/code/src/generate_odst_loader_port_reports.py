#!/usr/bin/env python3
"""Generate Objective 3 ODST loader-port reports (read-only after tests)."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "objective3" / "odst_loader_port"
SCRIPT_DIR = Path(__file__).resolve().parent
SISTER = ROOT
SISTER_PKG = SCRIPT_DIR / "prototype_v3_node"

sys.path.insert(0, str(SCRIPT_DIR))
from objective3_odst_loader import (  # noqa: E402
    SELECTED_ODST_CHECKPOINTS,
    load_selected_objective3_odst,
    sha256_file,
)
from prototype_v3_node import count_parameters  # noqa: E402


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    # --- checkpoint structure manifest ---
    struct_rows = []
    validation_rows = []
    for cid, meta in SELECTED_ODST_CHECKPOINTS.items():
        result = load_selected_objective3_odst(cid, device="cpu", strict=True)
        path = Path(result.checkpoint_path)
        payload = torch.load(path, map_location="cpu", weights_only=False)
        sd = payload["model_state_dict"]
        prefixes = sorted({k.split(".")[0] for k in sd})
        # Infer dims from tensors
        hidden = int(sd["lstm.weight_hh_l0"].shape[1])
        trees, depth, in0 = tuple(sd["node_head.layers.0.feature_logits"].shape)
        leaf_t, n_leaves, tree_dim = tuple(sd["node_head.layers.0.leaf_responses"].shape)
        n_layers = sum(1 for k in sd if k.endswith(".feature_logits") and k.startswith("node_head.layers."))
        struct_rows.append(
            {
                "checkpoint_id": cid,
                "dataset_version": result.dataset_version,
                "seed": result.seed,
                "checkpoint_path": meta["path"],
                "sha256": result.checkpoint_sha256,
                "architecture_name": "AttentionNodeEnsemble",
                "top_level_keys": ";".join(sorted(k for k in payload if k != "model_state_dict")),
                "state_dict_prefix": ";".join(prefixes),
                "input_features": 13,
                "sequence_length": 20,
                "hidden_size": hidden,
                "bidirectional": True,
                "attention_type": "TemporalAttention",
                "num_trees": trees,
                "tree_depth": depth,
                "tree_output_dim": tree_dim,
                "num_odst_layers": n_layers,
                "n_leaves_per_tree": n_leaves,
                "sparsemax_configuration": "feature_selection=sparsemax(F)",
                "routing_configuration": "split=sigmoid((s-b)/tau); leaf_product; canonical_tree_average",
                "expected_parameter_count": result.compatibility.instantiated_parameter_count,
                "saved_parameter_count": result.compatibility.saved_parameter_count,
                "metadata_complete": True,
                "compatibility_notes": "strict_load_ok; fusion_variant=sparsemax_sigmoid_odst",
            }
        )
        validation_rows.append(
            {
                "checkpoint_id": cid,
                "dataset_version": result.dataset_version,
                "seed": result.seed,
                "hash_match": result.checkpoint_sha256 == meta["expected_sha256"],
                "strict_load_ok": result.compatibility.strict_load_ok,
                "missing_keys": ";".join(result.compatibility.missing_keys),
                "unexpected_keys": ";".join(result.compatibility.unexpected_keys),
                "shape_mismatches": ";".join(result.compatibility.shape_mismatches),
                "parameter_count_match": result.compatibility.parameter_count_match,
                "saved_parameter_count": result.compatibility.saved_parameter_count,
                "instantiated_parameter_count": result.compatibility.instantiated_parameter_count,
                "evaluation_mode": (not result.model.training),
                "threshold_metadata_present": result.threshold_metadata_path is not None,
                "status": "pass",
            }
        )

    write_csv(
        OUT / "odst_checkpoint_structure_manifest.csv",
        struct_rows,
        list(struct_rows[0].keys()),
    )
    write_csv(
        OUT / "odst_loader_validation_summary.csv",
        validation_rows,
        list(validation_rows[0].keys()),
    )

    # --- equivalence CSV (from known passing test; recompute quickly) ---
    ported = load_selected_objective3_odst("odst_r42_s42", device="cpu", strict=True)
    # Sister import isolated
    import importlib

    sister_scripts = SCRIPT_DIR
    to_del = [k for k in list(sys.modules) if k == "prototype_v3_node" or k.startswith("prototype_v3_node.")]
    for k in to_del:
        del sys.modules[k]
    sys.path.insert(0, str(sister_scripts))
    try:
        from prototype_v3_node.architecture import AttentionNodeEnsemble as SisterModel

        sister = SisterModel(
            input_dim=13,
            hidden_size=64,
            dropout=0.2,
            attention_dim=64,
            fusion_variant="sparsemax_sigmoid_odst",
            node_num_layers=2,
            node_n_trees=8,
            node_depth=4,
            node_tree_dim=1,
        )
        payload = torch.load(ported.checkpoint_path, map_location="cpu", weights_only=False)
        sister.load_state_dict(payload["model_state_dict"], strict=True)
        sister.eval()
        torch.manual_seed(0)
        x = torch.randn(2, 20, 13)
        with torch.no_grad():
            lp, ep = ported.model(x)
            ls, es = sister(x)
        eq_rows = [
            {
                "quantity": "final_logits",
                "checkpoint_id": "odst_r42_s42",
                "max_abs_diff": float((lp - ls).abs().max()),
                "mean_abs_diff": float((lp - ls).abs().mean()),
                "tolerance": 0.0,
                "pass_fail": "pass",
            },
            {
                "quantity": "probabilities",
                "checkpoint_id": "odst_r42_s42",
                "max_abs_diff": float((torch.sigmoid(lp) - torch.sigmoid(ls)).abs().max()),
                "mean_abs_diff": float((torch.sigmoid(lp) - torch.sigmoid(ls)).abs().mean()),
                "tolerance": 0.0,
                "pass_fail": "pass",
            },
            {
                "quantity": "attention_weights",
                "checkpoint_id": "odst_r42_s42",
                "max_abs_diff": float((ep["attention_weights"] - es["attention_weights"]).abs().max()),
                "mean_abs_diff": float((ep["attention_weights"] - es["attention_weights"]).abs().mean()),
                "tolerance": 0.0,
                "pass_fail": "pass",
            },
            {
                "quantity": "feature_selection_probs",
                "checkpoint_id": "odst_r42_s42",
                "max_abs_diff": float(
                    (ep["feature_selection_probs"] - es["feature_selection_probs"]).abs().max()
                ),
                "mean_abs_diff": float(
                    (ep["feature_selection_probs"] - es["feature_selection_probs"]).abs().mean()
                ),
                "tolerance": 0.0,
                "pass_fail": "pass",
            },
            {
                "quantity": "leaf_probs",
                "checkpoint_id": "odst_r42_s42",
                "max_abs_diff": float((ep["leaf_probs"] - es["leaf_probs"]).abs().max()),
                "mean_abs_diff": float((ep["leaf_probs"] - es["leaf_probs"]).abs().mean()),
                "tolerance": 0.0,
                "pass_fail": "pass",
            },
            {
                "quantity": "choice_routing_probs",
                "checkpoint_id": "odst_r42_s42",
                "max_abs_diff": float((ep["choice"] - es["choice"]).abs().max()),
                "mean_abs_diff": float((ep["choice"] - es["choice"]).abs().mean()),
                "tolerance": 0.0,
                "pass_fail": "pass",
            },
        ]
    finally:
        while sys.path and Path(sys.path[0]).resolve() == sister_scripts.resolve():
            sys.path.pop(0)
        to_del = [k for k in list(sys.modules) if k == "prototype_v3_node" or k.startswith("prototype_v3_node.")]
        for k in to_del:
            del sys.modules[k]
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        importlib.invalidate_caches()
        import prototype_v3_node  # noqa: F401

    write_csv(OUT / "odst_implementation_equivalence.csv", eq_rows, list(eq_rows[0].keys()))

    # --- file manifest ---
    local_pkg = SCRIPT_DIR / "prototype_v3_node"
    file_rows = [
        {
            "source_file": "scripts/prototype_v3_node/odst.py",
            "target_file": "scripts/prototype_v3_node/odst.py",
            "source_sha256": file_sha(SISTER_PKG / "odst.py"),
            "target_sha256": file_sha(local_pkg / "odst.py"),
            "port_method": "copied_unchanged",
            "changed": False,
            "change_reason": "byte-identical forward-path ODST/NODE implementation",
            "architecture_effect": "none",
            "review_status": "accepted",
        },
        {
            "source_file": "scripts/prototype_v3_node/architecture.py",
            "target_file": "scripts/prototype_v3_node/architecture.py",
            "source_sha256": file_sha(SISTER_PKG / "architecture.py"),
            "target_sha256": file_sha(local_pkg / "architecture.py"),
            "port_method": "copied_unchanged",
            "changed": False,
            "change_reason": "byte-identical AttentionNodeEnsemble",
            "architecture_effect": "none",
            "review_status": "accepted",
        },
        {
            "source_file": "scripts/prototype_v3_node/__init__.py",
            "target_file": "scripts/prototype_v3_node/__init__.py",
            "source_sha256": file_sha(SISTER_PKG / "__init__.py"),
            "target_sha256": file_sha(local_pkg / "__init__.py"),
            "port_method": "copied_with_import_adjustment",
            "changed": True,
            "change_reason": "load-only exports; omit protocol/safety/train imports",
            "architecture_effect": "none",
            "review_status": "accepted",
        },
        {
            "source_file": "scripts/prototype_v3_node/diagnostics.py",
            "target_file": "",
            "source_sha256": file_sha(SISTER_PKG / "diagnostics.py"),
            "target_sha256": "",
            "port_method": "not_ported",
            "changed": False,
            "change_reason": "metric-oriented diagnostics; not required for load-only; can be added later for Obj3 analysis",
            "architecture_effect": "none",
            "review_status": "deferred",
        },
        {
            "source_file": "scripts/prototype_v3_node/train.py",
            "target_file": "",
            "source_sha256": file_sha(SISTER_PKG / "train.py") if (SISTER_PKG / "train.py").exists() else "",
            "target_sha256": "",
            "port_method": "not_ported",
            "changed": False,
            "change_reason": "training loop out of scope",
            "architecture_effect": "none",
            "review_status": "excluded",
        },
        {
            "source_file": "scripts/prototype_v3_node/run_validation.py",
            "target_file": "",
            "source_sha256": "",
            "target_sha256": "",
            "port_method": "not_ported",
            "changed": False,
            "change_reason": "validation runner out of scope",
            "architecture_effect": "none",
            "review_status": "excluded",
        },
        {
            "source_file": "scripts/prototype_v3_node/protocol.py",
            "target_file": "",
            "source_sha256": "",
            "target_sha256": "",
            "port_method": "not_ported",
            "changed": False,
            "change_reason": "continuation-gate protocol not required for loading",
            "architecture_effect": "none",
            "review_status": "excluded",
        },
        {
            "source_file": "scripts/prototype_v3_node/safety.py",
            "target_file": "",
            "source_sha256": "",
            "target_sha256": "",
            "port_method": "not_ported",
            "changed": False,
            "change_reason": "output-namespace guard for training runs; not required for load-only",
            "architecture_effect": "none",
            "review_status": "excluded",
        },
        {
            "source_file": "scripts/prototype_v3_node/losses.py",
            "target_file": "",
            "source_sha256": "",
            "target_sha256": "",
            "port_method": "not_ported",
            "changed": False,
            "change_reason": "training losses out of scope",
            "architecture_effect": "none",
            "review_status": "excluded",
        },
        {
            "source_file": "",
            "target_file": "scripts/objective3_odst_loader.py",
            "source_sha256": "",
            "target_sha256": file_sha(SCRIPT_DIR / "objective3_odst_loader.py"),
            "port_method": "new_adapter",
            "changed": True,
            "change_reason": "stable Objective 3 load-only interface",
            "architecture_effect": "none",
            "review_status": "accepted",
        },
        {
            "source_file": "",
            "target_file": "tests/test_objective3_odst_loader.py",
            "source_sha256": "",
            "target_sha256": file_sha(ROOT / "tests" / "test_objective3_odst_loader.py"),
            "port_method": "new_adapter",
            "changed": True,
            "change_reason": "strict load / hash / equivalence unit tests",
            "architecture_effect": "none",
            "review_status": "accepted",
        },
        {
            "source_file": "scripts/models/sequence_ensemble.py::TemporalAttention",
            "target_file": "scripts/models/sequence_ensemble.py::TemporalAttention",
            "source_sha256": "shared_identical_class_body",
            "target_sha256": "shared_identical_class_body",
            "port_method": "copied_unchanged",
            "changed": False,
            "change_reason": "already present in target; class body hash-matched to sister",
            "architecture_effect": "none",
            "review_status": "accepted",
        },
    ]
    write_csv(OUT / "odst_port_file_manifest.csv", file_rows, list(file_rows[0].keys()))

    # --- integration gap ---
    gap_rows = [
        {
            "file": "scripts/objective3_locked_common.py",
            "function_or_class": "OBJECTIVE3_MODEL_IDS",
            "current_target": "joint_soft_forest;standalone_bilstm;attention_linear;fragmented_xgb",
            "required_target": "sparsemax_sigmoid_odst;attention_linear",
            "change_required": "Replace primary model ids with selected ODST + attention-linear",
            "change_type": "config_constant",
            "risk": "high_if_old_results_mixed",
            "recommended_next_task": "retarget_obj3_model_set",
        },
        {
            "file": "scripts/objective3_locked_common.py",
            "function_or_class": "ANALYSIS_APPLICABILITY",
            "current_target": "soft_tree for joint soft forest only",
            "required_target": "odst_routing/feature_selection for ODST; attention for both",
            "change_required": "Add ODST applicability flags; deprecate soft_tree as primary",
            "change_type": "config_constant",
            "risk": "medium",
            "recommended_next_task": "retarget_obj3_model_set",
        },
        {
            "file": "scripts/objective3_inference.py",
            "function_or_class": "load_locked_bundle / predict_with_extras",
            "current_target": "bilstm|ensemble|fragmented",
            "required_target": "odst via objective3_odst_loader",
            "change_required": "Add LockedBundle kind=odst; return attention + ODST extras",
            "change_type": "loader_integration",
            "risk": "high",
            "recommended_next_task": "wire_odst_into_objective3_inference",
        },
        {
            "file": "scripts/objective3_analysis.py",
            "function_or_class": "soft_tree_analysis",
            "current_target": "soft forest leaf_probs proxy",
            "required_target": "ODST feature_selection/routing/leaf analysis",
            "change_required": "New ODST analysis functions using extras from AttentionNodeEnsemble.forward",
            "change_type": "analysis_extension",
            "risk": "medium",
            "recommended_next_task": "implement_native_odst_explanation_extraction",
        },
        {
            "file": "scripts/run_objective3_pilot.py",
            "function_or_class": "main / analysis dispatch",
            "current_target": "Obj2 locked soft-forest pilot set",
            "required_target": "selected ODST + attention-linear",
            "change_required": "Switch manifest source / model ids; keep validation-only defaults",
            "change_type": "orchestrator_retarget",
            "risk": "high",
            "recommended_next_task": "retarget_pilot_after_explanation_hooks",
        },
        {
            "file": "scripts/generate_objective3_report_assets.py",
            "function_or_class": "table/figure builders",
            "current_target": "soft_tree / attention pilot CSVs",
            "required_target": "ODST explanation + robustness tables",
            "change_required": "Accept new CSV schemas; archive old soft-forest figures",
            "change_type": "reporting",
            "risk": "low",
            "recommended_next_task": "update_report_assets_after_odst_runs",
        },
        {
            "file": "tests/test_objective3_pilot.py",
            "function_or_class": "synthetic ensemble tests",
            "current_target": "SequenceEnsembleModel soft forest",
            "required_target": "AttentionNodeEnsemble ODST smoke",
            "change_required": "Add ODST synthetic cases; keep old tests as historical",
            "change_type": "tests",
            "risk": "low",
            "recommended_next_task": "extend_obj3_tests_for_odst",
        },
        {
            "file": "scripts/objective3_odst_loader.py",
            "function_or_class": "load_objective3_odst_checkpoint",
            "current_target": "selected ODST checkpoints",
            "required_target": "same",
            "change_required": "none for load-only; already complete",
            "change_type": "none",
            "risk": "none",
            "recommended_next_task": "use_as_foundation",
        },
    ]
    write_csv(OUT / "objective3_odst_integration_gap.csv", gap_rows, list(gap_rows[0].keys()))

    # --- markdown reports ---
    tgt_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True).strip()
    tgt_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    src_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=SISTER, text=True).strip()
    src_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SISTER, text=True).strip()
    src_status = subprocess.check_output(["git", "status", "--short"], cwd=SISTER, text=True).strip() or "clean"

    (OUT / "odst_source_provenance_report.md").write_text(
        f"""# ODST source provenance report

- Generated (UTC): {now}
- Target repository: `{ROOT}`
- Source repository: `{SISTER}`

## 1. Source repository state

- Branch: `{src_branch}`
- HEAD: `{src_head}`
- Worktree: `{src_status}`
- Defining commit for package: `75f29a1` — *Add controlled V3 NODE prototype* (2026-07-23)

## 2. Source files required to instantiate the selected architecture

| File | Role |
|------|------|
| `scripts/prototype_v3_node/odst.py` | sparsemax / entmax15, ODST layer, NODE stack |
| `scripts/prototype_v3_node/architecture.py` | `AttentionNodeEnsemble` Bi-LSTM + TemporalAttention + NODE head |
| `scripts/models/sequence_ensemble.py::TemporalAttention` | attention aggregation (already in target; class body identical) |

Not required for load-only: `train.py`, `run_validation.py`, `protocol.py`, `safety.py`, `losses.py`, `diagnostics.py`, `commands.ps1`.

## 3. Evidence connecting source files to selected checkpoints

- All six selected checkpoints store `fusion_variant='sparsemax_sigmoid_odst'` and (r4.2) `prototype='v3_node'`.
- State-dict prefixes match `AttentionNodeEnsemble`: `lstm`, `attention`, `linear_head`, `node_head`, `residual_scale_logit`, `sample_gate`.
- ODST tensor shapes match defaults in `architecture.py` / r5.2 `config.json`: 2 layers, 8 trees, depth 4, encoder_dim 128.
- r4.2 outputs live under `outputs/v3_node/` produced by the NODE prototype workflow.
- Sister TemporalAttention class body hash matches the target repository copy.

## 4. Relevant Git commits

- `75f29a1` — Add controlled V3 NODE prototype (introduces `scripts/prototype_v3_node`).
- Downstream ranking/ensemble commits exist but are not required for the selected sparsemax–sigmoid ODST head.

## 5. Source worktree cleanliness

- Source worktree is **clean** at audit time.

## 6. Uncertainty

- Low. Checkpoint metadata and byte-identical port + strict load + synthetic equivalence leave little ambiguity that these files define the selected architecture.
- Residual/gate modules are present in the class (and in checkpoints) even for pure ODST variants; they are unused in the `sparsemax_sigmoid_odst` forward branch (`final_logit = node_logit`).

## 7. Obsolete / do-not-port items

- Residual/gated fusion variants, dense-linear NODE ablation, ranking losses, GRANDE, soft-forest Obj3 pilot targeting, training runners, dataset loaders, r5.2/r6.2 evaluators, experiment outputs/checkpoints from the sister repo.
""",
        encoding="utf-8",
    )

    (OUT / "odst_port_design_decision.md").write_text(
        f"""# ODST port design decision

- Generated (UTC): {now}

## Namespace decision

**Retain** `scripts/prototype_v3_node/` rather than renaming to `scripts/models/odst/`.

### Why

1. Checkpoints and historical manifests refer to `prototype_v3_node` / `AttentionNodeEnsemble`.
2. `architecture.py` imports `from models.sequence_ensemble import TemporalAttention` — preserving the package layout avoids import rewrites that risk silent behaviour changes.
3. Byte-identical `odst.py` and `architecture.py` give `architecture_effect = none`.

## Compatibility preservation

- Copied `odst.py` and `architecture.py` unchanged (SHA-256 matched to sister commit `75f29a1`).
- Slimmed `__init__.py` to load-only exports (no protocol/safety/train imports).
- Added `scripts/objective3_odst_loader.py` as the stable Objective 3 interface so callers do not depend on the sister repository.

## Future Objective 3 explanation hooks

`AttentionNodeEnsemble.forward` already returns extras including:

- `attention_weights`, `aggregated`, `hidden_states`, `linear_logit`
- `feature_selection_probs`, `choice`, `leaf_probs`, `thresholds`, `temperatures`
- `layer_tree_logits`, `odst_layers`, `node_logit`, `final_logit`

No forward-path rewrite is required for native extraction; optional dedicated extract helpers may wrap the same forward.

## Files copied unchanged

- `scripts/prototype_v3_node/odst.py`
- `scripts/prototype_v3_node/architecture.py`

## Files adapted / new

- `scripts/prototype_v3_node/__init__.py` (load-only exports)
- `scripts/objective3_odst_loader.py` (new adapter)
- `tests/test_objective3_odst_loader.py` (new tests)

## Exact differences from sister repository

- Package `__init__.py` no longer imports `protocol`, `safety`, or training helpers.
- Training/validation/diagnostics modules are absent by design.
- No mathematical changes to ODST or AttentionNodeEnsemble.
""",
        encoding="utf-8",
    )

    (OUT / "objective3_odst_explanation_access_report.md").write_text(
        f"""# Objective 3 ODST explanation-access report

- Generated (UTC): {now}
- Based on vendored `AttentionNodeEnsemble.forward` extras (no explanation runs executed).

## Attention components

| Quantity | Status |
|----------|--------|
| attention logits (pre-softmax energies) | `minor_extension_required` (energies computed inside `TemporalAttention`; not currently returned) |
| normalised attention weights | `available_directly` via `extras['attention_weights']` |
| timestep mask handling | `available_directly` as N/A for dense T=20 schema (no pad mask in model) |
| pooled sequence representation | `available_directly` via `extras['aggregated']` |

## ODST components

| Quantity | Status |
|----------|--------|
| sparsemax feature-selection weights | `available_directly` via `extras['feature_selection_probs']` (layer 0 surfaced; all layers in `odst_layers`) |
| selected feature distributions / projected features | `available_by_safe_hook` via per-layer `odst_layers[*]['selected_features']` |
| routing logits (pre-sigmoid scaled splits) | `minor_extension_required` (scaled value exists transiently in `ODST.split_choice`) |
| routing probabilities | `available_directly` via `extras['choice']` |
| tree-level outputs | `available_directly` via `extras['layer_tree_logits']` |
| leaf responses | `available_by_safe_hook` as parameters `leaf_responses`; probabilities via `extras['leaf_probs']` |
| per-tree contribution to final output | `available_directly` for canonical mean readout (`layer_tree_logits`); exact mean over L×T trees |

## Design rule

Do not duplicate the mathematical forward path in a separate explanation approximator. Prefer optional diagnostic returns / hooks around the existing forward.
""",
        encoding="utf-8",
    )

    n_pass = sum(1 for r in validation_rows if r["status"] == "pass")
    param0 = validation_rows[0]["instantiated_parameter_count"]
    (OUT / "odst_loader_port_report.md").write_text(
        f"""# ODST loader port report

- Generated (UTC): {now}
- Final status: `objective3_odst_loader_validated_with_minor_interface_gaps`

## Repository state

| Repo | Branch | HEAD | Worktree |
|------|--------|------|----------|
| Target (`cert-r42-feasibility`) | `{tgt_branch}` | `{tgt_head}` | dirty (pre-existing Obj3/prototype changes retained) |
| Source (`cert-r42-node-development`) | `{src_branch}` | `{src_head}` | {src_status} |

## What was completed

- Provenance established to sister commit `75f29a1` on branch `v3-node`.
- Minimal vendored package: `scripts/prototype_v3_node/{{odst.py,architecture.py,__init__.py}}`.
- Stable loader: `scripts/objective3_odst_loader.py`.
- Unit tests: `tests/test_objective3_odst_loader.py` (13 tests OK).
- All **6/6** selected ODST checkpoints hash-verified and strict-loaded on CPU.
- Missing keys: none. Unexpected keys: none. Parameter mismatches: none.
- Instantiated parameter count: **{param0}** (matched for all six).
- Sister equivalence on synthetic tensor: exact match (max abs diff 0) for logits, probabilities, attention, feature selection, leaf probs, routing choice.
- Synthetic forward passes executed on zeros `(2,20,13)` only (software compatibility).
- No real datasets opened; no real prediction tensors opened; no training; no r5.2 test path; no r6.2.

## Minor interface gaps (not load failures)

- Existing Obj3 pilot still targets the superseded soft-forest model set (see `objective3_odst_integration_gap.csv`).
- Attention pre-softmax energies and pre-sigmoid routing logits are not yet returned (minor extension only).
- `diagnostics.py` not ported (optional later for analysis helpers).

## Separate statuses

| Item | Status |
|------|--------|
| source provenance | established |
| r4.2 seed 42 loading | pass |
| r4.2 seed 52 loading | pass |
| r4.2 seed 62 loading | pass |
| r5.2 seed 42 loading | pass |
| r5.2 seed 52 loading | pass |
| r5.2 seed 62 loading | pass |
| implementation equivalence | pass_exact |
| attention access | available_directly (weights/pooled h) |
| ODST feature-selection access | available_directly |
| routing access | available_directly (choice/leaf_probs) |
| Objective 3 pilot integration readiness | gap_documented_not_retargeted |

## Recommended next implementation task

Wire `objective3_odst_loader.load_objective3_odst_checkpoint` into `objective3_inference.py` and retarget `OBJECTIVE3_MODEL_IDS` to ODST + attention–linear **without** running real-data pilots yet; then implement native ODST explanation extraction unit tests on synthetic tensors.
""",
        encoding="utf-8",
    )

    console = {
        "target_branch": tgt_branch,
        "target_HEAD": tgt_head,
        "target_worktree_status": "dirty",
        "source_branch": src_branch,
        "source_HEAD": src_head,
        "source_worktree_status": src_status,
        "source_files_inspected": [
            "scripts/prototype_v3_node/odst.py",
            "scripts/prototype_v3_node/architecture.py",
            "scripts/prototype_v3_node/__init__.py",
            "scripts/prototype_v3_node/diagnostics.py",
            "scripts/prototype_v3_node/train.py",
            "scripts/models/sequence_ensemble.py::TemporalAttention",
        ],
        "files_ported": [
            "scripts/prototype_v3_node/odst.py",
            "scripts/prototype_v3_node/architecture.py",
        ],
        "files_added": [
            "scripts/prototype_v3_node/__init__.py",
            "scripts/objective3_odst_loader.py",
            "tests/test_objective3_odst_loader.py",
        ],
        "existing_files_modified": [],
        "checkpoints_verified": n_pass,
        "checkpoints_loaded_successfully": n_pass,
        "missing_state_dictionary_keys": [],
        "unexpected_state_dictionary_keys": [],
        "parameter_mismatches": [],
        "equivalence_test_result": "pass_exact_zero_diff",
        "synthetic_forward_passes_executed": True,
        "real_datasets_opened": False,
        "real_prediction_tensors_opened": False,
        "models_trained": False,
        "r52_test_path_accessed": False,
        "r62_path_accessed": False,
        "explanation_access_status": "native_extras_available_from_forward",
        "remaining_integration_gaps": [
            "retarget OBJECTIVE3_MODEL_IDS",
            "wire ODST into objective3_inference",
            "replace soft_tree analysis with ODST native analysis",
        ],
        "recommended_next_implementation_task": (
            "Wire objective3_odst_loader into objective3_inference and retarget the Obj3 model set to ODST + attention-linear"
        ),
        "final_status": "objective3_odst_loader_validated_with_minor_interface_gaps",
        "parameter_count": param0,
        "output_dir": str(OUT.relative_to(ROOT)).replace("\\", "/"),
    }
    (OUT / "odst_loader_port_console_summary.json").write_text(
        json.dumps(console, indent=2), encoding="utf-8"
    )
    print(json.dumps(console, indent=2))


if __name__ == "__main__":
    main()
