# Change Record 309 — refuse dispatch while a cancelled call is retained

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Acceptance: `S13-WRITER-QUEUE-REFUSAL-01`.
- State: implemented in source; functional/E2E qualification remains `NOT_RUN`.

## Change and reason

`PrivateWriterService.dispatch()` releases its local base-dispatch lock when the requesting coroutine is cancelled, while the shielded `_active_dispatch` task continues under the serving-authority lease. A subsequent request previously passed the local-lock check, waited until `try_acquire()` and then returned `SERVING_AUTHORITY_BUSY` from the process-wide mutex. That violated the immediate `WRITER_BUSY` refusal contract, even though it did not proceed to admission or the physical writer.

The entry check now treats a retained `_active_dispatch` as an occupied local lane, returning `WRITER_BUSY` before taking the local lock, acquiring the OS mutex, reading preconditions, or creating another durable admission. A completed retained task remains busy only until its existing completion callback clears `_active_dispatch` after lease release.

## Affected path

- `src/erp_mcp_private_writer/service.py:1317-1320` — combine the active-dispatch and local-lock refusal before the first await in `dispatch()`.
- Acceptance contract: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, `S13-WRITER-QUEUE-REFUSAL-01`.

## Evidence and verification

- Baseline source SHA-256 observed immediately before this edit: `124E120BFCE248B4908A67625A7C488690A5C94B818AC4C9FA780B78074A17B0`.
- Source SHA-256 after this edit: `87F971ED737CFBF84FF032DF285082ED56E6833A7CD06F477B1CC7CB9B592970`.
- `service.py` was already modified in the worktree before this edit; the hashes identify the whole file and do not imply authorship of its earlier changes.
- No test, check, build, SQL parse, database operation, migration, COM action, staging, commit, or push was performed for this change. Coding remains open, so test execution is deferred to the designated functional/E2E roles after code completion.

## Remaining acceptance

After all in-scope coding closes, functional/E2E qualification must hold one dispatch in the shielded inner task after cancelling its requester, submit a second dispatch, and capture immediate `WRITER_BUSY`, zero precheck/admission/writer/COM calls for the second request, unchanged durable state, and successful lane reuse only after the original task completes and releases its authority lease. The barrier-held queue-refusal case remains required as a separate control.

Next: continue the source-wide S13 closure. After coding completion, assign the mapped dispatch and barrier cases to `functional-test-reviewer` and `e2e-runner`.
