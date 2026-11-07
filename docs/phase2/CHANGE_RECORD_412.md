# Change Record 412 — show authoritative approval context

## Scope

Sprint `beea27520b33`; focused accessibility and decision-context fix following the review of
`src/erp_mcp_s16/approval_page.py`. This change owns only that page handler and this record.
The contracts and service metadata are coordinated with the S16 core owner; they are not edited
by this page change.

## Finding and rationale

The approval page previously showed the immutable canonical proposal preview and its digest but
did not show the current lifecycle state, current authorization state, explicit proposal version,
proposal creation time, or an approver's readable identity label. An approver therefore lacked
service-authoritative context for deciding whether the displayed proposal was still pending and
which identity was reviewing it. The page now requires service metadata for these facts and
renders them in a semantic definition list before the separately labelled immutable preview.

The current-state values are deliberately rendered outside the canonical preview section. They
are dynamic service context; they are not inserted into, reserialized into, or described as part
of the canonical preview bytes or `preview_digest`. The creation timestamp is supplied by the
service from the stored proposal. The displayed version is the explicit service snapshot version.
The approver is displayed only as the service-provided human label; the handler refuses to render
a decision form when the label is missing, invalid, or equal to the session, principal, or person
identifier.

The service-owned `decision_allowed` result controls whether the page renders either decision
form. If the service indicates that the receipt is already decided or otherwise cannot receive a
decision, the page shows the current state and emits no Approve or Reject form. The handler does
not infer eligibility from request fields or canonical preview content. POST continues to accept
only the one-use decision reference, the decision, and optional typed confirmation; caller body
fields cannot supply or override status, approver identity, creation time, or version.

## Contracts and UI semantics

`DecisionPage` metadata used by this handler:

- `lifecycle_status` and `authorization_status`: current service-owned state labels.
- `snapshot_version`: immutable proposal version selected by the service.
- `created_at`: timezone-aware creation time read from the stored proposal.
- `approver_person_label`: current approver's readable label, with no principal/session ID.
- `decision_allowed`: service authorization to present decision actions for this current receipt.

Invalid or unavailable required metadata fails closed before a decision form is rendered. Native
Approve and Reject forms remain separate; a required typed confirmation applies to the approval
form while rejection remains available without that confirmation. The current-state section has
its own heading and `<dl>` labels, distinct from the canonical preview heading and digest.

## Accessibility barriers and verification

| Barrier before this change | Who/task affected | Criterion | Source fix | Verification still needed |
|---|---|---|---|---|
| An approver could not tell the record's current lifecycle and authorization state before deciding. | Keyboard or screen-reader user reviewing a pending change. | WCAG 1.3.1, Info and Relationships; 2.4.6, Headings and Labels. | A separate headed section presents lifecycle and authorization labels from `DecisionPage` in a semantic definition list before the decision forms. | E2E confirms values and no forms for disallowed state; screen-reader/keyboard review confirms reading order. `NOT_RUN`. |
| The page did not expose an explicit snapshot version, stored proposal creation time, or readable approver identity. | Approver comparing the current proposal and identifying who is reviewing it. | WCAG 1.3.1; 2.4.6. | Service-provided metadata is presented as labelled terms; creation time is a timezone-aware `<time>` value and approver identity is a human-readable label. | Keyboard/screen-reader review confirms labels and values; 200–400% zoom/reflow review checks layout. `NOT_RUN`. |
| Review context could be mistaken as part of the immutable content covered by the preview digest. | Approver judging the exact bytes to which the approval is bound. | WCAG 1.3.1, Info and Relationships. | A separate “Current record status” section precedes “Canonical preview”; the digest is shown only with the exact escaped canonical bytes. | Assistive-technology review confirms the section boundary and digest association. `NOT_RUN`. |

## Files changed

| File | Change |
|---|---|
| `src/erp_mcp_s16/approval_page.py` | Validates and renders current service state, version, creation time, and approver label separately from canonical preview; omits decision forms when service disallows a decision or metadata is invalid. |
| `docs/phase2/CHANGE_RECORD_412.md` | Records the accessibility finding, contract boundary, UI semantics, and verification state. |

## Evidence state

- Source implementation: completed in the two files above, integrated against the core-owned
  `DecisionPage` metadata fields listed in this record.
- Tests, checks, lint, build, browser, keyboard, screen-reader, and accessibility-tool verification:
  `NOT_RUN` by task instruction. No runtime or accessibility pass is claimed.
- The E2E owner should verify lifecycle and authorization labels, the explicit version and proposal
  creation time, the approver label, absence of decision forms for a decided receipt, and that
  request-body fields cannot override any service metadata. A separate keyboard/screen-reader and
  responsive reflow review remains required before calling the UI manually or runtime proven.

## Acceptance matrix

| Item | State | Evidence / remaining acceptance | Dependency and owner | Next action |
|---|---|---|---|---|
| Service-authoritative page context | Implemented in source; runtime `NOT_RUN` | Page consumes explicit `DecisionPage` fields for lifecycle, authorization, version, creation time and approver label. E2E owner must verify rendered values against service output. | Core owns API values; E2E runner owns runtime evidence. | E2E runner asserts metadata fidelity after all sprint code is complete. |
| No decision form for decided receipt | Implemented in source; runtime `NOT_RUN` | Both forms render only when service `decision_allowed` is true; E2E owner must exercise decided/current-state refusal. | Core owns eligibility decision; E2E runner owns runtime evidence. | Verify approved/rejected/already-decided states produce no decision form. |
| Identity privacy and availability | Implemented in source; runtime `NOT_RUN` | Missing/invalid label blocks decision forms; labels matching identifiers are rejected. E2E/security review must check response markup for session/principal identifiers. | Codex owns implementation; security reviewer and E2E runner own independent evidence. | Inspect sanitized responses in assigned review and E2E cases. |
| UI accessibility | Source semantics/style updated; manual review `NOT_RUN` | Definition-list labels and separate headings are present; no browser, keyboard, screen-reader, zoom, or reflow evidence exists. | Codex coordinates; a11y reviewer owns independent review. | Run keyboard, screen-reader, and responsive review after coding is complete. |

No test, browser, build, or runtime command was run for this change.
