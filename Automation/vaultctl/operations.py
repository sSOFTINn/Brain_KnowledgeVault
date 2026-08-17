from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

from .backup import backup_snapshots
from .config import Config
from .planner import resolve_run
from .fileops import file_sha256


def generate_report(run: str | Path, config: Config) -> Path:
    run_dir = resolve_run(run, config)
    sections: list[str] = [
        "# KnowledgeVault run report",
        "",
        "AUTO-GENERATED. DO NOT EDIT MANUALLY.",
        "",
        f"- Run: `{run_dir.name}`",
    ]
    for name in ("summary.json", "apply_summary.json"):
        path = run_dir / name
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            sections.extend(["", f"## {name}", "", "```json", json.dumps(data, ensure_ascii=False, indent=2), "```"])
    conflicts = run_dir / "conflicts.md"
    if conflicts.is_file():
        sections.extend(["", "## Conflicts", "", conflicts.read_text(encoding="utf-8")])
    output = run_dir / "final_report.md"
    output.write_text("\n".join(sections) + "\n", encoding="utf-8", newline="\n")
    return output


def verify_run(run: str | Path, config: Config) -> tuple[Path, list[dict]]:
    run_dir = resolve_run(run, config)
    journal = run_dir / "migration_apply_journal.jsonl"
    if not journal.is_file():
        raise FileNotFoundError(f"Migration journal not found: {journal}")
    results: list[dict] = []
    with journal.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            result = str(event.get("result", ""))
            if not result.startswith("copied"):
                continue
            destination = Path(event["destination_path"])
            expected = event.get("sha256")
            verified = (
                destination.is_file()
                and bool(expected)
                and file_sha256(destination) == expected
            )
            results.append(
                {
                    "row_id": event["row_id"],
                    "destination_path": str(destination),
                    "expected_sha256": expected,
                    "verified": verified,
                }
            )
    output = run_dir / "post_apply_verification.json"
    output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if any(not item["verified"] for item in results):
        raise RuntimeError("One or more migrated files failed verification")
    return output, results


def create_cleanup_plan(
    run: str | Path,
    config: Config,
    retention_days: int = 30,
) -> Path:
    run_dir = resolve_run(run, config)
    journal = run_dir / "migration_apply_journal.jsonl"
    if not journal.is_file():
        raise FileNotFoundError("Migration journal is missing")
    snapshots = backup_snapshots(config)
    if not snapshots:
        raise RuntimeError("Cleanup plan requires at least one verified backup snapshot")
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    candidates: list[dict] = []
    with journal.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            if not str(event.get("result", "")).startswith("copied"):
                continue
            finished = datetime.fromisoformat(event["finished_at"])
            eligible = finished <= cutoff
            candidates.append(
                {
                    "row_id": event["row_id"],
                    "source_path": event["source_path"],
                    "destination_path": event["destination_path"],
                    "finished_at": event["finished_at"],
                    "eligible_after_days": retention_days,
                    "eligible": eligible,
                    "action": "manual-review-only",
                }
            )
    output = run_dir / "cleanup_plan.json"
    output.write_text(
        json.dumps(
            {
                "notice": "This plan never deletes files automatically.",
                "backup_snapshot_count": len(snapshots),
                "candidates": candidates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output
