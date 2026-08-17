from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os

from .config import Config


SENSITIVE_KEY_PARTS = (
    "answer",
    "authorization",
    "content",
    "credential",
    "password",
    "prompt",
    "query",
    "secret",
    "snippet",
    "token",
)


def redact(value: Any, key: str = "") -> Any:
    lowered = key.casefold()
    if any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return type(value).__name__


def _rotate(path: Path, max_bytes: int, backup_count: int, incoming: int) -> None:
    if not path.is_file() or path.stat().st_size + incoming <= max_bytes:
        return
    oldest = path.with_name(f"{path.name}.{backup_count}")
    if oldest.exists():
        oldest.unlink()
    for index in range(backup_count - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        if source.exists():
            os.replace(source, path.with_name(f"{path.name}.{index + 1}"))
    os.replace(path, path.with_name(f"{path.name}.1"))


def write_event(config: Config, event: dict[str, Any]) -> Path | None:
    if not config.logging.enabled:
        return None
    log_dir = config.logs
    resolved_parent = log_dir.resolve()
    try:
        resolved_parent.relative_to(config.root.resolve())
    except ValueError as exc:
        raise ValueError("Log directory escapes KnowledgeVault root") from exc
    if log_dir.is_symlink():
        raise ValueError("Log directory cannot be a symlink")
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "vaultctl.jsonl"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        **redact(event),
    }
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    encoded_size = len(line.encode("utf-8"))
    _rotate(path, config.logging.max_bytes, config.logging.backup_count, encoded_size)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
    return path


def record_command(config: Config, command: str, exit_code: int, duration_ms: int) -> None:
    try:
        write_event(
            config,
            {
                "event": "command_complete",
                "command": command,
                "status": "ok" if exit_code == 0 else "failed",
                "exit_code": exit_code,
                "duration_ms": duration_ms,
            },
        )
    except (OSError, ValueError):
        # Observability must never make an otherwise safe command fail.
        return
