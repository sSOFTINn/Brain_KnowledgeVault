# Політика зберігання даних Codex

## Мета

Політика визначає, які дані Codex є канонічними для KnowledgeVault, які є
відновлюваними runtime-даними, а які Windows-каталоги повинні залишатися на
системному диску. Вона не перетворює `E:\KnowledgeVault` на заміну всього
Windows-профілю.

## Канонічна модель

| Категорія | Канонічний шлях | Правило |
|---|---|---|
| Codex state | `60_Private\ToolState\Codex` | Захищений `CODEX_HOME`; не індексувати й не комітити |
| Довгострокові проєкти | `10_Projects\{Active,Reference,Completed}` | Кожний Git-проєкт зберігається цілісно |
| Migration staging | `90_Runtime\Staging\CodexStorageMigration` | Відновлювані copy-only дані, не source of truth |
| Migration evidence | `00_System\Audit\CodexStorageMigration` | Постійні manifests, hashes, approvals і verification |

Офіційна документація OpenAI визначає `CODEX_HOME` як корінь стану Codex,
зокрема config, auth, logs, sessions, skills і standalone package metadata.
Керовані worktrees також створюються під `$CODEX_HOME/worktrees`. Тому цей
каталог зберігається як одна захищена приватна зона, без окремих junction для
його внутрішніх компонентів.

Джерела:

- [Environment variables](https://learn.chatgpt.com/docs/config-file/environment-variables)
- [Config and state locations](https://learn.chatgpt.com/docs/config-file/config-advanced#config-and-state-locations)
- [Worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)
- [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

## Windows-каталоги, що залишаються на C:

Ці шляхи не є помилкою міграції й не переносяться вручну:

- `%LOCALAPPDATA%\OpenAI\Codex` — binaries і application runtimes;
- `%LOCALAPPDATA%\Codex` — desktop operational logs;
- `%APPDATA%\Codex` — desktop profile і Chromium state;
- `%USERPROFILE%\.cache\codex-runtimes` — кеш runtime-залежностей;
- загальні `%TEMP%` і `%TMP%` — спільні каталоги Windows та інших програм.

Внутрішні SQLite-файли, auth/session state, sandbox secrets, binaries і
runtimes не класифікуються як звичайне сміття. Для SQLite використовується
підтримуваний Codex механізм `CODEX_SQLITE_HOME`/`sqlite_home`, якщо буде
окреме рішення; ручне перенесення файлів БД заборонене.

## Дозволені cleanup-кандидати

Read-only аудит може запропонувати для окремого review лише відомі
відновлювані залишки:

- `Documents\codex_search*.txt` — згенеровані звіти інвентаризації;
- `%TEMP%\codex-clipboard-*.png` — тимчасові копії вкладень;
- `%TEMP%\openai-docs-cache` — відновлюваний кеш документації.

Наявність назви `temp`, `cache`, `log` або `codex` сама по собі не є дозволом
на видалення. План враховує retention, фіксує точні paths, SHA-256 для
окремих файлів і file manifest для дозволеного cache-каталогу та не виконує
cleanup.

## Міграційний протокол

```text
inventory -> DryRun/SHA-256 -> explicit approval -> verified copy
          -> restore verification -> separately approved cleanup
```

- source зберігається за замовчуванням;
- overwrite і mirror заборонені;
- reparse points не обходяться;
- `node_modules` та runtime dependencies вважаються rebuildable або
  `manual-review`;
- evidence пишеться лише до `00_System\Audit\CodexStorageMigration`;
- видалення не є частиною `apply` або `cleanup-plan`.

## Автоматизований контроль

```powershell
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local audit
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local cleanup-plan
```

`audit` повертає ненульовий код, якщо фактичний `CODEX_HOME` не збігається з
канонічним шляхом. Обидві команди залишають timestamped JSON evidence.
