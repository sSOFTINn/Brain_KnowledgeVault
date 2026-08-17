# Журнал аудиту

## Scope і припущення

- Перевірено весь tracked repository `E:\Brain`, runtime Python modules, tests, docs/configs, risk Markdown і 4-сторінковий PDF.
- Перевірено фактичний health стан `E:\KnowledgeVault` та read-only стан restic repository.
- Не сканувався весь диск, не мігрувалися й не видалялися файли.
- Не виконувалися commit/push/merge або dependency installation/update.
- Audit artifacts — єдині створені файли в repository.

## Ключові команди

```powershell
git status --short --branch
git log -1 --oneline --decorate
rg --files
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\vaultctl.ps1 doctor
powershell -NoProfile -ExecutionPolicy Bypass -File .\vaultctl.ps1 validate
powershell -NoProfile -ExecutionPolicy Bypass -File .\vaultctl.ps1 backup check
powershell -NoProfile -ExecutionPolicy Bypass -File .\vaultctl.ps1 backup snapshots
.venv\Scripts\python.exe -m pip check
```

Також виконані targeted synthetic PoCs у `TemporaryDirectory` для lock ownership, malformed YAML, wiki external path і external LLM URL. Реальні секрети не читалися.

## Результати

- Tests: 51 passed / 0 failed.
- Doctor: PASS.
- Validate: FAIL, один missing frontmatter; expected encrypted-Private warning.
- Restic check: PASS, no errors, 1 snapshot.
- Restore repository: latest snapshot доступний, але не містить current ClearSUHF project.
- Dependencies: pip check PASS; OSV point-in-time query — 0 advisories for installed Python packages.
- Git до створення audit artifacts: clean `main...origin/main`.

## Обмеження

- Codex Security preflight: `incomplete`; delegation/multi-agent runtime недоступний. Тому security section є повним однопрохідним parent-agent review, але не заявляється як exhaustive multi-agent scan.
- Не проводилися destructive fault injection, physical disk failure, ransomware simulation або повний restic `--read-data`.
- Optional Ollama не запускався; LLM findings підтверджені статичним потоком даних і synthetic config, не реальною передачею chunks.
- GitHub visibility repository не підтверджена; для confidential PDF зафіксовано лише факт Git tracking/remote history.

## Відсутні матеріали

У repository немає окремих `ARCHITECTURE.md`, `DECISIONS.md`, `TASKS.md`, `CHANGELOG.md`, `SECURITY.md`, CI workflow або dependency lock. Їхню роль частково виконують `plans.md`, ADR, runbooks і цей audit.

