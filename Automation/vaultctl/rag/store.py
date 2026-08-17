from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import shutil
import sqlite3
import time
import uuid

from vaultctl.config import Config
from vaultctl.locks import vault_lock
from vaultctl.schema import ensure_schema_migrations

from .chunker import Chunk, SourceDocument, chunk_source, iter_sources
from .embeddings import blob_to_vector, cosine, embed_text, vector_to_blob


SCHEMA_VERSION = 2
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    source_uid TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    visibility TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    updated TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    source_uid TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT,
    heading_path TEXT,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    visibility TEXT NOT NULL,
    updated TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    title,
    heading_path,
    content,
    source_path,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS vectors (
    chunk_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    vector BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS build_manifest (
    run_id TEXT PRIMARY KEY,
    built_at REAL NOT NULL,
    mode TEXT NOT NULL,
    sources INTEGER NOT NULL,
    chunks INTEGER NOT NULL,
    embeddings INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    changed_sources INTEGER NOT NULL DEFAULT 0,
    reused_sources INTEGER NOT NULL DEFAULT 0,
    removed_sources INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class RagBuildSummary:
    database: Path
    run_id: str
    mode: str
    sources: int
    chunks: int
    embeddings: int
    duration_seconds: float
    changed_sources: int = 0
    reused_sources: int = 0
    removed_sources: int = 0


class IncrementalUnavailable(RuntimeError):
    pass


def _require_enabled(config: Config) -> None:
    if not config.rag.enabled:
        raise RuntimeError("RAG is disabled in vault.toml")


def _connect(path: Path, *, rebuild_writer: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        if rebuild_writer:
            # The writer always targets a disposable copy and atomically replaces
            # the live database only after integrity_check succeeds.
            connection.execute("PRAGMA journal_mode = OFF")
            connection.execute("PRAGMA synchronous = OFF")
            connection.execute("PRAGMA temp_store = MEMORY")
        return connection
    except Exception:
        connection.close()
        raise


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(build_manifest)")
    }
    for name in ("changed_sources", "reused_sources", "removed_sources"):
        if name not in columns:
            connection.execute(
                f"ALTER TABLE build_manifest ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
            )
    ensure_schema_migrations(connection, "rag", SCHEMA_VERSION)


def _collect(config: Config) -> tuple[list[SourceDocument], list[Chunk]]:
    sources = iter_sources(config)
    chunks: list[Chunk] = []
    for source in sources:
        chunks.extend(chunk_source(source, config))
    return sources, chunks


def _insert_sources(connection: sqlite3.Connection, sources: list[SourceDocument]) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO sources(
            source_uid, source_path, source_type, title, visibility, content_hash, updated
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            (
                source.source_uid,
                source.source_path,
                source.source_type,
                source.title,
                source.visibility,
                source.content_hash,
                source.updated,
            )
            for source in sources
        ),
    )


def _insert_chunks(connection: sqlite3.Connection, chunks: list[Chunk]) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO chunks(
            chunk_id, source_uid, source_path, source_type, title, heading_path,
            chunk_index, content, content_hash, visibility, updated
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            (
                chunk.chunk_id,
                chunk.source_uid,
                chunk.source_path,
                chunk.source_type,
                chunk.title,
                chunk.heading_path,
                chunk.chunk_index,
                chunk.content,
                chunk.content_hash,
                chunk.visibility,
                chunk.updated,
            )
            for chunk in chunks
        ),
    )
    connection.executemany(
        "INSERT INTO chunks_fts(chunk_id,title,heading_path,content,source_path) VALUES(?,?,?,?,?)",
        (
            (
                chunk.chunk_id,
                chunk.title,
                chunk.heading_path,
                chunk.content,
                chunk.source_path,
            )
            for chunk in chunks
        ),
    )


def _embedding_signature(config: Config) -> tuple[str, str, int]:
    embeddings = config.rag.embeddings
    return embeddings.provider, embeddings.model, embeddings.dimension


