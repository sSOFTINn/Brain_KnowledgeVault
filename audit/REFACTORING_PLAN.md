# Безпечний план покращень

## Етап 0 — Захист і фіксація стану

- **Мета:** не втратити current Vault.
- **Команди:** backup run/check/snapshots/restore-drill, git status, validate report.
- **Ризик:** низький; **DoD:** новий snapshot містить ClearSUHF artifact; hashes restore pass.
- **Відкат:** snapshots versioned; код не змінюється.

## Етап 1 — Security correctness

- **Файли:** `locks.py`, `policy.py`, `wiki.py`, `config.py`, `ask.py`, metadata handling, tests.
- **Зміни:** owner-safe lock; root allowlist; loopback endpoint; YAMLError normalization; draft hash; citation validator.
- **Ризик:** низький-середній; **DoD:** нові negative tests + 51 regression green.
- **Відкат:** один ізольований commit; LLM залишається off.

## Етап 2 — Дані й operations

- **Файли:** проблемний README, `backup.py`, doctor/validator, runbook.
- **Зміни:** валідний frontmatter; backup freshness/ACL checks; configurable restore set.
- **Ризик:** середній через користувацький файл; **DoD:** validate pass, restore project hash pass.
- **Відкат:** restore original file з backup; config-compatible changes.

## Етап 3 — Чесний RAG v1.1

- **Файли:** `rag/store.py`, `rag/embeddings.py`, tests/docs.
- **Зміни:** incremental manifest/GC; hybrid ranker; model/dimension compatibility; behavior for `rag.enabled`.
- **Ризик:** середній; DB rebuildable.
- **DoD:** unchanged corpus no re-embed, semantic fixture found, no private leakage, rebuild fallback.
- **Відкат:** embeddings disabled, full rebuild FTS path.

## Етап 4 — Reproducibility/observability

- **Файли:** dependency lock, CI workflow, logging helper, launch docs.
- **Зміни:** Windows test matrix, structured redacted JSONL, rotation, Bypass examples.
- **Ризик:** низький-середній.
- **DoD:** fresh clone install deterministic; CI green; logs contain no secret text.
- **Відкат:** optional logging/CI removal без зміни data format.

## Не робити в одному PR

- security fixes + dependency upgrades;
- hybrid retrieval + schema redesign + UI;
- history rewrite для PDF classification;
- refactor двох migration pipelines до закриття KV-001-KV-010.

