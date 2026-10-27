# Change record 317 — S13 persisted evidence resolver and production verification boundary

## Ownership and scope

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and closure owner: Codex.
- Technical boundary: ERP_MCP S13 private-writer persisted evidence read path.
- Acceptance: exact immutable evidence reload, production verification, and fail-closed T16 preparation.
- State: source implemented; candidate SQL remains revoked; specialist and disposable qualification pending.

## Change

Added `PostgresWriterEvidenceResolver` for exact signed-envelope reloading. The resolver obtains the
attempt from the existing exact-selector attempt source, checks the complete `CallIdentity` binding,
loads one receipt or the fixed five-record conditional-conflict set in a bounded read-only
`private_writer_evidence_ingest` transaction, and asks `ProductionEvidenceVerifier.verify_set` to
validate original canonical envelopes against one fresh trust snapshot. It re-derives each immutable
reference and checks row type, returned order and envelope bounds before constructing service result
records.

Added the candidate `private_writer_load_evidence_records_v1` SECURITY DEFINER routine. It has a
fixed search path, explicit evidence-ingest `SESSION_USER` check, a maximum of five unique bounded
references, an exact full-attempt selector, a per-envelope 2 MiB bound, and no direct table grant.
Its `EXECUTE` privilege is revoked from all roles including `private_writer_evidence_ingest` pending
independent database/security review and role-by-role qualification.

Changed the service resolver result contract to carry `VerifiedEvidenceRecord` objects associated
with each exact typed record. The service applies the structural S12 conditional-conflict predicate
after production verification and no longer invokes the evaluation-only registry signature wrapper
for this path. Production composition accepts only the concrete PostgreSQL evidence resolver.

## Affected paths

- `src/erp_mcp_private_writer/postgres_evidence_resolver.py`
- `src/erp_mcp_private_writer/service.py`
- `src/erp_mcp_private_writer/runtime_composition.py`
- `src/erp_mcp_private_writer/__init__.py`
- `db/phase2/027_private_writer_admission_schema.sql`
- `docs/phase2/S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md`

## Evidence and limits

Current SHA-256 values when recorded:

- candidate migration 027: `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F`
- resolver: `7957672779A7484382EBC1D1253683536DDF11EB11FCAF3655B5CC7AC76728DC`
- service: `93054D7FE20D7D34643938E40C6E2B119DD1583804E3059F90869285C23DEFCC`
- runtime composition: `2E83C8DFEAE1FE2A1ACFC3334CD36122B6ACB8B0CFB1B9480157CEE89DDFBBE2`
- package exports: `4372FC1A983750D963D31608349A716553B29F99BD53F1D1465796710013CC0C`

The hashes above identify the exact observed file bytes at this checkpoint. The pre-edit worktree was
branch `codex/erp-mcp-autonomous-2026-10-21`, HEAD
`3e12436bc874f6aa12b33cdee1ef6111ee33b25c`; the checkout already contained extensive dirty/untracked
files, including `service.py` and package exports. This record attributes only the resolver/service/runtime
integration edits described above, not the files' pre-existing contents.

The functional-test reviewer previously reported `15 passed in 234.75s` for
`tests/phase2/test_s13_current_turn_sql.py`, with migration hash
`9D0B5B2A30D6FB1C6185F10D60310745BC79EC175C71D691C44FE09B0A6249FF` and test hash
`CA2CF50C35429CEF2C861C4310568E4A28AF59EBA4158607D19E1575C86DCC44`. That run predates the new
resolver SQL routine and is not evidence for it. No test or check was run in the primary session.
No SQL parse, migration, grant, configured database, COM, stage, commit or push occurred for this
change. The candidate routine is uninstalled and ungranted; installed effective grants remain
`NOT_VERIFIED`.

## Ordered next work

1. Functional-test-reviewer adds and runs exact selector, wrong-scope, missing-reference, malformed
   array, oversized envelope and unauthorized-session cases on the revised exact migration hash.
2. E2E runner executes the real T16 service path using the concrete resolver, with only the COM
   boundary and immutable synthetic envelope locator isolated.
3. Database/security and Python reviewers inspect exact final diffs and hashes; fix all valid
   BLOCKER/MAJOR findings before any grant or deployment qualification.
