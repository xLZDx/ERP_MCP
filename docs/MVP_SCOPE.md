# 1C Day-1 MVP acceptance

The MVP is production-ready only when all gates below pass.

- G1 Auth: unauthenticated/wrong issuer/audience/scope requests are denied.
- G2 Registry: add/revoke source access without code change or restart.
- G3 Secrets: no production credential stored in repository/env.
- G4 Read-only: production OData transport has no 1C write HTTP verbs/tools.
- G5 Compatibility: each source gets a persisted capability fingerprint and an explicit
  `SUPPORTED` / `SUPPORTED_WITH_FALLBACK` / `UNSUPPORTED` decision; JSON and Atom profiles
  are contract-tested with Fake1C.
- G6 Metadata: live `$metadata` discovers standard and extra OData-published objects.
- G7 Limits: rows, timeout, filter length, body/response size and rate limits enforced.
- G8 Audit: principal/client/tool/source/outcome/duration/fingerprint stored append-only.
- G9 Multi-company: at least three bases with different ACL grants.
- G10 Accounting: at least ten representative accountant questions reconciled independently
  against 1C UI/reports on a real test copy.
- G11 Operations: health/readiness, migrations, least-privilege DB roles and CI green.
- G12 Testbed: L1 Fake1C contracts green; L2 real file-mode 1C evidence captured; L3
  server-mode parity planned/executed before environment-specific production GO.

No gate may be waived by switching production into a development profile.
