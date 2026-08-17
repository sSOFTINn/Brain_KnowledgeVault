# Підсумок незалежного аудиту KnowledgeVault

Дата аудиту: 2026-07-11  
Об'єкт: `E:\Brain` і пов'язаний робочий стан `E:\KnowledgeVault` / `E:\KnowledgeVault_Backup`  
Ревізія: `d1e26fb` (`main`, синхронізована з `origin/main`)  
Режим: read-only для коду й користувацьких даних; створено лише звіти в `audit/`.

## Короткий висновок

KnowledgeVault має добрий безпечний фундамент: міграція працює через copy + SHA-256, source не видаляється, Private/restricted виключені з основних індексів, SQLite перебудовується атомарно, restic repository читається і проходить перевірку. Автоматизовані тести пройшли: **51/51**.

Водночас проєкт ще не варто вважати повністю production-ready v1.1. Підтверджено шість High-проблем: помилка володіння lock-файлом, можливість wiki summarize читати довільний зовнішній файл, відсутність примусового local-only endpoint для LLM, фактична відсутність hybrid/vector retrieval, відсутність перевірки LLM-цитат і застарілий backup, що не містить поточного проєкту користувача.

Поточний `vaultctl validate` також завершується помилкою через `Vault\02_Projects\Completed\ClearSUHF_Project-main\README.md` без YAML frontmatter.

## Оцінка готовності

- Безпечна міграція Phase 1-5: **готова для контрольованого локального використання**.
- Backup-механізм: **технічно справний, операційно прострочений**.
- RAG sources-only: **працює**, але `rag build` не є інкрементальним.
- LLM mode: **experimental**, не має заявленої citation validation і local endpoint enforcement.
- Embeddings/hybrid search: **не завершено**; vectors записуються, але retrieval їх не використовує.
- Поточний Vault: **невалідний** до виправлення одного Markdown-файла.

## Кількість знахідок

| Рівень | Кількість |
|---|---:|
| Critical | 0 |
| High | 6 |
| Medium | 8 |
| Low | 2 |
| Informational | 2 |
| Разом | 18 |

## Найважливіші висновки

1. `vault_lock()` видаляє lock іншого процесу після невдалої спроби захоплення.
2. `wiki summarize` приймає абсолютний шлях поза KnowledgeVault і копіює текст у Staging.
3. Увімкнений LLM може бути спрямований на довільний HTTP(S) endpoint; внутрішні chunks можуть залишити ПК.
4. Embeddings створюються, але cosine/vector retrieval ніде не викликається.
5. Відповідь Ollama не перевіряється на валідність citation IDs і не обмежується `context_limit_tokens`.
6. Єдиний snapshot датований 2026-06-29; `ClearSUHF_Project-main` та нові Obsidian-файли в ньому відсутні.
7. Поточна валідація Vault падає на README без frontmatter.
8. Некоректний YAML породжує необроблений `yaml.parser.ParserError`, блокуючи validate/RAG.
9. `rag build` лише позначає запуск як build, але виконує повний rebuild у нову БД.
10. 51 тести не ловлять ключову lock-помилку, бо тест перевіряє тільки відсутність lock після виходу.

## Рекомендований порядок дій

### Виправити негайно

1. Запустити новий encrypted backup до будь-яких змін і повторити restore drill.
2. Виправити ownership semantics у `locks.py` та додати regression test з трьома конкурентами.
3. Обмежити wiki summarize дозволеними root (`Vault`, дозволені `Assets`) і fail-closed policy.
4. Дозволяти LLM/embeddings endpoint лише loopback за замовчуванням; зовнішній endpoint — окрема небезпечна opt-in політика.
5. Додати реальну citation validation або залишити answer mode вимкненим.
6. Додати frontmatter до проблемного README або зберігати його поза керованою Markdown-зоною.

### Виправити найближчим часом

1. Реалізувати vector + FTS5 hybrid retrieval і тест, де семантичний результат неможливо знайти keyword-пошуком.
2. Реалізувати справжній incremental `rag build` за `content_hash` та GC.
3. Обробляти `yaml.YAMLError` і відмовляти fail-closed без аварії всього запуску.
4. Прив'язувати wiki approval до SHA-256 драфта і target.
5. Додати lock/requirements файл із hashes і мінімальний Windows CI.

## Що не варто змінювати без окремої потреби

- copy + SHA-256 + no-overwrite модель міграції;
- dry-run by default та append-only approvals/journals;
- atomic replacement rebuildable SQLite;
- централізовану visibility policy як архітектурну точку контролю;
- відокремлення Vault, Assets, Private, Runtime і Staging;
- LLM та embeddings disabled by default;
- ручний review перед wiki apply.

## Остаточні відповіді

1. **Обов'язково виправити:** KV-001-KV-007, передусім lock, межі читання wiki/LLM і актуальний backup.
2. **Бажано покращити:** incremental RAG, стійкість до битого YAML, content-bound approvals, dependency reproducibility, logging.
3. **Залишити без змін:** безпечну copy-модель, SHA-256 verification, атомарні індекси, local-first структуру та human-in-the-loop.

