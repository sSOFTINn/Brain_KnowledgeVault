# KnowledgeVault v2: інструкція користувача

## 1. Перед початком

Для нового диска працюйте з тимчасового checkout поза майбутнім Vault, доки
сховище не пройде bootstrap і verified import. Для вже створеного Vault
використовуйте canonical checkout:

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
.\run_tests.ps1
```

Деталі двоетапної моделі: [CONTROL_PLANE_BOOTSTRAP.md](CONTROL_PLANE_BOOTSTRAP.md).

Створіть `vault.toml.local` з `vault.toml.example`. Укажіть реальні volume
label/serial для `E:` і `F:`. Локальний файл конфігурації і секрети не комітьте.

Пріоритет конфігурації:

1. явний `--config`;
2. `KNOWLEDGE_VAULT_CONFIG`;
3. `<root>\vault.toml.local`;
4. `<root>\vault.toml`;
5. локальний config у поточній папці;
6. tracked `Automation\vault.toml` лише як legacy fallback.

## 2. Створення структури

Спочатку використовуйте disposable-каталог:

```powershell
.\vaultctl.ps1 bootstrap --config .\vault.toml.local --root C:\Temp\KV-v2 --dry-run
.\vaultctl.ps1 bootstrap --config .\vault.toml.local --root C:\Temp\KV-v2
.\vaultctl.ps1 storage --config C:\Temp\KV-v2\vault.toml.local audit --json
.\vaultctl.ps1 doctor --config C:\Temp\KV-v2\vault.toml.local
.\vaultctl.ps1 validate --config C:\Temp\KV-v2\vault.toml.local
```

Повторний bootstrap безпечний. Непорожній root без
`.knowledgevault-root.json` блокується. Не вмикайте adopt для реального
`E:\KnowledgeVault` без окремої карти відновлення.

## 3. Куди зберігати дані

| Тип | Канонічний шлях |
|---|---|
| Control plane | `00_System\ControlPlane\Brain_KnowledgeVault` |
| Активні Git-проєкти | `10_Projects\Active` |
| Довідкові Git-проєкти | `10_Projects\Reference` |
| Завершені Git-проєкти | `10_Projects\Completed` |
| Markdown/Obsidian | `20_Knowledge` |
| Особисті/робочі/адміністративні документи | `30_Documents` |
| Фото, відео, аудіо, графіка | `40_Media` |
| Дистрибутиви, datasets, довідники | `50_Resources` |
| Приватні дані | `60_Private` |
| Невідомі нові файли | `70_Inbox` |
| Готові експорти | `75_Exports` |
| Заморожені матеріали | `80_Archive` |
| Відтворювані БД, кеші, логи, runs | `90_Runtime` |
| Підозрілі конфлікти | `99_Quarantine` |

У root немає глобального Git. Не переносіть `.git` окремо від проєкту.

## 4. Перенесення репозиторіїв

Створення immutable-плану:

```powershell
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local plan `
  --source "C:\KnowledgeVault-Bootstrap\Brain_KnowledgeVault" `
  --source "<legacy-project-root>"
```

Перевірте `git-repositories.csv`, `RESTORE_MAP.csv`, per-repository manifests,
dirty/untracked count, remotes, branch, HEAD, submodules, LFS, worktrees та
reparse points.

Затверджуйте кожний repository ID окремо:

```powershell
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local review `
  --plan "<repository_plan.jsonl>" `
  --approve "<repository-id>" `
  --note "Перевірено власником"
```

Dry-run і виконання:

```powershell
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local apply `
  --plan "<repository_plan.jsonl>"
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local apply `
  --plan "<repository_plan.jsonl>" --execute
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local verify `
  --plan "<repository_plan.jsonl>"
