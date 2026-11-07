# Change Record 406 - S16 library integration and source-bound period evidence

Sprint: beea27520b33

## Scope and decisions

This coherent source commit combines the S16 core and transport handoffs described
in CR-404 and CR-405, plus tightening of CR-403's period evidence binding. The
implementation is isolated under `src/erp_mcp_s16/`; it registers no gateway route,
starts no listener, imports no private writer, and enables no production binding.
The period binding now carries tenant, company, source, organization and immutable
base fingerprint; the configured reader consumer preserves independent target
authentication guards and cannot qualify a nonexistent real source operation.

The S16 design decisions are 15-minute idle and absolute approver-session limits,
5-minute internal approval nonces, registry-owned confirmation thresholds and a
script-free server-rendered preview. Displayed canonical bytes have their own
preview digest; the internal S12 approval envelope binds that digest and nonce.
Only a session-bound one-use opaque decision reference is returned in the form.
GET may create transient form binding state but cannot approve, consume an approval
nonce, alter business lifecycle or apply. The scoped Secure cookie uses a
`__Secure-` prefix; `__Host-` requires a root path incompatible with scoped cookies.

## Paths and contracts

- `src/erp_mcp_s16/contracts.py`, `core.py`, `services.py`, `registries.py`,
  `fakes.py`, `__init__.py`: typed fake-backed decision and dependency boundaries.
- `src/erp_mcp_s16/tools.py`, `approval_page.py`, `ingress.py`: explicit five-tool
  surface, immutable preview/form handling and inert positively authenticated
  private ASGI factory.
- `src/business_ai_gateway/phase2/change/observations.py`: stricter source binding
  and actual configured-reader-to-BeginApplyEvidence consumer.
- `docs/phase2/CHANGE_RECORD_403.md`, `CHANGE_RECORD_404.md`,
  `CHANGE_RECORD_405.md`: detailed source contracts, decisions and limitations.

## Verification and provenance

Source changes were produced in this turn by actual implementation-engineer agents.
No test/check/build/lint, migration application or live/COM operation ran during
coding. Implementation is not runtime qualification. All tests follow only after
all source handoffs are complete; functional-test-reviewer and e2e-runner own them.
The pre-existing `ct14_measure.py` modification and framework state/view are not
included in the source commit. No push or approval is part of this commit.

S12/S13/S15 acceptance and real period qualification remain unproven; the writer
remains unqualified and disabled by the unchanged runtime boundary. No release GO
is established by adding this library. Registry regeneration records a Git-ref
snapshot rather than proving current-head code or tests.
