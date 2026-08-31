# Codex storage runbook

## 1. Межі операції

Цей runbook стосується лише локальних даних і робочих каталогів Codex.
ChatGPT conversations у хмарі, Downloads, загальний `Documents`, інші
програми та весь Windows-профіль не входять до scope.

Канонічні значення беруться з `[codex_storage]` у локальному
`vault.toml.local`. Production baseline:

```toml
[codex_storage]
enabled = true
home = "60_Private/ToolState/Codex"
projects = "10_Projects"
staging = "90_Runtime/Staging/CodexStorageMigration"
audit = "00_System/Audit/CodexStorageMigration"
cleanup_retention_days = 14
```

## 2. Read-only аудит

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local audit
```

PASS означає, що effective `CODEX_HOME` збігається з конфігурацією. Звіт
окремо показує canonical paths, protected Windows paths, legacy source та
cleanup candidates. Аудит не змінює environment variables, registry,
junctions або зовнішні файли.

## 3. План очищення

```powershell
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local `
  cleanup-plan --retention-days 14
```

Перевірити JSON у
`00_System\Audit\CodexStorageMigration\codex-storage-cleanup-plan-*.json`:

- кожний path належить до дозволеної категорії;
- `eligible=true` лише після retention;
- файл має SHA-256;
- дозволений cache-каталог має hash-backed `file_manifest`;
- `blocked_reason` порожній;
- reparse points відсутні;
- `execute_supported=false`.

Команда лише готує план. Вона не видаляє об'єкти.

## 4. Перенесення legacy workspace

Для `Documents\Codex` використовувати загальний verified-copy pipeline:

1. `scan` конкретного source, не всього диска;
2. `plan` і review усіх collisions/reparse points;
3. явне approval точних destination paths;
4. `apply --execute` лише copy-only;
5. `verify` з SHA-256;
6. restore check на окремому test path;
7. cleanup лише окремим рішенням після retention.

Не використовувати `Documents\Codex` як destination для нових робіт.

## 5. Заборонені дії

- не змінювати загальні `TEMP`/`TMP`;
- не створювати junction для всього AppData або CODEX_HOME;
- не копіювати junction/symlink/reparse point як каталог;
- не переносити вручну SQLite, auth, sessions, sandbox secrets, binaries або
  runtimes;
- не видаляти source під час apply;
- не комітити Codex state чи audit reports із секретними значеннями.

## 6. Перевірка після зміни

```powershell
.\vaultctl.ps1 doctor --config E:\KnowledgeVault\vault.toml.local
.\vaultctl.ps1 validate --config E:\KnowledgeVault\vault.toml.local
.\vaultctl.ps1 codex-storage --config E:\KnowledgeVault\vault.toml.local audit
.\run_tests.ps1
```

Завершення підтверджується лише коли `CODEX_HOME` збігається, canonical paths
існують, protected paths не змінювалися, source збережений, hashes збігаються,
а всі тести пройшли.
