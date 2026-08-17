from __future__ import annotations

from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultctl.ask import ask
from vaultctl.backup import ensure_password_file, password_acl_health
from vaultctl.config import load_config
from vaultctl.local_http import _NoRedirectHandler, validate_local_base_url
from vaultctl.locks import LockError, vault_lock
from vaultctl.metadata import new_uid
from vaultctl.policy import can_read_path
from vaultctl.router import file_sha256
from vaultctl.scaffold import initialize
from vaultctl.validator import validate_vault
from vaultctl.wiki import apply_draft, approve_draft, draft_concept, summarize_path

from test_router import CONFIG


def note_text(title: str, body: str, *, visibility: str = "internal") -> str:
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
visibility: {visibility}
---

# {title}

{body}
"""


class SecurityCorrectnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        config_path = self.base / "source.toml"
        config_path.write_text(CONFIG, encoding="utf-8")
        self.config = load_config(config_path)
        initialize(self.config)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _note(self, name: str = "Allowed.md", *, visibility: str = "internal") -> Path:
        path = self.config.vault / "04_Knowledge" / "Concepts" / name
        path.write_text(note_text(path.stem, "allowed body", visibility=visibility), encoding="utf-8")
        return path

    def _asset(self, name: str = "asset.txt", *, visibility: str = "internal", cache: bool = True) -> Path:
        asset = self.config.assets / "Projects" / "PRJ-2026-001" / "docs" / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text(f"raw asset text for {name}", encoding="utf-8")
        digest = file_sha256(asset)
        today = date.today().isoformat()
        sidecar = asset.with_name(asset.name + ".asset.md")
        sidecar.write_text(
            f"""---
schema_version: 1
uid: {new_uid()}
type: asset
title: "{asset.name}"
status: active
created: {today}
updated: {today}
tags: []
aliases: []
visibility: {visibility}
project_code: PRJ-2026-001
sha256: "{digest}"
source: synthetic
asset_path: "{asset.relative_to(self.config.assets).as_posix()}"
---
""",
            encoding="utf-8",
        )
        if cache:
            cache_path = self.config.runtime / "cache" / "extracted" / f"{digest}.txt"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text("safe extracted asset text", encoding="utf-8")
        return asset

    def test_failed_lock_contenders_do_not_remove_owner_lock(self) -> None:
        lock_path = self.config.runtime / "locks" / "owner.lock"
        with vault_lock(self.config, "owner"):
            with self.assertRaises(LockError):
                with vault_lock(self.config, "owner"):
                    pass
            self.assertTrue(lock_path.is_file())
            with self.assertRaises(LockError):
                with vault_lock(self.config, "owner"):
                    pass
            self.assertTrue(lock_path.is_file())
        self.assertFalse(lock_path.exists())

    def test_owner_does_not_remove_replaced_token(self) -> None:
        lock_path = self.config.runtime / "locks" / "token.lock"
        with vault_lock(self.config, "token"):
            lock_path.write_text(json.dumps({"pid": 999, "created": time.time(), "token": "replacement"}), encoding="utf-8")
        self.assertTrue(lock_path.is_file())

    def test_stale_malformed_lock_is_recovered_but_young_one_is_preserved(self) -> None:
        lock_path = self.config.runtime / "locks" / "stale.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("malformed", encoding="utf-8")
        old = time.time() - 10
        os.utime(lock_path, (old, old))
        with vault_lock(self.config, "stale", stale_seconds=1):
            self.assertTrue(lock_path.is_file())
        lock_path.write_text("malformed", encoding="utf-8")
        with self.assertRaises(LockError):
            with vault_lock(self.config, "stale", stale_seconds=3600):
                pass
        self.assertTrue(lock_path.is_file())

    def test_metadata_failures_are_findings_and_policy_denials(self) -> None:
        cases = {
            "Malformed.md": b"---\nvisibility: restricted\nbroken: [\n---\nsecret",
            "Mapping.md": b"---\n- not\n- mapping\n---\nsecret",
            "Missing.md": b"secret without frontmatter",
            "Encoding.md": b"---\nvisibility: internal\n---\n\xff",
        }
        for name, content in cases.items():
            path = self.config.vault / "04_Knowledge" / "Concepts" / name
            path.write_bytes(content)
            decision = can_read_path(path, self.config, "rag")
            self.assertFalse(decision.allowed, name)
        findings = validate_vault(self.config)
        frontmatter_paths = {item.path for item in findings if item.code == "frontmatter"}
        for name in cases:
            self.assertTrue(any(path.endswith(name) for path in frontmatter_paths), name)

    def test_wiki_allows_valid_vault_note_and_cached_asset(self) -> None:
        note = self._note()
        draft = summarize_path(self.config, str(note))
        text = draft.path.read_text(encoding="utf-8")
        self.assertIn("allowed body", text)
        self.assertNotIn("schema_version: 1\nuid:", text.split("## Extract", 1)[-1])

        asset = self._asset()
        asset_draft = summarize_path(self.config, str(asset))
        self.assertIn("safe extracted asset text", asset_draft.path.read_text(encoding="utf-8"))
        self.assertNotIn("raw asset text for asset.txt", asset_draft.path.read_text(encoding="utf-8"))

    def test_wiki_denies_external_private_templates_and_unsafe_assets(self) -> None:
        external = self.base / "outside.txt"
        external.write_text("synthetic secret", encoding="utf-8")
        private = self.config.private / "secret.md"
        private.write_text(note_text("Private", "secret"), encoding="utf-8")
        template = self.config.vault / "90_Templates" / "Project.md"
        for path in (external, private, template):
            with self.assertRaises(PermissionError):
                summarize_path(self.config, str(path))

        missing_sidecar = self.config.assets / "missing.txt"
        missing_sidecar.write_text("unsafe", encoding="utf-8")
        with self.assertRaises(PermissionError):
            summarize_path(self.config, str(missing_sidecar))

        restricted = self._asset("restricted.txt", visibility="restricted")
        with self.assertRaises(PermissionError):
            summarize_path(self.config, str(restricted))

        bad_hash = self._asset("bad-hash.txt")
        bad_hash.write_text("changed after sidecar", encoding="utf-8")
        with self.assertRaises(PermissionError):
            summarize_path(self.config, str(bad_hash))

        no_cache = self._asset("no-cache.bin", cache=False)
        with self.assertRaises(FileNotFoundError):
            summarize_path(self.config, str(no_cache))

    def test_wiki_denies_symlink_when_platform_supports_it(self) -> None:
        external = self.base / "outside.md"
        external.write_text(note_text("Outside", "secret"), encoding="utf-8")
        link = self.config.vault / "04_Knowledge" / "Concepts" / "Link.md"
        try:
            link.symlink_to(external)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(PermissionError):
            summarize_path(self.config, str(link))

    def test_local_service_url_policy(self) -> None:
        accepted = ["http://localhost:11434", "https://127.0.0.1", "http://[::1]:11434/"]
        rejected = [
            "https://example.com",
            "http://192.168.1.5:11434",
            "http://user:pass@localhost:11434",
            "http://localhost:11434/base",
            "http://localhost:11434?x=1",
            "file:///tmp/ollama",
        ]
        for value in accepted:
            self.assertTrue(validate_local_base_url(value))
        for value in rejected:
            with self.assertRaises(ValueError, msg=value):
                validate_local_base_url(value)

    def test_config_rejects_remote_ollama_even_when_disabled(self) -> None:
        raw = CONFIG + """

