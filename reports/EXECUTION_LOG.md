# Autonomous engineering execution log

<!-- ENGINEERING_CHECKPOINT=CAPABILITY_BOUNDARY_20261006 ENGINEERING_IMPLEMENTATION=acf338777033cbfd07b7b354254606711e57a78e167e279b5a05ef97cc7f4ca3 -->

## Capability observation boundary — 2026-10-06

Added migration 014 and routed registry capability persistence through the constrained observation function. Metadata failure now yields `metadata_fingerprint=None` and `NEEDS_VALIDATION`; existing evidence is not replaced by an exception-derived hash. Focused tests: 20 passed; combined suite: 1123 passed/39 skipped. Direct migration identity validation passes. Local PostgreSQL acceptance is pending because Docker/testbed is unavailable.

## Fault-injection runner — 2026-10-06

Implemented Compose config validation and a bounded five-dependency outage plan. The runner records the existing local readiness/JWKS regression coverage separately from cases not executed in the current environment; no outage PASS is synthesized. Focused tests: 8 passed; full suite: 769 passed/18 skipped; Ruff passed. Hosted CI `37508235079`: four jobs passed; tested merge `30a3c4a93137729b7a6de0ad5e26890e6a4c7a76`. Production NO-GO; DoD PARTIAL.

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

## Step 21 — source-specific register capability rule

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-05

- Added migration 005 to persist register capability evidence per source.
- The Python adapter and OData sidecar require confirmation for the exact source, register entity
  set, and method. The sidecar rechecks its short-lived live-metadata profile before each operation.
- Configuration-sensitive operations, including `DrCrTurnovers`, return
  `CAPABILITY_UNSUPPORTED` when evidence is absent or stale. No alternate names are guessed and no
  speculative OData data request is issued. Positive and negative evidence is returned in the
  source capability profile.
- Added the internal ERP_MCP ↔ pinned OData sidecar contract, capability endpoint/response tests,
  migration/persistence coverage, and confirmed-positive/unsupported-negative DrCr fixtures.
- Reuse remains pinned to `hacker-cb/1c-odata` SHA
  `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`; upstream source is unchanged. No new OData protocol
  implementation, COM bridge, or GPL-derived core code was added.
- Verification: Python `67 passed, 5 skipped`; sidecar `11/11`; pinned upstream client
  `428 passed, 1 skipped`; metadata `53 passed`; PostgreSQL integration `4 passed`; Ruff,
  compileall, Bandit, and `git diff --check` pass. The rebuilt image returned `/healthz` 200 as UID
  10001 with no published ports.
- Next: publish this batch and wait for hosted CI; then continue with semantic profile/preset
  lifecycle and deterministic tests. Real-source semantic validation still requires a real 1C base.

## Step 22 — semantic profile/preset foundation

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-06

- Rechecked the pinned Aprovodka SHA `7b62c90e1fe74324605dc28d76f195200bb97252`: preset types,
  BP 3.0/UT 11/ZUP 3.1/ERP 2 data, accounting/register read-side tools, and `tests/presets.test.ts`.
  Its `verified` label refers to upstream documentation, not a concrete customer source; ERP_MCP
  therefore imports only the four preset identities as `CANDIDATE_ONLY` references.
- Added migration 006 for source/company-scoped, versioned semantic profiles and canonical mappings,
  preserving upstream repository/SHA and metadata/capability/profile fingerprints. Runtime role is
  read-only; admin role can maintain profiles/mappings but cannot delete them.
- A profile can be used only when explicitly `VALIDATED`, exact source/company and metadata match,
  metadata drift is acknowledged, and ten passing native-report reconciliation cases are present.
  Capability dependencies still require current positive source evidence and deny with
  `CAPABILITY_UNSUPPORTED` otherwise.
- Metadata-fingerprint changes automatically stale previously validated profiles via a narrow
  `SECURITY DEFINER` trigger on source capability updates; no broad runtime UPDATE privilege is
  granted.
- Verification: full Python suite `73 passed, 6 skipped`; Ruff, compileall, Bandit pass; disposable
  PostgreSQL applied migrations 001–006, privilege checker passed, PostgreSQL integration `5/5`.
  The prior capability batch CI Python job passed on `e964e32`; pinned OData job remains queued.
- Still not implemented: validated accounting mappings/tools, administrator workflows/audit, and
  actual native 1C reconciliation. No preset is promoted from candidate based solely on its name.

