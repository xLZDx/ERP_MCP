# FIN-S2.1 — Recover ambiguous approval consumption

Task: FIN-S2.1 — Put approval decisions in the S16 core

## Finding and change

The atomic `consume_decision_ref_and_nonce()` store operation could persist the approval and then raise before returning. The core previously classified that outcome as an invalid nonce and returned before installing its replay, approval, and S12 anchors. A successful consume followed by a failed read-back also left a consumed reference without those local anchors.

The core now treats a raised consume call as ambiguous and reads the authoritative receipt. It accepts the decision only when the exact receipt identity, approval, and transitioned S12 record match. Read errors or mismatches remain `AUDIT_UNAVAILABLE`; a definite non-consume remains `APPROVAL_NONCE_INVALID`. After a confirmed consume, replay and approval anchors are installed before the separate read-back, so a transient read failure cannot orphan the consumed reference in this process. Success is returned only after exact persisted-state verification.

## Verification and limits

The assigned functional-test-reviewer ran the named `test_s16_approval_core.py` and `test_s16_private_ingress.py` modules at source HEAD `20b2833f78316f51f1096402a3ff35ba3ae9a26b`; 65 passed with 2 warnings in 0.96 seconds. Coverage includes a store that commits then raises, post-commit read failure, replay refusal, status recovery, and a single apply-port call. The scoped run used `--confcutdir=tests/phase2` because the root conftest could not import `MCPServer` from the installed MCP SDK.

This is synthetic/current-tree evidence only. It does not establish a database-backed store, live approval service, production authorization, listener, or 1C write. Formal FIN acceptance remains pending the ledger's exact-head review and verification records.
