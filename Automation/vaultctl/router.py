from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import stat
import unicodedata
import uuid

from .config import Config, Project, Rule
from .fileops import choose_destination, file_sha256, verified_copy


@dataclass
class Route:
    route_id: str
    source: str
    destination: str
    project_code: str | None
    rule: str | None
    confidence: float
    status: str
    reason: str
    size: int
    source_mtime_ns: int | None = None
    source_sha256: str | None = None
    result: str | None = None


def normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().replace("\\", "/")


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & flag)


def _contained(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes configured root: {resolved}") from exc
    return resolved


def _project_score(text: str, project: Project) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    for value in (project.code, project.name, *project.aliases):
        candidate = normalized(value)
        if candidate and candidate in text:
            score = max(score, 0.65)
            reasons.append(f"збіг проєкту: {value}")
    keyword_hits = [word for word in project.keywords if normalized(word) in text]
    if keyword_hits:
        score += min(0.24, 0.08 * len(keyword_hits))
        reasons.append("ключові слова: " + ", ".join(keyword_hits[:3]))
    hint_hits = [hint for hint in project.source_hints if normalized(hint) in text]
    if hint_hits:
        score += min(0.25, 0.15 * len(hint_hits))
        reasons.append("джерело: " + ", ".join(hint_hits[:2]))
    return min(score, 0.95), reasons


def select_project(source: Path, inbox: Path, projects: tuple[Project, ...]) -> tuple[Project | None, float, list[str]]:
    try:
        relative = source.relative_to(inbox)
    except ValueError:
        relative = source
    text = normalized(str(relative))
    ranked = [(project, *_project_score(text, project)) for project in projects]
    ranked.sort(key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] == 0:
        return None, 0.0, []
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None, ranked[0][1], ["неоднозначний збіг між проєктами"]
    return ranked[0]


def select_rule(source: Path, rules: tuple[Rule, ...]) -> Rule | None:
    suffix = source.suffix.lower()
    return next((rule for rule in rules if suffix in rule.extensions), None)


def safe_destination(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return _contained(candidate if candidate.is_absolute() else root / candidate, root, "Destination")


def _destination_from_template(root: Path, template: str, project: Project | None, filename: str) -> Path:
    values = {
        "project_code": project.code if project else "UNASSIGNED",
        "project_name": project.name if project else "Unassigned",
    }
    return safe_destination(root, Path(template.format(**values)) / filename)


def classify(source: Path, config: Config) -> Route:
    project, project_score, reasons = select_project(source, config.inbox, config.projects)
    rule = select_rule(source, config.rules)
    confidence = min(project_score + (0.10 if rule else 0.0), 0.99)
    if rule:
        template = rule.destination
        reasons.append(f"тип файла: {rule.name}")
    else:
        template = "Assets/Unassigned/other"
        reasons.append("немає правила для розширення")
    destination = _destination_from_template(config.root, template, project, source.name)
    status = "approved" if project and rule and confidence >= config.auto_threshold else "review"
    source_stat = source.stat()
    return Route(
        route_id=str(uuid.uuid7() if hasattr(uuid, "uuid7") else uuid.uuid4()),
        source=str(source.resolve()),
        destination=str(destination),
        project_code=project.code if project else None,
        rule=rule.name if rule else None,
        confidence=round(confidence, 2),
        status=status,
        reason="; ".join(reasons) or "недостатньо сигналів",
        size=source_stat.st_size,
        source_mtime_ns=source_stat.st_mtime_ns,
    )


def inventory(config: Config) -> list[Route]:
    if not config.inbox.exists():
        return []
    files: list[Path] = []
    for path in config.inbox.rglob("*"):
        if _is_reparse_point(path):
            continue
        if path.is_file() and not path.name.endswith((".partial", ".tmp")):
            files.append(path)
    return [classify(path, config) for path in sorted(files)]


def create_run(config: Config, routes: list[Route]) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = config.routing_runtime / f"{timestamp}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    plan_path = run_dir / "route_plan.jsonl"
    with plan_path.open("w", encoding="utf-8", newline="\n") as handle:
        for route in routes:
            handle.write(json.dumps(asdict(route), ensure_ascii=False) + "\n")
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": str(config.config_path),
        "inbox": str(config.inbox),
        "total": len(routes),
        "approved": sum(route.status == "approved" for route in routes),
        "review": sum(route.status == "review" for route in routes),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_dir


def load_plan(path: str | Path) -> list[Route]:
    routes: list[Route] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                routes.append(Route(**json.loads(line)))
    return routes


def _approval_path(plan_path: str | Path) -> Path:
    return Path(plan_path).parent / "approvals.jsonl"


def approve_route(
    plan_path: str | Path,
    route_id: str,
    config: Config,
    destination: str | None = None,
) -> Route:
    routes = load_plan(plan_path)
    selected = next((route for route in routes if route.route_id == route_id), None)
    if selected is None:
        raise KeyError(f"Route not found: {route_id}")
    approved_destination = safe_destination(config.root, destination or selected.destination)
    event = {
        "route_id": route_id,
        "status": "approved",
        "destination": str(approved_destination),
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    with _approval_path(plan_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    selected.status = "approved"
    selected.destination = str(approved_destination)
    return selected


def effective_plan(plan_path: str | Path) -> list[Route]:
    routes = load_plan(plan_path)
    by_id = {route.route_id: route for route in routes}
    approvals = _approval_path(plan_path)
    if approvals.exists():
        with approvals.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                route = by_id.get(event["route_id"])
                if route:
                    route.status = event["status"]
                    route.destination = event["destination"]
    return routes


def execute_route(route: Route, config: Config) -> Route:
    source = _contained(Path(route.source), config.inbox, "Source")
    destination = safe_destination(config.root, route.destination)
    if not source.is_file() or _is_reparse_point(source):
        route.result = "error: source missing or unsafe"
        return route
    current = source.stat()
    if current.st_size != route.size or (
        route.source_mtime_ns is not None and current.st_mtime_ns != route.source_mtime_ns
    ):
        route.result = "error: source changed after planning"
        return route

    source_hash = file_sha256(source)
    route.source_sha256 = source_hash
    destination, collision = choose_destination(destination, source_hash)
    route.destination = str(destination)
    if collision == "duplicate":
        route.result = "skipped: exact duplicate"
        return route

    verified_copy(
        source,
        destination,
        expected_size=current.st_size,
        expected_sha256=source_hash,
        preserve_timestamps=config.preserve_timestamps,
    )
    route.result = (
        "copied and verified"
        if collision == "new"
        else "copied with collision suffix and verified"
    )
    return route


def execute_plan(plan_path: str | Path, config: Config) -> list[Route]:
    routes = effective_plan(plan_path)
    journal_path = Path(plan_path).parent / "apply_journal.jsonl"
    completed: set[str] = set()
    if journal_path.exists():
        with journal_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    event = json.loads(line)
                    if not str(event.get("result", "")).startswith("error:"):
                        completed.add(event["route_id"])
    with journal_path.open("a", encoding="utf-8", newline="\n") as journal:
        for route in routes:
            if route.status != "approved" or route.route_id in completed:
                continue
            try:
                execute_route(route, config)
            except Exception as exc:
                route.result = f"error: {type(exc).__name__}: {exc}"
            journal.write(json.dumps(asdict(route), ensure_ascii=False) + "\n")
            journal.flush()
    return routes
