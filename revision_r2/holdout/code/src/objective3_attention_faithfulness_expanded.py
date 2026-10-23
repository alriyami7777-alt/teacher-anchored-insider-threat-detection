#!/usr/bin/env python3
"""Expanded attention-faithfulness cohort construction (CERT r4.2 validation).

Excludes the frozen 20-sequence pilot. Includes all remaining malicious sequences
and an equal deterministically selected benign cohort.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd
import torch

from objective3_attention_faithfulness import (
    EXPECTED_MANIFEST_SHA256,
    PROTOCOL_SEED,
    predicted_class,
)
from objective3_locked_common import SEQ_LEN, sha256_file
from objective3_model_interface import load_objective3_model, objective3_inference
from objective3_model_registry import (
    NEURAL_REFERENCE_ARCHITECTURE,
    PRIMARY_ARCHITECTURE,
    get_registry_entry,
)
from objective3_multiseed_native_extraction import verify_frozen_sample_manifest
from objective3_native_explanation_pilot import (
    ProtocolVerificationError,
    load_frozen_threshold,
)
from objective3_odst_loader import resolve_checkpoint_path

ARCHITECTURES = (PRIMARY_ARCHITECTURE, NEURAL_REFERENCE_ARCHITECTURE)
SEEDS = (42, 52, 62)
EXPECTED_VAL_N = 31000
EXPECTED_VAL_MAL = 252
USER_CAP_STAGES = (5, 10, 20, 50, 10**9)


def stable_cohort_hash(
    sequence_id: str,
    user_id: str,
    protocol_seed: int,
    stratum: str,
) -> str:
    payload = f"{protocol_seed}|{stratum}|{sequence_id}|{user_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_validation_counts(y: np.ndarray) -> dict[str, int]:
    n = int(len(y))
    mal = int(np.sum(y == 1))
    ben = int(np.sum(y == 0))
    if n != EXPECTED_VAL_N:
        raise ProtocolVerificationError(f"Expected {EXPECTED_VAL_N} val sequences; got {n}")
    if mal != EXPECTED_VAL_MAL:
        raise ProtocolVerificationError(f"Expected {EXPECTED_VAL_MAL} malicious; got {mal}")
    return {"n": n, "malicious": mal, "benign": ben}


def load_pilot_exclusion(manifest_path, expected_sha256: str = EXPECTED_MANIFEST_SHA256) -> pd.DataFrame:
    ver = verify_frozen_sample_manifest(manifest_path, expected_sha256=expected_sha256)
    df = pd.read_csv(manifest_path)
    if len(df) != 20:
        raise ProtocolVerificationError("Pilot must have 20 rows")
    if int((df.ground_truth == 1).sum()) != 10 or int((df.ground_truth == 0).sum()) != 10:
        raise ProtocolVerificationError("Pilot must have 10 malicious and 10 benign")
    strata = df.joint_stratum.value_counts().to_dict()
    for s in (
        "A_malicious_detected_both",
        "B_malicious_missed_at_least_one",
        "C_benign_false_flag_at_least_one",
        "D_benign_correct_both",
    ):
        if int(strata.get(s, 0)) != 5:
            raise ProtocolVerificationError(f"Pilot stratum {s} must have 5; got {strata}")
    ver["ok"] = True
    df.attrs["verification"] = ver
    return df


def six_model_predictions(
    x: np.ndarray,
    *,
    root,
    batch_size: int = 512,
    device: str = "cpu",
) -> dict[str, np.ndarray]:
    """Return probs and preds for all six models on full validation X."""
    out: dict[str, np.ndarray] = {}
    n = len(x)
    for arch in ARCHITECTURES:
        for seed in SEEDS:
            entry = get_registry_entry(arch, "r4.2", seed)
            thr = load_frozen_threshold(
                resolve_checkpoint_path(entry.threshold_metadata_path or "", root=root)
            )
            loaded = load_objective3_model(
                arch,
                "r4.2",
                seed,
                device=device,
                partition_role="r42_development",
                root=root,
            )
            model = loaded.model
            model.eval()
            probs = np.empty(n, dtype=np.float64)
            with torch.no_grad():
                for start in range(0, n, batch_size):
                    xb = torch.from_numpy(
                        np.asarray(x[start : start + batch_size], dtype=np.float32)
                    ).to(device)
                    logits, _ = model(xb)
                    probs[start : start + len(xb)] = (
                        torch.sigmoid(logits).detach().cpu().numpy()
                    )
            preds = (probs >= thr).astype(np.int8)
            key = f"{arch}|{seed}"
            out[f"prob_{key}"] = probs
            out[f"pred_{key}"] = preds
            out[f"thr_{key}"] = np.full(n, thr, dtype=np.float64)
    return out


def classify_benign_eligibility(pred_mat: np.ndarray) -> np.ndarray:
    """pred_mat: (N, 6) predictions. Returns stratum labels for benign rows only conceptually.

    - false_flag_at_least_one: any model predicts 1
    - unanimously_rejected: all predict 0
    - disagreement_subset of false_flag: not all equal (for fill)
    """
    any_pos = pred_mat.max(axis=1) == 1
    all_neg = pred_mat.max(axis=1) == 0
    all_same = pred_mat.min(axis=1) == pred_mat.max(axis=1)
    labels = np.full(len(pred_mat), "other", dtype=object)
    labels[all_neg] = "unanimously_rejected"
    labels[any_pos] = "false_flag_at_least_one"
    # disagreement among models (for fill after FP shortage)
    disagree = any_pos & (~all_same)
    labels[disagree] = "false_flag_with_disagreement"
    # pure FP unanimous malicious across models still false_flag
    labels[any_pos & all_same] = "false_flag_unanimous_malicious"
    # For target: false_flag_at_least_one = any_pos
    return labels, any_pos, all_neg, disagree


def _select_with_user_caps(
    idxs: list[int],
    *,
    sequence_id: np.ndarray,
    user: np.ndarray,
    stratum: str,
    target_n: int,
    protocol_seed: int = PROTOCOL_SEED,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Deterministic hash sort + staged user caps."""
    keyed = sorted(
        idxs,
        key=lambda i: (
            stable_cohort_hash(str(sequence_id[i]), str(user[i]), protocol_seed, stratum),
            str(sequence_id[i]),
        ),
    )
    selected: list[dict[str, Any]] = []
    notes: list[str] = []
    used: set[str] = set()
    for stage, cap in enumerate(USER_CAP_STAGES):
        user_counts: dict[str, int] = {}
        for i in keyed:
            sid = str(sequence_id[i])
            if sid in used:
                continue
            uid = str(user[i])
            if user_counts.get(uid, 0) >= cap:
                continue
            selected.append(
                {
                    "validation_row_index": int(i),
                    "sequence_id": sid,
                    "user_id": uid,
                    "selection_stratum": stratum,
                    "stable_selection_hash": stable_cohort_hash(
                        sid, uid, protocol_seed, stratum
                    ),
                    "user_cap_stage": int(cap if cap < 10**8 else -1),
                    "user_cap_stage_index": stage,
                }
            )
            used.add(sid)
            user_counts[uid] = user_counts.get(uid, 0) + 1
            if len(selected) >= target_n:
                break
        if len(selected) >= target_n:
            if stage > 0:
                notes.append(f"{stratum}: filled at user_cap={cap} (stage {stage})")
            break
        notes.append(
            f"{stratum}: after cap={cap} selected={len(selected)}/{target_n}; relaxing"
        )
    return selected[:target_n], notes