4. Measure effective grants only in the owned disposable qualification environment; no live lane
   installation is authorized by this source change.


## Independent source review

The actual `code-reviewer` role (GPT-6 Luna, medium effort) reviewed the resolver, SQL selector,
service integration, runtime composition and exports without running tests, checks or SQL. It found
one MAJOR: a concrete resolver could still receive a forged trust-source implementation through the
verifier. The resolver now requires the exact `PostgresEvidenceTrustSource` and the same pool as the
attempt source; re-review confirmed that finding closed and found no additional BLOCKER/MAJOR. The
review found one MINOR array-shape edge; the SQL routine now explicitly requires a one-dimensional
reference array. The role separately rechecked that one-line correction and confirmed the MINOR closed. Exact current-hash functional qualification and independent database/security review remain required.

## 2026-10-26 exact candidate qualification update

The functional-test-reviewer ran `uv run pytest -q tests/phase2/test_s13_current_turn_sql.py -k evidence_loader` against the exact candidate migration SHA-256 `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F`: **23 passed, 15 deselected in 11.42s**. The test file SHA-256 before and after the final run was `EC85FCDC550ABC69D19BFECB49CDE3145CA3989778E4BCDBBE46D81829297853`. Coverage includes ordered one/five-reference reads, malformed and mismatched selectors, no-partial refusal, wrong session, oversized envelope and effective direct ACL/EXECUTE denial. Temporary EXECUTE grants were rolled back; cleanup used the invocation-owned disposable PostgreSQL 16 cluster. No configured lane database, real provider, COM, or production credential was used.

An independent database-reviewer inspected the same migration hash and routine/revoke lines 2888–2970 and 11754–11757. It found no actionable source issue. A separate security-reviewer reviewed the resolver, service integration, production composition, and candidate SQL at the hashes above and found no actionable BLOCKER/MAJOR/MINOR. These are source reviews, not SQL parser, installed-grant, or production runtime evidence.

The E2E runner did not execute `prepare_t16_resolution`: the genuine authenticated validator build-provenance source/policy required by evidence registration is absent. It also did not substitute a fake provenance source or checkpoint sink. The resolver SQL slice is functionally qualified in a disposable database; full production evidence registration and T16 service E2E remain `NOT_RUN`.

GPT-PM request `a8cb13d2-1dc0-45b4-a9d8-7e7c910d26f4` was correlated to project `erp_mcp`, conversation `6adf096a-b7c0-83eb-a0b9-5c05a5792783`, reply `715ec2da-934a-5823-ba47-0fe2984789e9`. GPT-PM agreed that keeping provider-dependent paths fail-closed while continuing independent resolver work remains within S13 scope. It identified activation dependencies for external anti-rollback provider, trusted signer/key custody, and authenticated validator build provenance; no PostgreSQL-backed substitute or fabricated identity is acceptable. This PM review assessed the attached checkpoint contract and resolver design, not a production-provider implementation or the later runtime-authority code.

Current acceptance state for this record: resolver source implemented; exact candidate SQL function passes its focused disposable functional matrix; independent DB/security source reviews found no actionable issues; production routine remains uninstalled and revoked; effective installed grants remain `NOT_VERIFIED`; T16 service E2E remains `NOT_RUN` on the missing authenticated build-provenance dependency. Accountable owner: operator; executor/closure owner: Codex. Next: continue independent S13/WP5 code while maintaining the external trust gates and exact provenance above.

### Full current-candidate S13 SQL qualification — 2026-10-26

After source closure, the functional-test-reviewer ran the complete `uv run pytest -q tests/phase2/test_s13_current_turn_sql.py` against the exact current candidate SHA `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F` and test-file SHA `EC85FCDC550ABC69D19BFECB49CDE3145CA3989778E4BCDBE46D81829297853`: **38 passed in 174.20s**. The child process used a fresh invocation-owned loopback PostgreSQL 16 cluster and throwaway databases; the DSN was not printed. The ownership label and exact container name were checked before cleanup; cleanup succeeded. No configured lane DB, installed environment, COM, or production provider was used. This broadens the previous focused 23-pass result but does not qualify runtime grants on the local lane or activate candidate 027. T16 service E2E remains `NOT_RUN` because the authentic validator-build-provenance source/policy and real external checkpoint trust authority are absent.



