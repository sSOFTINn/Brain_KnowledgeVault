from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import yaml

from .backup import backup_freshness, find_restic, password_acl_health
from .config import Config
from .gitpolicy import oversized_tracked_files, tracked_files
from .policy import backup_includes_private
from .scaffold import DIRECTORIES


@dataclass
class Check:
    level: str
    name: str
    message: str


def run_doctor(config: Config) -> list[Check]:
    checks: list[Check] = []

    def add(level: str, name: str, message: str) -> None:
        checks.append(Check(level, name, message))

    add("PASS" if sys.version_info >= (3, 11) else "FAIL", "python", sys.version.split()[0])
    add("PASS", "pyyaml", yaml.__version__)
    add("PASS" if shutil.which("git") else "WARN", "git", shutil.which("git") or "not found")
    try:
        restic = str(find_restic())
        add("PASS", "backup-tool", restic)
    except FileNotFoundError:
        add("WARN", "backup-tool", "restic is not installed; backup is inactive")
    add("PASS", "sqlite", sqlite3.sqlite_version)

    if config.root.exists():
        usage = shutil.disk_usage(config.root)
        add("PASS", "root", str(config.root))
        add("PASS" if usage.free >= 1024**3 else "WARN", "free-space", f"{usage.free / 1024**3:.1f} GiB")
    else:
        parent = config.root.parent
        if parent.exists():
            usage = shutil.disk_usage(parent)
            add("WARN", "root", f"not initialized: {config.root}")
            add("PASS" if usage.free >= 1024**3 else "WARN", "free-space", f"{usage.free / 1024**3:.1f} GiB")
        else:
            add("FAIL", "root", f"parent does not exist: {parent}")

    required_directories = (
        config.storage.directories if config.schema_version == 2 else DIRECTORIES
    )
    missing = [
        relative for relative in required_directories if not (config.root / relative).is_dir()
    ]
    add("PASS" if not missing else "WARN", "structure", "complete" if not missing else f"{len(missing)} directories missing")
    add("PASS", "safe-copy", "copy + SHA-256; overwrite disabled")
    add("PASS" if config.preserve_source else "FAIL", "source-retention", "source is preserved")
    add("PASS" if not config.follow_symlinks else "FAIL", "symlinks", "not followed")
    add("PASS", "scan-workers", f"effective max_workers={config.max_workers}")
    if config.git_enabled:
        git_root, _tracked, git_message = tracked_files(config)
        oversized = oversized_tracked_files(config) if git_root else []
        if oversized:
            add("FAIL", "git-policy", f"{len(oversized)} tracked files exceed {config.max_tracked_file_mb} MiB")
        else:
            add("PASS" if git_root else "WARN", "git-policy", git_message)
    else:
        add("PASS", "git-policy", "disabled by configuration")
    add("PASS" if not config.allow_ai_confidential else "WARN", "ai-privacy", "confidential access disabled")
    add("PASS", "visibility-policy", "central policy excludes Private/restricted/confidential from AI/RAG/Graph")
    add(
        "PASS" if backup_includes_private(config) else "WARN",
        "backup-private-scope",
        "Private is included only in encrypted backup scope" if backup_includes_private(config) else "Private is not included in backup scope",
    )
    if not config.backup.password_file.is_file() and not (
        config.backup.repository / "config"
    ).is_file():
        add(
            "WARN",
            "backup-password-acl",
            "backup is not initialized; run `vaultctl backup init`",
        )
    else:
        try:
            acl_ok, acl_message = password_acl_health(config)
            add("PASS" if acl_ok else "FAIL", "backup-password-acl", acl_message)
        except (OSError, subprocess.SubprocessError) as exc:
            add("FAIL", "backup-password-acl", f"ACL check failed: {exc}")
    try:
        fresh, freshness_message = backup_freshness(config)
        add("PASS" if fresh else "WARN", "backup-freshness", freshness_message)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        add("WARN", "backup-freshness", f"freshness check unavailable: {exc}")
    add("PASS" if not config.llm.enabled else "WARN", "llm-default", "LLM disabled by default" if not config.llm.enabled else "LLM enabled; verify Ollama locality")
    add("PASS", "llm-context", f"effective context limit={config.llm.context_limit_tokens} tokens")
    add(
        "PASS",
        "rag-effective",
        "disabled" if not config.rag.enabled else (
            f"enabled; embeddings={config.rag.embeddings.provider}"
            if config.rag.embeddings.enabled
            else "enabled; FTS5 only"
        ),
    )
    return checks


def checks_as_dict(checks: list[Check]) -> list[dict]:
    return [asdict(check) for check in checks]


def has_failures(checks: list[Check]) -> bool:
    return any(check.level == "FAIL" for check in checks)
