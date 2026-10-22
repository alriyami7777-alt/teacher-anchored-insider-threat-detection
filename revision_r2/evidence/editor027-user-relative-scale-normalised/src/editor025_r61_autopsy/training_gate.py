"""Scan EDITOR-025 producing code for prohibited training APIs."""

from __future__ import annotations

import ast
from pathlib import Path

from .safety import Editor025Blocked, REPO_ROOT

PACKAGE_DIR = REPO_ROOT / "src" / "editor025_r61_autopsy"
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_editor025_r61_autopsy.py"

FORBIDDEN_ATTRS = {"backward", "fit", "partial_fit"}
FORBIDDEN_NAMES = {"fit", "partial_fit", "backward"}


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
        PACKAGE_DIR / "representation.py",
        PACKAGE_DIR / "support_clip.py",
        PACKAGE_DIR / "inference.py",
        SCRIPT_PATH,
    ]


def scan_optimizer_construction(paths: list[Path] | None = None) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    tokens = ("optim.", "torch.optim", "optimizer", "scheduler.step")
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
        raise Editor025Blocked(f"EDITOR025_TRAINING_GATE = FAIL: {hits}")
    opt = scan_optimizer_construction()
    if opt:
        raise Editor025Blocked(f"EDITOR025_TRAINING_GATE = FAIL optimizer constructed: {opt}")