def build_expanded_cohort(
    *,
    y: np.ndarray,
    sequence_id: np.ndarray,
    user: np.ndarray,
    start_date: np.ndarray,
    end_date: np.ndarray,
    pred_cols: dict[str, np.ndarray],
    pilot_df: pd.DataFrame,
    protocol_seed: int = PROTOCOL_SEED,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    verify_validation_counts(y)
    pilot_seqs = set(pilot_df.sequence_id.astype(str).tolist())
    pilot_mal = set(pilot_df.loc[pilot_df.ground_truth == 1, "sequence_id"].astype(str))
    pilot_ben = set(pilot_df.loc[pilot_df.ground_truth == 0, "sequence_id"].astype(str))

    # Six-model prediction matrix
    pred_keys = [f"pred_{a}|{s}" for a in ARCHITECTURES for s in SEEDS]
    pred_mat = np.stack([pred_cols[k].astype(int) for k in pred_keys], axis=1)

    mal_idxs = [
        i
        for i in range(len(y))
        if int(y[i]) == 1 and str(sequence_id[i]) not in pilot_seqs
    ]
    if len(mal_idxs) != EXPECTED_VAL_MAL - 10:
        raise ProtocolVerificationError(
            f"Expected {EXPECTED_VAL_MAL - 10} non-pilot malicious; got {len(mal_idxs)}"
        )

    ben_all = [
        i
        for i in range(len(y))
        if int(y[i]) == 0 and str(sequence_id[i]) not in pilot_seqs
    ]
    labels, any_pos, all_neg, disagree = classify_benign_eligibility(pred_mat)

    fp_idxs = [i for i in ben_all if any_pos[i]]
    uni_neg_idxs = [i for i in ben_all if all_neg[i]]
    # disagreement among false flags for fill
    fp_disagree = [i for i in ben_all if disagree[i]]

    target_ben = len(mal_idxs)
    half = target_ben // 2
    other_half = target_ben - half
    notes: list[str] = []

    # Target: half FP, half unanimously rejected
    selected_ben: list[dict[str, Any]] = []
    fp_sel, n1 = _select_with_user_caps(
        fp_idxs,
        sequence_id=sequence_id,
        user=user,
        stratum="benign_false_flag_at_least_one",
        target_n=half,
        protocol_seed=protocol_seed,
    )
    notes.extend(n1)
    if len(fp_sel) < half:
        shortage = half - len(fp_sel)
        notes.append(
            f"FP shortage={shortage}; fill with disagreement then unanimously rejected"
        )
        already = {r["sequence_id"] for r in fp_sel}
        fill_pool = [i for i in fp_disagree if str(sequence_id[i]) not in already]
        fill1, n2 = _select_with_user_caps(
            fill_pool,
            sequence_id=sequence_id,
            user=user,
            stratum="benign_fp_disagreement_fill",
            target_n=shortage,
            protocol_seed=protocol_seed,
        )
        for r in fill1:
            r["inclusion_reason"] = "fp_shortage_disagreement_fill"
        notes.extend(n2)
        fp_sel.extend(fill1)
        if len(fp_sel) < half:
            shortage2 = half - len(fp_sel)
            already = {r["sequence_id"] for r in fp_sel}
            fill_pool2 = [i for i in uni_neg_idxs if str(sequence_id[i]) not in already]
            fill2, n3 = _select_with_user_caps(
                fill_pool2,
                sequence_id=sequence_id,
                user=user,
                stratum="benign_unanimous_neg_fill_for_fp",
                target_n=shortage2,
                protocol_seed=protocol_seed,
            )
            for r in fill2:
                r["inclusion_reason"] = "fp_shortage_unanimous_neg_fill"
            notes.extend(n3)
            fp_sel.extend(fill2)
    for r in fp_sel:
        r.setdefault("inclusion_reason", "target_false_flag_stratum")
    selected_ben.extend(fp_sel[:half] if len(fp_sel) >= half else fp_sel)

    already_ben = {r["sequence_id"] for r in selected_ben}
    uni_pool = [i for i in uni_neg_idxs if str(sequence_id[i]) not in already_ben]
    need_uni = target_ben - len(selected_ben)
    uni_sel, n4 = _select_with_user_caps(
        uni_pool,
        sequence_id=sequence_id,
        user=user,
        stratum="benign_unanimously_rejected",
        target_n=need_uni,
        protocol_seed=protocol_seed,
    )
    notes.extend(n4)
    for r in uni_sel:
        r.setdefault("inclusion_reason", "target_unanimously_rejected_stratum")
    selected_ben.extend(uni_sel)

    if len(selected_ben) != target_ben:
        raise ProtocolVerificationError(
            f"Benign cohort size {len(selected_ben)} != malicious {target_ben}"
        )

    rows: list[dict[str, Any]] = []
    # Malicious: all remaining, deterministic order by hash
    mal_sorted = sorted(
        mal_idxs,
        key=lambda i: (
            stable_cohort_hash(
                str(sequence_id[i]), str(user[i]), protocol_seed, "malicious_all_remaining"
            ),
            str(sequence_id[i]),
        ),
    )
    for rank, i in enumerate(mal_sorted, start=1):
        preds = pred_mat[i]
        rows.append(
            _row(
                i,
                rank,
                y,
                sequence_id,
                user,
                start_date,
                end_date,
                preds,
                pred_keys,
                selection_stratum="malicious_all_remaining",
                inclusion_reason="all_non_pilot_malicious",
                protocol_seed=protocol_seed,
            )
        )

    for rank, rec in enumerate(selected_ben, start=1):
        i = rec["validation_row_index"]
        preds = pred_mat[i]
        rows.append(
            _row(
                i,
                rank,
                y,
                sequence_id,
                user,
                start_date,
                end_date,
                preds,
                pred_keys,
                selection_stratum=rec["selection_stratum"],
                inclusion_reason=rec.get("inclusion_reason", ""),
                protocol_seed=protocol_seed,
                user_cap_stage=rec.get("user_cap_stage", 5),
                stable_hash=rec.get("stable_selection_hash"),
            )
        )

    df = pd.DataFrame(rows)
    df.insert(0, "cohort_sample_id", [f"E{i:04d}" for i in range(1, len(df) + 1)])
    # Verify pilot exclusion
    if set(df.sequence_id.astype(str)) & pilot_seqs:
        raise ProtocolVerificationError("Pilot sequences leaked into expanded cohort")
    meta = {
        "pilot_excluded": len(pilot_seqs),
        "pilot_malicious_excluded": len(pilot_mal),
        "pilot_benign_excluded": len(pilot_ben),
        "malicious_count": int((df.ground_truth == 1).sum()),
        "benign_count": int((df.ground_truth == 0).sum()),
        "unique_users": int(df.user_id.nunique()),
        "benign_stratum_counts": df.loc[df.ground_truth == 0, "selection_stratum"]
        .value_counts()
        .to_dict(),
        "notes": notes,
        "expected_size": 2 * len(mal_idxs),
        "actual_size": len(df),
    }
    return df, meta


def _row(
    i,
    rank,
    y,
    sequence_id,
    user,
    start_date,
    end_date,
    preds,
    pred_keys,
    *,
    selection_stratum,
    inclusion_reason,
    protocol_seed,
    user_cap_stage=5,
    stable_hash=None,
):
    pattern = "".join(str(int(p)) for p in preds)
    sid = str(sequence_id[i])
    uid = str(user[i])
    return {
        "sequence_id": sid,
        "user_id": uid,
        "window_start": str(start_date[i])[:10],
        "window_end": str(end_date[i])[:10],
        "ground_truth": int(y[i]),
        "malicious_or_benign": "malicious" if int(y[i]) == 1 else "benign",
        "selection_stratum": selection_stratum,
        "six_model_prediction_pattern": pattern,
        "number_of_models_predicting_malicious": int(preds.sum()),
        "pilot_exclusion_verified": 1,
        "stable_selection_hash": stable_hash
        or stable_cohort_hash(sid, uid, protocol_seed, selection_stratum),
        "selection_rank": int(rank),
        "user_cap_stage": int(user_cap_stage),
        "inclusion_reason": inclusion_reason,
        "validation_row_index": int(i),
        **{pred_keys[j]: int(preds[j]) for j in range(6)},
    }


__all__ = [
    "ARCHITECTURES",
    "SEEDS",
    "build_expanded_cohort",
    "load_pilot_exclusion",
    "six_model_predictions",
    "stable_cohort_hash",
    "verify_validation_counts",
]
