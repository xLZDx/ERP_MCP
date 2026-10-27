# Change Record 259 — Preserve bounded 1C transport reason in source-health audit

Date: 2026-10-25

## Status

Source change only. No service reload, test/check, database operation, or runtime requalification was performed.

## What changed

- `OneCTransportError` now carries a bounded internal code. Codes are limited to uppercase ASCII letters, digits, and underscores, up to 48 characters; unrecognized values collapse to `TRANSPORT_ERROR`.
- Native 1C transport failures now use stable codes for malformed paths, host mismatch, egress denial, timeout, network error, upstream HTTP status, unsupported content encoding, oversized response, and exhausted retries.
- The `source_health` audit writes that code for `OneCTransportError`; the caller still receives the existing generic `SOURCE_UNAVAILABLE` response.

## Why

The observed gateway `source_health` request returned `SOURCE_UNAVAILABLE`, while the correlated audit recorded only the common exception type `OneCTransportError`. That lost the client's already-safe transport category and prevented distinguishing a timeout, network failure, or upstream HTTP status without exposing the underlying exception text.

## Evidence and limits

- `src/business_ai_gateway/adapters/onec/client.py`: transport error class, safe code assignments, and both GET/HEAD exception mappings.
- `src/business_ai_gateway/server.py`: `source_health` error-audit branch.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: added `GATEWAY-SOURCE-HEALTH-TRANSPORT-CODE-01` for the post-coding functional/E2E phase.
- Prior observed gateway audit for correlation `db285a23-1feb-4e35-8caf-05ad5f2d8791` recorded `OneCTransportError`; direct authenticated metadata GET and HEAD through proxy 8191 returned HTTP 200. This change has not been loaded into the running process and does not explain that prior event retroactively.
- No tests/checks/build, service restart, migration, DB mutation, staging, commit, or push was performed.

## Follow-up

After a normal authorized gateway deployment/reload, repeat one read-only `source_health` request and inspect its correlated audit code. Keep the public failure response generic. Required functional/E2E coverage belongs to the post-coding test phase.

Accountable owner: operator. Executor: Codex. Technical owner for the local gateway process: UNKNOWN in inspected canonical records.
