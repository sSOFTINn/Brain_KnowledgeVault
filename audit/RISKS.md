# Реєстр ризиків

| ID | Ризик | Ймовірність | Вплив | Поточний контроль | Зниження |
|---|---|---|---|---|---|
| R-01 | Паралельні writers після втрати lock | Середня | Високий | lock-файл, але дефектний | KV-001 fix + concurrency tests |
| R-02 | Локальний секрет потрапляє у wiki draft | Середня | Високий | visibility policy | root allowlist + fail-closed |
| R-03 | Internal chunks відправляються на remote LLM | Середня | Високий | LLM off by default | loopback enforcement |
| R-04 | Галюцинації/вигадані citations | Висока при LLM on | Високий | prompt only | structured citations + threshold |
| R-05 | Втрата даних після останнього snapshot | Середня | Високий | manual restic | backup now + reminder + 3-2-1 |
| R-06 | Відмова диска E: | Низька-середня | Критичний | немає незалежної копії | окремий/off-site encrypted repository |
| R-07 | Один битий YAML блокує rebuild | Середня | Середній | CLI error handling | MetadataError + continue/fail-closed |
| R-08 | RAG performance деградує зі зростанням | Висока | Середній | 1000-note smoke | real incremental build |
| R-09 | Dependency drift ламає clean install | Середня | Середній | version ranges, tests | lock/hashes + CI |
| R-10 | Wiki apply виконує змінений після review текст | Низька-середня | Середній | append-only approval | approval SHA-256 |
| R-11 | Restic password ACL погіршується | Низька | Високий | ACL під час creation | doctor ACL check |
| R-12 | Невірне очікування semantic search | Висока | Середній | vectors table | hybrid retrieval або чесний FTS-only status |

## Прийняті ризики

- Manual backup без Task Scheduler — свідоме рішення, але потребує зовнішнього нагадування.
- Repository на E: — прийнятний лише як захист від логічних помилок.
- LLM/embeddings disabled by default — правильний тимчасовий контроль до завершення hardening.

