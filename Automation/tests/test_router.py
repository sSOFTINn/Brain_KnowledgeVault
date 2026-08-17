from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.router import (
    approve_route,
    classify,
    create_run,
    effective_plan,
    execute_plan,
    file_sha256,
    inventory,
    load_plan,
)


CONFIG = """
schema_version = 1
root = "."

[paths]
vault = "Vault"
workspaces = "Workspaces"
assets = "Assets"
private = "Private"
runtime = "Runtime"
staging = "Staging"
logs = "Logs"
inbox = "Staging/Inbox"
processed = "Staging/Processed"
routing_runtime = "Runtime/routing"

[scan]
follow_symlinks = false
hash_mode = "duplicates"
max_workers = 2

[migration]
default_mode = "copy"
verify_hash = true
preserve_timestamps = true
overwrite = false

[git]
enabled = false
max_tracked_file_mb = 10

[privacy]
default_visibility = "internal"
allow_ai_confidential = false

[routing]
auto_threshold = 0.90
preserve_source = true

[[projects]]
code = "PRJ-001"
name = "Alpha"
aliases = ["alpha-project"]
keywords = ["alpha", "invoice"]
source_hints = ["client-alpha"]

[[projects]]
code = "PRJ-002"
name = "Beta"
aliases = ["beta-project"]
keywords = ["beta"]
source_hints = ["client-beta"]

[[rules]]
name = "documents"
extensions = [".pdf", ".docx"]
destination = "Assets/Projects/{project_code}/docs"

[[rules]]
name = "data"
extensions = [".csv", ".xlsx"]
destination = "Assets/Projects/{project_code}/data"
"""


class RouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "vault.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(self.config_path)
        self.config.inbox.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_high_confidence_route_is_approved(self) -> None:
        source = self.config.inbox / "client-alpha" / "invoice_alpha.pdf"
        source.parent.mkdir()
        source.write_bytes(b"alpha invoice")
        route = classify(source, self.config)
        self.assertEqual(route.status, "approved")
        self.assertEqual(route.project_code, "PRJ-001")

    def test_unknown_project_requires_review(self) -> None:
        source = self.config.inbox / "random.pdf"
        source.write_bytes(b"unknown")
        route = classify(source, self.config)
        self.assertEqual(route.status, "review")
        self.assertIsNone(route.project_code)

    def test_execute_copies_and_verifies_without_deleting_source(self) -> None:
        source = self.config.inbox / "client-alpha" / "invoice_alpha.pdf"
        source.parent.mkdir()
        source.write_bytes(b"verified content")
        run_dir = create_run(self.config, inventory(self.config))
        executed = execute_plan(run_dir / "route_plan.jsonl", self.config)
        destination = Path(executed[0].destination)
        self.assertTrue(source.exists())
        self.assertTrue(destination.exists())
        self.assertEqual(file_sha256(source), file_sha256(destination))
        self.assertEqual(executed[0].result, "copied and verified")

    def test_exact_duplicate_is_skipped(self) -> None:
        source = self.config.inbox / "client-alpha" / "invoice_alpha.pdf"
        source.parent.mkdir()
        source.write_bytes(b"same")
        route = classify(source, self.config)
        destination = Path(route.destination)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"same")
        run_dir = create_run(self.config, [route])
        executed = execute_plan(run_dir / "route_plan.jsonl", self.config)
        self.assertEqual(executed[0].result, "skipped: exact duplicate")

    def test_collision_gets_hash_suffix(self) -> None:
        source = self.config.inbox / "client-alpha" / "invoice_alpha.pdf"
        source.parent.mkdir()
        source.write_bytes(b"new content")
        route = classify(source, self.config)
        original = Path(route.destination)
        original.parent.mkdir(parents=True)
        original.write_bytes(b"old content")
        run_dir = create_run(self.config, [route])
        executed = execute_plan(run_dir / "route_plan.jsonl", self.config)
        destination = Path(executed[0].destination)
        self.assertNotEqual(destination, original)
        self.assertIn(file_sha256(source)[:8], destination.name)

    def test_manual_approval_is_append_only(self) -> None:
        source = self.config.inbox / "random.pdf"
        source.write_bytes(b"unknown")
        run_dir = create_run(self.config, [classify(source, self.config)])
        plan = run_dir / "route_plan.jsonl"
        original = plan.read_bytes()
        route_id = load_plan(plan)[0].route_id
        approve_route(plan, route_id, self.config, "Assets/Unassigned/random.pdf")
        self.assertEqual(plan.read_bytes(), original)
        self.assertEqual(effective_plan(plan)[0].status, "approved")

    def test_manual_destination_cannot_escape_root(self) -> None:
        source = self.config.inbox / "random.pdf"
        source.write_bytes(b"unknown")
        run_dir = create_run(self.config, [classify(source, self.config)])
        route_id = load_plan(run_dir / "route_plan.jsonl")[0].route_id
        with self.assertRaises(ValueError):
            approve_route(run_dir / "route_plan.jsonl", route_id, self.config, "../escape.pdf")

    def test_changed_source_is_not_copied(self) -> None:
        source = self.config.inbox / "client-alpha" / "invoice_alpha.pdf"
        source.parent.mkdir()
        source.write_bytes(b"before")
        run_dir = create_run(self.config, inventory(self.config))
        source.write_bytes(b"after and changed")
        executed = execute_plan(run_dir / "route_plan.jsonl", self.config)
        self.assertEqual(executed[0].result, "error: source changed after planning")


if __name__ == "__main__":
    unittest.main()
