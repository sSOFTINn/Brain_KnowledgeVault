from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config
from vaultctl.indexer import integrity_check, rebuild_index, search_index
from vaultctl.metadata import new_uid, today
from vaultctl.scaffold import initialize

from test_router import CONFIG


class IndexerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "source.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(self.config_path)
        initialize(self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _note(self, name: str, title: str, body: str, tags: list[str] | None = None) -> Path:
        path = self.config.vault / "04_Knowledge/Concepts" / name
        tag_yaml = "\n".join(f"  - {tag}" for tag in (tags or []))
        text = f"""---
schema_version: 1
uid: {new_uid()}
type: note
title: "{title}"
status: active
created: {today()}
updated: {today()}
tags:
{tag_yaml if tag_yaml else '  []'}
aliases: []
visibility: internal
---

# {title}

{body}
"""
        path.write_text(text, encoding="utf-8")
        return path

    def test_rebuild_and_multilingual_search(self) -> None:
        self._note("Local_First.md", "Локальне сховище", "Local-first knowledge система", ["architecture"])
        summary = rebuild_index(self.config)
        self.assertGreater(summary.objects, 0)
        self.assertTrue(summary.database.is_file())
        self.assertTrue(search_index(self.config, "Локальне"))
        self.assertTrue(search_index(self.config, "knowledge"))
        self.assertTrue(integrity_check(self.config).startswith("ok"))

    def test_rebuild_replaces_database_without_duplicate_rows(self) -> None:
        self._note("One.md", "Одна нотатка", "унікальний текст")
        first = rebuild_index(self.config)
        second = rebuild_index(self.config)
        self.assertEqual(first.objects, second.objects)
        connection = sqlite3.connect(second.database)
        try:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM objects").fetchone()[0],
                second.objects,
            )
        finally:
            connection.close()

    def test_wikilinks_become_relations(self) -> None:
        self._note("Target.md", "Ціль", "target body")
        self._note("Source.md", "Джерело", "Посилання [[Target]]")
        summary = rebuild_index(self.config)
        self.assertGreaterEqual(summary.relations, 1)

    def test_private_directory_is_not_indexed(self) -> None:
        secret = self.config.private / "secret.txt"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text("SECRET-UNIQUE-TOKEN", encoding="utf-8")
        rebuild_index(self.config)
        self.assertEqual(search_index(self.config, "SECRET"), [])


if __name__ == "__main__":
    unittest.main()
