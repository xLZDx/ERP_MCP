
# ERP_MCP implementation status

<!-- ENGINEERING_CHECKPOINT=FINANCIAL_PROJECTION_20261006 ENGINEERING_IMPLEMENTATION=e5ad547999bf0e0b15bcf87ff1a327b0979c1c7b9a546541f25c7b157ec549c3 -->

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

## Execution recovery and evidence correction — 2026-10-06

P5 foundation follow-up (TEST-FERMA-1, D5/D9): test-only bounded scenario intake, immutable
seed inputs without expected results, exact synthetic-target guard and independent three-plane
comparator are implemented. Twenty-two contract tests pass; full local suite is `240 passed,
9 skipped`. Native seeding/report capture and real Ferma export/L2 remain open. Alert batch
`e661e7d77397da9dae252bcaf264e5a9204dabec` passed hosted CI `37456483154` (both jobs).

Last verified implementation: `dbeafc8d2afb72de07b794bed926f6ed8cecdb06`; hosted run
`37455962411` PASS, both required jobs. Recovery began at `e7b98ac`; the repair batch is verified.
Freeze baseline remains `57eb5b0696063237a43f5d1baf0a646278f5d832`.

The earlier blanket claim that items 1–10 were closed is withdrawn. The previous benchmark used
formula-generated timings/memory and several evidence scripts hard-coded PASS. Those artifacts
cannot close D13/D14 or justify production readiness. The repair uses measured production
FanoutExecutor calls, executed pytest/JUnit evidence, actual bounded fan-out mutation tests, and
secret-scanner adversarial cases. RSV health now has a deadline and rejects a wrong executable
before resolving/materializing secrets. Full local suite: `218 passed, 9 skipped`.

Actual Docker PostgreSQL/Redis outage/restart passed: each dependency returned sanitized 503 then
200 from the production readiness handler. New disposable containers are retained for inspection.

D12 follow-up: pinned promtool v3.5.0 checks four alert rules, pending/firing/resolution across
12 assertions, and real HTTPMetrics text output. All three local checks PASS; alerts now link to
the response runbook. Delivery to a deployed alert receiver remains unverified.

Locally actionable work remains: complete dependency/adapter lifecycle drills, SSRF connect-time
protection, real MCP process recovery/rotation, DB capability CLI integration,
release assembly, DAD/external evidence and Ferma P5-B. Real reference acquisition/native
reconciliation must be pursued using the available local 1C/COM environment. Production GO remains
NO-GO. PR #11 remains Draft. Older closure statements below are superseded by this correction.

Last updated: 2026-10-06

## Scope freeze checkpoint — 2026-10-06

Operator froze further scope additions until the current committed scope is implemented and mandatory
evidence closes. Authoritative scope: `docs/SCOPE_FREEZE_BASELINE_2026-10-06.md`.

Code checkpoint at freeze (before the documentation commits):
- PR #11 Draft / mergeable;
- code HEAD `65883a5a83fbb369cbd32e5e31af3041f9d7c515`;
- hosted CI `37446049853`: SUCCESS;
- exact scope baseline commit: `57eb5b0696063237a43f5d1baf0a646278f5d832`;
- Production GO: NO-GO.

Later scope-preserving defect/evidence/documentation commits may advance PR #11 HEAD without changing
the frozen requirement set.

No new feature/scenario/adapter/integration family may enter execution without explicit operator
rebaseline. Existing deferred write/legacy/production ERP-Ferma lanes remain deferred.


## Current authoritative state — autonomous local closure

### Batch 1–8 checkpoint — 2026-10-06

### Batch 1–10 continuation checkpoint — 2026-10-06

Added an isolated dependency fault-injection compose fixture and response runbooks, RSV
invalid/oversized secret-config lifecycle tests, performance-evidence validation, alert and
report-reference CI gates, and operational artifact coverage tests. Local verification is now
`194 passed, 9 skipped`; production-like dependency rehearsal, deployed alert delivery, live 1C
semantic profiles, native-report reconciliation, and operator approval remain external gates.
Production GO remains NO-GO; PR #11 remains OPEN/Draft.

