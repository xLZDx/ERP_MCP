# Change Record 346 — fix an unreachable evidence registration and repair its red test

## Ownership and scope

- Date: 2026-10-27.
- Accountable owner: operator; executor: Claude Code session.
- Covers `src/erp_mcp_private_writer/postgres_evidence_registrar.py`,
  `tests/phase2/test_s13_evidence_provider_composition.py`,
  `tests/phase2/test_s14_simulated_write_port.py`, this record and the matching log entries.

## Defect

`PostgresWriterReceiptRegistrar._register` called the static method `_same_validator_build_authority` as a
bare name instead of `self._same_validator_build_authority`. Python raised `NameError`, and the
`except Exception` clause at the end of `_register` turned it into
`EvidenceRegistrationError("EVIDENCE_REGISTER_UNAVAILABLE")`. Every registration would therefore have failed
closed with a misleading "unavailable" code, and the build-policy staleness check could never run. Found by
ruff rule `F821` (undefined name) after the preservation commit made the file reviewable.

## Change

- `postgres_evidence_registrar.py`: the call is now `self._same_validator_build_authority(...)`.
- `test_s13_evidence_provider_composition.py`:
  - two regression tests drive `_register`: with a matching build the comparison runs and the pool is reached
    (`acquire_calls == 1`); with a changed build the call refuses with
    `EVIDENCE_REGISTER_BUILD_POLICY_STALE` before any database access (`acquire_calls == 0`);
  - the existing red test `test_valid_production_graph_passes_evidence_checks_without_database_access`
    failed at registrar construction (`EVIDENCE_REGISTER_BUILD_SOURCE_INVALID`) because the registrar
    constructor was tightened to accept only a real `ValidatorBuildAttestationVerifier` whose input source is
    on the production allowlist, which is empty by design. The test now builds a real verifier over a
    concrete stub source and allows that stub type through an autouse fixture. The empty production
    allowlist itself is unchanged.
- `test_s14_simulated_write_port.py`: added the missing `DispatchPermit` import (annotation only, so there was
  no runtime failure).

## Contracts and paths affected

No public contract change. The registrar still refuses every real source until a host-authorized build source
is reviewed and added to the allowlist.

## Verification state

- RUN (focused, no database): `test_s13_evidence_provider_composition.py` 11 passed;
  `test_s14_simulated_write_port.py` 16 passed.
- The fix was not validated by breaking the code and watching a test fail (the operator forbids mutation
  runs); the first regression test would fail on the old code because the `NameError` is raised before the
  pool is reached, so `acquire_calls` would stay 0.
- NOT_RUN: the remaining suite beyond the files above, review.

## Addendum: trust snapshot limit

`postgres_evidence_trust.py` set `_MAX_SNAPSHOT_BYTES` to 16 MiB, while the design document, Change Record 304 and
`test_wp5_json_decoder_contracts.py` specify 8 MiB. Three boundary tests failed in the full `tests/phase2` run.
The constant is now 8 MiB. The barrier-acknowledgement 16 MiB payload limit is a different contract and is unchanged.

Updated verification: `test_wp5_json_decoder_contracts.py` plus `test_s13_evidence_provider_composition.py`
31 passed. Full `tests/phase2` run before the fix: 3 failed, 6995 passed, 602 skipped, 13 errors. The 13 errors are
migration harness scripts documented as "run directly, never through pytest" (they start a disposable PostgreSQL
container), so they are NOT_RUN.
