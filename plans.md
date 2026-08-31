# KnowledgeVault: покращений план проєкту

> Версія: 4.0
> Дата перегляду: 2026-08-17
> Статус: Storage Platform v2 implementation and release acceptance
> Головний принцип: спочатку інвентаризація і копіювання з перевіркою, видалення джерел — лише окремим пізнішим етапом.

## 0. Призначення документа

Цей файл є головною специфікацією майбутньої системи KnowledgeVault. Інші файли в репозиторії — джерела ідей, шаблонів та прикладів, але не мають вищого пріоритету за цей документ.

Мета проєкту — створити довговічну local-first систему для:

- активних і завершених проєктів;
- знань, досліджень і робочих нотаток;
- документів і вкладень;
- контексту для Codex, ChatGPT, Claude та інших AI-агентів;
- безпечної інвентаризації наявних файлів;
- контрольованої міграції без втрати даних;
- швидкого пошуку через Obsidian, файлову систему та SQLite FTS5;
- відновлення після помилки, пошкодження диска або ransomware.

Цей план описує архітектуру і порядок реалізації. Він **не дозволяє автоматично переміщати, перейменовувати або видаляти наявні файли**.

## 0.1. Архітектурний контракт Storage Platform v2

Schema v2 замінює legacy-модель `Vault/Workspaces/Assets/Runtime` як головну
структуру, але залишає v1 file pipeline для сумісності й керованого імпорту.

Чотири шари:

1. control plane — `00_System\ControlPlane\Brain_KnowledgeVault`;
2. data plane — `10_Projects` … `80_Archive`;
3. derived/runtime plane — `90_Runtime`;
4. backup plane — `F:\Backup_E` на іншому фізичному носії.

Канонічний root — один: `E:\KnowledgeVault`. У root немає глобального `.git`.
Кожний проєкт є окремим Git-репозиторієм.

V2 acceptance pipeline:

```text
bootstrap --dry-run
→ schema marker + volume identity
→ storage audit
→ repository plan + manifests
→ review + append-only approval
→ verified copy without overwrite
→ destination SHA-256 + git HEAD + git fsck
→ encrypted external backup
→ full readback + restore drill
```

Config precedence: explicit `--config` → environment → root
`vault.toml.local` → root `vault.toml` → current directory → tracked legacy
fallback. Реальні machine paths/serials зберігаються лише в ignored
`vault.toml.local`.

Index scope v2: `20_Knowledge`, `30_Documents`, проєктна документація,
дозволені metadata з `40_Media`/`50_Resources` та `80_Archive`.
`60_Private`, secrets, `.git`, dependencies, build outputs, `90_Runtime`,
`99_Quarantine` і backup не індексуються.

Реальні дані переносяться лише після Gate 1–5 із
`PRE_WIPE_RUNBOOK.md`. Форматування не автоматизується.

## 0.2. Історичний завершений стан v1.1

Додатково до completed baseline реалізовано контрольований RAG/Wiki/Graph layer:

- централізована `vaultctl.policy` для `Private/`, `restricted`, `confidential`;
- lock-файли для rebuild/backup/graph/RAG операцій;
- schema migration marker для SQLite (`schema_migrations`, `PRAGMA user_version`);
- `vaultctl rag build|rebuild|sources|search` на SQLite FTS5: справжній
  incremental build із manifest/content-hash GC та атомарним full fallback;
- `vaultctl ask --sources-only` і optional Ollama answer mode;
- optional embeddings provider interface (`none`, `ollama`, `test`) без важких
  ML-залежностей у baseline; за явного ввімкнення — hybrid FTS5/vector ranker із
  перевіркою provider/model/dimension і без vector-only режиму;
- `vaultctl wiki suggest-links|draft-concept|summarize|draft-moc|approve|apply`;
- `vaultctl graph build|neighbors|export|stats`;
- Obsidian-only dashboard у `Vault/91_Views/`;
- regression і v1.1 тести, включно з 1000-note performance smoke.
- exact runtime dependency lock, Windows CI для Python 3.11/3.14 і
  структурований redacted JSONL command log із rotation.
- effective semantics для `scan.max_workers`, `git.enabled`,
  `git.max_tracked_file_mb`, `llm.context_limit_tokens` і `rag.enabled`;
- один verified-copy primitive для routing/migration із failure-injection
  тестами, cleanup partial та publish без overwrite.

LLM, embeddings і wiki apply залишаються safe-by-default: cloud AI не використовується, embeddings disabled, LLM disabled, apply dry-run без `--execute`.

Незалежний аудит від 2026-07-11 зберігається без змін у `audit/`. Поточний
статус remediation ведеться в `AUDIT_STATUS.md`: KV-001–KV-016 закриті,
KV-017 прийнятий до появи іншого фізичного/off-site backup, KV-018 потребує
окремого рішення щодо confidential-labelled PDF і Git history.

---

## 1. Очікуваний результат

Після завершення проєкту має існувати:

1. Одна логічна коренева система з конфігурованим шляхом.
2. Окремі фізичні шари для Markdown, коду, великих вкладень, приватних даних і похідних індексів.
3. Obsidian-vault, який не залежить від Obsidian для збереження змісту.
4. Єдина схема метаданих із валідацією.
5. Контекстний шар для AI-агентів із tier-навігацією.
6. CLI для `init`, `scan`, `plan`, `apply`, `verify`, `index` і `doctor`.
7. Безпечний конвеєр міграції:

```text
inventory
-> report
-> classify
-> migration plan
-> human review
-> dry-run
-> copy to staging/destination
-> checksum verification
-> acceptance period
-> separate cleanup plan
```

8. SQLite-каталог і FTS5-індекс, які можна повністю перебудувати з канонічних файлів.
9. Git-історія для текстових матеріалів без безконтрольного додавання великих бінарних файлів.
10. Encrypted versioned backup із регулярною перевіркою відновлення; повне
    правило 3-2-1 вимагає окремого фізичного/off-site носія і залишається
    зовнішньою операційною дією.

---

## 2. Висновки з аналізу початкового плану

Початковий варіант має правильні базові принципи: Markdown, YAML, Obsidian-незалежність, dry-run, індексація, заборона перезапису і поетапна міграція. Перед реалізацією потрібно виправити такі проблеми.

