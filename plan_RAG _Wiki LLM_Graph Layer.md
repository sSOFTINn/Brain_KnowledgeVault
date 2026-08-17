# plan.md — завершення Brain_KnowledgeVault

> Проєкт: `sSOFTINn/Brain_KnowledgeVault`  
> Мета: довести KnowledgeVault від local-first сховища з SQLite/FTS5 до повноцінної системи RAG + Wiki LLM + Graph Layer.  
> Поточний стан: Phase 1–5 реалізовані: каркас, validate/doctor, scan, migration plan, approved-only copy, SQLite/FTS5 catalog/search.  
> Головний принцип: спочатку безпека, відтворюваність і джерела; тільки потім LLM.

---

## 0. Контекст

`Brain_KnowledgeVault` уже має правильний фундамент:

- Markdown + YAML frontmatter;
- Obsidian-compatible `Vault/`;
- CLI `vaultctl`;
- read-only inventory scanner;
- deterministic migration plan;
- safe copy + SHA-256 verification;
- SQLite catalog;
- FTS5 full-text search;
- basic wikilink relations.

Але ще не завершені:

- encrypted backup / restore;
- справжній RAG;
- embeddings / vector search;
- LLM answer layer;
- Wiki LLM інструменти;
- graph export / Graphify layer;
- dashboard / UI;
- фінальне hardening-тестування.

---

## 1. Цільова фінальна архітектура

```text
KnowledgeVault/
│
├── Vault/                         # Obsidian + Markdown notes
│   ├── 00_System/
│   ├── 01_Inbox/
│   ├── 02_Projects/
│   ├── 03_Areas/
│   ├── 04_Knowledge/
│   ├── 05_Resources/
│   ├── 06_Records/
│   ├── 90_Templates/
│   ├── 91_Views/
│   └── 99_Archive/
│
├── Assets/                        # великі вкладення
├── Private/                       # приватні дані, не читаються AI автоматично
├── Workspaces/                    # код і робочі проєкти
├── Automation/                    # vaultctl, tests, docs
├── Runtime/
│   ├── db/
│   │   ├── catalog.sqlite3
│   │   └── rag.sqlite3
│   ├── indexes/
│   ├── cache/
│   └── runs/
├── Staging/
├── Logs/
├── vault.toml
├── README.md
└── MANIFEST.md
```

Фінальна логіка системи:

```text
Markdown / Assets / Metadata
        ↓
SQLite catalog + FTS5
        ↓
Chunks + embeddings
        ↓
Retriever
        ↓
LLM answer with sources
        ↓
Wiki drafts + graph relations
```

---

# Phase 6 — Backup & Restore

## Мета

Перед додаванням LLM/RAG зробити систему безпечною для втрати диска, пошкодження індексу, помилкової міграції або ransomware.

## Завдання

```text
Automation/vaultctl/backup.py
Automation/vaultctl/restore.py
Automation/docs/BACKUP_RESTORE_RUNBOOK.md
Automation/tests/test_backup.py
Automation/tests/test_restore.py
```

Реалізувати:

- backup profile у `vault.toml`;
- encrypted backup;
- restore dry-run;
- restore verification;
- backup manifest;
- checksum verification;
- backup health check у `vaultctl doctor`;
- окрему інструкцію з ключами та recovery.

## CLI

```powershell
vaultctl backup --dry-run
vaultctl backup --execute
vaultctl backup --verify
vaultctl restore --dry-run --from "<backup-path>"
vaultctl restore --verify --from "<backup-path>"
```

## Правила безпеки

- backup не має читати `Private/`, якщо це не дозволено явно;
- ключі не зберігати в Git;
- restore не перезаписує існуюче сховище без окремого `--target`;
- будь-яке відновлення спочатку тільки dry-run.

## Definition of Done

- `vaultctl backup --dry-run` працює без змін файлів;
- `vaultctl backup --execute` створює backup;
- `vaultctl backup --verify` підтверджує цілісність;
- `vaultctl restore --dry-run` показує план відновлення;
- є тести на успішний backup, пошкоджений backup і відсутній ключ.

---

# Phase 7 — RAG Sources Layer

## Мета

Спочатку зробити RAG без LLM: система має знаходити правильні джерела, фрагменти й цитати.

Це важливо: якщо retrieval поганий, LLM буде просто красиво помилятися.

