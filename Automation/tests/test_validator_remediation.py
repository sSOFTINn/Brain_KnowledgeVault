from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.gitpolicy import tracked_files
from vaultctl.metadata import new_uid
from vaultctl.storage import bootstrap_storage
from vaultctl.validator import _is_operational_path, _tree_digest, validate_vault


EXAMPLE = Path(__file__).resolve().parents[1] / "vault.toml.example"


def note(title: str, body: str) -> str:
    today = date.today().isoformat()
    return f"""---
schema_version: 1
uid: {new_uid()}
type: note
title: "{title}"
status: active
created: {today}
updated: {today}
tags: []
aliases: []
visibility: internal
---

# {title}

{body}
"""


class ValidatorRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "KnowledgeVault"
        self.config = load_config(EXAMPLE, root_override=self.root)
        bootstrap_storage(self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_operational_long_paths_are_excluded(self) -> None:
        operational = self.config.tool_state.joinpath(*(["tool-state-segment"] * 16), "state.bin")
        content = self.config.documents.joinpath(*(["content-segment"] * 16), "document.bin")
        nested_git = self.config.workspaces / "Project" / ".git" / "objects" / "pack"
        self.assertTrue(_is_operational_path(operational, self.config))
        self.assertTrue(_is_operational_path(nested_git, self.config))
        self.assertFalse(_is_operational_path(content, self.config))

    def test_qualified_wikilink_resolves_duplicate_stems(self) -> None:
        first = self.config.vault / "GroupA" / "Search.md"
        second = self.config.vault / "GroupB" / "Search.md"
        home = self.config.vault / "GroupA" / "Home.md"
        first.parent.mkdir(parents=True)
        second.parent.mkdir(parents=True)
        first.write_text(note("Search A", "one"), encoding="utf-8")
        second.write_text(note("Search B", "two"), encoding="utf-8")
        home.write_text(note("Home", "[[GroupA/Search|Search]]"), encoding="utf-8")
        findings = validate_vault(self.config)
        self.assertFalse(
            any(item.code in {"broken-wikilink", "ambiguous-wikilink"} and item.path.endswith("Home.md") for item in findings)
        )

    def test_package_sidecar_covers_managed_bundle(self) -> None:
        package = self.config.assets / "OfflineTool"
        package.mkdir(parents=True)
        (package / "setup.exe").write_bytes(b"binary")
        (package / "README.txt").write_text("instructions", encoding="utf-8")
        today = date.today().isoformat()
        digest = _tree_digest(package)
        (package / "PACKAGE.asset.md").write_text(
            f"""---
schema_version: 1
uid: {new_uid()}
type: asset
title: "OfflineTool"
status: active
created: {today}
updated: {today}
tags: []
aliases: []
visibility: internal
asset_kind: package
asset_path: "OfflineTool"
sha256: "{digest}"
source: synthetic
---
""",
            encoding="utf-8",
        )
        findings = validate_vault(self.config)
        self.assertFalse(any(item.code == "missing-sidecar" and "OfflineTool" in item.path for item in findings))
        self.assertFalse(any(item.code.startswith("asset-package") for item in findings))

    def test_v2_git_policy_uses_control_plane_repository(self) -> None:
        repository = self.config.control_plane / "Brain_KnowledgeVault"
        repository.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, stdout=subprocess.PIPE)
        (repository / "tracked.txt").write_text("tracked", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
        root, paths, message = tracked_files(self.config)
        self.assertEqual(root, repository.resolve())
        self.assertEqual(paths, [(repository / "tracked.txt").resolve()])
        self.assertIn("1 tracked files", message)


if __name__ == "__main__":
    unittest.main()
