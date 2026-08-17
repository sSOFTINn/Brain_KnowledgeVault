from __future__ import annotations

from pathlib import Path

from .config import Config
from .metadata import new_uid, today
from .rag.store import latest_manifest


def _frontmatter(title: str) -> str:
    return f"""---
schema_version: 1
uid: {new_uid()}
type: index
title: "{title}"
status: active
created: {today()}
updated: {today()}
tags:
  - dashboard
aliases: []
visibility: internal
---

"""


def write_dashboard(config: Config) -> list[Path]:
    views = config.vault / "91_Views"
    views.mkdir(parents=True, exist_ok=True)
    manifest = latest_manifest(config)
    graph_dir = config.runtime / "graph"
    files = [
        views / "Home.md",
        views / "Search.md",
        views / "Graph.md",
    ]
    files[0].write_text(
        _frontmatter("KnowledgeVault Dashboard") + f"""# KnowledgeVault Dashboard

## Робочі команди

```powershell
cd <Brain>\\Automation
.\\vaultctl.ps1 validate
.\\vaultctl.ps1 index --rebuild
.\\vaultctl.ps1 extract --rebuild
.\\vaultctl.ps1 rag rebuild
.\\vaultctl.ps1 ask "питання" --sources-only
.\\vaultctl.ps1 graph build
.\\vaultctl.ps1 backup run
```

## RAG status

- Last RAG run: `{manifest.get('run_id', 'not built')}`
- Sources: `{manifest.get('sources', 0)}`
- Chunks: `{manifest.get('chunks', 0)}`

## Views

- [[Search]]
- [[Graph]]
- `Projects.base`
- `Inbox.base`
- `Records.base`

Private, confidential and restricted materials are intentionally excluded from AI/RAG/Graph dashboards.
""",
        encoding="utf-8",
        newline="\n",
    )
    files[1].write_text(
        _frontmatter("Search Dashboard") + """# Search

## Full-text catalog

```powershell
cd <Brain>\\Automation
.\\vaultctl.ps1 index --rebuild
.\\vaultctl.ps1 search "knowledge"
```

## RAG sources

```powershell
.\\vaultctl.ps1 rag sources "ризики міграції"
.\\vaultctl.ps1 ask "які головні ризики KnowledgeVault?" --sources-only
```
""",
        encoding="utf-8",
        newline="\n",
    )
    files[2].write_text(
        _frontmatter("Graph Dashboard") + f"""# Graph

## Build/export

```powershell
cd <Brain>\\Automation
.\\vaultctl.ps1 graph build
.\\vaultctl.ps1 graph stats
.\\vaultctl.ps1 graph export --format json
.\\vaultctl.ps1 graph export --format mermaid
```

## Artifacts

- JSON: `Runtime/graph/graph.json`
- Mermaid: `Runtime/graph/graph.mmd`
- GraphML: `Runtime/graph/graph.graphml`
""",
        encoding="utf-8",
        newline="\n",
    )
    return files
