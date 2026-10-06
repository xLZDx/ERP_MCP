# ERP_MCP Engineering Governance

**Version:** 1.1
**Date:** 2026-10-06
**Applies to:** code, infrastructure, migrations, adapters, documentation and vendor intake

## 1. Governance objectives

- prevent architecture drift;
- preserve read-only and security boundaries;
- make every production claim traceable to evidence;
- prevent license contamination;
- prevent unreviewed destructive actions;
- keep implementation aligned with exact source/configuration capabilities.

## 2. Authority and source of truth

The normative document precedence is defined in `DOCUMENT_INDEX.md`.

Code does not override an invariant simply because it already exists. If code conflicts with the
normative baseline, the conflict must be resolved through an explicit governance decision.

## 2A. Operator scope freeze — active

The operator froze further product-scope additions on 2026-10-06.

Authoritative baseline:
`docs/SCOPE_FREEZE_BASELINE_2026-10-06.md`.

While active:

- every issue/PR/task MUST identify the existing frozen requirement/gate it closes;
- new feature/scenario/adapter/integration families are blocked;
- deferred lanes cannot be promoted implicitly;
- upstream functionality does not become product scope merely because it is available;
- only the operator may explicitly rebaseline/unfreeze scope.

Scope-preserving work is allowed when necessary to close accepted scope:

- defect/regression fixes;
- security/privacy/compliance/license remediation;
- tests, observability, evidence, runbooks, restore/rollback;
- configuration/source mappings required by already accepted semantic requirements;
- external-evidence ingestion required by already accepted DAD scenarios;
- refactors with no new externally promised capability.

If a proposed task cannot cite an existing requirement/gate, it is treated as scope expansion and
MUST NOT start until operator rebaseline.

## 3. Change classes

### C0 — Documentation/non-behavioral

Examples: typo, diagram, comment, evidence link.

Requires:
- correctness check;
- no architecture/security behavior change.

### C1 — Bounded read-only feature

During the active scope freeze, C1 is allowed only when it implements an already frozen requirement; otherwise it is scope expansion and blocked.

Examples: metadata helper, semantic read tool using existing adapter contract.

Requires:
- tests;
- DoD trace;
- audit/limit behavior verified;
- no new protocol implementation if an approved upstream exists.

### C2 — Adapter/protocol/capability change

Examples: new OData behavior, new bridge, capability routing.

Requires:
- upstream search/intake statement;
- license decision;
- compatibility tests;
- failure/timeout behavior;
- ADR if contract changes.

### C3 — Security/data model/migration change

Examples: auth, ACL, secret handling, audit, DB schema, company scoping.

Requires:
- threat/impact analysis;
- migration + rollback;
- least-privilege validation;
- security tests;
- updated TDD/data model/docs.

### C4 — Production/deployment/destructive change

Examples: production secret rotation, source removal, DB destructive migration, data deletion,
rollback affecting customer access.

Requires:
- explicit operator/owner approval;
- exact target/environment;
- backup/rollback evidence;
- post-change verification.

**No deletion of files/data/resources is routine. Destructive actions require separate explicit approval.**

## 4. Pull request contract

Every non-trivial PR must state:
- exact frozen requirement/gate IDs advanced, or explicit operator rebaseline reference;
- exact scope;
- base/head SHA;
- affected normative requirements/DoD gates;
- security/data/license impact;
- tests/evidence;
- rollback;
- open risks/deferred items.

For adapter work it must also state:
- upstreams searched;
- chosen implementation/test or “none found”;
- pinned SHA/license;
- reuse mode: direct dependency / port / sidecar / isolated service / reference-only.

## 5. Reuse-before-rewrite

Protocol/register/bridge code is not written from scratch until:
1. adapter census/intake is checked;
2. pinned upstream implementation/tests are inspected;
3. license is compatible with intended reuse;
4. a documented gap remains.

“No time to inspect upstream” is not an exception.

## 6. License governance

- MIT/Apache/BSD-like code may be reused under their notice obligations.
- GPL/AGPL code is not copied/linked into core unless an explicit license decision changes the product strategy.
- LGPL is reference-only by default until linking/distribution obligations are reviewed.
- unlicensed code is reference-only.
- every imported substantial upstream component carries provenance and notices.
- CI must validate machine-readable intake policy.

## 7. Security governance

Security invariants are non-waivable by feature code:
- production auth cannot be disabled;
- production secret values cannot be committed or returned to AI;
- arbitrary target URLs are forbidden;
- write tools are absent from 1C MVP;
- runtime DB role cannot administer grants/sources;
- audit remains append-only;
- source/company ACL is evaluated server-side.

Any proposal to weaken these requires C3/C4 governance and an ADR.

## 8. Accounting correctness governance

A semantic tool may have three statuses:
- `DRAFT` — implementation/tests exist;
- `VALIDATED` — reconciled on designated real test configuration;
- `PRODUCTION_APPROVED` — DoD evidence complete for target environment.

Synthetic test success alone cannot promote an accounting tool to production-approved.

## 9. Schema/migration governance

Every migration:
- is monotonic/versioned;
- has forward and rollback/restore analysis;
- is exercised from the previous supported schema in CI/test;
- does not silently grant broader DB privileges;
- documents data backfill and failure semantics.

Destructive migration requires C4 approval.

## 10. Vendor/upstream update governance

Updating an upstream package/SHA requires:
- changelog/diff review;
- license re-check;
- upstream test parity;
- our contract suite;
- security/dependency scan;
- explicit note if upstream is pre-1.0/unstable.

Pin exact versions for production reproducibility.

## 11. Evidence and closure

A gate is closed only by evidence tied to:
- exact commit SHA;
- exact configuration/profile;
- exact test/run;
- exact source capability/metadata fingerprint when relevant.

“Worked previously” is not valid evidence after a material change.

## 12. Exceptions

Exceptions must be:
- explicit;
- time-bounded;
- risk-owned;
- documented with compensating controls;
- excluded from “production-ready” claims if they violate a mandatory DoD gate.

Silence is not approval.
