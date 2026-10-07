

# Risk status

<!-- ENGINEERING_CHECKPOINT=CAPABILITY_BOUNDARY_20261006 ENGINEERING_IMPLEMENTATION=ba43973ae6c4787b5fec7d81063fd88e628df46cc0ff26df831bd78f8a0049eb -->

## Capability observation boundary — 2026-10-06

Risk reduced: unavailable metadata is no longer durable schema truth, and the runtime role cannot directly acknowledge or rewrite drift status. Remaining risk is limited to executing the new privilege/upgrade acceptance against a live disposable PostgreSQL service and then deployed/native gates.

## Fault-injection runner — 2026-10-06

Risk reduced: the runner cannot silently convert a dry-run Compose plan into outage evidence; every unexecuted dependency case is marked `NOT_RUN`. Remaining risk is unchanged for real deployed secret-provider/OData/RSV/audit recovery, retention/DR, native parsers and live 1C reconciliation. Production remains NO-GO.

## Internal settlement aging — 2026-10-06

FR-E1/D9: internal exact-profile AR/AP document/payment/allocation→aging contract implemented; REUSES existing aggregate_open_items, no second bucket engine/source protocol. Source/company/config/semantic/metadata/as-of/timezone/due-date/relationship/native-report/sign encoding fingerprinted. Partial settlement and multiple explicit allocation identities preserved; counterparty+contract+document/payment chronology exact, no FIFO/guessing or cross-currency conversion. Advances remain credits without netting other debt; payment overallocation blocked, document oversettlement visible anomaly/credit. Unknown opening/incomplete/stale/cross-scope/duplicate/nonfinite relationships cannot PASS. Canonical reused aggregator now bounds 2000 rows/schema/IDs/as-of/decimal precision, rejects float/hidden query fields, sanitizes errors and preserves micro-units at 120-digit local context. 34 focused aging/allocation contracts PASS; synthetic-only source semantics/native approval not inferred; private money/party output not public evidence. Parent 672fec4 CI 37501690166 FOUR jobs PASS (tested merge c12409bb4f8b6cc6a53e7de73e9f32dbef9654a9). Full current suite 769 passed/18 skipped; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render/release gates PASS. Own hosted run pending. Runtime public AR/AP-aging tools/live source collectors/approved real mapping/native reconciliation, frozen month-close/tax/payroll/native parsers/Ferma/fault/deployment/retention remain OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=FINANCIAL_PROJECTION_20261006 ENGINEERING_IMPLEMENTATION=af6dabd96d613dfed3d4265ee0941b472abb90b0572ea97bdf52f74bdd09b4d8 -->

## Internal financial projection — 2026-10-06

DAD-4/D9: internal exact-profile Balance Sheet/P&L/Cash Flow projection and independent native comparison contract implemented. Scope/config/metadata/chart/activity metric-sign-row mapping/period/currency/timezone/comparative/effective-date/native-report/tolerance fingerprinted; no universal chart, protocol/query/formula generator. BS exact as-of known-opening snapshots; P&L gross turnovers; cash flow only confirmed gross cash events, never balances. Explicit zero coverage required; missing/unmapped nonzero/duplicate/nonfinite/stale/cross-scope facts cannot PASS. Required comparative snapshots AND comparative native reports independent/complete. Result hash binds data/artifact/level, rejects mutation; native approval requires exact profile hash, not shared mapping-name alias. Private monetary projection stays private; hashed mismatches/human review/no evidence-level upgrade or source/release GO. 32 focused statement contracts and 71 combined statement/invoice rules PASS. Public financial tools/live collectors/real chart/native report validation remain OPEN. Parent 15fc9d0 CI 37499186509 FOUR jobs PASS; unused pip cache failure at 160e3c9 fixed, release assembly restored (tested merge e1790df45ef6f84638918bbafc347087bdd1cf15). Current full suite 741 passed/18 skipped; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render/release gates PASS. Own hosted CI pending. Full frozen month-close/tax/payroll/aging/native parsers/corpus/Ferma/fault/deployment/retention remain OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=INVOICE_RULE_PACK_20261006 ENGINEERING_IMPLEMENTATION=39ee0ad1433f488681518a0f30441874123164387f37eb197d7ccf56404dc32e -->

## Invoice normalized rule pack / CI fix — 2026-10-06

DAD-2/D9/D11: internal versioned eleven-case invoice comparison pack implemented with exact source/company/config/metadata/buyer/item/native-report/amount-encoding profiles, bounded typed independent observations, parser snapshot and detached-facts fingerprints. Source-specific service/overhead applicability; no universal 821, tax/VAT deductibility inference or 1C mutation. Verified primary archive proof binds scope+invoice/supplier+original digest; normalized carrier/source digest cannot masquerade as original, absent proof EVIDENCE_REQUIRED. Missing receipt never manufactures other PASS checks. Quantity/price/discount/net/VAT/total/header math discrepancies remain findings; profile line-VAT rounding requires EXACT header totals and cannot waive total mismatch. Hashed findings preserve L1/native/legal approval false. 106 focused rule/parser/CSV tests PASS: all eleven frozen logical aliases are SYNTHETIC, not real private corpus. Parent 160e3c9 CI 37496725289 FAILED only in setup-python post-step: unused pip cache directory absent while uv installs dependencies; tests/security/build gates successful, OData+Windows PASS, release assembly skipped. Removed unused cache: pip, no test/security suppression. Last fully verified bda7e34 CI 37494671262 retained. Current full suite 709 passed/18 skipped; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render/scenario/release gates PASS. Own hosted remediation pending. Public/live invoice delivery, native extraction/original archive/private corpus, full month-close/statements/tax/aging/Ferma/native/fault/deployment/retention remain OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=STRUCTURED_INVOICE_INPUT_20261006 ENGINEERING_IMPLEMENTATION=5d379650bceed8faa9f12159d0dd7dfeed20945b8e981c73c20a889885106548 -->