## Step 23 — operator profile lifecycle and audit

**Status:** implemented and verified locally; hosted CI pass.
**Date:** 2026-10-06

- Added operator-only CLI commands to create a source/company-scoped draft, add candidate mappings,
  validate, and retire profile versions. Creation requires supported live metadata and acknowledged
  stable drift state; validation compares the stored live source capability/metadata fingerprints
  and checks every mapping's exact register dependency before promotion.
- Validation normalizes evidence to ten or more distinct passing case IDs and controlled native
  report references; raw reports are not copied into PostgreSQL. Database checks enforce case count,
  uniqueness, PASS state and non-empty report references.
- Migration 007 adds an append-only profile lifecycle event table. Runtime role can only read it;
  admin can append but cannot update/delete event history. Profile administration itself is restricted
  to the admin connection.
- Added [operator workflow documentation](../docs/SEMANTIC_PROFILES.md), lifecycle and privilege
  integration coverage. Verification: Python `74 passed, 7 skipped`; disposable PostgreSQL applied
  migrations 001–007, privilege checker passed, PostgreSQL integration `6 passed`; Ruff, compileall,
  Bandit, pip-audit (`no known vulnerabilities`) and diff checks pass.
- Preset mappings remain candidate-only until a real source has been inspected and native reports
  reconciled. Canonical MCP accounting tools are still not exposed.
- Hosted CI run `37375030150` on `5f7061d` passed both the gateway/database test job and pinned
  `odata-upstream` job. A duplicate same-SHA run remains queued and is not used as acceptance
  evidence.

## Step 24 — pinned semantic preset candidate data

**Status:** implemented and verified locally and in hosted CI.
**Date:** 2026-10-06

- Re-read the exact pinned Aprovodka preset files/types/tests at SHA
  `7b62c90e1fe74324605dc28d76f195200bb97252`; imported a selected, explicitly documented subset
  of entity-set hints for BP 3.0, UT 11, ZUP 3.1 and ERP 2. The source's `verified`/`common` labels
  are retained only as upstream confidence metadata, not as evidence about an installed base.
- Semantic profile creation persists candidate entity names, kinds, upstream confidence, exact
  repository/SHA/path provenance, and `CANDIDATE_ONLY` status. Candidate names are never sent to
  OData or used to promote a profile. The per-source capability check remains the only operation
  gate; unconfirmed register calls return `CAPABILITY_UNSUPPORTED`.
- Updated third-party attribution with the Aprovodka MIT notice. Added catalog invariants and a
  PostgreSQL lifecycle assertion that candidate records remain candidate-only.
- Verification: Python `74 passed, 7 skipped`; migrations 001–007 and DB privilege policy pass;
  PostgreSQL integration `6 passed`; Ruff, compileall, Bandit, pip-audit (no known vulnerabilities)
  and `git diff --check` pass. The pinned upstream source remains unchanged.
- Hosted CI run `37375751454` on `de03524` passed both gateway/database tests and the pinned upstream
  OData build, contract tests, and non-root image smoke.
- Next software work: executable company-filtered business reads, canonical accounting tools,
  completed audit/operations proof and remaining deployment/security gates. Promoting a candidate
  or validating accounting semantics still requires a real target 1C source and native reports.

## Step 25 — company-scoped account-turnover semantic vertical slice

**Status:** implemented and verified locally; phase PR / hosted CI pending.
**Date:** 2026-10-06

- Reused the pinned Aprovodka accounting contract at `7b62c90e1fe74324605dc28d76f195200bb97252`
  (`tools/accounting.ts`): BalanceAndTurnovers is period-bounded; company/account selection is an
  explicit condition. OData request construction and register execution remain in the pinned
  `hacker-cb/1c-odata` sidecar (`cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`).
- Added `accounting_balance_and_turnovers`: it authorizes the exact source/company before metadata
  or data access, accepts no caller-selected EntitySet/filter/register args, and requires a
  validated exact-company profile plus explicitly `CONFIRMED`/`HIGH` mapping, current fingerprints
  and live `balanceAndTurnovers` capability. Company conditions are built only from operator-mapped
  field/type and the registry external reference. Seven source fields map to canonical output keys;
  missing fields fail closed and numeric/currency values are not silently converted.
