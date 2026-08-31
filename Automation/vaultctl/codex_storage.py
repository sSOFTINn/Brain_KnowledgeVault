from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Mapping
import json
import os

from .config import Config
from .storage import validate_storage_marker, write_audit_event


REPARSE_POINT_ATTRIBUTE = 0x400


@dataclass(frozen=True)
class CodexStorageItem:
    category: str
    path: str
    disposition: str
    protected: bool
    exists: bool
    kind: str
    size_bytes: int | None
    last_write_utc: str | None
    note: str


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & REPARSE_POINT_ATTRIBUTE)
    except OSError:
        return False


def _directory_size(path: Path) -> int | None:
    total = 0
    stack = [path]
    try:
        while stack:
            current = stack.pop()
            if _is_reparse_point(current):
                continue
            for child in current.iterdir():
                if _is_reparse_point(child):
                    continue
                if child.is_dir():
                    stack.append(child)
                elif child.is_file():
                    total += child.stat().st_size
    except OSError:
        return None
    return total


def _last_write_utc(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _item(
    category: str,
    path: Path,
    disposition: str,
    *,
    protected: bool,
    note: str,
    measure_directory: bool = False,
) -> CodexStorageItem:
    exists = path.exists()
    kind = "missing"
    size: int | None = None
    if exists:
        if _is_reparse_point(path):
            kind = "reparse-point"
        elif path.is_dir():
            kind = "directory"
            size = _directory_size(path) if measure_directory else None
        elif path.is_file():
            kind = "file"
            try:
                size = path.stat().st_size
            except OSError:
                size = None
        else:
            kind = "other"
    return CodexStorageItem(
        category=category,
        path=str(path),
        disposition=disposition,
        protected=protected,
        exists=exists,
        kind=kind,
        size_bytes=size,
        last_write_utc=_last_write_utc(path) if exists else None,
        note=note,
    )


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _profile_root(home: str | Path | None, environment: Mapping[str, str]) -> Path:
    value = home or environment.get("USERPROFILE") or Path.home()
    return _resolved(value)


def _temp_root(temp: str | Path | None, environment: Mapping[str, str]) -> Path:
    value = temp or environment.get("TEMP") or environment.get("TMP")
    if value is None:
        value = _profile_root(None, environment) / "AppData" / "Local" / "Temp"
    return _resolved(value)


def _cleanup_candidates(profile: Path, temp_root: Path) -> list[CodexStorageItem]:
    candidates: list[CodexStorageItem] = []
    documents = profile / "Documents"
    if documents.is_dir():
        for path in sorted(documents.glob("codex_search*.txt")):
            candidates.append(
                _item(
                    "generated-report",
                    path,
                    "cleanup-candidate",
                    protected=False,
                    note="Generated directory-listing report; review and remove separately.",
                )
            )
    if temp_root.is_dir():
        for path in sorted(temp_root.glob("codex-clipboard-*.png")):
            candidates.append(
                _item(
                    "clipboard-image",
                    path,
                    "cleanup-candidate",
                    protected=False,
                    note="Temporary clipboard image created for a Codex attachment.",
                )
            )
    docs_cache = temp_root / "openai-docs-cache"
    if docs_cache.exists():
        candidates.append(
            _item(
                "documentation-cache",
                docs_cache,
                "cleanup-candidate",
                protected=False,
                note="Regenerable official-documentation cache; clean only when Codex is idle.",
                measure_directory=True,
            )
        )
    return candidates


def audit_codex_storage(
    config: Config,
    *,
    home: str | Path | None = None,
    temp: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict]:
    """Create a read-only inventory of Codex storage boundaries.

    The command writes audit evidence under KnowledgeVault but never changes,
    copies, redirects, or deletes any inspected Windows or Codex path.
    """

    validate_storage_marker(config)
    env = dict(os.environ if environment is None else environment)
    profile = _profile_root(home, env)
    temp_root = _temp_root(temp, env)
    expected_home = config.codex_storage.home.resolve()
    configured_home = _resolved(env.get("CODEX_HOME", profile / ".codex"))

    canonical = [
        _item(
            "codex-home",
            expected_home,
            "canonical-private-state",
            protected=True,
            note="Canonical CODEX_HOME; contains private config, auth, sessions, skills, logs, and managed worktrees.",
        ),
        _item(
            "projects",
            config.codex_storage.projects,
            "canonical-projects",
            protected=True,
            note="Long-lived repositories belong under the KnowledgeVault projects tree.",
        ),
        _item(
            "migration-staging",
            config.codex_storage.staging,
            "rebuildable-runtime",
            protected=False,
            note="Copy-only migration staging; not a canonical source of truth.",
        ),
        _item(
            "migration-audit",
            config.codex_storage.audit,
            "permanent-evidence",
            protected=True,
            note="Permanent manifests, approvals, verification, and cleanup evidence.",
        ),
    ]

    protected_paths = [
        _item(
            "desktop-runtime",
            profile / "AppData" / "Local" / "OpenAI" / "Codex",
            "leave-in-place",
            protected=True,
            note="Installed binaries and runtimes; do not migrate or delete manually.",
            measure_directory=True,
        ),
        _item(
            "desktop-logs",
            profile / "AppData" / "Local" / "Codex",
            "leave-in-place",
            protected=True,
            note="Desktop operational logs; use application-supported retention only.",
            measure_directory=True,
        ),
        _item(
            "desktop-profile",
            profile / "AppData" / "Roaming" / "Codex",
            "leave-in-place",
            protected=True,
            note="Desktop profile and Chromium state; do not relocate wholesale.",
            measure_directory=True,
        ),
        _item(
            "runtime-cache",
            profile / ".cache" / "codex-runtimes",
            "leave-in-place",
            protected=True,
            note="Application runtime cache; may be linked from active tools and must not be traversed for migration.",
            measure_directory=True,
        ),
    ]

    legacy = [
        _item(
            "legacy-documents-workspace",
            profile / "Documents" / "Codex",
            "migrate-copy-verify-before-cleanup",
            protected=False,
            note="Do not create new projects here; preserve, hash-verify, restore-test, then clean only with separate approval.",
            measure_directory=True,
        )
    ]
    cleanup = _cleanup_candidates(profile, temp_root)
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "policy_version": 1,
        "generated_at": generated_at.isoformat(),
        "read_only": True,
        "profile": str(profile),
        "temp": str(temp_root),
        "expected_codex_home": str(expected_home),
        "effective_codex_home": str(configured_home),
        "codex_home_matches": _same_path(expected_home, configured_home),
        "canonical_paths": [asdict(item) for item in canonical],
        "protected_windows_paths": [asdict(item) for item in protected_paths],
        "legacy_paths": [asdict(item) for item in legacy],
        "cleanup_candidates": [asdict(item) for item in cleanup],
        "cleanup_candidate_count": len(cleanup),
        "cleanup_candidate_bytes": sum(item.size_bytes or 0 for item in cleanup),
        "rules": {
            "general_temp_redirect_forbidden": True,
            "appdata_relocation_forbidden": True,
            "source_preserved_by_default": True,
            "cleanup_requires_separate_confirmation": True,
            "reparse_points_not_followed": True,
        },
    }
    output_dir = config.codex_storage.audit
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"codex-storage-audit-{stamp}.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_audit_event(
        config,
        "codex-storage-audit",
        {
            "output": str(output),
            "codex_home_matches": payload["codex_home_matches"],
            "cleanup_candidate_count": len(cleanup),
        },
    )
    return output, payload


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _directory_manifest(path: Path) -> tuple[list[dict], bool]:
    files: list[Path] = []
    stack = [path]
    while stack:
        current = stack.pop()
        if _is_reparse_point(current):
            return [], True
        try:
            children = sorted(current.iterdir(), key=lambda item: str(item).casefold())
        except OSError:
            return [], True
        for child in children:
            if _is_reparse_point(child):
                return [], True
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                files.append(child)
    manifest = []
    for file_path in sorted(files, key=lambda item: str(item).casefold()):
        stat_result = file_path.stat()
        manifest.append(
            {
                "relative_path": file_path.relative_to(path).as_posix(),
                "size_bytes": stat_result.st_size,
                "last_write_utc": datetime.fromtimestamp(
                    stat_result.st_mtime, timezone.utc
                ).isoformat(),
                "sha256": _sha256(file_path),
            }
        )
    return manifest, False


