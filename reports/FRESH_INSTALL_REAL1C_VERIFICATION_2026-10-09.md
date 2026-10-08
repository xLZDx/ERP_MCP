# ERP_MCP Release 1 — fresh GitHub install with real local 1C (L2)

**Executed:** 2026-10-09 (Europe/Chisinau).  
**Type:** authorized isolated Windows 11 engineering workstation; fresh repository clone, **not a new physical computer**.  
**Source baseline:** public `main` at `6c9e4a001301f90325558c630c72dd6ed16296ec`.  
**Remediation candidate:** `fix/e2e-comspec-first-install-20261009`.  
**Scope:** install, isolated PostgreSQL/Redis, test IdP/MCP gateway, registered real 1C reference, read-only metadata and data-plane ACL. **No 1C writes or native accounting sign-off.**

## Fresh install / isolation

- New clone: `git clone --depth 1 --single-branch --branch main https://github.com/xLZDx/ERP_MCP.git`.
- `uv sync --locked --all-groups --extra dev`: **PASS**, 83 installed packages under Python 3.14.3.
- E2E profile: `E2E_REAL1C=1`, `-Seed bootstrap-only`, `E2E_PORT_OFFSET=10500`, `E2E_PROJECT_SUFFIX=-installreal-20261009`.
- Disposable project: `erpmcp-e2e-installreal-20261009`. Independent PostgreSQL 16, Redis 7, test IdP `127.0.0.1:28580`, gateway `127.0.0.1:28500`.
- Schema migrations, DB role privilege policy, admin bootstrap: **PASS**.
- New gateway `/healthz=200`, `/readyz=200`, `.e2e/env.json` READY marker: **PASS**.
- Fake1C and synthetic sidecar not started in the real-1C profile.
- Existing `127.0.0.1:21000` gateway, upstream real-1C proxy/sidecar and production databases were not restarted, modified or replaced.

## Genuine 1C integration

The test-only read-only 1C identity from an existing protected Windows credential source reached the authorized loopback proxy:

- unauthenticated 1C endpoint: `401`;
- authenticated GET `$metadata`: `HTTP 200`, XML;
- Admin source probes and capability refresh: `200` on each of three explicitly registered test aliases;
- observed `920` EntitySets, compatibility `SUPPORTED`;
- live organization discovery: 1;
- company and admin roles registered in the **new disposable control DB**.

This proves authentic metadata connectivity, not native financial numbers or complete 1C reconciliation.

## First-install findings and fixes

### F-001 — missing `ComSpec` in some remote/noninteractive PowerShell hosts

First `up.ps1` run on the clean clone passed database bootstrap but failed detached service launch with a null `Start-Process -FilePath $env:ComSpec`. Exporting the official `%SystemRoot%\System32\cmd.exe` resolved the same disposable setup. The patch provides a checked fallback in `scripts/e2e/_common.ps1`; explicit test with `ComSpec` unset passed.

### F-002 — auditor Admin role does not imply data-plane source grant

On the new disposable control DB the test `auditor` had `AUDITOR` platform role, but **zero** `bag.access_grants` for the exact source. Thus `source_health` and `onec_capabilities` denied with `AccessDenied`, while the earlier correctly provisioned real-1C lane passed.

The remediation adds a separate, narrowly bounded, idempotent **test-only** source grant for `auditor` on `onec-818ha-reference`, through the authorized Admin API. It is not `all_sources`, does not authorize `onec-818ha-drift` or `onec-818ha-down`, and cannot grant a production profile. It does **not** change the registry ACL contract or make Admin `AUDITOR` implicitly data-authorized.

The already provisioned isolated stand was repaired explicitly via `python -m scripts.real1c.lane_setup --repair-auditor-grant`. A second invocation reported the existing grant, not a duplicate.

## Executed end-to-end MCP results

| Identity | Operation | Source | Outcome |
| --- | --- | --- | --- |
| auditor | `source_health` | reference | **PASS**, `status_code=200` |
| auditor | `onec_capabilities` | reference | **PASS**, `entity_set_count=920`, `SUPPORTED` |
| auditor | `source_health` | drift | **PASS (denied)** |
| auditor | `onec_capabilities` | down | **PASS (denied)** |
| user_company_one | `source_health` | reference | **PASS (denied)** |
| user_company_one | `onec_capabilities` | reference | **PASS (denied)** |
| user_no_access | `source_health` | reference | **PASS (denied)** |

**7/7 behavioral expectations PASS** against real local 1C and new isolated MCP. Denied calls correlated with `bag.audit_events.detail_code=AccessDenied`; successful source-level reads generated `ACCESS_AUTHORIZED` plus completion evidence.

Focused tests `tests/test_real1c_lane_bootstrap.py` + `tests/test_company_read_and_rbac.py`: **10 passed** on the candidate version; Ruff: PASS; `git diff --check`: PASS. The extra opt-in repeat/ComSpec checks passed.

## Remaining boundaries / NO-GO

This verification is **Release 1**, not Phase 2. No generic business `onec_read` company-scope bypass was authorized. No actual accounting amounts, posting balances, 521.1 six-total native report reconciliation, accountant attestation, operational DR, production load, remote Unix installation or production OAuth were asserted as PASS. Release 1 production decision remains subject to separate exact-head gates.

For Unix: the Windows COM bridge and 1C test base remain on the authorized Windows host; the Linux gateway would require a private authenticated network route to 1C and sidecar, Linux-native deployment secrets/IdP/TLS/least-privilege DB and independent acceptance. A target Unix SSH host was **not configured or connected during this run**, so no remote deployment claim is made.
