# ERP_MCP Threat Model

**Version:** 1.0  
**Date:** 2026-10-05

## Assets

Critical:
- source credentials;
- OAuth identity/claims;
- source/company ACL;
- audit/provenance;
- accounting data returned from 1C;
- semantic profiles/mappings;
- production endpoint registry.

## Adversaries / failure sources

- unauthorized external client;
- compromised/overprivileged valid user;
- prompt/tool injection through business data;
- malicious/compromised upstream source;
- vulnerable third-party adapter/dependency;
- operator misconfiguration;
- accidental source/company scope mix-up;
- compromised internal adapter process;
- supply-chain/license error.

## STRIDE-oriented threats

### Spoofing

Threat:
- forged bearer token;
- caller-supplied identity;
- fake internal adapter.

Controls:
- JWT signature/issuer/audience/expiry/scope validation;
- principal derived only from validated token;
- private/authenticated internal adapter channel;
- stable source IDs and adapter binding.

### Tampering

Threat:
- registry/grant modification by runtime;
- audit history modification;
- metadata/profile manipulation.

Controls:
- split DB roles;
- append-only audit;
- admin/migration separation;
- profile/version provenance;
- governance/PR/migration controls.

### Repudiation

Threat:
- user/agent denies running a query;
- results cannot be tied to adapter/schema.

Controls:
- request ID;
- subject/client/tool/source/company;
- query fingerprint;
- adapter version/SHA;
- metadata/profile fingerprint;
- immutable audit.

### Information disclosure

Threat:
- credentials/tokens in logs/model responses;
- user accesses another company's data;
- excessive fields returned.

Controls:
- secret provider/reference model;
- source/company ACL;
- projection/byte/row limits;
- redaction/anonymization options;
- telemetry minimization.

### Denial of service

Threat:
- expensive filters/register queries;
- unbounded fan-out across 150 companies;
- slow/down source consumes workers;
- huge ValueStorage/text.

Controls:
- rate limits;
- deadlines;
- concurrency/fan-out budgets;
- circuit breaker;
- response/field size caps;
- server-side register aggregation;
- source isolation.

### Elevation of privilege

Threat:
- model supplies arbitrary URL;
- raw native query used to mutate/execute code;
- runtime changes grants;
- upstream write APIs leak through wrapper.

Controls:
- registered endpoint only;
- read-only operation allowlist;
- typed/validated native read query;
- runtime DB least privilege;
- mutation-negative tests;
- public/internal tool inventory checks.

## Prompt/data injection model

All text read from 1C is **untrusted business data**, not instructions.

The gateway/model integration must:
- never treat 1C text fields as authority to change policy;
- never derive tool permissions from returned content;
- keep policy/identity outside model-controlled payloads;
- keep read-only boundary even if returned text asks for write/destructive actions.

## SSRF model

AI cannot provide arbitrary endpoint URLs.

Admin source registration must validate:
- scheme;
- credentials not embedded in URL;
- allowed network policy;
- redirect behavior;
- DNS/host resolution policy where applicable.

Adapter requests are pinned to the registered source/binding.

## Supply-chain model

For every upstream:
- exact SHA/version;
- verified license;
- intended reuse mode;
- security/dependency scan;
- contract tests;
- upgrade review.

Copyleft/unknown-license code follows ADR-0006.

## Residual risk

No technical control can prove accounting semantic correctness for an arbitrary custom 1C
configuration. That residual risk is controlled through semantic profiles and native-report
reconciliation before production approval.

## Admin Control Center threat-model delta

Additional assets include platform-role bindings, admin sessions/CSRF tokens, admin mutation/idempotency records, source onboarding endpoints and business capability policy.

Additional threats and controls:
- OAuth login CSRF/code interception: state + nonce + PKCE, exact redirect URI, validated issuer/signature/audience and one-time login state.
- Browser bearer theft: access tokens stay server-side; browser cookie is opaque, HttpOnly, SameSite and Secure in production.
- Ambient-cookie mutation CSRF: all cookie-authenticated non-read admin routes require the per-session CSRF token.
- Privilege escalation: distinct admin audience/scope plus DB-backed platform role enforcement; UI visibility is never authorization.
- Confused deputy across delegated sources: every source/company/policy mutation is checked against the actor's effective platform-role source boundary.
- Source-onboarding SSRF/DNS rebinding: exact host allowlist, optional approved CIDRs, server-side DNS resolution, redirects disabled, bounded GET/HEAD-only probe and registered endpoints only.
- Duplicate/replayed mutations: actor-scoped idempotency key + request fingerprint and optimistic row version.
- Audit tampering: admin and runtime audit tables reject UPDATE/DELETE.
- Company-scope bypass: generic source reads cannot consume a company-only grant; explicit company-aware reads require a validated metadata-bound company predicate before adapter execution.
