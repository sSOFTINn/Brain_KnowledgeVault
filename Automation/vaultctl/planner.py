from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import csv
import json
import uuid

from .config import Config
from .fileops import file_sha256
from .router import normalized, safe_destination


@dataclass
class MigrationRow:
    row_id: str
    scan_run_id: str
    source_path: str
    destination_path: str
    operation: str
    reason: str
    confidence: str
    source_sha256: str | None
    expected_size: int
    exact_duplicate: bool
    name_collision: bool
    privacy_classification: str
    review_status: str
    reviewer_note: str = ""
    approved_at: str | None = None


def _load_inventory(run_dir: Path) -> list[dict]:
    path = run_dir / "inventory.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"Inventory not found: {path}")
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def resolve_run(value: str | Path, config: Config) -> Path:
    runs_root = (
        config.routing_runtime
        if config.schema_version == 2
        else config.runtime / "runs"
    )
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = runs_root / candidate
    run_dir = candidate.resolve()
    try:
        run_dir.relative_to(runs_root.resolve())
    except ValueError as exc:
        raise ValueError("Scan run must be inside Runtime/runs") from exc
    if not run_dir.is_dir():
        raise NotADirectoryError(f"Scan run does not exist: {run_dir}")
    return run_dir


def _source_hash(record: dict) -> str | None:
    existing = record.get("sha256")
    if existing:
        return str(existing)
    path = Path(record["source_path"])
    try:
        if path.is_file() and path.stat().st_size == int(record["size"]):
            return file_sha256(path)
    except OSError:
        return None
    return None


def create_plan(run: str | Path, config: Config) -> tuple[Path, list[MigrationRow]]:
    run_dir = resolve_run(run, config)
    records = _load_inventory(run_dir)
    run_meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    scan_run_id = run_meta["run_id"]

    rows: list[MigrationRow] = []
    canonical_by_hash: dict[str, MigrationRow] = {}
    destination_rows: dict[str, MigrationRow] = {}

    for record in records:
        source = Path(record["source_path"])
        destination = safe_destination(
            config.root,
            Path(record["proposed_destination"]) / record["filename"],
        )
        source_hash = _source_hash(record)
        confidence = str(record["confidence"])
        privacy = str(record["privacy_risk"])
        operation = "copy"
        review_status = "pending"
        reasons = [f"class={record['proposed_class']}", f"confidence={confidence}"]
        exact_duplicate = False
        name_collision = False

        if confidence == "low" or privacy != "normal":
            operation = "manual-review"
            review_status = "manual"
            reasons.append("manual review required")

        if source_hash and source_hash in canonical_by_hash:
            operation = "skip"
            review_status = "pending"
            exact_duplicate = True
            reasons.append(f"exact duplicate of {canonical_by_hash[source_hash].row_id}")

        destination_key = normalized(str(destination))
        previous = destination_rows.get(destination_key)
        if previous and not exact_duplicate:
            name_collision = True
            operation = "manual-review"
            review_status = "manual"
            reasons.append(f"destination collision with {previous.row_id}")

        if destination.exists() and source_hash:
            try:
                if file_sha256(destination) == source_hash:
                    operation = "skip"
                    review_status = "pending"
                    exact_duplicate = True
                    reasons.append("exact duplicate already exists at destination")
                else:
                    name_collision = True
                    operation = "manual-review"
                    review_status = "manual"
                    reasons.append("different file already exists at destination")
            except OSError as exc:
                operation = "manual-review"
                review_status = "manual"
                reasons.append(f"destination check failed: {type(exc).__name__}")

        row_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"knowledgevault:{scan_run_id}:{source}:{destination}",
            )
        )
        row = MigrationRow(
            row_id=row_id,
            scan_run_id=scan_run_id,
            source_path=str(source),
            destination_path=str(destination),
            operation=operation,
            reason="; ".join(reasons),
            confidence=confidence,
            source_sha256=source_hash,
            expected_size=int(record["size"]),
            exact_duplicate=exact_duplicate,
            name_collision=name_collision,
            privacy_classification=privacy,
            review_status=review_status,
        )
        rows.append(row)
        destination_rows.setdefault(destination_key, row)
        if source_hash:
            canonical_by_hash.setdefault(source_hash, row)

    _write_outputs(run_dir, rows)
    return run_dir / "migration_plan.jsonl", rows


def _write_outputs(run_dir: Path, rows: list[MigrationRow]) -> None:
    jsonl = run_dir / "migration_plan.jsonl"
    with jsonl.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")

    fields = list(MigrationRow.__dataclass_fields__)
    with (run_dir / "migration_plan.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)

    lines = [
        "# Migration plan",
        "",
        "AUTO-GENERATED. DO NOT EDIT MANUALLY.",
        "",
        "| Operation | Review | Confidence | Source | Destination | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        source = row.source_path.replace("|", "\\|")
        destination = row.destination_path.replace("|", "\\|")
        reason = row.reason.replace("|", "\\|")
        lines.append(
            f"| {row.operation} | {row.review_status} | {row.confidence} | "
            f"`{source}` | `{destination}` | {reason} |"
        )
    (run_dir / "migration_plan.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )

    conflicts = [row for row in rows if row.exact_duplicate or row.name_collision]
    conflict_lines = [
        "# Migration conflicts",
        "",
        "AUTO-GENERATED. DO NOT EDIT MANUALLY.",
        "",
    ]
    if not conflicts:
        conflict_lines.append("No duplicate or destination conflicts detected.")
    else:
        for row in conflicts:
            conflict_lines.append(
                f"- `{row.row_id}`: duplicate={row.exact_duplicate}, "
                f"collision={row.name_collision}, source=`{row.source_path}`"
            )
    (run_dir / "conflicts.md").write_text(
        "\n".join(conflict_lines) + "\n", encoding="utf-8", newline="\n"
    )
