# Security and privacy checklist

- [ ] Перевірено актуальний `AUDIT_STATUS.md`, а не лише історичний `audit/` snapshot.
- [ ] `Private/` не передається AI автоматично.
- [ ] `allow_ai_confidential = false`.
- [ ] `follow_symlinks = false`.
- [ ] `default_mode = "copy"`.
- [ ] `verify_hash = true`.
- [ ] `overwrite = false`.
- [ ] `preserve_source = true`.
- [ ] Secrets, `.env`, ключі й токени відсутні у Vault.
- [ ] Scan запускається лише на явно вибраній папці.
- [ ] Перед execute переглянуто report, conflicts і migration plan.
- [ ] Затверджено лише конкретні migration rows.
- [ ] Після execute перевірено verification log.
- [ ] Backup перевірено через restore drill.
- [ ] Останній snapshot містить поточні активні проєкти.
- [ ] `doctor` підтверджує protected ACL restic password file.
- [ ] Ollama endpoint використовує лише `localhost`, `127.0.0.1` або `::1`.
- [ ] LLM-відповідь має перевірені citations на retrieved `chunk_id`.
- [ ] `wiki summarize` не отримує external, Private, template або raw binary path.
- [ ] Wiki draft і target не змінювалися після `wiki approve`.
- [ ] Cleanup source виконується лише окремим ручним рішенням.
- [ ] Effective `CODEX_HOME` дорівнює `60_Private\ToolState\Codex`.
- [ ] `codex-storage audit` не показує drift або невідомі legacy paths.
- [ ] `codex-storage cleanup-plan` має `execute_supported=false`; підтверджені
      targets належать лише до дозволених cleanup-категорій.
- [ ] Codex AppData, `.cache\codex-runtimes`, binaries, runtimes, SQLite і
      загальні `TEMP`/`TMP` не перенесені й не видалені вручну.
- [ ] Confidential-labelled файли не додаються в Git без явної classification/access review.
- [ ] Для KV-017 є окремий план другої encrypted копії на іншому/off-site носії.
