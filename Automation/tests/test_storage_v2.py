from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import discover_config_path, load_config
from vaultctl.cli import main as cli_main
from vaultctl.backup import (
    backup_check,
    backup_init,
    backup_preflight,
    backup_restore_drill,
    backup_run,
)
from vaultctl.doctor import has_failures, run_doctor
from vaultctl.indexer import rebuild_index, search_index
from vaultctl.rag.chunker import iter_sources
from vaultctl.repositories import (
    apply_repository_plan,
    approve_repository,
    create_repository_plan,
    verify_repository_plan,
)
from vaultctl.policy import can_read_path
from vaultctl.storage import (
    VolumeIdentity,
    audit_storage,
    bootstrap_storage,
    validate_storage_marker,
)
from vaultctl.validator import has_errors, validate_vault


EXAMPLE = Path(__file__).resolve().parents[1] / "vault.toml.example"


class StorageV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "KnowledgeVault"
        self.config = load_config(EXAMPLE, root_override=self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_dry_run_writes_nothing(self) -> None:
        result = bootstrap_storage(self.config, dry_run=True)
        self.assertTrue(result.created)
        self.assertFalse(self.root.exists())
        self.assertEqual(
            cli_main(
                [
                    "bootstrap",
                    "--config",
                    str(EXAMPLE),
                    "--root",
                    str(self.root),
                    "--dry-run",
                ]
            ),
            0,
        )
        self.assertFalse(self.root.exists())

    def test_bootstrap_is_idempotent_and_valid(self) -> None:
        first = bootstrap_storage(self.config)
        second = bootstrap_storage(self.config)
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        marker = validate_storage_marker(self.config)
        self.assertEqual(marker["schema_version"], 2)
        generated = load_config(self.root / "vault.toml.local")
        self.assertEqual(generated.schema_version, 2)
        self.assertEqual(generated.root, self.root.resolve())
        self.assertFalse((self.root / ".git").exists())
        self.assertFalse(has_failures(run_doctor(self.config)))
        self.assertFalse(has_errors(validate_vault(self.config)))
        audit = audit_storage(self.config)
        self.assertTrue(audit.marker_valid)
        self.assertFalse(audit.missing_directories)
        self.assertFalse(audit.unexpected_root_git)

    def test_nonempty_unmarked_target_is_blocked(self) -> None:
        self.root.mkdir()
        (self.root / "user-file.txt").write_text("preserve", encoding="utf-8")
        with self.assertRaises(ValueError):
            bootstrap_storage(self.config)
        self.assertEqual(
            (self.root / "user-file.txt").read_text(encoding="utf-8"), "preserve"
        )

    def test_local_root_config_precedes_tracked_fallback(self) -> None:
        self.root.mkdir()
        local = self.root / "vault.toml.local"
        local.write_text("schema_version = 2\nroot = '.'\n", encoding="utf-8")
        self.assertEqual(discover_config_path(None, self.root), local.resolve())

    def test_repository_is_copied_as_one_verified_unit(self) -> None:
        bootstrap_storage(self.config)
        source_parent = self.base / "sources"
        repository = source_parent / "Project Alpha"
        repository.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, stdout=subprocess.PIPE)
        subprocess.run(["git", "config", "user.name", "Storage Test"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.email", "storage@example.invalid"], cwd=repository, check=True)
        (repository / "tracked.txt").write_text("tracked", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repository, check=True, stdout=subprocess.PIPE)
        (repository / "untracked.txt").write_text("untracked", encoding="utf-8")
        unicode_file = repository / "документація" / (("довгий_" * 20) + ".md")
        unicode_file.parent.mkdir()
        unicode_file.write_text("unicode long path", encoding="utf-8")
        nested = repository / "vendor" / "Nested Repo"
        nested.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=nested, check=True, stdout=subprocess.PIPE)
        subprocess.run(["git", "config", "user.name", "Storage Test"], cwd=nested, check=True)
        subprocess.run(["git", "config", "user.email", "storage@example.invalid"], cwd=nested, check=True)
        (nested / "nested.txt").write_text("nested", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=nested, check=True)
        subprocess.run(["git", "commit", "-m", "Nested"], cwd=nested, check=True, stdout=subprocess.PIPE)

        plan, records = create_repository_plan(self.config, [source_parent])
        self.assertEqual(len(records), 1)
        self.assertGreaterEqual(records[0].dirty_entries, 3)
        self.assertGreaterEqual(records[0].ignored_entries, 0)
        self.assertEqual(records[0].nested_repositories, ("vendor/Nested Repo",))
        self.assertGreater(records[0].file_count, 2)
        approve_repository(plan, records[0].repository_id, self.config, note="test")
        events = apply_repository_plan(plan, self.config)
        self.assertEqual(events[0]["result"], "copied and verified")
        results = verify_repository_plan(plan)
        self.assertTrue(results[0]["verified"])
        destination = Path(records[0].destination)
        self.assertTrue((destination / ".git").is_dir())
        self.assertEqual((destination / "untracked.txt").read_text(encoding="utf-8"), "untracked")
        self.assertEqual((destination / unicode_file.relative_to(repository)).read_text(encoding="utf-8"), "unicode long path")
        self.assertTrue((self.root / "00_System/Audit/storage-events.jsonl").is_file())

    def test_repository_plan_is_immutable(self) -> None:
        bootstrap_storage(self.config)
        repository = self.base / "source" / "Repo"
        repository.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, stdout=subprocess.PIPE)
        subprocess.run(["git", "config", "user.name", "Storage Test"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.email", "storage@example.invalid"], cwd=repository, check=True)
        (repository / "file.txt").write_text("one", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repository, check=True, stdout=subprocess.PIPE)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/sSOFTINn/Brain_KnowledgeVault.git"],
            cwd=repository,
            check=True,
        )
        plan, records = create_repository_plan(self.config, [repository.parent])
        self.assertEqual(
            Path(records[0].destination),
            self.config.control_plane / "Brain_KnowledgeVault",
        )
        plan.write_text(plan.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            approve_repository(plan, records[0].repository_id, self.config)

    def test_v2_index_includes_documents_and_excludes_private(self) -> None:
        bootstrap_storage(self.config)
        document = self.root / "30_Documents/Work/visible.md"
        document.write_text("# Visible\n\nvisibleunique storage fact", encoding="utf-8")
        private = self.root / "60_Private/secret.md"
        private.write_text("# Secret\n\nsecretunique private fact", encoding="utf-8")
        summary = rebuild_index(self.config)
        self.assertGreaterEqual(summary.objects, 1)
        self.assertTrue(search_index(self.config, "visibleunique"))
        self.assertFalse(search_index(self.config, "secretunique"))
        sources = iter_sources(self.config)
        self.assertTrue(any(item.source_path.endswith("visible.md") for item in sources))
        self.assertFalse(any("60_Private" in item.source_path for item in sources))

    def test_junction_component_is_denied_without_traversal(self) -> None:
        bootstrap_storage(self.config)
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "Outside.md").write_text("outside", encoding="utf-8")
        junction = self.root / "20_Knowledge" / "Junction"
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            self.skipTest(f"junction creation unavailable: {result.stdout}")
        decision = can_read_path(junction / "Outside.md", self.config, "wiki")
        self.assertFalse(decision.allowed)
        audit = audit_storage(self.config)
        self.assertTrue(any(item["path"] == "20_Knowledge/Junction" for item in audit.reparse_points))

    def test_backup_preflight_blocks_unhealthy_same_disk_and_low_space(self) -> None:
        bootstrap_storage(self.config)
        unhealthy = VolumeIdentity(
            root="X:\\",
            label="BACKUP",
            serial="11111111",
            filesystem="NTFS",
            disk_id="same-disk",
            health_status="Warning",
            operational_status="Full Repair Needed",
        )
        with patch("vaultctl.backup.get_volume_identity", return_value=unhealthy), patch(
            "vaultctl.backup.shutil.disk_usage",
            return_value=shutil._ntuple_diskusage(total=100, used=99, free=1),
        ):
            checks = backup_preflight(self.config)
        failures = {item.name for item in checks if item.level == "FAIL"}
        self.assertIn("backup-volume-health", failures)
        self.assertIn("physical-separation", failures)
        self.assertIn("backup-free-space", failures)

    def test_v2_disposable_backup_and_restore_drill(self) -> None:
        bootstrap_storage(self.config)
        healthy = VolumeIdentity(
            root="X:\\",
            label="BACKUP",
            serial="22222222",
            filesystem="NTFS",
            disk_id="backup-disk",
            health_status="Healthy",
            operational_status="OK",
        )
        config = replace(
            self.config,
            machine=replace(
                self.config.machine,
                require_distinct_physical_disks=False,
            ),
            backup=replace(
                self.config.backup,
                repository=self.base / "restic-repository",
                password_file=self.base / "secrets" / "restic-password.txt",
                minimum_free_gib=1,
            ),
        )
        with patch("vaultctl.backup.get_volume_identity", return_value=healthy):
            backup_init(config)
            backup_run(config)
            self.assertIn("no errors were found", backup_check(config).output.lower())
            result = backup_restore_drill(config)
        self.assertEqual(result["count"], 3)


if __name__ == "__main__":
    unittest.main()