### 2.1. Структурні проблеми

- `Documents`, `Resources`, `Knowledge_Base` і `Attachments` частково дублюють одне одного.
- Централізація вкладень лише за розширенням (`PDFs`, `Excel`, `Word`) відриває файли від проєктного контексту.
- Папки `AI`, `Excel`, `Linux` наперед створюють тематичну таксономію, яка швидко застаріває.
- Відсутній нормальний `Inbox` для необроблених матеріалів.
- Відсутні окремі шари для staging, журналів, кешу та згенерованих даних.
- Код проєктів, приватні документи і великі медіафайли не повинні мати однаковий Git та sync-профіль.

### 2.2. Проблеми метаданих

- Загальний список статусів не підтримує `todo` для задач і `accepted` для рішень, хоча ці значення вже використовуються у шаблонах.
- Список `type` не містить `meeting`, `postmortem`, `context`, `attachment` та інших потрібних типів.
- Послідовні ID на кшталт `NOTE-2026-0001` потребують централізованого лічильника і створюють конфлікти при паралельній роботі.
- Не визначено версію схеми метаданих і спосіб її міграції.
- Не визначено, які файли є канонічними, а які генеруються автоматично.

### 2.3. Ризики міграції

- Категоризація лише за розширенням недостатня.
- `shutil.move()` між різними дисками може фактично виконати copy + delete.
- Суфікс `_DUPLICATE_001` не розрізняє точний дублікат і різні файли з однаковим ім’ям.
- Немає SHA-256 перевірки до і після копіювання.
- Немає rollback-маніфесту, run ID, контрольних точок і періоду приймання.
- Не враховано junctions, symlinks, reparse points, OneDrive placeholders, locked files, довгі шляхи, регістр і Unicode-нормалізацію.
- CSV/JSON зі старими повними шляхами можуть самі містити конфіденційні дані.

### 2.4. Операційні ризики

- “Один диск” без незалежних резервних копій є single point of failure.
- Git не є резервною копією всіх даних і погано підходить для великих змінюваних бінарних файлів.
- Синхронізація не дорівнює backup: помилкове видалення може синхронізуватися на всі пристрої.
- Приватні, фінансові та юридичні документи не можна автоматично відкривати AI-агентам.
- Велика кількість вручну підтримуваних індексів неминуче призведе до розсинхронізації.

---

## 3. Архітектурні принципи

1. **Local-first.** Канонічні дані зберігаються у звичайних локальних файлах і доступні без хмари.
2. **Один логічний root, кілька профілів зберігання.** Не весь root є одним Obsidian vault або одним Git-репозиторієм.
3. **Markdown — джерело істини для знань.** SQLite, Bases і Markdown-індекси є похідними.
4. **Контекст важливіший за розширення.** Проєктний PDF належить проєкту, а не абстрактній папці `PDFs`.
5. **Мінімальна таксономія.** Спочатку життєвий цикл і тип об’єкта, потім теги та зв’язки.
6. **Безпечне копіювання замість початкового переміщення.** Джерело залишається недоторканим до окремого cleanup-рішення.
7. **Ідемпотентність.** Повторний запуск не дублює вже виконані дії.
8. **Fail closed.** Сумнівний шлях, конфлікт або невідома ситуація блокують операцію над конкретним файлом.
9. **Все, що генерується, має бути відтворюваним.**
10. **Приватність за замовчуванням.** AI і зовнішня синхронізація отримують лише явно дозволені шари.
11. **Поступове ускладнення.** Семантичний пошук, OCR та embeddings додаються лише після стабільної базової системи.
12. **Портативність.** Шляхи в метаданих відносні до root; абсолютні шляхи зберігаються лише в локальних runtime-звітах.

---

## 4. Цільова структура

Рекомендований root:

```text
E:\KnowledgeVault\
```

Фактичний шлях задається у `vault.toml` і може перевизначатися змінною середовища `KNOWLEDGE_VAULT_ROOT`.

```text
KnowledgeVault/
│
├── Vault/                         # Obsidian + Markdown + невеликі вкладення
│   ├── 00_System/
│   │   ├── README.md
│   │   ├── Home.md
│   │   ├── Context.md
│   │   ├── Projects.md
│   │   ├── Memory.md
│   │   ├── Conventions.md
│   │   ├── Metadata_Schema.md
│   │   ├── Security_Policy.md
│   │   ├── Backup_Policy.md
│   │   ├── AI_Policy.md
│   │   └── Decisions/
│   │
│   ├── 01_Inbox/
│   │   ├── Notes/
│   │   ├── Imports/
│   │   └── Meetings/
│   │
│   ├── 02_Projects/
│   │   ├── Active/
│   │   ├── Paused/
│   │   └── Completed/
│   │
│   ├── 03_Areas/
│   ├── 04_Knowledge/
│   │   ├── Concepts/
│   │   ├── How_To/
│   │   ├── Research/
│   │   ├── Glossary/
│   │   └── MOCs/
│   │
│   ├── 05_Resources/
│   │   ├── Sources/
│   │   ├── Reading/
│   │   └── Tools/
│   │
│   ├── 06_Records/                # лише несекретні записи
│   │   ├── Meetings/
│   │   ├── Decisions/
│   │   ├── Postmortems/
│   │   └── Session_Logs/
│   │
│   ├── 90_Templates/
│   ├── 91_Views/                  # Obsidian .base та dashboard-файли
│   └── 99_Archive/
│
├── Workspaces/                    # код і робочі проєкти; кожен може мати власний Git
├── Assets/                        # великі/бінарні файли, організовані за контекстом
│   ├── Projects/
│   ├── Shared/
│   └── Unassigned/
│
├── Private/                       # окремий захищений профіль; не читається AI автоматично
├── Automation/                    # Python-пакет, тести, конфігурація, документація CLI
├── Runtime/                       # SQLite, кеші, тимчасові й згенеровані дані
│   ├── db/
│   ├── indexes/
│   ├── cache/
│   └── runs/
├── Staging/                       # тимчасова зона імпорту та міграції
├── Logs/
├── vault.toml
├── README.md
└── MANIFEST.md
```

