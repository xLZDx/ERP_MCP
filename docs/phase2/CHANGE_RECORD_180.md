# Change record 180 — require a unique Windows service SID for the writer mutex

## Security finding and fix

- **Actor/precondition:** a local process running as a broadly shared Windows account, or an
  operator misconfiguration that supplies that account SID as `service_sid`.
- **Entry point and boundary:** `WindowsServingAuthorityMutex.__init__` accepted any syntactically
  valid SID and used it as both the named-mutex owner and the sole non-SYSTEM DACL principal.
- **Sensitive sink and impact:** the cross-process serving-authority mutex protecting the private
  COM queue. A broadly shared principal could open/hold or alter the security boundary, causing
  writer denial of service and undermining the intended isolation between the writer process and
  unrelated processes under the same account. The mutex alone does not authorize a database write.
- **Fix:** accept only a canonical, unique NT SERVICE SID (`S-1-5-80-` plus exactly five bounded
  subauthorities), rejecting ordinary user SIDs, built-in service groups and other principals.

## Changes made in this turn

- Tightened SID validation in `src/erp_mcp_private_writer/windows_authority_mutex.py` before any
  Windows API call. Existing fingerprint, DACL and owner checks remain in place.
- Added a read-only Ivan scheduled-task principal observation to the WP0 evidence artifact. The
  existing `ERP_MCP_Ivan_Stack` task reports `UserId=koros`, `LogonType=Interactive`,
  `RunLevel=Highest`; this is not accepted as the dedicated writer service identity.

## Verification and remaining work

- Manually reviewed the validation against the accepted S13 requirement that the mutex owner and
  DACL be restricted to one exclusive writer service SID plus LocalSystem.
- No tests, checks, build, Windows API call, service change, restart, COM operation, staging,
  commit or push was performed for this fix. Windows runtime behavior is `NOT_RUN`.
- Required regression scenario for `functional-test-reviewer`/`e2e-runner` after coding closure:
  reject the observed ordinary `koros` user SID, `S-1-5-80-0` (the all-services group), malformed
  or out-of-range service SID strings before creating/opening a mutex, and accept a unique NT
  SERVICE SID without broadening its protected DACL.
- Accountable task owner: operator. Executor: Codex. Ivan stack owns the host boundary; its existing
  scheduled-task account is not identified as the future writer service owner.

## Evidence

- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` — serving-authority mutex
  trust boundary and requirement that the configured service SID be exclusive to the writer.
- `docs/adr/ADR-0009-private-test-writer.md` — separate private service and least-privilege ingress.
- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md` — read-only scheduled-task
  principal observation and its limits.
