"""EDITOR-006B hash-gated inference-only harness (engineering validation).

This package must not run CERT r6.2 predictive inference and must not open
the r5.2 TEST tensor. Fixture scores are not scientific results.
"""

from __future__ import annotations

__all__ = ["PROTOCOL_NAME"]

PROTOCOL_NAME = "EDITOR-006B"
TASK_ID = "EDITOR-006B"
