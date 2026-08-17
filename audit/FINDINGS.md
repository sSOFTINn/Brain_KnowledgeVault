# Повний перелік знахідок

## KV-001 Lock іншого процесу видаляється невдалим конкурентом

- **Рівень:** High; **Статус:** підтверджено; **Компонент:** `Automation/vaultctl/locks.py:16-46`.
- **Доказ:** після вкладеної невдалої спроби `LOCK_OWNERSHIP_PRESERVED_AFTER_CONTENDER=False`; `finally` на рядках 41-44 видаляє path незалежно від факту захоплення.
- **Суть:** конкурент, який отримав `LockError`, видаляє lock власника; третій writer може зайти паралельно.
- **Наслідки:** одночасні rebuild/backup, пошкоджені або суперечливі derived artifacts.
- **Ймовірність / вплив:** середня / високий.
- **Рекомендація:** зберігати `acquired=False`, видаляти lock лише якщо поточний context його створив; перевіряти token/PID перед unlink.
- **Складність / ризик зміни:** мала / низький; **Backup:** ні.
- **Перевірка:** тест owner + failed contender + third contender; lock існує до виходу owner.
- **Відкат:** повернення одного модуля і тесту.

## KV-002 Wiki summarize читає довільний файл поза KnowledgeVault

- **Рівень:** High; **Статус:** підтверджено; **Компонент:** `wiki.py:87-98`, `policy.py:42-76`.
- **Доказ:** synthetic файл поза root успішно скопійовано в draft: `WIKI_OUTSIDE_ROOT_COPIED=True`.
- **Суть:** абсолютний шлях приймається, а файл без metadata отримує default `internal`; можна випадково прочитати password/.env/інший локальний секрет.
- **Наслідки:** секрет потрапляє у `Staging/WikiDrafts`, а згодом у backup/індекс або LLM-контекст.
- **Ймовірність / вплив:** середня / високий.
- **Рекомендація:** allowlist `Vault` і sidecar-validated `Assets`; зовнішні шляхи deny by default; окремий explicit import flow без AI.
- **Складність / ризик зміни:** мала / низький; **Backup:** так, перед очищенням уже створених drafts.
- **Перевірка:** тести на restic password path, `.env`, Private і arbitrary external path.
- **Відкат:** повернути policy change; користувацькі drafts не видаляти автоматично.

## KV-003 LLM endpoint не обмежений loopback

- **Рівень:** High; **Статус:** підтверджено; **Компонент:** `config.py:274-280,324-327`, `ask.py:32-60`.
- **Доказ:** конфіг з `https://example.invalid` і `llm.enabled=true` успішно завантажився.
- **Суть:** provider називається Ollama/local, але `base_url` може бути довільним; chunks надсилаються POST-запитом.
- **Наслідки:** витік internal-матеріалів у мережу через помилкову конфігурацію або підміну config.
- **Ймовірність / вплив:** середня / високий.
- **Рекомендація:** default allowlist `localhost`, `127.0.0.1`, `::1`; external endpoint лише через явно названий unsafe opt-in і warning у doctor/validate.
- **Складність / ризик зміни:** мала / низький; **Backup:** ні.
- **Перевірка:** config tests для loopback/remote/redirect; HTTP redirects вимкнути або перевіряти кінцевий host.
- **Відкат:** повернути URL validator.

## KV-004 Embeddings зберігаються, але hybrid/vector retrieval відсутній

- **Рівень:** High; **Статус:** підтверджено; **Компонент:** `rag/embeddings.py`, `rag/store.py:204-240`.
- **Доказ:** `cosine()` і `blob_to_vector()` не мають викликів; `query_sources()` виконує лише FTS5/LIKE. Тест перевіряє тільки кількість записаних embeddings.
- **Суть:** реалізація не відповідає заявленому hybrid retrieval; semantic search не існує.
- **Наслідки:** статус v1.1 вводить в оману; українські/синонімічні запити не отримують очікуваної семантичної релевантності.
- **Ймовірність / вплив:** висока / високий для заявленої функції.
- **Рекомендація:** query embedding + cosine over compatible vectors + normalized FTS score + metadata filter; FTS обов'язковий.
- **Складність / ризик зміни:** середня / середній; **Backup:** ні, DB rebuildable.
- **Перевірка:** semantic-only fixture, dimension/model mismatch, restricted leakage, deterministic rank.
- **Відкат:** embeddings disabled і FTS-only режим.

