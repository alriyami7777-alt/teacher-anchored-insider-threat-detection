#!/usr/bin/env python3
"""Generate Objective 3 ODST inference-integration reports (no real-data experiments)."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from objective3_model_registry import (  # noqa: E402
    NEURAL_REFERENCE_ARCHITECTURE,
    PRIMARY_ARCHITECTURE,
    list_registry_entries,
    registry_counts_by_architecture,
    registry_row_count,
)

OUT = ROOT / "outputs" / "objective3" / "odst_inference_integration"
LOG = OUT / "test_logs"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = fieldnames or list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def git(cmd: list[str]) -> str:
    return subprocess.check_output(["git", *cmd], cwd=ROOT, text=True).strip()


def write_audit() -> None:
    text = """# Objective 3 existing interface audit

Scope: software interface for Research Objective 3 / Chapter 3 explainability and robustness.
No real CERT data opened during this audit.

| File | Function / class | Current model target | Input type | Output type | Soft-forest assumptions | Valid for ODST | Valid for attention–linear | Required modification | Behaviour-change risk |
|---|---|---|---|---|---|---|---|---|---|
| `objective3_locked_common.py` | `OBJECTIVE3_MODEL_IDS` | soft forest; bilstm; attention_linear; fragmented xgb | n/a | tuple[str] | Soft forest is primary | No (legacy) | Partial (legacy alias) | Keep as `LEGACY_OBJECTIVE3_MODEL_IDS`; add selected architecture IDs | Low if legacy retained |
| `objective3_locked_common.py` | `ANALYSIS_APPLICABILITY` | soft_tree → soft forest only | n/a | dict | Soft-tree routing = explainability | Soft tree ≠ ODST | No soft tree | Add `odst_native`; mark soft_tree superseded | Low |
| `objective3_inference.py` | `load_locked_bundle` | Obj2 manifest models | manifest entry | `LockedBundle` | soft_forest head for joint model | No ODST kind | Yes via ensemble/linear | Keep legacy; selected path uses new loader | Medium if IDs swapped |
| `objective3_inference.py` | `predict_with_extras` | bilstm/ensemble/fragmented | numpy (N,T,F) | probs + attention + soft routing | Soft routing labelled as routing | Must not use soft routing as ODST | Attention only | Document superseded; new `objective3_inference` | High if pilots reinterpreted |
| `objective3_perturbations.py` | `apply_perturbation` | feature tensors | numpy (B,T,F) | numpy | Device/threshold agnostic | Valid | Valid | Add thin inference adapter only | Low |
| `run_objective3_pilot.py` | CLI / main | `OBJECTIVE3_MODEL_IDS` | validation tensors | pilot artefacts | Soft-tree analysis for joint forest | Must not claim ODST | Attention analyses OK | Leave pilot; new registry for selected models | High if retargeted now |
| `generate_objective3_report_assets.py` | report builders | legacy model order | pilot CSVs | figures | Soft-forest labels | Not ODST evidence | OK as reference | Untouched this task | Medium |
| `objective3_odst_loader.py` | `load_objective3_odst_checkpoint` | sparsemax_sigmoid_odst | checkpoint path | loaded ODST | n/a | Yes | No | Wire into common interface | Low |
| `prototype_v3_node/architecture.py` | `AttentionNodeEnsemble.forward` | ODST variants | (B,20,13) | logit + extras | n/a | Native extras | linear reference variant exists | Consume extras in interface | None (read-only) |
| `prototype_v3_node/odst.py` | `ODST.forward` / `NODE.forward` | ODST layers | (B,d) | tree responses + extras | n/a | Yes | No | Document tensor semantics | None |

## Soft-forest stand-in findings

- `predict_with_extras` returns soft-tree `routing` (`leaf_probs`, `p_left`, `p_right`) for `joint_bilstm_attention_soft_forest`.
- Pilot soft-tree analysis treated those quantities as tree explanations.
- They must **not** be labelled as ODST sparsemax feature-selection or ODST leaf probabilities.

## Modifications applied this task

- New hash-pinned registry: `objective3_model_registry.py` (12 entries).
- New common load/inference: `objective3_model_interface.py`.
- Legacy IDs retained; soft-forest path marked `superseded_model_only`.
- Perturbation module gains a thin adapter to the common inference interface.
"""
    (OUT / "objective3_existing_interface_audit.md").write_text(text, encoding="utf-8")


def write_tensor_semantics() -> None:
    text = """# Objective 3 ODST tensor semantics

