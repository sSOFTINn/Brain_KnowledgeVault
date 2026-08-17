from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import csv
import json
import os
import shutil
import stat
import subprocess
import uuid

from .config import Config
from .fileops import file_sha256, verified_copy
from .storage import validate_storage_marker, write_audit_event


@dataclass(frozen=True)
class RepositoryRecord:
    repository_id: str
    source: str
    destination: str
    branch: str
    head: str
    remotes: tuple[str, ...]
    dirty_entries: int
    ignored_entries: int
    dirty_paths: tuple[str, ...]
    ignored_paths: tuple[str, ...]
    local_branches: int
    tags: int
    local_branch_names: tuple[str, ...]
    tag_names: tuple[str, ...]
    nested_repositories: tuple[str, ...]
    submodules: tuple[str, ...]
    worktrees: tuple[str, ...]
    lfs_enabled: bool
    reparse_points: tuple[dict[str, str], ...]
    file_count: int
    total_bytes: int
    manifest_sha256: str
    review_status: str
    reviewer_note: str = ""
    approved_at: str | None = None


def _run_git(repository: Path, *arguments: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        detail = "\n".join(
            value.strip() for value in (result.stdout, result.stderr) if value.strip()
        )
        raise RuntimeError(
            f"git {' '.join(arguments)} failed in {repository}: {detail}"
        )
    return result.stdout


def _current_head(repository: Path) -> str:
    output = _run_git(repository, "rev-parse", "--verify", "HEAD", check=False).strip()
    candidate = output.splitlines()[0] if output else ""
    return (
        candidate
        if len(candidate) in {40, 64}
        and all(ch in "0123456789abcdefABCDEF" for ch in candidate)
        else ""
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


def discover_repositories(source_roots: list[str | Path]) -> list[Path]:
    found: set[Path] = set()
    for value in source_roots:
        source = Path(value).expanduser().resolve()
        if not source.is_dir():
            raise NotADirectoryError(f"Repository source root does not exist: {source}")
        stack = [source]
        while stack:
            current = stack.pop()
            marker = current / ".git"
            if marker.is_dir() or marker.is_file():
                found.add(current)
                # A repository is one migration unit. Nested repositories are
                # recorded by the manifest traversal and are not double-routed.
                continue
            try:
                children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                continue
            for child in children:
                if child.name in {"$RECYCLE.BIN", "System Volume Information"}:
                    continue
                if _is_reparse(child):
                    continue
                if child.is_dir():
                    stack.append(child)
    return sorted(found, key=lambda item: str(item).casefold())


def _tree_manifest(repository: Path) -> tuple[list[dict], list[dict[str, str]]]:
    files: list[dict] = []
    reparses: list[dict[str, str]] = []
    stack = [repository]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise OSError(f"Cannot enumerate repository path {current}: {exc}") from exc
        for child in children:
            relative = child.relative_to(repository).as_posix()
            if _is_reparse(child):
                try:
                    target = str(child.resolve(strict=False))
                except OSError:
                    target = "unresolved"
                reparses.append({"path": relative, "target": target, "type": "reparse"})
                continue
            if child.is_dir():
                stack.append(child)
                continue
            if not child.is_file():
                raise OSError(f"Unsupported repository object: {child}")
            info = child.stat()
            files.append(
                {
                    "relative_path": relative,
                    "size": info.st_size,
                    "mtime_ns": info.st_mtime_ns,
                    "sha256": file_sha256(child),
                }
            )
    files.sort(key=lambda item: str(item["relative_path"]).casefold())
    reparses.sort(key=lambda item: item["path"].casefold())
    return files, reparses


def _manifest_digest(files: list[dict]) -> str:
    payload = "".join(
        f"{item['relative_path']}\0{item['size']}\0{item['sha256']}\n"
        for item in files
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _repo_metadata(repository: Path) -> dict:
    status = _run_git(repository, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    ignored = _run_git(
        repository,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
    )
    remote_values: list[str] = []
    for remote_name in _run_git(repository, "remote", check=False).splitlines():
        remote_name = remote_name.strip()
        if not remote_name:
            continue
        for value in _run_git(
            repository, "remote", "get-url", "--all", remote_name, check=False
        ).splitlines():
            if value.strip():
                remote_values.append(f"{remote_name}={value.strip()}")
    remotes = tuple(remote_values)
    worktrees_raw = _run_git(repository, "worktree", "list", "--porcelain")
    worktrees = tuple(
        line[9:].strip() for line in worktrees_raw.splitlines() if line.startswith("worktree ")
    )
    submodules = tuple(
        line.strip()
        for line in _run_git(repository, "submodule", "status", "--recursive", check=False).splitlines()
        if line.strip()
    )
    nested: list[str] = []
    stack = [repository]
    while stack:
        current = stack.pop()
        if current != repository and (
            (current / ".git").is_dir() or (current / ".git").is_file()
        ):
            nested.append(current.relative_to(repository).as_posix())
            continue
        try:
            children = current.iterdir()
        except OSError:
            continue
        for child in children:
            if child.name == ".git" or _is_reparse(child):
                continue
            if child.is_dir():
                stack.append(child)
    lfs_output = _run_git(repository, "lfs", "ls-files", check=False)
    branch_names = tuple(
        line.strip()
        for line in _run_git(
            repository, "for-each-ref", "refs/heads", "--format=%(refname:short)"
        ).splitlines()
        if line.strip()
    )
    tag_names = tuple(
        line.strip()
        for line in _run_git(repository, "tag", "--list").splitlines()
        if line.strip()
    )
    return {
        "branch": _run_git(repository, "branch", "--show-current").strip(),
        "head": _current_head(repository),
        "remotes": remotes,
        "dirty_entries": status.count("\0"),
        "ignored_entries": ignored.count("\0"),
        "dirty_paths": tuple(item for item in status.split("\0") if item),
        "ignored_paths": tuple(item for item in ignored.split("\0") if item),
        "local_branches": len(branch_names),
        "tags": len(tag_names),
        "local_branch_names": branch_names,
        "tag_names": tag_names,
        "nested_repositories": tuple(sorted(set(nested), key=str.casefold)),
        "submodules": submodules,
        "worktrees": worktrees,
        "lfs_enabled": bool(lfs_output.strip()) or (repository / ".lfsconfig").exists(),
    }


def create_repository_plan(
    config: Config,
    source_roots: list[str | Path],
    *,
    project_state: str = "Active",
    output_dir: str | Path | None = None,
) -> tuple[Path, list[RepositoryRecord]]:
    if config.schema_version != 2:
        raise ValueError("Repository migration requires schema_version = 2")
    if project_state not in {"Active", "Reference", "Completed"}:
        raise ValueError("project_state must be Active, Reference, or Completed")
    repositories = discover_repositories(source_roots)
    output_root = Path(output_dir or config.routing_runtime).expanduser().resolve()
    if any(output_root.is_relative_to(repository) for repository in repositories):
        raise ValueError("Repository plan output cannot be inside a source repository")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run_dir = output_root / f"repositories_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=False)
    records: list[RepositoryRecord] = []
    destinations: set[str] = set()
    for repository in repositories:
        metadata = _repo_metadata(repository)
        files, reparses = _tree_manifest(repository)
        digest = _manifest_digest(files)
        is_control_plane = any(
            "brain_knowledgevault" in remote.casefold()
            for remote in metadata["remotes"]
        )
        canonical_name = (
            "AGENTS_Colaboration_Claude"
            if any(
                "agents_colaboration_claude" in remote.casefold()
                for remote in metadata["remotes"]
            )
            else repository.name
        )
        base_destination = (
            config.control_plane / "Brain_KnowledgeVault"
            if is_control_plane
            else config.root / "10_Projects" / project_state / canonical_name
        )
        destination = base_destination
        counter = 2
        while str(destination).casefold() in destinations:
            destination = base_destination.with_name(f"{base_destination.name}-{counter}")
            counter += 1
        destinations.add(str(destination).casefold())
        repository_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"knowledgevault-repository:{repository}:{digest}")
        )
        manifest_name = f"repository-{repository_id}.jsonl"
        with (run_dir / manifest_name).open("w", encoding="utf-8", newline="\n") as handle:
            for item in files:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        records.append(
            RepositoryRecord(
                repository_id=repository_id,
                source=str(repository),
                destination=str(destination),
                reparse_points=tuple(reparses),
                file_count=len(files),
                total_bytes=sum(int(item["size"]) for item in files),
                manifest_sha256=digest,
                review_status=(
                    "blocked"
                    if (
                        reparses
                        or destination.exists()
                        or any(
                            Path(item).resolve() != repository.resolve()
                            for item in metadata["worktrees"]
                        )
                    )
                    else "pending"
                ),
                **metadata,
            )
        )
    plan_path = run_dir / "repository_plan.jsonl"
    with plan_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")
    fields = list(RepositoryRecord.__dataclass_fields__)
    with (run_dir / "git-repositories.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = asdict(record)
            for field in (
                "remotes",
                "dirty_paths",
                "ignored_paths",
                "local_branch_names",
                "tag_names",
                "nested_repositories",
                "submodules",
                "worktrees",
                "reparse_points",
            ):
                row[field] = json.dumps(row[field], ensure_ascii=False)
            writer.writerow(row)
    with (run_dir / "RESTORE_MAP.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(("OriginalPath", "NewPath", "Classification", "Approved", "Notes"))
        for record in records:
            classification = (
                "Git/ControlPlane"
                if Path(record.destination).is_relative_to(config.control_plane)
                else f"Git/{project_state}"
            )
            writer.writerow((record.source, record.destination, classification, "NO", ""))
    digest_file = sha256(plan_path.read_bytes()).hexdigest()
    (run_dir / "repository_plan.sha256").write_text(
        f"{digest_file}  repository_plan.jsonl\n", encoding="ascii", newline="\n"
    )
    return plan_path, records


def _verify_plan_digest(plan_path: Path) -> None:
    digest_path = plan_path.with_name("repository_plan.sha256")
    if not digest_path.is_file():
        raise FileNotFoundError("Repository plan digest is missing")
    expected = digest_path.read_text(encoding="ascii").split()[0]
    actual = sha256(plan_path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("Repository plan changed after creation")


def _load_plan(plan_path: Path) -> list[RepositoryRecord]:
    _verify_plan_digest(plan_path)
    records: list[RepositoryRecord] = []
    with plan_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                for field in (
                    "remotes",
                    "dirty_paths",
                    "ignored_paths",
                    "local_branch_names",
                    "tag_names",
                    "nested_repositories",
                    "submodules",
                    "worktrees",
                    "reparse_points",
                ):
                    payload[field] = tuple(payload[field])
                records.append(RepositoryRecord(**payload))
    return records


def approve_repository(
    plan_path: str | Path,
    repository_id: str,
    config: Config,
    *,
    destination: str | Path | None = None,
    note: str = "",
) -> RepositoryRecord:
    path = Path(plan_path).resolve()
    selected = next(
        (item for item in _load_plan(path) if item.repository_id == repository_id), None
    )
    if selected is None:
        raise KeyError(f"Repository not found in plan: {repository_id}")
    if selected.reparse_points:
        raise ValueError("Repository contains reparse points and cannot be approved")
    if any(
        Path(item).resolve() != Path(selected.source).resolve()
        for item in selected.worktrees
    ):
        raise ValueError("Repository has external linked worktrees and cannot be approved")
    target = Path(destination or selected.destination)
    if not target.is_absolute():
        target = config.root / target
    target = target.resolve()
    allowed_roots = (
        (config.root / "10_Projects").resolve(),
        config.control_plane.resolve(),
    )
    if not any(target.is_relative_to(root) for root in allowed_roots):
        raise ValueError("Repository destination must be inside 10_Projects or ControlPlane")
    if target.exists():
        raise FileExistsError(f"Repository destination already exists: {target}")
    event = {
        "repository_id": repository_id,
        "destination": str(target),
        "review_status": "approved",
        "reviewer_note": note,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.with_name("repository_approvals.jsonl").open(
        "a", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return RepositoryRecord(
        **{
            **asdict(selected),
            "destination": str(target),
            "review_status": "approved",
            "reviewer_note": note,
            "approved_at": event["approved_at"],
        }
    )


def effective_repository_plan(plan_path: str | Path) -> list[RepositoryRecord]:
    path = Path(plan_path).resolve()
    records = {item.repository_id: item for item in _load_plan(path)}
    approvals = path.with_name("repository_approvals.jsonl")
    if approvals.is_file():
        with approvals.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                selected = records.get(event["repository_id"])
                if selected is None:
                    continue
                records[selected.repository_id] = RepositoryRecord(
                    **{
                        **asdict(selected),
                        "destination": event["destination"],
                        "review_status": event["review_status"],
                        "reviewer_note": event.get("reviewer_note", ""),
                        "approved_at": event["approved_at"],
                    }
                )
    return list(records.values())


def _load_manifest(run_dir: Path, repository_id: str) -> list[dict]:
    path = run_dir / f"repository-{repository_id}.jsonl"
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _verify_source(record: RepositoryRecord, manifest: list[dict]) -> None:
    source = Path(record.source)
    current, reparses = _tree_manifest(source)
    if reparses:
        raise ValueError(f"Repository gained reparse points: {source}")
    if _manifest_digest(current) != record.manifest_sha256 or current != manifest:
        raise ValueError(f"Repository changed after planning: {source}")


def apply_repository_plan(plan_path: str | Path, config: Config) -> list[dict]:
    validate_storage_marker(config)
    path = Path(plan_path).resolve()
    records = effective_repository_plan(path)
    journal_path = path.with_name("repository_apply_journal.jsonl")
    completed: set[str] = set()
    if journal_path.is_file():
        with journal_path.open("r", encoding="utf-8") as handle:
            completed = {
                item["repository_id"]
                for item in (json.loads(line) for line in handle if line.strip())
                if item.get("result") == "copied and verified"
            }
    events: list[dict] = []
    with journal_path.open("a", encoding="utf-8", newline="\n") as journal:
        for record in records:
            if record.review_status != "approved" or record.repository_id in completed:
                continue
            event = {
                "repository_id": record.repository_id,
                "source": record.source,
                "destination": record.destination,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                source = Path(record.source)
                destination = Path(record.destination)
                allowed_roots = (
                    (config.root / "10_Projects").resolve(),
                    config.control_plane.resolve(),
                )
                if not any(destination.resolve().is_relative_to(root) for root in allowed_roots):
                    raise ValueError("Destination escapes repository roots")
                if destination.exists():
                    raise FileExistsError(f"Destination already exists: {destination}")
                manifest = _load_manifest(path.parent, record.repository_id)
                _verify_source(record, manifest)
                temporary = destination.with_name(
                    f".{destination.name}.{uuid.uuid4().hex}.partial"
                )
                try:
                    temporary.mkdir(parents=True, exist_ok=False)
                    for item in manifest:
                        source_file = source / item["relative_path"]
                        destination_file = temporary / item["relative_path"]
                        verified_copy(
                            source_file,
                            destination_file,
                            expected_size=int(item["size"]),
                            expected_sha256=str(item["sha256"]),
                            preserve_timestamps=True,
                        )
                    destination_manifest, destination_reparses = _tree_manifest(temporary)
                    if destination_reparses or _manifest_digest(destination_manifest) != record.manifest_sha256:
                        raise RuntimeError("Destination repository verification failed")
                    if _current_head(temporary) != record.head:
                        raise RuntimeError("Destination Git HEAD differs from source plan")
                    _run_git(temporary, "fsck", "--full")
                    os.rename(temporary, destination)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
                event["result"] = "copied and verified"
            except Exception as exc:
                event["result"] = f"error: {type(exc).__name__}: {exc}"
            event["finished_at"] = datetime.now(timezone.utc).isoformat()
            journal.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            journal.flush()
            events.append(event)
    if events:
        write_audit_event(config, "repository-import", {"events": events})
    return events


def verify_repository_plan(plan_path: str | Path) -> list[dict]:
    path = Path(plan_path).resolve()
    results: list[dict] = []
    for record in effective_repository_plan(path):
        if record.review_status != "approved":
            continue
        destination = Path(record.destination)
        try:
            manifest, reparses = _tree_manifest(destination)
            valid = (
                not reparses
                and _manifest_digest(manifest) == record.manifest_sha256
                and _current_head(destination) == record.head
            )
            if valid:
                _run_git(destination, "fsck", "--full")
            results.append(
                {
                    "repository_id": record.repository_id,
                    "destination": record.destination,
                    "verified": valid,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "repository_id": record.repository_id,
                    "destination": record.destination,
                    "verified": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return results