## Structured normalized invoice input — 2026-10-06

DAD-2/EVID-1/D4/D11: explicitly approved INVOICE-only normalized JSON codec supports scoped header/line supplier-buyer identity, invoice number/date, currency, quantity/price/discount/net/VAT/total, item-quality-UOM and service dates. Shared exact source/profile/retention/digest gate reused; strict UTF-8/exact schema/duplicate/size/row/decimal/date validation. No content sniffing, native PDF/XML/UTF16 fallback, policy overrides or class relabelling. Private store/index/runtime safe manifest support exact approved JSON MIME; operator CLI requires explicit --mime application/json. Immutable facts preserve arithmetic discrepancies for future rules, never auto-repair/legal VAT approval. Carrier fingerprint explicitly NORMALIZED_CARRIER; original PDF/archive fingerprint never inferred. Generic scalar DAD comparator rejects invoice line type. 121 focused invoice/existing CSV/store/operator tests PASS, including 29 structured invoice contracts; backward compatibility unaffected. Parent bda7e34 CI 37494671262 FOUR jobs PASS (tested merge 38d36f99bc96f6f2fd2e28c610f25a5a656603b6). Current full suite 670 passed/18 skipped; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render/release gates PASS. Downloaded parent release exact head/merge, four image/SBOM and five JUnit summary hashes verified; SHA256 8289372cf43a40879915ca4b25807404ceb8a5832d9738350fa4bb1b82db4fb0, scanner PASS. Own hosted CI pending. Eleven invoice business rules, native extraction/original archive/live collectors/real corpus, month-close/statements/tax/aging/Ferma/native/full fault/deployment/retention remain OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=APPROVED_EVIDENCE_RUNTIME_20261006 ENGINEERING_IMPLEMENTATION=6f14065bc3613f0e4b370fe11fa60585f58704c6afbb2c5efb069513bb6852d5 -->

## Approved private evidence runtime — 2026-10-06

EVID-1/FR-F1/D11/D4: optional runtime provider and read-only external_evidence_manifest wired behind normal gateway scope/source-company ACL/rate/durable access receipt. Model inputs are bounded IDs only, never path/hash/profile/policy approval. Private operator-pinned static index (512 KB/64 entries) binds actual receipts, parser fingerprints, exact scopes and UTC READ-approval windows; strict duplicate/schema validation, file permissions and SHA checked before AND after blob reading, no stale approval cache. Only safe manifest returned: business_acceptance NOT_EVALUATED/native NOT_PROVEN; timeout/tamper never PASS. Operator-only CLI persists approved normalized CSV into private store and publishes a NEW pinned index, preserving previous records; actual subprocess repeat rejects overwrite without raw diagnostics. 117 focused tests PASS/zero skips with actual app-role PostgreSQL: receipt visible before actual SDK/provider FS read, correlated completion/no raw query; readonly append failure prevents provider call. ACL contracts are stubs, not live/native acceptance. Settings paired/absolute/hash-pinned, validation inputs hidden; metric tool allowlist matches new endpoint. Source docs/env examples/34 offline render synchronized. Parent 908d7ac CI 37491887628 FOUR jobs PASS (tested merge 9ae4efde9debe89a82152d62d1e2ac9db2d1e4e4). Full current suite 641 passed/18 skipped; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render/release gates PASS. Own hosted CI pending. READ approval expiry is NOT physical/legal retention; deployment/retention/DR/native parsers, invoice/month-close/statements/tax/aging/Ferma/native/fault/deployment remain OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=PRIVATE_EVIDENCE_STORE_20261006 ENGINEERING_IMPLEMENTATION=29e6051f77bd1a7c7dcfd770209a6cf1f1552babf190a301839969d51a74779d -->

## Private normalized evidence storage — 2026-10-06

EVID-1/D11/D4: private append-only local normalized evidence provider implements new outside-Git protected stores, opaque references, exclusive file creation, fsync and final manifest commit marker. Existing approved bounded CSV parser reused for all 14 classes; native formats/URLs/decompression NOT enabled. Reopen binds independently pinned manifest/document SHA, exact source/company/config/profile and retention approval. Actual disk/NTFS permissions, Everyone file-ACL widening rejection, owned junction rejection, hardlink/traversal/tamper/oversize/orphan/no-overwrite controls PASS. Shared permission verifier is read-only on existing objects; RSV ACL behavior retained. Internal reader requires OAuth scope/current company ACL/rate/durable access receipt before filesystem; completion/error audit and bounded deadline; background timed-out thread remains read-only. 91 focused store/OS/evidence tests PASS (45 store, 8 RSV privacy, 38 normalized evidence); runtime/testbed Bandit and Ruff PASS. Parent 98dabc3 CI 37490159346 FOUR jobs PASS (tested merge ae49662738357246a88f26e4ce7c82539f1f932f). Full current suite 607 passed/17 skipped; combined Windows privacy/bridge/wire/store suite 81 passed/zero skips; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render/release gates PASS. Own hosted verification pending. Receipt index/operator ingest/runtime wiring, production volume identity/retention/DR, native parsers and frozen DAD/Ferma/native/fault/deployment remain OPEN; no WORM/PITR/native acceptance inferred. Production NO-GO; DoD PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=DAD_SMALL_NORMALIZED_RULES_20261006 ENGINEERING_IMPLEMENTATION=ace9edf0e6a05c37684ffe5bbf65d6f12d41b4ad4123deabedfe3b708bbf123b -->