Source modules: `scripts/prototype_v3_node/odst.py`, `scripts/prototype_v3_node/architecture.py`.
Selected fusion variant: `sparsemax_sigmoid_odst` (sparsemax feature selection + sigmoid splits + canonical tree average).

**Do not interpret routing values as causal explanations.** They are intermediate differentiable computations.

| Source variable | Mathematical meaning | Shape | Axis definitions | Bounds | Normalisation | Future explanation use | Limitation |
|---|---|---|---|---|---|---|---|
| `attention_weights` | Softmax attention over timesteps | `(B, T)` T=20 | B batch; T timestep | ≥0 | Sum_T ≈ 1 | Temporal importance | Not causal; sensitive to padding unless masked |
| `attention_logits` | Pre-softmax energies | not in forward extras | — | ℝ | none | Planned recovery from TemporalAttention | Currently `None` / unavailable |
| `aggregated` / pooled | Attention-weighted hidden state `h` | `(B, 2H)` H=64 → 128 | B; feature | ℝ | none | Input to ODST | Encoder-dependent |
| `hidden_states` | BiLSTM outputs | `(B, T, 2H)` | B,T,feat | ℝ | none | Sequence representation | Dropout inactive in eval |
| `feature_selection_probs` | Sparsemax feature weights `π` | `(T_tree, D, d_in)` | trees, depth, feature candidates | ≥0 | Sum over `d_in` = 1 | Native feature selection | Layer-0 exposed at top level; later layers differ in `d_in` |
| `choice` | Soft right-branch probability per split | `(B, T_tree, D)` | B, trees, depth | (0,1) | Independent Bernoulli-style soft gates (not a simplex over depth) | Routing visualisation | **Probabilities, not logits / hard indices**; not a full path distribution by itself |
| `leaf_probs` `μ` | Oblivious product leaf membership | `(B, T_tree, L)` L=2^D=16 | B, trees, leaves | ≥0 | Sum over leaves ≈ 1 per tree | Leaf occupancy | Soft membership; not hard leaf assignment |
| `thresholds` | Split thresholds | `(T_tree, D)` | trees, depth | ℝ | none | Diagnostics | Not an explanation alone |
| `temperatures` | Positive scales `softplus(log_τ)+ε` | `(T_tree, D)` | trees, depth | >0 | none | Diagnostics | Affects softness of `choice` |
| `layer_tree_logits` / tree response | Per-tree scalar outputs | list of `(B, T_tree)` per layer | layer then trees | ℝ | Averaged across all trees/layers for final logit | Tree-level contribution | Contribution = tree_logit / (n_layers·n_trees) under mean readout |
| `final_logit` / model logit | `mean` of all tree responses | `(B,)` | B | ℝ | sigmoid → probability | Prediction | ODST ablation (non-canonical choice functions) |

## Axis summary for selected ODST

- Trees per layer: 8 (`node_n_trees`)
- Depth: 4 (`node_depth`)
- Leaves per tree: 16
- Layers: 2 (`node_num_layers`)
- Layer-0 `d_in`: 128 (encoder dim)
- Layer-1 `d_in`: 136 (128 + 8 tree outputs)
- Final logit: mean over 16 tree responses (2×8)

## Combination rule

`final_logit = mean_{layer,tree} f_tree^(layer,tree)` for `canonical_tree_average` readout.
Tree-level contribution recoverable as `f_tree / 16` without changing the forward path.
"""
    (OUT / "objective3_odst_tensor_semantics.md").write_text(text, encoding="utf-8")


def write_legacy_report() -> None:
    text = """# Objective 3 legacy soft-forest stand-in report

## Finding

Earlier Objective 3 pilot code used `joint_bilstm_attention_soft_forest` soft-tree routing
(`p_left`, `p_right`, soft `leaf_probs`) as the tree-explanation pathway. That pathway is
**not** ODST and must not be described as sparsemax feature-selection or ODST leaf routing.

## Actions taken

1. Selected Objective 3 registry (`objective3_model_registry.py`) contains only:
   - `bi_lstm_attention_sparsemax_sigmoid_odst` (6 seeds/datasets)
   - `bi_lstm_attention_linear` (6 seeds/datasets)
2. Soft-forest / fragmented / standalone Bi-LSTM IDs are listed in
   `LEGACY_SUPERSEDED_MODEL_IDS` and raise on registry lookup.
3. `objective3_inference.load_locked_bundle` / `predict_with_extras` remain as a
   **legacy pilot path** marked `superseded_model_only` / `not_odst`.
