"""Entrypoint: lock configs, audit r5.2 data, train locked baselines, consolidate."""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

# Allow `python -m` and direct script execution.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.r52_locked_baselines import OUTPUT_NAMESPACE  # noqa: E402
from scripts.r52_locked_baselines.consolidate import consolidate  # noqa: E402
from scripts.r52_locked_baselines.data import audit_r52_tensors  # noqa: E402
from scripts.r52_locked_baselines.lock_configs import lock_configs  # noqa: E402
from scripts.r52_locked_baselines.safety import (  # noqa: E402
    ProtocolAccessError,
    assert_output_namespace,
    refuse_if_prohibited,
    write_json_atomic,
)
from scripts.r52_locked_baselines.train import run_all_seeds  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="r5.2 locked conventional baselines")
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument(
        "--tensor-dir",
        type=Path,
        default=None,
        help="Directory containing r52_T20_s1_{train,validation}.npz",
    )
    parser.add_argument(
        "--evaluate-test",
        action="store_true",
        help="PROHIBITED; present only so the guard can refuse it.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    tensor_dir = (args.tensor_dir or (root / "data" / "processed" / "r5.2" / "tensors")).resolve()

    print("=" * 72, flush=True)
    print("CERT r5.2 locked conventional baselines (XGBoost + Random Forest)", flush=True)
    print(f"root={root}", flush=True)
    print(f"tensor_dir={tensor_dir}", flush=True)
    print("=" * 72, flush=True)

    try:
        refuse_if_prohibited(
            evaluate_test=bool(args.evaluate_test),
            tensor_paths=[
                tensor_dir / "r52_T20_s1_train.npz",
                tensor_dir / "r52_T20_s1_validation.npz",
            ],
        )
        if args.evaluate_test:
            raise ProtocolAccessError("REFUSED: --evaluate-test")

        out = assert_output_namespace(root / OUTPUT_NAMESPACE, root)
        out.mkdir(parents=True, exist_ok=True)

        print("[1/4] Locking r4.2 configurations ...", flush=True)
        lock_report = lock_configs(root)
        print(f"  locked: {lock_report['written']}", flush=True)

        print("[2/4] Auditing r5.2 train/validation tensors ...", flush=True)
        data_manifest, split_audit, datasets = audit_r52_tensors(tensor_dir, root)
        write_json_atomic(out / "r52_data_manifest.json", data_manifest)
        write_json_atomic(out / "r52_split_audit.json", split_audit)
        print(
            f"  users={data_manifest['users']} train={data_manifest['train_sequences']} "
            f"val={data_manifest['validation_sequences']} "
            f"train_end={data_manifest['train_end_date_max']} "
            f"val={data_manifest['validation_start_date_min']}..{data_manifest['validation_end_date_max']}",
            flush=True,
        )

        print("[3/4] Training locked XGBoost and Random Forest (seeds 42/52/62) ...", flush=True)
        summaries = run_all_seeds(root, datasets)

        print("[4/4] Consolidating comparisons + preregistration draft ...", flush=True)
        interpretation = consolidate(root, summaries)
        print(f"  overall_status={interpretation['overall_validation_status']}", flush=True)
        print(f"  conventional_status={interpretation['conventional_model_status']}", flush=True)
        print("DONE. Stop for manual review.", flush=True)
        return 0
    except ProtocolAccessError as exc:
        print(f"PROTOCOL BLOCKED / REFUSED: {exc}", flush=True)
        try:
            out = assert_output_namespace(root / OUTPUT_NAMESPACE, root)
            out.mkdir(parents=True, exist_ok=True)
            status_path = out / "completion_status.json"
            if not status_path.exists():
                write_json_atomic(
                    status_path,
                    {
                        "overall_validation_status": "protocol_blocked",
                        "error": str(exc),
                    },
                )
        except Exception:
            pass
        return 2
    except Exception as exc:
        print(f"IMPLEMENTATION FAILURE: {exc}", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
