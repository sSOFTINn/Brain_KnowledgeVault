# Windows data redirection

`vaultctl windows-data audit` є read-only. Він не змінює profile, registry,
environment variables або junctions.

| Path | Classification | Підтримуваний контроль |
|---|---|---|
| `.cache` | disposable-cache | application-specific |
| `.codex` | legacy/default location | `CODEX_HOME`; перевіряється окремим Codex audit |
| `.copilot` | manual-review | не підтверджено |
| `.dotnet` | must-stay-on-C | обмежено `DOTNET_CLI_HOME` |
| `.ipython` | supported-redirect | `IPYTHONDIR` |
| `.nuget\packages` | supported-redirect | `NUGET_PACKAGES` |
| `.vscode` | manual-review | `--extensions-dir`/profiles |
| `.vscode-shared` | manual-review | не підтверджено |

Для кожної зміни окремо:

1. визначити owner і supported setting;
2. створити encrypted backup важливої конфігурації;
3. змінити один path/env;
4. перезапустити application і виконати smoke test;
5. старий каталог залишити в карантині 14–30 днів;
6. видаляти лише окремим рішенням.

Заборонено переносити весь `AppData`/profile, комітити auth/session state або
створювати масові junction.

## Codex-specific policy

Канонічний `CODEX_HOME`:

```text
E:\KnowledgeVault\60_Private\ToolState\Codex
```

Перевірка:

```powershell
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local audit
```

Команда відокремлює:

- canonical приватний Codex state;
- довгострокові проєкти у `10_Projects`;
- rebuildable staging у `90_Runtime`;
- permanent evidence у `00_System\Audit`;
- protected AppData/binaries/runtimes, які повинні залишатися на C:;
- обмежений список cleanup-кандидатів.

Не перенаправляти загальні `TEMP`/`TMP` і не переносити вручну
`AppData\Roaming\Codex`, `AppData\Local\Codex`,
`AppData\Local\OpenAI\Codex`, `.cache\codex-runtimes` або внутрішні
SQLite-файли. Деталі: [CODEX_STORAGE_POLICY.md](CODEX_STORAGE_POLICY.md).
