# Change record: migration 016 (dispatch receipt)

What: db/phase2/016_dispatch_receipt.sql adds record_dispatch_receipt, require_dispatch_receipt and a records trigger; clone_1c.py signs receipts; reference_writer.py forwards and checks them; new tests/phase2/test_change_hardening_h_sql.py.
Why: F-01 gap (bytes received by the simulated 1C not proven to equal the approved payload).
Limits: opt-in marker; digest is the 009 payload digest; simulation only.
Verification: agent-run focused tests, see DECISION_LOG.md.
