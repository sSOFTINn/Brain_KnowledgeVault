from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import ctypes
import json
import os
import stat
import subprocess

from .config import Config, render_runtime_config


@dataclass(frozen=True)
class VolumeIdentity:
    root: str
    label: str
    serial: str
    filesystem: str
    disk_id: str
    health_status: str
    operational_status: str


@dataclass(frozen=True)
class BootstrapResult:
    root: str
    dry_run: bool
    adopted: bool
    created: tuple[str, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class StorageAudit:
    root: str
    schema_version: int
    marker_valid: bool
    missing_directories: tuple[str, ...]
    unexpected_root_git: bool
    reparse_points: tuple[dict[str, str], ...]
    volume: VolumeIdentity
    errors: tuple[str, ...]


def _existing_anchor(path: Path) -> Path:
    candidate = path.expanduser().resolve(strict=False)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _windows_volume_information(path: Path) -> tuple[str, str, str]:
    kernel32 = ctypes.windll.kernel32
    volume_path = ctypes.create_unicode_buffer(261)
    if not kernel32.GetVolumePathNameW(str(path), volume_path, len(volume_path)):
        raise OSError(ctypes.get_last_error(), "GetVolumePathNameW failed")
    label = ctypes.create_unicode_buffer(261)
    filesystem = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_uint32()
    maximum_component = ctypes.c_uint32()
    flags = ctypes.c_uint32()
    if not kernel32.GetVolumeInformationW(
        volume_path.value,
        label,
        len(label),
        ctypes.byref(serial),
        ctypes.byref(maximum_component),
        ctypes.byref(flags),
        filesystem,
        len(filesystem),
    ):
        raise OSError(ctypes.get_last_error(), "GetVolumeInformationW failed")
    return label.value, f"{serial.value:08X}", filesystem.value


def _windows_storage_metadata(drive_letter: str) -> dict[str, str]:
    script = r"""
$ErrorActionPreference = 'Stop'
$volume = Get-Volume -DriveLetter $env:KV_DRIVE
$partition = Get-Partition -DriveLetter $env:KV_DRIVE
$disk = $partition | Get-Disk
[ordered]@{
  disk_id = if ($disk.UniqueId) { [string]$disk.UniqueId } elseif ($disk.SerialNumber) { [string]$disk.SerialNumber } else { [string]$disk.Number }
  health_status = [string]$volume.HealthStatus
  operational_status = [string]($volume.OperationalStatus -join ',')
} | ConvertTo-Json -Compress
"""
    environment = os.environ.copy()
    environment["KV_DRIVE"] = drive_letter
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=environment,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        return {}
    for line in reversed(result.stdout.splitlines()):
        try:
            payload = json.loads(line.strip().lstrip("\ufeff"))
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(payload, dict):
            return {str(key): str(value or "") for key, value in payload.items()}
    return {}


def get_volume_identity(path: str | Path) -> VolumeIdentity:
    existing = _existing_anchor(Path(path))
    anchor = Path(existing.anchor or existing)
    if os.name != "nt":
        device = str(existing.stat().st_dev)
        return VolumeIdentity(
            root=str(anchor),
            label="",
            serial=device,
            filesystem="",
            disk_id=device,
            health_status="Unknown",
            operational_status="Unknown",
        )
    label, serial, filesystem = _windows_volume_information(existing)
    drive_letter = anchor.drive.rstrip(":")
    storage = _windows_storage_metadata(drive_letter)
    return VolumeIdentity(
        root=str(anchor),
        label=label,
        serial=serial,
        filesystem=filesystem,
        disk_id=storage.get("disk_id", ""),
        health_status=storage.get("health_status", "Unknown"),
        operational_status=storage.get("operational_status", "Unknown"),
    )


def marker_path(config: Config) -> Path:
    return config.root / config.storage.marker_file


def _marker_payload(config: Config, identity: VolumeIdentity) -> dict:
    return {
        "product": "Brain_KnowledgeVault",
        "schema_version": 2,
        "machine_profile": config.machine.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "volume": asdict(identity),
    }


def validate_storage_marker(config: Config) -> dict:
    if config.schema_version != 2:
        return {"schema_version": config.schema_version, "legacy": True}
    path = marker_path(config)
    if not path.is_file():
        raise FileNotFoundError(f"Storage marker is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Storage marker is invalid: {exc}") from exc
    if payload.get("product") != "Brain_KnowledgeVault" or payload.get("schema_version") != 2:
        raise ValueError("Storage marker does not identify schema v2")
    expected = str(payload.get("volume", {}).get("serial", "")).casefold()
    current = get_volume_identity(config.root)
    if expected and current.serial.casefold() != expected:
        raise ValueError(
            f"Storage volume identity mismatch: expected {expected}, got {current.serial}"
        )
    configured = config.machine.root_volume_serial.strip().casefold()
    if configured and current.serial.casefold() != configured:
        raise ValueError(
            "Storage volume does not match machine.root_volume_serial"
        )
    configured_label = config.machine.root_volume_label.strip().casefold()
    if configured_label and current.label.casefold() != configured_label:
        raise ValueError("Storage volume does not match machine.root_volume_label")
    return payload


def write_audit_event(config: Config, event: str, payload: dict) -> Path:
    target = config.audit / "storage-events.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "payload": payload,
    }
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return target


