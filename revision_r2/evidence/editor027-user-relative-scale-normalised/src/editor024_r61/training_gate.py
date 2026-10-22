"""Scan EDITOR-024 producing code for prohibited training APIs."""

from __future__ import annotations

import ast
from pathlib import Path

from .safety import Editor024Blocked, REPO_ROOT

PACKAGE_DIR = REPO_ROOT / "src" / "editor024_r61"
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_editor024_r61.py"

FORBIDDEN_ATTRS = {"step", "backward", "fit", "partial_fit"}
FORBIDDEN_NAMES = {"fit", "partial_fit"}


def _iter_py_files() -> list[Path]:
    files = sorted(PACKAGE_DIR.glob("*.py"))
    if SCRIPT_PATH.is_file():
        files.append(SCRIPT_PATH)
    return files


def scan_training_apis(paths: list[Path] | None = None) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in paths or _iter_py_files():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_ATTRS:
                    found.append(f"call.{func.attr}@{func.lineno}")
                if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAMES:
                    found.append(f"call.{func.id}@{func.lineno}")
        if found:
            hits[str(path)] = found
    return hits


def _research_runner_files() -> list[Path]:
    return [
        PACKAGE_DIR / "campaign.py",
        PACKAGE_DIR / "inference.py",
        PACKAGE_DIR / "bundle.py",
        SCRIPT_PATH,
    ]


def scan_optimizer_construction(paths: list[Path] | None = None) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    tokens = ("optim.", "torch.optim", "optimizer")
    for path in paths or [p for p in _research_runner_files() if p.is_file()]:
        text = path.read_text(encoding="utf-8")
        found = []
        for i, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            if any(tok.lower() in low for tok in tokens):
                found.append(f"opt@{i}:{line.strip()}")
        if found:
            hits[str(path)] = found
    return hits


def assert_no_training() -> None:
    hits = scan_training_apis()
    if hits:
        raise Editor024Blocked(f"EDITOR024_TRAINING_GATE = FAIL: {hits}")
    opt = scan_optimizer_construction()
    if opt:
        raise Editor024Blocked(f"EDITOR024_TRAINING_GATE = FAIL optimizer constructed: {opt}")
