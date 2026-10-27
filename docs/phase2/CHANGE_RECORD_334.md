# Change record 334 — close direct validator-provenance registration bypass

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator; implementation owner: Codex; first source reviewer: python-reviewer.
- This change extends the source-only build-attestation contract in `CHANGE_RECORD_331.md` and the evidence-ingest privilege gate in `CHANGE_RECORD_332.md`.
- The relevant modules were pre-existing modified shared-worktree artifacts. This record attributes only the safeguards described here to the current turn; it does not claim authorship of their prior contents.

## Finding and remediation

The read-only Python review found that the abstract production-source marker could be subclassed by a synthetic source, and production authorization was checked only by `compose_private_writer_runtime()`. Direct construction/use of `PostgresWriterReceiptRegistrar` could reach evidence registration without passing that composition root.

The production verifier now recognizes only an exact source type explicitly listed in a module-local allowlist. That allowlist is empty because no concrete host-bound provider or externally authorized root/policy/measurement source exists. Pure signature verification returns an ordinary verifier-sealed result; only the instance loader can add the production-authority seal after loading from an allowlisted exact source.

The production registrar constructor now refuses a verifier without that exact production source. `verify_and_store`, `verify_set_and_store`, build-source resolution, and the private `_register` helper independently enforce the authority, so direct method use cannot bypass the composition gate. The initial disposable subclass was removed after follow-up review noted it could be invoked with an arbitrary caller-supplied pool; future synthetic persistence must be implemented by the disposable test harness, outside the application package and production dependency graph. No concrete source type is allowlisted, so production remains intentionally unavailable.

Added acceptance `S13-VALIDATOR-BUILD-REGISTRATION-GATE-01` to require constructor/direct-method denial, a zero evidence-insert count on refusal, and exact-type separation of the disposable registrar from production composition.

## Review and verification state

- First python-reviewer source pass found the direct-registration bypass. The exact finding and remediation were returned through the agent channel; no tests/checks were run by the reviewer.
- The final focused python-reviewer re-review confirmed the direct production bypasses are closed and found no remaining actionable B/MAJ issue in the three source files. It found and reported one stale disposable-registrar comment, which Codex corrected. The reviewer did not run tests/checks or edit files.
- Private Python module constants are not an isolation boundary against arbitrary code execution inside the process. The production guard addresses supported construction/composition paths; it does not claim to defend against malicious same-process introspection or code mutation.
- No tests, checks, builds, SQL parsing, migrations, database or COM operations, staging deployment, Git staging, commit, or push were performed.
- Production registration remains disabled by the empty exact-source allowlist and withheld evidence-ingest EXECUTE privileges.

## Current file hashes

- `src/erp_mcp_private_writer/validator_build_attestation.py`: `2CCEF054B9B3075FE196E884E797EC77E446F6A354F29E79B8C0481A552D47D0`.
- `src/erp_mcp_private_writer/postgres_evidence_registrar.py`: `10CD7D462107BA838510B3E95D322B8154E1C74FDBF739E1ECE4240482161440`.
- `src/erp_mcp_private_writer/runtime_composition.py`: `4261BAD4D8A3FCF2383C5D185B355B2A84C5ACE82569E3FB8C4447F434EF262D`.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `E48729D208B36EEE05891743D437857F172B8638D662B661C55C98631301AC97`.

## Remaining work

1. Codex: complete the independent source re-review and remediate any valid direct regression.
2. After coding closes, functional-test-reviewer/e2e-runner own the mapped refusal, no-insert, synthetic-source, and exact composition-type scenarios on disposable PostgreSQL. Any persistence test harness must stay outside the application/production dependency graph and bind only to its invocation-owned disposable database.
3. GPT-PM adjudicates any material contract change; its existing decisions in `CHANGE_RECORD_331.md` support source-only verifier implementation with production disabled.
4. Operator remains accountable for the externally authorized trust root, build policy, actual artifact measurement and deployment identity. Until those exist and independent security/database reviews pass, do not add evidence-ingest EXECUTE grants.