## DAD six internal checks — 2026-10-06

DAD-1/D9/D11: internal DAD-SMALL-01..04 arithmetic engine implemented over bounded typed facts, exact approved versioned source/company/configuration/semantic/metadata profiles and selectors. No universal account numbers, query engine or register naming guesses. Negative quantity/value, gross no-movement, contract/document/currency cross balances and complete continuous daily cash checks. Invalid, truncated, stale, duplicate or wrong-grain facts never PASS; unconfirmed profile CAPABILITY_UNSUPPORTED. DAD-SMALL-05/06 reuse existing provenance-bound normalized Z/terminal comparator; missing evidence EVIDENCE_REQUIRED, mismatches enumerate hashed findings. 122 focused DAD/evidence tests PASS, including 46 small-check contracts. Source collectors, runtime ACL/audit exposure, real profiles/native acceptance remain OPEN; no native approval/level upgrade. Normative coverage table now distinguishes internal PARTIAL from native OPEN; 34-source offline copies synchronized. Audit parent f84e84b CI 37489215259 FOUR jobs PASS; tested merge 99f38d53b64fc7fe417897ac638da0282b79f474. Current full suite 562 passed/17 skipped; Ruff, runtime/testbed Bandit, compileall, checkpoint/report/source-render and release preflight gates PASS. Own CI pending. Frozen invoice/month-close/statements/tax/aging/evidence storage/Ferma/native/fault/deployment work remains OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=PREDISPATCH_DURABLE_AUDIT_20261006 ENGINEERING_IMPLEMENTATION=54d54d2bd076e5d3064c48521a055c646e44a4874b0774654db47d9f9eabcfe5 -->
## Durable pre-dispatch audit — 2026-10-06

FR-F1/D11: source/company ACL and rate checks precede durable ACCESS_AUTHORIZED receipt; adapter, secrets and capability calls occur only after append succeeds. Receipt and completion share the transport request context; receipt does not count business success. Every real Audit append failure, including completion, is normalized to AUDIT_UNAVAILABLE with provider context suppressed; cancellation propagates. 52 focused tests PASS with actual migrated disposable PostgreSQL app role: receipt observed inside adapter, two correlated rows with NULL raw query, readonly append failure prevents adapter dispatch and drives audit alert metrics. Direct SDK test explicitly establishes transport request context. Invalid metric policy rejected before INSERT. Normative data/SRE docs and 34-document offline render synchronized. Parent e462941 CI 37487651656 all four jobs PASS (tested merge 1905d0a6adfa8241d0ae700713c9e39cd0fb0613). Current full suite 516 passed/17 skipped; Ruff, runtime/testbed Bandit, compileall, release preflight, 12 synthetic scenarios, checkpoint/report/source-render gates PASS. Downloaded parent release bundle exact head/merge plus four image/SBOM and five test summary hashes verified; bundle SHA256 9102f3ca99ee35ec69244b467c1297860783d60b0d4a5295e6b4c4ef655bb32c. Own hosted run pending. Remaining frozen DAD/Ferma/native/fault/deployment/evidence storage/ACL/parsers remain locally OPEN. Production NO-GO; DoD PARTIAL; PR #11 Draft.
<!-- ENGINEERING_CHECKPOINT=RSV_WIRE_BOUNDS_20261006 ENGINEERING_IMPLEMENTATION=a886933286d4662657d4e7391da15d1d5b28987b32b27976defd92891e481cb5 -->

## Scoped pre-parser RSV wire resource guard — 2026-10-06

P6-SEC-1/NFR-R2/D4/D8/D14: locked SDK TextReceiveStream is wrapped once with per-stream RSV ContextVar activation; 5 MB line/10 MB session/64 frames enforced after UTF-8 decode BEFORE JSON parsing. Only owned receive pipe closes on excess; fixed code, no raw stdout/cleanup details; SDK retains spawning/framing/teardown, upstream COM bridge unchanged. Fragmented/multibyte/boundary/reset/flood/cleanup/idempotency/concurrent non-RSV contracts PASS. 36 focused privacy/bridge/wire tests, executed 19-case lifecycle harness and actual native bridge 1 PASS (zero skips); default 6 MB attacks actually rejected before parser, fresh sessions/rotation recover. Initial flood was a fixture failure: SDK diverted handler stdout to stderr; corrected with test-only saved wire descriptor. Malformed case now proves SDK validation received it, not just timeout. SDK seam coupling documented; Windows job includes wire contracts. Parent 2c86e51 CI 37484138607 four jobs PASS. Full current local suite 510 passed/16 skipped; Ruff/Bandit(runtime+testbed)/compileall/checkpoint/source-render/report gates PASS. Wire batch awaits its own hosted run. Native engine crash/zero-write/accounting, DAD/Ferma/full fault/deployment/evidence storage/ACL/parsers remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=SCRIPT_EVIDENCE_HARDENING_20261006 ENGINEERING_IMPLEMENTATION=44c37233b715dda3413d94fd58fb1ff0ee16dd8b8f72bd6880fc57f6c3c6e6d5 -->

