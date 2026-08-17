from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.config import load_config, validate_config
from vaultctl.metadata import new_uid, today
from vaultctl.rag.embeddings import test_embedding
from vaultctl.rag.store import query_sources, rebuild_rag
from vaultctl.scaffold import initialize

from test_router import CONFIG


class HybridRagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config_path = self.root / "vault.toml"
        config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(config_path)
        initialize(self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _note(self, name: str, title: str, body: str, visibility: str = "internal") -> Path:
        path = self.config.vault / "04_Knowledge/Concepts" / name
        path.write_text(
            f"""---
schema_version: 1
uid: {new_uid()}
type: note
title: "{title}"
status: active
created: {today()}
updated: {today()}
tags:
  - rag-test
aliases: []
visibility: {visibility}
---

# {title}

{body}
""",
            encoding="utf-8",
        )
        return path

    def _embedding_config(self, *, dimension: int = 8, model: str = "test-v1"):
        return replace(
            self.config,
            rag=replace(
                self.config.rag,
                embeddings=replace(
                    self.config.rag.embeddings,
                    enabled=True,
                    provider="test",
                    model=model,
                    dimension=dimension,
                ),
            ),
        )

    def test_incremental_build_reuses_unchanged_sources_and_vectors(self) -> None:
        config = self._embedding_config()
        self._note("Stable.md", "Stable", "unchanged semantic content")
        first = rebuild_rag(config)
        with patch("vaultctl.rag.store.embed_text") as mocked:
            second = rebuild_rag(config, incremental=True)
        self.assertEqual(second.mode, "build")
        self.assertEqual(second.changed_sources, 0)
        self.assertEqual(second.reused_sources, first.sources)
        self.assertEqual(second.embeddings, 0)
        mocked.assert_not_called()

    def test_incremental_build_updates_only_changed_source(self) -> None:
        config = self._embedding_config()
        changed = self._note("Changed.md", "Changed", "before update")
        self._note("Stable.md", "Stable", "never changes")
        rebuild_rag(config)
        changed.write_text(
            changed.read_text(encoding="utf-8").replace("before update", "after update"),
            encoding="utf-8",
        )
        with patch(
            "vaultctl.rag.store.embed_text",
            side_effect=lambda _config, text: test_embedding(text, 8),
        ) as mocked:
            summary = rebuild_rag(config, incremental=True)
        self.assertEqual(summary.changed_sources, 1)
        self.assertEqual(summary.embeddings, 1)
        self.assertEqual(mocked.call_count, 1)
        self.assertTrue(query_sources(config, "after update"))

    def test_incremental_gc_removes_missing_and_restricted_sources(self) -> None:
        missing = self._note("Missing.md", "Missing", "TOKEN_MISSING")
        restricted = self._note("Restricted.md", "Restricted", "TOKEN_RESTRICTED")
        rebuild_rag(self.config)
        missing.unlink()
        restricted.write_text(
            restricted.read_text(encoding="utf-8").replace(
                "visibility: internal", "visibility: restricted"
            ),
            encoding="utf-8",
        )
        summary = rebuild_rag(self.config, incremental=True)
        self.assertEqual(summary.removed_sources, 2)
        self.assertEqual(query_sources(self.config, "TOKEN_MISSING"), [])
        self.assertEqual(query_sources(self.config, "TOKEN_RESTRICTED"), [])

    def test_corrupt_database_falls_back_to_full_build(self) -> None:
        self._note("Recovery.md", "Recovery", "recoverable content")
        self.config.rag.database.parent.mkdir(parents=True, exist_ok=True)
        self.config.rag.database.write_bytes(b"not a sqlite database")
        summary = rebuild_rag(self.config, incremental=True)
        self.assertEqual(summary.mode, "build-fallback")
        self.assertTrue(query_sources(self.config, "recoverable content"))

    def test_failed_rebuild_preserves_last_good_database(self) -> None:
        config = self._embedding_config()
        self._note("Atomic.md", "Atomic", "LAST_GOOD_TOKEN")
        rebuild_rag(config)
        before = config.rag.database.read_bytes()
        with patch("vaultctl.rag.store.embed_text", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                rebuild_rag(config)
        self.assertEqual(config.rag.database.read_bytes(), before)
        self.assertTrue(query_sources(config, "LAST_GOOD_TOKEN"))

    def test_embedding_signature_change_rebuilds_vectors(self) -> None:
        first = self._embedding_config(dimension=8, model="v1")
        self._note("Signature.md", "Signature", "embedding signature")
        initial = rebuild_rag(first)
        second = self._embedding_config(dimension=16, model="v2")
        summary = rebuild_rag(second, incremental=True)
        self.assertEqual(summary.changed_sources, 0)
        self.assertEqual(summary.embeddings, initial.chunks)
        connection = sqlite3.connect(second.rag.database)
        try:
            signatures = connection.execute(
                "SELECT DISTINCT model,dimension FROM vectors"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(signatures, [("v2", 16)])

    def test_hybrid_search_can_return_semantic_only_match(self) -> None:
        config = self._embedding_config(dimension=2)
        self._note("Semantic.md", "Semantic target", "automobile road journey")
        self._note("Other.md", "Other", "banana orchard harvest")

        def vectors(_config, text: str):
            lowered = text.casefold()
            return [1.0, 0.0] if any(word in lowered for word in ("automobile", "vehicle")) else [0.0, 1.0]

        with patch("vaultctl.rag.store.embed_text", side_effect=vectors):
            rebuild_rag(config)
            rows = query_sources(config, "vehicle", limit=3)
        target = next(row for row in rows if row["title"] == "Semantic target")
        self.assertIn(target["retrieval"], {"vector", "hybrid"})
        self.assertGreater(target["vector_score"], 0.9)

    def test_disabled_rag_blocks_build_and_query(self) -> None:
        disabled = replace(self.config, rag=replace(self.config.rag, enabled=False))
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            rebuild_rag(disabled)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            query_sources(disabled, "anything")

    def test_test_embedding_dimension_must_be_positive(self) -> None:
        invalid = self._embedding_config(dimension=0)
        with self.assertRaisesRegex(ValueError, "positive dimension"):
            validate_config(invalid)


if __name__ == "__main__":
    unittest.main()
