from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
import shutil

from .config import Config, render_runtime_config
from .metadata import new_uid, today


DIRECTORIES = (
    "Vault/00_System/Decisions",
    "Vault/01_Inbox/Notes",
    "Vault/01_Inbox/Imports",
    "Vault/01_Inbox/Meetings",
    "Vault/02_Projects/Active",
    "Vault/02_Projects/Paused",
    "Vault/02_Projects/Completed",
    "Vault/03_Areas",
    "Vault/04_Knowledge/Concepts",
    "Vault/04_Knowledge/How_To",
    "Vault/04_Knowledge/Research",
    "Vault/04_Knowledge/Glossary",
    "Vault/04_Knowledge/MOCs",
    "Vault/05_Resources/Sources",
    "Vault/05_Resources/Reading",
    "Vault/05_Resources/Tools",
    "Vault/06_Records/Meetings",
    "Vault/06_Records/Decisions",
    "Vault/06_Records/Postmortems",
    "Vault/06_Records/Session_Logs",
    "Vault/90_Templates",
    "Vault/91_Views",
    "Vault/99_Archive",
    "Workspaces",
    "Assets/Projects",
    "Assets/Shared",
    "Assets/Unassigned",
    "Private",
    "Runtime/db",
    "Runtime/indexes",
    "Runtime/cache",
    "Runtime/graph",
    "Runtime/locks",
    "Runtime/rag",
    "Runtime/runs",
    "Runtime/routing",
    "Staging/Inbox",
    "Staging/Processed",
    "Staging/WikiDrafts",
    "Logs",
)


def _frontmatter(kind: str, title: str, status: str = "active") -> str:
    return f"""---
schema_version: 1
uid: {new_uid()}
type: {kind}
title: "{title}"
status: {status}
created: {today()}
updated: {today()}
tags: []
aliases: []
visibility: internal
---
"""


def _template(kind: str, title: str, status: str, body: str) -> str:
    return f"""---
schema_version: 1
uid: "{{{{uid}}}}"
type: {kind}
title: "{title}"
status: {status}
created: "{{{{date}}}}"
updated: "{{{{date}}}}"
tags: []
aliases: []
visibility: internal
---

# {title}

{body.strip()}
"""