- Migration 008 adds explicit mapping confirmation and invalidates/audits direct post-validation
  mapping changes. Migration 009 adds semantic profile fingerprint to audit events. Operator CLI
  records controlled evidence references and append-only lifecycle events.
- Added source/company deny-before-1C, unconfirmed-mapping no-dispatch, profile scope/drift,
  condition escaping, output normalization, audit provenance and PostgreSQL trigger tests.
- Verification: full Python suite `80 passed, 7 skipped`; disposable PostgreSQL migrations 001–009,
  privilege checker PASS and integration `6 passed`; Ruff, compileall, Bandit pass. A real 1C base
  and native reports remain necessary to promote any customer mapping; remaining canonical P4 tools
  are not yet implemented.

## Step 26 — company-scoped sales and purchase document reads

**Status:** implemented; local and hosted CI PASS.
**Date:** 2026-10-06

- Extended the evidence-backed semantic mapping lifecycle to sales and purchases. Each mapping
  requires a confirmed `Document_*` EntitySet, company equality field/type, canonical field mapping,
  and a date order field; caller input cannot select an EntitySet, filter, or projection.
- Added `sales_documents` and `purchase_documents`. Both authorize the exact source/company before
  metadata or business data, require a current validated source/company profile, derive the company
  predicate only from the mapping and registered external reference, bound page size, normalize
  seven canonical document fields, and record profile/metadata fingerprints in audit.
- Protocol and transport continue through the existing pinned OData adapter/sidecar; no new OData
  protocol implementation was introduced. Other P4 domains (cash/bank, inventory, AR/AP aging,
  tax/VAT and posting trace) and real native-report reconciliation remain open.
- Verification: Python `83 passed, 7 skipped`; disposable PostgreSQL 16 migrations 001–009, DB
  privilege policy and PostgreSQL integration `6 passed`; Ruff, compileall, Bandit, pip-audit and
  diff check PASS. Hosted CI run `37380789434` passed both `test` and `odata-upstream` jobs on
  commit `b212790`.

## Step 27 — source-capability-gated inventory balance snapshot

**Status:** implemented; local and hosted CI PASS.
**Date:** 2026-10-06

- Reused pinned Aprovodka `getAccumulationBalance` semantics and its `Balance(Period, Condition)`
  shape, plus UT11/ERP2 candidate descriptions for `AccumulationRegister_ТоварыНаСкладах`; the
  preset entity name remains advisory and is never selected automatically. Reused pinned OData
  `RegisterHelper.balance` and the existing sidecar's live metadata capability gate.
- Added `inventory.balance` profile mapping with exact accumulation-register entity, `Balance`
  dependency, required company dimension, and reviewed item/warehouse/quantity projection.
  `inventory_balance` requires an explicit timezone-qualified point-in-time period and exact
  source/company authorization. It does not infer quantity by summing documents or switch methods.
- Positive semantic/capability/normalization/runtime fixtures and negative tests prove unconfirmed,
  cross-source, stale, or unavailable capability evidence cannot dispatch a register request.
  PostgreSQL lifecycle coverage includes inventory and purchase mapping confirmation/profile load.
- Local full suite at implementation: Python `90 passed, 7 skipped`; Ruff, compileall, Bandit,
  pip-audit and diff check PASS. Disposable PostgreSQL 16 migrations 001–009 and DB privilege
  policy PASS; integration `6 passed`. Hosted CI run `37381909454` passed both jobs on `90cd70c`.

## Step 28 — source-capability-gated bank balance snapshot

**Status:** implemented; local and hosted CI PASS.
**Date:** 2026-10-06

- Reused Aprovodka's pinned `getAccumulationBalance` implementation/tests and UT11's
  `AccumulationRegister_ДенежныеСредстваБезналичные` preset description. The upstream preset marks
  this candidate `common`; it is not treated as source evidence. Reused pinned OData `Balance` and
  the sidecar's exact live metadata recheck.
- Added `bank.balance` with a source/company-scoped `Balance` mapping for bank-account reference,
  currency and amount, plus the `bank_balance` tool. EntitySet and all projection/filter fields must
  be operator-confirmed; monetary values are preserved without conversion.
- Tests cover typed company filtering, explicit timezone period, canonical output, exact live
  capability evidence, and PostgreSQL profile lifecycle. No caller-supplied register/filter and no
  OData protocol code were added.
