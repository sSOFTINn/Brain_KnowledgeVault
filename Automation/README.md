# KnowledgeVault Automation

## Storage Platform v2

Для нових сховищ використовуйте `vault.toml.example` зі
`schema_version = 2` та локальний ignored `vault.toml.local`.

Нові команди:

```powershell
.\vaultctl.ps1 bootstrap --config .\vault.toml.local --dry-run
.\vaultctl.ps1 storage --config E:\KnowledgeVault\vault.toml.local audit --json
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local plan --source E:\Brain
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local preflight
.\vaultctl.ps1 restore --config E:\KnowledgeVault\vault.toml.local drill
.\vaultctl.ps1 windows-data --config E:\KnowledgeVault\vault.toml.local audit
```

`init/scan/plan/review/apply` залишаються для legacy/file migration. Для
перенесення Git використовуйте repository-aware `import`, який включає
`.git`, untracked files, manifests, SHA-256 і `git fsck`.

Ця папка є самодостатнім control plane для KnowledgeVault. Вона містить конфігурацію, CLI, metadata schema, launcher-скрипти й тести.

Незалежний аудит у `..\audit` є історичним snapshot стану на 2026-07-11.
Актуальна матриця KV-001–KV-018 і acceptance evidence:
[`../AUDIT_STATUS.md`](../AUDIT_STATUS.md). Audit-файли не переписуються після
remediation.

## Що реалізовано

```text
init      створення каркаса KnowledgeVault
doctor    перевірка Python, Git, SQLite, конфігурації та безпеки
validate  перевірка структури, YAML metadata, UID, links і Windows paths
scan      read-only inventory з JSONL, CSV, summary та Markdown report
plan      deterministic migration plan з duplicate/collision analysis
route     створення immutable плану для Staging/Inbox
review    перегляд і append-only затвердження маршруту
apply     dry-run або безпечне copy + SHA-256 verify
report    підсумковий Markdown-звіт конкретного migration run
verify    повторна перевірка destination size і SHA-256 за journal
cleanup-plan список source-кандидатів після retention; без видалення
extract   безпечне локальне вилучення тексту з дозволених assets
index     atomic rebuild та integrity check SQLite/FTS5 catalog
search    пошук українською й англійською через FTS5
suggest   runtime-only MOC, stale і duplicate recommendations
backup    encrypted restic init/run/check/snapshots/restore-drill
rag       SQLite/FTS5 RAG sources layer: build/rebuild/sources/search
ask       sources-only відповіді або optional local Ollama answer mode
wiki      review-only wiki drafts: suggest/draft/approve/apply dry-run
graph     rebuildable graph build/neighbors/export/stats
```

Автоматизація ніколи не видаляє і не переміщує source. `apply` виконує лише копіювання затверджених записів.
RAG/LLM/Wiki/Graph використовують єдину visibility policy: `Private/`, `restricted` і `confidential` не читаються.

Обидва migration pipelines використовують один `verified_copy`: повторна
перевірка source, `.partial`, size/SHA-256 verification, publish без overwrite
та cleanup при помилці. `migration.preserve_timestamps` реально перемикає
`copy2`/`copyfile`.

## Структура

```text
Automation/
├── vaultctl/                 Python-пакет
├── tests/                    unit та integration tests
├── docs/                     runbooks, checklist та ADR
├── metadata.schema.json      формальна metadata schema
├── vault.toml                робочий локальний конфіг
├── vault.toml.example        приклад конфігурації
├── requirements.lock         точні runtime-залежності
├── install.ps1               встановлення у .venv
├── vaultctl.ps1              єдина точка запуску
├── run_tests.ps1             запуск тестів
└── EXECUTION_PROMPT.md       промпт для автономного виконання проєкту
```

## Встановлення

```powershell
cd E:\Brain\Automation
.\install.ps1
```

