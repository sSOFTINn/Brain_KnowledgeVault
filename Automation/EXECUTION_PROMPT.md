# Промпт для автономного обслуговування KnowledgeVault

```text
Твоє завдання — автономно перевірити й безпечно продовжити KnowledgeVault у E:\Brain.

Пріоритет джерел:
1. E:\Brain\plans.md
2. E:\Brain\AUDIT_STATUS.md
3. E:\Brain\USER_GUIDE.md
4. E:\Brain\Automation\README.md
5. E:\Brain\SECURITY.md
6. Решта файлів — допоміжні.

Кодова baseline Phase 1–8 і v1.1 RAG/Wiki/Graph layer завершені. Файли
`E:\Brain\audit` є незмінним історичним snapshot і не відображають статус
після remediation; KV-001–KV-016 закриті, KV-017/KV-018 залишаються зовнішніми
операційними рішеннями. Operational artifacts завжди перевіряй фактично.

Обов'язковий порядок:
1. Проінвентаризуй E:\Brain і прочитай п'ять головних документів.
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

Правила безпеки:
- Не скануй і не мігруй весь диск без окремого підтвердження.
- Не видаляй, не переміщуй і не перезаписуй source.
- Реальні операції над файлами — тільки copy + SHA-256 verification.
- cleanup-plan ніколи не є дозволом на автоматичне видалення.
- Не давай AI/extraction доступ до Private, confidential або restricted.
- Не послаблюй safe defaults у vault.toml.
- Не створюй scheduled tasks без окремого запиту.
- Не копіюй restic password у Vault, Git, Markdown або звіти.
- Не вмикай LLM або embeddings без явного рішення користувача.
- Не застосовуй wiki drafts до Vault без review; `wiki apply` спершу dry-run.

Працюй автономно в межах цих правил: реалізуй, тестуй і виправляй локально.
У фіналі повідом результати tests/doctor/validate/index/backup і всі змінені файли.
```
