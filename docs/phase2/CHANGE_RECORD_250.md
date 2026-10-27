# Change record 250 — bind the serving mutex SID to the process token

Date: 2026-10-25  
Scope: S13 Windows serving-authority identity admission.

## What changed

- `WindowsServingAuthorityMutex` now checks the configured service SID against the current process token before loading the Windows mutex APIs or creating/opening a named kernel object.
- The configured SID is accepted only as the token user (virtual service account) or as an enabled, non-deny-only token group (dedicated service identity). Missing/disabled identity fails with `SERVICE_SID_NOT_IN_PROCESS_TOKEN`; token query or cleanup failures fail closed with `SERVICE_SID_IDENTITY_UNAVAILABLE`.
- The disposable qualification contract now requires zero `CreateMutexExW` calls for negative/error cases and owner/DACL verification for both positive identity forms.

## Why

A syntactically valid caller-supplied SID did not prove that the process acquiring the serving lease actually ran under that identity. This guard binds the mutex owner/DACL principal to the current process token before any named-object operation.

## Contracts and paths

- `src/erp_mcp_private_writer/windows_authority_mutex.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md`
- `S13-SERVING-MUTEX-CONFIG-IMMUTABILITY-01`

## Verification state

- Source SHA-256: `2BD137170D82ABE7F66981534C9D78C7DAC3A6E74E5CF3F79D6C4D5F62F70007`.
- Static inspection only. Windows runtime qualification, tests/checks and database/COM operations remain `NOT_RUN`; no test or check was run during this code phase.
- No stage, commit or push was performed in this turn.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Technical owner: Windows host mutex/service-token boundary; no separate human service owner is established by this record.
- Next: finish S13 source closure; then delegate the required functional/E2E qualification and relevant specialist review after coding closes.