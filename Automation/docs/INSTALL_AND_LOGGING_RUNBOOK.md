# Install and logging runbook

## Відтворюване встановлення

Підтримувані версії: Python 3.11-3.14 на Windows. Runtime-залежності мають точні
версії в `requirements.lock`, а build backend зафіксований у `pyproject.toml`.

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
```

`Bypass` діє лише для запущеного процесу PowerShell і не змінює системну або
користувацьку Execution Policy. Не використовуйте `Set-ExecutionPolicy
Unrestricted` для запуску KnowledgeVault.

Для контрольованого оновлення залежностей змініть точні версії в
`requirements.lock`, виконайте встановлення в новій `.venv` та запустіть повний
набір тестів на всіх підтримуваних Python-версіях.

## Структурований журнал

Кожен коректно розібраний CLI-запуск додає один JSON-об'єкт до:

```text
E:\KnowledgeVault\Logs\vaultctl.jsonl
```

Журнал містить тільки UTC timestamp, PID, назву команди, статус, exit code і
тривалість. Аргументи, запити, відповіді, snippets, exception messages,
паролі, tokens і вміст файлів не записуються. Поля з чутливими назвами
додатково замінюються на `[REDACTED]`.

Rotation керується `[logging]` у `vault.toml`: `max_bytes` визначає максимальний
розмір активного JSONL, `backup_count` — кількість файлів `.1`, `.2` тощо.
Logging можна вимкнути через `enabled = false`; помилка журналювання ніколи не
повинна блокувати основну команду.
