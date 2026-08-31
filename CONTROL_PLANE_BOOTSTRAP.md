# Модель bootstrap та canonical control plane

## Чому немає циклічної залежності

`Brain_KnowledgeVault` має дві різні ролі на різних етапах:

1. **Bootstrap checkout** — тимчасова копія репозиторію поза майбутнім
   `E:\KnowledgeVault`. Вона створює й перевіряє schema v2 root.
2. **Canonical control plane** — перевірена повна Git-копія в
   `E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault`, з якої
   виконуються всі подальші операції.

Bootstrap checkout не є канонічними даними й не видаляється до завершення
SHA-256, `git fsck` та restore verification canonical copy.

## Нове сховище

Приклад тимчасового checkout:

```powershell
git clone https://github.com/sSOFTINn/Brain_KnowledgeVault.git `
  C:\KnowledgeVault-Bootstrap\Brain_KnowledgeVault
cd C:\KnowledgeVault-Bootstrap\Brain_KnowledgeVault\Automation
Copy-Item .\vault.toml.example .\vault.toml.local
.\vaultctl.ps1 bootstrap --config .\vault.toml.local --root E:\KnowledgeVault --dry-run
.\vaultctl.ps1 bootstrap --config .\vault.toml.local --root E:\KnowledgeVault
```

Після bootstrap створити repository plan. `vaultctl` розпізнає remote
`sSOFTINn/Brain_KnowledgeVault` і призначає destination у ControlPlane:

```powershell
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local plan `
  --source C:\KnowledgeVault-Bootstrap\Brain_KnowledgeVault
.\vaultctl.ps1 import --config E:\KnowledgeVault\vault.toml.local review `
  --plan "<repository_plan.jsonl>"
```

Далі потрібні явне approval repository ID, copy-only `apply --execute` і
`verify`. Cleanup bootstrap checkout є окремою операцією після retention.

## Уже створене сховище

Коли canonical checkout існує, запускати команди лише з:

```text
E:\KnowledgeVault\00_System\ControlPlane\Brain_KnowledgeVault\Automation
```

Не клонувати другу робочу копію в `E:\Brain` або
`C:\Users\Nitfo\Documents\Codex`. Для паралельної роботи використовувати
Git/Codex worktrees, пам'ятаючи, що Codex-managed worktrees розміщуються під
`$CODEX_HOME\worktrees`.

## Оновлення з GitHub

GitHub є upstream для control-plane коду, але не backup для KnowledgeVault.
Безпечне оновлення:

1. перевірити repository identity, remote URL, branch і working tree;
2. `git fetch --prune origin`;
3. переглянути local-only та remote-only commits;
4. не перезаписувати локальні зміни й не робити force push;
5. після інтеграції запустити повні тести, `doctor`, `validate` і storage
   audits;
6. push виконувати лише після явного рішення власника.
