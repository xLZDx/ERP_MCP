# Script evidence security triage — 2026-10-06

Frozen gates: D0/D1/D4/D13–D15/D18. Production remains NO-GO.

Expanded Bandit scan (src/scripts/testbed) initially reported 38 script findings: 32 LOW, 6 MEDIUM,
no HIGH. Do not reinterpret this as 38 confirmed vulnerabilities or suppress the output for green.

Implemented fixes:

- B405/B314, `execute_evidence_tests.py`: shared bounded defusedxml JUnit reader, DTD rejected,
  actual testcase counts/outcomes required; malformed/oversized/missing/failed reports cannot PASS.
  Suite-declared positive totals never manufacture cases; declared negative signals stay blocking.
  Parser/spawn errors are sanitized. Release summary CLI refuses to overwrite an existing artifact.
- B101, `acl_load_drill.py`: authorization-count proof is an explicit runtime guard, not assert.
  A real `python -O` subprocess must still reject mismatch; invalid/bool counts cannot PASS.

Remaining scan: 35 script findings (30 LOW, 5 MEDIUM). Classification, not suppression:

| Finding | Context/control | Evidence | Disposition |
| --- | --- | --- | --- |
| B102 `mutation_negative_pack.py` | Deliberate test-only compilation of own inspected FanoutExecutor; four fixed mutations, exact single-match guard, no model/remote code input | Four baseline oracles PASS; all four mutants killed | Controlled test execution; not a new runtime native-query/COM path |
| B608 `postgres_restore_drill.py` | Own new control-plane PostgreSQL schema; table identifiers must match `[a-z_]+` before quoting/interpolation | Five invalid/injection identifiers rejected before dynamic SQL dispatch | Guarded identifier formatting; no internal 1C SQL |
| B108 restore dump paths | Fixed `/tmp/control-plane.dump` only in newly created UUID-named disposable containers; no existing database/container reused | Actual restore drill retained earlier; source/target fingerprints and runtime role tested | Container-private artifact; not shared host temp or customer backup |
| B108 `validate_prometheus.py` | Docker `/tmp` is a bounded read-only-container tmpfs with noexec/nosuid, network none, capabilities dropped | Pinned promtool actual lint/format/alert tests PASS | Controlled ephemeral container mount |
| LOW B404/B603/B607 | Operator-owned subprocess tools and fixed argv without shell; test paths are trusted repo call sites | Runtime/source-scoped harness tests and current CI | Context review remains explicit; no blanket finding suppression |

Neither this classification nor green scripts closes deployed audit recovery, production security,
native semantics, complete fault/deployment rehearsals or the remaining frozen business scope.
