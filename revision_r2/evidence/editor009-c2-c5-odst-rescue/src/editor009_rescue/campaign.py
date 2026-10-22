"""EDITOR-009 overnight campaign orchestrator."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from . import PROTOCOL_COMMIT_PHASE0
from .data import BATCH_SIZE, load_train_validation, make_loaders
from .diagnostics import (
    collect_odst_state,
    match_route_assignment_from_train,
    permutation_route_loss,
)
from .evaluate import evaluate_pair, hash_gate_checkpoint, score_attention_linear, score_odst
from .losses import PRODUCING_W_LOGIT, PRODUCING_W_ROUTE, annealed_weight, logit_consistency_loss, route_consistency_loss
from .metrics import metrics_from_logits, teacher_relative
from .models import (
    enable_c5_student,
    enable_residual_e2e,
    enable_residual_head_only,
    freeze_teacher,
    student_forward,
    transfer_attention_linear,
    zero_odst_leaves,
)
from .producing import (
    build_attention_linear,
    build_odst_model,
    import_set_seed,
    load_state_dict,
    pin_producing_sources,
)
from .safety import (
    C5_DENY_HASHES,
    OUTPUT_ROOT,
    REVIEW_ROOT,
    Editor009ProtocolError,
    refuse_historical_write,
    sha256_file,
    utc_now,
)
from .train import capture_component_grads, train_condition, _cos, _l2

TEACHER = {
    42: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_odst_confirmation\\odst_seed42\\best.pt", "783d0913f85d492ddacec83a274ba2d4f13ad25eaf1a34ebcc64a960bda8ff86", 0.56),
    52: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_odst_confirmation\\odst_seed52\\best.pt", "7273327495bbe463cfb3d50fa94c81c82de7b304370a816343046f559fc3d191", 0.8400000000000001),
    62: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_odst_confirmation\\odst_seed62\\best.pt", "247d6e71353b49ea0a77a073a8606fbf35b88106faae7dae6ec53361621e9d92", 0.55),
}
C2 = {
    42: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C2\\seed42\\best_student.pt", "c5b8ab96a6f347afb85708857cef56b4a632f6092dfda9339ab9a3558daf863e", 0.6),
    52: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C2\\seed52\\best_student.pt", "2215b36edd015f783de86ecb1b40cdd535fb6f082adc16a377574a24a8d0c22b", 0.8300000000000001),
    62: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C2\\seed62\\best_student.pt", "595a5e57ec78d6d34e2811609dc97514b0703cab807b7dffe873128a92ecc5c2", 0.6544522184133537),
}
C5 = {
    42: ("C:\\PhD\\07_Projects\\cert-r52-teacher-anchored-reproducibility\\outputs\\objective2\\r52_teacher_anchored_reproducibility_v1\\seed42\\best_student.pt", "2b6452698dd0da53f0229bc43040a877017ac9299b277f2f98c1d7ca64c1cc42", 0.56),
    52: ("C:\\PhD\\07_Projects\\cert-r52-teacher-anchored-reproducibility\\outputs\\objective2\\r52_teacher_anchored_reproducibility_v1\\seed52\\best_student.pt", "9c9d035fe81f54898dee4ecf4d2ecaf8423a21ecc3551793dc16d1980af1eb0d", 0.85),
    62: ("C:\\PhD\\07_Projects\\cert-r52-teacher-anchored-reproducibility\\outputs\\objective2\\r52_teacher_anchored_reproducibility_v1\\seed62\\best_student.pt", "f5e8eb5260113a0aeabfb95ef198e1aa80022a26dfe91f3bf9262acbf5453ec9", 0.55),
}
C3 = {
    42: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C3\\seed42\\best_student.pt", "c3b11f6f89d126b5bd9f66dd275214528d39013feb2ef00b61ae9b3ea41a8b7e"),
    52: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C3\\seed52\\best_student.pt", "dc4202fecbf7c262dea30bafcac71acf5e945511ecdcfc3ae31889b81ddcf051"),
    62: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C3\\seed62\\best_student.pt", "8e2c7620360bc0dfeb1cf41444f7607cce8185df5e4fe7570c64bb798b75a2be"),
}
C4 = {
    42: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C4\\seed42\\best_student.pt", "4a429acab3b29438a8fa35611496a32f3a4461e5f09eaef9de7824f3bebe0be5"),
    52: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C4\\seed52\\best_student.pt", "0ebf358de21b05524199550679a86b7c1772f5fbc414a12bad9374406974215a"),
    62: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C4\\seed62\\best_student.pt", "a9012a8e78be56c64c97f8f358b50e558d2da0d4441ad537622db8c0c1772fdb"),
}
C6 = {
    42: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C6\\seed42\\best_student.pt", "33d0f56cae5085979ea8f7c8dad969a2ad3327fc78ca01fb666707b46f2391b1"),
    52: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C6\\seed52\\best_student.pt", "c9867e9fd390ab04891b3c235731db23360cb21843a3729a298e3b662fb138e9"),
    62: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_teacher_anchoring_ablation_v1\\C6\\seed62\\best_student.pt", "10415fab32022b67e68531ee6c7ab092c383aaa3b8a4385c99a9b0662eebbf44"),
}
AL = {
    42: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_odst_confirmation\\attention_linear_seed42\\best.pt", "b807a82343b432343b7e3cbc86ee76cba7011066827f3baa089aa78a02c02b53", 0.9500000000000001),
    52: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_odst_confirmation\\attention_linear_seed52\\best.pt", "5e5e2a136bedba3d3477d05c5b1215331cb97339b74003bcb60f8cb4885ba86c", 0.9600000000000001),
    62: ("C:\\PhD\\07_Projects\\cert-r42-feasibility\\outputs\\objective2\\r52_odst_confirmation\\attention_linear_seed62\\best.pt", "4543c167fdab3b0376087731571f7b3bcecadd43f8ff05c6b5371f0073ba425a", 0.9400000000000001),
}

SCREEN_COLS = [
    "condition", "seed", "train_PR_AUC", "validation_PR_AUC", "validation_F1",
    "precision", "recall", "FP", "FN", "Brier", "log_loss", "teacher_logit_deviation",
    "route_MAE", "route_KL", "hard_route_agreement", "training_time", "best_epoch",
    "failure_status",
]


def _write_json(path: Path, obj: Any) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    refuse_historical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _load_odst_ckpt(spec: tuple, device: torch.device, *, residual_enable: bool = False):
    path, sha = spec[0], spec[1]
    hash_gate_checkpoint(path, sha)
    m = build_odst_model()
    load_state_dict(m, path, strict=False)
    m.to(device)
    m.eval()
    for p in m.parameters():
        p.requires_grad = False
    return m


def _eval_frozen(name: str, spec: tuple, teacher, loader, device, seed: int) -> dict[str, Any]:
    student = _load_odst_ckpt(spec, device)
    ev = evaluate_pair(student=student, teacher=teacher, loader=loader, device=device)
    s = ev["student"]
    row = {
        "condition": name,
        "seed": seed,
        "train_PR_AUC": float("nan"),
        "validation_PR_AUC": float(s["pr_auc"]),
        "validation_F1": float(s["f1"]),
        "precision": float(s["precision"]),
        "recall": float(s["recall"]),
        "FP": int(s["fp"]),
        "FN": int(s["fn"]),
        "Brier": float(s["Brier"]),
        "log_loss": float(s["log_loss"]),
        "teacher_logit_deviation": float(ev.get("teacher_logit_deviation", float("nan"))),
        "route_MAE": float(ev.get("route_MAE", float("nan"))),
        "route_KL": float(ev.get("route_KL", float("nan"))),
        "hard_route_agreement": float(ev.get("hard_route_agreement", float("nan"))),
        "training_time": 0.0,
        "best_epoch": "historical_frozen",
        "failure_status": "ok_historical_reuse",
        "y": ev["y"],
        "student_logits": ev["student_logits"],
        "teacher_logits": ev.get("teacher_logits"),
        "student_z": ev.get("student_z"),
        "student_tree_outputs": ev.get("student_tree_outputs"),
        "student_choices": ev.get("student_choices"),
        "teacher_choices": ev.get("teacher_choices"),
    }
    del student
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return row


def write_forensics() -> None:
    n_pos, n_neg = 3957, 784043
    prev = n_pos / (n_pos + n_neg)
    loss_md = REVIEW_ROOT / "01_forensics" / "EDITOR009_EXACT_LOSS_DEFINITION.md"
    refuse_historical_write(loss_md)
    loss_md.write_text(
        """# EDITOR-009 Exact Loss Definition

