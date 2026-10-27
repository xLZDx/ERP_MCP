# Change record 318 — checkpoint runtime authority fail-closed contract

## Ownership and scope

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and closure owner: Codex.
- Technical boundary: S13 checkpoint-backed permit and T16 paths in `DispatchGate`.
- State: fail-closed contract implemented and unit/regression tested; provider authentication and atomic latest/readiness binding remain open activation blockers.

## Change

Added the `CheckpointRuntimeAuthority` dependency to `DispatchGate`. The gate is disabled if no
authority is supplied or if dependencies are marked as test doubles. Before permit issuance and
T16 resolution, it requests provider qualification and current admission readiness. Before
checkpoint recording and T16 hold release, it rechecks provider qualification. Authority responses
must be exactly `None`; `False` and all other non-empty results refuse. The provider and readiness
calls share a five-second asynchronous timeout, and external errors are redacted to the stable
checkpoint-unavailable result. The runtime authority is part of the gate's immutable configuration.

This code does not make an injected protocol implementation trustworthy. The code and its
`enabled` property are not evidence of provider authentication. It also does not bind the external
latest-checkpoint proof to a durable readiness epoch consumed transactionally by permit issuance.
Those two conditions remain explicitly open; no production authority is composed, so the gate must
remain disabled in production.

## Affected paths

- `src/business_ai_gateway/phase2/change_ledger/checkpoint.py`
- `tests/phase2/test_s13_checkpoint_runtime_authority.py`
- `tests/phase2/test_change_ledger_port.py`

## Verification evidence

The functional-test-reviewer authored the focused tests and ran:

- `uv run pytest -q tests/phase2/test_s13_checkpoint_runtime_authority.py` — **19 passed in 0.59s**.
- `uv run pytest -q tests/phase2/test_change_ledger_port.py` — **18 passed in 47.06s**. This full direct regression file ran in an invocation-owned disposable loopback PostgreSQL 16 cluster; the helper verified exact container name and owner label before cleanup. No lane database or COM call was used.

The final exact hashes before and after those runs were:

- `checkpoint.py`: `B67AB573916A3FD4F0FBA34B65915E8BB369DAD8954819B7A44B4B51D5334173`.
- `test_s13_checkpoint_runtime_authority.py`: `BDB2ECAD11AF6F443247282F7B8BD75C16617D0E24D12EF499BF8B83310830DE`.
- `test_change_ledger_port.py`: `980ED42720E0AEB6C9C32D2437B2FBB021E1E829647091FFB074145756B6`.

The test doubles have no credentials and do not qualify a real provider, key source, deployment
policy or startup/restore state. The PostgreSQL runtime tests exercise the existing test database
fixture only; no new provider schema was installed.

Independent source reviews:

- `code-reviewer` inspected the candidate at SHA `B67AB573916A3FD4F0FBA34B65915E8BB369DAD8954819B7A44B4B51D5334173`. No direct regression was found. It confirmed M1 remains open because the protocol and caller-controlled `is_test_double` do not authenticate the provider/policy; M2 remains open because the external latest/readiness result is not bound to permit SQL issuance.
- `security-reviewer` inspected the same SHA and migration candidate `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F`. It confirmed the same activation blockers and found the T16 hold-release path remains fail-closed when authority/provider calls refuse.
- `python-reviewer` initially found a MAJOR in ignoring non-`None` results and a missing timeout. A targeted re-review at SHA `7E35906241838CA50B1AB7E1688215438F214401329DF5A3144E98D1AB92A0B6` confirmed those code findings closed. The later `B67...` source change only clarified docstrings; tests were repeated on `B67...`.

GPT-PM's correlated architecture review is recorded in `CHANGE_RECORD_317.md`. It approved the
fail-closed development direction as within accepted S13 scope and identified the provider,
signer/key custody, and build-provenance dependencies. The review did not approve production
readiness or authorize a provider substitute.

## Remaining acceptance and next work

1. Codex: implement a concrete verifier-backed production authority only after the accepted provider API and authenticated trust root exist; bind its fresh latest-checkpoint proof to a durable readiness epoch/fence consumed under permit issuance. Do not turn a structural protocol or boolean marker into a trust claim.
2. Operator: provide the named external anti-rollback provider/API, its authenticated capability and retention evidence, trusted key/custody source, and approved deployment policy. No service, credentials, key, retention guarantee, or owner is inferred from local access.
3. Codex: after those artifacts exist, wire the verified authority through the production composition root, qualify outage/latest mismatch/revocation/replay on the disposable environment, and run exact-hash specialist re-review.

No staging, commit, push, migration activation, live provider call, or production readiness claim
was made for this record. Pre-existing dirty/untracked worktree contents were preserved. The
tracked source file had pre-existing modifications before this turn; this record attributes only
the runtime-authority edits described above. Test-file updates were made by the functional-test
reviewer during this turn.
