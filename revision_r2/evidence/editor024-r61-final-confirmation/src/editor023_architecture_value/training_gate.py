"""Scan EDITOR-023 producing code for prohibited training APIs."""

from __future__ import annotations

import ast
from pathlib import Path

from .safety import Editor023Blocked, REPO_ROOT

PACKAGE_DIR = REPO_ROOT / "src" / "editor023_architecture_value"
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_editor023_architecture_value.py"

FORBIDDEN_ATTRS = {"step", "backward", "fit", "partial_fit"}


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
                if isinstance(func, ast.Name) and func.id in {"fit", "partial_fit"}:
                    found.append(f"call.{func.id}@{func.lineno}")
        if found:
            hits[str(path)] = found
    return hits


def assert_no_training() -> None:
    hits = scan_training_apis()
    if hits:
        raise Editor023Blocked(f"EDITOR023_TRAINING_GATE = FAIL: {hits}")