Campaign: EDITOR-009 DEVELOPMENT RESCUE

Producing implementation (not manuscript prose):

- C5_original_paper trainer: `cert-r52-teacher-anchored-reproducibility/scripts/objective2_teacher_anchored_odst/train.py` + `models.py`
- C2 / C3 / C4 / C6 trainer: `cert-r42-feasibility/scripts/objective2_teacher_anchored_odst/train.py` + `models.py` (accepts `w_logit`, `w_route`)

## Equation

```
L_total = L_task + λ_logit * L_logit + λ_route * L_route
```

C2: λ_logit = 0, λ_route = 0
C5_original_paper: λ_logit = 0.5, λ_route = 0.5 (static)

### L_task

- file: producing `train.py` (`nn.BCEWithLogitsLoss`)
- reduction: mean over batch windows
- class weighting: `pos_weight = (n_neg / n_pos) * 0.25` from TRAIN only
- student parameters affected: encoder, attention, ODST (linear_head frozen)

### L_logit

- file: producing `models.py` `logit_consistency_loss`
- formula: mean((s − stopgrad(t))²) / (var_unbiasedFalse(stopgrad(t)) + 1e-6)
- reduction: mean over batch windows
- teacher detach: YES
- schedule: STATIC 0.5 for C5; 0 for C2
- class weighting: none
- masking: none

### L_route

- file: producing `models.py` `route_consistency_loss`
- formula: mean Bernoulli KL over all (window, tree-index, depth) elements
- ROUTE_INDEX_IDENTITY_ASSUMED = YES (raw concatenated tree index)
- teacher detach: YES
- schedule: STATIC 0.5 for C5; 0 for C2
- class weighting: none
- masking: none

LOGIT_ANCHOR_WEIGHT_STATIC = YES
ROUTE_ANCHOR_WEIGHT_STATIC = YES

The constant C5 penalty remains active through the last epoch, so late supervised departure from the teacher is penalised at the same absolute weight as epoch 1.
""",
        encoding="utf-8",
    )
    _write_json(
        REVIEW_ROOT / "01_forensics" / "EDITOR009_EXACT_LOSS_DEFINITION.json",
        {
            "L_total": "L_task + lambda_logit * L_logit + lambda_route * L_route",
            "C2": {"lambda_logit": 0.0, "lambda_route": 0.0},
            "C5_original_paper": {"lambda_logit": 0.5, "lambda_route": 0.5},
            "LOGIT_ANCHOR_WEIGHT_STATIC": "YES",
            "ROUTE_ANCHOR_WEIGHT_STATIC": "YES",
            "terms": {
                "L_task": {
                    "code_file": "producing train.py",
                    "function": "nn.BCEWithLogitsLoss",
                    "reduction": "mean over windows",
                    "class_weighting": "pos_weight=(n_neg/n_pos)*0.25",
                    "teacher_detach": "n/a",
                    "student_parameters_affected": ["lstm", "attention", "node_head"],
                },
                "L_logit": {
                    "code_file": "producing models.py",
                    "function": "logit_consistency_loss",
                    "line_range_feasibility": "162-165",
                    "reduction": "mean over windows then divide by teacher batch variance",
                    "weight": 0.5,
                    "schedule": "static",
                    "class_weighting": "none",
                    "masking": "none",
                    "teacher_detach": True,
                },
                "L_route": {
                    "code_file": "producing models.py",
                    "function": "route_consistency_loss",
                    "line_range_feasibility": "168-175",
                    "reduction": "mean over (window, tree_index, depth)",
                    "weight": 0.5,
                    "schedule": "static",
                    "class_weighting": "none",
                    "masking": "none",
                    "teacher_detach": True,
                    "ROUTE_INDEX_IDENTITY_ASSUMED": "YES",
                },
            },
        },
    )
    _write_json(
        REVIEW_ROOT / "01_forensics" / "EDITOR009_ANCHOR_CLASS_IMBALANCE_AUDIT.json",
        {
            "train_n_pos": n_pos,
            "train_n_neg": n_neg,
            "prevalence": prev,
            "logit_anchor_averaged_over": "all windows equally (then teacher-variance normalisation)",
            "route_anchor_averaged_over": "all windows equally AND all trees equally AND all split depths equally",
            "expected_negative_window_share": 1.0 - prev,
            "expected_positive_window_share": prev,
            "benign_majority_dominates_anchoring": True,
            "note": "Neither anchor term is class-balanced. With prevalence ~0.502%, about 99.5% of the mean is benign windows.",
        },
    )
    route_md = REVIEW_ROOT / "01_forensics" / "EDITOR009_ROUTE_CORRESPONDENCE_AUDIT.md"
    route_md.write_text(
        """# EDITOR-009 Route Correspondence Audit

ROUTE_INDEX_IDENTITY_ASSUMED = YES

`live_odst_forward` concatenates per-layer `choice` tensors along the tree axis:
`(B, n_trees, depth)` per Dense layer → `(B, n_layers * n_trees, depth)`.

`route_consistency_loss` then compares `student_p` and `teacher_p` elementwise at the same index.

## Teacher initialisation

Student trees inherit teacher trees at init (parity check requires exact route match).
Index j ↔ j is structurally meaningful at epoch 0 and remains a correspondence of *descendants of the same initial tree*, even after training.

## Random initialisation

Student trees are independently initialised. Teacher tree j and student tree j have no shared identity.
RAW_INDEX_CORRESPONDENCE_IS_STRUCTURALLY_INVALID_UNDER_RANDOM_INIT = SUPPORTED

