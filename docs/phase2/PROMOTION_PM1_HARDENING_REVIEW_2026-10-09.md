# Phase 2 — P-M1 promotion preflight hardening (2026-10-09)

**Decision:** local code fix VERIFIED; **Release 2 NO-GO**. Review branch `hardening/phase2-promotion-pm1-20261009`, base `a00d16a077848ca2ebd092e5b99cda90e7350132` (the source commit containing the S1–S4 offline slice). This is not an approval to merge, deploy or grant write authority.

## Verified failure before the fix (RED)

The promotion service trusted a stale or misrouted `AttestationReader.find_attestation` result without verifying that the returned attestation belonged to the requested revision and evidence reference. Prior isolated review `PROMOTION_PREFLIGHT_REVIEW_2026-10-09.md` reproduced one premature write-port attempt. On this branch, the two RED regression tests confirmed:
- A cached attestation for a different revision returned `REJECTED_EVIDENCE` **only after calling** `promote_head`; the service's no-write-on-rejection contract was broken.
- A cached attestation carrying a mismatched evidence reference did not fail at the service boundary; with genuine underlying data the fake-port completed a promotion, demonstrating that this was more than an error-code mismatch.
- Adversarial follow-up RED cases confirmed that custom equality objects as `decision` and `evidence_digest` and a truthy string returned by `is_trusted_reviewer` could each fool preflight into `PROMOTED` under local fakes.

These are local pure/fake contract findings, **not evidence of unauthorized real 1C operations**. The SQL permission/revocation/CAS checks remain separately authoritative.

## Changes and acceptance checks (GREEN)

- `PromotionService._run` now validates that the read view is precisely an `AttestationView` with exact UUID attestation/revision IDs and an exact string evidence reference equal to the request; any mismatch returns `REJECTED_EVIDENCE / EVIDENCE_IDENTITY_MISMATCH` **without** invoking the write-port.
- The decision must be a built-in `str` equal to `APPROVE`. The stored evidence digest must be a built-in `str` equal to the independently recomputed digest. Reviewer trust must return the singleton `True`, not merely a truthy object.
- Additional negative tests exercise stale other-revision and other-ref views, three malformed identity values, wrong view type, two custom-equality spoof claims, and non-bool reviewer trust. Existing happy-path promotion, rollback, revoked/expired attestation and CAS tests were preserved.
- Promotion-focused suite after first fix: **63 PASS**, Ruff PASS.
- Full isolated Phase 2 suite after additional guard tests: **737 PASS / 180 SKIP**, 11.73 s; Ruff PASS; `compileall` PASS. The 180 skipped tests remain NOT_RUN; they are not implicit evidence for live PostgreSQL, 1C or Drive.
- Git diff integrity `git diff --check`: no whitespace errors (CRLF normalization warnings only).

## Review perspectives / residual risks

**Security:** invalid attestation identity, type or trust cannot reach the write-port through ordinary service calls covered by tests. SQL must independently enforce attestation authenticity, source scope, role separation, race fencing, and revocation. No trust is inferred from a Python-side view alone.

**Functional testing:** tests assert no `SpyPort.promote_head` call and no head/version mutation on rejection; the valid approval/rollback controls remain green. Unexpected callback exceptions fail closed.

**Architecture:** the preflight guard does not provide native evidence approval and does not replace the trusted database function. Real deployment wiring, IAM, source-wide ACLs, production rollback drills, capacity and independent customer acceptance are not closed by this patch.

**Devil's advocate:** a malicious actor with direct Python object access or a compromised privileged DB layer is outside this preflight boundary. In-process mock evidence does not prove transactional PostgreSQL behavior. Real-source production release remains NO-GO.

## Follow-up gate

- Review this exact change with the Phase 2 owner/GPT-PM; apply only after governance approval, then run all mandatory PostgreSQL integration and R1 compatibility gates on the proposed merge/release HEAD.
- Do not merge the old `hardening/phase2-budget-validation` review branch blindly: it started before `a00d16a` and contains separate fixes. Rebase/cherry-pick reviewed slices deliberately, avoiding changes to currently unfinished `connector_sdk.py` / `drift.py` in the active worktree.
