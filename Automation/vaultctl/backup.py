from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import csv
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile

from .config import Config
from .locks import vault_lock
from .storage import get_volume_identity, validate_storage_marker


@dataclass
class BackupResult:
    command: str
    output: str


@dataclass(frozen=True)
class BackupPreflightCheck:
    level: str
    name: str
    message: str


def find_restic() -> Path:
    found = shutil.which("restic")
    if found:
        return Path(found)
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/WinGet/Links/restic.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/WindowsApps/restic.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    packages = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/WinGet/Packages"
    )
    if packages.is_dir():
        matches = sorted(packages.glob("restic.restic_*/restic_*_windows_amd64.exe"))
        if matches:
            return matches[-1]
    raise FileNotFoundError("restic is not installed or not discoverable")


def _env(config: Config) -> dict[str, str]:
    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = str(config.backup.repository)
    env["RESTIC_PASSWORD_FILE"] = str(config.backup.password_file)
    cache_name = "Caches" if config.schema_version == 2 else "cache"
    env["RESTIC_CACHE_DIR"] = str(config.runtime / cache_name / "restic")
    return env


def _run(config: Config, *arguments: str) -> BackupResult:
    command = [str(find_restic()), *arguments]
    result = subprocess.run(
        command,
        env=_env(config),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"restic exit {result.returncode}: {result.stdout.strip()}")
    return BackupResult(" ".join(command), result.stdout.strip())