## Нова структура

```text
Automation/vaultctl/rag/
  __init__.py
  chunker.py
  store.py
  retriever.py
  sources.py
  schema.py
```

## Дані

Створити окрему SQLite-базу:

```text
Runtime/db/rag.sqlite3
```

Мінімальна схема:

```sql
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    source_uid TEXT,
    source_path TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT,
    heading_path TEXT,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    visibility TEXT NOT NULL,
    updated TEXT
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id UNINDEXED,
    title,
    heading_path,
    content,
    source_path,
    tokenize = 'unicode61'
);
```

## Chunking rules

Markdown:

- chunk за heading;
- якщо heading дуже великий — розбити на менші частини;
- зберігати heading path;
- зберігати source UID;
- пропускати `visibility: restricted`.

Assets:

- на першому етапі індексувати тільки `.asset.md` sidecar;
- PDF/DOCX OCR не додавати одразу;
- великі binary-файли не читати напряму.

Private:

- `Private/` не індексувати;
- restricted metadata не індексувати;
- у логах не писати секретний текст.

## CLI

```powershell
vaultctl rag build
vaultctl rag rebuild
vaultctl rag sources "Що я писав про SQLite?"
vaultctl rag sources "Які є ризики міграції?" --limit 10
```

## Definition of Done

- `vaultctl rag build` створює chunks;
- `vaultctl rag sources` повертає релевантні фрагменти;
- джерела містять path, title, heading, snippet;
- restricted/private не потрапляють у результат;
- є тести для українського й англійського тексту.

---

# Phase 8 — Embeddings & Vector Search

## Мета

Додати семантичний пошук поверх FTS5.

## Важливий принцип

FTS5 не викидати. Потрібен hybrid retrieval:

```text
FTS5 keyword search
+ vector semantic search
+ metadata filters
+ optional reranking
```

## Нова структура

```text
Automation/vaultctl/rag/embeddings.py
Automation/vaultctl/rag/vector_store.py
Automation/vaultctl/rag/hybrid.py
Automation/tests/test_embeddings.py
```

## Варіанти embeddings

Перший рекомендований варіант:

```text
local embeddings через sentence-transformers
```

Альтернативи:

```text
Ollama embeddings
OpenAI embeddings
інший локальний embedding server
```

## vault.toml

```toml
[rag]
enabled = true
database = "Runtime/db/rag.sqlite3"
chunk_max_chars = 1800
chunk_overlap_chars = 200
default_top_k = 8

[rag.embeddings]
enabled = false
provider = "local"
model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
dimension = 384
```

## CLI

```powershell
vaultctl rag embed
vaultctl rag embed --rebuild
vaultctl rag search "питання" --hybrid
```

## Definition of Done

- embeddings можна вимкнути;
- без embeddings працює FTS5;
- з embeddings працює semantic search;
- rebuild є відтворюваним;
- зміна embedding-моделі створює нову версію індексу;
- немає індексації restricted/private.

---

# Phase 9 — LLM Answer Layer

## Мета

Додати відповідь LLM по знайдених джерелах.

## Нова структура

```text
Automation/vaultctl/rag/llm_client.py
Automation/vaultctl/rag/prompt_builder.py
Automation/vaultctl/rag/answer.py
Automation/vaultctl/rag/citations.py
Automation/tests/test_answer.py
```

## Початковий підхід

Першим зробити sources-only режим, потім answer mode.

```text
retriever → context pack → prompt → LLM → answer with sources
```

## LLM provider

Почати з Ollama як локального варіанту.

```toml
[llm]
enabled = false
provider = "ollama"
model = "llama3.1:8b"
base_url = "http://localhost:11434"
context_limit_tokens = 8192
temperature = 0.2
```

## CLI

```powershell
vaultctl ask "Що я писав про SQLite?"
vaultctl ask "Які ризики у міграції файлів?"
vaultctl ask "Поясни різницю PostgreSQL і SQLite за моїми нотатками"
vaultctl ask "..." --sources-only
vaultctl ask "..." --json
```

## Правила відповіді

LLM має:

- відповідати тільки на основі знайдених джерел;
- явно казати, якщо джерел недостатньо;
- показувати джерела;
- не вигадувати факти;
- не читати `Private/`;
- не використовувати restricted chunks.