def _compatible_vector_ids(connection: sqlite3.Connection, config: Config) -> set[str]:
    provider, model, expected_dimension = _embedding_signature(config)
    compatible: set[str] = set()
    stale: list[str] = []
    for row in connection.execute(
        "SELECT chunk_id,provider,model,dimension FROM vectors"
    ):
        valid = row["provider"] == provider and row["model"] == model
        if expected_dimension > 0:
            valid = valid and row["dimension"] == expected_dimension
        if valid:
            compatible.add(str(row["chunk_id"]))
        else:
            stale.append(str(row["chunk_id"]))
    if stale:
        connection.executemany(
            "DELETE FROM vectors WHERE chunk_id=?", ((chunk_id,) for chunk_id in stale)
        )
    return compatible


def _embed_missing(
    connection: sqlite3.Connection,
    config: Config,
    chunks: list[Chunk],
) -> int:
    if not config.rag.embeddings.enabled:
        connection.execute("DELETE FROM vectors")
        return 0
    compatible = _compatible_vector_ids(connection, config)
    inserted = 0
    for chunk in chunks:
        if chunk.chunk_id in compatible:
            continue
        vector = embed_text(config, chunk.content)
        if vector is None:
            continue
        expected = config.rag.embeddings.dimension
        if expected > 0 and len(vector) != expected:
            raise RuntimeError(
                f"Embedding dimension mismatch: expected {expected}, received {len(vector)}"
            )
        connection.execute(
            """
            INSERT OR REPLACE INTO vectors(chunk_id,provider,model,dimension,vector)
            VALUES(?,?,?,?,?)
            """,
            (
                chunk.chunk_id,
                config.rag.embeddings.provider,
                config.rag.embeddings.model,
                len(vector),
                vector_to_blob(vector),
            ),
        )
        compatible.add(chunk.chunk_id)
        inserted += 1
    return inserted


def _delete_sources(
    connection: sqlite3.Connection,
    source_uids: set[str],
    *,
    preserve_vector_ids: set[str] | None = None,
) -> None:
    preserve = preserve_vector_ids or set()
    for source_uid in source_uids:
        chunk_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT chunk_id FROM chunks WHERE source_uid=?", (source_uid,)
            )
        ]
        connection.executemany(
            "DELETE FROM chunks_fts WHERE chunk_id=?", ((item,) for item in chunk_ids)
        )
        connection.executemany(
            "DELETE FROM vectors WHERE chunk_id=?",
            ((item,) for item in chunk_ids if item not in preserve),
        )
        connection.execute("DELETE FROM chunks WHERE source_uid=?", (source_uid,))
        connection.execute("DELETE FROM sources WHERE source_uid=?", (source_uid,))


