# Change record: migration 015 (Ed25519 signatures)

What: db/phase2/015_ed25519_signatures.sql routes evidence, checkpoint and permit signature checks through change_ledger.ed25519_verify; harness FILES now 15 entries; fixtures in tests/phase2/_ed25519_fixtures.py; new tests/phase2/test_change_hardening_g_sql.py (9 tests).
Why: replace keyed-hash stand-ins with real Ed25519 in the simulation lane (plan P1).
Contracts: signature verification errors keep their previous codes; legacy keyed-hash rows remain readable.
Verification: agent-run focused files on a disposable container, see DECISION_LOG.md. Test lane only, not gate evidence.
