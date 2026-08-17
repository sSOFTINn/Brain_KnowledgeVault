from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import shutil
import stat
import uuid


class SourceChangedError(OSError):
    pass


class CopyVerificationError(OSError):
    pass


@dataclass(frozen=True)
class CopyResult:
    destination: Path
    sha256: str
    size: int


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & flag)


def choose_destination(destination: Path, source_hash: str) -> tuple[Path, str]:
    if not destination.exists():
        return destination, "new"
    if file_sha256(destination) == source_hash:
        return destination, "duplicate"
    candidate = destination.with_name(
        f"{destination.stem}__{source_hash[:8]}{destination.suffix}"
    )
    if not candidate.exists():
        return candidate, "collision"
    if file_sha256(candidate) == source_hash:
        return candidate, "duplicate"
    counter = 2
    while True:
        candidate = destination.with_name(
            f"{destination.stem}__{source_hash[:8]}_{counter}{destination.suffix}"
        )
        if not candidate.exists():
            return candidate, "collision"
        if file_sha256(candidate) == source_hash:
            return candidate, "duplicate"
        counter += 1


def verified_copy(
    source: Path,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    preserve_timestamps: bool,
) -> CopyResult:
    if not source.is_file():
        raise FileNotFoundError(f"Source file is missing: {source}")
    if _is_reparse_point(source):
        raise SourceChangedError("source is a symlink or reparse point")
    source_stat = source.stat()
    if source_stat.st_size != expected_size:
        raise SourceChangedError("source size changed")
    if file_sha256(source) != expected_sha256:
        raise SourceChangedError("source hash changed")
    if destination.exists():
        raise FileExistsError(f"Destination appeared before copy: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.partial"
    )
    try:
        copier = shutil.copy2 if preserve_timestamps else shutil.copyfile
        copier(source, temporary)
        if temporary.stat().st_size != expected_size:
            raise CopyVerificationError("copied file size differs from source")
        if file_sha256(temporary) != expected_sha256:
            raise CopyVerificationError("SHA-256 verification failed")
        # KnowledgeVault targets Windows. os.rename does not replace an existing
        # destination there, so a file created after collision planning is not
        # silently overwritten.
        os.rename(temporary, destination)
        if destination.stat().st_size != expected_size:
            raise CopyVerificationError("published file size differs from source")
        if file_sha256(destination) != expected_sha256:
            raise CopyVerificationError("published SHA-256 verification failed")
        return CopyResult(destination, expected_sha256, expected_size)
    finally:
        if temporary.exists():
            temporary.unlink()
