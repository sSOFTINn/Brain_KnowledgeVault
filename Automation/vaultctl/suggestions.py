from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import json
import re
import uuid

from .config import Config
from .metadata import parse_frontmatter
from .fileops import file_sha256
from .router import normalized


def generate_suggestions(config: Config, kind: str = "all") -> Path:
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    output = config.runtime / "suggestions" / run_id
    output.mkdir(parents=True, exist_ok=False)
    suggestions: dict[str, list[dict]] = {"moc": [], "stale": [], "duplicates": []}
    tags: dict[str, list[str]] = defaultdict(list)
    titles: dict[str, list[str]] = defaultdict(list)

    for path in sorted(config.vault.rglob("*.md")):
        if "90_Templates" in path.parts:
            continue
        try:
            metadata, body = parse_frontmatter(path)
        except (OSError, UnicodeError, ValueError):
            continue
        relative = path.relative_to(config.vault).as_posix()
        for tag in metadata.get("tags", []) if isinstance(metadata.get("tags"), list) else []:
            tags[str(tag)].append(relative)
        titles[normalized(str(metadata.get("title", "")))].append(relative)
        if metadata.get("type") == "project" and metadata.get("status") == "active":
            try:
                age = (date.today() - date.fromisoformat(str(metadata["updated"]))).days
                if age > 30:
                    suggestions["stale"].append({"path": relative, "days": age})
            except ValueError:
                pass
        links = re.findall(r"\[\[([^\]|#]+)", body)
        if len(links) >= 3:
            suggestions["moc"].append(
                {"basis": "links", "path": relative, "links": sorted(set(links))}
            )

    for tag, paths in sorted(tags.items()):
        if len(paths) >= 2:
            suggestions["moc"].append({"basis": "tag", "tag": tag, "paths": paths})
    for title, paths in titles.items():
        if title and len(paths) > 1:
            suggestions["duplicates"].append(
                {"basis": "normalized-title", "title": title, "paths": paths}
            )

    hashes: dict[str, list[str]] = defaultdict(list)
    for asset in sorted(config.assets.rglob("*")):
        if asset.is_file() and not asset.name.endswith(".asset.md"):
            hashes[file_sha256(asset)].append(asset.relative_to(config.root).as_posix())
    for digest, paths in hashes.items():
        if len(paths) > 1:
            suggestions["duplicates"].append(
                {"basis": "sha256", "sha256": digest, "paths": paths}
            )

    selected = suggestions if kind == "all" else {kind: suggestions[kind]}
    (output / "suggestions.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# KnowledgeVault suggestions", "", "AUTO-GENERATED. DO NOT EDIT MANUALLY."]
    for category, items in selected.items():
        lines.extend(["", f"## {category}", ""])
        lines.extend(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in items)
        if not items:
            lines.append("No suggestions.")
    (output / "suggestions.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    return output
