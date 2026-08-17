# Security policy

## Межі

Цей Git-репозиторій є control plane. Канонічні дані знаходяться поза Git у
`E:\KnowledgeVault`, а encrypted backup — у `F:\Backup_E`. GitHub не замінює
backup локальних документів, БД, untracked/ignored файлів або ключів.

## Незмінні гарантії

- лише copy; source не видаляється;
- overwrite заборонений;
- план незмінний, approvals append-only;
- source і destination перевіряються SHA-256;
- repository переноситься разом із `.git` і перевіряється `git fsck --full`;
- schema v2 marker та volume identity перевіряються перед apply;
- symlink, junction і reparse point не обходяться; repository з ними
  блокується до окремого рішення;
- непорожній unmarked root блокується;
- backup блокується при missing include, unhealthy volume, нестачі місця або
  однаковому фізичному диску source/repository;
- `60_Private`, `restricted`, `confidential`, credentials і runtime не
  читаються RAG/LLM/Wiki/Graph;
- LLM/embeddings вимкнені; Ollama — лише loopback, redirects заборонені;
- Restic password зберігається поза Vault/Git і захищений ACL для поточного
  Windows SID.

## Секрети

Не комітьте `vault.toml.local`, `.env`, tokens, private keys, BitLocker/Restic
recovery data, Codex auth/session state або реальні користувацькі fixtures.
Постійні audit/manifests не повинні містити secret values чи вміст документів.

Відомий історичний ризик KV-018: tracked PDF у `Ризики/` має confidential
label. Видалення з working tree не прибирає Git history. History rewrite
дозволений лише окремим рішенням із backup і координацією.

## Backup boundary

Default repository: `F:\Backup_E\20_ResticRepository`. Носій повинен мати
`Healthy / OK`, стабільне підключення і відрізнятися від source фізично.
Перед wipe потрібна ще одна незалежна перевірена encrypted копія. Backup
snapshots не можна змінювати після фінальної верифікації.

## Повідомлення

Не публікуйте секрети або exploit data у відкритому issue. Для приватного
репозиторію використовуйте private GitHub security advisory або прямий канал
власника. Додайте affected path, boundary, мінімальне відтворення і фактичний
результат без реальних даних.