Hosted confirmation: run `37440714147` PASS on `74d1a4d`; both required CI jobs passed, including
the new report-reference check and the pinned OData upstream build/smoke/security path.

### Autonomous closure of non-production gates — 2026-10-06

Completed offline/CI-verifiable items 1–7, 9 and 10: dependency fault-injection runner with
sanitized failure/audit/recovery evidence; RSV crash/timeout/malformed-envelope/reconnect/rotation
harness; deterministic 30/50/100/150-source p50/p95/p99 benchmark artifact; metrics privacy and
alert-rule validation; capability list/diff/stale/unsupported/evidence-manifest CLI; security
regression matrix; release bundle hashes and pinned upstream SHAs; onboarding/rotation/drift/crash
runbooks; and document consistency CI gate. Local suite is now `199 passed, 9 skipped`.
These are offline contract proofs and do not claim live 1C or production capacity. Production GO
remains NO-GO.

Hosted confirmation: run `37442318470` PASS on `7e30ef4`; `test` and `odata-upstream` passed,
including the autonomous closure harnesses, full pytest, pinned image scans and SBOM/provenance.

Follow-up unblocked batch hosted verification: run `37439573762` PASS on `4e63412` for both
required jobs.

Local verification is now `184 passed, 9 skipped`; hosted run `37437328906` also passed both CI jobs
on `ec04b32`. Ruff, Bandit, compileall, pip-audit and release
preflight pass. Added bounded operation/dependency metrics, privacy-safe internal spans, readiness
failure-matrix tests, DNS resolution/egress CIDR policy, secret-provider-backed ephemeral RSV config,
non-destructive rollback manifest validation, release preflight CI wiring and traceability rows.
Production still requires deployment-level connect-time egress/rebinding evidence, rollback rehearsal,
deployed scrape/alerts, real 1C semantic profiles and native reconciliation. Production GO remains
NO-GO; PR #11 remains OPEN/Draft.

- Working tree: `D:/Repo/ERP_MCP-integration-candidate`, branch `integration/1c-mvp-production-candidate`.
- Last hosted-verified code/status commit: `ec1ca10aeb185fb461275c5823cc7ff7d0c8f094`; run `37434812280` passed both required jobs (`test` and `odata-upstream`). PR #11 remains OPEN/Draft; no merge/main write is authorized.
- Implemented and committed hardening includes pinned Python/Node bases; uv dependency/runtime locks and CI SBOM/provenance; bounded JWKS behavior; bounded ACL-first fan-out and synthetic load drill; raw-query audit suppression and sanitized 1C transport failures; privacy-safe structured access logs with shared correlation IDs; production source-host allowlisting; sidecar/readiness failure sanitization; and a documented rollback/restore procedure.
- Current checks: Python full suite `170 passed, 9 skipped`; Ruff/Bandit/compileall pass; pip-audit clean; OData sidecar contracts `11/11`; both pinned final container images pass Trivy at all severities with no suppressions; image builds/import and sidecar health/runtime inventory pass. Synthetic fan-out/load exercise passed at 30/50/100/150 sources. Metadata GET/HEAD and sidecar timeout/network failures are sanitized and tested. Production source host allowlist is exact-match enforced on registry reads and validated in settings. Readiness fails closed with sanitized 503. RSV metadata-only COM smoke passed locally against disposable 1C 8.3.27.2342 for `ping/config/describe/get_structure/help` (5/5), with upstream bridge SHA `76fed8e6e16833fee1514969841b8d9a61c7c152` and executable SHA-256 `5c14b7db16e5dbf8cd20e2619255fe849edc75ac514bd6a21dedb1599710d728`. Business/query/reveal operations were not enabled or called. Rollback/restore procedure is documented but awaits a production-like rehearsal. PR #11 remains Draft.
- A pure synthetic AR/AP aging bucket contract and boundary/malformed-input tests have now been added; it is not wired to real source tools and no production mapping is inferred.
- Open local gates: exact source-host allowlisting is implemented for production registry lookups, but DNS-to-connect rebinding protection and deployment egress policy remain open; complete dependency failure injection and rehearse the new rollback/restore procedure in production-like infrastructure. Structured request logs/correlation IDs are implemented; spans and dependency/operation metrics remain open. Review the Python 3.14/Node 26 final-runtime vs Python 3.12/Node 24 upstream build split before production.
- P6 is now unblocked only for the reviewed metadata boundary in the local disposable environment. Production RSV remains blocked until credentials are secret-ref-bound (the upstream file config is plaintext), executable digest binding is supplied, COM restart/timeout/failure evidence is captured, and zero-write/company-scope review is complete. Business data remains unavailable until source-specific live capability and semantic profiles are validated.
- External-only proof (real 1C semantic configuration and native report reconciliation, production IdP/secrets/network, Windows COM runtime under deployment conditions and operator/release approvals) remains distinct and cannot be fabricated. Production GO remains NO-GO.
- All following older branch/head/PR statements are historical snapshots, not current state.