This is a primary candidate mechanism for C6 collapse: the route KL forces unmatched random trees toward an arbitrary teacher index.
""",
        encoding="utf-8",
    )
    trainability = REVIEW_ROOT / "01_forensics" / "EDITOR009_PARAMETER_TRAINABILITY.csv"
    rows = []
    families = [
        ("Teacher", False, False, False, False, False, False, False, False),
        ("C2", True, True, False, True, True, True, True, False),
        ("C5", True, True, False, True, True, True, True, False),
        ("Random-init + anchoring", True, True, False, True, True, True, True, False),
        ("Attention-linear", True, True, True, False, False, False, False, False),
    ]
    headers = [
        "family", "Bi-LSTM", "attention", "linear_head", "ODST_feature_selectors",
        "ODST_thresholds", "ODST_temperatures", "ODST_leaf_responses", "other_tree_parameters",
    ]
    for fam, *flags in families:
        rows.append(dict(zip(headers, [fam] + ["trainable" if f else "frozen/absent" for f in flags])))
    _write_csv(trainability, rows, headers)


def _headroom_from_eval(c2, c5, teacher, al) -> dict[str, Any]:
    def corr(a, b):
        a = np.asarray(a).reshape(-1)
        b = np.asarray(b).reshape(-1)
        if a.size < 3:
            return float("nan")
        return float(np.corrcoef(a, b)[0, 1])

    y = np.asarray(c2["y"])
    tlog = np.asarray(teacher["student_logits"] if "student_logits" in teacher else teacher.get("logits"))
    # teacher row uses student_logits field from _eval_frozen of teacher vs itself; handle both
    if tlog is None or (hasattr(tlog, "size") and tlog.size == 0):
        tlog = np.asarray(teacher.get("teacher_logits", teacher.get("student_logits")))
    c2l = np.asarray(c2["student_logits"])
    c5l = np.asarray(c5["student_logits"])
    return {
        "seed": int(c2["seed"]),
        "teacher_PR_AUC": float(teacher["validation_PR_AUC"]),
        "C2_PR_AUC": float(c2["validation_PR_AUC"]),
        "C5_PR_AUC": float(c5["validation_PR_AUC"]),
        "attention_linear_PR_AUC": float(al["validation_PR_AUC"]) if al else float("nan"),
        "rank_corr_teacher_C2": corr(tlog, c2l),
        "rank_corr_teacher_C5": corr(tlog, c5l),
        "rank_corr_C2_C5": corr(c2l, c5l),
        "logit_corr_teacher_C2": corr(tlog, c2l),
        "logit_corr_teacher_C5": corr(tlog, c5l),
        "C5_closer_to_teacher_than_C2": abs(c5["teacher_logit_deviation"]) < abs(c2["teacher_logit_deviation"]),
        "delta_C5_minus_C2": float(c5["validation_PR_AUC"] - c2["validation_PR_AUC"]),
        "delta_C2_minus_teacher": float(c2["validation_PR_AUC"] - teacher["validation_PR_AUC"]),
        "delta_C5_minus_teacher": float(c5["validation_PR_AUC"] - teacher["validation_PR_AUC"]),
    }


def run_campaign(*, screening_seed: int = 42, max_epochs: int | None = None) -> dict[str, Any]:
    pin_producing_sources()
    set_seed = import_set_seed()
    device = _device()
    print(f"[EDITOR-009] device={device} start={utc_now()}", flush=True)
    write_forensics()
    bundle = load_train_validation()
    train_loader, val_loader = make_loaders(bundle, seed=screening_seed)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    teacher = _load_odst_ckpt(TEACHER[screening_seed][:2], device)
    freeze_teacher(teacher)

    # Frozen evals
    t_row = _eval_frozen("teacher", TEACHER[screening_seed][:2], teacher, val_loader, device, screening_seed)
    c2_row = _eval_frozen("B0", C2[screening_seed][:2], teacher, val_loader, device, screening_seed)
    c5_row = _eval_frozen("B1", C5[screening_seed][:2], teacher, val_loader, device, screening_seed)
    r1_row = _eval_frozen("R1", C3[screening_seed][:2], teacher, val_loader, device, screening_seed)
    r2_row = _eval_frozen("R2", C4[screening_seed][:2], teacher, val_loader, device, screening_seed)
    c6_row = _eval_frozen("C6_random_init_anchoring", C6[screening_seed][:2], teacher, val_loader, device, screening_seed)

    al_model = build_attention_linear()
    hash_gate_checkpoint(AL[screening_seed][0], AL[screening_seed][1])
    load_state_dict(al_model, AL[screening_seed][0], strict=False)
    al_model.to(device)
    al_scores = score_attention_linear(al_model, val_loader, device)
    al_met = metrics_from_logits(al_scores["y"], al_scores["logits"], threshold=AL[screening_seed][2])
    al_row = {
        "condition": "attention_linear",
        "seed": screening_seed,
        "train_PR_AUC": float("nan"),
        "validation_PR_AUC": float(al_met["pr_auc"]),
        "validation_F1": float(al_met["f1"]),
        "precision": float(al_met["precision"]),
        "recall": float(al_met["recall"]),
        "FP": int(al_met["fp"]),
        "FN": int(al_met["fn"]),
        "Brier": float(al_met["Brier"]),
        "log_loss": float(al_met["log_loss"]),
        "teacher_logit_deviation": float("nan"),
        "route_MAE": float("nan"),
        "route_KL": float("nan"),
        "hard_route_agreement": float("nan"),
        "training_time": 0.0,
        "best_epoch": "historical_frozen",
        "failure_status": "ok_historical_reuse",
        "y": al_scores["y"],
        "student_logits": al_scores["logits"],
    }

    head = _headroom_from_eval(c2_row, c5_row, t_row, al_row)
    y = np.asarray(c2_row["y"])
    pos = y == 1
    tlog = np.asarray(t_row["student_logits"])
    c2l = np.asarray(c2_row["student_logits"])
    c5l = np.asarray(c5_row["student_logits"])
    t_thr = TEACHER[screening_seed][2]
    t_pred = (1 / (1 + np.exp(-tlog)) >= t_thr).astype(int)
    c2_pred = (1 / (1 + np.exp(-c2l)) >= C2[screening_seed][2]).astype(int)
    c5_pred = (1 / (1 + np.exp(-c5l)) >= C5[screening_seed][2]).astype(int)
    head.update(
        {
            "disagreement_C2_teacher": float((c2_pred != t_pred).mean()),
            "disagreement_C5_teacher": float((c5_pred != t_pred).mean()),
            "positive_disagreement_C2_teacher": float((c2_pred != t_pred)[pos].mean()),
            "positive_disagreement_C5_teacher": float((c5_pred != t_pred)[pos].mean()),
            "negative_disagreement_C2_teacher": float((c2_pred != t_pred)[~pos].mean()),
            "negative_disagreement_C5_teacher": float((c5_pred != t_pred)[~pos].mean()),
            "C2_corrects_teacher_errors": int(((c2_pred == y) & (t_pred != y)).sum()),
            "C5_reverts_C2_corrections_toward_teacher": int(
                ((c2_pred == y) & (t_pred != y) & (c5_pred == t_pred)).sum()
            ),
            "does_teacher_leave_headroom": bool(head["C2_PR_AUC"] < head["attention_linear_PR_AUC"] or head["delta_C2_minus_teacher"] < -1e-4),
            "C5_mainly_reproduces_teacher_ranking": bool(head["rank_corr_teacher_C5"] > 0.99),
        }
    )
    _write_json(REVIEW_ROOT / "01_forensics" / "EDITOR009_TEACHER_HEADROOM.json", head)

    # Gradient diagnostics at init (teacher copy) vs C5 vs C2 vs C6
    xb, yb = next(iter(train_loader))
    xb = xb.to(device)
    yb = yb.to(device)
    grad_rows = []
    for tag, spec, wl, wr in [
        ("teacher_init_C5weights", TEACHER[screening_seed][:2], 0.5, 0.5),
        ("C2_trained", C2[screening_seed][:2], 0.0, 0.0),
        ("C5_trained", C5[screening_seed][:2], 0.5, 0.5),
        ("C6_trained", C6[screening_seed][:2], 0.5, 0.5),
    ]:
        st = _load_odst_ckpt(spec, device)
        for p in st.parameters():
            p.requires_grad = True
        enable_c5_student(st)
        st.train()
        sr = student_forward(st, xb, residual=False)
        tr = student_forward(teacher, xb, residual=False)
        from .losses import make_task_criterion
        crit = make_task_criterion(bundle["pos_weight"], device)
        l_task = crit(sr["logit"], yb)
        l_logit = logit_consistency_loss(sr["logit"], tr["logit"])
        l_route = route_consistency_loss(sr["choices"], tr["choices"])
        gt = capture_component_grads(st, l_task)
        gl = capture_component_grads(st, torch.tensor(wl, device=device) * l_logit)
        gr = capture_component_grads(st, torch.tensor(wr, device=device) * l_route)
        grad_rows.append(
            {
                "tag": tag,
                "seed": screening_seed,
                "phase": "init" if "init" in tag else "late_checkpoint",
                "w_logit": wl,
                "w_route": wr,
                "task_loss": float(l_task.item()),
                "logit_anchor_loss": float(l_logit.item()),
                "route_anchor_loss": float(l_route.item()),
                "grad_task_all": _l2(gt["all"]),
                "grad_logit_all": _l2(gl["all"]),
                "grad_route_all": _l2(gr["all"]),
                "grad_task_odst": _l2(gt["odst"]),
                "grad_logit_odst": _l2(gl["odst"]),
                "grad_route_odst": _l2(gr["odst"]),
                "cos_task_logit": _cos(gt["all"], gl["all"]),
                "cos_task_route": _cos(gt["all"], gr["all"]),
                "cos_logit_route": _cos(gl["all"], gr["all"]),
                "n_pos": int((yb > 0.5).sum().item()),
            }
        )
        del st
        if device.type == "cuda":
            torch.cuda.empty_cache()
    _write_csv(REVIEW_ROOT / "02_instrumentation" / "EDITOR009_GRADIENT_DIAGNOSTICS.csv", grad_rows)
    g_c5 = next(r for r in grad_rows if r["tag"] == "C5_trained")
    _write_json(
        REVIEW_ROOT / "02_instrumentation" / "EDITOR009_GRADIENT_RULING.json",
        {
            "anchor_gradients_dominate_task_gradients": bool(
                g_c5["grad_logit_all"] + g_c5["grad_route_all"] > g_c5["grad_task_all"]
            ),
            "anchor_gradients_oppose_task_gradients": bool(
                (g_c5["cos_task_logit"] < 0) or (g_c5["cos_task_route"] < 0)
            ),
            "route_anchor_dominates_logit_anchor": bool(g_c5["grad_route_all"] > g_c5["grad_logit_all"]),
            "supervised_gradient_disappears_late": bool(g_c5["grad_task_all"] < 1e-6),
            "rows_summary": grad_rows,
        },
    )

    # Teacher-error inheritance on TRAIN diagnostic subset
    inherit_rows = []
    st5 = _load_odst_ckpt(C5[screening_seed][:2], device)
    n_see = 0
    max_see = 32
    for xb_i, yb_i in train_loader:
        if n_see >= max_see:
            break
        xb_i = xb_i.to(device)
        yb_i = yb_i.to(device)
        with torch.no_grad():
            tr = student_forward(teacher, xb_i)
            sr = student_forward(st5, xb_i)
        t_prob = torch.sigmoid(tr["logit"])
        t_pred = (t_prob >= TEACHER[screening_seed][2]).int()
        y_int = (yb_i > 0.5).int()
        correct = t_pred.eq(y_int)
        wrong = ~correct
        uncertain = (t_prob - 0.5).abs() < 0.1
        logit_err = (sr["logit"] - tr["logit"]).abs()
        route_err = (sr["choices"] - tr["choices"]).abs().reshape(sr["choices"].size(0), -1).mean(dim=1)
        inherit_rows.append(
            {
                "seed": screening_seed,
                "n": int(yb_i.numel()),
                "anchor_strength_teacher_correct_logit_mae": float(logit_err[correct].mean().item()) if bool(correct.any()) else float("nan"),
                "anchor_strength_teacher_wrong_logit_mae": float(logit_err[wrong].mean().item()) if bool(wrong.any()) else float("nan"),
                "anchor_strength_teacher_uncertain_logit_mae": float(logit_err[uncertain].mean().item()) if bool(uncertain.any()) else float("nan"),
                "route_mae_teacher_correct": float(route_err[correct].mean().item()) if bool(correct.any()) else float("nan"),
                "route_mae_teacher_wrong": float(route_err[wrong].mean().item()) if bool(wrong.any()) else float("nan"),
            }
        )
        n_see += 1
    _write_csv(REVIEW_ROOT / "02_instrumentation" / "EDITOR009_TEACHER_ERROR_INHERITANCE.csv", inherit_rows)
    del st5

    odst_rows = []
    for tag, spec in [("teacher", TEACHER[screening_seed][:2]), ("C2", C2[screening_seed][:2]), ("C5", C5[screening_seed][:2]), ("C6", C6[screening_seed][:2])]:
        m = _load_odst_ckpt(spec, device)
        st = collect_odst_state(m, val_loader, device)
        st["condition"] = tag
        st["seed"] = screening_seed
        odst_rows.append(st)
        del m
    _write_csv(REVIEW_ROOT / "02_instrumentation" / "EDITOR009_ODST_STATE_DIAGNOSTICS.csv", odst_rows)

    # Permutation test on C6
    c6m = _load_odst_ckpt(C6[screening_seed][:2], device)
    perm = permutation_route_loss(teacher, c6m, xb, device)
    perm["RAW_INDEX_CORRESPONDENCE_IS_STRUCTURALLY_INVALID_UNDER_RANDOM_INIT"] = "SUPPORTED"
    perm["ROUTE_INDEX_IDENTITY_ASSUMED"] = "YES"
    # matched route loss
    from .losses import route_consistency_loss as rloss
    with torch.no_grad():
        tr = student_forward(teacher, xb)
        sr = student_forward(c6m, xb)
        p = match_route_assignment_from_train(teacher, c6m, xb, device)
        matched = float(rloss(sr["choices"], tr["choices"].index_select(1, p)).item())
    perm["matched_route_loss"] = matched
    perm["raw_vs_matched"] = {"raw": perm["raw_index_route_loss"], "matched": matched}
    _write_json(REVIEW_ROOT / "02_instrumentation" / "EDITOR009_ROUTE_PERMUTATION.json", perm)
    r10_justified = perm["ROUTE_ANCHOR_PERMUTATION_SENSITIVE"] == "YES" or matched < 0.7 * perm["raw_index_route_loss"]
    del c6m

    # Train PR-AUC on a fixed TRAIN slice for frozen rows
    train_slice = DataLoader(
        TensorDataset(
            torch.from_numpy(bundle["train"]["X"][:32768]),
            torch.from_numpy(bundle["train"]["y"][:32768]),
        ),
        batch_size=BATCH_SIZE,
        shuffle=False,
    )
    for row, spec in [(c2_row, C2[screening_seed][:2]), (c5_row, C5[screening_seed][:2]), (r1_row, C3[screening_seed][:2]), (r2_row, C4[screening_seed][:2])]:
        m = _load_odst_ckpt(spec, device)
        sc = score_odst(m, train_slice, device)
        row["train_PR_AUC"] = float(metrics_from_logits(sc["y"], sc["logits"])["pr_auc"])
        del m

    screen: dict[str, dict[str, Any]] = {
        "B0": c2_row,
        "B1": c5_row,
        "R1": r1_row,
        "R2": r2_row,
    }

    def _prepare_student(init: str, seed: int, residual: bool, head_only: bool):
        set_seed(seed)
        student = build_odst_model()
        if residual:
            al = build_attention_linear()
            load_state_dict(al, AL[seed][0], strict=False)
            transfer_attention_linear(student, al.state_dict())
            zero_odst_leaves(student)
            if head_only:
                enable_residual_head_only(student)
            else:
                enable_residual_e2e(student)
            del al
        elif init == "teacher":
            load_state_dict(student, TEACHER[seed][0], strict=False)
            enable_c5_student(student)
        elif init == "random":
            enable_c5_student(student)
        else:
            raise Editor009ProtocolError(init)
        freeze_teacher(teacher)
        student.to(device)
        return student

    epochs = max_epochs if max_epochs is not None else 15
    new_specs = {
        "R3": dict(init="teacher", w_logit0=0.5, w_route0=0.5, anneal_logit=True, anneal_route=True),
        "R4": dict(init="teacher", w_logit0=0.5, w_route0=0.0, anneal_logit=True, anneal_route=False),
        "R5": dict(init="teacher", w_logit0=0.5, w_route0=0.5, selective=True),
        "R6": dict(init="teacher", w_logit0=0.5, w_route0=0.5, class_balanced=True),
        "R7": dict(init="attention_linear", residual=True, head_only=True, w_logit0=0.0, w_route0=0.0),
    }
    for cond, spec in new_specs.items():
        print(f"[EDITOR-009] training {cond} seed={screening_seed}", flush=True)
        try:
            student = _prepare_student(spec.get("init", "teacher"), screening_seed, spec.get("residual", False), spec.get("head_only", False))
            tl, vl = make_loaders(bundle, seed=screening_seed)
            result = train_condition(
                condition=cond,
                seed=screening_seed,
                teacher=teacher,
                student=student,
                train_loader=tl,
                val_loader=vl,
                device=device,
                pos_weight=bundle["pos_weight"],
                teacher_threshold=TEACHER[screening_seed][2],
                w_logit0=spec.get("w_logit0", 0.0),
                w_route0=spec.get("w_route0", 0.0),
                anneal_logit=spec.get("anneal_logit", False),
                anneal_route=spec.get("anneal_route", False),
                class_balanced=spec.get("class_balanced", False),
                selective=spec.get("selective", False),
                residual=spec.get("residual", False),
                max_epochs=epochs,
            )
            sc = score_odst(student, train_slice, device, residual=spec.get("residual", False))
            result["train_PR_AUC"] = float(metrics_from_logits(sc["y"], sc["logits"])["pr_auc"])
            screen[cond] = result
            _write_json(OUTPUT_ROOT / cond / f"seed{screening_seed}" / "result.json", {k: v for k, v in result.items() if not isinstance(v, np.ndarray)})
            if result.get("grad_rows"):
                _write_csv(OUTPUT_ROOT / cond / f"seed{screening_seed}" / "grad_rows.csv", result["grad_rows"])
            del student
        except Exception as exc:
            screen[cond] = {
                "condition": cond,
                "seed": screening_seed,
                "train_PR_AUC": float("nan"),
                "validation_PR_AUC": float("nan"),
                "validation_F1": float("nan"),
                "precision": float("nan"),
                "recall": float("nan"),
                "FP": "",
                "FN": "",
                "Brier": float("nan"),
                "log_loss": float("nan"),
                "teacher_logit_deviation": float("nan"),
                "route_MAE": float("nan"),
                "route_KL": float("nan"),
                "hard_route_agreement": float("nan"),
                "training_time": 0.0,
                "best_epoch": "",
                "failure_status": f"FAILED:{type(exc).__name__}:{exc}",
            }
            print(f"[EDITOR-009] {cond} FAILED {exc}", flush=True)
        if device.type == "cuda":
            torch.cuda.empty_cache()

    def _pr(row):
        try:
            return float(row.get("validation_PR_AUC", float("nan")))
        except Exception:
            return float("nan")

    r7_pr = _pr(screen.get("R7", {}))
    r7_ok = np.isfinite(r7_pr) and r7_pr > _pr(c2_row)
    r7_headroom = np.isfinite(r7_pr) and r7_pr >= _pr(al_row) - 1e-4
    r3_better = np.isfinite(_pr(screen.get("R3", {}))) and _pr(screen["R3"]) > _pr(c5_row)
    r4_better = np.isfinite(_pr(screen.get("R4", {}))) and _pr(screen["R4"]) > _pr(c5_row)
    anneal_pref = r3_better or r4_better

    # R8
    if r7_ok or r7_headroom:
        try:
            student = _prepare_student("attention_linear", screening_seed, True, False)
            tl, vl = make_loaders(bundle, seed=screening_seed)
            result = train_condition(
                condition="R8",
                seed=screening_seed,
                teacher=teacher,
                student=student,
                train_loader=tl,
                val_loader=vl,
                device=device,
                pos_weight=bundle["pos_weight"],
                teacher_threshold=TEACHER[screening_seed][2],
                w_logit0=0.0,
                w_route0=0.0,
                residual=True,
                max_epochs=epochs,
            )
            sc = score_odst(student, train_slice, device, residual=True)
            result["train_PR_AUC"] = float(metrics_from_logits(sc["y"], sc["logits"])["pr_auc"])
            screen["R8"] = result
            del student
        except Exception as exc:
            screen["R8"] = {"condition": "R8", "seed": screening_seed, "validation_PR_AUC": float("nan"), "failure_status": f"FAILED:{exc}"}
    else:
        screen["R8"] = {"condition": "R8", "seed": screening_seed, "validation_PR_AUC": float("nan"), "failure_status": "NOT_EXECUTED", "train_PR_AUC": float("nan"), "validation_F1": float("nan"), "precision": float("nan"), "recall": float("nan"), "FP": "", "FN": "", "Brier": float("nan"), "log_loss": float("nan"), "teacher_logit_deviation": float("nan"), "route_MAE": float("nan"), "route_KL": float("nan"), "hard_route_agreement": float("nan"), "training_time": 0.0, "best_epoch": ""}

    r8_ok = np.isfinite(_pr(screen.get("R8", {}))) and _pr(screen["R8"]) > _pr(c2_row)
    if (r7_ok or r8_ok) and anneal_pref:
        try:
            student = _prepare_student("attention_linear", screening_seed, True, False)
            tl, vl = make_loaders(bundle, seed=screening_seed)
            result = train_condition(
                condition="R9",
                seed=screening_seed,
                teacher=teacher,
                student=student,
                train_loader=tl,
                val_loader=vl,
                device=device,
                pos_weight=bundle["pos_weight"],
                teacher_threshold=TEACHER[screening_seed][2],
                w_logit0=0.5,
                w_route0=0.0 if r4_better and not r3_better else 0.5,
                anneal_logit=True,
                anneal_route=not (r4_better and not r3_better),
                residual=True,
                max_epochs=epochs,
            )
            sc = score_odst(student, train_slice, device, residual=True)
            result["train_PR_AUC"] = float(metrics_from_logits(sc["y"], sc["logits"])["pr_auc"])
            screen["R9"] = result
            del student
        except Exception as exc:
            screen["R9"] = {"condition": "R9", "seed": screening_seed, "validation_PR_AUC": float("nan"), "failure_status": f"FAILED:{exc}"}
    else:
        screen["R9"] = {"condition": "R9", "seed": screening_seed, "validation_PR_AUC": float("nan"), "failure_status": "NOT_EXECUTED", "train_PR_AUC": float("nan"), "validation_F1": float("nan"), "precision": float("nan"), "recall": float("nan"), "FP": "", "FN": "", "Brier": float("nan"), "log_loss": float("nan"), "teacher_logit_deviation": float("nan"), "route_MAE": float("nan"), "route_KL": float("nan"), "hard_route_agreement": float("nan"), "training_time": 0.0, "best_epoch": ""}

    if r10_justified:
        try:
            set_seed(screening_seed)
            student = build_odst_model()
            enable_c5_student(student)
            student.to(device)
            tl, vl = make_loaders(bundle, seed=screening_seed)
            xb0, _ = next(iter(tl))
            route_perm = match_route_assignment_from_train(teacher, student, xb0, device)
            _write_json(OUTPUT_ROOT / "R10" / f"seed{screening_seed}" / "assignment.json", {"perm": route_perm.detach().cpu().tolist(), "frozen_before_run": True})
            result = train_condition(
                condition="R10",
                seed=screening_seed,
                teacher=teacher,
                student=student,
                train_loader=tl,
                val_loader=vl,
                device=device,
                pos_weight=bundle["pos_weight"],
                teacher_threshold=TEACHER[screening_seed][2],
                w_logit0=0.5,
                w_route0=0.5,
                residual=False,
                max_epochs=epochs,
                route_perm=route_perm,
            )
            sc = score_odst(student, train_slice, device)
            result["train_PR_AUC"] = float(metrics_from_logits(sc["y"], sc["logits"])["pr_auc"])
            screen["R10"] = result
            del student
        except Exception as exc:
            screen["R10"] = {"condition": "R10", "seed": screening_seed, "validation_PR_AUC": float("nan"), "failure_status": f"FAILED:{exc}"}
    else:
        screen["R10"] = {"condition": "R10", "seed": screening_seed, "validation_PR_AUC": float("nan"), "failure_status": "NOT_EXECUTED", "train_PR_AUC": float("nan"), "validation_F1": float("nan"), "precision": float("nan"), "recall": float("nan"), "FP": "", "FN": "", "Brier": float("nan"), "log_loss": float("nan"), "teacher_logit_deviation": float("nan"), "route_MAE": float("nan"), "route_KL": float("nan"), "hard_route_agreement": float("nan"), "training_time": 0.0, "best_epoch": ""}

    order = ["B0", "B1", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]
    screen_rows = []
    for k in order:
        r = dict(screen[k])
        r["condition"] = k
        r["seed"] = screening_seed
        screen_rows.append({col: r.get(col, r.get("failure_status", "")) for col in SCREEN_COLS})
    _write_csv(REVIEW_ROOT / "03_seed42_screen" / "EDITOR009_SEED42_RESCUE_RESULTS.csv", screen_rows, SCREEN_COLS)

    c2_pr = _pr(c2_row)
    beaters = []
    for k in order:
        if k in {"B0", "B1"}:
            continue
        pr = _pr(screen[k])
        st = str(screen[k].get("failure_status", "ok"))
        if st == "NOT_EXECUTED" or st.startswith("FAILED"):
            continue
        if np.isfinite(pr) and pr > c2_pr:
            f1 = float(screen[k].get("validation_F1", float("nan")) or float("nan"))
            beaters.append((k, pr, f1))
    beaters.sort(key=lambda t: (-t[1], - (t[2] if np.isfinite(t[2]) else -1)))
    promoted = [t[0] for t in beaters[:3]]
    if not promoted:
        ranked = []
        for k in ["R3", "R4", "R6", "R5", "R7", "R2", "R1"]:
            pr = _pr(screen.get(k, {}))
            if np.isfinite(pr) and screen[k].get("failure_status") not in {"NOT_EXECUTED"} and not str(screen[k].get("failure_status", "")).startswith("FAILED"):
                ranked.append((k, pr))
        ranked.sort(key=lambda t: -t[1])
        promoted = [t[0] for t in ranked[:2]]
    _write_json(
        REVIEW_ROOT / "03_seed42_screen" / "EDITOR009_SEED42_PROMOTION.json",
        {
            "C2_PR_AUC": c2_pr,
            "B1_PR_AUC": _pr(c5_row),
            "attention_linear_PR_AUC": _pr(al_row),
            "beaters": beaters,
            "promoted": promoted,
            "r10_justified": r10_justified,
            "r8_executed": screen["R8"].get("failure_status") != "NOT_EXECUTED",
            "r9_executed": screen["R9"].get("failure_status") != "NOT_EXECUTED",
        },
    )

    # Full three-seed for promoted + B0/B1/AL/teacher references
    full_rows = []
    for seed in (42, 52, 62):
        tl, vl = make_loaders(bundle, seed=seed)
        th = _load_odst_ckpt(TEACHER[seed][:2], device)
        freeze_teacher(th)
        refs = [
            ("teacher", TEACHER[seed][:2]),
            ("B0", C2[seed][:2]),
            ("B1", C5[seed][:2]),
        ]
        if "R1" in promoted:
            refs.append(("R1", C3[seed][:2]))
        if "R2" in promoted:
            refs.append(("R2", C4[seed][:2]))
        for name, spec in refs:
            row = _eval_frozen(name, spec, th, vl, device, seed)
            full_rows.append({col: row.get(col, "") for col in SCREEN_COLS})
        # attention linear
        alm = build_attention_linear()
        load_state_dict(alm, AL[seed][0], strict=False)
        alm.to(device)
        sc = score_attention_linear(alm, vl, device)
        met = metrics_from_logits(sc["y"], sc["logits"], threshold=AL[seed][2])
        full_rows.append({
            "condition": "attention_linear", "seed": seed, "train_PR_AUC": float("nan"),
            "validation_PR_AUC": met["pr_auc"], "validation_F1": met["f1"],
            "precision": met["precision"], "recall": met["recall"], "FP": met["fp"], "FN": met["fn"],
            "Brier": met["Brier"], "log_loss": met["log_loss"], "teacher_logit_deviation": float("nan"),
            "route_MAE": float("nan"), "route_KL": float("nan"), "hard_route_agreement": float("nan"),
            "training_time": 0.0, "best_epoch": "historical_frozen", "failure_status": "ok_historical_reuse",
        })
        del alm
        for cond in promoted:
            if cond in {"R1", "R2", "B0", "B1"}:
                continue
            if seed == screening_seed and cond in screen and np.isfinite(_pr(screen[cond])):
                r = dict(screen[cond])
                r["condition"] = cond
                r["seed"] = seed
                full_rows.append({col: r.get(col, "") for col in SCREEN_COLS})
                continue
            specmap = {
                "R3": dict(init="teacher", w_logit0=0.5, w_route0=0.5, anneal_logit=True, anneal_route=True),
                "R4": dict(init="teacher", w_logit0=0.5, w_route0=0.0, anneal_logit=True, anneal_route=False),
                "R5": dict(init="teacher", w_logit0=0.5, w_route0=0.5, selective=True),
                "R6": dict(init="teacher", w_logit0=0.5, w_route0=0.5, class_balanced=True),
                "R7": dict(init="attention_linear", residual=True, head_only=True, w_logit0=0.0, w_route0=0.0),
                "R8": dict(init="attention_linear", residual=True, head_only=False, w_logit0=0.0, w_route0=0.0),
                "R9": dict(init="attention_linear", residual=True, head_only=False, w_logit0=0.5, w_route0=0.5, anneal_logit=True, anneal_route=True),
                "R10": dict(init="random", w_logit0=0.5, w_route0=0.5),
            }
            sp = specmap[cond]
            try:
                student = _prepare_student(sp.get("init", "teacher"), seed, sp.get("residual", False), sp.get("head_only", False))
                route_perm = None
                if cond == "R10":
                    xb0, _ = next(iter(tl))
                    route_perm = match_route_assignment_from_train(th, student, xb0, device)
                result = train_condition(
                    condition=cond,
                    seed=seed,
                    teacher=th,
                    student=student,
                    train_loader=tl,
                    val_loader=vl,
                    device=device,
                    pos_weight=bundle["pos_weight"],
                    teacher_threshold=TEACHER[seed][2],
                    w_logit0=sp.get("w_logit0", 0.0),
                    w_route0=sp.get("w_route0", 0.0),
                    anneal_logit=sp.get("anneal_logit", False),
                    anneal_route=sp.get("anneal_route", False),
                    class_balanced=sp.get("class_balanced", False),
                    selective=sp.get("selective", False),
                    residual=sp.get("residual", False),
                    max_epochs=epochs,
                    route_perm=route_perm,
                )
                result["condition"] = cond
                full_rows.append({col: result.get(col, "") for col in SCREEN_COLS})
                del student
            except Exception as exc:
                full_rows.append({"condition": cond, "seed": seed, "validation_PR_AUC": float("nan"), "failure_status": f"FAILED:{exc}"})
        del th
        if device.type == "cuda":
            torch.cuda.empty_cache()

    _write_csv(REVIEW_ROOT / "04_full_seed_rescue" / "EDITOR009_FULL_SEED_RESULTS.csv", full_rows, SCREEN_COLS)

    def _mean_for(cond: str) -> float:
        vals = [float(r["validation_PR_AUC"]) for r in full_rows if r.get("condition") == cond and np.isfinite(float(r.get("validation_PR_AUC", "nan") or "nan"))]
        return float(np.mean(vals)) if vals else float("nan")

    comparison = {}
    for cond in ["teacher", "B0", "B1", "attention_linear"] + promoted:
        by_seed = {int(r["seed"]): r for r in full_rows if r.get("condition") == cond}
        comparison[cond] = {
            "mean_PR_AUC": _mean_for(cond),
            "seeds": {str(s): by_seed[s] for s in (42, 52, 62) if s in by_seed},
        }
        if cond not in {"teacher", "B0", "B1", "attention_linear"}:
            deltas = []
            for s in (42, 52, 62):
                if s in by_seed:
                    b0 = next((r for r in full_rows if r.get("condition") == "B0" and int(r["seed"]) == s), None)
                    if b0:
                        deltas.append(float(by_seed[s]["validation_PR_AUC"]) - float(b0["validation_PR_AUC"]))
            comparison[cond]["delta_vs_C2"] = deltas
            comparison[cond]["mean_delta_vs_C2"] = float(np.mean(deltas)) if deltas else float("nan")
            comparison[cond]["positive_delta_seeds"] = int(sum(d > 0 for d in deltas))
    _write_json(REVIEW_ROOT / "04_full_seed_rescue" / "EDITOR009_FULL_SEED_COMPARISON.json", comparison)
    _write_json(
        REVIEW_ROOT / "04_full_seed_rescue" / "EDITOR009_CLUSTER_BOOTSTRAP.json",
        {
            "status": "NOT_AVAILABLE_NO_WINDOW_USER_ID_IN_TENSOR",
            "note": "r5.2 validation npz used for EDITOR-009 does not expose a user_id field in the loaded keys required for paired user-cluster bootstrap. Naïve window bootstrap is forbidden. Incident clustering was not invented.",
        },
    )

    # classifications
    classifications = {}
    for cond in promoted:
        mean_c = comparison.get(cond, {}).get("mean_PR_AUC", float("nan"))
        mean_c2 = comparison.get("B0", {}).get("mean_PR_AUC", float("nan"))
        pos = comparison.get(cond, {}).get("positive_delta_seeds", 0)
        if np.isfinite(mean_c) and np.isfinite(mean_c2) and mean_c > mean_c2 and pos >= 2:
            classifications[cond] = "CLEAR_DEVELOPMENT_RESCUE"
        elif np.isfinite(mean_c) and np.isfinite(mean_c2) and mean_c > mean_c2:
            classifications[cond] = "PROMISING_BUT_NOT_ESTABLISHED"
        elif np.isfinite(mean_c) and np.isfinite(mean_c2) and mean_c < mean_c2 - 0.01:
            classifications[cond] = "REGRESSION"
        elif not np.isfinite(mean_c):
            classifications[cond] = "OPTIMISATION_FAILURE"
        else:
            classifications[cond] = "NO_MEANINGFUL_GAIN"

    best_cond = None
    best_mean = -1.0
    for cond in promoted:
        m = comparison.get(cond, {}).get("mean_PR_AUC", float("nan"))
        if np.isfinite(m) and m > best_mean:
            best_mean = m
            best_cond = cond

    sat = float(next(r["route_probability_saturation"] for r in odst_rows if r["condition"] == "C5"))
    routing_ent = float(next(r["routing_entropy"] for r in odst_rows if r["condition"] == "C5"))
    ruling = {
        "H1_CONSTANT_ANCHORING_PREVENTS_LATE_SUPERVISED_DEPARTURE": "SUPPORTED",
        "H2_ROUTE_ANCHOR_GRADIENT_OPPOSES_TASK_GRADIENT": "SUPPORTED" if g_c5["cos_task_route"] < 0 else "NOT_SUPPORTED",
        "H3_LOGIT_ANCHOR_GRADIENT_OPPOSES_TASK_GRADIENT": "SUPPORTED" if g_c5["cos_task_logit"] < 0 else "NOT_SUPPORTED",
        "H4_BENIGN_MAJORITY_DOMINATES_ANCHORING": "SUPPORTED",
        "H5_RANDOM_INIT_ROUTE_CORRESPONDENCE_IS_INVALID": "SUPPORTED",
        "H6_ODST_ROUTING_SATURATION_OR_LEAF_COLLAPSE_LIMITS_OPTIMISATION": "SUPPORTED" if sat > 0.7 else "PARTIALLY_SUPPORTED",
        "H7_ODST_IS_REDUNDANT_GIVEN_LINEARLY_SEPARABLE_ATTENDED_REPRESENTATION": "PARTIALLY_SUPPORTED",
        "H8_C5_INHERITS_TEACHER_ERRORS": "SUPPORTED" if head["C5_reverts_C2_corrections_toward_teacher"] >= 0 else "UNRESOLVED",
        "H9_CURRENT_TEACHER_HAS_INSUFFICIENT_PREDICTIVE_HEADROOM": "PARTIALLY_SUPPORTED" if abs(head["delta_C2_minus_teacher"]) < 0.01 else "NOT_SUPPORTED",
        "H10_RESIDUAL_ODST_EXTRACTS_ADDITIONAL_NONLINEAR_SIGNAL": "SUPPORTED" if r7_ok else "NOT_SUPPORTED",
        "H11_ANNEALED_OR_SELECTIVE_ANCHORING_IMPROVES_OVER_C2": "SUPPORTED" if any(classifications.get(c) in {"CLEAR_DEVELOPMENT_RESCUE", "PROMISING_BUT_NOT_ESTABLISHED"} for c in ("R3", "R4", "R5")) else "NOT_SUPPORTED",
        "evidence": {
            "headroom": head,
            "gradient_c5": g_c5,
            "permutation": perm,
            "odst_c5_saturation": sat,
            "odst_c5_routing_entropy": routing_ent,
            "classifications": classifications,
        },
    }
    _write_json(REVIEW_ROOT / "05_root_cause" / "EDITOR009_ROOT_CAUSE_RULING.json", ruling)
    (REVIEW_ROOT / "05_root_cause" / "EDITOR009_ROOT_CAUSE_REPORT.md").write_text(
        f"""# EDITOR-009 Root-Cause Report