### 4.1. Що відкривати в Obsidian

Obsidian відкриває тільки `KnowledgeVault/Vault/`.

Це:

- не завантажує в Obsidian великі робочі дерева й кеші;
- не змішує `.git`, `node_modules`, медіа та SQLite з нотатками;
- дозволяє окремі правила sync і backup;
- зменшує ризик випадкового доступу до `Private/`.

### 4.2. Де зберігати вкладення

Правило:

- невелике зображення або PDF, потрібне безпосередньо в нотатці, можна зберігати поруч у `_assets/`;
- великі файли проєкту зберігаються в `Assets/Projects/<project-code>/`;
- спільні матеріали — в `Assets/Shared/<domain>/`;
- нерозібрані імпорти — тільки тимчасово в `Assets/Unassigned/` або `Staging/`;
- приватні вкладення — в `Private/`, а у Vault зберігається лише безпечна картка-посилання без секретного змісту.

Не створювати глобальні папки лише за розширенням на кшталт `PDFs/`, `Word/`, `Excel/`.

### 4.3. Де зберігати код

Код не переноситься в `Vault/`.

Кожен значний програмний проєкт у `Workspaces/` має:

- власний Git-репозиторій;
- власні залежності та `.gitignore`;
- `README.md`;
- за потреби `ARCHITECTURE.md`, `DECISIONS.md`, `SESSION_LOG.md`;
- картку проєкту у `Vault/02_Projects/`, яка посилається на workspace.

---

## 5. Модель джерел істини

| Дані | Канонічне джерело | Похідні представлення |
|---|---|---|
| Нотатки, знання, рішення | Markdown у `Vault/` | Obsidian Bases, MOC, SQLite FTS5 |
| Статус проєкту | `README.md`/картка проєкту | `Projects.md`, dashboards |
| Великі вкладення | `Assets/` | `.asset.md`, SQLite catalog |
| Приватні файли | `Private/` | мінімальна безпечна картка у Vault |
| Код | окремий Git у `Workspaces/` | картка та архітектурний огляд у Vault |
| Індекс пошуку | Markdown + assets metadata | `Runtime/db/catalog.sqlite3` |
| Міграційний стан | immutable run manifests | CSV/JSON/Markdown reports |
| Конфігурація | `vault.toml` | CLI runtime settings |

Згенеровані файли повинні містити попередження:

```text
AUTO-GENERATED. DO NOT EDIT MANUALLY.
```

---

## 6. Метадані

### 6.1. Мінімальна схема Markdown

```yaml
---
schema_version: 1
uid: 0197...
type: note
title: Назва
status: active
created: 2026-06-19
updated: 2026-06-19
tags: []
aliases: []
visibility: internal
---
```

### 6.2. Правила

- `uid` незмінний після створення.
- `title` може змінюватися.
- `created` і `updated` — ISO 8601.
- Назви властивостей — англійською, lowercase snake_case.
- Значення enum — lowercase kebab-case.
- `tags` не дублюють `type`, `status` або шлях.
- Порожні необов’язкові поля краще не створювати.
- Абсолютні локальні шляхи не комітяться в Git.
- `schema_version` обов’язкова для файлів, які обробляє автоматизація.

### 6.3. Типи

```text
project
area
note
research
how-to
resource
document
task
decision
meeting
postmortem
context
memory
index
session-log
asset
person
```

Новий тип додається лише через зміну схеми й тестів.

### 6.4. Статуси за типом

Не використовувати один універсальний список статусів.

```text
project:  idea | planned | active | paused | completed | cancelled | archived
task:     todo | doing | blocked | done | cancelled
decision: proposed | accepted | superseded | deprecated
document: draft | active | final | archived
resource: unread | reading | processed | archived
meeting:  raw | processed | archived
```

### 6.5. Видимість

```text
public
internal
confidential
restricted
```

- `public` — можна публікувати.
- `internal` — звичайний робочий матеріал.
- `confidential` — не передавати зовнішнім сервісам без явного дозволу.
- `restricted` — не читати AI-агентам і не синхронізувати поза затвердженим захищеним каналом.

---

## 7. Ідентифікатори

### 7.1. Технічний UID

Для кожного керованого об’єкта використовується UUIDv7 відповідно до RFC 9562. Якщо обране середовище ще не має надійної реалізації UUIDv7, дозволений UUIDv4 до окремої міграції.

```yaml
uid: 0197a4c0-...
```

UID:

- не залежить від року, типу або шляху;
- не змінюється при перейменуванні;
- не потребує глобального лічильника;
- використовується в SQLite і машинних зв’язках.

### 7.2. Людський код

Людські коди потрібні лише там, де ними реально користуються:

```text
PRJ-2026-001
ADR-2026-001
```

Не створювати окремі послідовні коди для кожної звичайної нотатки або файла.

### 7.3. Бінарні файли

Для assets використовуються:

- `uid` у sidecar-картці;
- SHA-256 для цілісності й точних дублікатів;
- відносний шлях;
- оригінальне ім’я;
- MIME/розширення;
- розмір;
- дати;
- пов’язаний проєкт або область.

---

## 8. Контекст для AI

Ідеї з `Claude_Second_Brain` потрібно зберегти, але зробити vendor-neutral.

### 8.1. Tier-навігація

**Tier 0 — правила системи**

- `00_System/AI_Policy.md`
- `00_System/Conventions.md`
- локальний файл інструкцій конкретного workspace.

**Tier 1 — читати на старті робочої сесії**

- `00_System/Context.md`;
- `00_System/Projects.md`;
- `00_System/Memory.md`;
- картка поточного проєкту.

**Tier 2 — читати за задачею**

- рішення;
- дослідження;
- архітектура;
- зустрічі;
- voice profile;
- локальні skills.

**Tier 3 — тільки за явним запитом**

- архів;
- raw transcripts;
- старі версії;
- bulk imports;
- confidential матеріали.

**Заборонений автоматичний tier**

- `Private/`;
- `restricted` матеріали;
- секрети;
- `.env`;
- ключі, токени, фінансові та ідентифікаційні документи.

### 8.2. Vendor adapters