## Hardened actual-case evidence and optimization-proof ACL guard — 2026-10-06

SCOPE-1/NFR-P2/D0/D1/D14-D18: execution harnesses now share bounded defusedxml JUnit parsing with release summaries; DTD/malformed/oversized/missing reports fail sanitized, suite totals cannot manufacture actual cases, declared failure/skip signals stay blocking. Spawn errors sanitized; summary CLI refuses overwrite. ACL measurement guard survives actual python -O; five SQL identifier-injection cases denied before dispatch. 49 focused tests PASS. Hardened reader reruns: fault/JWKS 11, SDK RSV 10, pinned private Ferma 47, actual native bridge 1 PASS (zero skips); four actual fanout mutations killed; five artifacts scanner PASS. Expanded scan reduced 38 to 35 findings; remaining 5 medium contexts documented with controls/tests, not suppressed or production approval. Parent 0eb66fd CI 37481295210 four jobs PASS. Full current local suite 501 passed/16 skipped; Ruff/Bandit(runtime+testbed)/compileall/checkpoint/source-render/report gates PASS. Script batch awaits its own hosted run. Remaining frozen DAD/Ferma/native storage/parsers/ACL/full fault/deployment/stdout gates OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=DASHBOARD_SOURCE_SYNC_20261006 ENGINEERING_IMPLEMENTATION=b0c9ec58d9d448e9425d9dbc8e224c34c2ad1926a8e86323c0c1055057fcf572 -->

## Authoritative offline documentation source/render synchronization — 2026-10-06

SCOPE-1/D0/D18: both offline dashboards now deterministically embed all 31 required normative sources plus 3 existing supporting sources using locked dev-only Python-Markdown 3.11 and narrow presentation policy. Source SHA plus exact sanitized render checked; source drift, hash-only forgery, altered/missing/duplicate bodies/cards, divergent copies fail CI. Phase-status overlay retained; known normative links use shared offline anchors; scripts/data URLs/tracking images cannot activate; code operators remain exact. 14 focused tests PASS; installed dependency audit found no known vulnerabilities, runtime lock unchanged; Ruff/Bandit(runtime+testbed+renderer) PASS. Legacy copied read/device wrapper text removed from report/dashboard shells; immutable freeze source/hash retained, wrappers omitted only in presentation. Expanded scripts audit separately reports 38 findings (6 medium) for triage, not suppressed or mislabeled closed. Parent 42ecfbe CI 37478449261 four jobs PASS; full current local suite 479 passed/16 skipped; Ruff/Bandit(runtime+testbed+renderer)/compileall/checkpoint/source-render/report gates PASS, browser header/status review PASS. Dashboard batch awaits its own hosted run. Native/DAD/Ferma/full fault/deployment/source stdout gates remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=FERMA_PINNED_EXPORT_20261006 ENGINEERING_IMPLEMENTATION=939f780dd1f7cb3b77f394eece05b3586bbc60fec8097be8287511300b6881bf -->

## Actual pinned Ferma generator/oracle package export — 2026-10-06

TEST-FERMA-1/D5/D9/SCOPE-1: private pinned Ferma package exporter directly reuses committed generator, integrity/usage-policy gate, transitive oracle boundary and independent OracleProjector for two existing scenarios. Source snapshot SHA verified before/after; cached bytecode/symlinks/changed/oversized sources refused, no runtime production import/source copy, output outside Git/new directory only. 47 executed exporter/intake/comparator/checkpoint contracts PASS, zero skips; actual bakery 4 events/8 master records and chain 9 events/321 records exported privately. ActualProjector corruption cannot alter expected; unavailable oracle creates no package; wall clock cannot alter economic outputs. Native Ferma 128-bit BLAKE2b SEMANTIC_V3 identities retained separately from named package SHA-256; naive logical UTC mapping explicit, no native timezone inferred. Testbed implementation now included in content fingerprint. Parent fc61b1c CI 37476481866 four jobs PASS; full local exporter batch 465 passed/16 skipped; actual private harness 47/47 separately, Ruff/Bandit(src+testbed)/compileall/checkpoint/document gates PASS. Exporter batch awaits its own hosted run. Full matrix/native seeder/observers/L2, DAD/evidence storage/ACL/parsers/fault/deployment/stdout bounds remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=AUDIT_METRIC_PRIVACY_20261006 ENGINEERING_IMPLEMENTATION=ae442eba2e20d75cd4dce0ee81aabf3f98f07de82e58e135437db2183e44e6e6 -->

## Bounded metrics/traces and actual audit-alert signal — 2026-10-06

NFR-O1/D12/D11: fixed MCP-tool metric allowlist (plus reserved audit), bounded HTTP status and trace attribute/name allowlists prevent alphanumeric private identifiers becoming series/log data. Audit outcome now recorded only after INSERT; real append failure/cancellation emits existing audit alert selector and original-tool error, never false success. Dependency duration sum/count rejects non-measurements and bounds overflow. 26 focused tests PASS against actual disposable PostgreSQL runtime role; one successful append retained, readonly INSERT failure verified; pinned promtool format/lint/firing/resolution and evidence scanner PASS. Parent bebc223 CI 37475685751 ALL FOUR jobs PASS. Full current local suite 455 passed/13 skipped; real DB focused 26 PASS separately, Ruff/Bandit/compileall/document gates PASS. Audit batch awaits its own hosted run. Alert delivery, full fault/deployment/DAD/Ferma/native evidence storage/ACL/parsers/stdout bound remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=EVIDENCE_PROFILE_BINDING_20261006 ENGINEERING_IMPLEMENTATION=465da0053ae2d5029224389141cc23c1217265e0cb96af329ac031f6c9c1abf8 -->