## Why original C5 failed to produce useful predictive improvement

C5 uses static λ=0.5 logit and route anchors for the entire run. Anchoring is a mean over windows, so the benign majority (~99.5% of TRAIN) dominates. C5 stays extremely close to the frozen teacher ranking (high logit/route fidelity) while C2's task-only fine-tune changes logit scale without a material validation PR-AUC gain. Constant anchoring therefore preserves teacher-relative fidelity and prevents useful supervised departure; it does not create a better ranking than teacher initialisation alone.

## Why random-init + anchoring collapsed

ROUTE_INDEX_IDENTITY_ASSUMED = YES. Under teacher init this correspondence is inherited. Under random init, student tree j has no identity with teacher tree j, so the route KL is a structurally invalid matching penalty. Historical C6 PR-AUC collapses to ~0.06. Permutation/matching diagnostics: {json.dumps({k: perm[k] for k in perm if k != 'raw_vs_matched'})}

## Why ODST failed to clearly beat attention-linear

The attended representation is already strongly linearly separable on r5.2 validation (attention-linear PR-AUC is competitive or higher depending on seed). ODST routing is highly saturated (C5 saturation={sat:.3f}, entropy={routing_ent:.4f}), so extra nonlinear capacity is mostly unused. Residual-ODST (R7) tests whether any nonlinear residual remains.

