from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json

from .config import Config
from .fileops import choose_destination, file_sha256, verified_copy
from .planner import MigrationRow
from .router import safe_destination
from .metadata import new_uid, today
from .storage import validate_storage_marker, write_audit_event


def load_migration_plan(path: str | Path) -> list[MigrationRow]:
    rows: list[MigrationRow] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(MigrationRow(**json.loads(line)))
    return rows


def _approval_path(plan_path: str | Path) -> Path:
    return Path(plan_path).parent / "migration_approvals.jsonl"


def approve_migration_row(
    plan_path: str | Path,
    row_id: str,
    config: Config,
    destination: str | None = None,
    note: str = "",
) -> MigrationRow:
    rows = load_migration_plan(plan_path)
    selected = next((row for row in rows if row.row_id == row_id), None)
    if selected is None:
        raise KeyError(f"Migration row not found: {row_id}")
    if selected.operation == "skip":
        approved_destination = safe_destination(config.root, selected.destination_path)
    else:
        approved_destination = safe_destination(
            config.root, destination or selected.destination_path
        )
    event = {
        "row_id": row_id,
        "review_status": "approved",
        "destination_path": str(approved_destination),
        "reviewer_note": note,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    with _approval_path(plan_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    selected.review_status = "approved"
    selected.destination_path = str(approved_destination)
    selected.reviewer_note = note
    selected.approved_at = event["approved_at"]
    return selected


def effective_migration_plan(path: str | Path) -> list[MigrationRow]:
    rows = load_migration_plan(path)
    by_id = {row.row_id: row for row in rows}
    approvals = _approval_path(path)
    if approvals.exists():
        with approvals.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                row = by_id.get(event["row_id"])
                if row:
                    row.review_status = event["review_status"]
                    row.destination_path = event["destination_path"]
                    row.reviewer_note = event.get("reviewer_note", "")
                    row.approved_at = event["approved_at"]
    return rows


def _completed_rows(journal_path: Path) -> set[str]:
    completed: set[str] = set()
    if not journal_path.exists():
        return completed
    with journal_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("result") in {
                "copied and verified",
                "copied with collision suffix and verified",
                "skipped: exact duplicate",
                "skipped: plan duplicate",
            }:
                completed.add(event["row_id"])
    return completed


def _write_asset_sidecar(
    destination: Path,
    source: Path,
    source_hash: str,
    config: Config,
) -> Path | None:
    try:
        relative = destination.resolve().relative_to(config.assets.resolve())
    except ValueError:
        return None
    sidecar = destination.with_name(destination.name + ".asset.md")
    if sidecar.exists():
        return sidecar
    parts = relative.parts
    project_code = parts[1] if len(parts) > 1 and parts[0] == "Projects" else ""
    content = f"""---
schema_version: 1
uid: {new_uid()}
type: asset
title: "{destination.name}"
status: active
created: {today()}
updated: {today()}
tags:
  - migrated-asset
aliases: []
visibility: internal
project_code: "{project_code}"
sha256: "{source_hash}"
source: {json.dumps(str(source), ensure_ascii=False)}
asset_path: {json.dumps(relative.as_posix(), ensure_ascii=False)}
---

# {destination.name}

Картка вкладення, створена після перевіреного копіювання.
"""
    frontmatter_end = content.find("\n---", 4)
    content = (
        content[: frontmatter_end + 4]
        + f"\n\n# {destination.name}\n\n"
        + "Картка вкладення, створена після перевіреного копіювання.\n"
    )
    sidecar.write_text(content, encoding="utf-8", newline="\n")
    return sidecar


def _execute_row(row: MigrationRow, config: Config) -> dict:
    event = {
        "row_id": row.row_id,
        "source_path": row.source_path,
        "destination_path": row.destination_path,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
        "sha256": row.source_sha256,
    }
    if row.operation == "skip" and row.exact_duplicate:
        event["result"] = "skipped: plan duplicate"
        return event

    source = Path(row.source_path).resolve()
    if not source.is_file():
        event["result"] = "error: source missing"
        return event
    if source.stat().st_size != row.expected_size:
        event["result"] = "error: source size changed"
        return event
    source_hash = file_sha256(source)
    if not row.source_sha256 or source_hash != row.source_sha256:
        event["result"] = "error: source hash changed"
        return event

    destination = safe_destination(config.root, row.destination_path)
    destination, state = choose_destination(destination, source_hash)
    event["destination_path"] = str(destination)
    if state == "duplicate":
        _write_asset_sidecar(destination, source, source_hash, config)
        event["result"] = "skipped: exact duplicate"
        return event

    verified_copy(
        source,
        destination,
        expected_size=row.expected_size,
        expected_sha256=source_hash,
        preserve_timestamps=config.preserve_timestamps,
    )
    sidecar = _write_asset_sidecar(destination, source, source_hash, config)
    if sidecar:
        event["sidecar_path"] = str(sidecar)
    event["result"] = (
        "copied and verified"
        if state == "new"
        else "copied with collision suffix and verified"
    )
    return event


def execute_migration_plan(
    plan_path: str | Path,
    config: Config,
) -> list[dict]:
    if config.schema_version == 2:
        validate_storage_marker(config)
    plan_path = Path(plan_path)
    rows = effective_migration_plan(plan_path)
    run_dir = plan_path.parent
    journal_path = run_dir / "migration_apply_journal.jsonl"
    verification_path = run_dir / "verification.jsonl"
    rollback_path = run_dir / "rollback_manifest.json"
    completed = _completed_rows(journal_path)
    events: list[dict] = []

    with journal_path.open("a", encoding="utf-8", newline="\n") as journal, \
            verification_path.open("a", encoding="utf-8", newline="\n") as verification:
        for row in rows:
            if row.review_status != "approved" or row.row_id in completed:
                continue
            try:
                event = _execute_row(row, config)
            except Exception as exc:
                event = {
                    "row_id": row.row_id,
                    "source_path": row.source_path,
                    "destination_path": row.destination_path,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "result": f"error: {type(exc).__name__}: {exc}",
                    "sha256": row.source_sha256,
                }
            event["finished_at"] = datetime.now(timezone.utc).isoformat()
            journal.write(json.dumps(event, ensure_ascii=False) + "\n")
            journal.flush()
            verification.write(
                json.dumps(
                    {
                        "row_id": event["row_id"],
                        "sha256": event.get("sha256"),
                        "verified": "verified" in str(event["result"])
                        or str(event["result"]).startswith("skipped:"),
                        "result": event["result"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            verification.flush()
            events.append(event)

    created = [
        {
            "row_id": event["row_id"],
            "created_path": event["destination_path"],
            "sha256": event.get("sha256"),
        }
        for event in events
        if str(event["result"]).startswith("copied")
    ]
    previous_created: list[dict] = []
    if rollback_path.exists():
        try:
            previous = json.loads(rollback_path.read_text(encoding="utf-8"))
            previous_created = list(previous.get("created_files", []))
        except (OSError, ValueError, TypeError):
            previous_created = []
    merged_created = {
        (item["row_id"], item["created_path"]): item
        for item in (*previous_created, *created)
    }
    rollback_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "notice": "Review manually. This manifest never deletes files automatically.",
                "created_files": list(merged_created.values()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    all_events: list[dict] = []
    if journal_path.exists():
        with journal_path.open("r", encoding="utf-8") as handle:
            all_events = [json.loads(line) for line in handle if line.strip()]
    summary = {
        "processed": len(all_events),
        "copied": sum(
            str(event["result"]).startswith("copied") for event in all_events
        ),
        "skipped": sum(
            str(event["result"]).startswith("skipped") for event in all_events
        ),
        "errors": sum(
            str(event["result"]).startswith("error:") for event in all_events
        ),
        "last_invocation_processed": len(events),
    }
    (run_dir / "apply_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if config.schema_version == 2 and events:
        write_audit_event(
            config,
            "file-import",
            {"plan": str(plan_path), "summary": summary},
        )
    return events


def is_migration_plan(path: str | Path) -> bool:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                return "scan_run_id" in json.loads(line)
    return Path(path).name.startswith("migration_plan")