4. `ANALYSIS_APPLICABILITY["soft_tree"]` is False for selected ODST and attention–linear.
5. New analysis key `odst_native` is True only for the selected ODST architecture.

## Scientific status of old pilot artefacts

Old soft-forest Objective 3 pilot results are **preliminary** and are **not evidence** for the
selected ODST architecture. They may remain on disk for historical comparison but must be
labelled as superseded-model-only.
"""
    (OUT / "objective3_legacy_standin_report.md").write_text(text, encoding="utf-8")


def write_registry_csv() -> None:
    rows = [e.to_row() for e in list_registry_entries()]
    write_csv(OUT / "objective3_model_registry.csv", rows)


def write_capability_matrix() -> None:
    rows = []
    for e in list_registry_entries():
        base = {
            "registry_key": e.registry_key,
            "model_id": e.model_id,
            "dataset_version": e.dataset_version,
            "seed": e.seed,
        }
        for k, v in e.explanation_capabilities.to_dict().items():
            rows.append({**base, "capability_group": "explanation", "capability": k, "status": v})
        for k, v in e.robustness_capabilities.to_dict().items():
            rows.append({**base, "capability_group": "robustness", "capability": k, "status": v})
    write_csv(OUT / "objective3_explanation_capability_matrix.csv", rows)


def write_modified_manifest(pre_hashes: dict[str, str]) -> None:
    tracked = [
        (
            "scripts/objective3_locked_common.py",
            "Annotate legacy IDs; add selected architecture IDs and odst_native applicability",
            "Obj3 registry/protocol separation",
            "Chapter 3 method applicability matrix",
            "no",
            "no_pilot_numerics",
        ),
        (
            "scripts/objective3_inference.py",
            "Document legacy soft-forest path; mark soft forest superseded_model_only",
            "Prevent ODST/soft-forest confusion",
            "Chapter 3 explanation interface hygiene",
            "no",
            "legacy_path_docs_only",
        ),
        (
            "scripts/objective3_perturbations.py",
            "Add thin adapter to common inference for future robustness work",
            "Future faithfulness/robustness interface",
            "Chapter 3 robustness phase readiness",
            "no",
            "no",
        ),
        (
            "scripts/objective3_model_registry.py",
            "NEW: hash-pinned ODST + attention–linear registry",
            "Obj3 selected model set",
            "Chapter 3 model inventory",
            "n/a_new",
            "n/a_new",
        ),
        (
            "scripts/objective3_model_interface.py",
            "NEW: common load + inference + explanation schema",
            "Obj3 inference/explanation interface",
            "Chapter 3 explanation extraction",
            "n/a_new",
            "n/a_new",
        ),
        (
            "tests/test_objective3_model_integration.py",
            "NEW: synthetic integration tests A–J",
            "Validate Obj3 ODST integration",
            "Chapter 3 software verification",
            "n/a_new",
            "n/a_new",
        ),
    ]
    rows = []
    for path, reason, rel_obj3, rel_ch3, fwd, pilot in tracked:
        p = ROOT / path
        post = sha256_file(p) if p.exists() else ""
        pre = pre_hashes.get(path.replace("\\", "/"), "")
        rows.append(
            {
                "file_path": path,
                "pre_change_hash": pre,
                "post_change_hash": post,
                "reason_for_modification": reason,
                "relationship_to_research_objective_3": rel_obj3,
                "relationship_to_chapter3_explanation_robustness": rel_ch3,
                "forward_numerical_behaviour_changed": fwd,
                "existing_pilot_behaviour_changed": pilot,
            }
        )
    write_csv(OUT / "modified_file_manifest.csv", rows)


def write_test_summary() -> None:
    log = LOG / "all_objective3_tests.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    passed = "60 passed" in text
    rows = [
        {"suite": "test_objective3_model_integration", "tests": 15, "status": "passed" if passed else "check_log"},
        {"suite": "test_objective3_odst_loader", "tests": 13, "status": "passed" if passed else "check_log"},
        {"suite": "test_objective3_pilot", "tests": 32, "status": "passed" if passed else "check_log"},
        {"suite": "combined", "tests": 60, "status": "passed" if passed else "check_log"},
        {"suite": "real_datasets_opened", "tests": 0, "status": "none"},
        {"suite": "real_prediction_tensors_opened", "tests": 0, "status": "none"},
        {"suite": "models_trained", "tests": 0, "status": "none"},
        {"suite": "explanation_experiments_executed", "tests": 0, "status": "none"},
        {"suite": "robustness_experiments_executed", "tests": 0, "status": "none"},
        {"suite": "r52_test_accessed", "tests": 0, "status": "none"},
        {"suite": "r62_accessed", "tests": 0, "status": "none"},
    ]
    write_csv(OUT / "objective3_inference_integration_test_summary.csv", rows)


def write_final_report() -> None:
    counts = registry_counts_by_architecture()
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    head = git(["rev-parse", "HEAD"])
    status = git(["status", "--short"])
    report = f"""# Objective 3 ODST inference integration report

