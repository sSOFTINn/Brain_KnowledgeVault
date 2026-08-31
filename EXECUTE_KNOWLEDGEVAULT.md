# Запуск і приймання KnowledgeVault v2

## Перевірка релізу

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
.\install.ps1
.\run_tests.ps1
.\vaultctl.ps1 bootstrap --config .\vault.toml.example `
  --root C:\Temp\KnowledgeVault-v2 --dry-run
```

Після dry-run створіть disposable root, виконайте `storage audit`, `doctor`,
`validate`, repository import тестового Git-проєкту, `index --integrity`,
backup на disposable окремому носії та `restore drill`.

## Реальна послідовність

1. Завершити `PRE_WIPE_RUNBOOK.md` і зберегти докази Gate 1–5.
2. Отримати tagged release або offline recovery bundle.
3. Запустити `bootstrap --dry-run` з тимчасового шляху поза `E:`.
4. Виконати bootstrap у порожній `E:\KnowledgeVault`.
5. Розмістити control-plane checkout у
   `00_System\ControlPlane\Brain_KnowledgeVault`.
6. Виконати `storage audit`, `doctor` і `validate`.
7. Налаштувати `CODEX_HOME` на `60_Private\ToolState\Codex` і виконати
   `codex-storage audit`.
8. Створити repository import plan із verified snapshot.
9. Затвердити кожний destination окремо, виконати dry-run, apply і verify.
10. Перебудувати SQLite/FTS5/RAG.
11. Виконати новий encrypted backup і restore drill.

Жоден крок не видаляє source. Форматування `E:` не входить до CLI і
виконується лише вручну після повного GO-checklist.

Див. [USER_GUIDE.md](USER_GUIDE.md), [STORAGE_LAYOUT.md](STORAGE_LAYOUT.md),
[CONTROL_PLANE_BOOTSTRAP.md](CONTROL_PLANE_BOOTSTRAP.md),
[CODEX_STORAGE_POLICY.md](CODEX_STORAGE_POLICY.md),
[DISASTER_RECOVERY_RUNBOOK.md](DISASTER_RECOVERY_RUNBOOK.md) і
[SECURITY.md](SECURITY.md).
