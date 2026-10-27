# Change Record 195 — enforce signer validity at database registration time

## What changed

- The evidence-registration trigger now assigns `verified_at` from the database clock before reading validation rows, then requires the key to be valid at both signed time and registration time.
- The barrier-ack trigger applies the same database-assigned-time validity check.
- Removed the caller-routine timestamp assignment so the evidence trigger owns the trusted registration timestamp.
- Expanded `S13-TRUSTED-VALIDATION-TIME-01` to cover both evidence and barrier-ack registration boundaries.

## Why

The candidate checked signed-key validity at `signed_at`, but did not require the key to remain valid when the database accepted the registration. This left a gap if a verifier's snapshot was stale or the key expired between verification and insert. The trigger now samples the database clock and checks the immutable key's current validity window at that point. Existing revocation checks still compare the same server-assigned time, and the registration path holds the key row lock.

## Affected paths and contract

- `db/phase2/027_private_writer_admission_schema.sql`: `private_writer_evidence_binding_guard_v1`, `private_writer_register_evidence_v1`, and `private_writer_barrier_ack_guard_v1`.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: key valid-from/valid-until boundary qualification.
- WP5 production evidence validation and S13 evidence-ingest registration.

## Evidence and verification state

- Candidate SHA-256: `7105E332AD506A83FF1B280417E1EA5ADA1FA55CE95DDCADDEDC84932F5D2F8C`.
- Qualification-plan SHA-256: `FE3BAC32BE0D0436562800C0E0CC0603C785F324D8F17A91CEC235DA98CEB4B9`.
- Source-only change. No SQL parse, test/check/build, migration, database write, staging, commit, or push ran. Candidate 027 remains unparsed, uninstalled and ungranted; validity-boundary/race qualification is `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. No responsible human/service owner for production validator key custody, validation-time authority, or build provenance is established in the reviewed project records. Next: finish source coding and exact trust/ACL review; then let the functional/E2E test roles qualify the valid-from/valid-until and revocation races in the disposable database. Do not use this candidate for production evidence.
