from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.migrator import approve_migration_row, execute_migration_plan
from vaultctl.operations import create_cleanup_plan, generate_report, verify_run
from vaultctl.planner import create_plan
from vaultctl.scanner import scan

from test_router import CONFIG


class OperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config_path = self.root / "vault.toml"
        config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(config_path)
        source = self.root / "source/client-alpha"
        source.mkdir(parents=True)
        (source / "invoice_alpha.pdf").write_bytes(b"operations")
        scanned = scan(self.root / "source", self.config, hash_mode="all")
        self.plan, rows = create_plan(scanned.run_dir, self.config)
        approve_migration_row(self.plan, rows[0].row_id, self.config)
        execute_migration_plan(self.plan, self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_report_verify_and_cleanup_plan(self) -> None:
        report = generate_report(self.plan.parent, self.config)
        verification, rows = verify_run(self.plan.parent, self.config)
        self.assertTrue(report.is_file())
        self.assertTrue(verification.is_file())
        self.assertEqual(len(rows), 1)
        with patch("vaultctl.operations.backup_snapshots", return_value=[{"id": "one"}]):
            cleanup = create_cleanup_plan(self.plan.parent, self.config, 30)
        data = json.loads(cleanup.read_text(encoding="utf-8"))
        self.assertFalse(data["candidates"][0]["eligible"])
        self.assertEqual(data["candidates"][0]["action"], "manual-review-only")


if __name__ == "__main__":
    unittest.main()
