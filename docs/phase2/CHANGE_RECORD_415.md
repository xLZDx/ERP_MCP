# Change Record 415 - keep S13 restore diagnostics test-only

## Scope

This record covers the isolated dev anchor service path fix and the S13 checkpoint diagnostic test-fixture corrections made while running FIN-S3.1 acceptance on disposable infrastructure. The production gateway remains unwired to the dev service; no recovery or writer/readiness path was added.

## Findings and changes

- The child process in `test_s13_checkpoint_restore_e2e.py` could not resolve the repository root when launched from a temporary directory. `dev_anchor_service.py` now derives `_PROJECT_ROOT` from its own source path and uses it for configured SQLite path validation.
- The suffix test's synthetic key-authority fixture now obtains the key digest from the verifier's actual public-key digest implementation, so an invalid test assertion no longer masks the SQL suffix behavior.
- The suffix SQL journey now creates an approved-only suffix using proposal, validation and approval fixture operations. It avoids `begin_apply`, `record_call`, dispatch, physical writer invocation and any READY result; migration 027 intentionally withholds the legacy writer operations from runtime roles.

## Safety boundary

The service remains explicitly development/test-only, uses loopback and throwaway temporary state, and does not register a production route. All SQL execution is limited to an invocation-owned disposable PostgreSQL cluster. No shared or production database, real 1C source, or 1C write was used. Synthetic signer/latestness authorities are test doubles and do not prove external latestness or production key custody.

## Evidence status

The assigned e2e-runner has reported passing SQL parity, scoped list/status and suffix runs against the current working copy; exact-head reruns remain required after the candidate commit. The separate restore-skew rerun is in progress. No final S3.1 acceptance is claimed by this record.

## Dual-authority restore-skew follow-up

The restore-skew E2E initially stopped before its database restore because its child-service fixture still supplied the former single signing key. The implementation now validates separate latestness and key-authorization Ed25519 key pairs, including matching private/public bytes and collision refusal against each other and registered checkpoint keys. The test fixture supplies separate generated TEST pairs and passes their public identities to the client. The assigned e2e-runner reports `1 passed in 37.05s` on disposable PostgreSQL with service, SQLite state, dump, DBs, container and volumes cleaned. This result is working-copy evidence; exact candidate-head rerun remains required.
