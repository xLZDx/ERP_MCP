# Audit tooling final qualification

Source HEAD: ae48e290c779b8b4be1d09f25e48ac7890270d60.
Role: functional-test-reviewer. Exact command: python tests/test_rebaseline_audit_tools.py.
Result: Ran 11 tests in 9.907s; OK; exit0.

Eight inventory contracts cover fixed Git SHA despite moving remote refs, remote-only YAML/CSV/feature coverage, unknown ancestry/cherry errors as null/PARTIAL/exit2, FAILED invalidation, completed manifest/hash linkage and a real isolated temporary Git repository. Three additional tests cover real Windows subprocess contention, kernel-lock release after killing the holder with permanent guard identity preserved, and stale-marker independence. No project refs, services, secrets or application data were modified by fixtures.

Earlier results remain distinct: eight cases passed at 284f2dd; b357eea eleven-case run failed with one Windows pre-lock-read PermissionError; 19bc599 eleven cases passed after removing guard-content reads; ae48e29 publishes IN_PROGRESS before marker writes and is the final tested source. A test-loader import failure occurred before tests and was fixed only in test fixture sys.path. Neither the import failure nor the real contention defect is erased or relabeled as a pass.

Routed code, Python, reliability and silent-failure reviewers reviewed the mechanism and its fix-only rounds. Reliability review used the coordinator's exact source diff after its role shell reads were denied; this limitation is retained. The permanent kernel guard resolves stale-lock unlink races, and start-status ordering resolves the marker-before-invalidation window. No remaining BLOCKER/MAJOR in the final audit-tool delta. One nonblocking diagnostic MINOR remains in INTEGRATION_BACKLOG.md: lock-call OSError summaries can mislabel filesystem errors as contention; the original error remains chained and execution fails.

This qualifies audit tooling only. It does not approve dirty application changes, integration into main, a release, live accounting or production. Working-tree capture remains sequential and historical acceptances remain revision-bound. See CAPTURE_LIMITS.md.

## SHA256 of qualified bytes
- scripts/rebaseline_lock.py: 4c37867105e63d4207c766fc28f60f19d6d8de85d8cdb188253ad5d148a6d8d4
- scripts/rebaseline_inventory.py: 253696343ccef4be9e7a6deb194d31412a2d34694a6e05360559321a684cabe1
- scripts/rebaseline_branch_details.py: aec8a7f7665f8ee1c507eff4b13d5e19cc790d646211b82ad17f2605c240167d
- tests/test_rebaseline_audit_tools.py: 6d5798c9f0673aadc956cff7db1baf6e5234ebde003699549f3393dbf7d30595