- Local full suite: Python `93 passed, 7 skipped`; disposable PostgreSQL 16 migrations 001–009,
  privilege policy and integration `6 passed`; Ruff, compileall, Bandit, pip-audit and diff check
  PASS. Hosted CI run `37382615109` passed both jobs on `c6605b8`.

## Step 29 — company-scoped receivable/payable balance snapshots

**Status:** implemented locally; verification and publication in progress.
**Date:** 2026-10-06

- Reused Aprovodka's pinned UT11 candidate inventory for customer/supplier settlement accumulation
  registers and its existing point-in-time accumulation `Balance(Period, Condition)` implementation
  and tests. The candidate names are explicitly tagged `common` and never selected automatically.
- Added distinct `receivable.balance` / `payable.balance` mapping contracts and MCP tools. Each
  requires exact source/company authorization, a validated profile and exact live source
  `AccumulationRegister_*/Balance` capability; canonical projection is counterparty, contract and
  amount. Caller input cannot choose a register or filter.
- These tools deliberately return balances only: they do not calculate aging, overdue days, net
  positions, or infer due dates. Such semantics need a separate reviewed profile and native report
  reconciliation.
- Local full suite: Python `101 passed, 7 skipped`; disposable PostgreSQL 16 migrations 001–009,
  privilege policy and integration `6 passed`; Ruff, compileall, Bandit pass. Hosted CI and final
  pip-audit/diff-check for this batch follow publication.

## Step 30 — P5 deterministic L1 seed and accounting scenario contract

**Status:** implemented locally; publication/hosted CI pending.
**Date:** 2026-10-06

- Fake1C now loads the versioned `erp-mcp-synthetic-v1` JSON seed as its single source of truth and
  exposes sales/purchase plus inventory, bank, receivable and payable fixture EntitySets in metadata
  and GET responses. All fixture routes remain read-only.
- Upgraded the ten accounting scenarios to schema v2 with stable fixture IDs, executable expected
  invariants, and explicit `NOT_RUN` native 1C reconciliation status. The validator computes a
  canonical seed SHA-256 and rejects broken invariants or synthetic evidence falsely marked as
  native. Added a real-L2 snapshot manifest template whose required values are clearly unfilled.
- CI now runs `scripts/validate_scenarios.py`. Verification: Python `104 passed, 7 skipped`; Ruff,
  compileall, Bandit, pip-audit and scenario validator pass. Hosted CI run `37383877277` passed both
  jobs. These L1 artifacts are not L2/L3
  environment evidence and do not unblock native report validation.

## Step 31 — P6 isolated RSV bridge process and health boundary

**Status:** implementation in progress; data route intentionally fail-closed.
**Date:** 2026-10-06

- Re-read the pinned MIT `mcp-rsv-data` bridge contract (`serve.go`, `onec.go`, `config.go`) and
  product guide. Reuse is via the existing MCP stdio process; no COM/native-query/stdio protocol
  implementation was added to ERP_MCP.
- Added an MCP SDK process client with strict source-ID-to-config mapping, minimal child environment,
  exact upstream tool inventory check, ping-only health, restart-per-check recovery and sanitized
  errors. Added runtime wiring, paired absolute-path settings, negative tool-inventory/path tests,
  and a Windows installation/ACL/recovery runbook.
- Generic `query`/`execute_query` are not forwarded. Bridge health is not source capability evidence;
  until per-source/company query mapping can enforce company scope, business reads remain
  `CAPABILITY_UNSUPPORTED`.
- Initial targeted tests: 9 passed; Ruff reported import/style findings, corrected before final
  verification. Full suite, hosted CI and Windows/COM smoke remain pending.

## Step 32 — P7 legacy demand gate

**Status:** deferred for modern MVP; no 8.2 target evidence exists.
**Date:** 2026-10-06

- Kept the GPL-3.0 1c-mcp-toolkit on the isolated-service-only path. No source or dependency from it
  is added to ERP_MCP core.
- Formalized the demand gate: reopen only for a named 1C 8.2.13+ target and accountable owner, then
  do license/isolation/read-only review before deployment. This avoids shipping an unused legacy
  route or claiming platform compatibility without a test target.

## Step 33 — P8 protected aggregate HTTP metrics

**Status:** implementation in progress.
**Date:** 2026-10-06

- Added dependency-free HTTP request count, in-flight and latency histogram metrics. Labels have
  fixed route/method/status cardinality and never contain source/company/subject, URL IDs, or query
  data. `/metrics` is not found unless a 32-byte bearer token is explicitly configured.
