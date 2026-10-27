# Change record 184 — safe COM startup failure classification

## What changed

`ComStaLane` now preserves only five fixed startup failure codes from the Windows COM lane:
COM activation, connection configuration, connector `Connect`, base-fingerprint read, and
base-fingerprint mismatch. Arbitrary `ComLaneError` values still collapse to
`COM_LANE_START_FAILED`. `windows_com_sta_lane` maps exceptions to those fixed codes and never
returns exception text, HRESULTs, connection strings, or COM objects across the STA boundary.

## Why

The existing lane mapped activation and connection failures to the same generic startup code,
which obscured the failing stage during licensed-lane diagnosis. The new taxonomy improves the
diagnostic boundary without exposing connector or credential details and preserves fail-closed
fingerprint comparison.

## Affected contracts and paths

- `src/erp_mcp_private_writer/com_sta_lane.py` — startup error-code allowlist and worker mapping.
- `src/erp_mcp_private_writer/windows_com_lane.py` — fixed stage errors for activation, connection
  configuration, `Connect`, fingerprint read, and fingerprint mismatch.
- S13/CT14 COM admission remains disabled until the authenticated clone mapping, dedicated writer
  identity, effective rights, and operation manifest are qualified.

## Decisions and boundaries

- Diagnostics reveal only a fixed stage code. Raw HRESULT and exception data remain suppressed.
- The lane is still unstarted by module construction; no connection or base read occurs until
  `start()` is explicitly invoked.
- A fingerprint mismatch remains a refusal; there is no fallback base or alternate connection.
- The change does not implement `OneCWritePort` methods or claim a functioning writer boundary.

## Verification state

- Source inspected after edit; no tests, checks, build, CI, migration, or COM call was run for this
  change. Behavioral state: `NOT_RUN`.
- Separate current-turn runtime evidence: the local gateway on port 21000 was restarted alone by
  `scripts/e2e/fault.ps1 -Component gateway -Action restart` after its exact ownership and
  disposable-reader preflight passed. `/healthz` and `/readyz` returned HTTP 200; Apache 8088 and
  proxies 8191–8193 remained listening. The updated MCP schema then accepted the optional
  `include_property_types` argument and returned metadata-only OData types for the local
  read-only reference source. This is not verification of the new COM error classification or
  Ivan's clone mapping.
- Strict SSH stack status returned `True` for all nine named Ivan components. The inspected COM
  ProgID is registered to the host's `comcntr.dll`, and `818HA_p2diff` exists. This does not prove
  a usable COM connection, a current license, effective rights, or a write boundary. No remote
  service, credential, database, or clone was changed by these checks.

## Remaining acceptance and ownership

The S13/S14 writer remains `NOT_READY`: an authenticated COM metadata/fingerprint session for the
selected disposable clone, canonical payload mapping, signed operation manifest, effective
writer-rights evidence, and physical-operation behavior are still absent. The previous recorded
COM `Connect` failure remains unresolved; the current turn only inspected registration and clone
presence. Accountable task owner: operator. Executor: Codex. Technical owner of the host/connection
boundary: Ivan stack. The canonical records inspected do not name a human owner for licensed
identity provisioning or the payload-to-COM mapping. Next: continue independent source closure;
restore read-only COM access through the credential-owning identity before binding the mapping or
implementing a physical operation adapter. Functional/E2E and specialist qualification remains
after all coding.
