"""Objective 2 bounded end-to-end refinement package."""

from .protocol import MAX_TOTAL_RUNS, condition_configs
from .safety import (
    Objective3WriteProtectionError,
    ProtectedPartitionError,
    assert_output_namespace,
    assert_partition_role_permitted,
)

__all__ = [
    "MAX_TOTAL_RUNS",
    "Objective3WriteProtectionError",
    "ProtectedPartitionError",
    "assert_output_namespace",
    "assert_partition_role_permitted",
    "condition_configs",
]
