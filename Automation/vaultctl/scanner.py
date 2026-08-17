from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import csv
import json
import mimetypes
import os
import stat
import uuid

from .config import Config
from .fileops import file_sha256
from .router import normalized, select_project, select_rule


DEFAULT_EXCLUDED_NAMES = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
    "appdata",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
}

SENSITIVE_HINTS = {
    "private",
    "personal",
    "passport",
    "tax",
    "bank",
    "financial",
    "legal",
    "contract",
    "invoice",
    "медич",
    "паспорт",
    "банк",
    "фінанс",
    "догов",
}

FILE_ATTRIBUTE_OFFLINE = getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000


@dataclass
class InventoryItem:
    run_id: str
    source_root: str
    source_path: str
    relative_path: str
    filename: str
    extension: str
    mime_type: str | None
    size: int
    created_at: str
    modified_at: str
    attributes: int
    hidden: bool
    read_only: bool
    reparse_point: bool
    cloud_placeholder: bool
    project_code: str | None
    proposed_class: str
    proposed_destination: str
    confidence: str
    privacy_risk: str
    duplicate_candidate: bool = False
    sha256: str | None = None


@dataclass
class ScanError:
    path: str
    error_type: str
    message: str


@dataclass
class ScanResult:
    run_id: str
    run_dir: Path
    items: list[InventoryItem]
    errors: list[ScanError]
    skipped: dict[str, int]


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _attributes(info: os.stat_result) -> int:
    return int(getattr(info, "st_file_attributes", 0))


def _is_reparse(info: os.stat_result, entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink() or bool(_attributes(info) & FILE_ATTRIBUTE_REPARSE_POINT)


def _is_placeholder(attributes: int) -> bool:
    flags = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
    return bool(attributes & flags)


def _privacy(relative: str) -> str:
    text = normalized(relative)
    return "review" if any(hint in text for hint in SENSITIVE_HINTS) else "normal"


def _proposal(path: Path, source_root: Path, config: Config) -> tuple[str | None, str, str, str]:
    project, score, _ = select_project(path, source_root, config.projects)
    rule = select_rule(path, config.rules)
    if rule and project:
        destination = rule.destination.format(project_code=project.code, project_name=project.name)
        confidence = "high" if score + 0.10 >= config.auto_threshold else "medium"
        return project.code, rule.name, destination, confidence
    if rule:
        return None, rule.name, f"Assets/Unassigned/{rule.name}", "medium"
    return None, "unknown", "Assets/Unassigned/other", "low"


def _blocked_roots(config: Config) -> tuple[Path, ...]:
    return (config.runtime.resolve(), config.staging.resolve())


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _walk_read_only(
    source_root: Path,
    config: Config,
    run_id: str,
) -> tuple[list[InventoryItem], list[ScanError], dict[str, int]]:
    items: list[InventoryItem] = []
    errors: list[ScanError] = []
    skipped = {"excluded": 0, "reparse": 0, "placeholder": 0}
    stack = [source_root]
    blocked = _blocked_roots(config)

    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                ordered = sorted(entries, key=lambda item: normalized(item.name), reverse=True)
        except OSError as exc:
            errors.append(ScanError(str(directory), type(exc).__name__, str(exc)))
            continue

        for entry in ordered:
            path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
                attributes = _attributes(info)
                reparse = _is_reparse(info, entry)
                if reparse:
                    skipped["reparse"] += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if normalized(entry.name) in DEFAULT_EXCLUDED_NAMES:
                        skipped["excluded"] += 1
                        continue
                    if any(_inside(path, root) for root in blocked):
                        skipped["excluded"] += 1
                        continue
                    stack.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    skipped["excluded"] += 1
                    continue
                placeholder = _is_placeholder(attributes)
                if placeholder:
                    skipped["placeholder"] += 1
                    continue
                relative = path.relative_to(source_root).as_posix()
                project_code, proposed_class, destination, confidence = _proposal(
                    path, source_root, config
                )
                items.append(
                    InventoryItem(
                        run_id=run_id,
                        source_root=str(source_root),
                        source_path=str(path.resolve()),
                        relative_path=relative,
                        filename=entry.name,
                        extension=path.suffix.lower(),
                        mime_type=mimetypes.guess_type(entry.name)[0],
                        size=info.st_size,
                        created_at=_iso(info.st_ctime),
                        modified_at=_iso(info.st_mtime),
                        attributes=attributes,
                        hidden=entry.name.startswith(".") or bool(attributes & 0x2),
                        read_only=not os.access(path, os.W_OK) or bool(attributes & 0x1),
                        reparse_point=False,
                        cloud_placeholder=False,
                        project_code=project_code,
                        proposed_class=proposed_class,
                        proposed_destination=destination,
                        confidence=confidence,
                        privacy_risk=_privacy(relative),
                    )
                )
            except OSError as exc:
                errors.append(ScanError(str(path), type(exc).__name__, str(exc)))
    items.sort(key=lambda item: normalized(item.relative_path))
    return items, errors, skipped


def _hash_items(
    items: list[InventoryItem],
    mode: str,
    errors: list[ScanError],
    max_workers: int,
) -> None:
    if mode in {"none", "selected"}:
        return
    if mode == "all":
        candidates = items
    else:
        groups: dict[int, list[InventoryItem]] = {}
        for item in items:
            groups.setdefault(item.size, []).append(item)
        candidates = [item for group in groups.values() if len(group) > 1 for item in group]
        for item in candidates:
            item.duplicate_candidate = True
    def calculate(item: InventoryItem) -> tuple[InventoryItem, str | None, ScanError | None]:
        try:
            return item, file_sha256(Path(item.source_path)), None
        except OSError as exc:
            return item, None, ScanError(item.source_path, type(exc).__name__, str(exc))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(calculate, candidates))
    for item, digest, error in results:
        item.sha256 = digest
        if error is not None:
            errors.append(error)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_csv(path: Path, items: list[InventoryItem]) -> None:
    fields = list(InventoryItem.__dataclass_fields__)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(item) for item in items)