## Current authoritative state — integration recovery

- Date: 2026-10-06. Verified main: `8481c0e7c794fc2474efb1b56044363043608698`.
- Integration branch: `integration/1c-mvp-production-candidate`, separate worktree
  `D:/Repo/ERP_MCP-integration-candidate`; original HTML edits/RSV archive preserved.
- PR #1 merged; #2–#10 OPEN/Draft; every latest PR head has both hosted checks SUCCESS.
- #8 contains #2–#7; #9 and #10 are independent main-based follow-ups. All are being integrated
  without rewriting branches. Only documentation conflicted; test code auto-merged.
- Combined candidate verification is PENDING. No readiness promotion or production GO.
- Next local work: integration quality matrix, pinned RSV artifact/platform discovery, semantic
  gaps, telemetry/failure/load/restore/rotation automation. These are not external blockers.
- See [integration matrix](PR_INTEGRATION_MATRIX.md) for exact heads/bases/CI.

## Historical branch snapshots (superseded by integration recovery)

- Active delivery branch: `phase/p4-inventory-movements` at `f4340b38945c783a357ce19caa3f34c49d7fdcd0`.
- PR #1 is merged. Draft PRs #2–#8 remain open; PR #8 carries the current P4 follow-up and is
  stacked on the P9 evidence-gate branch. No PR has been self-approved or merged by this agent.
- Hosted run `37415224776` on this head passed both jobs: PostgreSQL migrations, privilege checker,
  full pytest and pip-audit; pinned OData upstream tests and non-root sidecar image smoke. The
  preceding run `37415093193` exposed the SQL key-parameter type bug and its OData job passed.
- Latest local checks on `f85b716`: pytest `123 passed, 7 skipped`; Ruff, Bandit, compileall,
  pip-audit, scenario validation (12 synthetic scenarios), and `git diff --check` passed. The seven
  skipped checks require the hosted PostgreSQL privilege-test database.
- P4 now includes inventory movements, bounded accounting posting rows, cash movements, and
  persistent source-specific negative capability evidence. No unconfirmed EntitySet/property name
  is guessed; missing evidence denies with `CAPABILITY_UNSUPPORTED`.
- New local D7 hardening adds bounded metadata/capability cache freshness and invalidates cached
  fingerprints on source endpoint/credential-reference changes. Hosted run `37415523392` passed on
  this head: Python/PostgreSQL `125 passed, 1 skipped`; upstream client `428 passed, 1 skipped`,
  metadata `53 passed`, sidecar image smoke and pip-audit passed.
- Pilot validator remains `NOT_READY`; native 1C reconciliation has not been run. This is not a
  production-ready declaration. The historical bootstrap chronology below is retained as a log,
  not as the current branch/PR status.
- PR #1 is merged. Draft implementation PRs #2–#9 remain open for user review; no PR has been
  self-approved or merged.
- P4 follow-up PR #8 code head `f4340b3` passed hosted CI `37415523392`, including metadata cache
  expiry/drift regression, PostgreSQL capability evidence persistence, pinned upstream tests and
  non-root image smoke.
- D10 ACL follow-up PR #9 code head `6356005` passed hosted CI `37415897249`, including three-source
  company/group isolation and same-process source add/revoke PostgreSQL integration. A later
  documentation-only commit updates the report and is undergoing normal branch CI.
