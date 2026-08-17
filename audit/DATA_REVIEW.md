# Огляд даних, SQLite та backup

## SQLite

- Catalog і RAG DB є derived/rebuildable, створюються у temporary file і замінюються атомарно.
- `PRAGMA integrity_check` використовується.
- SQL параметризований; очевидної SQL injection не виявлено.
- Schema marker (`schema_migrations`, `user_version`) є, але немає реальних forward migrations — поточна стратегія фактично rebuild.
- RAG `build` не incremental, vectors не читаються retrieval layer.

## Файли й міграція

- Source retention, no-overwrite, hash verification та journals реалізовані правильно.
- Sidecar створюється після verified copy.
- Safe-copy логіка дублюється у router/migrator, що підвищує ризик розходження.
- Поточний Vault має один невалідний Markdown без frontmatter.

## Backup

- Restic 0.19.0 repository check: PASS, 1 snapshot, no errors.
- Password ACL: owner current user, inheritance protected, одна explicit allow rule.
- Останній snapshot: 2026-06-29 23:09:38 +03:00.
- Snapshot не містить current `ClearSUHF_Project-main` і Obsidian workspace.
- `check --read-data-subset=5%` не є повною перевіркою всіх pack bytes.
- Restore drill перевіряє hashes трьох fixed files, але не активний project subset.
- Source і backup на E:, тому disk-failure protection відсутній.

## Рекомендації

1. Backup now, потім виправлення даних.
2. Додати freshness threshold у doctor (наприклад WARN >7 днів, FAIL configurable).
3. Configurable critical restore set.
4. Окремий encrypted repository на іншому носії.
5. Не включати derived DB/cache у backup — поточне виключення правильне.

