# Change Record 401 - Consolidate sibling ERP_MCP folders into D:\Repo\ERP_MCP

## Scope

- Date: 2026-10-29. Operator order: everything lives only in `D:\Repo\ERP_MCP`; the sibling folders are merged into it, then removed.
- Documentation only. No source, test or contract change.

## Facts

- `ERP_MCP_R2`: `main` and both agent branches are ancestors of the `ERP_MCP` HEAD (0 commits only in R2). The 11 uncommitted files of one agent worktree all hash to blobs already present in the `ERP_MCP` history.
- `ERP_MCP-integration-candidate` (156 differing files) and `ERP_MCP-chatgpt` (115 differing files): every differing file hashes to a blob that exists in the `ERP_MCP` history, so they are older versions and carry nothing new.
- Unique runtime files were copied into `ERP_MCP` and excluded locally from git (`.git/info/exclude`): `.chatgpt/`, `.e2e/`, `.dc_probe/`, `var/`, the runbook zip. They contain secrets and must never be committed.
- The lane scripts (`start_lane.ps1`, `.chatgpt/*.ps1`, token helpers) now point to `D:\Repo\ERP_MCP`; backups carry the suffix `.bak-20261029`. The lane was restarted from `ERP_MCP\.venv`; `initialize` on the gateway returned HTTP 200.

## Not done

- Deleting the three sibling folders and their two Trash copies: blocked by the shell policy hook, waiting for the operator's explicit command. `D:\Repo\ERP` (61 unpushed commits, 40 dirty files) and the rest of `Trash` were not touched.
