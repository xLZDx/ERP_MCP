# Change record 244 — protect COM STA lifecycle fields from ordinary mutation

Date: 2026-10-25  
Scope: source-only S13 COM STA lifecycle hardening; no runtime or COM behavior was exercised.

## What changed

- `ComStaLane` now rejects ordinary reassignment and deletion of `_state`, `_in_flight`, and `_thread` after construction, alongside the existing configuration-field protection.
- Internal lifecycle transitions use one narrow setter that accepts only those three fields. It enforces the declared state graph, permits same-state idempotency for cleanup paths, requires boolean in-flight transitions, and allows one-time thread binding; existing lock-protected transition sites remain responsible for when each state changes.
- The `S13-COM-STA-01` qualification row now includes mutation/deletion attempts for all three fields, valid/invalid/repeated-state transition cases, and requires zero callback, queue, or lane-state changes on refusal.
- Current source SHA-256: `190DB9599B70BF9F341DE08E50A2030F31A05CBFABE53FFAC7F7B7A960237EC6`.

## Why

The lane uses `_state`, `_in_flight`, and `_thread` to gate startup, single-call admission, shutdown, and worker ownership. Ordinary attribute writes could bypass the lock-protected methods and make the lane report a false lifecycle state or lose the tracked worker reference. Freezing external writes preserves the current internal transitions without adding a COM mapping or enabling a writer.

## Scope and safety

- This is a Python object-invariant hardening change. It does not authenticate a mapping, establish COM transaction semantics, implement `OneCWritePort`, start a listener, connect to COM, or authorize a write.
- It is not a defense against arbitrary same-process code deliberately invoking `object.__setattr__`; process/build provenance remains a separate trust boundary.
- Qualification remains `NOT_RUN`. No test, check, build, CI, migration, database operation, COM call, listener start, stage, commit, or push was performed.

## Ownership and next action

- Accountable task owner: operator; executor: Codex.
- Later scenario owners: `functional-test-reviewer` and `e2e-runner`; relevant source review: Python/reliability/security reviewers after coding closure.
- Next: continue the independent source-closure queue. After all code is complete, qualify direct mutation/deletion, worker lifecycle, cancellation, and cleanup on the authorized environment; keep the writer disabled until the authenticated clone mapping and transaction boundary are established.
