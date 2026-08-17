from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import csv
import json

import yaml
from docx import Document
from pypdf import PdfReader

from .config import Config
from .locks import vault_lock
from .metadata import parse_frontmatter
from .policy import can_read_path
from .fileops import file_sha256


SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".yaml", ".yml"}
MAX_SIZE = 25 * 1024 * 1024


@dataclass
class Extraction:
    asset_path: str
    sha256: str
    cache_path: str
    characters: int
    status: str
    reason: str = ""


def _text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        document = Document(path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            return "\n".join(" | ".join(row) for row in csv.reader(handle))
    if suffix == ".json":
        return json.dumps(
            json.loads(path.read_text(encoding="utf-8-sig")),
            ensure_ascii=False,
            indent=2,
        )
    if suffix in {".yaml", ".yml"}:
        return yaml.safe_dump(
            yaml.safe_load(path.read_text(encoding="utf-8-sig")),
            allow_unicode=True,
            sort_keys=False,
        )
    if suffix == ".md":
        try:
            _, body = parse_frontmatter(path)
            return body
        except ValueError:
            pass
    return path.read_text(encoding="utf-8-sig", errors="replace")


def rebuild_extractions(config: Config) -> tuple[Path, list[Extraction]]:
    cache_name = "Caches" if config.schema_version == 2 else "cache"
    cache = config.runtime / cache_name / "extracted"
    cache.mkdir(parents=True, exist_ok=True)
    with vault_lock(config, "extract-rebuild"):
        for old in cache.glob("*.txt"):
            old.unlink()
        results: list[Extraction] = []
        for asset in sorted(config.assets.rglob("*")):
            if not asset.is_file() or asset.name.endswith(".asset.md"):
                continue
            sidecar = asset.with_name(asset.name + ".asset.md")
            if not sidecar.is_file():
                results.append(Extraction(str(asset), "", "", 0, "skipped", "missing sidecar"))
                continue
            try:
                parse_frontmatter(sidecar)
            except (OSError, UnicodeError, ValueError) as exc:
                results.append(Extraction(str(asset), "", "", 0, "error", str(exc)))
                continue
            decision = can_read_path(asset, config, "rag")
            if not decision.allowed:
                results.append(Extraction(str(asset), "", "", 0, "skipped", decision.reason))
                continue
            if asset.suffix.lower() not in SUPPORTED:
                results.append(Extraction(str(asset), "", "", 0, "skipped", "unsupported type"))
                continue
            if asset.stat().st_size > MAX_SIZE:
                results.append(Extraction(str(asset), "", "", 0, "skipped", "larger than 25 MB"))
                continue
            digest = file_sha256(asset)
            target = cache / f"{digest}.txt"
            try:
                content = _text(asset).strip()
                target.write_text(content + ("\n" if content else ""), encoding="utf-8")
                results.append(
                    Extraction(str(asset), digest, str(target), len(content), "extracted")
                )
            except Exception as exc:
                results.append(
                    Extraction(str(asset), digest, "", 0, "error", f"{type(exc).__name__}: {exc}")
                )
        manifest = cache / "manifest.json"
        manifest.write_text(
            json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest, results
