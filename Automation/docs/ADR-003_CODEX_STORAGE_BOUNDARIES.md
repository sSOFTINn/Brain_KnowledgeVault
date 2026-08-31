# ADR-003: Codex storage boundaries

## Status

Accepted — 2026-08-31.

## Context

Codex durable state, long-lived repositories, migration staging, evidence and
Windows-owned desktop/runtime data have different retention and trust needs.
Treating every path containing `Codex`, `cache`, `log` or `temp` as equivalent
causes either unnecessary C: usage or unsafe deletion of operational state.

OpenAI documents `CODEX_HOME` as the root for config, auth, logs, sessions,
skills and package metadata; managed worktrees also live below that root.
Windows desktop binaries, profiles and shared temporary directories are not
documented as wholesale relocation targets.

## Decision

- set canonical `CODEX_HOME` to `60_Private/ToolState/Codex`;
- store long-lived repositories under `10_Projects`;
- store copy-only migration staging under
  `90_Runtime/Staging/CodexStorageMigration`;
- store permanent evidence under `00_System/Audit/CodexStorageMigration`;
- leave Codex AppData, binaries, runtimes and `.cache/codex-runtimes` in place;
- do not redirect general Windows `TEMP`/`TMP`;
- expose read-only `codex-storage audit` and non-executing
  `codex-storage cleanup-plan` commands;
- require separate approval for any cleanup.

## Consequences

The durable Codex state and managed worktrees consume space on E:. Some
application binaries and caches remain on C: by design. Audit evidence makes
this split explicit, while cleanup automation cannot delete sources by itself.

## References

- <https://learn.chatgpt.com/docs/config-file/environment-variables>
- <https://learn.chatgpt.com/docs/config-file/config-advanced#config-and-state-locations>
- <https://learn.chatgpt.com/docs/environments/git-worktrees>
- [`../../CODEX_STORAGE_POLICY.md`](../../CODEX_STORAGE_POLICY.md)
