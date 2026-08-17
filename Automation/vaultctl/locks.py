from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import os
import time
import uuid

from .config import Config


class LockError(RuntimeError):
    pass


@contextmanager
def vault_lock(config: Config, name: str, *, stale_seconds: int = 6 * 60 * 60):
    lock_dir = config.runtime / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / f"{name}.lock"
    token = uuid.uuid4().hex
    payload = {
        "pid": os.getpid(),
        "created": time.time(),
        "token": token,
    }
    serialized = json.dumps(payload, sort_keys=True) + "\n"
    acquired = False
    try:
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(serialized)
                acquired = True
                break
            except FileExistsError:
                try:
                    before = path.stat()
                    existing = path.read_text(encoding="utf-8")
                    age = time.time() - before.st_mtime
                except OSError:
                    continue
                if age > stale_seconds:
                    try:
                        after = path.stat()
                        if (
                            before.st_mtime_ns == after.st_mtime_ns
                            and before.st_size == after.st_size
                            and path.read_text(encoding="utf-8") == existing
                        ):
                            path.unlink()
                            continue
                    except OSError:
                        pass
                raise LockError(f"Another vaultctl operation is active: {path}")
        yield path
    finally:
        if acquired:
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
                if current.get("token") == token:
                    path.unlink()
            except (OSError, UnicodeError, ValueError, TypeError):
                pass