## KV-005 Anti-hallucination та citation validation не реалізовані

- **Рівень:** High; **Статус:** підтверджено; **Компонент:** `ask.py:32-84`.
- **Доказ:** відповідь Ollama приймається як непорожній рядок; немає parser/validator citation IDs; `context_limit_tokens` не використовується; sufficient = `bool(sources)`.
- **Суть:** prompt просить цитувати, але код не доводить, що цитати існують або відповідь підтримується джерелами.
- **Наслідки:** вигадані citations і впевнені відповіді зі слабко релевантними chunks.
- **Ймовірність / вплив:** висока при ввімкненні LLM / високий.
- **Рекомендація:** structured response, allowlist chunk IDs, coverage check, relevance threshold, token budget і відмова при invalid citations.
- **Складність / ризик зміни:** середня / низький, поки LLM off; **Backup:** ні.
- **Перевірка:** fake Ollama з missing/unknown citations, empty support, oversized context.
- **Відкат:** вимкнути answer mode, залишити `--sources-only`.

## KV-006 Поточні дані не покриті актуальним backup

- **Рівень:** High; **Статус:** підтверджено; **Компонент:** operational backup.
- **Доказ:** єдиний snapshot `08042067` від 2026-06-29; `restic ls latest` не містить `ClearSUHF_Project-main` та `.obsidian/workspace.json`.
- **Суть:** repository справний, але snapshot не відповідає поточному Vault.
- **Наслідки:** новий проєкт/налаштування не відновляться після логічної помилки; відмова E: знищить і source, і repository.
- **Ймовірність / вплив:** середня / високий.
- **Рекомендація:** негайний manual backup + check + restore drill; далі календарний operational reminder; 3-2-1 на окремий носій.
- **Складність / ризик зміни:** мала / низький; **Backup:** це і є перша дія.
- **Перевірка:** `backup snapshots`, `restic ls latest`, hash restore критичного project file.
- **Відкат:** не потрібен; snapshots versioned.

## KV-007 Поточний Vault не проходить validate

- **Рівень:** Medium; **Статус:** підтверджено; **Компонент:** `E:\KnowledgeVault\Vault\02_Projects\Completed\ClearSUHF_Project-main\README.md`.
- **Доказ:** `validate` exit 1: `missing YAML frontmatter`.
- **Суть:** будь-який Markdown у керованій Vault-зоні повинен мати schema metadata.
- **Наслідки:** health gate червоний; файл пропускається catalog/RAG і статус production-ready некоректний.
- **Ймовірність / вплив:** висока / середній.
- **Рекомендація:** додати валідний frontmatter або перемістити code README у Workspaces через контрольований процес.
- **Складність / ризик зміни:** мала / низький; **Backup:** так.
- **Перевірка:** `vaultctl validate`, `index --rebuild`, пошук UID.
- **Відкат:** відновити файл зі snapshot/копії.

## KV-008 Битий YAML аварійно зупиняє policy/validate/RAG

- **Рівень:** Medium; **Статус:** підтверджено; **Компонент:** `metadata.py:56-64`, catch sites у `policy.py`, `validator.py`, `rag/chunker.py`.
- **Доказ:** malformed flow sequence породив необроблений `yaml.parser.ParserError`.
- **Суть:** catch lists містять ValueError, але не `yaml.YAMLError`; одна пошкоджена нотатка зупиняє операцію.
- **Наслідки:** локальний denial of service, слабка діагностика, rebuild не завершується.
- **Ймовірність / вплив:** середня / середній.
- **Рекомендація:** normalize parser errors у власний MetadataError; policy fail-closed; validator додає finding і продовжує.
- **Складність / ризик зміни:** мала / низький; **Backup:** ні.
- **Перевірка:** fixtures із syntax error, non-mapping, encoding error та restricted marker.
- **Відкат:** повернути exception wrapper.

## KV-009 `rag build` не є інкрементальним

