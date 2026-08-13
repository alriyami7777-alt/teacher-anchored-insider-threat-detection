"""PHASE 1 score writer. Metrics are forbidden until SCORE_COMPLETE validates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .hash_gate import preflight_all_eighteen
from .input_bundle import DenseDailyWindowProvider, FUTURE_METADATA_FIELDS, SequenceIdentifiers
from .model_loaders import (
    CLASSICAL_FAMILIES,
    NEURAL_FAMILIES,
    import_aggregate_common13_windows,
    infer_classical,
    infer_neural,
    load_neural_checkpoint,
    load_rf,
    load_xgb,
    state_hash,
)
from .safety import (
    BATCH_SIZE_FROZEN,
    N_FEATURES,
    REGISTER,
    SCORE_STEM,
    T_WINDOW,
    HarnessProtocolError,
    sha256_file,
    utc_now,
)


SCORE_COMPLETE_NAME = "SCORE_COMPLETE.json"
SEQUENCE_METADATA_NAME = "SEQUENCE_METADATA.json"


def persist_sequence_metadata(out_dir: Path, identifiers: list[SequenceIdentifiers]) -> dict[str, Any]:
    from dataclasses import asdict

    records = []
    for row in identifiers:
        rec = asdict(row)
        rec["answer_scenario_ids"] = [int(v) for v in rec["answer_scenario_ids"]]
        rec["endpoint_answer_scenario_ids"] = [int(v) for v in rec["endpoint_answer_scenario_ids"]]
        missing = [k for k in FUTURE_METADATA_FIELDS if k not in rec]
        if missing:
            raise HarnessProtocolError(f"Metadata missing fields {missing}")
        records.append(rec)
    payload = {
        "n_sequences": len(records),
        "fields": list(FUTURE_METADATA_FIELDS),
        "records": records,
        "official_incident_id_distinct_from_answer_scenario_ids": True,
    }
    path = Path(out_dir) / SEQUENCE_METADATA_NAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    REGISTER.note(path, "output_sequence_metadata")
    return payload


def load_sequence_metadata(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir) / SEQUENCE_METADATA_NAME
    if not path.is_file():
        raise HarnessProtocolError("SEQUENCE_METADATA.json missing")
    return json.loads(path.read_text(encoding="utf-8"))


def score_filename(family: str, seed: int) -> str:
    stem = SCORE_STEM[family]
    return f"{stem}_seed{seed}.npy"


def write_scores_phase(
    *,
    artefacts: list[dict[str, Any]],
    deny_hashes: set[str],
    x: np.ndarray,
    out_dir: Path,
    identifiers_sha256: str,
    input_bundle_sha256: str,
    thresholds: list[dict[str, Any]],
    batch_size: int = BATCH_SIZE_FROZEN,
    identifiers: list[SequenceIdentifiers] | None = None,
) -> dict[str, Any]:
    """Development-array scoring. External mode must use write_scores_phase_streaming."""
    out_dir = Path(out_dir)
    score_dir = out_dir / "raw_scores"
    score_dir.mkdir(parents=True, exist_ok=True)
    preflight = preflight_all_eighteen(artefacts, deny_hashes)
    allow_hashes = {str(a["expected_sha256"]) for a in artefacts}
    thr_map = {(t["family"], int(t["seed"])): float(t["threshold"]) for t in thresholds}
    aggregate_fn = import_aggregate_common13_windows()
    records: list[dict[str, Any]] = []
    n = int(x.shape[0])
    try:
        for art in artefacts:
            family = str(art["family"])
            seed = int(art["seed"])
            path = art["path"]
            expected = str(art["expected_sha256"])
            before_file = sha256_file(Path(path))
            if family in NEURAL_FAMILIES:
                loaded = load_neural_checkpoint(
                    family=family,
                    seed=seed,
                    path=path,
                    expected_sha256=expected,
                    deny_hashes=deny_hashes,
                    allow_hashes=allow_hashes,
                )
                hash_before = loaded["state_hash"]
                scores = infer_neural(loaded["model"], x, batch_size=batch_size)
                hash_after = state_hash(loaded["model"])
                if hash_before != hash_after:
                    raise HarnessProtocolError(f"Neural state mutated {family} {seed}")
                del loaded["model"]
            elif family == "RF_40":
                loaded = load_rf(
                    seed=seed,
                    path=path,
                    expected_sha256=expected,
                    deny_hashes=deny_hashes,
                    allow_hashes=allow_hashes,
                )
                scores = infer_classical(
                    family=family, model=loaded["model"], x_seq=x, aggregate_fn=aggregate_fn
                )
                del loaded["model"]
                hash_before = hash_after = sha256_file(Path(path))
            elif family == "XGBoost_40":
                loaded = load_xgb(
                    seed=seed,
                    path=path,
                    expected_sha256=expected,
                    deny_hashes=deny_hashes,
                    allow_hashes=allow_hashes,
                )
                scores = infer_classical(
                    family=family, model=loaded["model"], x_seq=x, aggregate_fn=aggregate_fn
                )
                del loaded["model"]
                hash_before = hash_after = sha256_file(Path(path))
            else:
                raise HarnessProtocolError(f"Unknown family {family}")
            after_file = sha256_file(Path(path))
            if before_file != after_file:
                raise HarnessProtocolError(f"Artefact bytes mutated {family} {seed}")
            if scores.shape != (n,):
                raise HarnessProtocolError(f"Score length {scores.shape} != {n}")
            if not np.all(np.isfinite(scores)):
                raise HarnessProtocolError(f"Non-finite scores {family} {seed}")
            if np.any(scores < 0.0) or np.any(scores > 1.0):
                raise HarnessProtocolError(f"Scores outside [0,1] {family} {seed}")
            fname = score_filename(family, seed)
            fpath = score_dir / fname
            np.save(fpath, scores.astype(np.float64))
            REGISTER.note(fpath, "output_raw_score")
            rec = {
                "family": family,
                "seed": seed,
                "model_sha256": expected,
                "threshold": thr_map[(family, seed)],
                "path": str(fpath),
                "n": n,
                "dtype": "float64",
                "sha256": sha256_file(fpath),
                "state_hash_before": hash_before,
                "state_hash_after": hash_after,
                "file_sha256_before": before_file,
                "file_sha256_after": after_file,
                "input_bundle_sha256": input_bundle_sha256,
                "sequence_order_sha256": identifiers_sha256,
            }
            records.append(rec)
    except Exception:
        # Incomplete phase: do not write SCORE_COMPLETE.
        raise

    if len(records) != 18:
        raise HarnessProtocolError("Incomplete 18-model score phase")
    metadata = None
    if identifiers is not None:
        if len(identifiers) != n:
            raise HarnessProtocolError("Identifier count != n sequences")
        metadata = persist_sequence_metadata(out_dir, identifiers)
    manifest = {
        "phase": "SCORE",
        "complete": True,
        "n_models": 18,
        "n_sequences": n,
        "batch_size": batch_size,
        "device": "cpu",
        "dtype_input": "float32",
        "created_utc": utc_now(),
        "input_bundle_sha256": input_bundle_sha256,
        "sequence_order_sha256": identifiers_sha256,
        "preflight": preflight,
        "scores": records,
        "scoring_mode": "development_array",
        "sequence_metadata_persisted": metadata is not None,
    }
    man_path = out_dir / SCORE_COMPLETE_NAME
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    REGISTER.note(man_path, "output_score_complete")
    manifest["manifest_sha256"] = sha256_file(man_path)
    return manifest


def require_score_complete(out_dir: Path, expected_n: int | None = None) -> dict[str, Any]:
    path = Path(out_dir) / SCORE_COMPLETE_NAME
    if not path.is_file():
        raise HarnessProtocolError("ANALYSIS BLOCKED: SCORE_COMPLETE.json missing")
    man = json.loads(path.read_text(encoding="utf-8"))
    if not man.get("complete"):
        raise HarnessProtocolError("ANALYSIS BLOCKED: SCORE_COMPLETE incomplete")
    scores = man.get("scores") or []
    if len(scores) != 18:
        raise HarnessProtocolError("ANALYSIS BLOCKED: SCORE_COMPLETE does not list 18 artefacts")
    for rec in scores:
        fpath = Path(rec["path"])
        if not fpath.is_file():
            raise HarnessProtocolError(f"ANALYSIS BLOCKED: missing score file {fpath}")
        arr = np.load(fpath)
        if expected_n is not None and int(arr.shape[0]) != int(expected_n):
            raise HarnessProtocolError("ANALYSIS BLOCKED: score row count mismatch")
        if rec.get("n") is not None and int(arr.shape[0]) != int(rec["n"]):
            raise HarnessProtocolError("ANALYSIS BLOCKED: score n field mismatch")
        observed = sha256_file(fpath)
        if observed != rec["sha256"]:
            raise HarnessProtocolError("ANALYSIS BLOCKED: score file hash mismatch")
    return man


def stream_scores_from_provider(
    *,
    provider: DenseDailyWindowProvider,
    score_fn,
    expected_n: int,
    out_path: Path | None = None,
    resume_manifest_bound: bool = False,
) -> np.ndarray:
    """Score batchwise. Never requires a full (N,20,13) tensor.

    Resume is refused unless explicitly manifest-bound. Silent append is forbidden.
    """
    n = int(provider.n_sequences)
    if n != int(expected_n):
        raise HarnessProtocolError(f"Provider n={n} != expected_n={expected_n}")
    if out_path is not None and Path(out_path).exists() and not resume_manifest_bound:
        raise HarnessProtocolError(
            "STREAMING SCORER: score file exists; refusing silent append; restart required"
        )
    out = np.empty((n,), dtype=np.float64)
    filled = np.zeros((n,), dtype=np.bool_)
    max_batch = int(provider.batch_size)
    for lo, hi, batch in provider:
        if batch.ndim != 3 or batch.shape[1:] != (T_WINDOW, N_FEATURES):
            raise HarnessProtocolError(f"Unexpected batch shape {batch.shape}")
        if batch.shape[0] > max_batch:
            raise HarnessProtocolError("Streaming batch exceeded batch_size")
        if (n > max_batch) and tuple(batch.shape) == (n, T_WINDOW, N_FEATURES):
            raise HarnessProtocolError("Full (N,20,13) tensor passed to streaming scorer")
        scores = np.asarray(score_fn(batch), dtype=np.float64).reshape(-1)
        if scores.shape[0] != (hi - lo):
            raise HarnessProtocolError("Score slice length mismatch")
        out[lo:hi] = scores
        filled[lo:hi] = True
    if not bool(filled.all()) or int(filled.sum()) != n:
        raise HarnessProtocolError("STREAMING SCORER: final row count != expected sequence count")
    provider.assert_never_full_sequence_tensor()
    if out_path is not None:
        np.save(Path(out_path), out)
    return out


def _tracked_aggregate(aggregate_fn, batch_size: int, seen: list[int]):
    def wrapped(x: np.ndarray):
        n_b = int(x.shape[0])
        seen.append(n_b)
        if n_b > batch_size:
            raise HarnessProtocolError("RF/XGB aggregator received more than one batch")
        if x.ndim != 3 or x.shape[1:] != (T_WINDOW, N_FEATURES):
            raise HarnessProtocolError(f"Aggregator input must be (B,20,13); got {x.shape}")
        return aggregate_fn(x)

    return wrapped


def write_scores_phase_streaming(
    *,
    artefacts: list[dict[str, Any]],
    deny_hashes: set[str],
    provider: DenseDailyWindowProvider,
    out_dir: Path,
    identifiers_sha256: str,
    input_bundle_sha256: str,
    thresholds: list[dict[str, Any]],
    batch_size: int = BATCH_SIZE_FROZEN,
    identifiers: list[SequenceIdentifiers] | None = None,
    resume_manifest_bound: bool = False,
) -> dict[str, Any]:
    """External scoring path: dense daily memmap → batch gather → score → discard."""
    if int(provider.batch_size) != int(batch_size):
        raise HarnessProtocolError("Provider batch_size != frozen run configuration")
    out_dir = Path(out_dir)
    score_dir = out_dir / "raw_scores"
    score_dir.mkdir(parents=True, exist_ok=True)
    preflight = preflight_all_eighteen(artefacts, deny_hashes)
    allow_hashes = {str(a["expected_sha256"]) for a in artefacts}
    thr_map = {(t["family"], int(t["seed"])): float(t["threshold"]) for t in thresholds}
    aggregate_fn = import_aggregate_common13_windows()
    records: list[dict[str, Any]] = []
    n = int(provider.n_sequences)
    aggregator_batch_sizes: list[int] = []
    tracked_agg = _tracked_aggregate(aggregate_fn, batch_size, aggregator_batch_sizes)
    try:
        for art in artefacts:
            family = str(art["family"])
            seed = int(art["seed"])
            path = art["path"]
            expected = str(art["expected_sha256"])
            before_file = sha256_file(Path(path))
            fname = score_filename(family, seed)
            fpath = score_dir / fname
            if family in NEURAL_FAMILIES:
                loaded = load_neural_checkpoint(
                    family=family,
                    seed=seed,
                    path=path,
                    expected_sha256=expected,
                    deny_hashes=deny_hashes,
                    allow_hashes=allow_hashes,
                )
                hash_before = loaded["state_hash"]
                model = loaded["model"]

                def _neural_fn(batch: np.ndarray, _model=model) -> np.ndarray:
                    return infer_neural(_model, batch, batch_size=batch_size)

                scores = stream_scores_from_provider(
                    provider=provider,
                    score_fn=_neural_fn,
                    expected_n=n,
                    out_path=None,
                    resume_manifest_bound=resume_manifest_bound,
                )
                hash_after = state_hash(model)
                if hash_before != hash_after:
                    raise HarnessProtocolError(f"Neural state mutated {family} {seed}")
                del loaded["model"]
            elif family in CLASSICAL_FAMILIES:
                if family == "RF_40":
                    loaded = load_rf(
                        seed=seed,
                        path=path,
                        expected_sha256=expected,
                        deny_hashes=deny_hashes,
                        allow_hashes=allow_hashes,
                    )
                else:
                    loaded = load_xgb(
                        seed=seed,
                        path=path,
                        expected_sha256=expected,
                        deny_hashes=deny_hashes,
                        allow_hashes=allow_hashes,
                    )
                model = loaded["model"]

                def _classical_fn(batch: np.ndarray, _model=model, _family=family) -> np.ndarray:
                    return infer_classical(
                        family=_family, model=_model, x_seq=batch, aggregate_fn=tracked_agg
                    )

                scores = stream_scores_from_provider(
                    provider=provider,
                    score_fn=_classical_fn,
                    expected_n=n,
                    out_path=None,
                    resume_manifest_bound=resume_manifest_bound,
                )
                del loaded["model"]
                hash_before = hash_after = sha256_file(Path(path))
            else:
                raise HarnessProtocolError(f"Unknown family {family}")
            after_file = sha256_file(Path(path))
            if before_file != after_file:
                raise HarnessProtocolError(f"Artefact bytes mutated {family} {seed}")
            if scores.shape != (n,):
                raise HarnessProtocolError(f"Score length {scores.shape} != {n}")
            if not np.all(np.isfinite(scores)):
                raise HarnessProtocolError(f"Non-finite scores {family} {seed}")
            if np.any(scores < 0.0) or np.any(scores > 1.0):
                raise HarnessProtocolError(f"Scores outside [0,1] {family} {seed}")
            if fpath.exists() and not resume_manifest_bound:
                raise HarnessProtocolError(
                    f"STREAMING SCORER: refusing silent append for {fname}; restart required"
                )
            np.save(fpath, scores.astype(np.float64))
            REGISTER.note(fpath, "output_raw_score")
            rec = {
                "family": family,
                "seed": seed,
                "model_sha256": expected,
                "threshold": thr_map[(family, seed)],
                "path": str(fpath),
                "n": n,
                "dtype": "float64",
                "sha256": sha256_file(fpath),
                "state_hash_before": hash_before,
                "state_hash_after": hash_after,
                "file_sha256_before": before_file,
                "file_sha256_after": after_file,
                "input_bundle_sha256": input_bundle_sha256,
                "sequence_order_sha256": identifiers_sha256,
                "scoring_mode": "streaming_batchwise",
            }
            records.append(rec)
    except Exception:
        raise

    if aggregator_batch_sizes and max(aggregator_batch_sizes) > batch_size:
        raise HarnessProtocolError("RF/XGB aggregator saw more than one batch")
    if len(records) != 18:
        raise HarnessProtocolError("Incomplete 18-model streaming score phase")
    metadata = None
    if identifiers is not None:
        if len(identifiers) != n:
            raise HarnessProtocolError("Identifier count != n sequences")
        metadata = persist_sequence_metadata(out_dir, identifiers)
    manifest = {
        "phase": "SCORE",
        "complete": True,
        "n_models": 18,
        "n_sequences": n,
        "batch_size": batch_size,
        "device": "cpu",
        "dtype_input": "float32",
        "created_utc": utc_now(),
        "input_bundle_sha256": input_bundle_sha256,
        "sequence_order_sha256": identifiers_sha256,
        "preflight": preflight,
        "scores": records,
        "scoring_mode": "streaming_batchwise",
        "aggregator_max_batch": int(max(aggregator_batch_sizes) if aggregator_batch_sizes else 0),
        "sequence_metadata_persisted": metadata is not None,
        "resume_manifest_bound": resume_manifest_bound,
    }
    man_path = out_dir / SCORE_COMPLETE_NAME
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    REGISTER.note(man_path, "output_score_complete")
    manifest["manifest_sha256"] = sha256_file(man_path)
    return manifest
