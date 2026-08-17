from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import uuid

import yaml


REQUIRED_FIELDS = {
    "schema_version",
    "uid",
    "type",
    "title",
    "status",
    "created",
    "updated",
    "tags",
    "aliases",
    "visibility",
}

TYPE_STATUSES = {
    "project": {"idea", "planned", "active", "paused", "completed", "cancelled", "archived"},
    "task": {"todo", "doing", "blocked", "done", "cancelled"},
    "decision": {"proposed", "accepted", "superseded", "deprecated"},
    "document": {"draft", "active", "final", "archived"},
    "resource": {"unread", "reading", "processed", "archived"},
    "meeting": {"raw", "processed", "archived"},
    "area": {"active", "archived"},
    "note": {"draft", "active", "archived"},
    "research": {"draft", "active", "final", "archived"},
    "how-to": {"draft", "active", "deprecated", "archived"},
    "postmortem": {"draft", "final", "archived"},
    "context": {"active", "archived"},
    "memory": {"active", "archived"},
    "index": {"active", "archived"},
    "session-log": {"active", "archived"},
    "asset": {"active", "archived"},
    "person": {"active", "inactive", "archived"},
}

VISIBILITIES = {"public", "internal", "confidential", "restricted"}
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


class MetadataError(ValueError):
    """A normalized, content-safe metadata parsing failure."""


def new_uid() -> str:
    return str(uuid.uuid7() if hasattr(uuid, "uuid7") else uuid.uuid4())


def today() -> str:
    return date.today().isoformat()


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise MetadataError("file is not valid UTF-8") from exc
    match = FRONTMATTER.match(text)
    if not match:
        raise MetadataError("missing YAML frontmatter")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or type(exc).__name__
        raise MetadataError(f"invalid YAML frontmatter: {problem}") from exc
    if not isinstance(data, dict):
        raise MetadataError("frontmatter must be a YAML mapping")
    return data, text[match.end():]


def validate_metadata(data: dict, *, template: bool = False) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - data.keys())
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
        return errors
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    uid_value = str(data.get("uid", ""))
    if template and "{{" in uid_value:
        pass
    else:
        try:
            uuid.UUID(uid_value)
        except ValueError:
            errors.append("uid must be a UUID")

    object_type = data.get("type")
    status = data.get("status")
    if object_type not in TYPE_STATUSES:
        errors.append(f"unsupported type: {object_type}")
    elif status not in TYPE_STATUSES[object_type]:
        errors.append(f"status '{status}' is invalid for type '{object_type}'")

    for field in ("created", "updated"):
        value = data.get(field)
        if template and isinstance(value, str) and "{{" in value:
            continue
        try:
            date.fromisoformat(str(value))
        except ValueError:
            errors.append(f"{field} must use YYYY-MM-DD")

    if data.get("visibility") not in VISIBILITIES:
        errors.append("visibility is invalid")
    for field in ("tags", "aliases"):
        if not isinstance(data.get(field), list):
            errors.append(f"{field} must be a YAML list")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        errors.append("title must be a non-empty string")
    return errors
