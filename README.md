# Brain KnowledgeVault Storage Platform v2

`Brain_KnowledgeVault` — control plane для головного файлового сховища
`E:\KnowledgeVault`. Репозиторій містить CLI, схему, тести й runbooks; особисті
дані, документи, секрети та резервні копії до Git не входять.

## Архітектура

- **Control plane:** `E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault`.
- **Data plane:** `10_Projects`, `20_Knowledge`, `30_Documents`,
  `40_Media`, `50_Resources`, `60_Private`, `70_Inbox`, `80_Archive`.
- **Derived/runtime plane:** `90_Runtime`; його можна перебудувати.
- **Private tool state:** `60_Private\ToolState\Codex`; це канонічний
  `CODEX_HOME`, який не індексується і не комітиться.
- **Backup plane:** `F:\Backup_E`; джерело й backup мають бути на різних
  фізичних дисках.

У корені `E:\KnowledgeVault` не створюється глобальний `.git`. Кожний
проєкт у `10_Projects` зберігає власну історію, локальні гілки, untracked
файли, submodules, LFS і worktree metadata.

## Що реалізовано у v2

- schema v2 і локальний `vault.toml.local` з вищим пріоритетом за tracked
  fallback-конфіг;
- `bootstrap --dry-run` з marker-файлом та перевіркою volume identity;
- блокування непорожнього root без явного дозволеного adopt;
- `storage audit` без обходу junction/symlink/reparse point;
- repository import як неподільної одиниці:
  `plan → review → approval → copy → SHA-256 → git fsck → verify`;
- immutable repository plan, `RESTORE_MAP.csv`, append-only approvals і
  постійний audit trail;
- backup preflight: required includes, health/identity носія, вільне місце та
  фізичне розділення source/backup;
- 100% Restic readback за default і SHA-256 restore drill критичних файлів;
- read-only аудит підтримуваного перенаправлення даних Windows-профілю;
- окрема Codex storage policy: перевірка `CODEX_HOME`, canonical/project/
  staging/audit boundaries, protected AppData/runtime paths і manual-only
  cleanup plan для відомих тимчасових залишків;
- індексація `20_Knowledge`, `30_Documents`, документації проєктів,
  дозволених resources/media metadata та `80_Archive`;
- fail-closed виключення `60_Private`, `.git`, `.env`, credentials,
  build/cache/runtime/quarantine;
- виправлена перевірка reparse-компонентів і стабільна Windows ACL-перевірка
  Restic password через SID.

## Вимоги

- Windows 10/11;
- PowerShell 5.1 або новіший;
- Python 3.11 або новіший;
- Git і Git LFS;
- Restic для backup/restore.

## Встановлення й тести

Для вже створеного Vault запускайте canonical checkout:

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
```

Для чистого диска спочатку клонуйте репозиторій у тимчасовий bootstrap-path
поза майбутнім `E:\KnowledgeVault`, виконайте `bootstrap`, а потім перенесіть
репозиторій через verified `import` до
`00_System\ControlPlane\Brain_KnowledgeVault`. Це усуває циклічність «проєкт
створює сховище, всередині якого сам має жити».

`ExecutionPolicy Bypass` діє лише для цього процесу.

## Bootstrap на disposable-каталозі

Спочатку скопіюйте `Automation\vault.toml.example` у локальний
`vault.toml.local`, заповніть volume label/serial і не комітьте цей файл.

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
.\vaultctl.ps1 bootstrap --config .\vault.toml.local --root C:\Temp\KV-Test --dry-run
.\vaultctl.ps1 bootstrap --config .\vault.toml.local --root C:\Temp\KV-Test
.\vaultctl.ps1 storage --config C:\Temp\KV-Test\vault.toml.local audit --json
.\vaultctl.ps1 doctor --config C:\Temp\KV-Test\vault.toml.local
.\vaultctl.ps1 validate --config C:\Temp\KV-Test\vault.toml.local
```

Непорожній реальний `E:\KnowledgeVault` без schema v2 marker блокується.
`--adopt` працює лише коли `storage.allow_adopt = true`; цей режим потребує
окремого review.

## Перенесення Git-репозиторіїв

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local plan `
  --source "C:\KnowledgeVault-Bootstrap\Brain_KnowledgeVault" `
  --source "<legacy-project-root>"
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local review `
  --plan "<repository_plan.jsonl>"
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local review `
  --plan "<repository_plan.jsonl>" --approve "<repository-id>"
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local apply `
  --plan "<repository_plan.jsonl>"
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local apply `
  --plan "<repository_plan.jsonl>" --execute
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local verify `
  --plan "<repository_plan.jsonl>"
```

`apply` без `--execute` є dry-run. Source не змінюється і не видаляється.
Репозиторій із reparse point або зайнятим destination не можна затвердити.

## Контроль зберігання Codex

```powershell
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local audit
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local cleanup-plan
```

`audit` перевіряє, що `CODEX_HOME` дорівнює
`E:\KnowledgeVault\60_Private\ToolState\Codex`, і класифікує дозволені,
protected, legacy та cleanup paths. `cleanup-plan` не видаляє файли та не має
execute-режиму.

## Backup

```powershell
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local preflight
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local init
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local run
.\vaultctl.ps1 backup --config E:\KnowledgeVault\vault.toml.local check
.\vaultctl.ps1 restore --config E:\KnowledgeVault\vault.toml.local drill
```

Будь-який FAIL у preflight блокує `init/run`. GitHub не є backup для
untracked/ignored файлів, локальних БД чи документів.

## Документація

- [Storage layout](STORAGE_LAYOUT.md)
- [Pre-wipe runbook](PRE_WIPE_RUNBOOK.md)
- [Disaster recovery](DISASTER_RECOVERY_RUNBOOK.md)
- [Windows data redirection](WINDOWS_DATA_REDIRECTION.md)
- [Codex storage policy](CODEX_STORAGE_POLICY.md)
- [Control-plane bootstrap model](CONTROL_PLANE_BOOTSTRAP.md)
- [Codex storage runbook](Automation/docs/CODEX_STORAGE_RUNBOOK.md)
- [User guide](USER_GUIDE.md)
- [Security policy](SECURITY.md)
- [Головна специфікація](plans.md)
- [ADR-002](Automation/docs/ADR-002_STORAGE_ROOT_AND_BACKUP.md)
- [ADR-003: Codex storage boundaries](Automation/docs/ADR-003_CODEX_STORAGE_BOUNDARIES.md)

Історичний аудит 2026-07-11 у `audit/` не переписується. Поточний стан
фіксується тестами, changelog і новими audit/manifests v2.