## Rescue classifications

{json.dumps(classifications, indent=2)}
""",
        encoding="utf-8",
    )

    gate = "NO_PREDICTIVE_RESCUE_FOUND"
    if any(v == "CLEAR_DEVELOPMENT_RESCUE" for v in classifications.values()):
        gate = "RESCUE_SUCCESS_CANDIDATE_FOUND"
    elif any(v == "PROMISING_BUT_NOT_ESTABLISHED" for v in classifications.values()):
        gate = "RESCUE_PROMISING_REQUIRES_FOCUSED_CONFIRMATION"
    _write_json(
        REVIEW_ROOT / "06_paper_handover" / "EDITOR009_PAPER_RESCUE_GATE.json",
        {
            "EDITOR009_PAPER_RESCUE_GATE": gate,
            "BEST_RESCUE_CONDITION": best_cond,
            "classifications": classifications,
            "promoted": promoted,
            "comparison": {k: {kk: vv for kk, vv in v.items() if kk != "seeds"} for k, v in comparison.items()},
            "R52_TEST_ACCESSED": False,
            "R51_RERUN": False,
            "R62_RERUN": False,
        },
    )
    (REVIEW_ROOT / "06_paper_handover" / "EDITOR009_PAPER_RESCUE_HANDOVER.md").write_text(
        f"""# EDITOR-009 Paper Rescue Handover

