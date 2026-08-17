from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import sqlite3
import uuid

from .config import Config
from .locks import vault_lock
from .metadata import parse_frontmatter
from .policy import can_read_path, is_indexable_text_path
from .fileops import file_sha256
from .schema import ensure_schema_migrations


HEADING = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE objects (
    uid TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    visibility TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE files (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT,
    kind TEXT NOT NULL
);

CREATE TABLE notes (
    uid TEXT PRIMARY KEY REFERENCES objects(uid) ON DELETE CASCADE,
    headings TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE assets (
    path TEXT PRIMARY KEY REFERENCES files(path) ON DELETE CASCADE,
    sidecar_uid TEXT,
    project_code TEXT
);

CREATE TABLE projects (
    uid TEXT PRIMARY KEY REFERENCES objects(uid) ON DELETE CASCADE,
    code TEXT,
    next_action TEXT
);

CREATE TABLE relations (
    source_uid TEXT NOT NULL REFERENCES objects(uid) ON DELETE CASCADE,
    target TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    UNIQUE(source_uid, target, relation_type)
);

CREATE TABLE tags (
    uid TEXT NOT NULL REFERENCES objects(uid) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    UNIQUE(uid, tag)
);

CREATE TABLE scan_runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT,
    source_root TEXT,
    hash_mode TEXT,
    path TEXT NOT NULL
);

CREATE TABLE migration_runs (
    run_id TEXT PRIMARY KEY,
    rows INTEGER NOT NULL,
    path TEXT NOT NULL
);

CREATE TABLE errors (
    run_id TEXT,
    path TEXT,
    error_type TEXT,
    message TEXT
);

CREATE VIRTUAL TABLE search_fts USING fts5(
    uid UNINDEXED,
    title,
    aliases,
    tags,
    headings,
    body,
    project,
    source_metadata,
    tokenize = 'unicode61'
);
"""


@dataclass
class IndexSummary:
    database: Path
    objects: int
    files: int
    assets: int
    relations: int
    scan_runs: int
    errors: int


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _string_list(value) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _markdown_paths(config: Config) -> list[Path]:
    if config.schema_version != 2:
        return sorted(config.vault.rglob("*.md")) if config.vault.exists() else []
    roots = (
        config.vault,
        config.documents,
        config.workspaces,
        config.resources,
        config.media,
        config.archive,
    )
    paths: set[Path] = set()
    for root in roots:
        if root.exists():
            paths.update(
                path for path in root.rglob("*.md") if is_indexable_text_path(path, config)
            )
    return sorted(paths)


def _document_metadata(path: Path, config: Config) -> tuple[dict, str] | None:
    try:
        return parse_frontmatter(path)
    except (OSError, UnicodeError, ValueError):
        if config.schema_version != 2 or not is_indexable_text_path(path, config):
            return None
        try:
            body = path.read_text(encoding="utf-8")
            relative = _relative(path, config.root)
            updated = str(path.stat().st_mtime_ns)
        except (OSError, UnicodeError, ValueError):
            return None
        return (
            {
                "uid": "document:" + file_sha256(path),
                "type": "document",
                "title": path.stem,
                "status": "active",
                "visibility": config.default_visibility,
                "updated": updated,
                "aliases": [],
                "tags": [],
                "source_path": relative,
            },
            body,
        )


def _index_markdown(connection: sqlite3.Connection, config: Config) -> dict[str, str]:
    uid_by_stem: dict[str, str] = {}
    pending_relations: list[tuple[str, str]] = []
    for path in _markdown_paths(config):
        if "90_Templates" in path.parts:
            continue
        document = _document_metadata(path, config)
        if document is None:
            continue
        metadata, body = document
        decision = can_read_path(path, config, "dashboard", metadata=metadata)
        if not decision.allowed:
            continue
        uid = str(metadata["uid"])
        object_type = str(metadata["type"])
        title = str(metadata["title"])
        relative = _relative(path, config.root)
        aliases = _string_list(metadata.get("aliases"))
        tags = _string_list(metadata.get("tags"))
        headings = HEADING.findall(body)
        project = str(metadata.get("project", ""))
        info = path.stat()
        connection.execute(
            "INSERT INTO files(path,size,mtime_ns,sha256,kind) VALUES(?,?,?,?,?)",
            (relative, info.st_size, info.st_mtime_ns, None, "markdown"),
        )
        connection.execute(
            """
            INSERT INTO objects(uid,type,title,status,path,visibility,updated)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                uid,
                object_type,
                title,
                str(metadata["status"]),
                relative,
                str(metadata["visibility"]),
                str(metadata["updated"]),
            ),
        )
        connection.execute(
            "INSERT INTO notes(uid,headings,body) VALUES(?,?,?)",
            (uid, "\n".join(headings), body),
        )
        connection.executemany(
            "INSERT INTO tags(uid,tag) VALUES(?,?)",
            ((uid, tag) for tag in tags),
        )
        if object_type == "project":
            connection.execute(
                "INSERT INTO projects(uid,code,next_action) VALUES(?,?,?)",
                (
                    uid,
                    str(metadata.get("code", "")),
                    str(metadata.get("next_action", "")),
                ),
            )
        connection.execute(
            """
            INSERT INTO search_fts(
                uid,title,aliases,tags,headings,body,project,source_metadata
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                uid,
                title,
                " ".join(aliases),
                " ".join(tags),
                "\n".join(headings),
                body,
                project,
                f"{object_type} {metadata['status']} {metadata['visibility']} {relative}",
            ),
        )
        uid_by_stem[path.stem.casefold()] = uid
        pending_relations.extend((uid, target.strip()) for target in WIKILINK.findall(body))

    for source_uid, target in pending_relations:
        resolved = uid_by_stem.get(Path(target).stem.casefold(), target)
        connection.execute(
            "INSERT OR IGNORE INTO relations(source_uid,target,relation_type) VALUES(?,?,?)",
            (source_uid, resolved, "wikilink"),
        )
    return uid_by_stem


def _index_assets(connection: sqlite3.Connection, config: Config) -> int:
    count = 0
    if not config.assets.exists():
        return count
    for path in sorted(config.assets.rglob("*")):
        if not path.is_file() or path.name.endswith(".asset.md"):
            continue
        info = path.stat()
        relative = _relative(path, config.root)
        sidecar = path.with_name(path.name + ".asset.md")
        sidecar_uid = None
        project_code = None
        title = path.name
        visibility = "internal"
        tags: list[str] = []
        if sidecar.is_file():
            try:
                metadata, _ = parse_frontmatter(sidecar)
                sidecar_uid = str(metadata.get("uid", "")) or None
                project_code = str(metadata.get("project_code", "")) or None
                title = str(metadata.get("title", path.name))
                visibility = str(metadata.get("visibility", "internal"))
                tags = _string_list(metadata.get("tags"))
            except (OSError, UnicodeError, ValueError):
                pass
        if not can_read_path(path, config, "dashboard").allowed:
            continue
        digest = file_sha256(path)
        connection.execute(
            "INSERT INTO files(path,size,mtime_ns,sha256,kind) VALUES(?,?,?,?,?)",
            (relative, info.st_size, info.st_mtime_ns, digest, "asset"),
        )
        connection.execute(
            "INSERT INTO assets(path,sidecar_uid,project_code) VALUES(?,?,?)",
            (relative, sidecar_uid, project_code),
        )
        cache_name = "Caches" if config.schema_version == 2 else "cache"
        extracted = config.runtime / cache_name / "extracted" / f"{digest}.txt"
        if extracted.is_file() and visibility in {"public", "internal"}:
            body = extracted.read_text(encoding="utf-8", errors="replace")
            connection.execute(
                """
                INSERT INTO search_fts(
                    uid,title,aliases,tags,headings,body,project,source_metadata
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    sidecar_uid or f"asset:{digest}",
                    title,
                    "",
                    " ".join(tags),
                    "",
                    body,
                    project_code or "",
                    f"asset {visibility} {relative}",
                ),
            )
        count += 1
    return count


