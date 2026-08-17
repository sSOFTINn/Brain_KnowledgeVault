# Backup and restore runbook

## Конфігурація

- tool: `restic`;
- repository: `E:\KnowledgeVault_Backup`;
- password file: `%LOCALAPPDATA%\KnowledgeVault\restic-password.txt`;
- retention: 14 daily, 8 weekly, 12 monthly;
- freshness gate: останній snapshot не старший за 7 днів;
- запуск: тільки вручну, Task Scheduler відсутній.

`backup.critical_paths` у `vault.toml` визначає файли, які обов'язково мають
існувати в backup та пройти SHA-256 restore drill. Relative paths рахуються від
кореня KnowledgeVault; абсолютні paths дозволені лише якщо вони входять до
`backup.includes`.

Repository на тому самому диску `E:` захищає від логічних помилок, але не від
повної відмови диска. Для 3-2-1 потрібна додаткова копія на іншому носії/off-site.
Це відкритий KV-017, а не властивість, яку може закрити локальний код.

## Перший запуск

```powershell
cd E:\Brain\Automation
.\vaultctl.ps1 backup init
.\vaultctl.ps1 backup run
.\vaultctl.ps1 backup check
.\vaultctl.ps1 backup restore-drill
```

`backup init` генерує криптографічний пароль, вимикає ACL inheritance і залишає
доступ поточному Windows-користувачу. Пароль не можна зберігати у Vault, Git або Markdown.

## Що включено

- `Vault`, `Assets`, `Private`, `Workspaces`;
- `vault.toml`, `MANIFEST.md`, `Runtime/runs`, `Logs`;
- `E:\Brain\Automation`.

Виключено: `.venv`, `__pycache__`, `Runtime/cache`, `Runtime/db`,
`Runtime/indexes`, `Staging`.

## Регулярні операції

```powershell
.\vaultctl.ps1 backup run
.\vaultctl.ps1 backup snapshots
.\vaultctl.ps1 backup check
```

Щомісяця запускайте `backup restore-drill`. Команда відновлює критичний набір
у тимчасову директорію, порівнює SHA-256 і прибирає лише створену нею temp-папку.
Відсутній або не включений critical path завершує drill помилкою, а не
пропускається мовчки.

`doctor` окремо перевіряє freshness snapshot і ACL password file. Прострочений
або відсутній snapshot дає `WARN`; порушений ACL password file дає `FAIL`.

Після контрольованого pilot/recovery додайте до робочого
`backup.critical_paths` project card і щонайменше один asset sidecar. Не
переносьте ці machine/data-specific paths у `vault.toml.example`, доки файли не
існують у новому Vault.

## Відмова або пошкодження

1. Не змінюйте repository вручну.
2. Запустіть `backup check`.
3. Перегляньте `backup snapshots`.
4. Виконайте `backup restore-drill`.
5. Для повного restore використовуйте restic у нову порожню директорію, не поверх
   робочого KnowledgeVault.

Sync і Git не є повноцінним backup.