Канонічні правила зберігаються в `AI_Policy.md`. За потреби генеруються короткі адаптери:

```text
AGENTS.md
CLAUDE.md
CODEX.md
```

Вони не повинні містити унікальних фактів, яких немає в канонічних документах.

### 8.3. Робочі ритуали

Підтримати як шаблони, а не як жорстко зашиті функції:

- weekly review;
- monthly strategy review;
- project kickoff;
- meeting processing;
- decision record;
- postmortem;
- session log;
- stale-project review.

`Context.md` і `Memory.md` мають бути компактними. Великі деталі переносяться в доменні файли.

---

## 9. Конфігурація

Замість hardcoded Python-змінних використати `vault.toml`.

```toml
schema_version = 1
root = "E:/KnowledgeVault"

[paths]
vault = "Vault"
workspaces = "Workspaces"
assets = "Assets"
private = "Private"
runtime = "Runtime"
staging = "Staging"
logs = "Logs"

[scan]
follow_symlinks = false
hash_mode = "duplicates"
max_workers = 4

[migration]
default_mode = "copy"
verify_hash = true
preserve_timestamps = true
overwrite = false

[git]
enabled = true
max_tracked_file_mb = 10

[privacy]
default_visibility = "internal"
allow_ai_confidential = false
```

Пріоритет конфігурації:

```text
CLI argument > environment variable > vault.toml > safe default
```

CLI завжди друкує фактичну конфігурацію run без секретів.

---

## 10. Архітектура автоматизації

Автоматизація є окремим control plane у `E:\Brain\Automation`. Усі файли,
необхідні для її встановлення, конфігурації, тестування та запуску, повинні
залишатися всередині цієї папки.

```text
Automation/
├── pyproject.toml
├── vault.toml
├── vault.toml.example
├── metadata.schema.json
├── install.ps1
├── vaultctl.ps1
├── run_tests.ps1
├── EXECUTION_PROMPT.md
├── README.md
├── vaultctl/
│   ├── cli.py
│   ├── config.py
│   ├── metadata.py
│   ├── scaffold.py
│   ├── doctor.py
│   ├── validator.py
│   └── router.py
└── tests/
    ├── test_phase1.py
    └── test_router.py
```

Головна користувацька точка запуску:

```powershell
E:\Brain\Automation\vaultctl.ps1 <command>
```

Безпосередній Python-виклик залишається доступним для розробки:

```powershell
python -m vaultctl <command>
```

Реалізовані команди baseline та v1.1:

```text
init
doctor
validate
scan
plan
route
review
apply
index
search
report
verify
cleanup-plan
extract
suggest
backup
rag
ask
wiki
graph
```

`route/review/apply` є обмеженим безпечним routing для `Staging/Inbox`, а не
заміною повного конвеєра міграції Phase 2–4.

---

## 11. Ініціалізація

```powershell
E:\Brain\Automation\vaultctl.ps1 init
```

Вимоги:

- створювати лише відсутні папки й файли;
- не перезаписувати наявні файли;
- підтримувати `--dry-run`;
- мати `--force-template-update` лише для керованих шаблонів із diff і backup;
- створювати `MANIFEST.md`;
- перевіряти доступність root, вільне місце та довжину шляхів;
- не ініціалізувати Git у всьому root;
- Git ініціалізується лише в `Vault/` та окремих `Workspaces/`.
- повторний `init` не повинен змінювати жодного наявного файла;
- `--dry-run` повинен показувати всі заплановані створення без запису;
- `--force-template-update` дозволений лише для `Vault/90_Templates`,
  друкує diff і створює backup попередньої версії.

---

## 12. Сканування наявних файлів

```powershell
python -m vaultctl scan "D:\OldFiles"
```

### 12.1. Незмінність джерела

Scanner:

- відкриває файли лише для читання;
- нічого не створює у source root;
- не змінює timestamps;
- не обходить symlink/junction/reparse point за замовчуванням;
- не гідрує cloud-only placeholders без окремого прапорця;
- не читає вміст приватних файлів у базовому режимі;
- не сканує системний диск цілком без `--allow-system-root`.

### 12.2. Run directory

Кожен запуск має immutable ID:

```text
Runtime/runs/20260619T143000Z_<short-id>/
├── run.json
├── inventory.jsonl
├── inventory.csv
├── errors.jsonl
├── summary.json
└── report.md
```

Не перезаписувати “останній” звіт. Для зручності можна створити pointer `Runtime/runs/latest.txt`.

### 12.3. Поля inventory

- run ID;
- source root;
- absolute source path — лише локальний runtime;
- normalized relative path;
- filename;
- extension;
- detected MIME, якщо можливо без небезпечного виконання;
- size;
- created time, якщо доступний;
- modified time;
- file attributes;
- hidden/system/read-only flags;
- reparse/symlink flag;
- cloud placeholder flag;
- access error;
- project/context hints;
- proposed class;
- proposed destination;
- confidence;
- privacy risk;
- duplicate candidate;
- optional SHA-256.

### 12.4. Хешування

Режими:

```text
none        metadata only
duplicates  group by size, then SHA-256 only for candidates
selected    hash approved migration rows
all         full integrity inventory
```

Для міграції затвердженого файла SHA-256 до і після копіювання є обов’язковим.

### 12.5. Виключення

Не покладатися лише на ім’я папки. Використати:

- canonical path перевірку;
- device/volume boundary;
- reparse point detection;
- configurable glob rules;
- system attributes;
- explicit allow/deny lists.

Базові exclusions:

```text
Windows
Program Files
Program Files (x86)
ProgramData
$Recycle.Bin
System Volume Information
AppData
.git
.venv
venv
node_modules
__pycache__
KnowledgeVault/Runtime
KnowledgeVault/Staging
```

---

## 13. Класифікація

Класифікатор не повинен видавати категорію як факт. Він формує рекомендацію, confidence і пояснення.

### 13.1. Сигнали

Використовувати комбінацію:

1. Розширення і MIME.
2. Вихідний відносний шлях.
3. Назви батьківських папок.
4. Імена відомих проєктів.
5. Дати й активність.
6. Розмір.
7. Exact duplicate hash.
8. За opt-in — безпечне вилучення тексту та keywords.

