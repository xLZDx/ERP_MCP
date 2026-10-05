# 1C Day-1 MVP acceptance

The MVP is production-ready only when all gates below pass.

- G1 Auth: unauthenticated/wrong issuer/audience/scope requests are denied.
- G2 Registry: add/revoke source access without code change or restart.
- G3 Secrets: no production credential stored in repository/env.
- G4 Read-only: production artifact has no 1C write HTTP verbs/tools.
- G5 Metadata: live `$metadata` discovers standard and extra OData-published objects.
- G6 Limits: rows, timeout, filter length, body/response size and rate limits enforced.
- G7 Audit: principal/client/tool/source/outcome/duration/fingerprint stored append-only.
- G8 Multi-company: at least three bases with different ACL grants.
- G9 Accounting: at least ten representative accountant questions reconciled independently
  against 1C UI/reports on a test copy.
- G10 Operations: health/readiness, migrations, least-privilege DB roles and CI green.

No gate may be waived by switching production into a development profile.