- Added endpoint authorization, settings and middleware tests; documented per-process/reset behavior
  and secret-store handling. This is a narrow observability slice; it does not close D12 or replace
  audit, source-health, database, or distributed telemetry.
- Full local verification: Python `112 passed, 7 skipped`; Ruff, Bandit, compileall, pip-audit,
  scenario validator and diff-check pass. Hosted CI run `37384949997` passed both jobs.

## Step 34 — P9 fail-closed pilot evidence gate

**Status:** implementation in progress; production GO remains blocked by absent external evidence.
**Date:** 2026-10-06

- Added a privacy-safe manifest template bound to an exact 40-character release SHA and positive
  pilot scope counts. Fixed gate names cover CI/config/auth/secrets/isolation/capabilities, ten
  native reconciliations, zero-write/audit, load/resilience, backup/restore/rollback, operations,
  privacy, user acceptance, and release approval.
- Added strict schema/evidence metadata validation and a `--require-go` mode. Unknown/freeform
  fields are rejected to discourage PII/secret collection. CI validates the template and asserts
  that an empty template cannot pass GO. Evidence artifacts remain in an approved external store;
  a human reviewer must verify their contents and hashes.
- No real pilot/native report/IdP/restore evidence is available, so current disposition is
  explicitly `NOT_READY` rather than inferred or synthesized.
- Verification: Python `116 passed, 7 skipped`; Ruff, Bandit, compileall, pip-audit, scenario
  validator and diff-check pass. The template validates; `--require-go` fails as intended. Positive
  and negative evidence fixtures pass. P9 test job passed in run `37385325901`; upstream image
  job is pending completion.

## Step 35 — source-profile-gated inventory register movements

**Status:** implementation in progress; native reconciliation is still required.
**Date:** 2026-10-06

- Rechecked pinned Aprovodka `registers.ts`, `accounting.ts`, UT11 preset, `common.ts`,
  `presets.test.ts` and `tools.test.ts` at `7b62c90e1fe74324605dc28d76f195200bb97252`. Reused its
  record-set `get_register` shape and candidate `ТоварыНаСкладах`/`RecordType` receipt-expense hint;
  upstream tests verify preset inventory but do not directly exercise this read handler. The hint
  remains `CANDIDATE_ONLY`; no register name or field is auto-selected.
- Added `inventory_movements` under the existing pinned OData GET path. A confirmed profile must
  define exact company dimension, fields, source IANA timezone, receipt/expense literal sets,
  positive-magnitude encoding and order field. Runtime converts offset-qualified boundaries into
  the confirmed source timezone, checks exact live metadata presence, builds only company/time
  predicates, and fails closed for absent EntitySet, unknown record type, invalid quantity or stale
  profile. Receipts are positive and expenses negative in canonical `quantity_delta`.
- Added profile CLI/registry validation, Windows-compatible `tzdata` dependency, positive/negative
  semantic, tool/audit and PostgreSQL lifecycle fixtures. No new OData protocol implementation or
  guessed alternative-name probing was added. Full suite: `119 passed, 7 skipped`; Ruff, Bandit,
  compileall, pip-audit, scenario/P9 validators and diff-check pass. P8 CI run `37384949997` and P9
  run `37385454985` passed both jobs. P4 movement follow-up CI and native report reconciliation
  remain pending.
- Extended L1 Fake1C metadata/GET with deterministic movement rows and added an eleventh scenario
  for receipt/expense sign reconciliation. Latest synthetic seed fingerprint:
  `sha256:e3dada8693b85ce7fd4571a9823873b84caaef536938b961c5e2b2885f0450d8`; it remains synthetic,
  not source capability or native-report evidence.
- Added a profile-gated `accounting.posting_rows` read slice after reviewing pinned
  `evilbruce666/1c-odata-mcp` at `dc6b6a1358c7e65e3cfb45c22e8157d1479ab71e`. Upstream postings code
  itself labels entity/field/filter assumptions LIVE-UNVERIFIED and its unit fixtures do not prove
  native compatibility. ERP_MCP therefore accepts no inferred register name: the exact configured
  EntitySet and every selected/company property must exist in current live metadata; missing fields
  are audited as `CAPABILITY_UNSUPPORTED` before dispatch. The tool returns only the six reviewed
  mapped fields and explicitly is not a full trace/report. Local full suite: 121 passed, 7 skipped;
  Ruff, Bandit, compileall, pip-audit, scenario validation and diff-check pass. Native reconciliation
  remains NOT RUN and P9 decision remains NOT_READY.
