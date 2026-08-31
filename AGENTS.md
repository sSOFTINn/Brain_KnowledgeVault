# Правила роботи з Brain_KnowledgeVault

## Призначення репозиторію

Цей репозиторій є control plane для `E:\KnowledgeVault`. Він містить правила,
CLI, тести та runbooks. Канонічні користувацькі дані, секрети, локальний стан
інструментів і резервні копії не комітяться до Git.

## Обов'язкові межі зберігання

- захищений `CODEX_HOME`: `E:\KnowledgeVault\60_Private\ToolState\Codex`;
- довгострокові Git-проєкти: відповідна папка в
  `E:\KnowledgeVault\10_Projects`;
- тимчасові міграційні копії Codex:
  `E:\KnowledgeVault\90_Runtime\Staging\CodexStorageMigration`;
- manifests, approvals і докази перевірки:
  `E:\KnowledgeVault\00_System\Audit\CodexStorageMigration`;
- `C:\Users\Nitfo\Documents\Codex` є лише legacy-source. Не створювати там
  нові проєкти.

Не переносити, не видаляти й не використовувати як migration source чинний
`CODEX_HOME`. Не перенаправляти загальні Windows `TEMP`/`TMP`. Не переміщувати
вручну `AppData\Roaming\Codex`, `AppData\Local\Codex`,
`AppData\Local\OpenAI\Codex`, `.cache\codex-runtimes`, системні binaries,
runtimes або внутрішні SQLite-файли.

## Безпечний процес

Для будь-якої міграції або очищення дотримуватися послідовності:

1. read-only інвентаризація;
2. immutable DryRun/plan із SHA-256;
3. явне підтвердження точних targets;
4. copy-only apply без overwrite;
5. повторна SHA-256 перевірка й restore check;
6. окремо підтверджене очищення після retention.

Звичайний `apply` ніколи не видаляє source. Reparse points, junctions,
symlinks і `node_modules` не обходити й не копіювати як звичайні каталоги.
Невідомі об'єкти класифікувати як `manual-review`, а не як сміття.

## Codex storage automation

Перед змінами запускати:

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local audit
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local cleanup-plan
```

`audit` лише читає зовнішні шляхи й записує evidence у KnowledgeVault.
`cleanup-plan` не має execute-режиму. Фактичне видалення можливе лише після
окремого підтвердження переліку шляхів користувачем.

## Розробка й перевірка

- Python: 3.11+;
- основні зміни автоматизації супроводжувати unit/integration тестами;
- запускати `Automation\run_tests.ps1` перед завершенням;
- після змін конфігурації перевіряти `bootstrap --dry-run`, `doctor`,
  `validate` і відповідний read-only audit;
- не змінювати історичні файли в `audit/`; новий стан фіксувати в changelog,
  нових docs та timestamped evidence;
- не push, не переписувати Git history і не видаляти remote/local refs без
  прямого дозволу користувача.

Робота завершена лише коли diff перевірений, тести зелені, джерела збережені,
а документація й CLI описують однакову фактичну поведінку.