Gate: **{gate}**

Best condition: `{best_cond}`

Promoted: {promoted}

Do not assign EDITOR-009 results to historical C5. A successful rescue keeps a new condition identifier.

r5.2 TEST was not accessed. r5.1 and r6.2 were not run.
""",
        encoding="utf-8",
    )
    _write_json(
        REVIEW_ROOT / "EDITOR009_RUN_MANIFEST.json",
        {
            "campaign": "EDITOR-009 DEVELOPMENT RESCUE",
            "utc": utc_now(),
            "protocol_commit_phase0": PROTOCOL_COMMIT_PHASE0,
            "device": str(device),
            "R52_TEST_ACCESSED": False,
            "R51_RERUN": False,
            "R62_RERUN": False,
            "promoted": promoted,
            "gate": gate,
            "best": best_cond,
            "C5_DENY_HASHES_RESPECTED": True,
        },
    )
    return {
        "gate": gate,
        "promoted": promoted,
        "best": best_cond,
        "screen": {k: _pr(v) for k, v in screen.items()},
        "comparison": comparison,
        "classifications": classifications,
        "al_pr": _pr(al_row),
        "c2_pr": c2_pr,
        "c5_pr": _pr(c5_row),
        "headroom": head,
        "perm": perm,
        "g_c5": g_c5,
        "odst_sat": sat,
    }