def _bootstrap_managed_files(config: Config, identity: VolumeIdentity) -> dict[str, str]:
    layout = "\n".join(f"- `{item}`" for item in config.storage.directories)
    return {
        config.storage.marker_file: json.dumps(
            _marker_payload(config, identity), ensure_ascii=False, indent=2
        ) + "\n",
        "vault.toml.local": render_runtime_config(config),
        "00_System/Policies/STORAGE_LAYOUT.md": (
            "# Storage layout v2\n\n"
            "This file is generated by `vaultctl bootstrap`. The root contains no global `.git`.\n\n"
            + layout
            + "\n"
        ),
        "00_System/Manifests/RESTORE_MAP.csv": (
            "OriginalRelativePath,NewRelativePath,Classification,Approved,Notes\n"
        ),
        "00_System/Recovery/README.md": (
            "# Recovery\n\nUse the tagged release and PRE_WIPE manifests. "
            "Never overwrite or delete the source during import.\n"
        ),
    }


def bootstrap_storage(
    config: Config,
    *,
    dry_run: bool = False,
    adopt: bool = False,
) -> BootstrapResult:
    if config.schema_version != 2:
        raise ValueError("bootstrap requires configuration schema_version = 2")
    root = config.root
    if not root.parent.exists():
        raise FileNotFoundError(f"Storage root parent does not exist: {root.parent}")
    existing = list(root.iterdir()) if root.exists() else []
    marker_exists = marker_path(config).is_file()
    if existing and not marker_exists and not (adopt and config.storage.allow_adopt):
        raise ValueError(
            "Target root is not empty and has no schema v2 marker; explicit approved adopt is required"
        )
    identity = get_volume_identity(root)
    if config.machine.root_volume_serial and (
        identity.serial.casefold() != config.machine.root_volume_serial.casefold()
    ):
        raise ValueError("Target volume serial does not match the machine profile")
    if config.machine.root_volume_label and (
        identity.label.casefold() != config.machine.root_volume_label.casefold()
    ):
        raise ValueError("Target volume label does not match the machine profile")
    if marker_exists:
        validate_storage_marker(config)

    created: list[str] = []
    skipped: list[str] = []
    for relative in config.storage.directories:
        target = root / relative
        if target.is_dir():
            skipped.append(relative + "/")
        elif target.exists():
            raise FileExistsError(f"Required directory path is occupied by a file: {target}")
        else:
            created.append(relative + "/")
            if not dry_run:
                target.mkdir(parents=True, exist_ok=False)
    for relative, content in _bootstrap_managed_files(config, identity).items():
        target = root / relative
        if target.exists():
            skipped.append(relative)
            continue
        created.append(relative)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
    if not dry_run:
        write_audit_event(
            config,
            "bootstrap",
            {"adopted": bool(existing), "created": created, "skipped": skipped},
        )
    return BootstrapResult(
        root=str(root),
        dry_run=dry_run,
        adopted=bool(existing and not marker_exists),
        created=tuple(created),
        skipped=tuple(skipped),
    )


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def audit_storage(config: Config) -> StorageAudit:
    errors: list[str] = []
    missing = tuple(
        relative
        for relative in config.storage.directories
        if not (config.root / relative).is_dir()
    )
    try:
        validate_storage_marker(config)
        marker_valid = True
    except (OSError, ValueError) as exc:
        marker_valid = False
        errors.append(str(exc))
    reparses: list[dict[str, str]] = []
    if config.root.exists():
        stack = [config.root]
        while stack:
            current = stack.pop()
            try:
                children = list(current.iterdir())
            except OSError as exc:
                errors.append(f"Cannot enumerate {current}: {exc}")
                continue
            for child in children:
                if _is_reparse(child):
                    try:
                        target = str(child.resolve(strict=False))
                    except OSError:
                        target = "unresolved"
                    reparses.append(
                        {
                            "path": child.relative_to(config.root).as_posix(),
                            "target": target,
                            "type": "reparse",
                        }
                    )
                    continue
                if child.is_dir():
                    stack.append(child)
    return StorageAudit(
        root=str(config.root),
        schema_version=config.schema_version,
        marker_valid=marker_valid,
        missing_directories=missing,
        unexpected_root_git=(config.root / ".git").exists(),
        reparse_points=tuple(reparses),
        volume=get_volume_identity(config.root),
        errors=tuple(errors),
    )
