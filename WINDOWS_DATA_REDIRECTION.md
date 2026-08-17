# Windows data redirection

`vaultctl windows-data audit` є read-only. Він не змінює profile, registry,
environment variables або junctions.

| Path | Classification | Підтримуваний контроль |
|---|---|---|
| `.cache` | disposable-cache | application-specific |
| `.codex` | supported-redirect | `CODEX_HOME` |
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