## Evidence profile binding and result privacy — 2026-10-06

EVID-1/DAD-5/D4: normalized evidence now retains and revalidates its immutable exact parser-profile snapshot; class/scope/version/parser/digest mismatch or missing/untyped profile cannot reuse an approved detached fingerprint. DAD evidence-level output allows only known bounded identifiers, rejects malformed/free-text/non-string levels without echo even on early rule rejection. 76 focused tests PASS including 13 new adversarial class-binding/privacy cases. No native format/authenticity/signature validation inferred. Parent 8e3abb0 CI 37475165164 pending; last fully verified 75c362d run 37474490200 four jobs PASS, actual hosted pool artifact validated. Full local suite 435 passed/12 skipped, Ruff/Bandit/compileall/document gates PASS; hosted binding batch pending. Native evidence storage/ACL/audit, full rule packs/Ferma/observers/fault/deployment/stdout bounds remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=RSV_NATIVE_LIFECYCLE_20261006 ENGINEERING_IMPLEMENTATION=b9f952c03cd8306096d4ca0089bd5e2d585475bdc1429b228f8fdd9336561c70 -->

## Executed native bridge crash and COM reconnect — 2026-10-06

P6-SEC-1/D14: opt-in native metadata lifecycle executed on established disposable 1C 8.3.27.2342 base with production client, official SDK and audited digest-pinned v1.3.0 RSV binary. Confirmed live ping, killed only exact test-owned bridge handle, dead-session sanitized failure, fresh process/COM health recovery and metadata config; three created processes terminated and protected ephemeral configs removed. Executed native test 1/1 PASS, zero skips; artifact scanner PASS. No new COM bridge/protocol, native engine kill, business query, zero-write snapshot, binary/source parity or native accounting approval inferred. Parent 75c362d CI 37474490200 all FOUR jobs PASS; hosted measured pool artifact validated, gateway suite 433 cases/3 skips, tested merge 189f0b2fbcd5355e344d96a90dd8f222e8a09358. Full local 422 passed/12 skipped (native opt-in separately executed PASS), Ruff/Bandit/compileall/document gates PASS. Native batch awaits its own hosted run. DAD/Ferma/native formats/storage/runtime evidence ACL/audit/full fault/deployment and stdout pre-parser bound remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=POSTGRES_POOL_MEASURED_20261006 ENGINEERING_IMPLEMENTATION=ef8034ee21c3775de5e9426f2eea453597097cab28cf4e272247628df7e8478d -->

## Actual PostgreSQL pool acquisition measurements — 2026-10-06

NFR-P2/D13: actual production Database pool and FanoutExecutor measured on NEW disposable PostgreSQL for 30/50/100/150 synthetic sources, three repetitions each. Pool acquisition/read/source/batch p50/p95/p99, peak ten connections, readonly transactions, denied-source zero calls and independent failure outcomes verified. Acquisition includes cold connection growth; Python allocated memory is not process RSS; no 1C/production capacity/native evidence claimed. 18 focused tests PASS with real DB; scanned measured artifact SHA 944e538d7dd844805169c3207c3e05162a0d6e9770b7f5661d2756c05e45704e. Parent d755ebc run 37473881846 ALL FOUR jobs PASS; downloaded release artifact hashes and same tested merge 504b48692b4749910ecb16b8e9892d3657b789c0 verified (two images/five suites), retains NO-GO/PARTIAL. Current full local suite 422 passed, 11 skipped; Ruff/Bandit/compileall/document gates PASS. Pool batch awaits its own CI. Remaining native/DAD/Ferma/deployment/fault gates OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=DAD_SCOPED_COMPARISON_20261006 ENGINEERING_IMPLEMENTATION=b9b2cb0783f03dd7dbad458f08820122658eeac1035712c97d812c4a6e9c6cfb -->

## Scoped DAD comparison foundation and release cache correction — 2026-10-06

DAD-3/DAD-5: internal versioned exact-scope normalized reconciliation rules for Z/terminal/bank comparisons implemented. Approved rule fingerprint, effective period/tolerance, confirmed semantic scope, confirmed external profile, complete observations and separate artifact planes required. Missing/invalid/cross-scope/ambiguous inputs cannot PASS; findings expose key hashes/reason codes only. Evidence level retained, human review always required, no native approval inferred. 33 focused tests PASS including exact large Decimal micro-differences. Runtime ACL/audit/tool integration, native parsers/selectors/observers/full month-close packs remain OPEN. 2affa6f run 37470166429: Windows, gateway and OData PASS; assembly failed strict dirty-worktree check because Trivy cache was in checkout. Cache moved to runner temp and excluded from source/build contexts; guard not relaxed. Full local suite 405 passed, 10 skipped; Ruff/Bandit/compileall/checkpoint gates PASS. Fresh 4-job assembly verification pending. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=JWKS_RECOVERY_20261006 ENGINEERING_IMPLEMENTATION=c0ed6464251446ec3dd71dd8db9cc8b2eb5d9f4d812239187296df13e97de58f -->