def create_codex_cleanup_plan(
    config: Config,
    *,
    home: str | Path | None = None,
    temp: str | Path | None = None,
    retention_days: int | None = None,
    environment: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict]:
    """Create a hash-backed, non-executing cleanup plan for known leftovers."""

    validate_storage_marker(config)
    days = (
        config.codex_storage.cleanup_retention_days
        if retention_days is None
        else retention_days
    )
    if days < 1:
        raise ValueError("retention_days must be positive")
    env = dict(os.environ if environment is None else environment)
    profile = _profile_root(home, env)
    temp_root = _temp_root(temp, env)
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = generated_at.timestamp() - (days * 86400)
    rows: list[dict] = []

    for item in _cleanup_candidates(profile, temp_root):
        candidate = Path(item.path)
        if _is_reparse_point(candidate):
            rows.append(
                {
                    **asdict(item),
                    "eligible": False,
                    "blocked_reason": "reparse-point",
                    "sha256": None,
                    "file_manifest": [],
                }
            )
            continue
        directory_manifest: list[dict] = []
        blocked_reason: str | None = None
        try:
            candidate_mtime = candidate.stat().st_mtime
            if candidate.is_dir():
                directory_manifest, contains_reparse = _directory_manifest(candidate)
                if contains_reparse:
                    blocked_reason = "contains-reparse-point-or-unreadable-entry"
                newest_mtime = max(
                    [candidate_mtime]
                    + [
                        datetime.fromisoformat(row["last_write_utc"]).timestamp()
                        for row in directory_manifest
                    ]
                )
            else:
                newest_mtime = candidate_mtime
            eligible = blocked_reason is None and newest_mtime <= cutoff
        except OSError:
            eligible = False
            blocked_reason = "unreadable"
        if blocked_reason is None and not eligible:
            blocked_reason = "retention-not-met"
        rows.append(
            {
                **asdict(item),
                "eligible": eligible,
                "blocked_reason": None if eligible else blocked_reason,
                "sha256": _sha256(candidate) if eligible and candidate.is_file() else None,
                "file_manifest": directory_manifest if eligible else [],
            }
        )

    payload = {
        "policy_version": 1,
        "generated_at": generated_at.isoformat(),
        "execute_supported": False,
        "requires_explicit_target_confirmation": True,
        "retention_days": days,
        "profile": str(profile),
        "temp": str(temp_root),
        "rows": rows,
    }
    output_dir = config.codex_storage.audit
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"codex-storage-cleanup-plan-{stamp}.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_audit_event(
        config,
        "codex-storage-cleanup-plan",
        {
            "output": str(output),
            "eligible": sum(bool(row["eligible"]) for row in rows),
            "retention_days": days,
        },
    )
    return output, payload