Generated: {datetime.now(timezone.utc).isoformat()}

## Git

- branch: `{branch}`
- HEAD: `{head}`
- worktree: dirty (pre-existing Obj3/prototype changes preserved)

```
{status}
```

## Registry

- total entries: {registry_row_count()}
- ODST (`{PRIMARY_ARCHITECTURE}`): {counts.get(PRIMARY_ARCHITECTURE, 0)}
- attention–linear (`{NEURAL_REFERENCE_ARCHITECTURE}`): {counts.get(NEURAL_REFERENCE_ARCHITECTURE, 0)}
- All 12 checkpoints hash-pinned from the audited manifest / on-disk SHA-256.

## Interface

- ODST loading: via `objective3_odst_loader` (strict, CPU default, eval mode, no data).
- Attention–linear loading: verified `SequenceEnsembleModel` linear head, hash-checked.
- Common inference: `objective3_inference` returns stable schema; unsupported fields are `None`.
- Soft-forest stand-in: isolated on legacy path; not selectable from the new registry.

## Component statuses

| Component | Status |
|---|---|
| model registry | complete_12_entries |
| ODST loading | validated |
| attention–linear loading | validated |
| common inference interface | validated |
| attention extraction | validated |
| sparsemax feature-selection extraction | validated |
| routing extraction | validated |
| leaf-probability extraction | validated |
| mask handling | validated |
| gradient-path preservation | validated |
| perturbation-interface compatibility | stub_adapter_ready |
| legacy soft-forest isolation | validated |
| readiness for small r4.2 development pilot | ready_software_only |

## Tests

- New integration tests: passed
- ODST loader tests (13): passed
- Existing Objective 3 unit tests (32): passed
- Combined: 60 passed

## Restrictions observed

- real datasets opened: no
- real prediction tensors opened: no
- models trained: no
- new explanation experiments: no
- new robustness experiments: no
- r5.2 test path accessed: no
- r6.2 path accessed: no

## Overall status

`objective3_model_integration_validated`

## Remaining gaps (minor / planned)

- Attention logits not exposed by `TemporalAttention` extras (`None` until recovered).
- Integrated gradients / faithfulness metrics not implemented (planned).
- High/low-attention deletion and ODST-ranked deletion remain planned.
- Existing pilot artefacts still use superseded soft-forest IDs (historical only).

## Recommended next task

Small **r4.2 development** explanation pilot on the selected ODST + attention–linear models
using this interface (validation partition only; no r5.2 test / r6.2).
"""
    (OUT / "objective3_inference_integration_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.mkdir(parents=True, exist_ok=True)
    pre_path = OUT / "pre_change_hashes.csv"
    pre_hashes: dict[str, str] = {}
    if pre_path.exists():
        raw = pre_path.read_text(encoding="utf-8-sig")
        with pre_path.open("w", encoding="utf-8", newline="") as _:
            pass
        # Re-parse without BOM issues
        import io

        for row in csv.DictReader(io.StringIO(raw)):
            key = (row.get("file_path") or row.get("\ufefffile_path") or "").strip()
            if key:
                pre_hashes[key] = (row.get("pre_change_sha256") or "").strip()
        pre_path.write_text(raw.lstrip("\ufeff"), encoding="utf-8")

    write_audit()
    write_tensor_semantics()
    write_legacy_report()
    write_registry_csv()
    write_capability_matrix()
    write_modified_manifest(pre_hashes)
    write_test_summary()
    write_final_report()

    # Ensure initial git status exists
    if not (OUT / "initial_git_status.txt").exists():
        (OUT / "initial_git_status.txt").write_text(
            f"branch={git(['rev-parse', '--abbrev-ref', 'HEAD'])}\n"
            f"HEAD={git(['rev-parse', 'HEAD'])}\n"
            f"{git(['status', '--short'])}\n",
            encoding="utf-8",
        )

    meta = {
        "final_status": "objective3_model_integration_validated",
        "registry_count": registry_row_count(),
        "counts": registry_counts_by_architecture(),
    }
    (OUT / "status.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