def _run_bytes(config: Config, *arguments: str) -> bytes:
    command = [str(find_restic()), *arguments]
    result = subprocess.run(
        command,
        env=_env(config),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"restic exit {result.returncode}: "
            f"{result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return result.stdout


def _acl_permission_lines(path: Path, output: str) -> list[str]:
    permission_lines: list[str] = []
    for line in output.splitlines():
        if ":(" not in line:
            continue
        stripped = line.strip()
        if stripped.casefold().startswith(str(path).casefold()):
            stripped = stripped[len(str(path)):].strip()
        permission_lines.append(stripped)
    return permission_lines


def _protect_password_acl(path: Path) -> None:
    _user, user_sid = _current_windows_identity()
    inheritance = subprocess.run(
        ["icacls.exe", str(path), "/inheritance:r"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if inheritance.returncode != 0:
        raise RuntimeError(
            f"Cannot disable restic password ACL inheritance (icacls exit {inheritance.returncode})"
        )
    current = subprocess.run(
        ["icacls.exe", str(path)],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if current.returncode != 0:
        raise RuntimeError(
            f"Cannot inspect restic password ACL (icacls exit {current.returncode})"
        )
    identities = {
        line.split(":(", 1)[0].strip()
        for line in _acl_permission_lines(path, current.stdout)
    }
    # GitHub-hosted and some managed Windows images create explicit SYSTEM and
    # Administrators ACEs. /inheritance:r cannot remove explicit rules, so
    # clear every existing allow/deny identity before granting the user SID.
    for identity in sorted(identities, key=str.casefold):
        for operation in ("/remove:g", "/remove:d"):
            subprocess.run(
                ["icacls.exe", str(path), operation, identity],
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
    grant = subprocess.run(
        ["icacls.exe", str(path), "/grant:r", f"*{user_sid}:(F)"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if grant.returncode != 0:
        raise RuntimeError(
            f"Cannot protect restic password ACL (icacls exit {grant.returncode})"
        )


def ensure_password_file(config: Config) -> Path:
    path = config.backup.password_file
    created = False
    if path.exists():
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"Invalid password file: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
        created = True
    if os.name == "nt":
        try:
            _protect_password_acl(path)
            healthy, message = password_acl_health(config)
            if not healthy:
                raise RuntimeError(message)
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
    return path


def _current_windows_identity() -> tuple[str, str]:
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip()
    rows = list(csv.reader([identity]))
    if not rows or len(rows[0]) < 2:
        raise RuntimeError("cannot determine the current Windows user SID")
    return rows[0][0].strip(), rows[0][1].strip()


def _saved_acl_sddl(path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="knowledgevault-acl-") as directory:
        output = Path(directory) / "acl.txt"
        result = subprocess.run(
            ["icacls.exe", str(path), "/save", str(output), "/c"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0 or not output.is_file():
            detail = " ".join(result.stdout.split())[:300]
            raise RuntimeError(
                f"icacls ACL export failed with exit {result.returncode}: {detail}"
            )
        raw = output.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-16-le"
    text = raw.decode(encoding, errors="strict")
    for line in text.splitlines():
        if line.startswith("D:"):
            return line.strip()
    raise RuntimeError("icacls ACL export contains no DACL descriptor")


def password_acl_health(config: Config) -> tuple[bool, str]:
    path = config.backup.password_file
    if not path.is_file():
        return False, "restic password file is missing"
    if os.name != "nt":
        return True, "Windows ACL check is not applicable"
    try:
        user, user_sid = _current_windows_identity()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    try:
        sddl = _saved_acl_sddl(path)
    except (OSError, RuntimeError, UnicodeError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if not sddl.startswith("D:P"):
        return False, "restic password ACL contains inherited entries"
    aces = re.findall(r"\(([^()]*)\)", sddl)
    if len(aces) != 1:
        return False, "restic password ACL must grant only the current user"
    fields = aces[0].split(";")
    if len(fields) < 6:
        return False, "restic password ACL contains a malformed access rule"
    ace_type, ace_flags, rights, trustee = fields[0], fields[1], fields[2], fields[5]
    if ace_type != "A" or "ID" in ace_flags or rights not in {"FA", "GA"}:
        return False, "restic password ACL must be one explicit full-control allow rule"
    trustee_matches = trustee.casefold() == user_sid.casefold() or (
        trustee.upper() == "LA" and user_sid.rsplit("-", 1)[-1] == "500"
    )
    if not trustee_matches:
        return False, (
            "restic password ACL is not assigned to the current user SID "
            f"(expected {user_sid}, found {trustee})"
        )
    return True, f"protected ACL for {user}"


def backup_init(config: Config) -> BackupResult:
    if config.schema_version == 2:
        failures = [item for item in backup_preflight(config) if item.level == "FAIL"]
        if failures:
            raise RuntimeError(
                "Backup preflight failed: "
                + "; ".join(f"{item.name}: {item.message}" for item in failures)
            )
    ensure_password_file(config)
    config.backup.repository.parent.mkdir(parents=True, exist_ok=True)
    if (config.backup.repository / "config").is_file():
        return BackupResult("restic init", "Repository already initialized.")
    config.backup.repository.mkdir(parents=True, exist_ok=True)
    return _run(config, "init")


def backup_run(config: Config) -> list[BackupResult]:
    if config.schema_version == 2:
        failures = [item for item in backup_preflight(config) if item.level == "FAIL"]
        if failures:
            raise RuntimeError(
                "Backup preflight failed: "
                + "; ".join(f"{item.name}: {item.message}" for item in failures)
            )
    ensure_password_file(config)
    with vault_lock(config, "backup"):
        missing = [path for path in config.backup.includes if not path.exists()]
        if missing and config.backup.require_all_includes:
            raise FileNotFoundError(
                "Configured backup includes are missing: "
                + ", ".join(str(path) for path in missing)
            )
        includes = [str(path) for path in config.backup.includes if path.exists()]
        if not includes:
            raise FileNotFoundError("No configured backup include paths exist")
        arguments = ["backup", *includes, "--tag", "knowledgevault-manual"]
        for pattern in config.backup.excludes:
            arguments.extend(["--exclude", pattern])
        backup_result = _run(config, *arguments)
        forget_result = _run(
            config,
            "forget",
            "--keep-daily",
            str(config.backup.keep_daily),
            "--keep-weekly",
            str(config.backup.keep_weekly),
            "--keep-monthly",
            str(config.backup.keep_monthly),
            "--prune",
        )
        return [backup_result, forget_result]


def backup_check(config: Config) -> BackupResult:
    return _run(
        config,
        "check",
        f"--read-data-subset={config.backup.readback_percent}%",
    )


def backup_preflight(config: Config) -> list[BackupPreflightCheck]:
    checks: list[BackupPreflightCheck] = []

    def add(level: str, name: str, message: str) -> None:
        checks.append(BackupPreflightCheck(level, name, message))

    try:
        validate_storage_marker(config)
        add("PASS", "source-marker", "schema marker and source volume identity match")
    except (OSError, ValueError) as exc:
        add("FAIL", "source-marker", str(exc))

    missing = [path for path in config.backup.includes if not path.exists()]
    if missing and config.backup.require_all_includes:
        add("FAIL", "required-includes", f"{len(missing)} configured paths are missing")
    else:
        add("PASS", "required-includes", "all required include paths exist")

    source_volume = get_volume_identity(config.root)
    backup_volume = get_volume_identity(config.backup.repository)
    if config.machine.backup_volume_serial and (
        backup_volume.serial.casefold() != config.machine.backup_volume_serial.casefold()
    ):
        add("FAIL", "backup-volume-serial", "backup volume serial does not match the machine profile")
    else:
        add("PASS", "backup-volume-serial", backup_volume.serial or "not configured")
    if config.machine.backup_volume_label and (
        backup_volume.label.casefold() != config.machine.backup_volume_label.casefold()
    ):
        add("FAIL", "backup-volume-label", "backup volume label does not match the machine profile")
    else:
        add("PASS", "backup-volume-label", backup_volume.label or "not configured")
    healthy = backup_volume.health_status.casefold() == "healthy"
    operational = backup_volume.operational_status.casefold() in {"ok", "healthy"}
    add(
        "PASS" if healthy and operational else "FAIL",
        "backup-volume-health",
        f"{backup_volume.health_status} / {backup_volume.operational_status}",
    )
    if config.machine.require_distinct_physical_disks:
        if not source_volume.disk_id or not backup_volume.disk_id:
            add("FAIL", "physical-separation", "physical disk identity could not be established")
        elif source_volume.disk_id.casefold() == backup_volume.disk_id.casefold():
            add("FAIL", "physical-separation", "source and backup are on the same physical disk")
        else:
            add("PASS", "physical-separation", "source and backup use different physical disks")
    try:
        existing = config.backup.repository
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        free = shutil.disk_usage(existing).free
        required = config.backup.minimum_free_gib * 1024**3
        add(
            "PASS" if free >= required else "FAIL",
            "backup-free-space",
            f"{free / 1024**3:.1f} GiB free; minimum {config.backup.minimum_free_gib} GiB",
        )
    except OSError as exc:
        add("FAIL", "backup-free-space", str(exc))
    return checks


def backup_snapshots(config: Config) -> list[dict]:
    result = _run(config, "snapshots", "--json")
    return json.loads(result.output or "[]")


def backup_freshness(config: Config, *, now: datetime | None = None) -> tuple[bool, str]:
    if not (config.backup.repository / "config").is_file():
        return False, "restic repository is not initialized"
    if not config.backup.password_file.is_file():
        return False, "restic password file is missing"
    snapshots = backup_snapshots(config)
    if not snapshots:
        return False, "restic repository has no snapshots"
    latest_raw = max(str(item.get("time", "")) for item in snapshots)
    try:
        latest = datetime.fromisoformat(latest_raw.replace("Z", "+00:00"))
    except ValueError:
        return False, "latest restic snapshot timestamp is invalid"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = current.astimezone(timezone.utc) - latest.astimezone(timezone.utc)
    age_days = max(0.0, age.total_seconds() / 86400)
    fresh = age_days <= config.backup.max_snapshot_age_days
    return (
        fresh,
        f"latest snapshot age {age_days:.1f} days; "
        f"maximum {config.backup.max_snapshot_age_days} days",
    )


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def backup_restore_drill(config: Config) -> dict:
    critical = list(config.backup.critical_paths)
    def included(path: Path) -> bool:
        resolved = path.resolve()
        for include in config.backup.includes:
            candidate = include.resolve()
            if candidate.is_file() and resolved == candidate:
                return True
            if candidate.is_dir():
                try:
                    resolved.relative_to(candidate)
                    return True
                except ValueError:
                    pass
        return False

    missing = [path for path in critical if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Configured critical files are missing: " + ", ".join(str(path) for path in missing)
        )
    excluded = [path for path in critical if not included(path)]
    if excluded:
        raise ValueError(
            "Configured critical files are outside backup includes: "
            + ", ".join(str(path) for path in excluded)
        )

    def label(path: Path) -> str:
        resolved = path.resolve()
        try:
            return "root:" + resolved.relative_to(config.root.resolve()).as_posix()
        except ValueError:
            return "absolute:" + resolved.as_posix()

    expected = {label(path): (path, _hash(path)) for path in critical}
    def snapshot_path(path: Path) -> str:
        resolved = path.resolve()
        drive = resolved.drive.rstrip(":").upper()
        remainder = resolved.as_posix().split(":", 1)[-1].lstrip("/")
        return f"/{drive}/{remainder}"

    with tempfile.TemporaryDirectory(prefix="knowledgevault-restore-") as temp:
        target = Path(temp)
        restored: dict[str, str] = {}
        for index, (name, (source, expected_hash)) in enumerate(expected.items(), 1):
            restored_file = target / f"{index:03d}-{source.name}"
            restored_file.write_bytes(
                _run_bytes(config, "dump", "latest", snapshot_path(source))
            )
            if _hash(restored_file) != expected_hash:
                raise RuntimeError(f"Restore drill failed for {name}")
            restored[name] = str(restored_file)
        return {
            "verified": sorted(restored),
            "count": len(restored),
            "target_removed_after_check": True,
        }