[llm]
enabled = false
provider = "ollama"
model = "test"
base_url = "https://example.com"
context_limit_tokens = 1024
temperature = 0.0
"""
        path = self.base / "remote.toml"
        path.write_text(raw, encoding="utf-8")
        with self.assertRaises(ValueError):
            load_config(path)

    def test_local_http_rejects_redirects(self) -> None:
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate", data=b"{}", method="POST"
        )
        handler = _NoRedirectHandler()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1:11434/redirected",
            )
        caught.exception.close()

    def _llm_config(self):
        return replace(self.config, llm=replace(self.config.llm, enabled=True))

    @staticmethod
    def _response(payload: object):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"response": payload}).encode("utf-8")

            def geturl(self):
                return "http://localhost:11434/api/generate"

        return FakeResponse()

    def test_citations_are_validated_and_exposed(self) -> None:
        sources = [{"chunk_id": "chunk-1", "title": "One", "source_path": "Vault/One.md", "heading_path": "", "snippet": "fact"}]
        payload = json.dumps({"answer": "Grounded answer", "citations": ["chunk-1"]})
        with patch("vaultctl.ask.query_sources", return_value=sources), patch(
            "vaultctl.ask.open_local_request", return_value=self._response(payload)
        ):
            result = ask(self._llm_config(), "question")
        self.assertEqual(result.citations, ["chunk-1"])
        self.assertEqual(result.citation_status, "validated")

    def test_invalid_structured_answers_are_rejected(self) -> None:
        sources = [{"chunk_id": "chunk-1", "title": "One", "source_path": "Vault/One.md", "heading_path": "", "snippet": "fact"}]
        invalid = [
            "not-json",
            json.dumps({"answer": "", "citations": ["chunk-1"]}),
            json.dumps({"answer": "answer", "citations": []}),
            json.dumps({"answer": "answer", "citations": ["unknown"]}),
        ]
        for payload in invalid:
            with patch("vaultctl.ask.query_sources", return_value=sources), patch(
                "vaultctl.ask.open_local_request", return_value=self._response(payload)
            ):
                with self.assertRaises(RuntimeError, msg=payload):
                    ask(self._llm_config(), "question")

    def test_sources_only_never_calls_local_service(self) -> None:
        sources = [{"chunk_id": "chunk-1", "title": "One", "source_path": "Vault/One.md", "heading_path": "", "snippet": "fact"}]
        with patch("vaultctl.ask.query_sources", return_value=sources), patch(
            "vaultctl.ask.open_local_request"
        ) as local:
            result = ask(self.config, "question", sources_only=True)
        local.assert_not_called()
        self.assertEqual(result.citation_status, "not-applicable")

    def test_wiki_approval_is_bound_to_draft_and_target_hashes(self) -> None:
        draft = draft_concept(self.config, "Concept")
        approve_draft(self.config, draft.draft_id, "04_Knowledge/Concepts/New.md")
        artifact = apply_draft(self.config, draft.draft_id)
        self.assertTrue(artifact.is_file())
        draft.path.write_text(draft.path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            apply_draft(self.config, draft.draft_id)

        existing = self._note("Existing.md")
        second = draft_concept(self.config, "Existing")
        approve_draft(self.config, second.draft_id, existing.relative_to(self.config.vault).as_posix())
        existing.write_text(existing.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            apply_draft(self.config, second.draft_id)

    def test_password_acl_health_matches_created_password(self) -> None:
        password = ensure_password_file(self.config)
        self.assertTrue(password.is_file())
        ok, message = password_acl_health(self.config)
        self.assertTrue(ok, message)


if __name__ == "__main__":
    unittest.main()
