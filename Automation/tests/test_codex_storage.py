from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.cli import main as cli_main
from vaultctl.codex_storage import audit_codex_storage, create_codex_cleanup_plan
from vaultctl.config import load_config, validate_config
from vaultctl.doctor import run_doctor
from vaultctl.storage import bootstrap_storage


EXAMPLE = Path(__file__).resolve().parents[1] / "vault.toml.example"


class CodexStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "KnowledgeVault"
        self.profile = self.base / "Profile"
        self.temp_root = self.profile / "AppData" / "Local" / "Temp"
        self.temp_root.mkdir(parents=True)
        self.config = load_config(EXAMPLE, root_override=self.root)
        bootstrap_storage(self.config)
        self.environment = {
            "USERPROFILE": str(self.profile),
            "TEMP": str(self.temp_root),
            "CODEX_HOME": str(self.config.codex_storage.home),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_audit_classifies_paths_without_changing_sources(self) -> None:
        documents = self.profile / "Documents"
        documents.mkdir()
        report = documents / "codex_search.txt"
        report.write_text("inventory", encoding="utf-8")
        clipboard = self.temp_root / "codex-clipboard-test.png"
        clipboard.write_bytes(b"png")
        docs_cache = self.temp_root / "openai-docs-cache"
        docs_cache.mkdir()
        (docs_cache / "manual.md").write_text("docs", encoding="utf-8")
        protected = self.profile / "AppData" / "Local" / "OpenAI" / "Codex"
        protected.mkdir(parents=True)
        (protected / "runtime.bin").write_bytes(b"runtime")

        output, payload = audit_codex_storage(
            self.config,
            home=self.profile,
            temp=self.temp_root,
            environment=self.environment,
            now=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(output.is_file())
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["codex_home_matches"])
        self.assertEqual(payload["cleanup_candidate_count"], 3)
        self.assertTrue(report.is_file())
        self.assertTrue(clipboard.is_file())
        self.assertTrue(docs_cache.is_dir())
        runtime = next(
            item
            for item in payload["protected_windows_paths"]
            if item["category"] == "desktop-runtime"
        )
        self.assertEqual(runtime["disposition"], "leave-in-place")
        self.assertTrue(runtime["protected"])

    def test_audit_detects_codex_home_drift(self) -> None:
        environment = {**self.environment, "CODEX_HOME": str(self.profile / ".codex")}
        _, payload = audit_codex_storage(
            self.config,
            home=self.profile,
            temp=self.temp_root,
            environment=environment,
        )
        self.assertFalse(payload["codex_home_matches"])

    def test_cleanup_plan_is_hash_backed_and_never_executes(self) -> None:
        documents = self.profile / "Documents"
        documents.mkdir()
        old = documents / "codex_search.txt"
        old.write_text("old inventory", encoding="utf-8")
        recent = self.temp_root / "codex-clipboard-recent.png"
        recent.write_bytes(b"recent")
        docs_cache = self.temp_root / "openai-docs-cache"
        docs_cache.mkdir()
        cached_manual = docs_cache / "manual.md"
        cached_manual.write_text("cached docs", encoding="utf-8")
        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        old_timestamp = now.timestamp() - (30 * 86400)
        os.utime(old, (old_timestamp, old_timestamp))
        os.utime(cached_manual, (old_timestamp, old_timestamp))
        os.utime(docs_cache, (old_timestamp, old_timestamp))
        os.utime(recent, (now.timestamp(), now.timestamp()))

        output, payload = create_codex_cleanup_plan(
            self.config,
            home=self.profile,
            temp=self.temp_root,
            retention_days=14,
            environment=self.environment,
            now=now,
        )

        self.assertTrue(output.is_file())
        self.assertFalse(payload["execute_supported"])
        rows = {Path(row["path"]).name: row for row in payload["rows"]}
        self.assertTrue(rows[old.name]["eligible"])
        self.assertEqual(len(rows[old.name]["sha256"]), 64)
        self.assertFalse(rows[recent.name]["eligible"])
        self.assertIsNone(rows[recent.name]["sha256"])
        self.assertTrue(rows[docs_cache.name]["eligible"])
        self.assertEqual(
            rows[docs_cache.name]["file_manifest"][0]["relative_path"],
            "manual.md",
        )
        self.assertEqual(len(rows[docs_cache.name]["file_manifest"][0]["sha256"]), 64)
        self.assertTrue(old.is_file())
        self.assertTrue(recent.is_file())
        self.assertTrue(cached_manual.is_file())

    def test_config_rejects_codex_home_outside_private_boundary(self) -> None:
        invalid = replace(
            self.config,
            codex_storage=replace(
                self.config.codex_storage, home=self.config.runtime / "Codex"
            ),
        )
        with self.assertRaisesRegex(ValueError, "codex_storage.home"):
            validate_config(invalid)

    def test_doctor_detects_codex_home_drift(self) -> None:
        with patch.dict(os.environ, self.environment, clear=False):
            check = next(item for item in run_doctor(self.config) if item.name == "codex-home")
        self.assertEqual(check.level, "PASS")

        with patch.dict(
            os.environ,
            {**self.environment, "CODEX_HOME": str(self.profile / ".codex")},
            clear=False,
        ):
            check = next(item for item in run_doctor(self.config) if item.name == "codex-home")
        self.assertEqual(check.level, "WARN")

    def test_cli_audit_returns_failure_for_wrong_codex_home(self) -> None:
        with patch.dict(
            os.environ,
            {
                "USERPROFILE": str(self.profile),
                "TEMP": str(self.temp_root),
                "CODEX_HOME": str(self.profile / ".codex"),
            },
            clear=False,
        ):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = cli_main(
                    [
                        "codex-storage",
                        "--config",
                        str(EXAMPLE),
                        "--root",
                        str(self.root),
                        "audit",
                        "--home",
                        str(self.profile),
                        "--temp",
                        str(self.temp_root),
                    ]
                )
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
