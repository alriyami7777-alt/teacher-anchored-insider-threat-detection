"""Manifest writers and static source scan."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from .safety import REGISTER, HarnessProtocolError, sha256_file, utc_now

FORBIDDEN_CALL_ATTRS = frozenset({"fit", "partial_fit", "backward"})
FORBIDDEN_IMPORT_MODULES = frozenset(
    {
        "torch.optim",
        "torch.optim.lr_scheduler",
        "sklearn.calibration",
        "sklearn.model_selection",
    }
)
FORBIDDEN_IMPORT_NAMES = frozenset(
    {
        "Optimizer",
        "Adam",
        "SGD",
        "ReduceLROnPlateau",
        "CalibratedClassifierCV",
        "GridSearchCV",
        "RandomizedSearchCV",
        "choose_threshold_f1",
        "choose_threshold",
    }
)


def scan_harness_source(package_dir: Path | None = None) -> dict[str, Any]:
    root = Path(package_dir) if package_dir is not None else Path(__file__).resolve().parent
    hits: list[dict[str, Any]] = []
    files = sorted(root.glob("*.py"))
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in FORBIDDEN_CALL_ATTRS:
                    hits.append({"file": path.name, "attr": node.func.attr, "lineno": node.lineno})
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORT_MODULES or alias.name.startswith("torch.optim"):
                        hits.append({"file": path.name, "import": alias.name, "lineno": node.lineno})
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in FORBIDDEN_IMPORT_MODULES or mod.startswith("torch.optim"):
                    hits.append({"file": path.name, "import_from": mod, "lineno": node.lineno})
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORT_NAMES:
                        hits.append({"file": path.name, "imported_name": alias.name, "lineno": node.lineno})
    if hits:
        raise HarnessProtocolError(f"Forbidden training/search constructs: {hits}")
    return {"status": "PASS", "files_scanned": [p.name for p in files], "hits": []}


def dump_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    REGISTER.note(path, "output")


def git_snapshot(repo: Path) -> dict[str, str]:
    import subprocess

    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return (proc.stdout or "").strip()

    return {
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "head": run("rev-parse", "HEAD"),
        "status_porcelain": run("status", "--porcelain"),
        "status_short": run("status", "--short"),
        "diff_check": run("diff", "--check"),
        "diff_stat": run("diff", "--stat"),
    }


def env_versions() -> dict[str, Any]:
    import sys
    import numpy
    import torch

    versions: dict[str, Any] = {
        "python": sys.version,
        "pytorch": torch.__version__,
        "numpy": numpy.__version__,
        "device": "cpu",
        "cuda": getattr(torch.version, "cuda", None),
    }
    try:
        import sklearn

        versions["scikit_learn"] = sklearn.__version__
    except Exception:  # noqa: BLE001
        versions["scikit_learn"] = None
    try:
        import xgboost

        versions["xgboost"] = xgboost.__version__
    except Exception:  # noqa: BLE001
        versions["xgboost"] = None
    return versions