- **Рівень:** Medium; **Статус:** підтверджено; **Компонент:** `rag/store.py:99-194`, `cli.py:388-389`.
- **Доказ:** параметр `incremental` змінює лише `mode`; код завжди читає всі sources, створює temporary DB і replace.
- **Суть:** заявлений build/GC-by-hash API не реалізовано.
- **Наслідки:** зайвий CPU/IO і повторні embedding calls на великих Vault.
- **Ймовірність / вплив:** висока / середній при масштабуванні.
- **Рекомендація:** reuse manifest/content_hash, upsert changed, delete missing/blocked, retain vector лише для same model/hash.
- **Складність / ризик зміни:** середня / середній; **Backup:** ні, DB rebuildable.
- **Перевірка:** call counters і unchanged 1000-note corpus.
- **Відкат:** `rag rebuild` як гарантований fallback.

## KV-010 Wiki approval не прив'язаний до вмісту драфта

- **Рівень:** Medium; **Статус:** підтверджено; **Компонент:** `wiki.py:124-160`.
- **Доказ:** approval містить лише draft_id/target/time; apply читає поточний `draft.md` без hash check.
- **Суть:** драфт можна змінити після review і до execute.
- **Наслідки:** застосовується не той текст, який затверджував користувач.
- **Ймовірність / вплив:** низька-середня / середній.
- **Рекомендація:** approval event з SHA-256 draft + normalized target + approver; apply відмовляє при drift.
- **Складність / ризик зміни:** мала / низький; **Backup:** так перед execute.
- **Перевірка:** approve, mutate draft, execute must fail.
- **Відкат:** сумісне читання старих approvals тільки в dry-run.

## KV-011 ACL пароля коректний зараз, але не контролюється постійно

- **Рівень:** Medium; **Статус:** підтверджено; **Компонент:** `backup.py:89-113`, `doctor.py:30-65`.
- **Доказ:** поточний файл має protected ACL лише для `DESKTOP-C62COHH\Nitfos`; однак existing password file повертається до ACL-коду, а doctor ACL не читає.
- **Суть:** permission drift не виявляється й не виправляється.
- **Наслідки:** інший локальний principal може отримати ключ до backup.
- **Ймовірність / вплив:** низька / високий.
- **Рекомендація:** read-only ACL check у doctor; explicit repair command, не silent mutation.
- **Складність / ризик зміни:** мала / низький; **Backup:** ні.
- **Перевірка:** temp file з inherited/broad ACL дає FAIL/WARN.
- **Відкат:** видалити health check.

## KV-012 Встановлення залежностей невідтворюване, CI відсутній

- **Рівень:** Medium; **Статус:** підтверджено; **Компонент:** `pyproject.toml:5-10`, `install.ps1:9-14`, repository root.
- **Доказ:** version ranges без lock/hashes; install робить online upgrade pip; `.github/workflows` відсутня. Локально `pip check` pass, OSV API не повернув advisories для встановлених версій.
- **Суть:** clean install може змінитися без commit; regression помітний лише вручну.
- **Наслідки:** supply-chain/reproducibility risk, різні результати на Python 3.11-3.14.
- **Ймовірність / вплив:** середня / середній.
- **Рекомендація:** constraints/lock з hashes, документований update process, Windows CI matrix, dependency audit.
- **Складність / ризик зміни:** середня / низький; **Backup:** ні.
- **Перевірка:** fresh venv install from lock + 51 tests.
- **Відкат:** старий pyproject ranges.

## KV-013 Частина конфігурації не впливає на поведінку

- **Рівень:** Medium; **Статус:** підтверджено; **Компонент:** `config.py`, usage search.
- **Доказ:** `context_limit_tokens`, `rag.enabled`, `max_workers`, `git_enabled`, `max_tracked_file_mb` не використовуються у runtime flow; vectors не читаються.
- **Суть:** конфіг створює хибне відчуття контролю.
- **Наслідки:** operator очікує limit/disable/concurrency, яких немає.
- **Ймовірність / вплив:** висока / середній.
- **Рекомендація:** реалізувати semantics або видалити/позначити reserved; doctor має перевіряти effective behavior.
- **Складність / ризик зміни:** середня / середній; **Backup:** ні.
- **Перевірка:** behavior tests для кожного exposed knob.
- **Відкат:** повернути knobs як deprecated no-op із warning.

