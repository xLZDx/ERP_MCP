# Functional Tester report REAL-1C-818HA

- Git SHA (code under test): `1864bd91da9d6cb2e6af7ba4e58f382b7559bda9`
- Reference manifest sha256: `2751d13fecde4ef11cf7c8cf676c156c4d80f56ba9aaf31a0a5d716aab01a426`
- Generated at: 2026-10-07T11:58:16+03:00
- Data as of: 2026-08-31
- Testbed readiness verdict: READY_FOR_SCENARIO_EXECUTION

## Story dispositions (90 ST + 40 AX)

- CAPABILITY_UNSUPPORTED: 25
- EVIDENCE_REQUIRED: 29
- FINDING: 4
- INCONCLUSIVE: 2
- PASS: 6
- REFUSED-WRITE: 6
- SEMANTIC_PROFILE_UNVALIDATED: 58

## Supplementary results

- ACL:PASS: 7
- INV:EVIDENCE_REQUIRED: 21
- NR:EVIDENCE_REQUIRED: 9
- NR:INCONCLUSIVE: 1
- RL2:FINDING: 1
- RL2:PASS: 9
- RULE:CAPABILITY_UNSUPPORTED: 90
- RULE:EVIDENCE_REQUIRED: 90
- SYS:FINDING: 5
- SYS:PASS: 2

## FINDING cases

- ST-075
- ST-076
- ST-077
- ST-085
- RL2-10
- SYS-01
- SYS-02
- SYS-03
- SYS-04
- SYS-05

## REAL 1C 818HA L2 ACCEPTANCE

- frozen catalogue sha256: OK dad5bddccc3c24ac…
- code tree: committed
- reference manifest hash: OK 2751d13fecde4ef1…
- testbed readiness: READY_FOR_SCENARIO_EXECUTION
- pre-run COM fingerprint equals manifest: OK d75bf1f7c4b0be1e… (1184 tables, 755011 rows)
- gateway + sidecar + proxies: reachable
- post-run COM fingerprint equals pre-run: OK identical
- upstream methods seen by the lane proxies: {'HEAD': 6, 'GET': 124} (no write verb)
- case result schema: OK 365 results
- public report view: exact monetary values of NR/RL2/INV removed (20 figures kept privately)

Read-only lane executed against the 818HA reference clone at 1864bd91da9d: 130 catalogue stories, 6 PASS, 58 blocked by the semantic profile gate, 10 FINDING items across all cases. Business acceptance stays PENDING and production stays NO-GO: no native 1C UI report has validated a semantic profile.

Open items:
- At least ten genuine native 1C UI reports are required before any semantic profile can be validated.
- Manual business acceptance is PENDING; production is NO-GO.
- Hosted CI on the exact head is PENDING (recorded in the PR body, not in tracked docs).
