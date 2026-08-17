from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from vaultctl.config import Config
from vaultctl.metadata import parse_frontmatter
from vaultctl.policy import can_read_path, is_indexable_text_path, read_visibility
from vaultctl.fileops import file_sha256


HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class SourceDocument:
    source_uid: str
    source_path: str
    source_type: str
    title: str
    visibility: str
    updated: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_uid: str
    source_path: str
    source_type: str
    title: str
    heading_path: str
    chunk_index: int
    content: str
    content_hash: str
    visibility: str
    updated: str


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def iter_sources(config: Config) -> list[SourceDocument]:
    sources: list[SourceDocument] = []
    if config.schema_version == 2:
        roots = (
            config.vault,
            config.documents,
            config.workspaces,
            config.resources,
            config.media,
            config.archive,
        )
    else:
        roots = (config.vault,)
    markdown: set[Path] = set()
    for root in roots:
        if root.exists():
            markdown.update(root.rglob("*.md"))
    if markdown:
        for path in sorted(markdown):
            if "90_Templates" in path.parts or "91_Views" in path.parts:
                continue
            try:
                metadata, body = parse_frontmatter(path)
            except (OSError, UnicodeError, ValueError):
                if config.schema_version != 2 or not is_indexable_text_path(path, config):
                    continue
                try:
                    body = path.read_text(encoding="utf-8")
                    metadata = {
                        "uid": "document:" + file_sha256(path),
                        "title": path.stem,
                        "visibility": config.default_visibility,
                        "updated": str(path.stat().st_mtime_ns),
                    }
                except (OSError, UnicodeError):
                    continue
            decision = can_read_path(path, config, "rag", metadata=metadata)
            if not decision.allowed:
                continue
            content = body.strip()
            if not content:
                continue
            digest = sha256(content.encode("utf-8")).hexdigest()
            sources.append(
                SourceDocument(
                    source_uid=str(metadata.get("uid")),
                    source_path=_relative(path, config.root),
                    source_type="markdown",
                    title=str(metadata.get("title", path.stem)),
                    visibility=str(metadata.get("visibility", decision.visibility)),
                    updated=str(metadata.get("updated", "")),
                    content=content,
                    content_hash=digest,
                )
            )
    cache_name = "Caches" if config.schema_version == 2 else "cache"
    extracted = config.runtime / cache_name / "extracted"
    if config.assets.exists() and extracted.exists():
        for asset in sorted(config.assets.rglob("*")):
            if not asset.is_file() or asset.name.endswith(".asset.md"):
                continue
            decision = can_read_path(asset, config, "rag")
            if not decision.allowed:
                continue
            digest = file_sha256(asset)
            cache = extracted / f"{digest}.txt"
            if not cache.is_file():
                continue
            content = cache.read_text(encoding="utf-8", errors="replace").strip()
            if not content:
                continue
            sidecar = asset.with_name(asset.name + ".asset.md")
            title = asset.name
            uid = f"asset:{digest}"
            updated = ""
            visibility = read_visibility(asset, config)
            if sidecar.is_file():
                try:
                    metadata, _ = parse_frontmatter(sidecar)
                    title = str(metadata.get("title", title))
                    uid = str(metadata.get("uid", uid))
                    updated = str(metadata.get("updated", ""))
                    visibility = str(metadata.get("visibility", visibility))
                except (OSError, UnicodeError, ValueError):
                    pass
            sources.append(
                SourceDocument(
                    source_uid=uid,
                    source_path=_relative(asset, config.root),
                    source_type="asset",
                    title=title,
                    visibility=visibility,
                    updated=updated,
                    content=content,
                    content_hash=sha256(content.encode("utf-8")).hexdigest(),
                )
            )
    return sources


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            cut = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if cut > start + max_chars // 2:
                end = cut + 1
        part = text[start:end].strip()
        if part:
            parts.append(part)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return parts


def chunk_source(source: SourceDocument, config: Config) -> list[Chunk]:
    lines = source.content.splitlines()
    sections: list[tuple[str, str]] = []
    heading_stack: list[tuple[int, str]] = []
    current_heading = ""
    current: list[str] = []

    def flush() -> None:
        body = "\n".join(current).strip()
        if body:
            sections.append((current_heading, body))

    for line in lines:
        match = HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack[:] = [(lvl, text) for lvl, text in heading_stack if lvl < level]
            heading_stack.append((level, title))
            current_heading = " > ".join(text for _, text in heading_stack)
            current = [line]
        else:
            current.append(line)
    flush()
    if not sections:
        sections = [("", source.content)]

    chunks: list[Chunk] = []
    index = 0
    for heading_path, section in sections:
        for part in _split_long(section, config.rag.chunk_max_chars, config.rag.chunk_overlap_chars):
            content_hash = sha256(part.encode("utf-8")).hexdigest()
            chunk_id = sha256(
                f"{source.source_uid}|{source.source_path}|{index}|{content_hash}".encode("utf-8")
            ).hexdigest()
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    source_uid=source.source_uid,
                    source_path=source.source_path,
                    source_type=source.source_type,
                    title=source.title,
                    heading_path=heading_path,
                    chunk_index=index,
                    content=part,
                    content_hash=content_hash,
                    visibility=source.visibility,
                    updated=source.updated,
                )
            )
            index += 1
    return chunks
