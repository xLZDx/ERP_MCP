# Autonomous implementation prompt — Admin Control Center

Use this only after ACC-00 governance/ADR approval.

You are implementing ERP_MCP Admin Control Center in repository xLZDx/ERP_MCP.

## Authority and baseline

- Read AGENTS.md, CODEX.md, SECURITY.md and docs/DOCUMENT_INDEX.md first.
- Respect normative precedence.
- Preserve the read-only 1C production boundary.
- Treat Admin Control Center work as C3 whenever it touches auth, ACL, DB schema, audit or secrets.
- Do not delete files/data/resources without explicit operator approval.
- Do not modify main directly.
- Start from the operator-approved exact baseline SHA and create feature/admin-control-center-implementation.
- feature/admin-control-center-design is reference/design evidence, not automatically normative.

## Required design inputs

Read all files under docs/admin-control-center, especially:
- PRODUCT_AND_UX_SPEC.md
- ARCHITECTURE_AND_API_CONTRACT.md
- RBAC_AND_POLICY_MODEL.md
- DATA_MODEL_AND_MIGRATION_PLAN.md
- TEST_AND_ACCEPTANCE_MATRIX.md
- IMPLEMENTATION_BACKLOG.md
- SECURITY_DECISIONS.md
- DRAFT_ADR_ADMIN_CONTROL_CENTER.md

If accepted ADR/normative docs differ, the accepted normative decision wins.

## Execution order

Implement ACC-01 through ACC-10 in dependency order. Do not enable a UI control before its server-side enforcement exists.

For every slice:
1. inspect exact current implementation and tests;
2. map change to normative requirements/DoD;
3. implement smallest coherent slice;
4. add negative security tests first for new authorization/egress paths;
5. run focused tests;
6. run full baseline verification;
7. record changed files, evidence and remaining gates;
8. commit with bounded message;
9. continue automatically unless blocked by explicit approval boundary or external dependency.

## Non-negotiable implementation rules

- browser never receives DB credentials or secret values;
- no CLI subprocess from HTTP handlers;
- no arbitrary source URL reaches an adapter without server egress policy;
- source probes are GET/HEAD-only, bounded and redirect-disabled;
- exact grant_id/assignment_id revocation;
- all mutations carry actor, reason, request ID, idempotency and optimistic concurrency;
- admin audit is append-only;
- business_ai_app remains unable to administer;
- platform roles, data scope and business capabilities remain separate;
- company-only grants do not authorize generic onec_read;
- capability role does not widen data ACL;
- unknown role/capability fails closed;
- local user passwords are forbidden;
- organization discovery is advisory unless profile evidence proves the mapping.

## Verification floor

At minimum after each coherent slice:
~~~powershell
$env:PYTHONPATH = 'src'
python -m compileall -q src tests scripts testbed
python -m pytest -q
python -m ruff check .
~~~

Also add/run:
- admin endpoint x role authorization matrix;
- CSRF/session tests;
- SSRF/egress source-probe tests;
- DB least-privilege tests;
- exact revoke/idempotency/concurrency tests;
- audit append-only tests;
- accessibility checks for the UI;
- migration forward/restore analysis.

## Stop conditions

Stop only for:
- required destructive action;
- missing explicit C3/C4 approval;
- unavailable external credential/service that cannot be safely mocked;
- contradictory normative requirements that require owner decision.

Otherwise continue through the next slice and keep status updated after each slice.

## Final handoff

Report:
- exact base/head SHA;
- commits;
- changed paths;
- completed ACC slices;
- tests/evidence;
- security/data-model impact;
- migrations/rollback status;
- unresolved production gates;
- whether PR is ready.

Do not create or merge a PR unless explicitly requested.