def _index_runs(connection: sqlite3.Connection, config: Config) -> None:
    runs_root = (
        config.routing_runtime
        if config.schema_version == 2
        else config.runtime / "runs"
    )
    if not runs_root.exists():
        return
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        run_json = run_dir / "run.json"
        if run_json.is_file():
            try:
                data = json.loads(run_json.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT OR REPLACE INTO scan_runs(
                        run_id,created_at,source_root,hash_mode,path
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        data["run_id"],
                        data.get("created_at"),
                        data.get("source_root"),
                        data.get("hash_mode"),
                        _relative(run_dir, config.root),
                    ),
                )
            except (OSError, ValueError, KeyError):
                pass
        plan = run_dir / "migration_plan.jsonl"
        if plan.is_file():
            rows = sum(1 for line in plan.read_text(encoding="utf-8").splitlines() if line)
            connection.execute(
                "INSERT OR REPLACE INTO migration_runs(run_id,rows,path) VALUES(?,?,?)",
                (run_dir.name, rows, _relative(run_dir, config.root)),
            )
        errors = run_dir / "errors.jsonl"
        if errors.is_file():
            with errors.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        error = json.loads(line)
                        connection.execute(
                            "INSERT INTO errors(run_id,path,error_type,message) VALUES(?,?,?,?)",
                            (
                                run_dir.name,
                                error.get("path"),
                                error.get("error_type"),
                                error.get("message"),
                            ),
                        )
                    except ValueError:
                        continue


