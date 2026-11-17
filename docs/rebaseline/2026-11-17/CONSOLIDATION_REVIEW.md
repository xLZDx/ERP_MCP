# Consolidation independent review

The router recorded four roles for the full application delta from main7c1f69c:
code-reviewer, silent-failure-hunter, python-reviewer and database-reviewer.
The reviewed initial source checkpoint was0d02626, with metadata HEAD3abd060.
The subsequent application fix is a9f03cf. This is independent source review,
not a claim of exhaustive line coverage or runtime/product acceptance.

| Role | Inspected paths and limits | Result |
|---|---|---|
| code-reviewer | Observation reservations, capture cancellation/drain, manifest binding, S12 lane/proofs, S13 latestness/key authorization; not every line of121 application files | No confirmed BLOCKER/MAJOR in inspected paths. |
| silent-failure-hunter | Cancellation/unknown outcomes, pending work, lifecycle fail-closed errors, anchor dev/loopback boundary and tunnel start non-claims | No confirmed BLOCKER/MAJOR in inspected failure paths. |
| python-reviewer | Python resource/validation/async and trust-boundary paths, followed by signature-reuse fix review | One confirmed MAJOR, accepted from a directly verified code fact and fixed in a9f03cf; no additional confirmed BLOCKER/MAJOR. |
| database-reviewer | Full016..018, historical028/029,031..039; key target/effect/fence paths in3292-line030, not every function body | No confirmed findings in inspected SQL. Caller timeout/recovery completion and live race behavior are not established by static review. |

## Accepted finding PY-01

`DispatchGate.checkpoint_operator_resolution` previously skipped the verifier
when `read_back` returned an existing matching record. The record's128-hex
signature shape did not prove authenticity, yet the next call stored
`signature_valid=True` and then released anchor-gap holds. A corrupted provider
row after an ambiguous attempt could therefore cross the hold boundary.

In a9f03cf every reused or new record must pass the real configured verifier
before checkpoint persistence or hold release. Immutable historical public
material remains usable; current-key signing permission and historical-key
authorization are separate policies. This does not create provider latestness
proof or a READY path.

The new named regression covers forged exact-metadata readback with no database
record/release effects, and a valid historical-key record reused without a new
provider write or current signing. Initial focused runs were2 plus19 passed on
the dirty source fix; the post-commit paired run was21 passed in1.13s at a9f03cf.
The test file is committed after execution, not falsely represented as already
present in that earlier source commit. A fresh post-commit test-role receipt
and fix-only reviewer run are recorded separately in the live ledger.

## Explicit limits and unresolved items

No unresolved confirmed BLOCKER/MAJOR remains in the reported review scopes.
The review does not qualify real external-provider trust, separate-service-user
DPAPI access, full startup recovery, shared physical-writer admission, real COM,
production deployment or prohibited artifact builds. Full-candidate GPT-PM
review of the exact final commit remains necessary before push/PR/merge. The
earlier audit-only approval is inapplicable to application consolidation.

An initial database-review invocation used an inaccessible Bash environment;
no SQL finding was inferred from it. Host `git show` with an explicit Windows
workdir succeeded and the reviewer completed the actual source inspection.
