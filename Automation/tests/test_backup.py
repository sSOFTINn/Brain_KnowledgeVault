from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.backup import (
    backup_check,
    backup_freshness,
    backup_init,
    backup_restore_drill,
    backup_run,
    backup_snapshots,
    ensure_password_file,
    find_restic,
    password_acl_health,
)
from vaultctl.config import load_config
from vaultctl.doctor import run_doctor
from vaultctl.scaffold import initialize

from test_router import CONFIG


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config_path = self.root / "source.toml"
        config_path.write_text(CONFIG, encoding="utf-8")
        config = load_config(config_path)
        backup = replace(
            config.backup,
            repository=self.root / "repository",
            password_file=self.root / "secrets" / "password.txt",
            includes=(config.vault, config.root / "vault.toml"),
            excludes=("**/__pycache__/**",),
            keep_daily=2,
            keep_weekly=2,
            keep_monthly=2,
            max_snapshot_age_days=7,
            critical_paths=(
                config.vault / "00_System" / "Home.md",
                config.root / "vault.toml",
            ),
        )
        self.config = replace(config, backup=backup)
        initialize(self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_password_repository_backup_check_and_restore(self) -> None:
        self.assertTrue(find_restic().is_file())
        password = ensure_password_file(self.config)
        self.assertTrue(password.is_file())
        acl_ok, acl_message = password_acl_health(self.config)
        self.assertTrue(acl_ok, acl_message)
        backup_init(self.config)
        backup_run(self.config)
        self.assertTrue(backup_snapshots(self.config))
        fresh, freshness_message = backup_freshness(self.config)
        self.assertTrue(fresh, freshness_message)
        self.assertIn("no errors were found", backup_check(self.config).output.lower())
        result = backup_restore_drill(self.config)
        self.assertGreaterEqual(result["count"], 2)
        self.assertIn("root:Vault/00_System/Home.md", result["verified"])
        self.assertIn("root:vault.toml", result["verified"])

    @unittest.skipUnless(os.name == "nt", "Windows ACL test")
    def test_password_acl_removes_preexisting_explicit_system_rule(self) -> None:
        password = ensure_password_file(self.config)
        added = subprocess.run(
            ["icacls.exe", str(password), "/grant", "*S-1-5-18:(F)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(added.returncode, 0, added.stdout)
        self.assertFalse(password_acl_health(self.config)[0])

        ensure_password_file(self.config)
        ok, message = password_acl_health(self.config)
        self.assertTrue(ok, message)

    @unittest.skipUnless(os.name == "nt", "Windows ACL test")
    def test_password_acl_accepts_local_administrator_sddl_alias(self) -> None:
        ensure_password_file(self.config)
        administrator_sid = "S-1-5-21-111111111-222222222-333333333-500"
        with patch(
            "vaultctl.backup._current_windows_identity",
            return_value=("runneradmin", administrator_sid),
        ), patch(
            "vaultctl.backup._saved_acl_sddl",
            return_value="D:PAI(A;;FA;;;LA)",
        ):
            ok, message = password_acl_health(self.config)
        self.assertTrue(ok, message)

    def test_restore_drill_rejects_missing_or_excluded_critical_paths(self) -> None:
        ensure_password_file(self.config)
        backup_init(self.config)
        backup_run(self.config)

        missing = replace(
            self.config,
            backup=replace(
                self.config.backup,
                critical_paths=(self.config.root / "missing.md",),
            ),
        )
        with self.assertRaises(FileNotFoundError):
            backup_restore_drill(missing)

        outside = self.root / "outside.txt"
        outside.write_text("not backed up", encoding="utf-8")
        excluded = replace(
            self.config,
            backup=replace(self.config.backup, critical_paths=(outside,)),
        )
        with self.assertRaises(ValueError):
            backup_restore_drill(excluded)

    def test_doctor_distinguishes_uninitialized_from_broken_backup(self) -> None:
        checks = {item.name: item for item in run_doctor(self.config)}
        self.assertEqual(checks["backup-password-acl"].level, "WARN")
        self.config.backup.repository.mkdir(parents=True)
        (self.config.backup.repository / "config").write_text("initialized", encoding="utf-8")
        checks = {item.name: item for item in run_doctor(self.config)}
        self.assertEqual(checks["backup-password-acl"].level, "FAIL")


if __name__ == "__main__":
    unittest.main()
