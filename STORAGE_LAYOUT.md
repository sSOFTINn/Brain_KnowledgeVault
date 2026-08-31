# Storage layout v2

## Канонічна структура

```text
E:\KnowledgeVault\
├── 00_System\
│   ├── ControlPlane\Brain_KnowledgeVault\
│   ├── Config\
│   ├── Audit\
│   │   └── CodexStorageMigration\
│   ├── Manifests\
│   ├── Policies\
│   ├── Recovery\
│   └── ToolState\
├── 10_Projects\{Active,Reference,Completed}\
├── 20_Knowledge\
├── 30_Documents\{Personal,Work,Administrative}\
├── 40_Media\{Photos,Video,Audio,Graphics}\
├── 50_Resources\ManagedAssets\
├── 60_Private\
│   └── ToolState\Codex\
├── 70_Inbox\
├── 75_Exports\
├── 80_Archive\
├── 90_Runtime\{Catalog,Caches,Logs,Runs,Staging,Temp,Worktrees}\
│   └── Staging\CodexStorageMigration\
└── 99_Quarantine\
```

## Інваріанти

- root позначений `.knowledgevault-root.json` зі schema/volume identity;
- root не має `.git`;
- repository зберігається неподільно з усією `.git` metadata;
- `10_Projects\Completed` — придатний до збирання Git-проєкт;
- `80_Archive` — заморожені матеріали, не активний checkout;
- `60_Private` і `99_Quarantine` не індексуються;
- `60_Private\ToolState\Codex` є канонічним захищеним `CODEX_HOME`;
- довгострокові Codex-проєкти живуть у `10_Projects`, а не всередині
  `CODEX_HOME` чи `Documents\Codex`;
- Codex migration staging зберігається лише у
  `90_Runtime\Staging\CodexStorageMigration`, а evidence — лише у
  `00_System\Audit\CodexStorageMigration`;
- `90_Runtime` відтворюваний і не є джерелом істини;
- approvals, manifests і restore evidence постійно зберігаються в
  `00_System`;
- reparse point не обходиться; path/type/target записуються в manifest;
- unknown не видаляється, а потрапляє у `70_Inbox`.

## Legacy mapping

| Legacy | V2 |
|---|---|
| `E:\Brain` | `00_System\ControlPlane\Brain_KnowledgeVault` |
| Git-проєкти з `E:\The Codex` | `10_Projects\...\<repo>` |
| старий `Vault` | `20_Knowledge` та тематичні data roots |
| старий `Assets` | `40_Media` або `50_Resources` |
| старий `Private` | `60_Private` |
| старий `Runtime` | не відновлювати; перебудувати у `90_Runtime` |

Mapping завжди фіксується в `RESTORE_MAP.csv`; автоматичне вгадування
невідомих root-папок заборонене.
