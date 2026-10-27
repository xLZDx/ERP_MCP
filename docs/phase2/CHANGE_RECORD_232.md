# Change Record 232 — require an explicit operational writer declaration

## What changed

- Added the `operational` declaration to the `OneCWritePort` protocol and set it to `False` on `NonOperationalWritePort`.
- Tightened `compose_private_writer_runtime()` to reject the named non-operational class and all its subclasses, and to require `operational is True` in the concrete writer class's own class dictionary, in addition to the existing required-method checks.
- Added candidate acceptance case `S13-OPERATIONAL-WRITER-COMPOSITION-01` to the disposable qualification prerequisites.

## Why

Method-presence checks plus an `isinstance(NonOperationalWritePort)` check could reject the named skeleton but still compose an unrelated duck-typed object whose methods were inert. The explicit declaration in the concrete class's own dictionary rejects missing, false, instance-only, and inherited declarations, while the nominal check also prevents a `NonOperationalWritePort` subclass from opting itself in by overriding the marker. It is an accidental-skeleton guard only; it does not authenticate a build, process, host, key, or deployment.

## Baseline and provenance

The checkout already had a large staged/unstaged/untracked S13 worktree. Before this change, `write_port.py` was modified and `runtime_composition.py` plus the qualification prerequisite document were untracked. Their pre-edit SHA-256 values observed in this turn were:

- `src/business_ai_gateway/phase2/change_ledger/write_port.py`: `40D9C015DECA4D2DEFF1A20F4621BA54D0274A098E4A5069AAB31B64A8C374F5`
- `src/erp_mcp_private_writer/runtime_composition.py`: `B4FBCDC1F89CCD2EE4C64CA065D9E96EC4519AFECF3AD6F8BE6E9A9FA6FAD166`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` was already untracked; its pre-edit hash was not captured.

This turn's changes are the focused `operational` protocol/skeleton declaration, the composition guard, the qualification row, and this record. Other pre-existing diffs in those files are not attributed to this turn.

## Verification state

- **Code:** implemented; not test-executed or independently reviewed.
- **Required qualification:** `NOT_RUN`; it belongs to `functional-test-reviewer` after coding closes. It must prove both rejection and the no-I/O composition boundary described in the prerequisite row.
- **Runtime:** the separate reader DPAPI blob on Ivan's host was unprotected in memory under the `koros` SSH identity; no secret value was emitted. A strict-host-key SSH attempt to connect only as `ERP_MCP_TEST_READER` to `D:\1c\env\bases\818HA_p2diff` returned sanitized `COMException`, `HRESULT -2147467259`; the detail was redacted. No COM operation, metadata query, or write followed. This does not establish the failure cause.
- **PostgreSQL grants:** the actual `database-reviewer` role inspected the disposable lane in a `REPEATABLE READ READ ONLY` transaction. PostgreSQL 16.15 database `business_ai` had no `change_ledger` schema, no candidate S13 roles, and no candidate tables/functions/grants to measure. The session was `business_ai_admin`, `transaction_read_only=on`, `rolsuper=false`, and `rolbypassrls=false`; therefore candidate effective grants are `NOT_MEASURABLE`, not denied or passed. No DB mutation or migration occurred.
- No tests, checks, build, CI, SQL parse, migration, stage, commit, or push ran in this change.
- Before any local commit, GPT-PM review was attempted against exact request `6f21b048-45a3-4fd6-99bf-3767ad06622a` on canonical project `erp_mcp`. `gpt_send_and_await` returned `Transport closed`; the subsequent read-only `pm_bridge_job_status` lookup for that request also returned `Transport closed`. Delivery/reply state is therefore `UNKNOWN`, not approved. The request must be status-reconciled before any resend; no commit was made.

## Affected contracts and scope

- `src/business_ai_gateway/phase2/change_ledger/write_port.py`
- `src/erp_mcp_private_writer/runtime_composition.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

The guard does not add an operational COM writer, alter PostgreSQL/COM transaction boundaries, enable S13, or authorize a listener. Exact clone identity, COM mapping, effective installed grants, signer custody, process/build provenance, and independent evidence validation remain separate requirements.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Technical owner of Ivan's host: Ivan stack. The responsible human/service owner for production signer custody and validator provenance is not established by the inspected project records.
- Next: continue code closure; then have the designated functional/E2E roles execute the new composition case and the full accepted S12/S13 qualification matrix, followed by relevant specialist review. Do not treat this marker as a runtime trust gate.