### 13.2. Рівні впевненості

```text
high    можна пакетно затвердити після перегляду правила
medium  потрібен вибір користувача або project mapping
low     тільки Inbox/Staging, без автоматичного розміщення
```

### 13.3. Рішення за контекстом

Приклади:

- `client-a/contracts/final.pdf` → `Private/Projects/PRJ-.../contracts/`;
- `my-app/docs/architecture.md` → workspace або картка проєкту;
- `course/sql/module-1.pdf` → `Assets/Shared/learning/sql/` + resource card;
- `project-x/report.xlsx` → `Assets/Projects/PRJ-.../data/`;
- невідомий `scan001.pdf` → staging/inbox, не “Books” автоматично.

### 13.4. Розширення не визначає роль

`.pdf` може бути:

- книгою;
- рахунком;
- договором;
- технічною документацією;
- результатом проєкту;
- сканом приватного документа.

Тому правила “всі PDF у PDFs” заборонені.

---

## 14. План міграції

```powershell
python -m vaultctl plan --run <scan-run-id>
```

Вихід:

```text
Runtime/runs/<run-id>/
├── migration_plan.jsonl
├── migration_plan.csv
├── migration_plan.md
└── conflicts.md
```

Поля:

- row ID;
- source path;
- destination path;
- operation: `copy | skip | link | manual-review`;
- reason;
- confidence;
- source SHA-256;
- expected size;
- exact duplicate status;
- name collision status;
- privacy classification;
- review status;
- reviewer note;
- approved timestamp.

Дозволені review status:

```text
pending
approved
rejected
manual
```

`apply` обробляє лише `approved`.

---

## 15. Застосування міграції

### 15.1. Безпечний default

```powershell
python -m vaultctl apply --plan <plan-file>
```

Без `--execute` — лише dry-run.

Перший реальний етап:

```powershell
python -m vaultctl apply --plan <plan-file> --execute --mode copy
```

Режим `move` не використовується у первинній міграції.

### 15.2. Алгоритм одного файла

1. Повторно перевірити, що source існує й не змінився після scan.
2. Перевірити, що destination знаходиться всередині дозволеного root.
3. Перевірити вільне місце.
4. Порахувати або підтвердити source SHA-256.
5. Створити destination directory.
6. Копіювати у тимчасовий файл `.<name>.partial`.
7. Flush/close.
8. Перевірити розмір і SHA-256.
9. Атомарно перейменувати `.partial` у фінальне ім’я.
10. Записати успіх у append-only journal.
11. Source залишити без змін.

Якщо будь-який крок не пройдено:

- фінальний файл не вважати створеним;
- `.partial` зареєструвати для безпечного cleanup;
- source не змінювати;
- продовжити інші рядки;
- завершити run ненульовим exit code при помилках.

### 15.3. Конфлікти

**Exact duplicate:** однаковий SHA-256.

- не створювати ще одну фізичну копію без потреби;
- записати canonical asset і зв’язок із другим source;
- рішення про видалення дубліката — тільки в cleanup-фазі.

**Name collision:** однакове ім’я, різний SHA-256.

- не перезаписувати;
- використати детерміноване ім’я:

```text
filename__a1b2c3d4.ext
```

- обидва файли позначити для review.

Перевіряти конфлікти case-insensitive і з Unicode normalization.

### 15.4. Журнал

```text
Runtime/runs/<run-id>/
├── apply_journal.jsonl
├── apply_summary.json
├── verification.jsonl
└── rollback_manifest.json
```

Journal має бути append-only і оновлюватися після кожного файла.

### 15.5. Cleanup

Видалення або архівація source не входить до `apply`.

Окрема команда лише після:

- успішної checksum verification;
- перевіреного backup;
- ручного приймання;
- рекомендованого періоду 30 днів;
- окремого підтвердження користувача.

```powershell
python -m vaultctl cleanup-plan --run <run-id>
```

Початкова версія може взагалі не мати команди автоматичного видалення.

---

## 16. Індексація і пошук

### 16.1. Рівень 1 — Obsidian

Використати:

- Properties;
- backlinks;
- native Search;
- Bases для таблиць і карток;
- MOC-сторінки для curated navigation.

Не генерувати десятки Markdown-індексів, якщо ту саму задачу стабільно вирішує Bases або пошук.

### 16.2. Рівень 2 — файловий каталог

SQLite:

```text
Runtime/db/catalog.sqlite3
```

Мінімальні таблиці:

```text
objects
files
notes
assets
projects
relations
tags
scan_runs
migration_runs
errors
```

### 16.3. Рівень 3 — FTS5

FTS5 індексує:

- title;
- aliases;
- tags;
- headings;
- body text;
- project;
- source metadata;
- extracted text лише для дозволених типів.

SQLite є кешем. Команда `index --rebuild` повинна відновити базу з нуля.

Потрібні:

- schema migrations;
- integrity check;
- rebuild command;
- transaction per batch;
- normalized paths;
- detection of deleted/renamed files;
- Ukrainian, English and mixed-language search testing.

### 16.4. Embeddings

Семантичний пошук не входить до MVP.

Перед його додаванням потрібно окремо вирішити:

- локальна чи хмарна модель;
- privacy;
- chunking;
- versioning embeddings;
- cost;
- rebuild;
- оцінка якості на реальних запитах.

---

## 17. Git, sync і backup

### 17.1. Git

Git використовується для:

- Markdown;
- шаблонів;
- конфігурації без секретів;
- automation code;
- невеликих текстових індексів.

Git не використовується за замовчуванням для:

- `Private/`;
- `Runtime/`;
- `Staging/`;
- баз даних;
- великих PDF, Excel, аудіо, відео й архівів;
- `.env`, ключів і токенів.

Якщо потрібне версіонування великих файлів — окреме рішення про Git LFS, а не автоматичне ввімкнення.

### 17.2. Sync

Обрати один основний механізм синхронізації для `Vault/`.

Не запускати два незалежні двосторонні sync-движки на одній папці без тестованої схеми конфліктів.

Папки `Runtime/`, `Staging/` і більшість `Workspaces/` не синхронізуються через Obsidian Sync.

### 17.3. Backup 3-2-1

