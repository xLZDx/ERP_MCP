# Change Record 400 - merge of PR #40 and recovery of the local real-1C lane gateway (erp-mcp-818ha)

## Ownership and scope

- Date: 2026-10-29 (work started 2026-10-28). Operator orders: merge PR #40; repair erp-mcp-818ha (HTTP 401); restore the lane by copying from Trash with the saved secrets and the current volume.
- PR #40 was merged with a merge commit (db30f96) after GPT-PM approved exact head d26617a. CI checks `test` and `odata-upstream` were red before the batch, as at the PR #39 merge; not a task per operator rule.

## Findings (FACT, read-only checks before any change)

- The 401 was a symptom. The local lane (gateway 21000, IdP 21080, lane proxies 8191-8193) was down because its project folder `D:\Repo\ERP_MCP-integration-candidate` had been moved to `D:\Repo\Trash\` (the lane was healthy until 21:44 on 2026-10-28; the 22:43 watchdog pass could not start anything). The Claude Code config held a short-lived IdP token.
- Lane state and secrets were intact outside the project folder: `D:\ERP_MCP_Testbed\real1c_e2e` (env, credentials, IdP config, refresh script) and the live Docker volume `erpmcp-e2e-real1c-pgdata`.
- The watchdog script `autostart\start_lane.ps1` derived its project root as three levels above itself, which resolves to `D:\` for a script in the testbed. It only started components that were not listening and could never have restarted a dead gateway.
- The copy from Trash held code older than the database (migration history 1-15 in the volume, code knew 1-14) and a damaged `.venv` (missing modules).

## Actions (no deletion of any existing file, container or volume)

- Copied `D:\Repo\Trash\ERP_MCP-integration-candidate` to `D:\Repo\ERP_MCP-integration-candidate` (9636 files, counts equal) and, on the operator's instruction, `D:\Repo\Trash\ERP_MCP-chatgpt` over the empty stub `D:\Repo\ERP_MCP-chatgpt` (6537 files). Originals in Trash are untouched. Neither copy is a git checkout (the `.git` file was excluded).
- Rebuilt the `.venv` of the restored lane folder with `uv sync --locked --all-groups --extra dev` (one forced reinstall; processes started from that venv were stopped first), and synced `src`, `db`, `scripts`, `testbed`, `adapters`, `deploy` plus lock and compose files from the current ERP_MCP checkout (robocopy without purge).
- Fixed `D:\ERP_MCP_Testbed\real1c_e2e\autostart\start_lane.ps1`: `$ProjectRoot` is now the explicit restored folder (backup `start_lane.ps1.bak-20261028`).
- Ran the lane autostart: postgres, redis, apache/1C, proxies 8191-8193, sidecar, idp and gateway all True. Re-registered `erp-mcp-818ha` with `refresh_mcp_token.py` (10-year dev-lane test token for the test user `auditor`, never printed).

## Evidence

- Autostart summary line `postgres=True redis=True apache/1C=True proxy8191=True proxy8192=True proxy8193=True sidecar=True idp=True gateway=True`; an `initialize` request to `http://127.0.0.1:21000/mcp` with the new token returned HTTP 200; token expiry year 2036. Claude Code picks the new header up after `/mcp` reconnect.

## Not established

- The restored folders are plain copies; the lane now depends on `D:\Repo\ERP_MCP-integration-candidate` staying in place (do not move it again while the lane runs). The Trash copies may be deleted by their owner at any time. ChatGPT connector `ERP_MCP_REAL1` reconnection was not tested. Running the scheduled watchdog unattended for an hour was not observed.