## Actual JWKS recovery and independent Windows proof correction — 2026-10-06

NFR-R2 actual HTTP JWKS recovery: after real cache TTL expiry, IdP 503 produces sanitized SDK 401, recovery returns 200; 4 JWKS HTTP tests PASS. Native Windows independent ACL test now uses SID-targeted access rules, explicit Windows PowerShell 5.1 system module path and bounded 45s startup budget, without widening permissions or skipping the check; combined privacy/JWKS focused suite 12/12 PASS. 4e07daf run 37468209819: gateway/OData PASS, Windows protected-DACL contracts PASS, independent PowerShell test timed out, assembly correctly SKIPPED. Current full local suite 372 passed, 10 skipped; Ruff/Bandit/documentation gates PASS. Fresh corrected 4-job evidence verification pending. Native COM/reconciliation, complete container/audit fault matrix, DAD/Ferma/deployment remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=RELEASE_ASSEMBLY_20261006 ENGINEERING_IMPLEMENTATION=bce5fae366d03bdddc1e2d6e6470534ec329b6ed3abf0db38171fe6023121608 -->

## Same-revision release evidence assembly — 2026-10-06

Release assembly (NFR-L1, D1/D18): two image config digests/SBOM/provenance pairs, exact current locks, all five sanitized JUnit suites, risk/DoD/freeze refs and four pinned SHAs are validated and assembled only after three prerequisite jobs PASS. Report URLs bind tested revision; PR head is separate; unpublished image config digest is not a registry manifest digest. Case hashes/outcomes/counts only, no raw names/payloads, no inferred L2/L3 or production GO. 22 assembly/gitlink focused tests PASS; actual pinned upstream JUnit: client 429 cases/1 skip, metadata 53, wrapper 14, all non-skipped cases PASS. 729273e run 37465948528: gateway/OData PASS, Windows FAIL on textual SDDL alias comparison; fixed with binary ACE/SID comparisons, unchanged allowed rights/principals. 29 Windows-local privacy/bridge tests PASS. Current full local suite: 371 passed, 10 skipped; Ruff/Bandit/workflow structure/documentation gates PASS. Fresh 4-job CI/actual assembled artifact verification pending. Native COM/reconciliation, DAD/Ferma/deployment gates remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=RSV_SECRET_PRIVACY_20261006 ENGINEERING_IMPLEMENTATION=b0e7cc82e2dab58e96f23fc2d9e09f623948f36e4854a6536e9c4f542f7babb4 -->

## Protected RSV secret files and scoped diagnostic privacy — 2026-10-06

P6-SEC-1 / D4 privacy: secret-backed configs use a verified protected NTFS DACL (runtime identity/SYSTEM/Administrators), restricted inherited file ACL and exclusive-create; POSIX owner/0700/0600. Failure prevents process launch; cleanup errors are sanitized. Raw bridge stderr is discarded, scoped SDK diagnostics/exception/path/structured-extra fields are sanitized; concurrent non-RSV logs remain unchanged. 29 focused contracts PASS on this Windows host, including independent native file ACL inheritance check. New mandatory windows-rsv-privacy CI job added; cross-platform evidence runner keeps that platform proof separate, no skipped test is treated as PASS. Upstream bridge/COM/protocol code unchanged. Hosted 5d49ec2 / run 37462582061 BOTH parent jobs PASS; current full suite 349 passed, 10 skipped; Ruff/Bandit/documentation gates PASS; new 3-job CI verification pending. Native COM restart, stdout pre-parser memory bound, DAD/Ferma/deployment/release assembly remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=CAPABILITY_REGISTRY_20261006 ENGINEERING_IMPLEMENTATION=2d34eb224df1c235c1a0aaa3e4755c2922c6d06bba407150d9df3542d63cc37e -->

## Persisted capability registry diagnostics — 2026-10-06

FR-C1/C2 registry diagnostics: all five CLI commands implemented against bounded repeatable read-only DB snapshots; aggregate output, exact source/profile/fingerprint freshness and drift checks, exact-register diff, safe private export outside Git/no overwrite. Diagnostic SUPPORTED does not grant runtime authorization; no OData/COM/probe calls. 22 focused tests PASS plus 1 executed test on a NEW PostgreSQL instance (5 snapshots readonly=on), including DrCr negative/positive, stale/drift and oversized profiles. Prior first drill failed because its synthetic seed used the unconfirmed default drift state; corrected fixture then actual DB PASS. Hosted e7898f2 / run 37461088241 BOTH jobs PASS. Current full local suite 341 passed, 10 skipped; separate actual PostgreSQL contract 1/1 PASS. Ruff/Bandit/documentation gates PASS; hosted CLI batch awaits its own run. DAD/native evidence/Ferma/deployment gates remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=EVIDENCE_BOUNDARY_20261006 ENGINEERING_IMPLEMENTATION=04b30b612b0301694c62f03ab36b10f3a5b4aaf57339f11f87ce3e2be6055cc6 -->

## Normalized external evidence boundary — 2026-10-06

