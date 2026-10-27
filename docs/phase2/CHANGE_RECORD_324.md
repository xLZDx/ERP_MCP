# Change record 324 — Canonical S13 physical barrier acknowledgement protocol

## Ownership and baseline

- Date: 2026-10-26.
- Accountable owner: operator by explicit delegation; executor: Codex.
- The checkout had extensive staged, unstaged, and untracked work before this slice. In particular, `service.py` and `dpapi_signer.py` already contained unrelated candidate work. This record attributes only the protocol module, its narrow service integration and signer-domain addition described below.
- No staging, commit, or push occurred. No database, COM lane, live business record, private key, or service was accessed or changed.

## Change

- Added `src/erp_mcp_private_writer/barrier_ack_protocol.py`. It validates the S13 physical writer acknowledgement's fixed domain, canonical sorted-key JSON preimage, bounded size, exact lower-case fingerprint and UUID forms, sorted unique call IDs, positive PostgreSQL BIGINT values, closed-queue boolean, and fixed UTC timestamp representation `YYYY-MM-DDTHH:MM:SS.ffffffZ`. The module exposes the exact signed message and Ed25519 verification while explicitly leaving trust lookup, process attestation, and persistence to separate gates.
- Added the existing S13 physical-writer-barrier domain to the `writer_receipt` DPAPI signer's allowlist. Other domains remain rejected.
- The service validates the typed acknowledgement before calling its injected verifier; malformed canonical input maps to `BARRIER_ACK_INVALID`.
- Amended `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` to state the exact UTF-8 canonical JSON options, detached Ed25519 signature shape, and UTC timestamp representation now enforced by source.
- Functional-test-reviewer authored `tests/phase2/test_s13_barrier_ack_protocol.py` and updated only the timestamp fixture in its pre-existing `tests/phase2/test_private_writer_barrier_ack.py`.

## Verification and reviews

- Functional-test-reviewer command: `uv run pytest -q tests/phase2/test_private_writer_barrier_ack.py tests/phase2/test_s13_barrier_ack_protocol.py` — **13 passed, 11 subtests passed in 1.15 s**.
- Current SHA-256: protocol `barrier_ack_protocol.py` = `99F635DDA2DBCE7F5BBE6DBF611BD5EC592EEBE188FE0B2F0E0CF2DD1C3ADD32`; signer `dpapi_signer.py` = `90A30E6D7CBBF455E5F2BC13C8AD94E7BBC820F6D82F0781BBFE8776D28CEF42`; service worktree `service.py` = `98B340A561A4C0874AB02D3657C2BB31AB47847BF26F16359A58C74B1A8AA95A`; protocol test = `03240510825017B844F37C0782DBD5863035E0E851CE29FBB084216991BD2761`; service fixture test = `8E9E03156AC510619386870036BF6E199B6084FDDCEC47A81DB17F32491084C0`. The service hash identifies the entire already-dirty worktree file, not solely this slice.
- Fresh `security-reviewer` read-only review (GPT-6 Luna, medium) found no actionable issue in this slice. It did not review or prove the complete durable verifier/provider.
- Fresh `python-reviewer` read-only review (GPT-6 Luna, medium) found no actionable correctness issue. It noted the absent concrete COM producer must emit the now-fixed UTC representation before qualification.
- These tests and reviews are source-local evidence only. They do not prove database trust/key resolution, process-attestation verification, registry idempotency, installed grants, COM queue closure, or 1C transaction boundaries.

## Remaining acceptance and next step

- A concrete production `BarrierAcknowledgementVerifier` is still absent. It must resolve the exact key version from an authoritative trust source, validate independent process attestation, verify the canonical message, and call the candidate PostgreSQL registration routine with replay-safe handling.
- GPT-PM contract request `f7d2c8a1-8e13-44df-b7cb-3b6af6219a04` targeted the exact signed-byte persistence/ref/replay contract. PM Bridge recorded it sent but returned no demonstrably complete reply before timeout; no new request was created. It remains a coordination dependency for adjudicating the full persistence envelope/replay path, not evidence of approval.
- Owner: Codex implements the concrete adapter and source/SQL reconciliation; GPT-PM owns contract adjudication. Next: continue independent implementation by mapping barrier-call organizations and process trust to a least-privilege authoritative resolver, then have GPT-PM adjudicate the exact stored-byte/ref/replay contract before finalizing that integration. Do not enable the candidate flag or claim S13 qualification from this slice.
