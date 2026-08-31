from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import tomllib

from .local_http import validate_local_base_url


STORAGE_DIRECTORIES_V2 = (
    "00_System/ControlPlane",
    "00_System/Config",
    "00_System/Audit",
    "00_System/Audit/CodexStorageMigration",
    "00_System/Manifests",
    "00_System/Policies",
    "00_System/Recovery",
    "00_System/ToolState",
    "10_Projects/Active",
    "10_Projects/Reference",
    "10_Projects/Completed",
    "20_Knowledge",
    "30_Documents/Personal",
    "30_Documents/Work",
    "30_Documents/Administrative",
    "40_Media/Photos",
    "40_Media/Video",
    "40_Media/Audio",
    "40_Media/Graphics",
    "50_Resources/ManagedAssets",
    "60_Private",
    "60_Private/ToolState/Codex",
    "70_Inbox",
    "75_Exports",
    "80_Archive",
    "90_Runtime/Catalog",
    "90_Runtime/Caches",
    "90_Runtime/Logs",
    "90_Runtime/Runs/Import",
    "90_Runtime/Staging",
    "90_Runtime/Staging/CodexStorageMigration",
    "90_Runtime/Temp",
    "90_Runtime/Worktrees",
    "99_Quarantine",
)


def discover_config_path(
    requested: str | Path | None,
    root_override: str | Path | None = None,
) -> Path:
    """Resolve CLI config precedence without preferring the tracked sample.

    Explicit --config wins, followed by KNOWLEDGE_VAULT_CONFIG, a local root
    config, and only then the tracked Automation fallback.
    """
    if requested:
        return Path(requested).expanduser().resolve()
    environment = os.environ.get("KNOWLEDGE_VAULT_CONFIG")
    if environment:
        return Path(os.path.expandvars(environment)).expanduser().resolve()
    root_value = root_override or os.environ.get("KNOWLEDGE_VAULT_ROOT")
    candidates: list[Path] = []
    if root_value:
        root = Path(os.path.expandvars(str(root_value))).expanduser().resolve()
        candidates.extend((root / "vault.toml.local", root / "vault.toml"))
    cwd = Path.cwd()
    candidates.extend((cwd / "vault.toml.local", cwd / "vault.toml"))
    automation = Path(__file__).resolve().parents[1]
    candidates.extend((automation / "vault.toml.local", automation / "vault.toml"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "No configuration found; pass --config or set KNOWLEDGE_VAULT_CONFIG"
    )


@dataclass(frozen=True)
class Project:
    code: str
    name: str
    aliases: tuple[str, ...]
    keywords: tuple[str, ...]
    source_hints: tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    name: str
    extensions: tuple[str, ...]
    destination: str


@dataclass(frozen=True)
class BackupConfig:
    repository: Path
    password_file: Path
    includes: tuple[Path, ...]
    excludes: tuple[str, ...]
    keep_daily: int
    keep_weekly: int
    keep_monthly: int
    max_snapshot_age_days: int
    critical_paths: tuple[Path, ...]
    require_all_includes: bool = True
    minimum_free_gib: int = 10
    readback_percent: int = 100


@dataclass(frozen=True)
class MachineProfileConfig:
    name: str
    root_volume_label: str
    root_volume_serial: str
    backup_volume_label: str
    backup_volume_serial: str
    require_distinct_physical_disks: bool


@dataclass(frozen=True)
class StorageConfig:
    marker_file: str
    allow_adopt: bool
    directories: tuple[str, ...]


@dataclass(frozen=True)
class CodexStorageConfig:
    enabled: bool
    home: Path
    projects: Path
    staging: Path
    audit: Path
    cleanup_retention_days: int


@dataclass(frozen=True)
class RagEmbeddingsConfig:
    enabled: bool
    provider: str
    model: str
    dimension: int


@dataclass(frozen=True)
class RagConfig:
    enabled: bool
    database: Path
    chunk_max_chars: int
    chunk_overlap_chars: int
    default_top_k: int
    embeddings: RagEmbeddingsConfig


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool
    provider: str
    model: str
    base_url: str
    context_limit_tokens: int
    temperature: float


@dataclass(frozen=True)
class LoggingConfig:
    enabled: bool
    max_bytes: int
    backup_count: int


@dataclass(frozen=True)
class Config:
    schema_version: int
    config_path: Path
    root: Path
    vault: Path
    workspaces: Path
    assets: Path
    private: Path
    runtime: Path
    staging: Path
    logs: Path
    inbox: Path
    processed: Path
    routing_runtime: Path
    control_plane: Path
    documents: Path
    media: Path
    resources: Path
    archive: Path
    quarantine: Path
    audit: Path
    manifests: Path
    recovery: Path
    tool_state: Path
    follow_symlinks: bool
    hash_mode: str
    max_workers: int
    default_mode: str
    verify_hash: bool
    preserve_timestamps: bool
    overwrite: bool
    git_enabled: bool
    max_tracked_file_mb: int
    default_visibility: str
    allow_ai_confidential: bool
    auto_threshold: float
    preserve_source: bool
    machine: MachineProfileConfig
    storage: StorageConfig
    codex_storage: CodexStorageConfig
    backup: BackupConfig
    rag: RagConfig
    llm: LlmConfig
    logging: LoggingConfig
    projects: tuple[Project, ...]
    rules: tuple[Rule, ...]


def _resolve(root: Path, value: str) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Configured path escapes KnowledgeVault root: {resolved}") from exc
    return resolved


def _require_mapping(raw: dict, key: str) -> dict:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{key}] must be a TOML table")
    return value


