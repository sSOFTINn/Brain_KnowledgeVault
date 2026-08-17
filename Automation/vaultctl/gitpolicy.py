from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from .config import Config


def _git_scope(config: Config) -> Path:
    if config.schema_version == 2:
        repository = config.control_plane / "Brain_KnowledgeVault"
        return repository if repository.is_dir() else config.control_plane
    return config.vault


def tracked_files(config: Config) -> tuple[Path | None, list[Path], str]:
    if not config.git_enabled:
        return None, [], "Git policy is disabled"
    git = shutil.which("git")
    if not git:
        return None, [], "Git executable is unavailable"
    scope = _git_scope(config)
    probe = subprocess.run(
        [git, "-C", str(scope), "rev-parse", "--show-toplevel"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        label = "Control plane" if config.schema_version == 2 else "Vault"
        return None, [], f"{label} is not inside a Git worktree"
    root = Path(probe.stdout.strip()).resolve()
    listing = subprocess.run(
        [git, "-C", str(root), "ls-files", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if listing.returncode != 0:
        return root, [], "Cannot list Git-tracked files"
    paths = [
        (root / item.decode("utf-8", errors="surrogateescape")).resolve()
        for item in listing.stdout.split(b"\0")
        if item
    ]
    return root, paths, f"{len(paths)} tracked files; limit {config.max_tracked_file_mb} MiB"


def oversized_tracked_files(config: Config) -> list[Path]:
    _root, paths, _message = tracked_files(config)
    scope = _git_scope(config).resolve()
    limit = config.max_tracked_file_mb * 1024 * 1024
    oversized: list[Path] = []
    for path in paths:
        try:
            path.relative_to(scope)
        except ValueError:
            continue
        if path.is_file() and path.stat().st_size > limit:
            oversized.append(path)
    return sorted(oversized)
