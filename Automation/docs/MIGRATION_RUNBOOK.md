# Migration runbook

## Безпечна послідовність

```text
scan -> report -> plan -> review -> dry-run -> approved copy -> verify -> backup -> cleanup-plan
```

## 1. Scan

```powershell
.\vaultctl.ps1 scan "E:\SpecificFolder" --hash-mode duplicates
```

Не скануйте корінь диска. Перегляньте `report.md` та `errors.jsonl`.

## 2. Plan

```powershell
.\vaultctl.ps1 plan --run "<run-id>"
```

Перегляньте `migration_plan.md` і `conflicts.md`. Low-confidence,
privacy-risk та collision записи не можна затверджувати пакетно.

## 3. Review

```powershell
.\vaultctl.ps1 review `
  --plan "E:\KnowledgeVault\Runtime\runs\<run-id>\migration_plan.jsonl"
```

Затверджуйте по одному рядку, перевіряючи destination.

## 4. Dry-run та execute

```powershell
.\vaultctl.ps1 apply --plan "<migration_plan.jsonl>"
.\vaultctl.ps1 apply --plan "<migration_plan.jsonl>" --execute
```

Після execute перевірте `migration_apply_journal.jsonl`,
`verification.jsonl`, `apply_summary.json` і `rollback_manifest.json`.

## 5. Report, verify і backup

```powershell
.\vaultctl.ps1 report --run "<run-id>"
.\vaultctl.ps1 verify --run "<run-id>"
.\vaultctl.ps1 backup run
.\vaultctl.ps1 backup check
```

## 6. Cleanup plan

Не раніше ніж через 30 днів і лише після успішного backup:

```powershell
.\vaultctl.ps1 cleanup-plan --run "<run-id>" --retention-days 30
```

Source не видаляється. `cleanup-plan` — лише список кандидатів для окремого ручного
рішення; автоматичного cleanup немає.

## Контрольований Phase 7 pilot

Pilot KnowledgeVault обмежений рівно трьома файлами з кореня `E:\Brain`:
`plans.md`, `USER_GUIDE.md`, `EXECUTE_KNOWLEDGEVAULT.md`. Для recovery після
втрати Vault виконайте новий `scan --hash-mode all`, новий deterministic plan,
затвердьте лише ці три row з destination
`Assets/Projects/PRJ-2026-001/docs/`, а потім dry-run, execute, повторний apply,
`verify`, `validate`, backup і restore drill. Старі approvals не перевикористовуйте,
якщо source hashes змінилися.
