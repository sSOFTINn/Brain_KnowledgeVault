from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from .config import Config


def tracked_files(config: Config) -> tuple[Path | None, list[Path], str]:
    if not config.git_enabled:
        return None, [], "Git policy is disabled"
    git = shutil.which("git")
    if not git:
        return None, [], "Git executable is unavailable"
    probe = subprocess.run(
        [git, "-C", str(config.vault), "rev-parse", "--show-toplevel"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        return None, [], "Vault is not inside a Git worktree"
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
    limit = config.max_tracked_file_mb * 1024 * 1024
    oversized: list[Path] = []
    for path in paths:
        try:
            path.relative_to(config.vault.resolve())
        except ValueError:
            continue
        if path.is_file() and path.stat().st_size > limit:
            oversized.append(path)
    return sorted(oversized)