Якщо PowerShell блокує локальні скрипти:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Той самий process-local спосіб використовуйте для інших launcher-скриптів,
не змінюючи системну Execution Policy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\vaultctl.ps1 doctor
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
```

`install.ps1` встановлює точні версії з `requirements.lock`; Windows CI
перевіряє Python 3.11 і 3.14. Деталі оновлення залежностей і журналювання:
[`docs/INSTALL_AND_LOGGING_RUNBOOK.md`](docs/INSTALL_AND_LOGGING_RUNBOOK.md).

CLI записує лише технічні події до `E:\KnowledgeVault\Logs\vaultctl.jsonl`:
команда, UTC timestamp, PID, exit code і тривалість. Аргументи, search/ask text,
відповіді, exception messages, tokens і вміст файлів не журналюються. JSONL
автоматично ротуються згідно з `[logging]` у `vault.toml`.

## Перша перевірка

```powershell
.\vaultctl.ps1 doctor
.\vaultctl.ps1 init --dry-run
.\run_tests.ps1
```

## Створення KnowledgeVault

За замовчуванням використовується `E:\KnowledgeVault`, вказаний у `vault.toml`.

```powershell
.\vaultctl.ps1 init
.\vaultctl.ps1 doctor
.\vaultctl.ps1 validate
```

Повторний `init` не перезаписує наявні файли. Оновлення керованих шаблонів дозволене лише окремо:

```powershell
.\vaultctl.ps1 init --force-template-update
```

Перед оновленням друкується diff і створюється backup старого шаблону.

## Read-only inventory

Скануйте лише конкретну папку, а не весь диск:

```powershell
.\vaultctl.ps1 scan "E:\SomeFolder"
```

Доступні режими хешування:

```powershell
.\vaultctl.ps1 scan "E:\SomeFolder" --hash-mode none
.\vaultctl.ps1 scan "E:\SomeFolder" --hash-mode duplicates
.\vaultctl.ps1 scan "E:\SomeFolder" --hash-mode all
```

`scan.max_workers` визначає фактичну кількість паралельних hash workers і
записується до `run.json`; обхід директорій залишається детермінованим і
read-only.

Результат кожного запуску:

```text
E:\KnowledgeVault\Runtime\runs\<run-id>\
├── run.json
├── inventory.jsonl
├── inventory.csv
├── errors.jsonl
├── summary.json
└── report.md
```

Scanner не записує нічого в source, не обходить symlinks/reparse points,
не гідрує cloud placeholders і пропускає системні та dependency-папки.
Сканування кореня диска заблоковане без `--allow-system-root`.

## Migration plan і verified copy

Після перегляду scan report створіть план:

```powershell
.\vaultctl.ps1 plan --run "<scan-run-id>"
```

У run directory з'являться `migration_plan.jsonl`, `migration_plan.csv`,
`migration_plan.md` і `conflicts.md`.

Low-confidence, privacy-risk і name-collision записи завжди отримують
`manual` та не виконуються автоматично. Початковий JSONL-план є immutable.

```powershell
.\vaultctl.ps1 review `
  --plan "E:\KnowledgeVault\Runtime\runs\<run-id>\migration_plan.jsonl"

.\vaultctl.ps1 review `
  --plan "E:\KnowledgeVault\Runtime\runs\<run-id>\migration_plan.jsonl" `
  --approve "<row-id>" `
  --destination "Assets/Projects/PRJ-2026-001/docs/example.pdf" `
  --note "Перевірено вручну"
```

Dry-run:

```powershell
.\vaultctl.ps1 apply `
  --plan "E:\KnowledgeVault\Runtime\runs\<run-id>\migration_plan.jsonl"
