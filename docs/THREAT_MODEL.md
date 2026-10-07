# ERP_MCP Threat Model

**Version:** 1.1
**Date:** 2026-10-06

## Assets

Critical:
- source credentials;
- OAuth identity/claims;
- source/company ACL;
- audit/provenance;
- accounting data returned from 1C;
- semantic profiles/mappings;
- production endpoint registry;
- private real-reference test artifacts and external evidence documents;
- Ferma oracle independence;
- test-only write boundary.

## Adversaries / failure sources

- unauthorized external client;
- compromised/overprivileged valid user;
- prompt/tool injection through business data;
- malicious/compromised upstream source;
- vulnerable third-party adapter/dependency;
- operator misconfiguration;
- accidental source/company scope mix-up;
- compromised internal adapter process;
- supply-chain/license error;
- malicious/untrusted external evidence document;
- accidental publication of private reference artifacts;
- test-only seeder/write helper exposed to production;
- scope creep that bypasses review/evidence.

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


## External evidence threat model

External evidence is untrusted input even when supplied by an accountant/operator.

Threats:
- prompt/instruction injection embedded in PDFs/XLSX/text;
- parser exploit/decompression bomb;
- stale/forged document;
- evidence associated with the wrong company/source;
- sensitive evidence leaked to logs/public CI/model context.

Controls:
- approved ingress only; no model-supplied arbitrary URL;
- MIME/size/decompression/parser limits;
- content fingerprint/provenance;
- explicit source/company association;
- business content treated as data, never policy/instructions;
- bounded extraction;
- retention/minimization and private storage;
- missing/invalid evidence yields explicit non-PASS state.

## Real-reference testbed threat model

The private real-reference base may contain realistic/customer-derived information even though it is
designated for testing.

Controls:
- immutable private golden archive;
- safe alias in public repo;
- disposable clones only;
- least-privilege RO identity for read validation;
- separate write-capable test identity only for isolated RW clone;
- no raw archive, credentials, private links or customer identifiers in Git/public CI;
- fingerprints and bounded sanitized summaries only.

## Test-only write boundary

Threat:
- Ferma seeder or historical write helper becomes callable from production MCP.

Controls:
- separate package/process/credentials;
- synthetic/test target marker;
- deny production source IDs;
- no production tool registration;
- package/tool inventory negative tests;
- no generic arbitrary mutation API.

## SC08 duplicate-counterparty candidate tool (explicit operator rebaseline 2026-10-07)

Tool `counterparty_duplicate_candidates` is a name-based, read-only candidate detector; semantics are
frozen in [SC08 contract](SC08_DUPLICATE_COUNTERPARTY_CONTRACT.md).

| Threat (STRIDE) | Risk | Controls |
|---|---|---|
| Information disclosure: counterparty names/codes leak | Names/codes reach unauthorised callers or telemetry | Returned only to callers authorised for source/company + `accounting.read`; never in audit rows, logs, metrics or evidence artifacts |
| Information disclosure: company-scope over-disclosure / false positive | Catalog has no company dimension; a pair from another company is shown | Activity-first two-phase scoping: catalog rows without company activity are never returned or counted |
| Tampering / elevation: merge or write | Candidate output used to mutate 1C | No merge/write capability; `merge_count` literal 0; read-only OData verbs only; no write verb reaches Fake1C or the sidecar |
| Tampering: partial result presented as complete | Truncated read yields a misleading FINDING | Truncation fails closed: INCONCLUSIVE, never a partial FINDING |
| Spoofing of evidence: fixture profile | Synthetic profile mistaken for real mapping | Fixture profile is test-only (`BAG_ENVIRONMENT=test`, hash-pinned); production fails closed with zero upstream reads; evidence is L1, never native reconciliation |

## Scope-freeze control

Scope expansion is itself a governance risk because it can delay closure and bypass threat/evidence
analysis.

Every new work item must cite an existing frozen requirement/gate. No trace -> no execution until
explicit operator rebaseline.

## Hybrid OData + COM analytics balance route (ADR-0008, operator decision 2026-10-07)

Tool `accounting_balance_by_analytics` reads balances by analytics through OData (primary) or a separate local COM bridge
(fallback). The route is chosen before execution from persisted evidence; there is no runtime fallback.

| Threat (STRIDE) | Risk | Controls |
|---|---|---|
| Tampering / elevation: caller text reaches a 1C query | Injection through account, company or date input | The tool has three parameters (`source_id`, `company_id`, `as_of`); account keys are GUIDs from the validated profile; the COM bridge runs one fixed code-owned template with typed parameters; no query text crosses any boundary |
| Spoofing: wrong physical source behind a logical source id | A stale COM binding answers for a re-registered source | The binding pins source id, base-URL hash, credential identity, configuration and metadata fingerprints; any change invalidates it until re-approval; the bridge refuses a request that does not match its own binding table |
| Information disclosure: cross-company rows | Company A reads company B through a shared base | Company reference must be in the binding's allowed set, checked before any COM call; the bridge filters by the company dimension, selects it in every row and fails closed on a row of another company; the gateway client and normalizer compare each row's company again; an OData row without the company property is refused |
| Information disclosure: silent fallback hides a real failure | An OData 401/503 is answered from COM | Selection is by evidence only; any selected-route error fails closed with zero COM calls; tests assert the call counts |
| Elevation: write or generic execute through COM | The bridge becomes a general 1C client | No write verb, no execute, one template, reader identity only, loopback + bearer, row cap and timeout; a test asserts the absence of write capability |
| Information disclosure: secrets | Reader password in a response, log or process argument | Secret references are resolved only inside the bridge; errors are sanitized; nothing secret is returned to the gateway or the model |
| Tampering: parity evidence from different databases | OData and COM compared on two copies | Parity is claimed only with a separate publication bound to the same disposable clone and a same-database proof before comparison; otherwise reported as cross-copy comparison |
| Denial of service | Large balance sets or COM license exhaustion | Row cap, timeout, one connection per binding, bounded accounts and analytics slots; after a timeout the binding stays poisoned (immediate `COM_UNAVAILABLE`, no second 1C session) until the abandoned query returns; at most two requests per binding are admitted so a slow binding cannot starve the others; the body cap is checked on `Content-Length` before the body is read; production licensing topology is an open item |
| Spoofing: bridge identity is configuration, not attestation | `clone_identity` and `metadata_fingerprint` come from the operator's bridge file and are not recomputed; the bridge does not itself refuse the reference clone path | Operator attestation: the binding is approved by the operator, the gateway compares the echoed identity with its own binding, the COM route serves only the fixed register and company field, and production binding review must confirm the base path is not the reference clone |
