from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.scanner import scan

from test_router import CONFIG


def snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            info = path.stat()
            result[path.relative_to(root).as_posix()] = (
                info.st_size,
                info.st_mtime_ns,
                sha256(path.read_bytes()).hexdigest(),
            )
    return result


class ScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.config_path = self.base / "vault.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(self.config_path)
        self.source = self.base / "source"
        self.source.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_scan_is_read_only_and_writes_complete_run(self) -> None:
        (self.source / "Клієнт Alpha").mkdir()
        (self.source / "Клієнт Alpha" / "invoice_alpha.pdf").write_bytes(b"invoice")
        (self.source / "notes.txt").write_text("hello", encoding="utf-8")
        before = snapshot(self.source)

        result = scan(self.source, self.config, hash_mode="all")

        self.assertEqual(before, snapshot(self.source))
        self.assertEqual(len(result.items), 2)
        for name in (
            "run.json",
            "inventory.jsonl",
            "inventory.csv",
            "errors.jsonl",
            "summary.json",
            "report.md",
        ):
            self.assertTrue((result.run_dir / name).is_file(), name)
        self.assertTrue(all(item.sha256 for item in result.items))
        self.assertEqual(
            (self.config.runtime / "runs" / "latest.txt").read_text(encoding="utf-8").strip(),
            result.run_id,
        )

    def test_duplicate_mode_hashes_only_equal_sizes(self) -> None:
        (self.source / "one.bin").write_bytes(b"same")
        (self.source / "two.bin").write_bytes(b"same")
        (self.source / "three.bin").write_bytes(b"different length")
        result = scan(self.source, self.config, hash_mode="duplicates")
        hashed = [item for item in result.items if item.sha256]
        self.assertEqual(len(hashed), 2)
        self.assertTrue(all(item.duplicate_candidate for item in hashed))

    def test_excluded_directory_is_not_scanned(self) -> None:
        excluded = self.source / "node_modules"
        excluded.mkdir()
        (excluded / "secret.txt").write_text("ignored", encoding="utf-8")
        (self.source / "visible.txt").write_text("visible", encoding="utf-8")
        result = scan(self.source, self.config)
        self.assertEqual([item.filename for item in result.items], ["visible.txt"])
        self.assertEqual(result.skipped["excluded"], 1)

    def test_filesystem_root_requires_explicit_override(self) -> None:
        with self.assertRaises(ValueError):
            scan(Path(self.source.anchor), self.config)

    def test_summary_is_valid_and_paths_stay_local_to_runtime(self) -> None:
        (self.source / "file.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        result = scan(self.source, self.config)
        summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["files"], 1)
        self.assertTrue(result.run_dir.is_relative_to(self.config.runtime))

    def test_static_fixture_covers_unicode_duplicates_and_exclusions(self) -> None:
        fixture = Path(__file__).parent / "fixtures"
        shutil.copytree(fixture, self.source, dirs_exist_ok=True)
        result = scan(self.source, self.config, hash_mode="duplicates")
        names = {item.relative_path for item in result.items}
        self.assertIn("Клієнт Alpha/invoice_alpha.pdf", names)
        self.assertIn("without_extension", names)
        self.assertNotIn("node_modules/ignored.txt", names)
        duplicates = [item for item in result.items if item.sha256]
        self.assertEqual(len(duplicates), 2)


if __name__ == "__main__":
    unittest.main()