def _write_manifest(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    mode: str,
    sources: int,
    chunks: int,
    changed: int,
    reused: int,
    removed: int,
    duration: float,
) -> None:
    total_embeddings = connection.execute("SELECT count(*) FROM vectors").fetchone()[0]
    connection.execute(
        """
        INSERT INTO build_manifest(
            run_id,built_at,mode,sources,chunks,embeddings,duration_seconds,
            changed_sources,reused_sources,removed_sources
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            time.time(),
            mode,
            sources,
            chunks,
            total_embeddings,
            duration,
            changed,
            reused,
            removed,
        ),
    )


def _integrity(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise sqlite3.DatabaseError(result)


def _full_build(
    config: Config,
    sources: list[SourceDocument],
    chunks: list[Chunk],
    *,
    run_id: str,
    started: float,
    mode: str,
) -> RagBuildSummary:
    database = config.rag.database
    temporary = database.with_name(f".{database.name}.{uuid.uuid4().hex}.rebuild")
    embedded = 0
    replaced = False
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(temporary, rebuild_writer=True)
        with connection:
            initialize_database(connection)
            _insert_sources(connection, sources)
            _insert_chunks(connection, chunks)
            embedded = _embed_missing(connection, config, chunks)
            duration = time.perf_counter() - started
            _write_manifest(
                connection,
                run_id=run_id,
                mode=mode,
                sources=len(sources),
                chunks=len(chunks),
                changed=len(sources),
                reused=0,
                removed=0,
                duration=duration,
            )
            _integrity(connection)
        connection.close()
        connection = None
        os.replace(temporary, database)
        replaced = True
    finally:
        if connection is not None:
            connection.close()
        if not replaced and temporary.exists():
            temporary.unlink()
    return RagBuildSummary(
        database,
        run_id,
        mode,
        len(sources),
        len(chunks),
        embedded,
        time.perf_counter() - started,
        len(sources),
        0,
        0,
    )


def _incremental_build(
    config: Config,
    sources: list[SourceDocument],
    chunks: list[Chunk],
    *,
    run_id: str,
    started: float,
) -> RagBuildSummary:
    database = config.rag.database
    temporary = database.with_name(f".{database.name}.{uuid.uuid4().hex}.build")
    replaced = False
    connection: sqlite3.Connection | None = None
    try:
        shutil.copy2(database, temporary)
        connection = _connect(temporary, rebuild_writer=True)
        try:
            with connection:
                _integrity(connection)
                initialize_database(connection)
                old = {
                    str(row["source_uid"]): dict(row)
                    for row in connection.execute("SELECT * FROM sources")
                }
                current = {source.source_uid: source for source in sources}
                removed = set(old) - set(current)
                changed = {
                    uid
                    for uid, source in current.items()
                    if uid not in old
                    or (
                        old[uid]["source_path"],
                        old[uid]["source_type"],
                        old[uid]["title"],
                        old[uid]["visibility"],
                        old[uid]["content_hash"],
                        old[uid]["updated"],
                    )
                    != (
                        source.source_path,
                        source.source_type,
                        source.title,
                        source.visibility,
                        source.content_hash,
                        source.updated,
                    )
                }
                changed_chunks = [chunk for chunk in chunks if chunk.source_uid in changed]
                new_chunk_ids = {chunk.chunk_id for chunk in changed_chunks}
                _delete_sources(connection, removed)
                _delete_sources(
                    connection,
                    changed & set(old),
                    preserve_vector_ids=new_chunk_ids,
                )
                changed_sources = [source for source in sources if source.source_uid in changed]
                _insert_sources(connection, changed_sources)
                _insert_chunks(connection, changed_chunks)
                embedded = _embed_missing(connection, config, chunks)
                reused = len(sources) - len(changed)
                duration = time.perf_counter() - started
                _write_manifest(
                    connection,
                    run_id=run_id,
                    mode="build",
                    sources=len(sources),
                    chunks=len(chunks),
                    changed=len(changed),
                    reused=reused,
                    removed=len(removed),
                    duration=duration,
                )
                _integrity(connection)
            connection.close()
            connection = None
            os.replace(temporary, database)
            replaced = True
        finally:
            if connection is not None:
                connection.close()
    except (OSError, sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
        raise IncrementalUnavailable(str(exc)) from exc
    finally:
        if not replaced and temporary.exists():
            temporary.unlink()
    return RagBuildSummary(
        database,
        run_id,
        "build",
        len(sources),
        len(chunks),
        embedded,
        time.perf_counter() - started,
        len(changed),
        reused,
        len(removed),
    )


def rebuild_rag(config: Config, *, incremental: bool = False) -> RagBuildSummary:
    _require_enabled(config)
    started = time.perf_counter()
    run_id = time.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    sources, chunks = _collect(config)
    with vault_lock(config, "rag-rebuild"):
        if incremental and config.rag.database.is_file():
            try:
                return _incremental_build(
                    config, sources, chunks, run_id=run_id, started=started
                )
            except IncrementalUnavailable:
                return _full_build(
                    config,
                    sources,
                    chunks,
                    run_id=run_id,
                    started=started,
                    mode="build-fallback",
                )
        return _full_build(
            config,
            sources,
            chunks,
            run_id=run_id,
            started=started,
            mode="build-fallback" if incremental else "rebuild",
        )


def _fts_query(query: str) -> str:
    words = re.findall(r"[\wА-Яа-яІіЇїЄєҐґ']+", query, flags=re.UNICODE)
    if not words:
        return '""'
    return " OR ".join(f'"{word}"' for word in words[:12])


def _fts_candidates(
    connection: sqlite3.Connection, query: str, limit: int
) -> list[dict]:
    try:
        rows = connection.execute(
            """
            SELECT c.chunk_id,c.source_uid,c.source_path,c.source_type,c.title,
                   c.heading_path,snippet(chunks_fts,3,'[',']',' … ',24) AS snippet,
                   bm25(chunks_fts) AS fts_score
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id=chunks_fts.chunk_id
            WHERE chunks_fts MATCH ? AND c.visibility IN ('public','internal')
            ORDER BY fts_score LIMIT ?
            """,
            (_fts_query(query), limit),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        rows = connection.execute(
            """
            SELECT chunk_id,source_uid,source_path,source_type,title,heading_path,
                   substr(content,1,240) AS snippet,0.0 AS fts_score
            FROM chunks
            WHERE visibility IN ('public','internal') AND content LIKE ?
            LIMIT ?
            """,
            (f"%{query}%", limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _vector_candidates(
    connection: sqlite3.Connection,
    config: Config,
    query: str,
    limit: int,
) -> list[dict]:
    if not config.rag.embeddings.enabled:
        return []
    query_vector = embed_text(config, query)
    if not query_vector:
        return []
    rows: list[dict] = []
    for row in connection.execute(
        """
        SELECT c.chunk_id,c.source_uid,c.source_path,c.source_type,c.title,
               c.heading_path,substr(c.content,1,240) AS snippet,
               v.provider,v.model,v.dimension,v.vector
        FROM vectors v JOIN chunks c ON c.chunk_id=v.chunk_id
        WHERE c.visibility IN ('public','internal') AND v.provider=? AND v.model=?
        """,
        (config.rag.embeddings.provider, config.rag.embeddings.model),
    ):
        if int(row["dimension"]) != len(query_vector):
            continue
        try:
            similarity = cosine(query_vector, blob_to_vector(row["vector"]))
        except (ValueError, TypeError):
            continue
        item = dict(row)
        item.pop("vector", None)
        item["vector_score"] = similarity
        rows.append(item)
    rows.sort(key=lambda item: (-float(item["vector_score"]), item["chunk_id"]))
    return rows[:limit]


def query_sources(config: Config, query: str, limit: int | None = None) -> list[dict]:
    _require_enabled(config)
    database = config.rag.database
    if not database.is_file():
        raise FileNotFoundError("Run `vaultctl rag rebuild` first")
    top_k = limit or config.rag.default_top_k
    candidate_limit = min(400, max(top_k * 4, top_k))
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        fts = _fts_candidates(connection, query, candidate_limit)
        vectors = _vector_candidates(connection, config, query, candidate_limit)
        combined: dict[str, dict] = {}
        for rank, row in enumerate(fts, 1):
            item = combined.setdefault(row["chunk_id"], dict(row))
            item["fts_score"] = row.get("fts_score")
            item["score"] = float(item.get("score", 0.0)) + 0.6 / (60 + rank)
            item["retrieval"] = "fts"
        for rank, row in enumerate(vectors, 1):
            item = combined.setdefault(row["chunk_id"], dict(row))
            item["vector_score"] = row.get("vector_score")
            item["score"] = float(item.get("score", 0.0)) + 0.4 / (60 + rank)
            item["retrieval"] = "hybrid" if item.get("retrieval") == "fts" else "vector"
        rows = sorted(
            combined.values(),
            key=lambda item: (
                -float(item.get("score", 0.0)),
                str(item.get("source_path", "")),
                str(item.get("chunk_id", "")),
            ),
        )[:top_k]
        for row in rows:
            row.pop("provider", None)
            row.pop("model", None)
            row.pop("dimension", None)
        return rows
    finally:
        connection.close()


def latest_manifest(config: Config) -> dict:
    database = config.rag.database
    if not database.is_file():
        return {}
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT * FROM build_manifest ORDER BY built_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else {}
    finally:
        connection.close()


def write_sources_report(config: Config, query: str, rows: list[dict]) -> Path:
    run_dir = config.runtime / "rag" / (
        time.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "sources.json").write_text(
        json.dumps({"query": query, "results": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [f"# RAG sources: {query}", ""]
    for index, row in enumerate(rows, 1):
        lines.append(f"## {index}. {row['title']}")
        lines.append("")
        lines.append(f"- Path: `{row['source_path']}`")
        lines.append(f"- Heading: `{row.get('heading_path') or ''}`")
        lines.append(f"- Chunk: `{row['chunk_id']}`")
        lines.append(f"- Retrieval: `{row.get('retrieval', 'fts')}`")
        lines.append("")
        lines.append(str(row.get("snippet", "")).replace("\n", " "))
        lines.append("")
    (run_dir / "sources.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8"
    )
    return run_dir