EVID-1 / DAD evidence boundary: exact-scope confirmed-profile normalized CSV parser and missing-evidence gate implemented, 30 focused tests PASS. Manifest exposes hashes/counts only; no arbitrary URL, blob writes or native-format/accounting PASS. Retention/ACL/storage/native parsers and DAD rule execution remain OPEN. Checkpoint portability fix excludes generated editable-install metadata; 11 checkpoint tests PASS. Last verified hosted code c59f070: run 37459728181 BOTH jobs PASS. Run 37460339973 at 871ea20 failed the new fingerprint gate on generated metadata; fix awaits hosted verification. Current full local suite: 319 passed, 9 skipped; Ruff/Bandit and both documentation gates PASS. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

<!-- ENGINEERING_CHECKPOINT=DOC_CHECKPOINT_20261006 ENGINEERING_IMPLEMENTATION=8cacf624874a4cb7eae41a0a9df8874557a842a1e422eb269855df2d4e055d55 -->

## Content-bound documentation checkpoint — 2026-10-06

Documentation gate (SCOPE-1, D0/D18): current snapshot is bound to implementation content, not old PASS strings. Source drift, a stale report marker, refreshed JSON without refreshed reports and unequal HTML copies fail CI. Ten focused tests and full local suite 288 passed, 9 skipped. Parent implementation c59f07096a1b08c27c33554c29638d4922fe8621 passed BOTH hosted jobs in run 37459728181; the new checkpoint gate awaits its own hosted run. Native accounting/Ferma/DAD/deployment gates remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL; PR #11 Draft.

## Executed RSV lifecycle and transport matrix — 2026-10-06

RSV/transport security batch (P6-SEC-1, D4/D11/D13): production RSV client now bounds secret resolution; official SDK stdio fixture verifies crash, timeout, malformed response, new-process recovery, between-call config rotation and temporary-config cleanup. No native 1C/COM calls occur in this harness. Replaced the parallel SSRF classifier with production path/DNS/connect/redirect tests; encoded traversal, controls and 3xx-as-data are denied. Local full suite: 278 passed, 9 skipped; Ruff/Bandit PASS. Node 24 wrapper contracts: 14/14, pinned metadata upstream: 53/53. Hosted run 37458293638 at e767b1d failed on build-environment dispatcher/import wiring; corrected locally, next hosted run must verify the correction. Native COM recovery, Windows secret DACL, deployment firewall and durable recovery audit remain OPEN. Production GO remains NO-GO; DoD remains PARTIAL.

## Connect-time egress verification — 2026-10-06

Connect-time egress batch (D4/D11): Python HTTPcore and pinned sidecar dispatcher validate DNS at socket creation, dial an approved numeric IP and retain TLS SNI. Redirects and ambient proxies cannot bypass the policy. Local Python suite: 245 passed, 9 skipped; baked sidecar: 14/14; exact runtime npm audit: 0 advisories. Dispatcher MIT undici 8.10.2 has its own lock/provenance; upstream engine SHA is unchanged. P5 foundation commit 0e3e038bfcf84d14446eb8d3592066db05060ddb passed both CI jobs in run 37457016876. Deployment firewall proof and real RSV lifecycle remain open; Production GO is NO-GO.

## Current evidence integrity assessment — 2026-10-06

R-34/R-35: test-only scenario intake exposes immutable seed facts without expected values;
production package excludes testbed; target guard refuses production IDs, scope/fingerprint drift
and shared write/read identity; comparator rejects same-origin/missing/truncated/cross-scope data.
22 contract tests pass. Actual native seeder/observers and Ferma exporter independence remain open.

Verified implementation `dbeafc8d2afb72de07b794bed926f6ed8cecdb06`, CI `37455962411` PASS.
R-25 remains OPEN: prior benchmark and harness closure claims included formula-generated numbers
and constant PASS values. They are withdrawn. R-05 is advanced by JSON/header scanner regression
coverage; R-12 by health timeout and pre-secret executable verification; R-13/R-28 by measured
production executor latency/memory/concurrency and four executed guard mutations. Actual Docker
PostgreSQL/Redis outages returned sanitized 503 then 200 after restart. No production risk
acceptance or complete mitigation is inferred. D12 checks now run pinned promtool: rule lint,
pending/firing/resolution and gateway text format pass locally. Alert delivery remains open.

## Scope freeze checkpoint — 2026-10-06

Operator scope freeze is active. Code checkpoint at freeze: PR #11 Draft/mergeable,
HEAD `65883a5a83fbb369cbd32e5e31af3041f9d7c515`; CI `37446049853` SUCCESS; exact scope baseline commit `57eb5b0696063237a43f5d1baf0a646278f5d832`; Production GO NO-GO. Later scope-preserving commits may advance PR HEAD without changing frozen scope.

New frozen-scope risk rows are R-31–R-35:
- scope creep;
- malicious/mis-scoped external evidence;
- private reference artifact leakage;
- Ferma oracle/actual correlation false-green;
- test-only write boundary leakage.

No risk acceptance is inferred. Deferred write/legacy/production ERP-Ferma lanes remain deferred.

## Current authoritative checkpoint — 2026-10-06

Last hosted candidate baseline: `b6df856ef518a5a972f2a8141fb87cbdc0432ea8`, PR #11 Draft, CI `37425137186` PASS. Current local uncommitted work is not represented in that CI. Focused security tests (15) pass, including no raw audit query persistence and sanitized upstream errors.

Still OPEN: R-04 SSRF/DNS rebinding/effective egress restriction (critical); R-05 end-to-end secret/log/trace leak and production rotation; R-09 clean dependency/image vulnerability results and provenance (pending scan); R-13 full controlled load proof; R-17/R-18 dependency failure matrix; accounting reconciliation risks R-01/R-23. Synthetic tests are not production evidence. Production GO remains NO-GO and no risk acceptance is inferred.

