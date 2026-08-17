# Pre-wipe runbook

Цей checklist не форматує диски. Один FAIL означає NO-GO.

## Gate 1 — inventory

- [ ] applications, що пишуть на `E:`, закриті;
- [ ] є inventory JSON/CSV всього `E:`, hidden/system і reparse metadata;
- [ ] кожний root classified: KEEP / REGENERABLE / EXCLUDE / UNKNOWN;
- [ ] `git-repositories.csv` містить remote, HEAD, branch, dirty/untracked,
      ignored, branches/tags, submodules, LFS і worktrees;
- [ ] AccessDenied/read/path-too-long/enumeration errors = 0;
- [ ] unresolved = 0 або всі UNKNOWN включені до backup.

## Gate 2 — backup носій

- [ ] `F:` має `HealthStatus=Healthy` і `OperationalStatus=OK`;
- [ ] кабель/порт пройшли тривале copy/readback без disconnect/ERROR 55;
- [ ] BitLocker/Restic recovery data збережені поза `E:`/`F:`;
- [ ] `vaultctl backup preflight` = PASS.

## Gate 3 — release v2

- [ ] всі тести зелені;
- [ ] reparse/ACL/path safety tests пройшли;
- [ ] disposable bootstrap, повторний bootstrap, doctor і validate = PASS;
- [ ] repository import з dirty/untracked fixture = PASS;
- [ ] tagged release і offline bundle перевірені.

## Gate 4 — дві незалежні копії

- [ ] обидві encrypted копії побудовані з одного frozen source-manifest;
- [ ] file count/bytes/SHA-256 mismatch = 0;
- [ ] probe restore відкриває PDF/DOCX/XLSX/images/archives/SQLite;
- [ ] кожний repository проходить `git fsck --full` і основний smoke test;
- [ ] друга копія знаходиться на іншому фізичному/off-site носії.

## Gate 5 — фінальний GO

- [ ] device identity `E:` звірено за model/serial/size/label;
- [ ] немає pagefile/system dependency від `E:`;
- [ ] required EFS/ACL/ADS/hardlinks збережені або втрату погоджено;
- [ ] snapshots після verification не змінювалися;
- [ ] final delta і обидві verification повторені після останньої зміни source;
- [ ] усі докази збережені поза диском, який перебудовується.

Лише після цього користувач вручну виконує форматування, фізично
від’єднавши backup-носії. CLI навмисно не має destructive-команди.