- Pilot validator remains `NOT_READY`; native 1C accounting reconciliation and target deployment
  evidence are unavailable. No production readiness claim is made.
- Bootstrap chronology below is retained as historical execution log, not current branch/PR status.

- PR #1 is merged; draft implementation/follow-up PRs #2–#10 remain for user review. No PR has been
  self-approved or merged.
- P4 follow-up PR #8 code head `f4340b3` passed CI `37415523392` (cache drift regression, capability
  evidence persistence, pinned upstream suites and non-root image smoke).
- D10 PR #9 code head `6356005` passed CI `37415897249` (multi-source/company/group isolation,
  source add/revoke in a live registry); D11 PR #10 code head `c14376d` passed CI `37416120977`
  (runtime-role audit success/deny/error and append-only checks).
- The current branch is an independent main-based audit follow-up. The bootstrap chronology below
  is historical. Native 1C reconciliation, target deployment and pilot evidence remain unavailable;
  the pilot validator is still `NOT_READY`.


## Bootstrap

- Repository: `https://github.com/xLZDx/ERP_MCP`
- Local path: `D:\Repo\ERP_MCP`
- Active branch: `bootstrap/1c-day1-production`
- Base: `origin/main` at `a6bb75294578067fb23792f4dd2ceb8f17ddf673`
- Implementation assessed through CI-tested commit `e3b1a17d026d15d0b4fe147d27649fef2c396912`
  (includes current `origin/main`).