Assessed: 2026-10-06. Source register: `docs/RISK_REGISTER.md`.

## Current integrated assessment

Candidate code `4683586` plus current drill follow-up: 138 Python/PostgreSQL tests PASS, 1 real-1C skip; migrations/privileges
and security/dependency checks pass. R-06 company isolation and R-08 audit outcomes now have
multi-source/lifecycle and success/deny/error append-only evidence from #9/#10 in this candidate.
R-02 includes metadata/capability TTL and source endpoint/credential-reference invalidation.
R-17 Redis fail-closed test is implemented; broader dependency failure injection remains open.
R-09 pinned upstream tests/image build pass; universal locks/SBOM/audit remain local work.
R-12: official v1.3.0 CFE artifact exists and hash is verified; compiled source/rights/company
audit and real COM smoke remain unverified. Release tag differs from approved source pin.
R-01/R-23 native accounting reconciliation, R-04 deployment egress, production R-05/R-26 secret
rotation, R-13/R-28 capacity, R-18 production PITR and R-22 fan-out remain open. File-secret
rotation behavior is now covered by a synthetic unit test; ACL list authorization correctness was
load-exercised at 30/50/100/150 sources, but noisy local latency is not a capacity claim. No risk
acceptance is inferred.
All independent software/drill work will precede any external-only stopping decision.

R-18 application-level backup/restore is now partially mitigated: disposable PostgreSQL 16 drill
passed on `4683586` with exact per-table row fingerprints after fresh-instance restore, runtime
readiness, privilege checker and seven registry integration tests. Production PITR/retention and
deployment rollback remain open.

## Historical controls (superseded where updated above)

| Risk | Status | Current control/evidence | Remaining action |
|---|---|---|---|
| R-01 / R-23 accounting meaning and universal presets | OPEN — critical | Reconciliation/profile gates documented | Implement semantic profiles and reconcile real 1C cases before approval |
| R-02 configuration/schema drift invalidates mappings | PARTIALLY MITIGATED | Sticky metadata fingerprint drift state, expected-fingerprint admin acknowledgement and `onec_read` fail-closed gate passed CI 37358947196; validated semantic profiles auto-stale on fingerprint change and operator lifecycle events are append-only | Reconcile affected native-report cases before revalidation; record operator identity for metadata-drift acknowledgement |
| R-03 write path exposure | MITIGATED IN CORE / OPEN FOR FUTURE ADAPTERS | Python transport only GET/HEAD; pinned sidecar routes only upstream query/key/count/register read methods and rejects mutation-shaped operations/method names in tests | Continue adapter inventory/static checks; zero-write proof against actual 1C |
| R-04 SSRF | OPEN — critical | Registry IDs, URL/path validation, redirects off | DNS/egress and real deployment checks |
| R-05 secret leakage | OPEN — critical | Secret references/providers; production env provider rejected | End-to-end leak and rotation evidence |
| R-06 company authorization leak | PARTIALLY MITIGATED | Company FK and scoped allow/deny grants; company-only grants blocked from unscoped reads; deny precedence, inaccessible enumeration and immediate revocation passed PostgreSQL CI run 37355876333 | Enforce company filter in business-data adapter; add cross-source isolation |
| R-07 runtime DB policy escalation | PARTIALLY MITIGATED | CI created roles, verified table privileges, and passed registry/audit DML checks using `SET LOCAL ROLE business_ai_app` (run 37356701516); admin-role positive/negative DML passed PostgreSQL CI run 37357432914 | production provisioning runbook |
| R-19 IdP/JWKS outage blocks valid users | PARTIALLY MITIGATED | JWT verifier fails closed on JWKS error; negative test added | Add bounded network timeout/cache behavior and live IdP failure test |
| R-08 audit tampering | PARTIALLY MITIGATED | Append-only trigger, table grants and CI privilege checker; `Audit.write` inserted an error event as runtime role and UPDATE/DELETE were denied in PostgreSQL CI run 37357024926 | Exercise remaining audit paths and ensure all request outcomes persist complete provenance |
| R-09 unstable upstream API | PARTIALLY MITIGATED | Runtime sidecar builds exact MIT upstream SHA; client suite and wrapper contract pass locally; response checks exact SHA | Hosted CI, metadata/register parity and monitor/upstream upgrade procedure |
| R-10 license contamination | MITIGATED BY POLICY | Copyleft isolation docs and vendor tests | Preserve policy on future adapter intake |
| R-13 slow 1C query overload | PARTIALLY MITIGATED | Sidecar timeout, pre-parser response cap, output bytes/rows, per-source concurrency and circuit breaker | Load/capacity test and telemetry |
| R-17 Redis failure removes rate protection | OPEN — high | Readiness pings Redis at startup | Explicit outage behavior and fault-injection tests |
| R-18 DB failure prevents safe auth/audit | PARTIALLY MITIGATED | Readiness and request dependencies fail closed by design | DB outage integration/failure-injection proof |
| R-22 partial fan-out corruption | NOT STARTED | No cross-company aggregate exposed | Preserve partial failures when semantic fan-out is introduced |
| R-25 unsupported production claim | MITIGATED IN STATUS REPORTING | This work uses DEV READY and explicit gate matrix | Keep exact evidence and readiness label updated |

Critical/high risks remain open; production readiness is not claimed.