## Definition of Done

- `vaultctl ask --sources-only` працює без LLM;
- `vaultctl ask` працює з Ollama;
- відповідь містить джерела;
- недостатність джерел обробляється чесно;
- є тести на prompt building і citation mapping.

---

# Phase 10 — Wiki LLM Draft Tools

## Мета

LLM не тільки відповідає, а допомагає підтримувати wiki, але без автоматичного редагування.

Перший режим — тільки draft/review.

## Нова структура

```text
Automation/vaultctl/wiki/
  __init__.py
  suggest_links.py
  draft_concept.py
  summarize.py
  project_card.py
  moc.py
```

## CLI

```powershell
vaultctl wiki suggest-links
vaultctl wiki draft-concept "SQLite"
vaultctl wiki summarize "Vault/04_Knowledge/Research/example.md"
vaultctl wiki draft-moc "Offline Databases"
vaultctl wiki draft-project-card "PRJ-2026-001"
```

## Правила

- нічого не змінювати без review;
- drafts писати у `Staging/WikiDrafts/`;
- кожен draft має посилання на джерела;
- не додавати вигадані wikilinks;
- зміни у Vault тільки через окреме approve/apply.

## Definition of Done

- створюються draft-файли;
- draft має metadata;
- draft має sources;
- existing files не перезаписуються;
- можна переглянути diff перед застосуванням.

---

# Phase 11 — Graph Layer / Graphify Foundation

## Мета

Побудувати граф зв’язків між нотатками, проєктами, вкладеннями, рішеннями й джерелами.

## Поточна база

Уже є:

- `relations` table;
- extraction of `[[wikilinks]]`.

Потрібно розширити.

## Типи relations

```text
wikilink
mentions
belongs_to_project
depends_on
derived_from
decision_for
source_for
duplicates
related_to
references_asset
has_concept
has_risk
```

## Нова структура

```text
Automation/vaultctl/graph/
  __init__.py
  builder.py
  exporter.py
  queries.py
  mermaid.py
  graphml.py
```

## CLI

```powershell
vaultctl graph build
vaultctl graph neighbors "NOTE-..."
vaultctl graph export --format json
vaultctl graph export --format graphml
vaultctl graph export --format mermaid
vaultctl graph stats
```

## Export formats

Почати з:

```text
JSON
Mermaid
GraphML
```

Пізніше, якщо потрібно:

```text
Neo4j
Kuzu
NetworkX
```

## Definition of Done

- graph build відтворюваний;
- graph export працює;
- можна знайти neighbors для UID;
- можна побачити orphan notes;
- можна побачити strongly connected areas;
- restricted/private не експортуються.

---

# Phase 12 — Dashboard / UI

## Мета

Зробити користування системою зручним без постійного CLI.

## Мінімальний варіант

Obsidian dashboards:

```text
Vault/91_Views/
  Home.base
  Projects.base
  Inbox.base
  Knowledge.base
  Search.md
  Graph.md
```

## Альтернативний варіант

Локальний web UI:

```text
Automation/vaultctl/ui/
  app.py
  templates/
  static/
```

## Функції dashboard

- active projects;
- inbox items;
- stale notes;
- broken links;
- orphan notes;
- recent imports;
- search;
- RAG question form;
- graph export links;
- backup status.

## Definition of Done

- є хоча б Obsidian dashboard;
- видно active projects;
- видно inbox;
- видно search usage;
- видно backup status;
- не показуються restricted/private дані.

---

# Phase 13 — Hardening & Performance

## Мета

Підготувати систему до реального довгого використання.

## Тести

Додати:

```text
Automation/tests/test_rag_chunker.py
Automation/tests/test_rag_sources.py
Automation/tests/test_graph.py
Automation/tests/test_backup_restore.py
Automation/tests/test_security_visibility.py
Automation/tests/test_large_vault.py
```

## Сценарії

Перевірити:

- 10k Markdown-файлів;
- 100k assets metadata;
- довгі Windows paths;
- Unicode filenames;
- український текст;
- битий YAML;
- duplicate UID;
- corrupt SQLite index;
- missing asset sidecar;
- restricted visibility;
- interrupted rebuild;
- interrupted backup;
- restore to clean target.

## Definition of Done