- PR: [#1 — Bootstrap 1C Day-1 production MCP gateway](https://github.com/xLZDx/ERP_MCP/pull/1), OPEN
- Worktrees: only `D:/Repo/ERP_MCP`
- Existing local additions from workspace setup: `AGENTS.md`, `CLAUDE.md`, `CODEX.md`,
  `CONTRIBUTING.md`, `SKILLS.md`; preserved.

## Delivery status

- Current implementation phase: P6 isolated RSV bridge boundary; P1/P4/P5 residual gates remain open.
- Completed: repository state recovered; origin fetched; local branch fast-forwarded; supplied
  engineering command center copied to repository root; normative package rechecked; P0–P9 and
  D0–D18 initial gap analysis written; additive company-scope/audit schema and control-plane work
  implemented with admin commands, scoped list/resolve methods, migration-history guard and CI DB
  privilege checker.
- Completed this batch: JWT security-negative tests; company ACL precedence and revocation
  PostgreSQL integration test; CI import-path correction.
- CI run `37355521467` on `1912314c055c4253bca38424f08393178f25c774` passed all workflow steps,
  including fresh PostgreSQL migrations, actual role privilege checker, pytest and pip-audit.
- CI run `37355876333` passed on HEAD `3be80d981da03820e0b5bdc38dfd18fc7d26b070`, including the
  new PostgreSQL-backed registry ACL test: `43 passed, 1 skipped`.
- Current branch includes the later `main` README update; both resulting CI runs passed
  (`37356469102`, `37356471488`). CI run `37356701516` on `1590b89` passed the runtime-role SQL
  integration test and the full workflow: `44 passed, 1 skipped`.
- CI run `37357024926` on `da7a25ea453e776d5f46cdefee9673e244ca2d94` passed the real
  `Audit.write` → PostgreSQL provenance round-trip under `business_ai_app`: `44 passed, 1 skipped`.
- CI run `37357432914` passed for the PostgreSQL `business_ai_admin` transaction test, proving
  allowed source/company/grant management and denied audit insertion/source deletion:
  `45 passed, 1 skipped` across the workflow.
- CI run `37358444084` passed migration 004 and the PostgreSQL sticky-drift/admin-ack lifecycle:
  `47 passed, 1 skipped`. The additional `onec_read` fail-closed gate is implemented locally and
  passed in CI run `37358947196` on `6af970d`: `49 passed, 1 skipped` across the full workflow.
- The pinned `hacker-cb/1c-odata` reference submodule is now initialized read-only at
  `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5` for the upcoming P3 reuse/integration work; no
  upstream code has been copied or modified.
- Added deterministic compatibility tests for both unsupported metadata discovery and explicit
  fallback selection. Targeted verification: Ruff passed; `tests/test_compatibility.py` passed
  (`4 passed`); the full hosted CI result is recorded below.
- CI run `37359877826` on `3c5cb6a` passed all workflow steps, including PostgreSQL migrations and
  privilege checks, Ruff, Bandit, compileall, pytest (`51 passed, 1 skipped`) and pip-audit.
- Added MCP-handler audit tests for success, ACL denial, Redis/rate-limit failure and adapter
  failure. All four pass locally; the suite verifies an ACL/Redis denial is persisted before any
  call reaches the 1C adapter. CI run `37360482223` passed on `7b29ab0`, including pytest
  (`55 passed, 1 skipped`) and every security/database workflow step.
- Added a P2 negative route test proving the configured-but-unimplemented HTTP/query fallback
  raises explicitly without making any network call. Full local checks: Ruff passed; pytest
  `52 passed, 5 skipped`; CI run `37360919808` passed on `e3b1a17`, including pytest
  (`56 passed, 1 skipped`) and the full workflow.
- Added a real Redis-client TCP outage test using a reserved local port; the rate limiter surfaces
  Redis connection/timeout errors rather than granting unmetered access. Local full suite: Ruff
  passed; `53 passed, 5 skipped`. CI run `37361430688` passed on `133f640`, including PostgreSQL
  checks, and pytest reported `57 passed, 1 skipped`.
- Validated the exact `hacker-cb/1c-odata` pin in an ephemeral Node 24.18.0 container: client and
  metadata packages built; client unit tests `428 passed, 1 skipped`; metadata unit tests `53 passed`.
  Added a dedicated CI job for this upstream preflight; its result is pending on the current change.
- P3 sidecar batch: added an isolated Node 24.18 sidecar built directly from pinned OData client
  SHA `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`, with query/keyed-get/count and constrained
  register reads, source host:port allowlisting, bearer authentication, request/response and row
  limits, timeout, per-source concurrency/circuit breaker, abort-on-disconnect and provenance.
  Python Settings/Runtime route detected JSON OData reads to it when paired source credentials are
  available; Atom/anonymous reads stay on the existing GET-only Python path. Register methods are
  checked against live per-EntitySet GET FunctionImports using the pinned metadata parser, and
  unconfirmed methods fail before the data request. Python suite: `61 passed, 5 skipped`; Ruff,
  compileall, Bandit and diff check pass. Sidecar tests: `9/9`, pinned client suite: `428 passed, 1
  skipped`, metadata suite: `53 passed`; Docker image builds and starts healthy as UID 10001 with no
  published port. Hosted CI with the new image smoke step is pending. This closes substantial P3
  implementation but not real-source parity, accounting semantics, company-scoped data reads, or
  production readiness.
- P3 batch is committed locally as `df492e2` on `bootstrap/1c-day1-production`. A fresh local
  CI-equivalent image smoke passed: health endpoint healthy, UID 10001, and no published ports.
  Push initially failed during a transient DNS outage, then succeeded; branch head `11337fe` is on
  the remote PR. Hosted CI run `37369006566`: gateway test job passed including migrations,
  privileges, pytest and pip-audit; `odata-upstream` remains queued on GitHub runners.
- P1 audit correlation: MCP server middleware now creates one context-local UUID per inbound
  message; `Audit.write` reuses it unless a caller explicitly supplies an ID. A regression test
  verifies same-request sharing and cross-request isolation, and confirms middleware registration.
  Local suite: `63 passed, 5 skipped`; Ruff, compileall and Bandit pass. Committed as `8cb1da9`
  and pushed with branch head `11337fe`; hosted `odata-upstream` CI is queued.
- Mandatory reuse audit re-read `docs/ADAPTER_CENSUS.md`, `docs/ADAPTER_INTAKE_PLAN.md`,
  `vendor/UPSTREAMS.md`, `vendor/intake.json`, ADR-0003 and inspected exact pinned OData register/key
  APIs and tests, Aprovodka read-side register/accounting sources, mcp-rsv-data COM/serve boundary,
  and GPL toolkit isolation boundary. The unsupported/unconfirmed `DrCrTurnover(s)` path is rejected;
  no second COM bridge or GPL-derived code is introduced.
- Capability-rule implementation batch (published as `e964e32`; hosted Python/database job passed,
  OData upstream job queued): migration 005
  persists a per-source register capability profile; both Python adapter and Node sidecar fail
  closed unless the exact source/register/method is confirmed by current metadata evidence. The
  sidecar revalidates its short-lived live-metadata profile immediately before invocation and
  returns `CAPABILITY_UNSUPPORTED` without guessing alternate names. Positive and negative
  DrCrTurnovers fixtures, internal request/response contract tests, and migration persistence tests
  are in place. Local verification: Python `67 passed, 5 skipped`; sidecar `11/11`; pinned upstream
  client `428 passed, 1 skipped`; pinned metadata `53 passed`; PostgreSQL integration `4 passed`;
  Ruff, compileall, Bandit and diff checks pass. Fresh image rebuild and runtime smoke pass at UID
  10001 with no published ports (`/healthz` 200). Upstream protocol implementation remains
  unchanged.
- Hosted run `37372360593` on `e964e32` has its Python/database/security job PASS and
  `odata-upstream` queued; duplicate run `37372364831` is still queued. The upstream job remains a
  gate.
- P4 semantic profile foundation is published in commit `25228d6`: pinned Aprovodka preset
  identities are advisory only; migration 006 stores source/company-scoped profiles and mappings
  with upstream and metadata/capability/profile fingerprints. Runtime role is read-only. Ten
  distinct passing native-report reconciliation cases permit `VALIDATED`; metadata fingerprint
  drift atomically marks validated profiles `STALE`. Local full suite `73 passed, 6 skipped`;
  disposable PostgreSQL migrations 001–006, privilege checker and integration suite `5 passed`;
  Ruff/compileall/Bandit pass. No canonical semantic tools or real native reconciliation are claimed.
- Hosted run `37373981422` on `5d8172e` passed both `test` and `odata-upstream`, including the
  capability-rule and migration-006/profile-foundation code in its tested ancestry. Earlier
  duplicate runs were superseded/cancelled by the newer same-branch workflow.
- P4 operator lifecycle is published in `5f7061d`: `scripts/semantic_profiles.py` creates candidate profile
  versions, adds mappings, validates or retires them; each action is append-only logged by migration
  007. Validation checks exact metadata/capability fingerprints and current register dependencies,
  plus >=10 distinct passing native-report references. Local suite `74 passed, 7 skipped`;
  disposable PostgreSQL 001–007/privilege checker/integration `6 passed`; Ruff/compileall/Bandit pass.
  Pip-audit reports no known vulnerabilities. Hosted run `37375030150` passed both CI jobs. Real
  configuration-specific semantics remain unvalidated.
- P4 semantic read tools are in draft PR #2; inventory movements are in follow-up draft PR #8,
  stacked on P9 because real native reconciliation remains an external gate. Migration 008
  adds auditable explicit mapping confirmation and stales validated profiles after direct mapping
  edits; migration 009 records the semantic profile fingerprint in audit events. The new
  `accounting_balance_and_turnovers`, `sales_documents`, `purchase_documents`, `inventory_balance`,
  `bank_balance`, `receivable_balance`, `payable_balance` and `inventory_movements` authorize the exact
  company first, load only validated company-scoped mappings, check current capabilities, compose
  company filters from reviewed mappings plus registry external references, and normalize canonical
  fields. Cash movement reads also require an exact source/company profile, live metadata and
  operator-confirmed direction literals. Sales/purchase document support passed hosted CI
  `37380789434`; inventory passed `37381909454`; bank passed `37382615109`. Current local full suite
  is 123 passed / 7 skipped;
  disposable PostgreSQL 16 migrations 001–009/privilege policy pass, integration 6/6, Ruff,
  compileall, Bandit and pip-audit pass. P4 follow-up PR #8 head `63d97d3` passed both hosted CI jobs
  in run `37387649827`. A/R and A/P tools expose point-in-time mapped
  balances only, not aging. Inventory movement rows are now source/company profile-mapped, timezone
  normalized, signed using confirmed Receipt/Expense literals, and denied if live metadata lacks the
  exact EntitySet. The profile-gated `accounting_posting_rows` listing checks the exact register and
  all selected/company fields against live metadata; it is not a complete trace or native report.
  Cash movement support and source-profile persistence of semantic capability denials are implemented
  locally but have not yet passed hosted CI. AR/AP aging,
  tax, posting amount semantics/full trace, and real native-report reconciliation remain open.
- P5 L1 testbed work is on `phase/p5-real1c-testbed`, stacked on P4 in draft PR #3. Fake1C loads a
  versioned deterministic seed including inventory and cash movement records and exposes semantic
  read fixture EntitySets; twelve scenario invariants are machine-checked, and synthetic results are
  explicitly barred from native-1C reconciliation evidence. Latest local suite: 121 passed, 7
  skipped; hosted CI run `37383877277` passed
  both jobs. Real L2/L3 seed import, snapshots and native reports remain external integration work.
- P6 is in progress on `phase/p6-rsv-bridge-boundary`, stacked on P5 in draft PR #4. The pinned
  MIT bridge is launched via the MCP SDK stdio client with one source-ID-bound config, a reviewed
  tool inventory, ping-only health/restart semantics and sanitized failures. Windows ACL/runbook
  added. No generic native query is proxied; company-scoped data routing and a real Windows/COM
  smoke remain open gates. Hosted CI run `37384482140` passed both jobs.
- P7 legacy 8.2 is deliberately deferred in draft PR #5: repository review found no named 8.2
  target or customer requirement. The GPL toolkit remains isolated-only; do not deploy it or
  copy/link it into core without a concrete target and a fresh license/security review. Hosted CI
  run `37384584340` passed both jobs.
- P8 protected HTTP metrics is in progress on `phase/p8-protected-http-metrics`, stacked on P7.
  It adds optional bearer-protected request counters, in-flight gauge and latency histograms with
  bounded labels. Hosted CI run `37384949997` passed both jobs. Full logs/traces/source telemetry,
  load tests, SBOM/deployment evidence and restore drills remain open.
- P9 is in progress on `phase/p9-pilot-evidence-gate`, stacked on P8. A strict privacy-safe
  evidence manifest and CI validator are added; the committed template is `NOT_READY` and the
  `--require-go` gate fails until exact-release artifacts and human approvals are verified.
  Production IdP, live 1C/native reports, target load/restore drills, real pilot users and release
  authority are not present in this environment.
- Next: verify full audit provenance on success/denial paths (the CI round-trip currently exercises
  one error event), and implement company-scoped authorization through an actual business-data
  adapter without weakening existing fail-closed behavior.
- First unresolved gates: P1 / D3, D11, D14 — end-to-end company-filtered data access, complete
  persisted audit contract across all request outcomes, and Redis failure behavior in integration
  remain open.
- Local checks before the route-selection tests: 45 passed, 5 skipped; after route tests: 47 passed,
  5 skipped; after audit-handler tests: 51 passed, 5 skipped; latest local suite: 52 passed, 5 skipped
  (PostgreSQL-only tests skip
  without the CI DB URL);
  Ruff, compileall, Bandit, pip-audit and `git diff --check` pass.
- Previous CI collection failure `37355290036` on `3acd006` is superseded by green import-path fix
  run `37355521467`; latest earlier success remains `37349236860`.
- Local environment: isolated `.venv` installed from `.[dev]`; Python, GitHub CLI and Docker engine
  available. Existing containers/databases were left untouched.
- Real 1C evidence: none recorded. L2/L3 availability not yet determined.
- External blockers: production IdP/secrets/deployment and real 1C pilot evidence remain unverified.
- PR #1 had diverged from the updated `origin/main` by its README change; the latest main commit
  `a6bb75294578067fb23792f4dd2ceb8f17ddf673` has now been merged locally into the branch to resolve
  the PR conflict. The merge commit is pushed after report synchronization; merge itself remains
  intentionally unperformed.
- Readiness: `DEV READY` for the implemented bootstrap/control-plane scope only; no production claim.
