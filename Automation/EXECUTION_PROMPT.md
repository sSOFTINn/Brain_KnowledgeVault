# Промпт для автономного обслуговування KnowledgeVault

```text
Твоє завдання — автономно перевірити й безпечно продовжити KnowledgeVault з
canonical control plane:
E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault.

Пріоритет джерел:
1. AGENTS.md
2. CODEX_STORAGE_POLICY.md
3. plans.md
4. AUDIT_STATUS.md
5. USER_GUIDE.md
6. Automation\README.md
7. SECURITY.md
8. Решта файлів — допоміжні.

Кодова baseline Phase 1–8 і v1.1 RAG/Wiki/Graph layer завершені. Файли
`audit` є незмінним історичним snapshot і не відображає статус
після remediation; KV-001–KV-016 закриті, KV-017/KV-018 залишаються зовнішніми
операційними рішеннями. Operational artifacts завжди перевіряй фактично.

Обов'язковий порядок:
1. Перевір Git root/remote/status і прочитай пріоритетні документи.
2. Запусти run_tests.ps1, doctor, validate та init --dry-run.
3. Перевір фактичний стан E:\KnowledgeVault.
4. Запусти index --integrity, rag sources smoke, graph stats і backup check.
5. Переглянь останні Runtime/runs, reports, verification та suggestions.
6. Перевір, що Phase 7 pilot містить рівно три approved source-файли,
   destination hashes/sidecars валідні, project card існує, а latest backup
   включає pilot critical paths.
7. Якщо потрібна міграція, працюй тільки через scan → report → plan → review →
   dry-run → copy → verify → backup → cleanup-plan.
8. Після змін повтори tests, doctor, validate, index --rebuild/index --integrity,
   extract --rebuild, rag rebuild, ask --sources-only, graph build/stats.
9. Для Codex storage запусти `codex-storage audit`; `cleanup-plan` створюй лише
   як manual-only evidence, без видалення.

Правила безпеки:
- Не скануй і не мігруй весь диск без окремого підтвердження.
- Не видаляй, не переміщуй і не перезаписуй source.
- Реальні операції над файлами — тільки copy + SHA-256 verification.
- cleanup-plan ніколи не є дозволом на автоматичне видалення.
- Не давай AI/extraction доступ до Private, confidential або restricted.
- Не послаблюй safe defaults у vault.toml.
- Не створюй scheduled tasks без окремого запиту.
- Канонічний CODEX_HOME —
  E:\KnowledgeVault\60_Private\ToolState\Codex; не використовуй його як
  migration source і не створюй нові проєкти в Documents\Codex.
- Не перенаправляй TEMP/TMP і не переміщуй вручну Codex AppData, runtime,
  binaries або SQLite.
- Не копіюй restic password у Vault, Git, Markdown або звіти.
- Не вмикай LLM або embeddings без явного рішення користувача.
- Не застосовуй wiki drafts до Vault без review; `wiki apply` спершу dry-run.

Працюй автономно в межах цих правил: реалізуй, тестуй і виправляй локально.
У фіналі повідом результати tests/doctor/validate/index/backup і всі змінені файли.
```
