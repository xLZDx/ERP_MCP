# Change record: SEC-ED25519-01 fix

What: small-order public keys and R points are rejected by src/business_ai_gateway/phase2/ed25519.py and db/phase2/014_ed25519_verify.sql (edited in place, unpushed); db/phase2/015 key registration refuses them; negative tests added in test_ed25519_offline.py, test_ed25519_sql.py, test_change_hardening_g_sql.py.
Why: GPT-PM reproduced a forgery with the neutral-point public key.
Verification: agent-run focused tests, see DECISION_LOG.md. Test lane only.
