# Change record 178 — private writer composition and outcome evidence

## Scope and reason

The S13 coordinator, PostgreSQL admission adapter, host-wide Windows authority mutex, and evidence
interfaces existed as separate source components, but the private service had no composition root
or concrete outcome-bundle registrar adapter. The accepted design requires a separate private
process and explicitly excludes writer methods from the public MCP gateway. This change adds the
dependency-wiring boundary and a typed provider that delegates trust to the existing registrar.

## Changes made in this turn

- Added `src/erp_mcp_private_writer/runtime_composition.py` with
  `compose_private_writer_runtime`, which assembles `PostgresAdmissionStore`,
  `WindowsServingAuthorityMutex`, and `PrivateWriterService` from caller-provided dependencies.
- The factory requires a Windows host, a PostgreSQL pool, an injected writer port, the service SID,
  and all four evidence/barrier verification interfaces. It refuses missing methods and the
  `NonOperationalWritePort` skeleton.
- Added an immutable `PrivateWriterRuntime` handle that exposes the coordinator and explicit
  closure of its owned mutex handle, and exported the composition API through the private-writer
  package. The raw store is not exposed by the runtime handle.
- Added `PostgresOutcomeEvidenceProvider`. Its injected source only locates original signed
  envelopes; the provider requires exact causal bundle shapes, confirms the supplied receipt
  reference, and delegates trust-snapshot signature verification, immutable-attempt binding,
  authenticated build provenance, and durable registration to the existing registrar.
- Success requires exactly one dispatch receipt, one outcome record, and one completion proof;
  conditional-conflict recovery requires those records plus the post-completion challenge and
  nonce-bound read attestation, with `OutcomeEvidenceV3`. Both paths require an `ENTERED`, returned
  receipt of the exact result class and `WRITER_CALL_RETURNED` completion proof. Loading and
  registration share a bounded five-second provider deadline.
- Exposed one registrar reference-derivation method so pre-registration receipt-reference matching
  uses the exact same record-type/digest rule as persistence.
- Added typed `T16ResolutionPreparation` output to the coordinator. A validated conditional-conflict
  recovery now retains the exact evidence-reference tuple instead of a boolean-only pending marker.
- Added `T16RecoveryCoordinator` to sequence proof preparation, the independently signed operator /
  witness T16 gate, exact checkpoint/read-back and hold release, then the separate S13
  `record_recovered_terminal` transition that clears the physical-base slot. It validates event,
  checkpoint sequence, result class, and complete released-hold IDs before advancing S13; replay
  uses the same cosign/evidence tuple and never invokes COM. An ambiguous final response is resolved
  by the authoritative private-writer lookup; a terminal call is returned without attempting a
  second terminal transition.
- Construction does not load credentials, connect to PostgreSQL or 1C, start COM, claim a serving
  epoch, or create a listener. Startup recovery remains an explicit caller action. The factory
  validates host/base identity shape downstream but cannot establish the provenance of the supplied
  host ID or base fingerprint.

## Decisions and boundaries

- The factory is private-writer package code and is not registered with the public MCP server.
- The checkpoint sink, authenticated host/base identity providers, operational `OneCWritePort`,
  signed-envelope locator, trust snapshot and build-attestation services, listener authentication/ACL,
  and process supervision remain external dependencies. The provider verifies records only through
  the injected project registrar and does not turn its locator into a trust authority.
- The T16 coordinator does not create the operator or witness signatures and does not install the
  candidate SQL or enable its ACL. The S13 terminal transition remains gated by the same exact
  immutable evidence references and event ID returned after the checkpoint gate.
- The runtime remains candidate-only. Constructing the object is not permission to start serving;
  startup recovery must complete before a later listener can be enabled.

## Review and verification state

- Manually inspected the coordinator constructor, its startup recovery contract, the admission
  adapter's dedicated database-role assertion, the Windows mutex ownership lifecycle, and the S13
  private-process boundary before implementation.
- No tests, checks, parser, build, database operation, migration, COM operation, service restart,
  listener startup, staging, commit, or push was run in this turn. Runtime and Windows behavior are
  `NOT_RUN`; the supplied host/base identity provenance and effective grants remain
  `NOT_VERIFIED`.
- Accountable task owner: operator. Executor: Codex. Technical owner of the Ivan host boundary:
  Ivan stack (`ERP_MCP_Ivan_Stack`), as recorded by the existing project design; this source change
  does not establish an owner for the missing authentication/evidence providers.
