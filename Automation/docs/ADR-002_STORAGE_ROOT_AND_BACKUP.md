# ADR-002: canonical storage root and external backup

- Status: accepted
- Date: 2026-08-17

## Context

Legacy data existed in parallel roots `E:\Brain`, `E:\KnowledgeVault` and
`E:\The Codex`. A same-disk backup could not protect against physical loss,
and a global Git repository would mix control code with personal data.

## Decision

- canonical data root: `E:\KnowledgeVault`;
- control plane: separate repository under `00_System\ControlPlane`;
- every project retains its own `.git`;
- runtime is derived under `90_Runtime`;
- external encrypted repository: `F:\Backup_E\20_ResticRepository`;
- source and backup must be different physical disks;
- schema marker binds root to volume identity;
- real migration uses immutable plan, explicit approval, verified copy,
  permanent audit and no source deletion.

## Consequences

Positive: deterministic restore, clear privacy boundary, preserved histories,
portable ordinary files and enforceable backup gates.

Trade-offs: initial migration is slower because repositories and files are
fully hashed; volume replacement requires updating the machine profile and
re-running bootstrap/restore verification; a second independent backup remains
an operational requirement outside Git.

## Rejected alternatives

- one global Git repository: leaks/mixes data and breaks project histories;
- mutable mirror as the only backup: propagates deletion/corruption;
- same-disk Restic repository: no protection from disk loss;
- mass junction redirection: opaque failure and recovery behavior;
- automatic source cleanup: conflicts with verified retention and rollback.
