from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.ask import ask
from vaultctl.config import load_config
from vaultctl.graph import build_graph, export_graph, graph_neighbors, graph_stats
from vaultctl.indexer import rebuild_index
from vaultctl.locks import LockError, vault_lock
from vaultctl.metadata import new_uid, today
from vaultctl.policy import can_read_path
from vaultctl.rag.store import query_sources, rebuild_rag
from vaultctl.scaffold import initialize
from vaultctl.wiki import apply_draft, approve_draft, draft_concept, suggest_links

from test_router import CONFIG


class V11RagWikiGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "source.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(self.config_path)
        initialize(self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _note(
        self,
        name: str,
        title: str,
        body: str,
        *,
        visibility: str = "internal",
        aliases: list[str] | None = None,
    ) -> Path:
        path = self.config.vault / "04_Knowledge/Concepts" / name
        alias_yaml = "\n".join(f"  - {alias}" for alias in (aliases or [])) or "  []"
        text = f"""---
schema_version: 1
uid: {new_uid()}
type: note
title: "{title}"
status: active
created: {today()}
updated: {today()}
tags:
  - rag-test
aliases:
{alias_yaml}
visibility: {visibility}
---

# {title}

{body}
"""
        path.write_text(text, encoding="utf-8")
        return path

    def test_central_policy_blocks_private_and_restricted(self) -> None:
        public = self._note("Public.md", "Public", "allowed")
        restricted = self._note("Restricted.md", "Restricted", "secret", visibility="restricted")
        private = self.config.private / "secret.md"
        private.write_text("private", encoding="utf-8")
        self.assertTrue(can_read_path(public, self.config, "rag").allowed)
        self.assertFalse(can_read_path(restricted, self.config, "rag").allowed)
        self.assertFalse(can_read_path(private, self.config, "graph").allowed)

    def test_lock_blocks_parallel_writer_and_cleans_up(self) -> None:
        with vault_lock(self.config, "unit-test"):
            with self.assertRaises(LockError):
                with vault_lock(self.config, "unit-test"):
                    pass
        self.assertFalse((self.config.runtime / "locks" / "unit-test.lock").exists())

    def test_rag_rebuild_sources_and_gc_for_restricted(self) -> None:
        note = self._note(
            "Migration_Risks.md",
            "Ризики міграції",
            "Ризики міграції включають дублікати, втрату джерел і неправильну видимість.",
        )
        summary = rebuild_rag(self.config)
        self.assertGreater(summary.chunks, 0)
        self.assertTrue(query_sources(self.config, "ризики міграції"))
        text = note.read_text(encoding="utf-8").replace("visibility: internal", "visibility: restricted")
        note.write_text(text, encoding="utf-8")
        rebuild_rag(self.config)
        self.assertEqual(query_sources(self.config, "неправильну видимість"), [])

    def test_ask_sources_only_and_llm_disabled_failure(self) -> None:
        self._note("SQLite.md", "SQLite", "SQLite використовується для локального RAG пошуку.")
        rebuild_rag(self.config)
        result = ask(self.config, "SQLite RAG", sources_only=True)
        self.assertEqual(result.mode, "sources-only")
        self.assertTrue(result.sources)
        with self.assertRaises(RuntimeError):
            ask(self.config, "SQLite RAG", sources_only=False)

    def test_rag_schema_migration_table_exists(self) -> None:
        rebuild_rag(self.config)
        connection = sqlite3.connect(self.config.rag.database)
        try:
            row = connection.execute(
                "SELECT version FROM schema_migrations WHERE schema_name='rag'"
            ).fetchone()
            self.assertEqual(row[0], 2)
        finally:
            connection.close()

    def test_wiki_draft_approve_and_apply_dry_run(self) -> None:
        self._note("Concept.md", "KnowledgeVault", "KnowledgeVault має RAG джерела.")
        rebuild_rag(self.config)
        draft = draft_concept(self.config, "KnowledgeVault")
        self.assertTrue(draft.path.is_file())
        approve_draft(self.config, draft.draft_id, "04_Knowledge/Concepts/Drafted.md")
        artifact = apply_draft(self.config, draft.draft_id)
        self.assertTrue(artifact.is_file())
        self.assertFalse((self.config.vault / "04_Knowledge/Concepts/Drafted.md").exists())

    def test_wiki_suggest_links_only_existing_targets(self) -> None:
        self._note("Target.md", "Target Concept", "target")
        self._note("Source.md", "Source", "This mentions Target Concept without a wikilink.")
        rebuild_index(self.config)
        draft = suggest_links(self.config)
        text = draft.path.read_text(encoding="utf-8")
        self.assertIn("[[Target Concept]]", text)

    def test_graph_build_export_neighbors_stats_and_dashboard(self) -> None:
        target = self._note("Target.md", "Graph Target", "target")
        source = self._note("Source.md", "Graph Source", "Link to [[Target]] and Graph Target.")
        summary = build_graph(self.config)
        self.assertGreaterEqual(summary.nodes, 2)
        self.assertGreaterEqual(summary.edges, 1)
        self.assertTrue(export_graph(self.config, "json").is_file())
        self.assertTrue(export_graph(self.config, "mermaid").is_file())
        self.assertTrue(export_graph(self.config, "graphml").is_file())
        self.assertTrue(graph_neighbors(self.config, "Graph Target"))
        self.assertGreaterEqual(graph_stats(self.config)["nodes"], 2)
        self.assertTrue((self.config.vault / "91_Views/Home.md").is_file())

    def test_embeddings_test_provider_is_optional_and_rebuildable(self) -> None:
        config = replace(
            self.config,
            rag=replace(
                self.config.rag,
                embeddings=replace(
                    self.config.rag.embeddings,
                    enabled=True,
                    provider="test",
                    dimension=16,
                ),
            ),
        )
        self._note("Embeddings.md", "Embeddings", "semantic hybrid search")
        summary = rebuild_rag(config)
        self.assertGreater(summary.embeddings, 0)

    def test_performance_smoke_1000_notes_no_private_leakage(self) -> None:
        for index in range(1000):
            self._note(f"Smoke_{index:04d}.md", f"Smoke {index}", f"synthetic performance note {index}")
        secret = self.config.private / "secret.txt"
        secret.write_text("UNIQUESECRETSMOKETOKEN", encoding="utf-8")
        started = time.perf_counter()
        summary = rebuild_rag(self.config)
        elapsed = time.perf_counter() - started
        self.assertGreaterEqual(summary.sources, 1000)
        self.assertLess(elapsed, 30)
        self.assertEqual(query_sources(self.config, "UNIQUESECRETSMOKETOKEN"), [])


if __name__ == "__main__":
    unittest.main()
