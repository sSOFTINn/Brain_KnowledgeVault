from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os

from .config import Config
from .metadata import parse_frontmatter, validate_metadata


AI_READ_PURPOSES = {"rag", "embeddings", "llm", "wiki", "graph", "dashboard"}
SAFE_VISIBILITIES = {"public", "internal"}
CONFIDENTIAL_VISIBILITIES = {"confidential", "restricted"}
INDEX_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "bin",
    "obj",
    "dist",
    "build",
    "__pycache__",
    "90_runtime",
    "99_quarantine",
}
SENSITIVE_NAMES = {".env", "auth.json", "credentials.json", "secrets.json"}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    visibility: str
    reason: str


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_private_path(path: Path, config: Config) -> bool:
    return _contains(config.private, path)


def is_vault_path(path: Path, config: Config) -> bool:
    return _contains(config.vault, path)


def is_asset_path(path: Path, config: Config) -> bool:
    return _contains(config.assets, path)


def is_indexable_text_path(path: Path, config: Config) -> bool:
    resolved = path.resolve(strict=False)
    if config.schema_version != 2:
        return _contains_resolved(config.vault, resolved)
    relative_parts = {part.casefold() for part in resolved.parts}
    if relative_parts & INDEX_EXCLUDED_PARTS:
        return False
    if resolved.name.casefold() in SENSITIVE_NAMES or resolved.name.casefold().startswith(".env."):
        return False
    if (
        _contains_resolved(config.private, resolved)
        or _contains_resolved(config.runtime, resolved)
        or _contains_resolved(config.quarantine, resolved)
    ):
        return False
    if any(
        _contains_resolved(root, resolved)
        for root in (config.vault, config.documents, config.archive)
    ):
        return True
    if _contains_resolved(config.workspaces, resolved):
        return any(part.casefold() in {"docs", "doc", "documentation"} for part in resolved.parts)
    if _contains_resolved(config.media, resolved) or _contains_resolved(config.resources, resolved):
        return resolved.suffix.lower() in {".md", ".txt"}
    return False


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _has_reparse_component(path: Path, root: Path) -> bool:
    lexical = Path(os.path.abspath(path))
    lexical_root = Path(os.path.abspath(root))
    try:
        relative = lexical.relative_to(lexical_root)
    except ValueError:
        return False

    # Resolve only after the lexical containment check.  Otherwise a junction
    # inside the vault can make an apparently safe path resolve outside the
    # configured root before we have inspected the path components.
    current = lexical_root
    candidates = (lexical_root, *(lexical_root / Path(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1)))
    for current in candidates:
        try:
            info = current.lstat()
        except FileNotFoundError:
            # A missing final component is not a reparse point.  Its existing
            # parents have already been checked.
            continue
        except OSError:
            return True
        attributes = getattr(info, "st_file_attributes", 0)
        if current.is_symlink() or bool(attributes & 0x400):
            return True
    try:
        lexical.resolve().relative_to(lexical_root.resolve())
    except (OSError, ValueError):
        return True
    return False


def _contains_resolved(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _asset_visibility(path: Path, config: Config) -> tuple[str, str]:
    if path.name.endswith(".asset.md"):
        return "restricted", "asset sidecars are metadata, not readable assets"
    sidecar = path.with_name(path.name + ".asset.md")
    if not sidecar.is_file():
        return "restricted", "asset sidecar is missing"
    try:
        metadata, _ = parse_frontmatter(sidecar)
    except (OSError, ValueError) as exc:
        return "restricted", f"invalid asset sidecar: {exc}"
    errors = validate_metadata(metadata)
    if errors:
        return "restricted", "invalid asset sidecar metadata: " + "; ".join(errors)
    if metadata.get("type") != "asset":
        return "restricted", "asset sidecar type must be asset"
    visibility = str(metadata.get("visibility", "restricted"))
    try:
        expected_path = path.relative_to(config.assets).as_posix()
        if metadata.get("asset_path") != expected_path:
            return "restricted", "asset sidecar path does not match"
        if metadata.get("sha256") != _digest(path):
            return "restricted", "asset sidecar hash does not match"
    except OSError as exc:
        return "restricted", f"asset cannot be verified: {exc}"
    return visibility, "allowed"


def read_visibility(path: Path, config: Config) -> str:
    resolved = path.resolve()
    if _contains_resolved(config.private, resolved):
        return "restricted"
    if resolved.suffix.lower() == ".md":
        try:
            metadata, _ = parse_frontmatter(resolved)
            return str(metadata.get("visibility", config.default_visibility))
        except (OSError, ValueError):
            return (
                config.default_visibility
                if config.schema_version == 2 and is_indexable_text_path(resolved, config)
                else "restricted"
            )
    if _contains_resolved(config.assets, resolved):
        return _asset_visibility(resolved, config)[0]
    return "restricted"


def can_read_path(
    path: Path,
    config: Config,
    purpose: str,
    *,
    metadata: dict | None = None,
) -> PolicyDecision:
    if purpose == "wiki" and (
        _has_reparse_component(path, config.vault)
        or _has_reparse_component(path, config.assets)
    ):
        return PolicyDecision(False, "restricted", "symlinks and reparse points are excluded")
    resolved = path.resolve()
    in_private = _contains_resolved(config.private, resolved)
    in_vault = _contains_resolved(config.vault, resolved)
    in_assets = _contains_resolved(config.assets, resolved)
    if purpose in AI_READ_PURPOSES:
        if in_private:
            return PolicyDecision(False, "restricted", "Private is excluded from AI/RAG/Graph")
        indexable_text = is_indexable_text_path(resolved, config)
        if not (in_vault or in_assets or indexable_text):
            return PolicyDecision(False, "restricted", "path is outside configured index roots")
        if purpose == "wiki" and in_vault:
            relative = resolved.relative_to(config.vault)
            if resolved.suffix.lower() != ".md":
                return PolicyDecision(False, "restricted", "wiki reads only Markdown from Vault")
            if relative.parts and relative.parts[0] in {"90_Templates", "91_Views"}:
                return PolicyDecision(False, "restricted", "templates and generated views are excluded")
        if in_assets:
            visibility, reason = _asset_visibility(resolved, config)
            if reason != "allowed":
                return PolicyDecision(False, visibility, reason)
        else:
            if metadata is not None:
                visibility = str(metadata.get("visibility", "restricted"))
            else:
                try:
                    parsed_metadata, _ = parse_frontmatter(resolved)
                    visibility = str(parsed_metadata.get("visibility", "restricted"))
                except (OSError, ValueError):
                    visibility = (
                        config.default_visibility
                        if config.schema_version == 2 and indexable_text
                        else "restricted"
                    )
        if visibility in CONFIDENTIAL_VISIBILITIES:
            return PolicyDecision(False, visibility, f"{visibility} is excluded")
        if visibility not in SAFE_VISIBILITIES:
            return PolicyDecision(False, visibility, "unknown visibility")
        return PolicyDecision(True, visibility, "allowed")
    visibility = read_visibility(resolved, config)
    if purpose == "backup":
        return PolicyDecision(True, visibility, "encrypted backup scope")
    if visibility == "restricted":
        return PolicyDecision(False, visibility, "restricted")
    return PolicyDecision(True, visibility, "allowed")


def backup_includes_private(config: Config) -> bool:
    for include in config.backup.includes:
        if include.resolve() == config.private.resolve():
            return True
        if include.is_dir():
            try:
                config.private.resolve().relative_to(include.resolve())
                return True
            except ValueError:
                pass
    return False
