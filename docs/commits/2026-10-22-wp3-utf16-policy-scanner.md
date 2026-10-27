# Change record: scan BOM-marked UTF-16 policy artifacts

Date: 2026-10-22  
Scope: WP3 English-policy scanner encoding handling.

## What changed

- Recognize UTF-16LE/BE only with its exact BOM, reject UTF-32 BOMs, and reject decoded U+0000 characters.
- Decode BOM-marked captures before checking for Cyrillic, while retaining the existing UTF-8-with-optional-BOM path.
- Include the SHA-256 of each violating normalized line alongside its path and line number, without printing source line contents. Allowlist exceptions match the full `(path, line number, normalized-line SHA-256)` tuple; stale checks also require that exact tuple.
- Preserve fail-closed reporting for malformed UTF-16/UTF-8 and NUL-containing unmarked files.
- Reconcile the WP3 plan and inherited backlog with the current registry contract: escape only heading variants exclusive to archive, rescue, or snapshot refs; retain readable current headings.
- Add eight exact line-hash exceptions for reviewed 1C OData metadata and test-datum lines in `adapters/odata-sidecar/server.test.mjs` and two register identifiers in the fixed posting-effect list in `db/phase2/007_change_hardening_a.sql`. Add 168 exact CT14 line-hash exceptions across 21 XML files from the reviewed path-and-line inventory. All unlisted lines remain scanned.

## Why

The existing scanner treated every NUL byte as a binary-file error before checking for a UTF-16 BOM. This made valid BOM-marked text captures unreadable to the policy scan. The first revision still keyed exceptions only by path and line hash, allowing an identical duplicate line to inherit another occurrence's exception. The corrected contract binds the exact line number as well and fails closed on unsupported UTF-32 and decoded NUL.

## Verification and limits

- The prior authorized functional-test-reviewer run found three UTF-16LE-BOM capture files unreadable; their contents were not decoded or emitted.
- A read-only functional-test-reviewer pass confirmed both exception hashes against the tracked blob and classified those lines as test data; no line content was returned.
- This turn inspected the exact newly classified OData fixture and SQL allowed-effect lines; line hashes were calculated in-process and added individually. The classified strings are literal 1C metadata/domain identifiers or reviewed synthetic fixture data, not English prose. No source SQL, XML, or fixture content was changed.
- The functional-test-reviewer ran exactly `.venv\\Scripts\\python.exe scripts/check_english_policy.py` once before this turn's line-hash output enhancement and 178 additional classifications. It exited 1, reporting 1,193 violations, zero stale file exceptions, zero stale line exceptions, and zero unreadable text files across 1,391 tracked files. This is a failing baseline policy result, not a pass or verification of the final output format or updated allowlist.
- The functional-test-reviewer confirmed all 168 exact CT14 line hashes against the tracked XML paths: 13 InformationRegisters files (104 hashes), one language file (1), the writer-role definition (2), Rights.xml (53), one sequence (4), and four session-parameter files (4), across 21 files. The reviewer corrected an earlier count of 14 InformationRegisters to 13; no path is missing. The writer-role definition includes a human-facing caption, so its exception reason names that caption explicitly. No XML source lines were persisted in the record. The review covered only the listed paths and hashes; other paths remain unclassified.
- The returned scanner output was truncated. Visible findings included OData test-fixture lines 436, 438-440, and 484-485; SQL migration `db/phase2/007_change_hardening_a.sql` lines 74-75; and CT14 extension metadata. Findings from the truncated portion and unlisted paths remain unknown.
- SQL, PowerShell, and other unclassified findings have no exception. Sensitive HTML and report paths were not opened. Policy classification and translation remain incomplete; scanner output truncation prevents treating the visible inventory as exhaustive.
- The code diff was manually inspected. The functional-test-reviewer performed the single scanner run above; no other tests, checks, builds, or CI were run in this implementation pass. The occurrence-bound tuple matching, UTF-32 rejection and decoded-NUL behavior are not yet runtime-verified.
- A read-only `code-reviewer` pass found no material defect in the initial scanner diff. GPT-PM request `af9d682d-8299-484d-8420-22bddadcd1aa`, exact initial patch SHA-256 `EA98D27C89680135D36D1B9C95DA2B64E0B57AEF52AAF4EB534341D1E1684E78`, returned REVISE: one MAJOR because the allowlist ignored line numbers and one MINOR for UTF-32/NUL handling. The current code and allowlist were revised to address both; that revised patch has not yet received review. The reviewer also confirmed the addition counts (168 CT14 + 8 OData + 2 SQL = 178). Hashes can still match known low-entropy lines, so they are identifying metadata rather than anonymization.

## Ownership and next step

- Accountable task owner: operator.
- Executor: Codex.
- Next: finish WP3 coding and policy classification from permitted evidence; retain unknown paths as unclassified. Then the functional-test-reviewer must run the scanner after coding is complete, capture the hash-bearing output without truncation, and report complete evidence. Do not add exceptions from path-and-line output alone.
