from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import unified_diff
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .config import Config
from .metadata import new_uid, parse_frontmatter, today
from .policy import can_read_path, is_asset_path, is_vault_path
from .rag.store import query_sources


@dataclass(frozen=True)
class WikiDraft:
    draft_id: str
    kind: str
    path: Path
    title: str


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run_dir(config: Config) -> Path:
    run_id = time.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    path = config.staging / "WikiDrafts" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_draft(run_dir: Path, kind: str, title: str, body: str) -> WikiDraft:
    draft_id = run_dir.name
    path = run_dir / "draft.md"
    path.write_text(
        f"""---
schema_version: 1
uid: {new_uid()}
type: note
title: "{title}"
status: draft
created: {today()}
updated: {today()}
tags:
  - wiki-draft
aliases: []
visibility: internal
draft_kind: {kind}
draft_id: {draft_id}
---

{body.rstrip()}
""",
        encoding="utf-8",
        newline="\n",
    )
    metadata = WikiDraft(draft_id, kind, path, title)
    (run_dir / "draft.json").write_text(json.dumps(asdict(metadata), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return metadata


def draft_concept(config: Config, concept: str) -> WikiDraft:
    rows = query_sources(config, concept, config.rag.default_top_k) if config.rag.database.is_file() else []
    lines = [f"# {concept}", "", "## Summary", "", "Draft generated from existing KnowledgeVault sources.", "", "## Sources", ""]
    if not rows:
        lines.append("Недостатньо джерел. Перед доповненням запустіть `vaultctl rag rebuild`.")
    for index, row in enumerate(rows, 1):
        lines.append(f"{index}. `{row['source_path']}` — {row['title']} / {row.get('heading_path') or ''}")
    return _write_draft(_run_dir(config), "concept", concept, "\n".join(lines))


def draft_moc(config: Config, topic: str) -> WikiDraft:
    rows = query_sources(config, topic, config.rag.default_top_k) if config.rag.database.is_file() else []
    lines = [f"# MOC: {topic}", "", "## Candidate notes", ""]
    seen: set[str] = set()
    for row in rows:
        key = str(row["source_path"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- [[{Path(key).stem}]] — `{key}`")
    if not seen:
        lines.append("- Недостатньо джерел для MOC.")
    return _write_draft(_run_dir(config), "moc", f"MOC: {topic}", "\n".join(lines))


def summarize_path(config: Config, target: str) -> WikiDraft:
    path = Path(target)
    if not path.is_absolute():
        path = config.root / target
    if not path.is_file():
        raise FileNotFoundError(path)
    decision = can_read_path(path, config, "wiki")
    if not decision.allowed:
        raise PermissionError(decision.reason)
    resolved = path.resolve()
    if is_vault_path(resolved, config):
        metadata, text = parse_frontmatter(resolved)
        source_title = str(metadata.get("title", resolved.name))
    elif is_asset_path(resolved, config):
        digest = _digest(resolved)
        cache_name = "Caches" if config.schema_version == 2 else "cache"
        cache = config.runtime / cache_name / "extracted" / f"{digest}.txt"
        if not cache.is_file():
            raise FileNotFoundError(
                "Extracted asset text is missing. Run `vaultctl extract --rebuild` first."
            )
        text = cache.read_text(encoding="utf-8")
        source_title = resolved.name
    else:
        raise PermissionError("path is outside Vault and Assets")
    body = f"# Summary: {source_title}\n\n## Extract\n\n{text[:2000].strip()}\n"
    return _write_draft(_run_dir(config), "summary", f"Summary: {source_title}", body)


def suggest_links(config: Config) -> WikiDraft:
    database = config.runtime / (
        "Catalog/catalog.sqlite3" if config.schema_version == 2 else "db/catalog.sqlite3"
    )
    suggestions: list[str] = ["# Link suggestions", ""]
    if not database.is_file():
        suggestions.append("Catalog is missing. Run `vaultctl index --rebuild`.")
        return _write_draft(_run_dir(config), "suggest-links", "Link suggestions", "\n".join(suggestions))
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        notes = connection.execute("SELECT o.uid,o.title,o.path,n.body FROM objects o JOIN notes n ON n.uid=o.uid WHERE o.visibility IN ('public','internal')").fetchall()
        titles = [(row["uid"], row["title"], row["path"]) for row in notes]
        for note in notes:
            body = str(note["body"])
            for uid, title, path in titles:
                if uid != note["uid"] and str(title) in body and f"[[{title}]]" not in body:
                    suggestions.append(f"- `{note['path']}` mentions existing note `[[{title}]]` (`{path}`)")
    finally:
        connection.close()
    if len(suggestions) == 2:
        suggestions.append("No deterministic link suggestions found.")
    return _write_draft(_run_dir(config), "suggest-links", "Link suggestions", "\n".join(suggestions))


def approve_draft(config: Config, draft: str, target: str) -> Path:
    draft_dir = config.staging / "WikiDrafts" / draft
    draft_path = draft_dir / "draft.md"
    if not draft_path.is_file():
        raise FileNotFoundError(draft_path)
    target_path = (config.vault / target).resolve()
    normalized_target = target_path.relative_to(config.vault.resolve()).as_posix()
    if target_path.suffix.lower() != ".md":
        raise ValueError("Wiki draft target must be a Markdown file")
    approvals = draft_dir / "approvals.jsonl"
    event = {
        "draft_id": draft,
        "draft_sha256": _digest(draft_path),
        "target": normalized_target,
        "target_exists": target_path.exists(),
        "target_sha256": _digest(target_path) if target_path.is_file() else None,
        "approved_at": time.time(),
    }
    with approvals.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return approvals


def apply_draft(config: Config, draft: str, *, execute: bool = False) -> Path:
    draft_dir = config.staging / "WikiDrafts" / draft
    approvals = draft_dir / "approvals.jsonl"
    draft_path = draft_dir / "draft.md"
    if not approvals.is_file():
        raise FileNotFoundError("Draft is not approved")
    if not draft_path.is_file():
        raise FileNotFoundError(draft_path)
    last = json.loads([line for line in approvals.read_text(encoding="utf-8").splitlines() if line][-1])
    target = (config.vault / last["target"]).resolve()
    normalized_target = target.relative_to(config.vault.resolve()).as_posix()
    if normalized_target != last["target"] or target.suffix.lower() != ".md":
        raise ValueError("Approved wiki target is invalid")
    approved_draft_hash = last.get("draft_sha256")
    if not approved_draft_hash or _digest(draft_path) != approved_draft_hash:
        raise RuntimeError("Wiki draft changed after approval; approve it again")
    target_exists = target.exists()
    if target_exists != bool(last.get("target_exists")):
        raise RuntimeError("Wiki target changed after approval; approve it again")
    if target_exists:
        approved_target_hash = last.get("target_sha256")
        if not approved_target_hash or _digest(target) != approved_target_hash:
            raise RuntimeError("Wiki target changed after approval; approve it again")
    content = draft_path.read_text(encoding="utf-8")
    if target.exists():
        old = target.read_text(encoding="utf-8", errors="replace")
        diff = "".join(unified_diff(old.splitlines(True), content.splitlines(True), fromfile=str(target), tofile=str(draft_path)))
        patch = draft_dir / "manual-review.diff"
        patch.write_text(diff, encoding="utf-8")
        return patch
    dry_run = draft_dir / "apply-dry-run.json"
    dry_run.write_text(json.dumps({"target": str(target), "execute": execute}, ensure_ascii=False, indent=2), encoding="utf-8")
    if execute:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return target
    return dry_run
