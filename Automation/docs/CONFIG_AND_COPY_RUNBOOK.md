# Configuration and verified-copy runbook

## Єдиний verified-copy контракт

Routing із `Staging/Inbox` і migration plan використовують спільний primitive:

1. source має існувати й збігатися за очікуваними size/SHA-256;
2. collision destination обирається одним детермінованим алгоритмом;
3. копія створюється як унікальний `.partial` у destination directory;
4. partial перевіряється за size/SHA-256;
5. publish на Windows виконується без дозволу overwrite;
6. опублікований файл повторно перевіряється;
7. partial видаляється при будь-якій помилці, source не змінюється.

`migration.preserve_timestamps=true` використовує metadata-preserving copy;
`false` копіює лише bytes. `migration.verify_hash=false` і `overwrite=true`
залишаються забороненими safe-default validation.

## Effective configuration

- `scan.max_workers`: реальний розмір thread pool для hashing, 1-64.
- `routing.auto_threshold`: поріг автоматичної класифікації.
- `rag.enabled`: блокує build/query, коли `false`.
- `rag.embeddings`: за ввімкнення додає hybrid vector retrieval.
- `llm.context_limit_tokens`: обмежує sources prompt і Ollama `num_ctx`.
- `git.enabled`: вмикає read-only Git policy checks.
- `git.max_tracked_file_mb`: максимальний tracked-файл у Vault; перевищення є
  validation error.
- `logging.*`: command JSONL, redaction і rotation.

Перевірка effective behavior:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\vaultctl.ps1 doctor
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\vaultctl.ps1 validate
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
```

Git checks нічого не ініціалізують, не додають і не видаляють. Якщо
`git.enabled=true`, але Vault не належить Git worktree, `doctor` показує WARN.
