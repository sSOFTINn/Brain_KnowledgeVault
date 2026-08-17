# Карта проєкту

## Призначення і користувачі

KnowledgeVault — local-first система керування знаннями для одного Windows-користувача та локальних AI-інструментів. Основні сценарії: Obsidian-нотатки, контрольована міграція файлів, локальний FTS5/RAG-пошук, wiki drafts, graph export і encrypted backup.

## Структура

```text
E:\Brain\
├── plans.md / USER_GUIDE.md / README.md       специфікація та UX
├── Ризики\                                    попередні аналітичні матеріали
└── Automation\
    ├── vaultctl.ps1 / run_tests.ps1           Windows entrypoints
    ├── vault.toml(.example)                   runtime policy/config
    ├── pyproject.toml                         Python package metadata
    ├── vaultctl\                              Python control plane
    ├── tests\                                 51 unit/integration tests
    └── docs\                                  ADR і runbooks

E:\KnowledgeVault\
├── Vault\                                     Obsidian Markdown
├── Assets\ / Workspaces\ / Private\          дані за класами
├── Staging\                                   inbox і wiki drafts
└── Runtime\                                   rebuildable DB/cache/runs/graph

E:\KnowledgeVault_Backup\                     encrypted restic repository
```

## Точки входу

- PowerShell: `Automation\vaultctl.ps1`, `Automation\run_tests.ps1`, `Automation\install.ps1`.
- Python: `vaultctl.__main__` -> `vaultctl.cli:main`.
- CLI: init, doctor, validate, scan, plan, review, apply, report, verify, cleanup-plan, index/search, extract/suggest, backup, rag/ask, wiki, graph.

## Модулі

| Модуль | Відповідальність |
|---|---|
| `config.py` | TOML parsing, safe defaults, path containment |
| `scaffold.py`, `validator.py`, `doctor.py` | bootstrap та health checks |
| `scanner.py`, `planner.py` | read-only inventory і deterministic plan |
| `router.py`, `migrator.py`, `operations.py` | approval, verified copy, journal, verify |
| `indexer.py`, `schema.py` | catalog SQLite/FTS5, atomic rebuild |
| `extractor.py`, `suggestions.py` | safe extraction і runtime-only suggestions |
| `policy.py` | visibility/privacy decisions |
| `rag/chunker.py`, `rag/store.py`, `rag/embeddings.py` | chunks, FTS5, vector storage |
| `ask.py`, `wiki.py`, `graph.py`, `dashboard.py` | intelligence/draft/graph layer |
| `backup.py` | restic wrapper, password ACL, retention, restore drill |
| `locks.py` | filesystem lock для writers |

## Критичні потоки даних

```text
Source folder -> scan -> plan -> manual approval -> copy.partial
-> SHA-256 verify -> atomic rename -> append-only journal

Vault/Assets -> visibility policy -> extract/index/RAG -> SQLite FTS5
-> sources-only або optional Ollama

Vault + Automation -> restic encrypted snapshot -> check -> restore drill
```

## Бази й storage

- `Runtime/db/catalog.sqlite3`: derived catalog/FTS5; відновлюється rebuild.
- `Runtime/db/rag.sqlite3`: derived chunks/FTS5/vectors; відновлюється rebuild.
- `Runtime/cache/extracted`: derived text cache.
- `Runtime/runs`, routing journals і approvals: операційний аудит-трейл.
- Restic repository: зашифрований backup; пароль поза Vault/Git.

## Зовнішні інтеграції

- restic 0.19.0 через subprocess без shell.
- optional Ollama HTTP API.
- Obsidian через файлову структуру та `.obsidian`.
- Git/GitHub для коду й документації, але не всього Vault.

## Межі довіри

- Source та Staging є недовіреними файловими входами.
- Frontmatter/sidecars визначають visibility, тому parser/policy — security boundary.
- `vault.toml` є privileged local config.
- Ollama endpoint — network trust boundary.
- Restic password file — secret boundary.

