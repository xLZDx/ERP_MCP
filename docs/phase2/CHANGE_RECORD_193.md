# Change Record 193 — pin immutable signer-key material during barrier acknowledgement

## What changed

- `private_writer_register_barrier_ack_v1` now retains the public key used to derive the verifier-material advisory lock and compares it with the locked row before validating the registration. A changed key fails closed.
- Added `S13-KEY-VERSION-IMMUTABILITY-01` to the disposable qualification plan to exercise the existing generic `s13_immutable` triggers on the three trust tables and the registration-versus-key-mutation race with a zero-row/zero-transition expectation. The same plan includes `S13-FIRST-LOCK-DOMAIN-01` for the preceding transaction-lock fix; both cases remain `NOT_RUN`.

## Why

An initial targeted database-reviewer pass suspected that owner-side mutation could change signer material between the unlocked lock-plan read and the later `FOR SHARE` read. Full source inspection found that the candidate already installs generic `s13_immutable` BEFORE UPDATE/DELETE triggers on key versions, scope rows, and rotation edges; therefore the reviewer’s claimed mutation path is not currently available. No new table-specific immutability triggers were retained. The equality recheck is defense in depth against future guard drift. This is source evidence only, not runtime proof or cryptographic verification.

## Affected paths and contract

- `db/phase2/027_private_writer_admission_schema.sql:1124-1182` (after removal of redundant explicit immutability triggers)
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:62-64`
- Barrier acknowledgement registration and signer-key rotation/revocation.

## Evidence and verification state

- Read-only `database-reviewer` source pass identified a possible unlocked-key/locked-key mismatch and recommended immutability plus equality recheck. Follow-up source inspection verified the existing generic immutability triggers and corrected the finding; the exact locked-key comparison remains as defense in depth. The role catalog selects GPT-6 Luna; the launch/result did not expose reasoning effort, so effort is `NOT_RECORDED`.
- Candidate SHA-256 at this change record's snapshot: `C0159C9ACC2A2FEAD455552EC7C1839B5CF5602B79DD9D298D95DDCE53CE8B7C`.
- Qualification-plan SHA-256: `9284194494B2BE954EBC1E66C8D315ACBF483E5EB9B723979C75444F1B332C98`.
- Source inspection only. No SQL parser, test/check, build, migration, database call, staging, commit, or push ran in this turn. Migration 027 remains unparsed, uninstalled, and ungranted; runtime qualification is `NOT_RUN`; installed candidate grants are `NOT_MEASURABLE` on the inspected disposable database.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Technical owner of the remote host boundary remains the Ivan stack as recorded in the project artifact. Next: continue candidate-wide lock/FK/trigger/effect closure; after coding, assign the immutability race and source review against the exact final hash, then qualify only in the approved disposable environment.