Мінімум:

1. Робоча копія на основному диску.
2. Версійна зашифрована backup-копія на іншому носії або remote.
3. Offline/off-site копія.

Backup має включати:

- `Vault/`;
- `Assets/`;
- `Private/` за окремою захищеною політикою;
- важливі `Workspaces/`, якщо вони не мають надійного remote;
- `vault.toml`;
- automation source.

Не обов’язково backup-ити rebuildable `Runtime/cache`.

### 17.4. Перевірка відновлення

Щомісяця:

- перевірка integrity;
- restore випадкової вибірки у тимчасову папку;
- звірка SHA-256;
- запис результату.

Щокварталу:

- повна тестова процедура відновлення критичного набору;
- перевірка доступності ключів/паролів;
- перевірка інструкції disaster recovery.

---

## 18. Безпека і приватність

1. `Private/` не входить до Git-репозиторію Vault.
2. Секрети не зберігаються у Markdown.
3. Runtime reports із повними шляхами не публікуються.
4. Експорт для AI повинен редагувати або прибирати:
   - паролі й токени;
   - персональні номери;
   - фінансові реквізити;
   - домашні адреси;
   - confidential/restricted матеріали.
5. Content extraction для документів — opt-in.
6. Архіви не розпаковуються автоматично.
7. Макроси, скрипти й executables не запускаються.
8. Scanner не переходить через reparse points за замовчуванням.
9. Destination path проходить canonical containment check.
10. Усі destructive дії потребують окремого explicit confirmation.
11. Для приватного шару має бути окреме рішення про encryption at rest.
12. Логи не повинні містити вміст документів, якщо це не потрібно.

---

## 19. Windows-специфічні вимоги

- Підтримувати Unicode paths.
- Виявляти шляхи, які можуть перевищити сумісний ліміт застосунків.
- Не припускати, що ввімкнення long paths вирішує сумісність усіх програм.
- Заборонити фінальні крапки/пробіли та reserved names у нових керованих іменах.
- Враховувати case-insensitive collisions.
- Виявляти junctions, symlinks і reparse points.
- Коректно працювати з read-only і locked files.
- Не змінювати ACL без окремої вимоги.
- Не припускати, що creation time переноситься однаково між файловими системами.
- Перевіряти доступне місце до batch copy.
- Не використовувати shell-команди, побудовані зі шляхів без безпечного quoting.

---

## 20. Шаблони

MVP-шаблони:

```text
Project.md
Area.md
Note.md
Research.md
How_To.md
Resource.md
Decision.md
Meeting.md
Postmortem.md
Session_Log.md
Asset.md
Person.md
```

### 20.1. Project

Обов’язкові секції:

- outcome;
- scope / non-goals;
- status;
- next action;
- blockers;
- links to workspace/assets;
- milestones;
- risks;
- decisions;
- changelog.

### 20.2. Decision

ADR має містити:

- context;
- decision;
- considered alternatives;
- consequences/trade-offs;
- status;
- supersedes/superseded_by;
- review date, якщо рішення тимчасове.

### 20.3. Meeting

- TL;DR;
- decisions;
- action items з owner і due date;
- facts/metrics;
- open questions;
- links;
- raw transcript окремо або в collapsed/archive layer.

### 20.4. Postmortem

- timeline;
- expected vs actual;
- root causes;
- what to repeat;
- what to avoid;
- corrective actions;
- transferred lessons.

---

## 21. Валідація

```powershell
E:\Brain\Automation\vaultctl.ps1 validate
```

Перевірки:

- валідний YAML;
- підтримуваний `schema_version`;
- унікальні UID;
- коректні type/status combinations;
- ISO dates;
- broken wikilinks і relative links;
- orphan assets;
- missing asset sidecars;
- absolute paths у Git-tracked Markdown;
- restricted файли в неправильному шарі;
- generated files зі зміненим вручну вмістом;
- надто довгі шляхи;
- case-insensitive collisions;
- дублікати за SHA-256;
- stale projects;
- незаповнені template placeholders.

---

## 22. Тестування

### 22.1. Unit

- path normalization;
- config precedence;
- metadata validation;
- status rules;
- classification rules;
- collision naming;
- exclusion logic;
- hash calculation;
- privacy redaction.

### 22.2. Integration

Fixture-набір має містити:

- Unicode та кириличні імена;
- довгі шляхи;
- два однакові файли;
- однакові імена з різним вмістом;
- locked/read-only file;
- broken symlink/junction;
- permission denied;
- файли без розширення;
- cloud placeholder;
- source, що змінився після scan;
- недостатньо місця;
- interrupted apply і resume.

### 22.3. Acceptance

MVP вважається готовим, якщо:

1. `init` повторюється без побічних ефектів.
2. `scan` не змінює source fixture.
3. `plan` детермінований для однакового inventory.
4. `apply` без `--execute` нічого не записує у destination.
5. Execute не перезаписує файли.
6. Кожна копія перевіряється SHA-256.
7. Перерваний run можна безпечно продовжити.
8. Exact duplicates і name collisions розрізняються.
9. SQLite повністю rebuildable.
10. Тестовий restore backup проходить.

---

## 23. Етапи реалізації

### Phase 0 — рішення і прототип

Результат:

- затверджений цей план;
- вибраний фактичний root;
- визначено, що входить у `Private/`;
- створено малий synthetic fixture;
- підтверджено Python version і backup tool.

Exit criteria:

- жодної міграції реальних файлів;
- узгоджені naming, metadata і storage profiles.

### Phase 1 — skeleton

Статус: реалізовано в `E:\Brain\Automation`; перед наступними фазами
обов'язково запускати повний regression test.

Реалізувати:

- `vault.toml`;
- root structure;
- базові системні документи;
- metadata schema;
- templates;
- `init`, `doctor`, `validate`.

Exit criteria:

- повторний `init` нічого не псує;
- всі шаблони проходять validation.

### Phase 2 — read-only inventory

Статус: реалізовано і перевірено на synthetic fixtures та контрольованій
папці `E:\Brain`. Source metadata після acceptance scan залишилися без змін.

Реалізувати:

- scanner;
- exclusions;
- run directories;
- reports;
- duplicate candidate hashing;
- error handling.

