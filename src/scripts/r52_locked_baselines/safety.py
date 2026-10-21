"""Safety guards for r5.2 locked conventional baselines."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from . import OUTPUT_NAMESPACE


class ProtocolAccessError(RuntimeError):
    pass


FORBIDDEN_TEST_MARKERS = (
    "r52_t20_s1_test",
    "r5.2_t20_s1_test",
    "r42_t20_s1_test",
    "/test.npz",
    "\\test.npz",
    "tensors/test",
    "tensors\\test",
)

FORBIDDEN_R42_TEST = (
    "r42_t20_s1_test",
    "r4.2_t20_s1_test",
    "processed/r4.2",
    "processed\\r4.2",
    "raw/r4.2",
    "raw\\r4.2",
)

FORBIDDEN_R62 = ("r6.2", "r62", "processed/r6.2", "processed\\r6.2", "raw/r6.2", "raw\\r6.2")

# Freeze-phase / pretest guards: test evaluation must not run until after the
# annotated tag and an explicit dual confirmation on the guarded evaluator.
PRETEST_FREEZE_TAG = "objective2-r52-pretest-freeze-v1"
PRETEST_FREEZE_TAG_V1 = PRETEST_FREEZE_TAG
PRETEST_FREEZE_TAG_V2 = "objective2-r52-pretest-freeze-v2"


def repo_root() -> Path:
    return Path(__file__).absolute().parents[2]


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            c = f.read(chunk_size)
            if not c:
                break
            h.update(c)
    return h.hexdigest()


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def path_looks_like_test(path: str | Path) -> bool:
    text = _norm(str(path))
    name = Path(path).name.lower()
    if name.endswith("_test.npz") or name.endswith("_test.parquet"):
        return True
    return any(m in text for m in FORBIDDEN_TEST_MARKERS)


def path_looks_like_r62(path: str | Path) -> bool:
    text = _norm(str(path))
    return any(m in text for m in FORBIDDEN_R62)


def path_looks_like_r42_test(path: str | Path) -> bool:
    text = _norm(str(path))
    name = Path(path).name.lower()
    if "r42" in name and "test" in name:
        return True
    if "r4.2" in text and "test" in text:
        return True
    return any(m in text for m in FORBIDDEN_R42_TEST)


def assert_path_allowed(path: str | Path, *, role: str = "path") -> Path:
    p = Path(path)
    if path_looks_like_test(p):
        raise ProtocolAccessError(f"REFUSED: {role} references test partition: {p}")
    if path_looks_like_r42_test(p):
        raise ProtocolAccessError(f"REFUSED: {role} references r4.2 test: {p}")
    if path_looks_like_r62(p):
        raise ProtocolAccessError(f"REFUSED: {role} references r6.2: {p}")
    return p


def refuse_if_prohibited(
    *,
    evaluate_test: bool = False,
    confirm_test_evaluation: bool = False,
    tensor_paths: Iterable[str | Path] | None = None,
    allow_guarded_test: bool = False,
) -> None:
    """Refuse test / r6.2 / r4.2-test access unless a future guarded evaluator unlocks.

    During the pretest freeze task, ``allow_guarded_test`` must remain False so the
    test loader cannot be invoked at all.
    """
    reasons: list[str] = []
    if evaluate_test and not allow_guarded_test:
        reasons.append("evaluate_test=True (freeze/pretest phase refuses test loader)")
    if confirm_test_evaluation and not allow_guarded_test:
        reasons.append("confirm_test_evaluation=True during freeze/pretest phase")
    if tensor_paths:
        for p in tensor_paths:
            if path_looks_like_test(p):
                reasons.append(f"test path: {p}")
            if path_looks_like_r42_test(p):
                reasons.append(f"r4.2 test path: {p}")
            if path_looks_like_r62(p):
                reasons.append(f"r6.2 path: {p}")
    if reasons:
        raise ProtocolAccessError("REFUSED: " + "; ".join(reasons))


def refuse_test_loader(*, split: str | None = None, path: str | Path | None = None) -> None:
    """Hard stop for any attempt to open a test partition loader."""
    bits = ["test loader invocation refused during freeze/pretest protocol"]
    if split is not None:
        bits.append(f"split={split}")
    if path is not None:
        bits.append(f"path={path}")
    raise ProtocolAccessError("REFUSED: " + "; ".join(bits))


def assert_output_namespace(output_dir: str | Path, root: Path | None = None) -> Path:
    root = root or repo_root()
    out = Path(output_dir)
    if not out.is_absolute():
        out = root / out
    out_resolved = out.resolve()
    allowed = (root / OUTPUT_NAMESPACE).resolve()
    try:
        out_resolved.relative_to(allowed)
    except ValueError as exc:
        raise ProtocolAccessError(
            f"Outputs must live under {allowed}; refused {out_resolved}"
        ) from exc
    return out_resolved


def refuse_overwrite(path: Path) -> None:
    if Path(path).exists():
        raise ProtocolAccessError(f"REFUSED overwrite of existing artefact: {path}")


def write_json_atomic(path: Path, payload: Any) -> Path:
    refuse_overwrite(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def software_versions() -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import sklearn
    import xgboost

    return {
        "python": __import__("sys").version.replace("\n", " "),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": sklearn.__version__,
        "xgboost": xgboost.__version__,
    }
