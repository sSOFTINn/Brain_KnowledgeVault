from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.migrator import (
    approve_migration_row,
    effective_migration_plan,
    execute_migration_plan,
)
from vaultctl.planner import create_plan
from vaultctl.router import file_sha256
from vaultctl.scanner import scan

from test_router import CONFIG


class MigratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "vault.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(self.config_path)
        self.source = self.root / "external-source"
        self.source.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _approved_plan(self) -> tuple[Path, Path]:
        folder = self.source / "client-alpha"
        folder.mkdir()
        source = folder / "invoice_alpha.pdf"
        source.write_bytes(b"migration content")
        scan_result = scan(self.source, self.config, hash_mode="all")
        plan_path, rows = create_plan(scan_result.run_dir, self.config)
        approve_migration_row(plan_path, rows[0].row_id, self.config)
        return plan_path, source

    def test_approved_row_copies_and_verifies_without_deleting_source(self) -> None:
        plan_path, source = self._approved_plan()
        events = execute_migration_plan(plan_path, self.config)
        destination = Path(events[0]["destination_path"])
        self.assertTrue(source.exists())
        self.assertTrue(destination.exists())
        self.assertEqual(file_sha256(source), file_sha256(destination))
        self.assertEqual(events[0]["result"], "copied and verified")
        for name in (
            "migration_apply_journal.jsonl",
            "verification.jsonl",
            "rollback_manifest.json",
            "apply_summary.json",
        ):
            self.assertTrue((plan_path.parent / name).is_file())

    def test_unapproved_rows_are_not_executed(self) -> None:
        folder = self.source / "client-alpha"
        folder.mkdir()
        (folder / "invoice_alpha.pdf").write_bytes(b"not approved")
        scan_result = scan(self.source, self.config, hash_mode="all")
        plan_path, rows = create_plan(scan_result.run_dir, self.config)
        events = execute_migration_plan(plan_path, self.config)
        self.assertEqual(events, [])
        self.assertFalse(Path(rows[0].destination_path).exists())

    def test_resume_does_not_copy_completed_row_again(self) -> None:
        plan_path, _ = self._approved_plan()
        first = execute_migration_plan(plan_path, self.config)
        second = execute_migration_plan(plan_path, self.config)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        rollback = json.loads(
            (plan_path.parent / "rollback_manifest.json").read_text(encoding="utf-8")
        )
        summary = json.loads(
            (plan_path.parent / "apply_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(rollback["created_files"]), 1)
        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["last_invocation_processed"], 0)

    def test_source_change_after_plan_is_blocked(self) -> None:
        plan_path, source = self._approved_plan()
        source.write_bytes(b"changed after approval")
        events = execute_migration_plan(plan_path, self.config)
        self.assertTrue(events[0]["result"].startswith("error: source"))

    def test_approval_destination_cannot_escape_root(self) -> None:
        folder = self.source / "client-alpha"
        folder.mkdir()
        (folder / "invoice_alpha.pdf").write_bytes(b"content")
        scan_result = scan(self.source, self.config, hash_mode="all")
        plan_path, rows = create_plan(scan_result.run_dir, self.config)
        with self.assertRaises(ValueError):
            approve_migration_row(
                plan_path, rows[0].row_id, self.config, "../outside.pdf"
            )
        self.assertNotEqual(
            effective_migration_plan(plan_path)[0].review_status, "approved"
        )


if __name__ == "__main__":
    unittest.main()