Exit criteria:

- fixture і тестова реальна папка проскановані без змін;
- звіт пояснює всі skipped/error cases.

Фактичні артефакти scan:

```text
Runtime/runs/<run-id>/
├── run.json
├── inventory.jsonl
├── inventory.csv
├── errors.jsonl
├── summary.json
└── report.md
```

### Phase 3 — planner

Статус: реалізовано і перевірено. `plan --run <scan-run-id>` створює
deterministic JSONL/CSV/Markdown план та окремий conflict report.

Реалізувати:

- project mappings;
- confidence;
- privacy classification;
- exact duplicate/name collision logic;
- reviewable CSV/JSON/Markdown plan.

Exit criteria:

- жодна low-confidence позиція не отримує auto-approved destination.

### Phase 4 — safe copy migration

Статус: реалізовано і перевірено end-to-end на synthetic temporary data.
Після synthetic acceptance виконано окремий обмежений реальний пілот,
описаний у Phase 7; це не є дозволом на масову міграцію `E:\Brain`.

Реалізувати:

- dry-run;
- approved-only execution;
- `.partial`;
- SHA-256 verification;
- append-only journal;
- resume;
- rollback manifest.

Exit criteria:

- повний integration suite;
- тестова міграція fixture;
- source не змінено.

Фактичні safety controls:

- append-only approvals;
- approved-only execution;
- source size + SHA-256 revalidation;
- `.partial` і atomic rename;
- exact duplicate skip;
- deterministic collision suffix;
- append-only apply journal;
- verification log;
- resume без повторного копіювання;
- cumulative summary і rollback manifest;
- rollback manifest не виконує видалення автоматично.

### Phase 5 — metadata and indexes

Статус: реалізовано і перевірено на synthetic та реальному каркасі.
SQLite catalog створюється атомарно, проходить `PRAGMA integrity_check` і
повністю відновлюється командою `index --rebuild`.

Реалізувати:

- sidecar asset cards;
- Markdown metadata parser;
- SQLite catalog;
- FTS5;
- Bases dashboards;
- rebuild/integrity commands.

Exit criteria:

- база видаляється і відновлюється однією командою;
- контрольні пошукові запити дають очікувані результати.

Фактичні команди:

```powershell
E:\Brain\Automation\vaultctl.ps1 index --rebuild
E:\Brain\Automation\vaultctl.ps1 index --integrity
E:\Brain\Automation\vaultctl.ps1 search "запит"
```

`Private/` і вміст бінарних assets не індексуються.

### Phase 6 — backup and operations

Статус: реалізовано. Використовується `restic` із ручним запуском, encrypted repository
`E:\KnowledgeVault_Backup`, окремим password file у `%LOCALAPPDATA%\KnowledgeVault`
та retention `14 daily / 8 weekly / 12 monthly`. Task Scheduler навмисно не створюється.

Реалізовано:

- `backup init`, `backup run`, `backup check`, `backup snapshots`, `backup restore-drill`;
- версійний encrypted backup канонічних даних, runtime-журналів, логів і Automation;
- виключення `.venv`, `__pycache__`, rebuildable cache/db/indexes і `Staging`;
- password file поза Vault/Git/Markdown з вимкненим ACL inheritance;
- `report --run`, `verify --run`, `cleanup-plan --run`;
- operational і backup/restore runbooks.

Exit criteria:

- repository check і restore drill критичного набору з SHA-256 проходять.

Обмеження: repository розташований на тому самому фізичному диску `E:`, тому захищає
від логічних помилок і випадкового пошкодження даних, але не від повної відмови диска.
Для правила 3-2-1 потрібна додаткова копія на іншому носії або off-site.

### Phase 7 — пілот реальних даних

Статус: реалізовано і повторно перевірено після відтворення Vault як
контрольований пілот рівно трьох кореневих документів:

- `plans.md`;
- `USER_GUIDE.md`;
- `EXECUTE_KNOWLEDGEVAULT.md`.

Destination: `Assets/Projects/PRJ-2026-001/docs/`. Для кожного файла створюється
валідний `.asset.md` sidecar. Source залишається незмінним. Повторний `apply` є
ідемпотентним. Створено активну картку `PRJ-2026-001 KnowledgeVault`.

Масове сканування або міграція всього диска не дозволені без окремого підтвердження.

### Phase 8 — optional intelligence

Статус: базові локальні функції реалізовано:

- валідні Obsidian Bases `Projects.base`, `Records.base`, `Inbox.base`;
- `extract --rebuild` для PDF, DOCX, TXT, MD, CSV, JSON, YAML/YML;
- extraction тільки для sidecar-assets із visibility `public/internal`, до 25 MB;
- rebuildable cache `Runtime/cache/extracted/<sha256>.txt`;
- inclusion extracted text у SQLite FTS5;
- `suggest --kind moc|stale|duplicates|all`;
- suggestions тільки у `Runtime/suggestions/<run-id>/`, без автоматичної зміни Vault.

Свідомо не реалізовано: OCR, cloud AI, vector-only search, автоматична обробка
зустрічей і автоматична міграція всього диска. Optional local embeddings та
hybrid FTS5/vector retrieval реалізовані у v1.1, але disabled by default.

---

## 24. Реєстр головних ризиків

| Ризик | Ймовірність | Вплив | Контроль |
|---|---:|---:|---|
| Втрата source під час move | середня | критичний | primary migration тільки copy + verify |
| Silent corruption | низька/середня | критичний | SHA-256 до/після, backup checks |
| Хибна класифікація | висока | середній | confidence + human review |
| Розростання Git | висока | середній | Git лише для text, size guard |
| Витік приватних даних | середня | критичний | Private layer, visibility, AI policy |
| Sync-конфлікти | середня | високий | один primary sync engine |
| Розсинхронізація SQLite | середня | середній | rebuildable derived DB |
| Довгі/несумісні шляхи | середня | середній | preflight path checks |
| Junction loop | низька | високий | no-follow default |
| OneDrive placeholder error | середня | середній | detect and skip by default |
| Таксономічний хаос | висока | середній | мінімальні папки, properties, MOC |
| Надмірна автоматизація | висока | середній | phased rollout, MVP limits |
| Backup, який не відновлюється | середня | критичний | ручний щомісячний restore drill + freshness gate |
| Vendor lock-in AI/Obsidian | середня | середній | canonical Markdown, adapters only |