def load_config(path: str | Path, root_override: str | Path | None = None) -> Config:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    schema_version = int(raw.get("schema_version", 1))
    if schema_version not in {1, 2}:
        raise ValueError("Only configuration schema_version 1 or 2 is supported")

    configured_root = (
        str(root_override)
        if root_override is not None
        else os.environ.get("KNOWLEDGE_VAULT_ROOT", raw.get("root", "E:/KnowledgeVault"))
    )
    root_path = Path(os.path.expandvars(configured_root)).expanduser()
    if not root_path.is_absolute():
        root_path = config_path.parent / root_path
    root = root_path.resolve()

    paths = _require_mapping(raw, "paths")
    machine = _require_mapping(raw, "machine")
    storage = _require_mapping(raw, "storage")
    scan = _require_mapping(raw, "scan")
    migration = _require_mapping(raw, "migration")
    git = _require_mapping(raw, "git")
    privacy = _require_mapping(raw, "privacy")
    routing = _require_mapping(raw, "routing")
    backup = _require_mapping(raw, "backup")
    codex_storage = _require_mapping(raw, "codex_storage")
    rag = _require_mapping(raw, "rag")
    rag_embeddings = rag.get("embeddings", {})
    if not isinstance(rag_embeddings, dict):
        raise ValueError("[rag.embeddings] must be a TOML table")
    llm = _require_mapping(raw, "llm")
    logging = _require_mapping(raw, "logging")

    if schema_version == 2:
        path_defaults = {
            "vault": "20_Knowledge",
            "workspaces": "10_Projects",
            "assets": "50_Resources/ManagedAssets",
            "private": "60_Private",
            "runtime": "90_Runtime",
            "staging": "90_Runtime/Staging",
            "logs": "90_Runtime/Logs",
            "inbox": "70_Inbox",
            "processed": "80_Archive/ProcessedImports",
            "routing_runtime": "90_Runtime/Runs/Import",
            "control_plane": "00_System/ControlPlane",
            "documents": "30_Documents",
            "media": "40_Media",
            "resources": "50_Resources",
            "archive": "80_Archive",
            "quarantine": "99_Quarantine",
            "audit": "00_System/Audit",
            "manifests": "00_System/Manifests",
            "recovery": "00_System/Recovery",
            "tool_state": "00_System/ToolState",
        }
    else:
        path_defaults = {
            "vault": "Vault",
            "workspaces": "Workspaces",
            "assets": "Assets",
            "private": "Private",
            "runtime": "Runtime",
            "staging": "Staging",
            "logs": "Logs",
            "inbox": "Staging/Inbox",
            "processed": "Staging/Processed",
            "routing_runtime": "Runtime/routing",
            "control_plane": "Automation",
            "documents": "Vault",
            "media": "Assets",
            "resources": "Assets",
            "archive": "Vault/99_Archive",
            "quarantine": "Staging/Quarantine",
            "audit": "Logs/Audit",
            "manifests": "Runtime/runs",
            "recovery": "Vault/00_System",
            "tool_state": "Runtime",
        }
    resolved_paths = {
        key: _resolve(root, paths.get(key, default))
        for key, default in path_defaults.items()
    }
    vault = resolved_paths["vault"]
    workspaces = resolved_paths["workspaces"]
    assets = resolved_paths["assets"]
    private = resolved_paths["private"]
    runtime = resolved_paths["runtime"]
    staging = resolved_paths["staging"]
    logs = resolved_paths["logs"]

    projects = tuple(
        Project(
            code=item["code"],
            name=item["name"],
            aliases=tuple(item.get("aliases", [])),
            keywords=tuple(item.get("keywords", [])),
            source_hints=tuple(item.get("source_hints", [])),
        )
        for item in raw.get("projects", [])
    )
    rules = tuple(
        Rule(
            name=item["name"],
            extensions=tuple(
                suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
                for suffix in item.get("extensions", [])
            ),
            destination=item["destination"],
        )
        for item in raw.get("rules", [])
    )
    repository = Path(
        os.path.expandvars(
            backup.get(
                "repository",
                "F:/Backup_E/20_ResticRepository"
                if schema_version == 2
                else "E:/KnowledgeVault_Backup",
            )
        )
    ).expanduser().resolve()
    password_file = Path(
        os.path.expandvars(
            backup.get(
                "password_file",
                "%LOCALAPPDATA%/KnowledgeVault/restic-password.txt",
            )
        )
    ).expanduser().resolve()
    include_values = backup.get(
        "includes",
        (
            [
                ".knowledgevault-root.json",
                "vault.toml.local",
                "00_System/Config",
                "00_System/Audit",
                "00_System/Manifests",
                "00_System/Policies",
                "00_System/Recovery",
                "00_System/ToolState",
                "10_Projects",
                "20_Knowledge",
                "30_Documents",
                "40_Media",
                "50_Resources",
                "60_Private",
                "70_Inbox",
                "75_Exports",
                "80_Archive",
            ]
            if schema_version == 2
            else [
                "Vault",
                "Assets",
                "Private",
                "Workspaces",
                "vault.toml",
                "Runtime/runs",
                "Logs",
                "E:/Brain/Automation",
            ]
        ),
    )
    includes = tuple(
        (
            Path(os.path.expandvars(value)).expanduser().resolve()
            if Path(os.path.expandvars(value)).expanduser().is_absolute()
            else (root / value).resolve()
        )
        for value in include_values
    )
    critical_values = backup.get(
        "critical_paths",
        (
            [
                "00_System/Policies/STORAGE_LAYOUT.md",
                "00_System/Manifests/RESTORE_MAP.csv",
                ".knowledgevault-root.json",
            ]
            if schema_version == 2
            else ["Vault/00_System/Home.md", "vault.toml", "MANIFEST.md"]
        ),
    )
    if not isinstance(critical_values, list) or not all(
        isinstance(value, str) and value.strip() for value in critical_values
    ):
        raise ValueError("backup.critical_paths must be a non-empty string list")
    critical_paths = tuple(
        (
            Path(os.path.expandvars(value)).expanduser().resolve()
            if Path(os.path.expandvars(value)).expanduser().is_absolute()
            else (root / value).resolve()
        )
        for value in critical_values
    )

    config = Config(
        schema_version=schema_version,
        config_path=config_path,
        root=root,
        vault=vault,
        workspaces=workspaces,
        assets=assets,
        private=private,
        runtime=runtime,
        staging=staging,
        logs=logs,
        inbox=resolved_paths["inbox"],
        processed=resolved_paths["processed"],
        routing_runtime=resolved_paths["routing_runtime"],
        control_plane=resolved_paths["control_plane"],
        documents=resolved_paths["documents"],
        media=resolved_paths["media"],
        resources=resolved_paths["resources"],
        archive=resolved_paths["archive"],
        quarantine=resolved_paths["quarantine"],
        audit=resolved_paths["audit"],
        manifests=resolved_paths["manifests"],
        recovery=resolved_paths["recovery"],
        tool_state=resolved_paths["tool_state"],
        follow_symlinks=bool(scan.get("follow_symlinks", False)),
        hash_mode=str(scan.get("hash_mode", "duplicates")),
        max_workers=int(scan.get("max_workers", 4)),
        default_mode=str(migration.get("default_mode", "copy")),
        verify_hash=bool(migration.get("verify_hash", True)),
        preserve_timestamps=bool(migration.get("preserve_timestamps", True)),
        overwrite=bool(migration.get("overwrite", False)),
        git_enabled=bool(git.get("enabled", True)),
        max_tracked_file_mb=int(git.get("max_tracked_file_mb", 10)),
        default_visibility=str(privacy.get("default_visibility", "internal")),
        allow_ai_confidential=bool(privacy.get("allow_ai_confidential", False)),
        auto_threshold=float(routing.get("auto_threshold", 0.90)),
        preserve_source=bool(routing.get("preserve_source", True)),
        machine=MachineProfileConfig(
            name=str(machine.get("name", "default")),
            root_volume_label=str(machine.get("root_volume_label", "")),
            root_volume_serial=str(machine.get("root_volume_serial", "")),
            backup_volume_label=str(machine.get("backup_volume_label", "")),
            backup_volume_serial=str(machine.get("backup_volume_serial", "")),
            require_distinct_physical_disks=bool(
                machine.get("require_distinct_physical_disks", schema_version == 2)
            ),
        ),
        storage=StorageConfig(
            marker_file=str(storage.get("marker_file", ".knowledgevault-root.json")),
            allow_adopt=bool(storage.get("allow_adopt", False)),
            directories=tuple(storage.get("directories", STORAGE_DIRECTORIES_V2)),
        ),
        codex_storage=CodexStorageConfig(
            enabled=bool(codex_storage.get("enabled", schema_version == 2)),
            home=_resolve(
                root,
                codex_storage.get(
                    "home",
                    "60_Private/ToolState/Codex"
                    if schema_version == 2
                    else "Private/ToolState/Codex",
                ),
            ),
            projects=_resolve(
                root,
                codex_storage.get(
                    "projects", "10_Projects" if schema_version == 2 else "Workspaces"
                ),
            ),
            staging=_resolve(
                root,
                codex_storage.get(
                    "staging",
                    "90_Runtime/Staging/CodexStorageMigration"
                    if schema_version == 2
                    else "Staging/CodexStorageMigration",
                ),
            ),
            audit=_resolve(
                root,
                codex_storage.get(
                    "audit",
                    "00_System/Audit/CodexStorageMigration"
                    if schema_version == 2
                    else "Logs/Audit/CodexStorageMigration",
                ),
            ),
            cleanup_retention_days=int(
                codex_storage.get("cleanup_retention_days", 14)
            ),
        ),
        backup=BackupConfig(
            repository=repository,
            password_file=password_file,
            includes=includes,
            excludes=tuple(
                backup.get(
                    "excludes",
                    (
                        [
                            "**/.venv/**",
                            "**/__pycache__/**",
                            "**/node_modules/**",
                            "**/.git/objects/pack/*.keep",
                            "90_Runtime/**",
                            "99_Quarantine/**",
                        ]
                        if schema_version == 2
                        else [
                            "**/.venv/**",
                            "**/__pycache__/**",
                            "Runtime/cache/**",
                            "Runtime/db/**",
                            "Runtime/indexes/**",
                            "Staging/**",
                        ]
                    ),
                )
            ),
            keep_daily=int(backup.get("keep_daily", 14)),
            keep_weekly=int(backup.get("keep_weekly", 8)),
            keep_monthly=int(backup.get("keep_monthly", 12)),
            max_snapshot_age_days=int(backup.get("max_snapshot_age_days", 7)),
            critical_paths=critical_paths,
            require_all_includes=bool(backup.get("require_all_includes", True)),
            minimum_free_gib=int(backup.get("minimum_free_gib", 10)),
            readback_percent=int(backup.get("readback_percent", 100)),
        ),
        rag=RagConfig(
            enabled=bool(rag.get("enabled", True)),
            database=_resolve(
                root,
                rag.get(
                    "database",
                    "90_Runtime/Catalog/rag.sqlite3"
                    if schema_version == 2
                    else "Runtime/db/rag.sqlite3",
                ),
            ),
            chunk_max_chars=int(rag.get("chunk_max_chars", 1800)),
            chunk_overlap_chars=int(rag.get("chunk_overlap_chars", 200)),
            default_top_k=int(rag.get("default_top_k", 8)),
            embeddings=RagEmbeddingsConfig(
                enabled=bool(rag_embeddings.get("enabled", False)),
                provider=str(rag_embeddings.get("provider", "none")),
                model=str(rag_embeddings.get("model", "")),
                dimension=int(rag_embeddings.get("dimension", 0)),
            ),
        ),
        llm=LlmConfig(
            enabled=bool(llm.get("enabled", False)),
            provider=str(llm.get("provider", "ollama")),
            model=str(llm.get("model", "llama3.1:8b")),
            base_url=str(llm.get("base_url", "http://localhost:11434")),
            context_limit_tokens=int(llm.get("context_limit_tokens", 8192)),
            temperature=float(llm.get("temperature", 0.2)),
        ),
        logging=LoggingConfig(
            enabled=bool(logging.get("enabled", True)),
            max_bytes=int(logging.get("max_bytes", 1_048_576)),
            backup_count=int(logging.get("backup_count", 5)),
        ),
        projects=projects,
        rules=rules,
    )
    validate_config(config)
    return config