def rebuild_index(config: Config) -> IndexSummary:
    database = config.runtime / (
        "Catalog/catalog.sqlite3" if config.schema_version == 2 else "db/catalog.sqlite3"
    )
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_name(
        f".{database.name}.{uuid.uuid4().hex}.rebuild"
    )
    try:
        connection = sqlite3.connect(temporary)
        try:
            with vault_lock(config, "catalog-rebuild"):
                connection.executescript(SCHEMA)
                with connection:
                    ensure_schema_migrations(connection, "catalog", 1)
                    _index_markdown(connection, config)
                    _index_assets(connection, config)
                    _index_runs(connection, config)
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise sqlite3.DatabaseError(f"Integrity check failed: {integrity}")
        finally:
            connection.close()
        os.replace(temporary, database)
    finally:
        if temporary.exists():
            temporary.unlink()

    connection = sqlite3.connect(database)
    try:
        return IndexSummary(
            database=database,
            objects=connection.execute("SELECT count(*) FROM objects").fetchone()[0],
            files=connection.execute("SELECT count(*) FROM files").fetchone()[0],
            assets=connection.execute("SELECT count(*) FROM assets").fetchone()[0],
            relations=connection.execute("SELECT count(*) FROM relations").fetchone()[0],
            scan_runs=connection.execute("SELECT count(*) FROM scan_runs").fetchone()[0],
            errors=connection.execute("SELECT count(*) FROM errors").fetchone()[0],
        )
    finally:
        connection.close()


def integrity_check(config: Config) -> str:
    database = config.runtime / (
        "Catalog/catalog.sqlite3" if config.schema_version == 2 else "db/catalog.sqlite3"
    )
    if not database.is_file():
        raise FileNotFoundError(f"Catalog does not exist: {database}")
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        fts = connection.execute(
            "SELECT count(*) FROM search_fts WHERE search_fts MATCH 'KnowledgeVault'"
        ).fetchone()[0]
        return f"{result}; fts-query-ok={fts >= 0}"
    finally:
        connection.close()


def search_index(config: Config, query: str, limit: int = 20) -> list[dict]:
    database = config.runtime / (
        "Catalog/catalog.sqlite3" if config.schema_version == 2 else "db/catalog.sqlite3"
    )
    if not database.is_file():
        raise FileNotFoundError("Run `vaultctl index --rebuild` first")
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT uid, title, snippet(search_fts, 5, '[', ']', ' … ', 16) AS snippet,
                   rank
            FROM search_fts
            WHERE search_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()
