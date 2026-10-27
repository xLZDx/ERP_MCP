# Change Record 357 — Ivan reference source repointed to the read-only base

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session. Operator approval: answered yes to repointing Ivan source to a read-only clone.
- Documentation of an operational change on Ivan host plus a wording fix in Change Record 356. No repository source changed.

## Change on Ivan host

- `D:\1c\env\odata\erp_mcp_ref\default.vrd` now points at `D:\1c\env\bases\818HA_test_ready` (before: `818HA_p2diff`, the clone the write tests use). Done with `D:\1c\mcp\ivan_repoint.ps1 -BaseName 818HA_test_ready` over strict SSH.
- The script stops Apache and starts it through the `ERP_MCP_Ivan_Stack` scheduled task; the script printed that port 8088 listens again.
- Rollback: `ivan_repoint.ps1 -BaseName 818HA_p2diff` (the original publication file is kept as `default.vrd.bak-test_ready`).

## Result

- `phase2_reconcile_two_bases` (real reference company, as of 2026-08-31): 521.1 closing comparison PARTIAL_MATCH / CLOSING_VALUES_EQUAL, 10 rows each side, identical rows digest, 0 differences.
- Still failing and unrelated to this change: six-column section GATEWAY_HTTP_ERROR, purchase section GATEWAY_TOOL_ERROR.
- A MATCH is numeric agreement of two machine reads of copies of one base, never a native 1C PASS.

## Open

- Named Cloudflare tunnel for the IdP: blocked on an interactive Cloudflare login and a domain (no cloudflared credentials on this machine).
- Change Record 356 wording fixed: three collected test cases were added, seven in the file.