def validate_config(config: Config) -> None:
    if config.schema_version not in {1, 2}:
        raise ValueError("Unsupported configuration schema version")
    if not 0.0 <= config.auto_threshold <= 1.0:
        raise ValueError("routing.auto_threshold must be between 0 and 1")
    if config.hash_mode not in {"none", "duplicates", "selected", "all"}:
        raise ValueError("scan.hash_mode must be none, duplicates, selected, or all")
    if not 1 <= config.max_workers <= 64:
        raise ValueError("scan.max_workers must be between 1 and 64")
    if config.default_mode != "copy":
        raise ValueError("Only migration.default_mode = 'copy' is allowed")
    if not config.verify_hash:
        raise ValueError("migration.verify_hash must remain true")
    if config.overwrite:
        raise ValueError("migration.overwrite must remain false")
    if not config.preserve_source:
        raise ValueError("routing.preserve_source must remain true")
    if config.default_visibility not in {"public", "internal", "confidential", "restricted"}:
        raise ValueError("privacy.default_visibility is invalid")
    if config.max_tracked_file_mb < 1:
        raise ValueError("git.max_tracked_file_mb must be positive")
    if len({project.code.casefold() for project in config.projects}) != len(config.projects):
        raise ValueError("Project codes must be unique")
    if config.backup.repository == config.root:
        raise ValueError("Backup repository cannot be the KnowledgeVault root")
    if min(
        config.backup.keep_daily,
        config.backup.keep_weekly,
        config.backup.keep_monthly,
    ) < 1:
        raise ValueError("Backup retention values must be positive")
    if config.backup.max_snapshot_age_days < 1:
        raise ValueError("backup.max_snapshot_age_days must be positive")
    if config.backup.minimum_free_gib < 1:
        raise ValueError("backup.minimum_free_gib must be positive")
    if not 1 <= config.backup.readback_percent <= 100:
        raise ValueError("backup.readback_percent must be between 1 and 100")
    if not config.backup.critical_paths:
        raise ValueError("backup.critical_paths must not be empty")
    if config.rag.chunk_max_chars < 200:
        raise ValueError("rag.chunk_max_chars must be at least 200")
    if not 0 <= config.rag.chunk_overlap_chars < config.rag.chunk_max_chars:
        raise ValueError("rag.chunk_overlap_chars must be lower than chunk_max_chars")
    if not 1 <= config.rag.default_top_k <= 100:
        raise ValueError("rag.default_top_k must be between 1 and 100")
    if config.rag.embeddings.provider not in {"none", "ollama", "test"}:
        raise ValueError("rag.embeddings.provider must be none, ollama, or test")
    if config.rag.embeddings.enabled and config.rag.embeddings.provider == "none":
        raise ValueError("rag.embeddings.enabled requires a non-none provider")
    if config.rag.embeddings.dimension < 0:
        raise ValueError("rag.embeddings.dimension must not be negative")
    if (
        config.rag.embeddings.enabled
        and config.rag.embeddings.provider == "test"
        and config.rag.embeddings.dimension < 1
    ):
        raise ValueError("test embeddings require a positive dimension")
    if config.llm.provider != "ollama":
        raise ValueError("Only llm.provider = 'ollama' is supported")
    if not 512 <= config.llm.context_limit_tokens <= 1_000_000:
        raise ValueError("llm.context_limit_tokens must be between 512 and 1000000")
    validate_local_base_url(config.llm.base_url)
    if not 0 <= config.llm.temperature <= 2:
        raise ValueError("llm.temperature must be between 0 and 2")
    if config.logging.max_bytes < 1024:
        raise ValueError("logging.max_bytes must be at least 1024")
    if not 1 <= config.logging.backup_count <= 20:
        raise ValueError("logging.backup_count must be between 1 and 20")
    if config.codex_storage.cleanup_retention_days < 1:
        raise ValueError("codex_storage.cleanup_retention_days must be positive")
    codex_boundaries = (
        ("home", config.codex_storage.home, config.private),
        ("projects", config.codex_storage.projects, config.workspaces),
        ("staging", config.codex_storage.staging, config.staging),
        ("audit", config.codex_storage.audit, config.audit),
    )
    for name, path, boundary in codex_boundaries:
        try:
            path.relative_to(boundary)
        except ValueError as exc:
            raise ValueError(
                f"codex_storage.{name} must remain inside {boundary}"
            ) from exc
    marker = Path(config.storage.marker_file)
    if marker.is_absolute() or ".." in marker.parts or len(marker.parts) != 1:
        raise ValueError("storage.marker_file must be a root-level filename")
    if config.schema_version == 2:
        if not config.storage.directories:
            raise ValueError("storage.directories must not be empty for schema v2")
        for value in config.storage.directories:
            candidate = Path(value)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError(f"Unsafe storage directory: {value}")
        if config.root in config.backup.repository.parents:
            raise ValueError("Backup repository cannot be inside the KnowledgeVault root")