- Hosted CI for P4 follow-up PR #8 head `63d97d3` passed both `test` and `odata-upstream` jobs in
  run `37387649827`. PR #8 remains open and Draft; no merge/approval was performed.
- Added the profile-gated `cash.movements` slice. Pinned Aprovodka generic register GET/paging is
  reused through the existing ERP_MCP adapter; its pinned UT11/ERP2 presets and tests contain no
  universal cash-register candidate/semantics. Exact source/company mapping, receipt/expense values,
  timezone and live EntitySet/property checks are mandatory; no currency conversion is performed.
  Fake1C now includes cash receipt/expense rows and a twelfth deterministic scenario, with native
  reconciliation still `NOT_RUN`. Seed fingerprint: `sha256:8322c0db8742603c71ac5a7cfe1fda845ba627ddf08d1a14f136c3623f33469b`.
  Local full suite: 123 passed, 7 skipped; Ruff, compileall, Bandit and pip-audit pass. Pilot evidence
  remains `NOT_READY`; `--require-go` correctly exits nonzero on the empty evidence template. This
  cash slice is local-only pending PR update and hosted CI.
- Closed the capability-evidence persistence gap: semantic EntitySet/property denials are now kept
  in `source_capabilities.evidence_json.semantic_capabilities`, keyed to source/concept/exact set and
  expected property mapping, tagged with metadata fingerprint and timestamp. Capability refresh
  preserves the nested evidence; older-fingerprint entries are historical and cannot authorize
  calls. Runtime denial still audits `CAPABILITY_UNSUPPORTED`; no business rows are stored. Added a
  PostgreSQL runtime-role integration check for persistence across refresh. The integration test is
  skipped locally without its disposable PG URL; hosted PR CI must exercise it.
- First hosted run on `f85b716` (`37415093193`) passed `odata-upstream`, but PostgreSQL CI exposed an
  asyncpg parameter-type error in `jsonb_build_object` for the evidence key. Added an explicit
  `::text` cast; local suite remains 123 passed / 7 PostgreSQL-only skips and Ruff passes. Awaiting
  hosted rerun to verify the SQL correction and role permissions.
- Corrected head `02eab2d` passed hosted run `37415224776`: PostgreSQL migrations, privilege checker,
  all pytest tests (including runtime-role capability evidence persistence/refresh), pip-audit,
  exact pinned upstream client/metadata tests, and non-root sidecar build/smoke all passed.
- D7 cache-refresh follow-up: gateway cached `$metadata` and capabilities indefinitely, so persisted
  metadata drift could remain invisible until restart. Added configurable `BAG_METADATA_CACHE_TTL_SECONDS`
  (60-second default, one-hour maximum), shared expiry for detector/capability results, invalidation
  when the registered base URL or credential references change, and forced capability refresh after
  directly refetching metadata. Synthetic detector test changes metadata fingerprint after expiry
  and confirms the new EntitySet is observed; targeted and full local tests pass (125 passed,
  7 PostgreSQL-only skips), as do Ruff, Bandit, compileall, scenario validation and pip-audit.
  Hosted run `37415523392` passed both jobs on `f4340b3`: Python/PostgreSQL `125 passed, 1 skipped`,
  pinned upstream client `428 passed, 1 skipped`, metadata `53 passed`, and non-root sidecar image
  smoke passed.
- D10 multi-source integration follow-up on `phase/p1-multisource-contract`: added a PostgreSQL
  contract test for three differently configured OData sources with separate subject/group company
  grants, plus a fourth source onboarded during the same live Registry instance and immediate access
  denial after revocation. This exercises registry/ACL control-plane behavior only; no 1C endpoint
  is contacted and no fan-out/performance claim is made. Local suite on the main-based branch:
  `74 passed, 8 skipped` (PostgreSQL integration requires CI DB); Ruff/compileall/diff-check pass.
  Draft PR #9 created at https://github.com/xLZDx/ERP_MCP/pull/9.
