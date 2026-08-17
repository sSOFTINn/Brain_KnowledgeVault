# Поточний статус аудиту KnowledgeVault

Дата перевірки: 2026-07-13

Історичний аудит: `audit/`, ревізія `d1e26fb` від 2026-07-11

Поточна гілка remediation: `codex/audit-alignment-phase7`

## Як читати цей документ

Файли в `audit/` є незмінним доказовим snapshot стану на момент аудиту. Вони
навмисно зберігають початкові 51 тест, старий snapshot і знайдені дефекти.
Цей файл є поточним ledger: показує, що виправлено після аудиту, які перевірки
це доводять і які ризики залишаються відкритими.

Статуси:

- `CLOSED` — виправлення є в коді та покрите тестом або live acceptance;
- `ACCEPTED` — ризик відомий і свідомо прийнятий у поточній конфігурації;
- `DECISION REQUIRED` — потрібне рішення користувача або нова зовнішня умова.

## Resolution matrix

| ID | Статус | Поточний контроль / доказ |
|---|---|---|
| KV-001 | CLOSED | owner-token lock; failed/stale/token-replaced contender tests |
| KV-002 | CLOSED | Wiki allowlist для Vault і validated extracted Assets; external/Private/symlink negative tests |
| KV-003 | CLOSED | спільна loopback-only URL policy, credentials/query/redirects заборонені |
| KV-004 | CLOSED | optional hybrid FTS5 + cosine retrieval; vector-only режим відсутній |
| KV-005 | CLOSED | structured Ollama JSON, citation allowlist і context budget |
| KV-006 | CLOSED | freshness gate, актуальні encrypted snapshots, repository check і restore drill |
| KV-007 | CLOSED | ClearSUHF README має metadata; `validate --json` без errors |
| KV-008 | CLOSED | `MetadataError`, validator продовжує, AI/RAG policy відмовляє fail-closed |
| KV-009 | CLOSED | incremental manifest/content-hash build, GC і atomic full fallback |
| KV-010 | CLOSED | approval зв'язаний із SHA-256 draft і normalized target |
| KV-011 | CLOSED | doctor перевіряє SID-based protected ACL password file |
| KV-012 | CLOSED | exact `requirements.lock`; Windows CI на Python 3.11 і 3.14 |
| KV-013 | CLOSED | behavior tests для scan/Git/RAG/LLM exposed controls |
| KV-014 | CLOSED | configurable `backup.critical_paths` і multi-file SHA-256 restore drill |
| KV-015 | CLOSED | process-local PowerShell `-ExecutionPolicy Bypass` у quick start/runbooks |
| KV-016 | CLOSED | shared `verified_copy`; redacted rotating JSONL operation log |
| KV-017 | ACCEPTED | repository на `E:` захищає лише від логічних помилок; потрібен інший/off-site носій |
| KV-018 | DECISION REQUIRED | repository підтверджено приватним, але confidential-labelled PDF уже є в Git history; history rewrite не виконується автоматично |

## Етапи реалізації

- Phase 0–6: код і live acceptance завершені.
- Phase 7: повторно виконаний run `20260713T133411Z_65503bd4`; затверджено
  рівно `plans.md`, `USER_GUIDE.md` та `EXECUTE_KNOWLEDGEVAULT.md` у
  `Assets/Projects/PRJ-2026-001/docs/`. Destination SHA-256 і три sidecars
  перевірені; повторний apply обробив `0` rows; project card створена.
- Phase 8 та v1.1: реалізовані; LLM/embeddings залишаються disabled by default.

Після пілота `backup.critical_paths` розширено project card і sidecar
`plans.md.asset.md`; snapshot `a3e084ae` і restore drill підтвердили обидва.

## Acceptance 2026-07-13

```text
run_tests.ps1: 94 tests OK, 2 expected Windows symlink skips
doctor: PASS, operational WARN якщо Vault не є Git worktree
validate --json: no errors; encrypted Private backup warning only
init --dry-run: no writes
index --integrity: PASS
rag sources / ask --sources-only: PASS
graph stats: PASS
backup check: PASS
backup snapshot: a3e084ae; includes Phase 7 pilot and final migration report
backup restore-drill: PASS, 6 critical paths including project card and sidecar
GitHub Actions remediation PR: PASS on Python 3.11 and 3.14
```

## Незакриті зовнішні дії

1. Створити другу encrypted backup-копію на іншому фізичному або off-site носії.
2. Вирішити класифікацію `Ризики/Brain_KnowledgeVault_Analytical_Report.pdf`.
   Якщо документ справді конфіденційний, потрібна окремо погоджена ротація
   доступів і переписування Git history; простого видалення файла недостатньо.