```

Копія вважається прийнятою лише після SHA-256, збігу HEAD і `git fsck --full`.
Source не видаляється. Cleanup виконується пізніше окремим рішенням.

## 5. Імпорт звичайних файлів

Для файлів з verified snapshot використовуйте старий file pipeline, який
залишається підтриманим:

```powershell
.\vaultctl.ps1 scan "<snapshot-root>" --hash-mode all `
  --config E:\KnowledgeVault\vault.toml.local
.\vaultctl.ps1 plan --run "<scan-run-id>" `
  --config E:\KnowledgeVault\vault.toml.local
.\vaultctl.ps1 review --plan "<migration_plan.jsonl>" `
  --config E:\KnowledgeVault\vault.toml.local
.\vaultctl.ps1 apply --plan "<migration_plan.jsonl>" `
  --config E:\KnowledgeVault\vault.toml.local
```

`apply` без `--execute` нічого не копіює. Unknown → `70_Inbox`, конфлікти →
`99_Quarantine` після ручної маршрутизації. Overwrite і видалення source
заборонені.

## 6. Пошук і приватність

```powershell
.\vaultctl.ps1 index --config E:\KnowledgeVault\vault.toml.local --rebuild
.\vaultctl.ps1 index --config E:\KnowledgeVault\vault.toml.local --integrity
.\vaultctl.ps1 rag --config E:\KnowledgeVault\vault.toml.local build
.\vaultctl.ps1 ask --config E:\KnowledgeVault\vault.toml.local `
  "питання" --sources-only
```

Default include: `20_Knowledge`, `30_Documents`, `docs/documentation` у
проєктах, дозволені metadata з `40_Media`/`50_Resources` та `80_Archive`.

Default deny: `60_Private`, `.git`, `.env`, credentials, `node_modules`,
`.venv`, `bin`, `obj`, `dist`, `build`, `90_Runtime`, `99_Quarantine` і
`F:\Backup_E`. LLM та embeddings вимкнені; Ollama дозволений лише через
loopback.

## 7. Backup і відновлення

```powershell
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local preflight
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local init
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local run
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local snapshots
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local check
.\vaultctl.ps1 restore --config E:\KnowledgeVault\vault.toml.local drill
```

Preflight блокує backup, якщо:

- marker/volume identity не збігаються;
- required include відсутній;
- source і backup на одному фізичному диску;
- носій не має `Healthy / OK`;
- недостатньо місця.

Restic password лежить поза Vault у
`%LOCALAPPDATA%\KnowledgeVault\restic-password.txt` і має ACL лише для
поточного SID. Recovery key/password зберігайте ще в одному безпечному місці.

## 8. Дані Windows-профілю

```powershell
.\vaultctl.ps1 windows-data --config E:\KnowledgeVault\vault.toml.local audit
```

Команда лише інвентаризує і створює план. Вона не переносить `AppData`, не
створює масових junction і не змінює environment variables.

Для Codex використовуйте точніший аудит:

```powershell
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local audit
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local `
  cleanup-plan --retention-days 14
```

Очікуваний `CODEX_HOME` —
`E:\KnowledgeVault\60_Private\ToolState\Codex`. Довгострокові проєкти
зберігаються у `10_Projects`; migration staging — у
`90_Runtime\Staging\CodexStorageMigration`; evidence — у
`00_System\Audit\CodexStorageMigration`.

`cleanup-plan` лише перераховує відомі відновлювані залишки після retention.
Він не видаляє файли. `AppData`, `.cache\codex-runtimes`, binaries, runtimes,
SQLite і загальні `TEMP`/`TMP` не входять до автоматичного cleanup.

## 9. Заборони

- не форматувати `E:` без повного Gate 1–5 із `PRE_WIPE_RUNBOOK.md`;
- не використовувати `F:` зі статусом Warning як єдину копію;
- не запускати mirror/`/MIR` і автоматичне видалення;
- не обходити reparse point;
- не комітити `vault.toml.local`, токени, ключі, паролі чи реальні приватні
  fixtures;
- не називати міграцію завершеною без hash, Git і restore verification.
