# Changelog

## v2.0.0 — storage platform

- додано schema v2 для єдиного canonical root `E:\KnowledgeVault` і
  declarative storage layout;
- додано idempotent `bootstrap --dry-run`, marker/volume identity та
  блокування непорожнього unmarked root;
- виправлено config precedence на користь explicit/local
  `vault.toml.local`;
- додано `storage audit`, repository-aware `import plan/review/apply/verify`,
  immutable plans, RESTORE_MAP та permanent audit trail;
- Git-проєкти копіюються як цілі одиниці разом із `.git`, untracked файлами,
  branches/tags/submodule/LFS/worktree metadata і перевіряються SHA-256 та
  `git fsck --full`;
- додано backup preflight для volume identity/health, required includes,
  distinct physical disks і free space; readback default підвищено до 100%;
- додано Windows profile read-only audit і runbooks для pre-wipe/disaster
  recovery/data redirection;
- розширено index/RAG scope v2 і fail-closed exclusions приватних,
  credential, build, runtime та quarantine paths;
- закрито unreachable reparse-point blocker у `policy.py`;
- ACL Restic password переведено на SID + `icacls` для стабільної роботи у
  Windows PowerShell/Python 3.11–3.14.

## Unreleased — audit alignment

- синхронізовано README, план, user guide, runbooks і execution prompts із
  незалежним аудитом та фактичним станом `main`;
- додано поточний `AUDIT_STATUS.md`, не змінюючи історичний `audit/` snapshot;
- задокументовано закриття KV-001–KV-016 та відкриті KV-017/KV-018;
- відновлено контрольований Phase 7 pilot і його backup/restore acceptance;
- додано root security policy та process-local PowerShell Bypass quick start.
- GitHub Actions оновлено до Node 24-compatible `checkout@v5` і
  `setup-python@v6`.

## v1.1 — security, data and RAG hardening

- owner-safe locks і fail-closed metadata policy;
- Wiki input allowlist та loopback-only Ollama/embeddings transport;
- structured citation validation і content-bound wiki approvals;
- incremental hybrid RAG із manifest/GC і atomic fallback;
- backup freshness/ACL/critical-path restore controls;
- exact dependency lock, Windows CI та redacted rotating JSONL logs;
- shared verified-copy primitive для routing і migration.

## v1.0 — completed baseline

- Phase 1–8 CLI baseline, synthetic fixtures та integration tests;
- SQLite/FTS5 catalog, extraction, suggestions, Obsidian Bases;
- encrypted manual restic backup і safe copy migration workflow.
