#!/usr/bin/env python3
"""Unit tests for CERT multi-release dataset registry and readiness audit."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_cert_dataset_readiness import build_parser, main as audit_main  # noqa: E402
from cert_ground_truth import (  # noqa: E402
    discover_answer_sources,
    load_answer_events,
    load_insiders_for_version,
    parse_answer_row,
    summarize_ground_truth,
)
from cert_schema_audit import (  # noqa: E402
    COMMON_13_FEATURES,
    assess_feature_compatibility,
    collect_release_schemas,
    compare_schemas,
    flatten_schema_comparison_rows,
)
from dataset_registry import (  # noqa: E402
    DATASETS,
    DatasetVersionError,
    assert_output_outside_raw,
    check_optional_logs,
    check_required_logs,
    get_dataset_spec,
    normalize_dataset_version,
    refuse_mixed_versions,
    resolve_dataset_paths,
    resolve_raw_dir_for_version,
    resolve_raw_dir_legacy_r42,
)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _write_answer_rows(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def build_mini_cert_tree(root: Path) -> dict[str, Path]:
    """Create tiny synthetic CERT trees for 4.2 / 5.2 / 6.2 + shared answers."""
    raw = root / "data" / "raw"
    answers = raw / "answers"
    answers.mkdir(parents=True)

    # Shared insiders.csv
    _write_csv(
        answers / "insiders.csv",
        ["dataset", "scenario", "details", "user", "start", "end"],
        [
            ["4.2", "1", "r4.2-1-U42A.csv", "U42A", "01/01/2010 00:00:00", "01/02/2010 00:00:00"],
            ["5.2", "1", "r5.2-1-U52A.csv", "U52A", "01/01/2010 00:00:00", "01/02/2010 00:00:00"],
            ["5.2", "2", "r5.2-2-U52B.csv", "U52B", "01/01/2010 00:00:00", "01/02/2010 00:00:00"],
            ["6.2", "1", "r6.2-1.csv", "U62A", "01/01/2010 00:00:00", "01/02/2010 00:00:00"],
        ],
    )

    # r4.2 answers (per-user dirs)
    _write_answer_rows(
        answers / "r4.2-1" / "r4.2-1-U42A.csv",
        [
            ["logon", "{A1B2-C3D4E5F6-1111AAAA}", "01/01/2010 08:00:00", "U42A", "PC-1", "Logon"],
            ["http", "{A1B2-C3D4E5F6-2222BBBB}", "01/01/2010 09:00:00", "U42A", "PC-1", "http://x"],
        ],
    )
    (answers / "r4.2-2").mkdir(exist_ok=True)
    (answers / "r4.2-3").mkdir(exist_ok=True)

    # r5.2 answers
    for scen in range(1, 5):
        (answers / f"r5.2-{scen}").mkdir(exist_ok=True)
    _write_answer_rows(
        answers / "r5.2-1" / "r5.2-1-U52A.csv",
        [
            ["logon", "{B1B2-C3D4E5F6-1111AAAA}", "01/01/2010 08:00:00", "U52A", "PC-2", "Logon"],
            [
                "device",
                "{B1B2-C3D4E5F6-3333CCCC}",
                "01/01/2010 08:30:00",
                "U52A",
                "PC-2",
                "REMOVABLE_ROOT;REMOVABLE_ROOT/U52A",
                "Connect",
            ],
        ],
    )
    _write_answer_rows(
        answers / "r5.2-2" / "r5.2-2-U52B.csv",
        [
            ["email", "{B1B2-C3D4E5F6-4444DDDD}", "01/01/2010 10:00:00", "U52B", "PC-3", "a@b.c"],
        ],
    )

    # r6.2 flat answers
    for scen in range(1, 6):
        rows = []
        if scen == 1:
            rows = [
                [
                    "logon",
                    "{C1B2-C3D4E5F6-1111AAAA}",
                    "01/01/2010 08:00:00",
                    "U62A",
                    "PC-9",
                    "Logon",
                ],
                [
                    "file",
                    "{C1B2-C3D4E5F6-5555EEEE}",
                    "01/01/2010 09:00:00",
                    "U62A",
                    "PC-9",
                    "REMOVABLE_ROOT/x.txt",
                    "File Open",
                ],
            ]
        _write_answer_rows(answers / f"r6.2-{scen}.csv", rows)

    # Activity logs per release
    releases = {
        "4.2": {
            "logon": ["id", "date", "user", "pc", "activity"],
            "device": ["id", "date", "user", "pc", "activity"],
            "file": ["id", "date", "user", "pc", "filename", "content"],
            "email": [
                "id",
                "date",
                "user",
                "pc",
                "to",
                "cc",
                "bcc",
                "from",
                "size",
                "attachments",
                "content",
            ],
            "http": ["id", "date", "user", "pc", "url", "content"],
            "psychometric": ["employee_name", "user_id", "O", "C", "E", "A", "N"],
            "decoy": False,
        },
        "5.2": {
            "logon": ["id", "date", "user", "pc", "activity"],
            "device": ["id", "date", "user", "pc", "file_tree", "activity"],
            "file": [
                "id",
                "date",
                "user",
                "pc",
                "filename",
                "activity",
                "to_removable_media",
                "from_removable_media",
                "content",
            ],
            "email": [
                "id",
                "date",
                "user",
                "pc",
                "to",
                "cc",
                "bcc",
                "from",
                "activity",
                "size",
                "attachments",
                "content",
            ],
            "http": ["id", "date", "user", "pc", "url", "content"],
            "psychometric": ["employee_name", "user_id", "O", "C", "E", "A", "N"],
            "decoy": True,
        },
        "6.2": {
            "logon": ["id", "date", "user", "pc", "activity"],
            "device": ["id", "date", "user", "pc", "file_tree", "activity"],
            "file": [
                "id",
                "date",
                "user",
                "pc",
                "filename",
                "activity",
                "to_removable_media",
                "from_removable_media",
                "content",
            ],
            "email": [
                "id",
                "date",
                "user",
                "pc",
                "to",
                "cc",
                "bcc",
                "from",
                "activity",
                "size",
                "attachments",
                "content",
            ],
            "http": ["id", "date", "user", "pc", "url", "activity", "content"],
            "psychometric": ["employee_name", "user_id", "O", "C", "E", "A", "N"],
            "decoy": True,
        },
    }

    paths: dict[str, Path] = {"answers": answers}
    for ver, spec in releases.items():
        folder = raw / f"r{ver}"
        folder.mkdir(parents=True)
        (folder / "LDAP").mkdir()
        (folder / "LDAP" / "2010-01.csv").write_text("user;employee\nU;Name\n", encoding="utf-8")
        (folder / "readme.txt").write_text(f"CERT r{ver} synthetic\n", encoding="utf-8")
        (folder / "license.txt").write_text("license\n", encoding="utf-8")

        user = {"4.2": "U42A", "5.2": "U52A", "6.2": "U62A"}[ver]
        eid = {
            "4.2": "{A1B2-C3D4E5F6-1111AAAA}",
            "5.2": "{B1B2-C3D4E5F6-1111AAAA}",
            "6.2": "{C1B2-C3D4E5F6-1111AAAA}",
        }[ver]

        _write_csv(
            folder / "logon.csv",
            spec["logon"],
            [[eid, "01/01/2010 08:00:00", user, "PC-1", "Logon"]],
        )
        device_row = [eid.replace("1111", "D111"), "01/01/2010 08:05:00", user, "PC-1"]
        if "file_tree" in spec["device"]:
            device_row.append("REMOVABLE_ROOT/")
        device_row.append("Connect")
        _write_csv(folder / "device.csv", spec["device"], [device_row])

        file_row = [
            eid.replace("1111", "F111"),
            "01/01/2010 08:10:00",
            user,
            "PC-1",
            "notes.txt",
        ]
        if "activity" in spec["file"]:
            file_row.extend(["File Open", "False", "False", "hello"])
        else:
            file_row.append("hello")
        _write_csv(folder / "file.csv", spec["file"], [file_row])

        email_row = [
            eid.replace("1111", "E111"),
            "01/01/2010 08:15:00",
            user,
            "PC-1",
            "a@b.c",
            "",
            "",
            f"{user}@x.com",
        ]
        if "activity" in spec["email"]:
            email_row.append("Send")
        email_row.extend(["100", "0", "hi"])
        _write_csv(folder / "email.csv", spec["email"], [email_row])

        http_row = [
            eid.replace("1111", "H111"),
            "01/01/2010 08:20:00",
            user,
            "PC-1",
            "http://example.com",
        ]
        if "activity" in spec["http"]:
            http_row.append("WWW Visit")
        http_row.append("page text")
        _write_csv(folder / "http.csv", spec["http"], [http_row])

        _write_csv(
            folder / "psychometric.csv",
            spec["psychometric"],
            [["Name", user, "1", "2", "3", "4", "5"]],
        )
        if spec["decoy"]:
            _write_csv(
                folder / "decoy_file.csv",
                ["decoy_filename", "pc"],
                [["decoy.txt", "PC-1"]],
            )
        paths[ver] = folder

    return paths


class TestDatasetRegistry(unittest.TestCase):
    def test_registry_entries(self) -> None:
        self.assertEqual(set(DATASETS), {"4.2", "5.2", "6.2"})
        self.assertEqual(get_dataset_spec("4.2").n_scenarios, 3)
        self.assertEqual(get_dataset_spec("5.2").n_scenarios, 4)
        self.assertEqual(get_dataset_spec("6.2").n_scenarios, 5)
        self.assertEqual(get_dataset_spec("4.2").answer_format, "per_user_directories")
        self.assertEqual(get_dataset_spec("5.2").answer_format, "per_user_directories")
        self.assertEqual(get_dataset_spec("6.2").answer_format, "flat_scenario_csv")
        self.assertEqual(get_dataset_spec("4.2").optional_logs, ())
        self.assertIn("decoy_file", get_dataset_spec("5.2").optional_logs)
        self.assertIn("decoy_file", get_dataset_spec("6.2").optional_logs)

    def test_version_normalization(self) -> None:
        self.assertEqual(normalize_dataset_version("5.2"), "5.2")
        self.assertEqual(normalize_dataset_version("r5.2"), "5.2")
        self.assertEqual(normalize_dataset_version("CERT r5.2"), "5.2")
        self.assertEqual(normalize_dataset_version("cert_r6.2"), "6.2")
        with self.assertRaises(DatasetVersionError):
            normalize_dataset_version("9.9")


class TestPathResolution(unittest.TestCase):
    def test_default_and_explicit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            resolved, source = resolve_raw_dir_for_version(
                "5.2", repo=root
            )
            self.assertEqual(resolved, paths["5.2"].resolve())
            self.assertIn("junction", source)

            explicit, source2 = resolve_raw_dir_for_version(
                "6.2", raw_dir=paths["6.2"], repo=root
            )
            self.assertEqual(explicit, paths["6.2"].resolve())
            self.assertEqual(source2, "explicit_raw_dir")

            full = resolve_dataset_paths(
                "5.2",
                raw_dir=paths["5.2"],
                answers_dir=paths["answers"],
                output_dir=root / "outputs" / "dataset_readiness" / "r5.2",
                repo=root,
            )
            self.assertEqual(full.version, "5.2")
            self.assertEqual(full.answers_dir, paths["answers"].resolve())

    def test_refuse_mixed_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            with self.assertRaises(DatasetVersionError):
                refuse_mixed_versions("5.2", paths["6.2"])

    def test_legacy_r42_compat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            legacy = resolve_raw_dir_legacy_r42(root / "data" / "raw", repo=root)
            self.assertEqual(legacy, paths["4.2"].resolve())


class TestLogChecks(unittest.TestCase):
    def test_required_and_optional_decoy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            spec52 = get_dataset_spec("5.2")
            present, missing = check_required_logs(paths["5.2"], spec52)
            self.assertEqual(missing, [])
            self.assertEqual(len(present), 6)
            optional = check_optional_logs(paths["5.2"], spec52)
            self.assertTrue(optional["decoy_file"])

            # Core schema audit must not fail merely because decoy is absent on r4.2
            spec42 = get_dataset_spec("4.2")
            opt42 = check_optional_logs(paths["4.2"], spec42)
            self.assertEqual(opt42, {})
            _, missing42 = check_required_logs(paths["4.2"], spec42)
            self.assertEqual(missing42, [])


class TestGroundTruthLoading(unittest.TestCase):
    def test_r42_r52_dirs_and_r62_flat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            answers = paths["answers"]

            ins42 = load_insiders_for_version(answers, "4.2")
            self.assertEqual(len(ins42), 1)
            ins52 = load_insiders_for_version(answers, "5.2")
            self.assertEqual(len(ins52), 2)
            ins62 = load_insiders_for_version(answers, "6.2")
            self.assertEqual(len(ins62), 1)

            d42 = discover_answer_sources(answers, "4.2")
            self.assertEqual(d42["answer_format"], "per_user_directories")
            d62 = discover_answer_sources(answers, "6.2")
            self.assertEqual(d62["answer_format"], "flat_scenario_csv")
            self.assertEqual(len(d62["missing_scenario_sources"]), 0)

            ev42, diag42 = load_answer_events(answers, "4.2")
            self.assertGreaterEqual(len(ev42), 2)
            self.assertEqual(diag42["malformed_rows"], 0)

            ev52, _ = load_answer_events(answers, "5.2")
            self.assertGreaterEqual(len(ev52), 3)

            ev62, diag62 = load_answer_events(answers, "6.2")
            self.assertGreaterEqual(len(ev62), 2)
            self.assertIn("r6.2-1", diag62["scenario_counts"])

            summary = summarize_ground_truth(answers, "6.2")
            self.assertEqual(summary["n_insider_users"], 1)
            self.assertGreaterEqual(summary["n_answer_records"], 2)

    def test_parse_quoted_r62_style_row(self) -> None:
        parsed = parse_answer_row(
            [
                "logon",
                '"{G3R8-G0BG91SZ-1111ZKPB}"',
                '"08/18/2010 21:47:42"',
                '"ACM2278"',
                '"PC-8431"',
                '"Logon"',
            ]
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], "logon")
        self.assertTrue(parsed[1].startswith("{"))

    def test_duplicate_event_id_detail_rows(self) -> None:
        from cert_ground_truth import (
            AnswerEventRecord,
            build_duplicate_event_id_detail_rows,
            resolve_matched_ids_from_summary,
        )

        records = [
            AnswerEventRecord(
                event_id="{DUP-ID-0001-AAAA}",
                event_type="file",
                scenario_key="r5.2-2",
                answer_user="U52A",
                answer_file="r5.2-2/r5.2-2-U52A.csv",
                answer_row=3,
            ),
            AnswerEventRecord(
                event_id="{DUP-ID-0001-AAAA}",
                event_type="file",
                scenario_key="r5.2-4",
                answer_user="U52B",
                answer_file="r5.2-4/r5.2-4-U52B.csv",
                answer_row=7,
            ),
            AnswerEventRecord(
                event_id="{UNIQ-ID-0002-BBBB}",
                event_type="http",
                scenario_key="r5.2-1",
                answer_user="U52A",
                answer_file="r5.2-1/r5.2-1-U52A.csv",
                answer_row=1,
            ),
        ]
        matched_ids, known = resolve_matched_ids_from_summary(
            {
                "n_target_ids": 2,
                "n_matched_ids": 2,
                "n_unmatched_ids": 0,
                "partial_scan": False,
                "skipped": False,
            },
            records,
        )
        self.assertTrue(known)
        self.assertIn("{DUP-ID-0001-AAAA}", matched_ids or set())
        rows = build_duplicate_event_id_detail_rows(
            records,
            "5.2",
            matched_event_ids=matched_ids,
            matching_status_known=known,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["duplicate_count"], 2)
        self.assertEqual(rows[0]["dataset_version"], "5.2")
        self.assertTrue(rows[0]["matched_raw_event"])
        self.assertEqual(
            {r["source_row_number"] for r in rows},
            {3, 7},
        )


class TestSchemaAndFeatures(unittest.TestCase):
    def test_schema_comparison_and_feature_compat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            schemas = collect_release_schemas(
                {"4.2": paths["4.2"], "5.2": paths["5.2"], "6.2": paths["6.2"]}
            )
            rows = compare_schemas(schemas)
            flat = flatten_schema_comparison_rows(rows)
            self.assertTrue(any(r["log_name"] == "device" for r in flat))
            device = next(r for r in flat if r["log_name"] == "device")
            self.assertIn("file_tree", device["release_specific_5.2"])

            feats = assess_feature_compatibility(schemas)
            common = [f for f in feats if f["feature_name"] in COMMON_13_FEATURES]
            self.assertEqual(len(common), 13)
            for f in common:
                self.assertTrue(f["available_r5.2"])
                self.assertTrue(f["available_r6.2"])
                self.assertEqual(f["mapping_r5.2"], "exact")
                self.assertEqual(f["mapping_r6.2"], "exact")
            deferred = [f for f in feats if f.get("exclude_from_common_space") == "yes"]
            self.assertGreaterEqual(len(deferred), 4)


class TestSafetyBoundaries(unittest.TestCase):
    def test_output_isolation_and_readonly_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            with self.assertRaises(DatasetVersionError):
                assert_output_outside_raw(paths["5.2"] / "derived", paths["5.2"])
            # Outside raw is fine
            assert_output_outside_raw(root / "outputs" / "x", paths["5.2"])

    def test_audit_refuses_training_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--dataset-version", "5.2", "--train"])
        self.assertTrue(args.train)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            out = str(root / "outputs" / "dataset_readiness" / "r5.2")
            base = [
                "--dataset-version",
                "5.2",
                "--raw-dir",
                str(paths["5.2"]),
                "--answers-dir",
                str(paths["answers"]),
                "--output-dir",
                out,
                "--smoke",
            ]
            with self.assertRaises(SystemExit) as ctx_train:
                audit_main([*base, "--train"])
            self.assertIn("REFUSED", str(ctx_train.exception))
            with self.assertRaises(SystemExit) as ctx_eval:
                audit_main([*base, "--evaluate-test"])
            self.assertIn("REFUSED", str(ctx_eval.exception))

    def test_smoke_audit_writes_manifest_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            out = root / "outputs" / "dataset_readiness" / "r5.2"
            code = audit_main(
                [
                    "--dataset-version",
                    "5.2",
                    "--raw-dir",
                    str(paths["5.2"]),
                    "--answers-dir",
                    str(paths["answers"]),
                    "--output-dir",
                    str(out),
                    "--smoke",
                ]
            )
            self.assertEqual(code, 0)
            manifest = json.loads((out / "readiness_manifest.json").read_text(encoding="utf-8"))
            self.assertIs(manifest["training_started"], False)
            self.assertIs(manifest["test_evaluated"], False)
            self.assertTrue((out / "feature_compatibility.csv").exists())
            self.assertTrue((out / "dataset_schema_comparison.csv").exists())
            self.assertTrue((out / "ground_truth_summary.csv").exists())


class TestBackwardCompatR42(unittest.TestCase):
    def test_resolve_paths_default_42(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_mini_cert_tree(root)
            resolved = resolve_dataset_paths(
                "4.2",
                answers_dir=paths["answers"],
                output_dir=root / "outputs" / "dataset_readiness" / "r4.2",
                repo=root,
            )
            self.assertEqual(resolved.raw_dir, paths["4.2"].resolve())
            self.assertEqual(resolved.spec.processed_prefix, "r42")


if __name__ == "__main__":
    unittest.main()
