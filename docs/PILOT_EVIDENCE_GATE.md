# P9 pilot and production evidence gate

`deploy/pilot/evidence.manifest.template.json` is an intentionally empty readiness template. It
does not claim that a pilot has started or that any production evidence exists. Copy it to a
controlled evidence workspace (do not commit filled manifests containing customer details), bind
it to the exact release commit, and run:

```powershell
python scripts/validate_pilot_evidence.py --manifest <controlled-manifest.json>
python scripts/validate_pilot_evidence.py --manifest <controlled-manifest.json> --require-go
```

The first command checks schema and any claimed decision. The second is the release gate and must
fail until all evidence is reviewed. It validates the manifest's claims and evidence metadata; it
does not fetch evidence artifacts, verify reviewer identity/signatures, run a 1C report, or prove a
zero-write deployment. A human release authority must independently verify each artifact in the
approved evidence store and confirm its SHA-256 before marking its gate `VERIFIED`.

## Gate meaning

- `ci_green`: full CI on the exact release SHA, including migrations and DB privilege checks.
- `production_config_review`: secure production settings, private topology, non-root deployment,
  pinned images/dependencies, network policy and TLS.
- `idp_authz_negative_tests`: issuer/audience/scope, revoked grant, deny precedence and company
  isolation checks in the target IdP/deployment.
- `secret_rotation_drill`: secret provider, access boundaries, rotation and rollback evidence.
- `source_company_isolation`: multiple real/synthetic sources and company-scoped reads prove no
  cross-source/company leakage.
- `source_capability_profiles`: exact-base live metadata/probe or validated profile evidence; no
  guessed virtual table names.
- `ten_case_native_reconciliation`: at least ten accounting scenarios reconciled to native 1C
  reports with discrepancies resolved or explicitly rejected. Synthetic L1 checks do not count.
- `zero_write_review`: evidence that the pilot identity and every adapter path are read-only, with
  no write side effects.
- `audit_provenance_review`: success, deny and failure records reviewed for provenance and leakage.
- `performance_load_test`: measured p50/p95/p99, concurrency, resource ceilings and fan-out limits.
- `resilience_drills`: Postgres/Redis/IdP/source/sidecar outage and restart behavior meet fail-safe
  expectations.
- `backup_restore_drill` and `rollback_drill`: completed, reviewed procedures on the target stack.
- `operations_oncall`: named operator/on-call, escalation and source onboarding/offboarding runbooks.
- `privacy_security_review`: data minimization, PII handling, threat review and incident process.
- `pilot_user_acceptance`: controlled pilot users confirm the bounded use cases and limitations.
- `production_release_approval`: accountable production authority approves this exact release.

Each verified gate must reference an evidence-store artifact ID, its lowercase SHA-256, reviewer and
offset-qualified review timestamp. Do not put credentials, raw accounting data, personal data, or
customer-identifying content in this manifest. The current repository has no real 1C L2/L3 pilot,
native report, production IdP, or restore-drill evidence; therefore its status remains `NOT_READY`.
