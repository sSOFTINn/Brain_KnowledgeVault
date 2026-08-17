from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
import re

from .config import Config
from .gitpolicy import oversized_tracked_files
from .metadata import parse_frontmatter, validate_metadata
from .policy import backup_includes_private
from .scaffold import DIRECTORIES


WIKILINK = re.compile(r"\[\[([^\]|#]+)")
PLACEHOLDER = re.compile(r"\{\{[^}]+\}\}")
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass
class Finding:
    level: str
    code: str
    path: str
    message: str


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_vault(config: Config) -> list[Finding]:
    findings: list[Finding] = []

    def add(level: str, code: str, path: Path | str, message: str) -> None:
        try:
            display = str(Path(path).relative_to(config.root))
        except ValueError:
            display = str(path)
        findings.append(Finding(level, code, display, message))

    required_directories = (
        config.storage.directories if config.schema_version == 2 else DIRECTORIES
    )
    for relative in required_directories:
        path = config.root / relative
        if not path.is_dir():
            add("ERROR", "missing-directory", path, "required directory is missing")

    if backup_includes_private(config):
        add("WARN", "backup-private-scope", config.private, "Private is included only in encrypted backup scope; AI/RAG/Graph remain excluded")

    if config.git_enabled:
        for path in oversized_tracked_files(config):
            add(
                "ERROR",
                "git-tracked-file-too-large",
                path,
                f"tracked file exceeds git.max_tracked_file_mb={config.max_tracked_file_mb}",
            )

    if not config.vault.exists():
        return findings

    markdown = sorted(config.vault.rglob("*.md"))
    stems: dict[str, list[Path]] = {}
    uid_paths: dict[str, Path] = {}
    metadata_by_path: dict[Path, dict] = {}
    case_paths: dict[str, Path] = {}

    for path in config.root.rglob("*"):
        relative_key = str(path.relative_to(config.root)).casefold()
        previous = case_paths.get(relative_key)
        if previous and previous != path:
            add("ERROR", "case-collision", path, f"collides with {previous}")
        else:
            case_paths[relative_key] = path
        if len(str(path)) > 240:
            add("WARN", "long-path", path, "path exceeds 240 characters")
        for part in path.parts:
            if part.rstrip(" .").casefold().split(".")[0] in WINDOWS_RESERVED:
                add("ERROR", "reserved-name", path, f"Windows reserved name: {part}")
            if part != part.rstrip(" ."):
                add("ERROR", "invalid-name", path, "name ends with a dot or space")

    for path in markdown:
        template = "90_Templates" in path.parts
        stems.setdefault(path.stem.casefold(), []).append(path)
        try:
            data, body = parse_frontmatter(path)
        except (OSError, UnicodeError, ValueError) as exc:
            add("ERROR", "frontmatter", path, str(exc))
            continue
        metadata_by_path[path] = data
        for error in validate_metadata(data, template=template):
            add("ERROR", "metadata", path, error)
        uid = str(data.get("uid", ""))
        if not template and uid:
            if uid in uid_paths:
                add("ERROR", "duplicate-uid", path, f"also used by {uid_paths[uid]}")
            else:
                uid_paths[uid] = path
        if data.get("visibility") == "restricted":
            add("ERROR", "restricted-in-vault", path, "restricted content must be stored outside Vault")
        if not template and PLACEHOLDER.search(path.read_text(encoding="utf-8")):
            add("ERROR", "placeholder", path, "unresolved template placeholder")
        if data.get("type") == "project" and data.get("status") == "active":
            try:
                updated = date.fromisoformat(str(data.get("updated")))
                if date.today() - updated > timedelta(days=30):
                    add("WARN", "stale-project", path, "active project was not updated for 30 days")
            except ValueError:
                pass

    for path, data in metadata_by_path.items():
        if "90_Templates" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for target in WIKILINK.findall(text):
            target_stem = Path(target.strip()).stem.casefold()
            if target_stem not in stems:
                add("ERROR", "broken-wikilink", path, f"target not found: {target}")
            elif len(stems[target_stem]) > 1:
                add("WARN", "ambiguous-wikilink", path, f"multiple targets: {target}")
        if re.search(r"(?i)\b[A-Z]:[\\/]", text):
            add("WARN", "absolute-path", path, "contains an absolute Windows path")

    hashes: dict[tuple[int, str], Path] = {}
    if config.assets.exists():
        for asset in config.assets.rglob("*"):
            if not asset.is_file() or asset.name.endswith(".asset.md"):
                continue
            asset_hash = _digest(asset)
            key = (asset.stat().st_size, asset_hash)
            if key in hashes:
                add("WARN", "duplicate-asset", asset, f"same content as {hashes[key]}")
            else:
                hashes[key] = asset
            sidecar = asset.with_name(asset.name + ".asset.md")
            if not sidecar.exists():
                add("WARN", "missing-sidecar", asset, "asset metadata sidecar is missing")
                continue
            try:
                data, _ = parse_frontmatter(sidecar)
            except (OSError, UnicodeError, ValueError) as exc:
                add("ERROR", "asset-sidecar", sidecar, str(exc))
                continue
            for error in validate_metadata(data):
                add("ERROR", "asset-sidecar-metadata", sidecar, error)
            if data.get("type") != "asset":
                add("ERROR", "asset-sidecar-type", sidecar, "type must be asset")
            if data.get("sha256") != asset_hash:
                add("ERROR", "asset-sidecar-hash", sidecar, "sha256 does not match asset")
            expected_path = asset.relative_to(config.assets).as_posix()
            if data.get("asset_path") != expected_path:
                add(
                    "ERROR",
                    "asset-sidecar-path",
                    sidecar,
                    f"asset_path must be {expected_path}",
                )
    return findings


def findings_as_dict(findings: list[Finding]) -> list[dict]:
    return [asdict(finding) for finding in findings]


def has_errors(findings: list[Finding]) -> bool:
    return any(finding.level == "ERROR" for finding in findings)
