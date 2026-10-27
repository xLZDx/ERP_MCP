# Change Record 377 - the capacity drill can no longer be pointed at a non-disposable container (GPT-PM M-01)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; code by the coordinator; tests written and run by the functional-test-reviewer agent.
- Changes `scripts/phase2_capacity_drill.py`; adds `tests/phase2/test_s14_capacity_drill_container_resolution.py`.

## Finding (GPT-PM delta gate on e7d8184, MAJOR M-01, accepted)

My change in Change Record 376 let `ERP_PHASE2_TEST_CONTAINER` name any container; the prefix check applied only to automatic
selection. A non-disposable container whose published port and `system_identifier` match the privileged DSN would have qualified
as the disposable cluster. That is a regression from the former fixed-name check.

## Fix

- `_disposable_container` now requires an approved prefix (`DISPOSABLE_PREFIXES`: `r2-s13-dump-`, `erp-s14-digest-`) for both
  paths. An environment name without the prefix is refused before any docker call; a prefixed name must still be the single
  running container, must publish the DSN port, and the `system_identifier` comparison still runs. The variable can only choose
  among disposable containers.

## Tests (agent-written and agent-run, no database, no docker; fake docker callable)

- New file: 17 passed. With `test_g1_capacity_smoke.py`: 18 passed, 5 skipped (the integration tests need
  `ERP_PHASE2_TEST_DSN` and were NOT_RUN in this command).
- They cover: approved container (both prefixes) accepted; no match, two matches without selection, wrong port, docker ps or port
  failure, port-less DSN: refused; an arbitrary name selected through the variable, even when running and publishing the port:
  refused with zero docker calls; an approved container displaced by a variable naming another: refused; a prefix in the middle of
  a name: refused; an unapproved auto-selected container: refused; end to end through `verify_cluster` with injected fakes: matching
  identifier accepted, different identifier refused, unapproved name refused before any exec.

## Not established

- The fake mimics `docker ps --filter name=^...$` matching; real docker matching is not re-verified here. The two earlier DSN-backed
  drill tests ran against the container `erp-s14-digest-wbqurn` before this fix (the name is covered by the approved prefix) and
  were not rerun because the container was stopped. NOT_RUN: GPT-PM re-review of this record.
