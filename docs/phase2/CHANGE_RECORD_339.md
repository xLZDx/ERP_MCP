# Change record 339 — bridge write-port payloads to typed COM values

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator; implementation owner: Codex; source reviewer: code-reviewer role.
- Before this turn's edits, `src/erp_mcp_private_writer/com_manifest.py` was already staged and modified in the shared worktree (`AM`); `__init__.py` was already modified and the disposable-prerequisites document was already untracked. Those existing changes are not attributed to this turn.
- This turn added a strict dictionary-to-`DraftPayload` decoder, a write-port wrapper for the existing approved-digest value extractor, package exports, and acceptance scenarios. It did not implement or enable a physical COM writer.

## Implementation

- `draft_payload_from_write_port()` accepts only the exact built-in dictionary shape emitted by `payload_to_dict`, exact line and duplicate-override shapes, and typed constructors that validate field values. All object dictionaries require exact built-in string keys before a key-set comparison; malformed objects return the stable `COM_APPROVED_PAYLOAD_INVALID` error.
- `com_values_from_write_port_payload()` rebuilds the typed model and delegates to the existing digest-checked CREATE_DRAFT extractor with no target-version preimage. The wrapper adds no property mapping, does not call COM, and does not authorize operations.
- The package exports both helpers. The qualification prerequisite now maps canonical round-trip, extra/missing fields, malformed nested shapes, target-version and digest refusal, hostile non-string keys, and exclusion of POST/UNPOST from this CREATE_DRAFT decoder.

## Review and verification

- A read-only `code-reviewer` pass found one MINOR error-sanitization issue in initial field-set validation. The code now checks exact string keys before any set conversion at the top-level, line and duplicate-override objects.
- The reviewer rechecked the latest `com_manifest.py` snapshot at SHA-256 `E3DA7F50E129DC4329B9D6B388D9F205C9A08C056B8F7E8E21F35EE3CBBE66EF`, confirmed the MINOR resolved, and reported no direct regression. Reviewer model/effort metadata was not exposed by the agent interface.
- Current SSH strict-host-key status returned all nine stack components `True`; the authenticated local MCP source-health call returned `ok=true`, HTTP 200. These are transport/source-health observations only.
- A read-only process/service-name query on Ivan returned no process matching `1cv8`, `hasplms` or `sentinel`; it reported generic Windows `LicenseManager` running and `ClipSVC` stopped/manual. These generic states do not establish 1C license availability, so no COM retry was made.
- No tests, checks, build, SQL parse, migration, database write, COM call, staging, commit or push ran. The required functional cases remain `NOT_RUN` until in-scope coding closes.

## Remaining gates

- The exact `818HA_p2diff` payload-to-1C property/type crosswalk and licensed read-only COM session remain `NOT_VERIFIED`; the concrete `OneCWritePort` is still absent. This helper closes only the typed-payload handoff needed by that future adapter.
- The candidate migration remains uninstalled and effective privileges remain `NOT_MEASURABLE` per CHANGE_RECORD_336. Source review does not establish runtime rights, transaction semantics or qualification.
- Next: Codex obtains the licensed clone metadata through the authorized Ivan stack and implements the physical writer against the reviewed crosswalk; then finish dependent WP7/WP8/WP10 code, followed by functional/E2E tests and relevant specialist review.
