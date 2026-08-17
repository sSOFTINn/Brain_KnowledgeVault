from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.ask import _bounded_sources
from vaultctl.config import load_config, validate_config
from vaultctl.doctor import run_doctor
from vaultctl.scaffold import initialize
from vaultctl.scanner import scan
from vaultctl.validator import validate_vault

from test_router import CONFIG


class ConfigBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config_path = self.root / "vault.toml"
        config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(config_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_scanner_uses_configured_worker_count(self) -> None:
        source = self.root / "source"
        source.mkdir()
        for index in range(4):
            (source / f"file-{index}.txt").write_text(str(index), encoding="utf-8")
        config = replace(self.config, max_workers=3)
        with patch("vaultctl.scanner.ThreadPoolExecutor", wraps=ThreadPoolExecutor) as pool:
            result = scan(source, config, hash_mode="all")
        pool.assert_called_once_with(max_workers=3)
        run = json.loads((result.run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["max_workers"], 3)
        self.assertTrue(all(item.sha256 for item in result.items))

    def test_llm_context_limit_bounds_sources(self) -> None:
        config = replace(
            self.config,
            llm=replace(self.config.llm, context_limit_tokens=512),
        )
        sources = [
            {
                "chunk_id": str(index),
                "title": f"Source {index}",
                "source_path": f"Vault/{index}.md",
                "heading_path": "Heading",
                "snippet": "x" * 1000,
            }
            for index in range(4)
        ]
        bounded = _bounded_sources(config, "question", sources)
        self.assertGreaterEqual(len(bounded), 1)
        self.assertLess(len(bounded), len(sources))

    def test_git_size_guard_applies_only_when_enabled(self) -> None:
        initialize(self.config)
        large = self.config.vault / "large.bin"
        large.write_bytes(b"x" * (1024 * 1024 + 1))
        subprocess.run(
            ["git", "init", str(self.config.vault)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.config.vault), "add", "large.bin"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        enabled = replace(self.config, git_enabled=True, max_tracked_file_mb=1)
        enabled_findings = validate_vault(enabled)
        self.assertTrue(
            any(item.code == "git-tracked-file-too-large" for item in enabled_findings)
        )
        disabled_findings = validate_vault(replace(enabled, git_enabled=False))
        self.assertFalse(
            any(item.code == "git-tracked-file-too-large" for item in disabled_findings)
        )

    def test_doctor_reports_effective_knobs(self) -> None:
        initialize(self.config)
        names = {item.name for item in run_doctor(self.config)}
        self.assertTrue({"scan-workers", "git-policy", "llm-context", "rag-effective"} <= names)

    def test_exposed_limits_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_workers"):
            validate_config(replace(self.config, max_workers=0))
        with self.assertRaisesRegex(ValueError, "max_tracked_file_mb"):
            validate_config(replace(self.config, max_tracked_file_mb=0))
        with self.assertRaisesRegex(ValueError, "context_limit_tokens"):
            validate_config(
                replace(
                    self.config,
                    llm=replace(self.config.llm, context_limit_tokens=128),
                )
            )


if __name__ == "__main__":
    unittest.main()
