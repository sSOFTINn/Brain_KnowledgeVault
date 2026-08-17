from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import os

from .config import Config
from .storage import validate_storage_marker, write_audit_event


@dataclass(frozen=True)
class ProfileItem:
    path: str
    owner: str
    classification: str
    supported_control: str
    exists: bool
    size_bytes: int | None
    note: str


POLICY = {
    ".cache": ("multiple applications", "disposable-cache", "application-specific", "Rebuild instead of relocating wholesale."),
    ".codex": ("Codex", "supported-redirect", "CODEX_HOME", "Back up encrypted; never commit auth or session data."),
    ".copilot": ("GitHub Copilot", "manual-review", "none confirmed", "Keep on C until the format and supported path are confirmed."),
    ".dotnet": (".NET", "must-stay-on-C", "DOTNET_CLI_HOME only for supported state", "Review global tools before any change."),
    ".ipython": ("IPython", "supported-redirect", "IPYTHONDIR", "Move only profiles and configuration through the supported variable."),
    ".nuget": ("NuGet", "supported-redirect", "NUGET_PACKAGES", "Redirect packages; keep NuGet.Config in its supported location."),
    ".vscode": ("Visual Studio Code", "manual-review", "--extensions-dir / supported profiles", "Export settings and extension list before changes."),
    ".vscode-shared": ("unknown", "manual-review", "none confirmed", "Identify the owning application first."),
}


def _directory_size(path: Path) -> int | None:
    total = 0
    stack = [path]
    try:
        while stack:
            current = stack.pop()
            for child in current.iterdir():
                if child.is_symlink():
                    continue
                if child.is_dir():
                    stack.append(child)
                elif child.is_file():
                    total += child.stat().st_size
    except OSError:
        return None
    return total


def audit_windows_profile(
    config: Config,
    *,
    home: str | Path | None = None,
) -> tuple[Path, list[ProfileItem]]:
    validate_storage_marker(config)
    profile = Path(home or os.environ.get("USERPROFILE", Path.home())).expanduser().resolve()
    items: list[ProfileItem] = []
    for name, (owner, classification, control, note) in POLICY.items():
        path = profile / name
        items.append(
            ProfileItem(
                path=str(path),
                owner=owner,
                classification=classification,
                supported_control=control,
                exists=path.exists(),
                size_bytes=_directory_size(path) if path.is_dir() else None,
                note=note,
            )
        )
    output = config.manifests / "windows-profile-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "profile": str(profile),
        "items": [asdict(item) for item in items],
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_audit_event(config, "windows-profile-audit", {"output": str(output)})
    return output, items