```

Verified copy виконується лише з `--execute`. Створюються append-only journal,
verification log, cumulative summary і rollback manifest. Rollback manifest
ніколи не виконує видалення автоматично.

## Безпечний routing

Додайте файли тільки в:

```text
E:\KnowledgeVault\Staging\Inbox
```

Створіть план:

```powershell
.\vaultctl.ps1 route
```

Перегляньте план:

```powershell
.\vaultctl.ps1 review --plan "E:\KnowledgeVault\Runtime\routing\<run-id>\route_plan.jsonl"
```

Затвердьте неоднозначний запис:

```powershell
.\vaultctl.ps1 review `
  --plan "E:\KnowledgeVault\Runtime\routing\<run-id>\route_plan.jsonl" `
  --approve "<route-id>" `
  --destination "Assets/Unassigned/example.pdf"
```

Approval записується окремо; початковий план не змінюється.

Dry-run:

```powershell
.\vaultctl.ps1 apply --plan "E:\KnowledgeVault\Runtime\routing\<run-id>\route_plan.jsonl"
```

Копіювання:

```powershell
.\vaultctl.ps1 apply `
  --plan "E:\KnowledgeVault\Runtime\routing\<run-id>\route_plan.jsonl" `
  --execute
```

Алгоритм: containment check → перевірка незмінності source → SHA-256 → `.partial` → повторний SHA-256 → atomic rename. Source залишається на місці.

## SQLite catalog і пошук

Каталог є похідним і повністю rebuildable:

```powershell
.\vaultctl.ps1 index --rebuild
.\vaultctl.ps1 index --integrity
.\vaultctl.ps1 search "проєкти"
.\vaultctl.ps1 search "knowledge" --limit 10
```

База зберігається у `E:\KnowledgeVault\Runtime\db\catalog.sqlite3`.

Індексуються Markdown metadata, headings, body, tags, aliases, wikilinks,
assets metadata та scan/migration runs. `Private/` і вміст бінарних assets
не індексуються.

## Extraction і suggestions

```powershell
.\vaultctl.ps1 extract --rebuild
.\vaultctl.ps1 index --rebuild
.\vaultctl.ps1 suggest --kind all
```

Extraction підтримує PDF, DOCX, TXT, MD, CSV, JSON, YAML/YML. Обробляються тільки
assets із sidecar та visibility `public/internal`, не більше 25 MB. `Private`,
`confidential`, `restricted` і архіви не читаються. Кеш повністю rebuildable:
`Runtime/cache/extracted/<sha256>.txt`.

Suggestions зберігаються тільки у `Runtime/suggestions/<run-id>/` як JSON і Markdown.
Vault автоматично не змінюється.

## Backup і operations

```powershell
.\vaultctl.ps1 backup init
.\vaultctl.ps1 backup run
.\vaultctl.ps1 backup check
.\vaultctl.ps1 backup snapshots
.\vaultctl.ps1 backup restore-drill
```

Restic repository: `E:\KnowledgeVault_Backup`. Password file:
`%LOCALAPPDATA%\KnowledgeVault\restic-password.txt`; ACL inheritance вимкнено,
доступ залишається поточному користувачу. Retention: 14 daily, 8 weekly, 12 monthly.
Task Scheduler не створюється. Repository на тому самому диску не захищає від
повної відмови диска `E:`.

`doctor` перевіряє ACL password file та freshness останнього snapshot за
`backup.max_snapshot_age_days`. `backup restore-drill` відновлює кожен файл із
`backup.critical_paths`, перевіряє SHA-256 і завершується помилкою, якщо critical
file відсутній або не входить до backup scope.

Операції над завершеним migration run:

```powershell
.\vaultctl.ps1 report --run "<run-id>"
.\vaultctl.ps1 verify --run "<run-id>"
.\vaultctl.ps1 cleanup-plan --run "<run-id>" --retention-days 30
```

`cleanup-plan` ніколи не видаляє source; це лише manual-review artifact.

## RAG, Ask, Wiki і Graph

