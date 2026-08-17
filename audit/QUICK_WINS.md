# Швидкі покращення

## До 1 години

1. Зробити актуальний `backup run`, `backup check`, `backup restore-drill`.
2. Додати frontmatter до проблемного ClearSUHF README після backup.
3. Виправити `vault_lock` через локальний `acquired` flag.
4. Додати `yaml.YAMLError` до єдиного parser wrapper.
5. Заборонити `wiki summarize` для path поза allowlist.
6. Додати loopback URL validation для Ollama.
7. Дописати Bypass-команди в Quick Start без зміни системної Execution Policy.

## До 1 дня

1. Citation allowlist + failure on unknown citation.
2. SHA-256 binding для wiki approval.
3. Doctor check для password ACL і freshness останнього snapshot.
4. Regression tests для всіх трьох відтворених security сценаріїв.
5. Позначити embeddings як storage-only experimental, доки hybrid retrieval не реалізовано.

## Висока користь, середня складність

1. Реальний incremental RAG із content hash і GC.
2. Hybrid ranker FTS5 + cosine + metadata filters.
3. Windows CI та lock/constraints dependencies.

