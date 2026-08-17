# Disaster recovery runbook

## Пріоритет

1. Зупинити записи у пошкоджений root.
2. Не запускати cleanup, mirror або повторне форматування.
3. Зберегти журнали, device identity й останні manifests.
4. Працювати з копією snapshot, а не з єдиним backup.

## Повна втрата `E:`

1. Замінити/підготувати справний NTFS-том і звірити identity.
2. Отримати tagged v2 release з GitHub або `00_RecoveryKit`.
3. Створити локальний `vault.toml.local` з новим serial/label.
4. Виконати `bootstrap --dry-run`, потім bootstrap у порожній root.
5. Виконати `storage audit`, `doctor` і `validate`.
6. Відновити `00_System`, крім автоматичного overwrite нового ControlPlane.
7. Відновлювати `10_Projects` → `20_Knowledge` → `30_Documents` →
   `40_Media` → `50_Resources` → `60_Private` → `70_Inbox` → `80_Archive`.
8. Перевірити included count/bytes/SHA-256 і `RESTORE_MAP.csv`.
9. Для кожного repo: HEAD, remotes, status, branches/tags, LFS/submodules,
   `git fsck --full` і smoke test.
10. Перебудувати catalog/RAG/graph і виконати новий backup + restore drill.

## Перерваний import

- повторно запустити apply з тим самим immutable plan;
- journal пропускає вже завершені repository IDs/rows;
- destination з помилкою не перезаписувати;
- частково створений repository вважати quarantine до окремої перевірки;
- source залишається канонічним до повного verify.

## Пошкоджений backup

- не ремонтувати носій із записом, доки унікальні дані не скопійовані/клоновані;
- переключитися на другу незалежну копію;
- зафіксувати missing/read errors;
- після відновлення замінити носій або повністю перевірити його до повторного
  використання.

## Rollback

До wipe rollback — продовження роботи зі старих шляхів. Після wipe exact
rollback відновлює первинне дерево PREWIPE за `OriginalPath` із
`RESTORE_MAP.csv` у тимчасовий root; новий import виправляється лише на
тестових даних.