```powershell
.\vaultctl.ps1 extract --rebuild
.\vaultctl.ps1 index --rebuild
.\vaultctl.ps1 rag rebuild
.\vaultctl.ps1 rag build
.\vaultctl.ps1 rag sources "ризики міграції"
.\vaultctl.ps1 ask "які головні ризики KnowledgeVault?" --sources-only
.\vaultctl.ps1 wiki draft-concept "KnowledgeVault"
.\vaultctl.ps1 wiki suggest-links
.\vaultctl.ps1 graph build
.\vaultctl.ps1 graph export --format json
.\vaultctl.ps1 graph export --format mermaid
.\vaultctl.ps1 graph stats
```

`rag rebuild` повністю й атомарно перебудовує rebuildable
`Runtime/db/rag.sqlite3`. Для щоденної роботи використовуйте `rag build`: він
порівнює manifest/content hash, повторно обробляє лише змінені sources, видаляє
з індексу missing або заборонені policy-файли та зберігає сумісні embeddings.
Підсумок команди показує `changed`, `reused` і `removed`. Якщо робоча БД
відсутня, пошкоджена або несумісна, виконується безпечний full fallback;
попередня справна БД замінюється лише після `PRAGMA integrity_check`.

Коли `[rag.embeddings].enabled = true`, retrieval об'єднує FTS5 keyword search
і cosine similarity локальних vectors через rank fusion. Vector-only режиму
немає: семантичні результати завжди проходять ту саму metadata/visibility
policy. Зміна provider, model або dimension автоматично інвалідує несумісні
vectors. За замовчуванням embeddings вимкнені, тому базовий режим — FTS5.
Якщо `[rag].enabled = false`, build і search завершуються явною відмовою.

`ask --sources-only` не викликає LLM. Звичайний `ask` працює тільки якщо
`[llm].enabled = true` і Ollama доступний на цьому ПК. Дозволені лише
`localhost`, `127.0.0.1` та `::1`; redirects, LAN і cloud endpoints блокуються.
LLM-відповідь приймається лише як structured JSON із citation `chunk_id`, що
належать фактично знайденим sources.

`wiki summarize` читає лише валідний Markdown у Vault або extracted cache asset
із валідним sidecar, SHA-256 та visibility `public/internal`. External paths,
`Private`, templates/views, symlinks і raw binary блокуються. Approval містить
SHA-256 драфта й target; після будь-якої зміни потрібне повторне approve.
`wiki apply` без `--execute` є dry-run, а існуючі файли не перезаписуються.
Graph artifacts пишуться в `Runtime/graph/`.

`llm.context_limit_tokens` обмежує фактичний sources budget і передається
Ollama як `num_ctx`. `git.enabled=true` активує read-only перевірку tracked
файлів; `validate` повертає error, якщо файл у Vault перевищує
`git.max_tracked_file_mb`. `doctor` показує effective значення цих controls.

Повний контракт: [`docs/CONFIG_AND_COPY_RUNBOOK.md`](docs/CONFIG_AND_COPY_RUNBOOK.md).

## Валідація

```powershell
.\vaultctl.ps1 validate
.\vaultctl.ps1 validate --json
```

Перевіряються:

- обов'язкова структура;
- YAML frontmatter;
- `schema_version`, UUID, type/status і ISO dates;
- duplicate UID;
- broken/ambiguous wikilinks;
- unresolved placeholders;
- restricted metadata у звичайному Vault;
- Windows reserved names, case collisions і довгі paths;
- duplicate assets, missing/invalid sidecars і невідповідність SHA-256;
- stale active projects.

`ERROR` повертає exit code `1`. `WARN` не блокує роботу.

## Тести

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
```

Поточний regression suite містить 94 тести; два symlink-тести можуть бути
очікувано пропущені у Windows без відповідного privilege. Тести використовують
тимчасові каталоги й не торкаються реального `E:\KnowledgeVault`.

## Незмінні обмеження

- `default_mode = "copy"`;
- `verify_hash = true`;
- `overwrite = false`;
- `preserve_source = true`;
- `follow_symlinks = false`;
- `allow_ai_confidential = false`.

Небезпечні значення блокуються під час завантаження конфігурації.
