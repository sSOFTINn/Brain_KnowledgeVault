# Прогалини тестування

Поточний результат: 51/51 tests OK за 23.9 s. Набір сильний для Phase 1-5, але green suite не доводить заявлені v1.1 invariants.

## Критичні відсутні сценарії

- failed lock contender не повинен видаляти owner lock;
- третій contender має залишатися заблокованим;
- wiki summarize відхиляє абсолютний path поза Vault/allowed Assets;
- remote LLM URL відхиляється за default policy;
- citation IDs в Ollama response перевіряються;
- malformed YAML не аварійно завершує весь validate/RAG;
- approval стає невалідним після зміни draft;
- актуальний backup містить активний project artifact.

## Функціональні прогалини

- semantic-only query доводить використання vectors;
- hybrid score combines FTS і cosine;
- `rag build` не обчислює embeddings для unchanged chunks;
- `rag.enabled=false` реально блокує build/query;
- `context_limit_tokens` реально обмежує context pack;
- GraphML проходить schema-aware consumer, а не лише `is_file()`;
- restore drill працює при clone не в `E:\Brain`.

## Environment/operations

- fresh venv Python 3.11, 3.12, 3.14;
- PowerShell 5.1 і 7 із Restricted policy;
- interrupted backup/rebuild;
- disk-full і read-only destination;
- long paths близько/понад 240 символів;
- ACL drift password file;
- dependency audit у CI.

## Недолік поточного lock test

`test_lock_blocks_parallel_writer_and_cleans_up` перевіряє лише `LockError` і відсутність lock після outer exit. Сам дефект видаляє lock під час inner failure, тому тест помилково проходить. Треба assert `lock_path.exists()` одразу після inner exception, ще всередині owner context.