def render_runtime_config(config: Config) -> str:
    def rel(path: Path) -> str:
        return path.relative_to(config.root).as_posix()

    def backup_path(path: Path) -> str:
        try:
            return path.relative_to(config.root).as_posix()
        except ValueError:
            return path.as_posix()

    extra_paths = ""
    machine_and_storage = ""
    if config.schema_version == 2:
        machine_and_storage = f'''
[machine]
name = {json.dumps(config.machine.name, ensure_ascii=False)}
root_volume_label = {json.dumps(config.machine.root_volume_label, ensure_ascii=False)}
root_volume_serial = {json.dumps(config.machine.root_volume_serial, ensure_ascii=False)}
backup_volume_label = {json.dumps(config.machine.backup_volume_label, ensure_ascii=False)}
backup_volume_serial = {json.dumps(config.machine.backup_volume_serial, ensure_ascii=False)}
require_distinct_physical_disks = {str(config.machine.require_distinct_physical_disks).lower()}

[storage]
marker_file = {json.dumps(config.storage.marker_file, ensure_ascii=False)}
allow_adopt = {str(config.storage.allow_adopt).lower()}
directories = {json.dumps(list(config.storage.directories), ensure_ascii=False)}
'''
        extra_paths = f'''
control_plane = "{rel(config.control_plane)}"
documents = "{rel(config.documents)}"
media = "{rel(config.media)}"
resources = "{rel(config.resources)}"
archive = "{rel(config.archive)}"
quarantine = "{rel(config.quarantine)}"
audit = "{rel(config.audit)}"
manifests = "{rel(config.manifests)}"
recovery = "{rel(config.recovery)}"
tool_state = "{rel(config.tool_state)}"
'''

    text = f'''schema_version = {config.schema_version}
root = "{config.root.as_posix()}"
{machine_and_storage}

[paths]
vault = "{rel(config.vault)}"
workspaces = "{rel(config.workspaces)}"
assets = "{rel(config.assets)}"
private = "{rel(config.private)}"
runtime = "{rel(config.runtime)}"
staging = "{rel(config.staging)}"
logs = "{rel(config.logs)}"
inbox = "{rel(config.inbox)}"
processed = "{rel(config.processed)}"
routing_runtime = "{rel(config.routing_runtime)}"
{extra_paths}

[codex_storage]
enabled = {str(config.codex_storage.enabled).lower()}
home = "{rel(config.codex_storage.home)}"
projects = "{rel(config.codex_storage.projects)}"
staging = "{rel(config.codex_storage.staging)}"
audit = "{rel(config.codex_storage.audit)}"
cleanup_retention_days = {config.codex_storage.cleanup_retention_days}

[scan]
follow_symlinks = false
hash_mode = "{config.hash_mode}"
max_workers = {config.max_workers}

[migration]
default_mode = "copy"
verify_hash = true
preserve_timestamps = {str(config.preserve_timestamps).lower()}
overwrite = false

[git]
enabled = {str(config.git_enabled).lower()}
max_tracked_file_mb = {config.max_tracked_file_mb}

[privacy]
default_visibility = "{config.default_visibility}"
allow_ai_confidential = {str(config.allow_ai_confidential).lower()}

[routing]
auto_threshold = {config.auto_threshold:.2f}
preserve_source = true

[backup]
repository = {json.dumps(config.backup.repository.as_posix(), ensure_ascii=False)}
password_file = {json.dumps(config.backup.password_file.as_posix(), ensure_ascii=False)}
includes = {json.dumps([path.as_posix() for path in config.backup.includes], ensure_ascii=False)}
excludes = {json.dumps(list(config.backup.excludes), ensure_ascii=False)}
keep_daily = {config.backup.keep_daily}
keep_weekly = {config.backup.keep_weekly}
keep_monthly = {config.backup.keep_monthly}
max_snapshot_age_days = {config.backup.max_snapshot_age_days}
critical_paths = {json.dumps([backup_path(path) for path in config.backup.critical_paths], ensure_ascii=False)}
require_all_includes = {str(config.backup.require_all_includes).lower()}
minimum_free_gib = {config.backup.minimum_free_gib}
readback_percent = {config.backup.readback_percent}

[rag]
enabled = {str(config.rag.enabled).lower()}
database = {json.dumps(config.rag.database.relative_to(config.root).as_posix(), ensure_ascii=False)}
chunk_max_chars = {config.rag.chunk_max_chars}
chunk_overlap_chars = {config.rag.chunk_overlap_chars}
default_top_k = {config.rag.default_top_k}

[rag.embeddings]
enabled = {str(config.rag.embeddings.enabled).lower()}
provider = {json.dumps(config.rag.embeddings.provider, ensure_ascii=False)}
model = {json.dumps(config.rag.embeddings.model, ensure_ascii=False)}
dimension = {config.rag.embeddings.dimension}

[llm]
enabled = {str(config.llm.enabled).lower()}
provider = {json.dumps(config.llm.provider, ensure_ascii=False)}
model = {json.dumps(config.llm.model, ensure_ascii=False)}
base_url = {json.dumps(config.llm.base_url, ensure_ascii=False)}
context_limit_tokens = {config.llm.context_limit_tokens}
temperature = {config.llm.temperature}

[logging]
enabled = {str(config.logging.enabled).lower()}
max_bytes = {config.logging.max_bytes}
backup_count = {config.logging.backup_count}
'''
    for project in config.projects:
        text += f'''
[[projects]]
code = {json.dumps(project.code, ensure_ascii=False)}
name = {json.dumps(project.name, ensure_ascii=False)}
aliases = {json.dumps(list(project.aliases), ensure_ascii=False)}
keywords = {json.dumps(list(project.keywords), ensure_ascii=False)}
source_hints = {json.dumps(list(project.source_hints), ensure_ascii=False)}
'''
    for rule in config.rules:
        text += f'''
[[rules]]
name = {json.dumps(rule.name, ensure_ascii=False)}
extensions = {json.dumps(list(rule.extensions), ensure_ascii=False)}
destination = {json.dumps(rule.destination, ensure_ascii=False)}
'''
    return text
