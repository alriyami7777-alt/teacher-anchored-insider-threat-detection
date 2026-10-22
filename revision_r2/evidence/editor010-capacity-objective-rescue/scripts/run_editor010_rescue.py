"""EDITOR-010 overnight runner."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor010_rescue.pipeline import run_campaign  # noqa: E402
from editor010_rescue.safety import Editor010SafetyError  # noqa: E402


def _editor009_running() -> bool:
    cmd = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'python' } | "
        "Select-Object -ExpandProperty CommandLine"
    )
    try:
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    return "run_editor009" in out.lower()


def wait_for_gpu_if_editor009() -> None:
    """Do not compete with EDITOR-009 for the single GPU."""
    while _editor009_running():
        print("EDITOR-010: EDITOR-009 still running; waiting 60s before GPU phases", flush=True)
        time.sleep(60)
    print("EDITOR-010: no EDITOR-009 process; proceeding", flush=True)


def main() -> int:
    wait_for_gpu_if_editor009()
    try:
        summary = run_campaign()
    except Editor010SafetyError as exc:
        print(f"EDITOR-010 HARD BLOCK: {exc}", file=sys.stderr)
        return 2
    print("EDITOR010_PARALLEL_OVERNIGHT_RESCUE_COMPLETE")
    for key in (
        "INNER_SPLIT_VALID",
        "BEST_FULL_R52_CANDIDATE",
        "BEST_CANDIDATE_MEAN_PR_AUC",
        "EDITOR010_PAPER_RESCUE_GATE",
    ):
        print(f"{key} = {summary.get(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
