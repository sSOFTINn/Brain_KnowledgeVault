from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.extractor import rebuild_extractions
from vaultctl.indexer import rebuild_index, search_index
from vaultctl.metadata import new_uid, today
from vaultctl.scaffold import initialize
from vaultctl.suggestions import generate_suggestions
from vaultctl.validator import validate_vault

from test_router import CONFIG


class IntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config_path = self.root / "source.toml"
        config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(config_path)
        initialize(self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _asset(self, name: str, content: str, visibility: str = "internal") -> Path:
        asset = self.config.assets / "Projects/PRJ-001/docs" / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text(content, encoding="utf-8")
        digest = sha256(asset.read_bytes()).hexdigest()
        sidecar = asset.with_name(asset.name + ".asset.md")
        sidecar.write_text(
            f"""---
schema_version: 1
uid: {new_uid()}
type: asset
title: "{name}"
status: active
created: {today()}
updated: {today()}
tags:
  - extracted
aliases: []
visibility: {visibility}
project_code: "PRJ-001"
sha256: "{digest}"
source: "test"
asset_path: "Projects/PRJ-001/docs/{name}"
---
""",
            encoding="utf-8",
        )
        return asset

    def test_bases_are_created(self) -> None:
        for name in ("Projects.base", "Records.base", "Inbox.base"):
            self.assertTrue((self.config.vault / "91_Views" / name).is_file())

    def test_extraction_enters_fts_and_confidential_is_skipped(self) -> None:
        self._asset("public.txt", "унікальний локальний інтелект")
        self._asset("secret.txt", "SECRET-EXTRACT-TOKEN", "confidential")
        _, results = rebuild_extractions(self.config)
        self.assertEqual(sum(item.status == "extracted" for item in results), 1)
        rebuild_index(self.config)
        self.assertTrue(search_index(self.config, "інтелект"))
        self.assertEqual(search_index(self.config, "SECRET"), [])

    def test_suggestions_are_runtime_only(self) -> None:
        self._asset("one.txt", "same")
        self._asset("two.txt", "same")
        output = generate_suggestions(self.config, "duplicates")
        data = json.loads((output / "suggestions.json").read_text(encoding="utf-8"))
        self.assertTrue(data["duplicates"])
        self.assertTrue(output.is_relative_to(self.config.runtime))

    def test_asset_sidecar_hash_is_validated(self) -> None:
        asset = self._asset("checked.txt", "original")
        self.assertFalse(
            any(item.code.startswith("asset-sidecar") for item in validate_vault(self.config))
        )
        asset.write_text("changed", encoding="utf-8")
        self.assertTrue(
            any(item.code == "asset-sidecar-hash" for item in validate_vault(self.config))
        )


if __name__ == "__main__":
    unittest.main()
