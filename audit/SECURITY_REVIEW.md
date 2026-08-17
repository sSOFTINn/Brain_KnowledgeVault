# Огляд безпеки

## Модель загроз

Assets: користувацькі файли, Private, metadata/visibility, restic password, backup repository, migration journals.  
Attackers/failures: випадковий користувацький input, malicious file/frontmatter, локальний процес, помилковий config, compromised/misconfigured LLM endpoint, disk failure.  
Trust boundaries: Staging/source filesystem, YAML parser, policy module, SQLite derived DB, subprocess restic, HTTP Ollama.

## Сильні сторони

- `yaml.safe_load`, не unsafe loader.
- subprocess запускається list-аргументами без shell.
- path containment застосовується до migration destinations.
- copy -> SHA-256 -> atomic replace; overwrite disabled.
- Private/restricted/confidential default exclusion.
- LLM та embeddings disabled by default.
- Password не в Git/Vault; фактичний ACL protected і має лише поточного користувача.
- Secret filename scan не виявив tracked key/password/env files.

## Reportable findings

- KV-001 lock ownership bug.
- KV-002 arbitrary local file read through wiki summarize.
- KV-003 remote LLM endpoint accepted.
- KV-005 no citation validation.
- KV-008 malformed YAML availability issue.
- KV-010 approval TOCTOU.
- KV-011 ACL drift not monitored.

## Перевірки

- Synthetic PoCs використовували лише temporary directories і synthetic secret.
- Реальні password bytes не читалися і не виводилися.
- Exploits, destructive migration та зовнішня передача даних не виконувалися.
- Повний Codex Security multi-agent scan не заявляється: preflight `incomplete`, delegation unavailable. Виконано однопрохідний parent-agent security review усіх runtime-модулів.

## Рекомендована security baseline

1. Fail-closed metadata policy.
2. Root allowlist для кожного AI purpose.
3. Local-only network policy за default.
4. Content-bound human approval.
5. Ownership-safe locks.
6. Fresh backup gate перед destructive/manual maintenance.

