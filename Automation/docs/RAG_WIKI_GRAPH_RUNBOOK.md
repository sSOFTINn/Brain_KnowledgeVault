# RAG / Wiki / Graph Runbook

## Build і rebuild

```powershell
cd E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
.\vaultctl.ps1 extract --rebuild
.\vaultctl.ps1 index --rebuild
.\vaultctl.ps1 rag build
.\vaultctl.ps1 graph build
```

Для звичайного оновлення запускайте `rag build`. Він використовує manifest і
content hashes, повторно chunk/embed лише змінені sources, виконує GC для
missing або вже недозволених policy-файлів і перевикористовує vectors тільки
коли provider/model/dimension збігаються.

Повна перебудова:

```powershell
.\vaultctl.ps1 rag rebuild
```

Writer працює з тимчасовою SQLite БД. Live-файл замінюється атомарно лише після
`PRAGMA integrity_check`; пошкоджений incremental input автоматично переходить
до full fallback. У підсумку `rag build` перевірте лічильники `changed`,
`reused`, `removed`.

## Sources-only answers

```powershell
.\vaultctl.ps1 rag sources "ризики міграції"
.\vaultctl.ps1 ask "які головні ризики KnowledgeVault?" --sources-only
```

Якщо джерел недостатньо, система має сказати це явно. LLM не викликається в режимі `--sources-only`.

За ввімкнених embeddings retrieval є гібридним: FTS5 і cosine similarity
об'єднуються rank fusion. Vector-only пошуку немає. Зміна model або dimension
спричиняє контрольоване переобчислення vectors; embeddings залишаються off за
замовчуванням. `[rag].enabled = false` блокує і build, і query.

Answer mode дозволяє лише Ollama на loopback-адресі цього ПК. LAN/cloud URLs,
credentials у URL і HTTP redirects блокуються. Ollama повертає structured JSON;
кожен citation `chunk_id` перевіряється проти фактично retrieved sources.

## Wiki drafts

```powershell
.\vaultctl.ps1 wiki suggest-links
.\vaultctl.ps1 wiki draft-concept "KnowledgeVault"
.\vaultctl.ps1 wiki draft-moc "Local-first systems"
```

Drafts зберігаються в `E:\KnowledgeVault\Staging\WikiDrafts\<run-id>\`.
`wiki summarize` приймає лише валідний Markdown у Vault або asset із валідним
sidecar та наявним `Runtime/cache/extracted/<sha256>.txt`. Для asset без cache
спочатку запустіть `extract --rebuild`. External paths і raw binary не читаються.
Застосування до Vault:

```powershell
.\vaultctl.ps1 wiki approve --draft "<run-id>" --target "04_Knowledge/Concepts/New.md"
.\vaultctl.ps1 wiki apply --draft "<run-id>"
```

Approval прив'язаний до SHA-256 draft і поточного target. Якщо один із них
змінено, виконайте approve повторно. Без `--execute` це dry-run. Якщо target
існує, створюється diff для ручного перегляду; автоматичного overwrite немає.

## Graph

```powershell
.\vaultctl.ps1 graph build
.\vaultctl.ps1 graph neighbors "KnowledgeVault"
.\vaultctl.ps1 graph export --format json
.\vaultctl.ps1 graph export --format mermaid
.\vaultctl.ps1 graph export --format graphml
.\vaultctl.ps1 graph stats
```

Artifacts: `E:\KnowledgeVault\Runtime\graph\`.

## Safety checks

- `Private/`, `restricted`, `confidential` не читаються RAG/LLM/Wiki/Graph.
- Embeddings disabled by default.
- LLM disabled by default.
- Cloud AI не використовується.
- Ollama працює тільки через loopback; redirects заборонені.
- Missing/malformed frontmatter і sidecar блокуються fail-closed.
- Усі індекси й graph artifacts rebuildable.