- First PR #9 hosted run `37415768895` showed the standalone `main` base predates the later
  `require_source_for_company` helper. The test now asserts only APIs present on `main`:
  `require_company` permits the granted company while `require_source` still denies a company-only
  grant. Local regression suite remains `74 passed, 8 skipped`. Corrected PR head `6356005` passed
  hosted CI run `37415897249`: `81 passed, 1 skipped`, pip-audit clean, and pinned upstream
  client/metadata tests plus non-root sidecar image smoke passed.

- D11 audit outcome follow-up on `phase/p1-audit-outcomes`: extended the runtime-role PostgreSQL
  round-trip to exercise success, denial and error events, assert company/provenance/result fields,
  and attempt append-only UPDATE/DELETE against each event. Local suite: `74 passed, 7 skipped`
  (the PostgreSQL integration test requires CI DB); Ruff, compileall and diff check pass. Draft PR
  #10 is at https://github.com/xLZDx/ERP_MCP/pull/10. Hosted CI run `37416120977` passed on
  `c14376d`: pytest `80 passed, 1 skipped`; pip-audit clean; pinned upstream client/metadata tests
  and non-root image smoke passed.


## Integration recovery — 2026-10-06

Verified main `8481c0e`; latest heads of PR #2–#10 all have successful hosted checks.
Created a separate production-candidate worktree, merged the #8 stack once and independent
#9/#10 follow-ups, preserving both historical evidence streams. Documentation conflicts were
reconciled; combined code/migrations/tests are awaiting the full quality gate.


## SC08 sprint local evidence — 2026-10-07

Code evidence `abe290f` (local; hosted CI for the exact final head is recorded only in PR #11).
Verification matrix 31/31 exit 0; full pytest 1438 passed / 238 skipped; E2E smoke 29, User U01-U18 53
passed (U18 = 11 of 12 scenarios PASS + SC06 EXTERNAL-GATE declared, Amendment A2 PROPOSED, not 12/12),
Admin A01-A54 87 + 1 declared EXTERNAL-GATE skip; Functional Tester 83 tests = 79 passed / 3 skipped /
1 xfailed (SC06), SC08 PASS. Local reviewers: no BLOCKER (`core/DECISION_LOG.md`). Production NO-GO; DoD
PARTIAL; real-reference L2-B lane not executed yet.

## E2E, Functional Tester and release-candidate closure — 2026-10-07 (earlier, code `d7e578e`)

Code evidence `d7e578e` (local; hosted CI for the exact final head is recorded only in PR #11).
Verification matrix 31/31 exit 0; full pytest 1230 passed / 232 skipped (dispositions in
`ERP_MCP_FINAL_MVP_CLOSURE_LEDGER.md`); E2E smoke 29, User U01-U18 52 passed (U18 = 10 of 12 scenarios PASS + SC06/SC08 declared per Amendment A1 of the E2E contract, not 12/12), Admin A01-A54 87 +
1 declared EXTERNAL-GATE skip; Functional Tester SC01-SC12 73 passed / 3 skipped / 2 xfailed
(`FUNCTIONAL_TESTER_SC01_SC12.md`). Evidence is synthetic L1 only. Owner manual acceptance: PENDING.
Production decision: NO-GO; DoD: PARTIAL; external gates unchanged.

2026-10-07 real-reference L2 lane (818HA clone, read-only, code `1864bd9`): 130 catalogue stories dispositioned (CAPABILITY_UNSUPPORTED 25, EVIDENCE_REQUIRED 29, FINDING 4, INCONCLUSIVE 2, PASS 6, REFUSED-WRITE 6, SEMANTIC_PROFILE_UNVALIDATED 58); supplementary: ACL:PASS 7, INV:EVIDENCE_REQUIRED 21, NR:EVIDENCE_REQUIRED 9, NR:INCONCLUSIVE 1, RL2:FINDING 1, RL2:PASS 9, RULE:CAPABILITY_UNSUPPORTED 90, RULE:EVIDENCE_REQUIRED 90, SYS:FINDING 5, SYS:PASS 2. No semantic profile is validated: COM comparisons are NATIVE_COM_QUERY context only and at least ten genuine native UI reports are still owed by the owner. Evidence: `reports/real1c/` (summary, per-test details ru/en; exact figures kept privately outside Git), `reports/FUNCTIONAL_TESTER_REAL-1C-818HA.md`. Hosted CI for the exact head: PENDING. Owner manual acceptance: PENDING. Production decision: NO-GO.
