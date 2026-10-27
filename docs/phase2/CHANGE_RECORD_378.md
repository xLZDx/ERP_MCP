# Change Record 378 - design draft for the COM CREATE_DRAFT executor

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session. Documentation only.
- Adds `docs/phase2/S14_COM_DRAFT_EXECUTOR_DESIGN_2026-10-27.md`. No code, test or database change.

## What it records

- A repository check (FACT): there is no code that performs the COM calls for a draft and no production binding set; everything
  upstream (payload contract, bindings, closed vocabularies, STA lane, digest-only manifests) exists.
- A proposed executor with one responsibility, a clone-only qualification plan, and five open design decisions, of which the
  reference format of the five payload references is the one that blocks code: the payload carries opaque identity text and the
  contract does not say how it maps to a 1C element. Recommendation: resolve by unique identifier, refuse unless exactly one existing
  element of the expected catalog is found.

## Not established

- UNKNOWN: the reference format actually used by the gateway that produced the payloads; the base user for the clone lane.
  NOT_RUN: any code, any test, any review of the design.