def managed_files(config: Config) -> dict[str, str]:
    system = {
        "README.md": """# KnowledgeVault

Local-first система для проєктів, знань, документів і безпечної автоматизації.

- В Obsidian відкривайте лише `Vault/`.
- Код зберігайте у `Workspaces/`.
- Великі вкладення — в `Assets/`.
- Конфіденційні матеріали — в `Private/`.
- Нерозібрані файли — в `Staging/Inbox/`.

Детальні правила: `Vault/00_System/Home.md`.
""",
        "MANIFEST.md": """# KnowledgeVault Manifest

Структуру створено командою `vaultctl init`.

Канонічні дані: Markdown у `Vault/`, код у `Workspaces/`, вкладення в `Assets/`.
`Runtime/` є похідним шаром і може перебудовуватися.
""",
        "Vault/00_System/README.md": _frontmatter("index", "Системний шар") + """
# Системний шар

Правила, контекст, проєкти, пам'ять і політики KnowledgeVault.
""",
        "Vault/00_System/Home.md": _frontmatter("index", "KnowledgeVault Home") + """
# KnowledgeVault

## Початок роботи

1. Перегляньте [[Context]].
2. Відкрийте [[Projects]].
3. Перейдіть до картки активного проєкту.

## Навігація

- `01_Inbox` — необроблені матеріали.
- `02_Projects` — проєкти.
- `03_Areas` — постійні сфери відповідальності.
- `04_Knowledge` — знання та дослідження.
- `05_Resources` — зовнішні джерела.
- `06_Records` — рішення, зустрічі та підсумки.
""",
        "Vault/00_System/Context.md": _frontmatter("context", "Поточний контекст") + """
# Поточний контекст

## Фокус

- Заповнити після ініціалізації.

## Пріоритети

- [ ] Визначити три головні пріоритети.
""",
        "Vault/00_System/Projects.md": _frontmatter("index", "Проєкти") + """
# Проєкти

## Активні

Поки немає.

## На паузі

Поки немає.
""",
        "Vault/00_System/Memory.md": _frontmatter("memory", "Пам'ять") + """
# Пам'ять

Індекс стабільних фактів і доменних файлів пам'яті.
""",
        "Vault/00_System/Conventions.md": _frontmatter("document", "Правила іменування") + """
# Правила іменування

- Технічні папки й поля metadata — англійською.
- Зміст документів може бути українською.
- Дати — `YYYY-MM-DD`.
- Шляхи в metadata — відносні до root.
- Не дублюйте type, status і шлях у tags.
""",
        "Vault/00_System/Metadata_Schema.md": _frontmatter("document", "Схема метаданих") + """
# Схема метаданих

Обов'язкові поля: `schema_version`, `uid`, `type`, `title`, `status`,
`created`, `updated`, `tags`, `aliases`, `visibility`.

Формальна схема зберігається в `Automation/metadata.schema.json`.
""",
        "Vault/00_System/Security_Policy.md": _frontmatter("document", "Політика безпеки") + """
# Політика безпеки

- Не зберігати секрети у Markdown.
- `Private/` не доступний AI автоматично.
- Не видаляти source після копіювання.
- Не виконувати макроси, скрипти чи архіви під час аналізу.
""",
        "Vault/00_System/Backup_Policy.md": _frontmatter("document", "Політика резервного копіювання") + """
# Політика резервного копіювання

Використовуйте правило 3-2-1 та щомісяця перевіряйте тестове відновлення.
Git і синхронізація не замінюють backup.
""",
        "Vault/00_System/AI_Policy.md": _frontmatter("document", "Політика AI") + """
# Політика AI

## Tier 1

`Context.md`, `Projects.md`, `Memory.md` і картка поточного проєкту.

## Заборонено автоматично

`Private/`, `restricted`, секрети, токени, фінансові та ідентифікаційні документи.
""",
        "Vault/91_Views/Projects.base": """filters:
  and:
    - 'type == "project"'
properties:
  status:
    displayName: Status
  updated:
    displayName: Updated
views:
  - type: table
    name: Active projects
    filters:
      and:
        - 'status == "active"'
    order:
      - file.name
      - status
      - updated
""",
        "Vault/91_Views/Records.base": """filters:
  or:
    - 'type == "meeting"'
    - 'type == "decision"'
    - 'type == "postmortem"'
    - 'type == "session-log"'
views:
  - type: table
    name: Records
    order:
      - file.name
      - type
      - status
      - updated
""",
        "Vault/91_Views/Inbox.base": """filters:
  and:
    - 'file.inFolder("01_Inbox")'
views:
  - type: table
    name: Inbox
    order:
      - file.name
      - file.mtime
      - status
""",
        "Vault/91_Views/Home.md": _frontmatter("index", "KnowledgeVault Dashboard") + """# KnowledgeVault Dashboard

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

Private, confidential and restricted materials are intentionally excluded from AI/RAG/Graph dashboards.
""",
        "Vault/91_Views/Search.md": _frontmatter("index", "Search Dashboard") + """# Search

```powershell
cd <Brain>\\Automation
.\\vaultctl.ps1 search "knowledge"
.\\vaultctl.ps1 rag sources "ризики міграції"
.\\vaultctl.ps1 ask "які головні ризики KnowledgeVault?" --sources-only
```
""",
        "Vault/91_Views/Graph.md": _frontmatter("index", "Graph Dashboard") + """# Graph

```powershell
cd <Brain>\\Automation
.\\vaultctl.ps1 graph build
.\\vaultctl.ps1 graph stats
.\\vaultctl.ps1 graph export --format mermaid
```
""",
    }
    templates = {
        "Project.md": _template("project", "Назва проєкту", "active", """
## Результат
## Межі та non-goals
## Поточний статус
## Наступна дія
## Блокери
## Workspace та assets
## Етапи
## Ризики
## Рішення
## Журнал змін
"""),
        "Area.md": _template("area", "Назва області", "active", "## Призначення\n## Стандарти\n## Пов'язані проєкти"),
        "Note.md": _template("note", "Назва нотатки", "active", "## Резюме\n## Зміст\n## Зв'язки"),
        "Research.md": _template("research", "Тема дослідження", "draft", "## Питання\n## Джерела\n## Висновки\n## Обмеження"),
        "How_To.md": _template("how-to", "Назва інструкції", "draft", "## Передумови\n## Кроки\n## Перевірка\n## Відкат"),
        "Resource.md": _template("resource", "Назва ресурсу", "unread", "## Джерело\n## Резюме\n## Корисність"),
        "Decision.md": _template("decision", "ADR: назва рішення", "proposed", "## Контекст\n## Рішення\n## Альтернативи\n## Наслідки\n## Supersedes\n## Review date"),
        "Meeting.md": _template("meeting", "Назва зустрічі", "raw", "## TL;DR\n## Рішення\n## Action items\n## Факти\n## Відкриті питання\n## Посилання"),
        "Postmortem.md": _template("postmortem", "Назва postmortem", "draft", "## Timeline\n## Очікування та факт\n## Root causes\n## Повторити\n## Не повторювати\n## Corrective actions"),
        "Session_Log.md": _template("session-log", "Журнал сесії", "active", "## Зроблено\n## Рішення\n## Проблеми\n## Наступний крок"),
        "Asset.md": _template("asset", "Картка вкладення", "active", "## Файл\n## SHA-256\n## Походження\n## Пов'язаний проєкт"),
        "Person.md": _template("person", "Ім'я людини", "active", "## Контекст\n## Роль\n## Взаємодії\n## Примітки"),
    }
    for name, content in templates.items():
        system[f"Vault/90_Templates/{name}"] = content
    system["vault.toml"] = render_runtime_config(config)
    return system


@dataclass
class InitResult:
    created: list[str]
    skipped: list[str]
    updated: list[str]


def initialize(
    config: Config,
    *,
    dry_run: bool = False,
    force_template_update: bool = False,
) -> InitResult:
    result = InitResult([], [], [])
    for relative in DIRECTORIES:
        path = config.root / relative
        if path.exists():
            result.skipped.append(relative + "/")
        else:
            result.created.append(relative + "/")
            if not dry_run:
                path.mkdir(parents=True, exist_ok=False)

    for relative, content in managed_files(config).items():
        path = config.root / relative
        if not path.exists():
            result.created.append(relative)
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
            continue
        can_update = force_template_update and relative.startswith("Vault/90_Templates/")
        if not can_update:
            result.skipped.append(relative)
            continue
        old = path.read_text(encoding="utf-8")
        new = content.rstrip() + "\n"
        if old == new:
            result.skipped.append(relative)
            continue
        result.updated.append(relative)
        print("".join(unified_diff(old.splitlines(True), new.splitlines(True), fromfile=str(path), tofile=str(path))))
        if not dry_run:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            shutil.copy2(path, path.with_name(f"{path.name}.backup-{stamp}"))
            path.write_text(new, encoding="utf-8", newline="\n")
    return result
