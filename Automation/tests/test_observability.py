from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
import json
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.cli import main
from vaultctl.config import load_config, validate_config
from vaultctl.event_log import write_event

from test_router import CONFIG


class ObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "vault.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(self.config_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_event_log_redacts_sensitive_fields(self) -> None:
        secret = "NEVER_WRITE_THIS_SECRET"
        path = write_event(
            self.config,
            {
                "event": "unit",
                "command": "ask",
                "api_token": secret,
                "query": secret,
                "nested": {"password": secret},
            },
        )
        self.assertIsNotNone(path)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn(secret, text)
        event = json.loads(text)
        self.assertEqual(event["api_token"], "[REDACTED]")
        self.assertEqual(event["nested"]["password"], "[REDACTED]")

    def test_rotation_keeps_valid_jsonl(self) -> None:
        config = replace(
            self.config,
            logging=replace(self.config.logging, max_bytes=1024, backup_count=2),
        )
        for index in range(4):
            write_event(config, {"event": "rotation", "index": index, "details": "x" * 700})
        active = config.logs / "vaultctl.jsonl"
        rotated = config.logs / "vaultctl.jsonl.1"
        self.assertTrue(active.is_file())
        self.assertTrue(rotated.is_file())
        for path in (active, rotated):
            for line in path.read_text(encoding="utf-8").splitlines():
                json.loads(line)

    def test_cli_log_contains_no_arguments_or_output_text(self) -> None:
        with redirect_stdout(StringIO()):
            exit_code = main(
                ["init", "--config", str(self.config_path), "--dry-run"]
            )
        self.assertEqual(exit_code, 0)
        event = json.loads(
            (self.config.logs / "vaultctl.jsonl").read_text(encoding="utf-8")
        )
        self.assertEqual(event["command"], "init")
        self.assertEqual(event["status"], "ok")
        serialized = json.dumps(event)
        self.assertNotIn(str(self.config_path), serialized)
        self.assertNotIn("WOULD CREATE", serialized)

    def test_logging_limits_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_bytes"):
            validate_config(
                replace(
                    self.config,
                    logging=replace(self.config.logging, max_bytes=100),
                )
            )

    def test_runtime_lock_uses_exact_versions(self) -> None:
        lock = Path(__file__).resolve().parents[1] / "requirements.lock"
        packages = [
            line.strip()
            for line in lock.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(packages)
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_.-]+==[^=\s]+", item) for item in packages))


if __name__ == "__main__":
    unittest.main()
