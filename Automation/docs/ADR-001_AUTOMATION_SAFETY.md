# ADR-001: Copy-only automation with immutable plans

## Status

Accepted — 2026-06-20.

## Context

KnowledgeVault працює з існуючими файлами користувача. Помилка автоматизації
може спричинити втрату даних або неправильну класифікацію.

## Decision

- Scan є read-only.
- Scan і migration plans є immutable.
- Approvals зберігаються append-only окремо.
- Apply обробляє лише approved rows.
- Файли копіюються через `.partial` із SHA-256 verification.
- Source не переміщується і не видаляється.
- Rollback manifest є інформаційним і не видаляє файли автоматично.

## Consequences

Міграція повільніша й потребує додаткового місця, але залишається
відновлюваною та контрольованою.