- всі тести проходять;
- rebuild не псує старий index;
- corrupt index можна перебудувати;
- backup можна перевірити;
- private/restricted не витікає у RAG/graph/search;
- документація покриває аварійні сценарії.

---

# Порядок реалізації

Рекомендований порядок:

```text
1. Phase 6  — Backup & Restore
2. Phase 7  — RAG Sources Layer
3. Phase 8  — Embeddings & Hybrid Search
4. Phase 9  — LLM Answer Layer
5. Phase 10 — Wiki LLM Draft Tools
6. Phase 11 — Graph Layer
7. Phase 12 — Dashboard
8. Phase 13 — Hardening
```

Не міняти порядок без причини.

Особливо важливо:

```text
Backup before LLM.
Sources before answers.
Drafts before auto-editing.
Graph export before graph database.
Tests before real migration.
```

---

# Мінімальна версія завершення v1.0

Проєкт можна вважати v1.0, якщо є:

- стабільний `vaultctl init`;
- стабільний `vaultctl validate`;
- стабільний `vaultctl scan`;
- стабільний `vaultctl plan/review/apply`;
- стабільний `vaultctl index/search`;
- working backup/verify;
- working restore dry-run;
- `vaultctl rag sources`;
- `vaultctl ask --sources-only`;
- базовий Ollama answer mode;
- citations/sources у відповідях;
- private/restricted exclusion;
- graph export JSON/Mermaid;
- документація для користувача;
- тести для основних сценаріїв.

---

# CLI target map

Фінальний набір команд:

```powershell
vaultctl doctor
vaultctl init
vaultctl validate

vaultctl scan "E:\SomeFolder"
vaultctl plan --run "<scan-run-id>"
vaultctl review --plan "<plan>"
vaultctl apply --plan "<plan>"
vaultctl apply --plan "<plan>" --execute

vaultctl index --rebuild
vaultctl index --integrity
vaultctl search "query"

vaultctl backup --dry-run
vaultctl backup --execute
vaultctl backup --verify
vaultctl restore --dry-run --from "<backup-path>"

vaultctl rag build
vaultctl rag rebuild
vaultctl rag sources "question"
vaultctl rag embed
vaultctl rag search "question" --hybrid

vaultctl ask "question"
vaultctl ask "question" --sources-only
vaultctl ask "question" --json

vaultctl wiki suggest-links
vaultctl wiki draft-concept "Concept"
vaultctl wiki summarize "<path>"
vaultctl wiki draft-moc "Topic"

vaultctl graph build
vaultctl graph neighbors "<uid>"
vaultctl graph export --format json
vaultctl graph export --format mermaid
vaultctl graph stats
```

---

# Правила для Codex

Codex має дотримуватися таких правил:

1. Не видаляти користувацькі файли.
2. Не переміщувати source-файли.
3. Не індексувати `Private/`.
4. Не індексувати `visibility: restricted`.
5. Не зберігати секрети в Git.
6. Не робити auto-edit Markdown без review.
7. Не перезаписувати існуючі файли без backup/diff.
8. Не додавати LLM-відповіді без sources.
9. Не робити vector-only search без FTS5 fallback.
10. Кожна нова фаза має мати тести.
11. Кожна generated artifact має бути відтворювана.
12. Будь-який destructive action має бути заборонений за замовчуванням.

---

# Найближчий наступний крок

Почати з Phase 6:

```text
Implement encrypted backup and restore dry-run for KnowledgeVault.
Do not touch RAG or LLM until backup verification exists.
```

Після Phase 6 перейти до Phase 7:

```text
Implement RAG sources-only retrieval using Markdown chunks and SQLite FTS5.
Do not add LLM answering until sources retrieval is reliable.
```

---

# Короткий стратегічний висновок

`Brain_KnowledgeVault` уже має сильну основу. Його не треба перебудовувати з нуля.

Правильна стратегія завершення:

```text
захистити дані
→ навчити систему знаходити джерела
→ додати semantic search
→ підключити LLM
→ дозволити draft wiki updates
→ побудувати graph layer
→ зробити dashboard
→ загартувати тестами
```

Головний ризик — занадто рано додати LLM і отримати красиві, але ненадійні відповіді.  
Головна перевага проєкту — він уже побудований як безпечна local-first система, тому RAG і Wiki LLM можна додавати без хаосу.