---

## 25. Deliverables

### Обов’язкові

- оновлений `plans.md`;
- root `README.md`;
- `vault.toml.example`;
- metadata JSON Schema або еквівалентна формальна схема;
- системні політики;
- templates;
- Python package `vaultctl`;
- unit та integration tests;
- fixture data;
- migration runbook;
- backup/restore runbook;
- threat/privacy checklist;
- architecture decision records.
- поточний remediation ledger `AUDIT_STATUS.md` і root `SECURITY.md`.

### Не входить до першої реалізації

- автоматичне видалення source;
- автоматична міграція всього диска;
- OCR усіх PDF;
- cloud embeddings;
- автоматичне розпакування архівів;
- виконання або аналіз макросів;
- командна багатокористувацька модель;
- повноцінний task manager;
- заміна спеціалізованих систем бухгалтерії, password manager або CRM.

---

## 26. Початкові рішення за замовчуванням

Якщо користувач не змінить їх перед реалізацією:

- root: конфігурований, робочий default `E:\KnowledgeVault`;
- Obsidian відкриває `Vault/`;
- Git лише для `Vault/` і окремих workspaces;
- primary migration mode: `copy`;
- hash: SHA-256;
- source retention після copy: мінімум 30 днів;
- symlinks/junctions: не обходити;
- content extraction: off;
- embeddings: off;
- default visibility: `internal`;
- private AI access: off;
- SQLite: derived and rebuildable;
- first pilot: synthetic fixture, потім одна некритична папка.

---

## 27. Джерела та технічні підстави

Офіційні й первинні джерела, використані для уточнення плану:

- Obsidian Properties: <https://obsidian.md/help/properties>
- Obsidian Bases: <https://obsidian.md/help/bases>
- Obsidian Attachments: <https://obsidian.md/help/attachments>
- Obsidian Sync selective settings: <https://obsidian.md/help/sync/settings>
- Obsidian Sync version history: <https://obsidian.md/help/sync/version-history>
- SQLite FTS5: <https://sqlite.org/fts5.html>
- Git LFS: <https://git-lfs.com/>
- Git partial clone and large repository behavior: <https://git-scm.com/docs/partial-clone>
- Python `shutil.move`: <https://docs.python.org/3/library/shutil.html>
- Python `hashlib`: <https://docs.python.org/3/library/hashlib.html>
- Microsoft Windows path limits: <https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation>
- Microsoft file naming rules: <https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file>
- CISA 3-2-1 backup guidance: <https://www.cisa.gov/audiences/state-local-tribal-and-territorial-government/secure-us-sltt/back-government-data>
- CISA offline encrypted backup guidance: <https://www.cisa.gov/stopransomware/ransomware-guide>
- UUID RFC 9562: <https://www.rfc-editor.org/info/rfc9562/>
- Local-first principles: <https://www.inkandswitch.com/essay/local-first/>
- Restic documentation: <https://restic.readthedocs.io/en/latest/>

---

## 28. Незмінне правило виконання

Для будь-яких реальних даних:

```text
scan
-> report
-> classify
-> plan
-> review
-> dry-run
-> copy
-> checksum verify
-> backup verify
-> acceptance period
-> separate cleanup decision
```

Жоден AI-агент або скрипт не має права скорочувати цю послідовність без окремого явного рішення користувача.

---

## 29. Фактичний контракт автоматизації

### 29.1. Встановлення і перевірка

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
.\install.ps1
.\run_tests.ps1
.\vaultctl.ps1 doctor
.\vaultctl.ps1 init --dry-run
```

### 29.2. Безпечні інваріанти

Конфігурація блокується, якщо:

- `migration.default_mode` не дорівнює `copy`;
- `migration.verify_hash` вимкнений;
- `migration.overwrite` увімкнений;
- `routing.preserve_source` вимкнений;
- scanner налаштований обходити symlinks.

`route` лише створює immutable JSONL-план. Ручні approvals записуються в
окремий append-only журнал. `apply` без `--execute` є dry-run. Після
`--execute` source залишається без змін.

### 29.3. Передача наступному агенту

Канонічний готовий промпт для автономного продовження:

```text
E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation\EXECUTION_PROMPT.md
```

Перед переходом до Phase 2 агент зобов'язаний виконати тести, подвійний
`init`, `doctor` і `validate`.

---

## 30. Amendment: self-bootstrap і Codex storage

### 30.1. Дві ролі control plane

- до створення Vault репозиторій працює як тимчасовий bootstrap checkout
  поза `E:\KnowledgeVault`;
- після bootstrap він переноситься repository-aware pipeline до
  `00_System\ControlPlane\Brain_KnowledgeVault` і стає canonical checkout;
- bootstrap source зберігається до SHA-256, `git fsck`, verify та окремого
  cleanup-рішення.

### 30.2. Канонічні Codex boundaries

```text
CODEX_HOME = 60_Private\ToolState\Codex
projects   = 10_Projects
staging    = 90_Runtime\Staging\CodexStorageMigration
evidence   = 00_System\Audit\CodexStorageMigration
```

Protected Windows paths (`AppData\Local\OpenAI\Codex`,
`AppData\Local\Codex`, `AppData\Roaming\Codex`, `.cache\codex-runtimes`),
загальні `TEMP`/`TMP`, binaries, runtimes і внутрішні SQLite не переносяться
вручну та не входять до cleanup.

### 30.3. Автоматизований контракт

```powershell
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local audit
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local cleanup-plan
```

`audit` є read-only щодо зовнішніх даних. `cleanup-plan` враховує retention,
фіксує точні paths і SHA-256 для файлів, має
`execute_supported=false` та не є дозволом на видалення.

Офіційні джерела OpenAI:

- <https://learn.chatgpt.com/docs/config-file/environment-variables>
- <https://learn.chatgpt.com/docs/config-file/config-advanced#config-and-state-locations>
- <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- <https://learn.chatgpt.com/docs/environments/git-worktrees>