def _write_report(path: Path, result: ScanResult, hash_mode: str) -> None:
    total_size = sum(item.size for item in result.items)
    classes: dict[str, int] = {}
    for item in result.items:
        classes[item.proposed_class] = classes.get(item.proposed_class, 0) + 1
    lines = [
        "# Read-only scan report",
        "",
        "AUTO-GENERATED. DO NOT EDIT MANUALLY.",
        "",
        f"- Run ID: `{result.run_id}`",
        f"- Files: {len(result.items)}",
        f"- Total size: {total_size} bytes",
        f"- Errors: {len(result.errors)}",
        f"- Hash mode: `{hash_mode}`",
        f"- Skipped: `{json.dumps(result.skipped, ensure_ascii=False)}`",
        "",
        "## Proposed classes",
        "",
        "| Class | Files |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(classes.items()))
    if result.errors:
        lines.extend(["", "## Errors", "", "| Path | Error |", "|---|---|"])
        for error in result.errors[:100]:
            escaped_path = error.path.replace("|", "\\|")
            escaped_message = error.message.replace("|", "\\|")
            lines.append(
                f"| `{escaped_path}` | {error.error_type}: {escaped_message} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def scan(
    source: str | Path,
    config: Config,
    *,
    hash_mode: str | None = None,
    allow_system_root: bool = False,
) -> ScanResult:
    source_root = Path(source).expanduser().resolve()
    if not source_root.is_dir():
        raise NotADirectoryError(f"Scan source is not a directory: {source_root}")
    if source_root == Path(source_root.anchor) and not allow_system_root:
        raise ValueError("Scanning a filesystem root requires --allow-system-root")
    selected_hash_mode = hash_mode or config.hash_mode
    if selected_hash_mode not in {"none", "duplicates", "selected", "all"}:
        raise ValueError("Invalid hash mode")

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    runs_root = (
        config.routing_runtime
        if config.schema_version == 2
        else config.runtime / "runs"
    )
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    items, errors, skipped = _walk_read_only(source_root, config, run_id)
    _hash_items(items, selected_hash_mode, errors, config.max_workers)
    result = ScanResult(run_id, run_dir, items, errors, skipped)

    run_meta = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "config": str(config.config_path),
        "hash_mode": selected_hash_mode,
        "max_workers": config.max_workers,
        "read_only": True,
    }
    (run_dir / "run.json").write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_jsonl(run_dir / "inventory.jsonl", [asdict(item) for item in items])
    _write_csv(run_dir / "inventory.csv", items)
    _write_jsonl(run_dir / "errors.jsonl", [asdict(error) for error in errors])
    summary = {
        "files": len(items),
        "bytes": sum(item.size for item in items),
        "errors": len(errors),
        "skipped": skipped,
        "duplicate_candidates": sum(item.duplicate_candidate for item in items),
        "hashed": sum(item.sha256 is not None for item in items),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(run_dir / "report.md", result, selected_hash_mode)
    latest = runs_root / "latest.txt"
    latest.write_text(run_id + "\n", encoding="utf-8")
    return result
