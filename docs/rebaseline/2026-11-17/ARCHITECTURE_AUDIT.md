# Architecture/design audit — 2026-11-17

Read-only architect review of dirty checkout HEAD 240070b. No test, build,
runtime, SQL or COM operation was performed. Findings describe current files,
not a deployed artifact. All-branch integration is covered separately.

## Inspected boundaries

Read AGENTS, CLAUDE, DOCUMENT_INDEX, ARCHITECTURE, INTEGRATION, DoD, scope freeze,
ADR-0001/0002/0009, S10 handoff and gate manifest. Traced gateway app/runtime/
server/registry/principal/settings, private-writer ingress/composition/service,
S16 entrypoints and setuptools package discovery.

| Mechanism | Actual source | Result and limit |
|---|---|---|
| Gateway composition | app.py:15-18; runtime.py:22-130 | Settings, DB, registry, policy, audit and read adapters composed |
| Read authorization | server.py:208-278; registry.py:48-113 | Source/grant/capability/rate/audit before adapter execution; static only |
| Public tool boundary | server.py:84-87,307-2407 | Shared read-only annotations; public app/runtime do not import writer/S16 |
| Disposable writer | private_ingress.py:261-406 | Bounded authenticated dispatch/lookup; not a deployed qualification |
| Independent authority | runtime_composition.py:159-166 | Missing independent build authority refused |
| Production artifacts | pyproject.toml:43-44 | Unrestricted src discovery; see A-01 |

## Findings

### A-01 — MAJOR: production package inventory is not isolated

ADR-0009-private-test-writer.md:52-56 requires the private service to be absent
from production process/tool/package inventory. pyproject.toml:43-44 discovers
all packages under src without an include/exclude restriction. The tree contains
erp_mcp_private_writer and erp_mcp_s16 packages. No public entrypoint imports them,
which reduces reachability but does not meet the package-inventory requirement.

Required: explicit production package allowlist or separate private distributions
with reviewed shared contracts; verify resulting artifact inventory. Artifact
build was NOT_RUN. This is not proof of a reachable production write operation.

### A-02 — MINOR: historical S10 architecture is presented as current

S10_RELEASE_HANDOFF.md:22-35,163-169 describes a separate Release 2 repository
and unwired reference modules. CLAUDE.md:3-7 records project unification on
2026-10-20. Retain S10 as historical evidence, label its time boundary, and point
to the current architecture/rebaseline. Do not reset integrated work from S10.

### A-03 — MINOR: mode metadata overstates environment

settings.py:29 defaults environment to development; server.py:315 always returns
mode=1c-production. The mode label can mislead status consumers. Specify separate
deployment/environment semantics before changing compatibility-sensitive output;
then verify development/test/production results with named tests. NOT_RUN here.

## Reconciled architecture

The project is one repository containing distinct deployment boundaries:
public read-only gateway/control plane, living-model/ledger/reconciliation,
isolated disposable writer, and S16 independent approval surface. Code existence,
bounded task acceptance, installed grants, provider authenticity and real COM
qualification are different states. Gate manifest NO_GO and S13/S16 NOT_STARTED
must not be interpreted as absence of their implementation packages.

## Not established by this review

Full line-by-line review of all branches, full security/database/reliability
review, effective grants/schema, signing-key custody, live IdP/browser behavior,
deployed process inventory, physical writer, mutex, recovery and accounting
correctness. These are explicit qualification tasks, not inferred passes.

## Deeper implementation audit — COM, anchors and recovery

The draft claim that COM implementation is absent is stale when applied to all
code. windows_com_lane.py:32-134 implements lazy x64 V83.COMConnector activation,
current-user and pinned-base checks. com_sta_lane.py:194-280,297-385 owns COM on
a dedicated STA worker, serializes one in-flight call and drains before closing.
com_draft_executor.py:397 onward creates an unposted document, writes and performs
fresh-object read-back of markers/fields. Its header says fake-COM tested and not
wired into the operational runtime. These implementations must be preserved.

S12_S13_COM_CLONE_REPORT_2026-10-28.md:1-16,33-39 records historical real draft
execution on a disposable clone with rollback and 16 historical passing tests.
E4/E14/E23/E25/E41 remain PARTIAL; this is neither PostgreSQL integration nor
real POST/UNPOST qualification. The missing part is a concrete operational
OneCWritePort composing the executor/STA/approved destinations and all required
verify/lookup/quiesce/create/post/unpost/drain methods (runtime_composition.py:140-143).

The dev_anchor_service.py implements a separate dev HTTP service with SQLite
append-only triggers, event history and signed nonce/scope latestness evidence.
It explicitly disclaims external immutability and host rollback protection.
DevHttpCheckpointSink is TEST/is_test_double; rollback memory is process-local.
This is implemented dev infrastructure, not an absent anchor and not production
trust. DispatchGate requires a REAL sink and non-test authority. LifecycleStatus
contains only NOT_READY; completed diagnostics still return SHARED_FENCE_UNAVAILABLE.
T16RecoveryCoordinator validates recovery/event/checkpoint outputs and records
terminal resolution but does not invoke COM. These deliberate qualification
boundaries explain why implemented code does not imply READY/admission.