## KV-014 Restore drill непереносний і вузький

- **Рівень:** Medium; **Статус:** підтверджено; **Компонент:** `backup.py:166-211`.
- **Доказ:** hardcoded `E:/Brain/Automation/README.md`; перевіряються максимум Home.md, vault.toml, README.md.
- **Суть:** clone в іншому місці втрачає automation check; project/assets/private metadata не входять у drill.
- **Наслідки:** green restore drill не доводить відновлення критичного користувацького набору.
- **Ймовірність / вплив:** середня / середній.
- **Рекомендація:** configurable critical paths, unique relative keys, include one active project/asset sidecar/Private sentinel metadata без розкриття вмісту.
- **Складність / ризик зміни:** мала-середня / низький; **Backup:** ні.
- **Перевірка:** clone path override і multi-file hash drill.
- **Відкат:** старий fixed subset.

## KV-015 Документація запуску не покриває поточну Execution Policy

- **Рівень:** Low; **Статус:** підтверджено; **Компонент:** README/USER_GUIDE/Automation README.
- **Доказ:** прямі `.\run_tests.ps1` і `.\vaultctl.ps1` заблоковані; workaround наведений лише для install.
- **Суть:** quick start не працює на поточній політиці PowerShell.
- **Наслідки:** новий користувач не може виконати health checks без самостійної діагностики.
- **Ймовірність / вплив:** висока / низький.
- **Рекомендація:** documented one-process `powershell -NoProfile -ExecutionPolicy Bypass -File ...`; не змінювати machine policy.
- **Складність / ризик зміни:** мала / низький; **Backup:** ні.
- **Перевірка:** fresh PowerShell session із Restricted policy.
- **Відкат:** documentation-only.

## KV-016 Observability слабка, safe-copy логіка дублюється

- **Рівень:** Low; **Статус:** підтверджено; **Компонент:** `router.py`, `migrator.py`, `Logs/`.
- **Доказ:** два окремі copy/hash/collision pipelines; `config.logs` ніде не використовується.
- **Суть:** виправлення safety bug треба дублювати, а загального structured operation log немає.
- **Наслідки:** maintenance drift і складніша діагностика.
- **Ймовірність / вплив:** середня / низький-середній.
- **Рекомендація:** малий спільний verified-copy primitive; JSONL operation log з rotation/redaction.
- **Складність / ризик зміни:** середня / середній; **Backup:** так перед refactor.
- **Перевірка:** весь regression suite та failure injection.
- **Відкат:** залишити окремі adapters навколо старої реалізації.

## KV-017 Backup repository на тому самому фізичному диску

- **Рівень:** Informational; **Статус:** підтверджено й прийнято; **Компонент:** `vault.toml:39-46`.
- **Доказ:** root і repository розташовані на E:; документація прямо це визнає.
- **Суть / наслідки:** захист від логічних помилок, але не від відмови диска/ransomware.
- **Рекомендація:** друга encrypted copy на окремому/off-site носії; **Складність:** середня; **Ризик:** низький.
- **Перевірка:** restore на інший носій; **Відкат:** не потрібен.

## KV-018 Маркування документа «КОНФІДЕНЦІЙНО» не узгоджене з Git tracking

- **Рівень:** Informational; **Статус:** підтверджено; **Компонент:** `Ризики/Brain_KnowledgeVault_Analytical_Report.pdf`.
- **Доказ:** PDF має видимий footer «КОНФІДЕНЦІЙНО» і відстежується Git у commit `7740c6d`.
- **Суть / наслідки:** незрозуміла класифікація; файл потрапляє до remote repository та collaborators.
- **Рекомендація:** визначити, чи label змістовний; якщо так — зберігати поза Git і очистити history окремою погодженою процедурою. Автоматично не видаляти.
- **Складність / ризик зміни:** мала для policy, висока для history rewrite; **Backup:** так.
- **Перевірка:** repository access/classification review; **Відкат:** повернути файл зі snapshot.

