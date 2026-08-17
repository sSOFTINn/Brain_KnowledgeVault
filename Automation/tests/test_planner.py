from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.planner import create_plan
from vaultctl.scanner import scan

from test_router import CONFIG


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "vault.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(self.config_path)
        self.source = self.root / "source"
        self.source.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_plan_is_deterministic_for_same_inventory(self) -> None:
        folder = self.source / "client-alpha"
        folder.mkdir()
        (folder / "invoice_alpha.pdf").write_bytes(b"invoice")
        scan_result = scan(self.source, self.config, hash_mode="all")
        _, first = create_plan(scan_result.run_dir, self.config)
        _, second = create_plan(scan_result.run_dir, self.config)
        self.assertEqual(first, second)

    def test_low_confidence_is_never_auto_approved(self) -> None:
        (self.source / "unknown.bin").write_bytes(b"unknown")
        scan_result = scan(self.source, self.config, hash_mode="all")
        _, rows = create_plan(scan_result.run_dir, self.config)
        self.assertEqual(rows[0].operation, "manual-review")
        self.assertEqual(rows[0].review_status, "manual")

    def test_exact_duplicate_is_marked_skip(self) -> None:
        (self.source / "one.bin").write_bytes(b"same")
        (self.source / "two.bin").write_bytes(b"same")
        scan_result = scan(self.source, self.config, hash_mode="duplicates")
        _, rows = create_plan(scan_result.run_dir, self.config)
        self.assertEqual(sum(row.exact_duplicate for row in rows), 1)
        duplicate = next(row for row in rows if row.exact_duplicate)
        self.assertEqual(duplicate.operation, "skip")

    def test_same_destination_is_manual_collision(self) -> None:
        first = self.source / "client-alpha"
        second = self.source / "other" / "client-alpha"
        first.mkdir()
        second.mkdir(parents=True)
        (first / "invoice_alpha.pdf").write_bytes(b"first")
        (second / "invoice_alpha.pdf").write_bytes(b"second")
        scan_result = scan(self.source, self.config, hash_mode="all")
        _, rows = create_plan(scan_result.run_dir, self.config)
        self.assertTrue(any(row.name_collision for row in rows))
        self.assertTrue(
            all(row.review_status == "manual" for row in rows if row.name_collision)
        )

    def test_plan_writes_all_review_artifacts(self) -> None:
        (self.source / "unknown.txt").write_text("text", encoding="utf-8")
        scan_result = scan(self.source, self.config)
        plan_path, _ = create_plan(scan_result.run_dir, self.config)
        self.assertTrue(plan_path.is_file())
        for name in ("migration_plan.csv", "migration_plan.md", "conflicts.md"):
            self.assertTrue((scan_result.run_dir / name).is_file())


if __name__ == "__main__":
    unittest.main()
