# S14 COM payload-value binding design

## Goal and current behavior

`com_manifest.py` proves that each supported business leaf in an approved `DraftPayload` maps once
to a reviewed 1C destination, but `MappedPropertyAssignment` retains only a value digest. A future
COM port also needs the original value to invoke the mapped property setter. `OneCWritePort` remains
only a protocol; there is no concrete operational COM adapter (`WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md:472-474`).

## Non-goals

This change will not invent the missing `818HA_p2diff` property crosswalk, authenticate its source,
perform a write, alter runtime composition, or enable an operational writer. The separate
`testlane/onec_extension/scripts/ct14_metadata_inventory_readonly.py` utility is clone-guarded and
enumerates only document and tabular-section metadata names; it must not read business rows or infer
the mapping. `PreparedComManifest` remains a value-minimized digest record.

## Design and decision

Keep the existing digest-only manifest and add a separate ephemeral value-binding result derived
from the exact `DraftPayload` with no CREATE_DRAFT target-version preimage, reviewed
`PayloadPropertyBinding` tuple, and approved payload digest.
Require the same one-line shape and exact one-to-one business-leaf coverage as the manifest builder;
exclude authorization-only duplicate-override and target-version inputs; reject a digest mismatch
before returning any values. Each ephemeral result carries destination, assignment kind, value type,
the original canonical value, and its canonical digest; the value is excluded from `repr` and
equality. Factor coverage/value selection so the digest-only and ephemeral APIs use the same
validated mapping logic.

`ComValueAssignment` accepts only immutable JSON scalar leaves (`str`, `bool`, `int`, or `None`).
The qualified `DraftPayload` currently supplies strings; rejecting direct container construction
prevents a mutable list or mapping from diverging from the digest captured at construction.

Alternative: place original values on `MappedPropertyAssignment`. This is simpler but mixes secret-
and business-value material into the durable-manifest type and its ordinary representation. The
separate ephemeral type preserves the current digest-only contract and lets the concrete adapter
consume values only inside its COM worker call.

## Failure modes and boundaries

Invalid payload type/shape, an external or embedded CREATE_DRAFT target preimage, unsupported canonical value, duplicate source or destination, missing or
extra business leaf, and approved-digest mismatch fail closed before COM. The helper does not prove
that the mapping matches live 1C metadata or that a caller will not log values. Production logging,
receipt and checkpoint formats must consume only digests; live use remains disabled without the
reviewed clone crosswalk and the complete pre-entry authority/CAS/evidence adapter.

## Rollout, rollback and verification plan

The new API is inert and is not composed into `PrivateWriterService`. Removing the helper and its
change record is the rollback; there is no database or deployment change. After coding closes, the
functional-test owner should prove exact leaf-to-value correspondence, canonical digest equality,
duplicate/omission/extra/mismatch refusal, authorization-only input exclusion, and that the existing
manifest still contains digests only. No COM call is needed for those cases. E2E COM-write scenarios
remain gated on the exact disposable-clone crosswalk and complete operational port.

## Unknowns and ownership

The Ivan stack owns its test-host boundary; the operator is accountable and Codex executes this
local source change. The exact 1C destination/type crosswalk and current clone identity remain
`NOT_VERIFIED`; the stack owner must provide those through an authorized, read-only clone evidence
path before operation. Functional/E2E agents own the later tests.

**2026-10-26 read-only COM metadata prerequisite recheck:** the local metadata-only inventory for
the guarded clone returned `CT14_METADATA_COM_CONNECT_FAILED` with HRESULT `0x80020009`, automation
code `0x80004005`, and classifier `LICENSE`; it emitted no metadata or business rows. A strict-host-key
SSH `-TestOnly` call to `D:\1c\mcp\store-onec-admin.ps1` targeting Ivan's `D:\1c\env\bases\818HA_p2diff`
also returned `COM connect ok: False` and the sanitized message `License not found. Software
protection key or acquired software license not found!`. No credentials were emitted, no 1C method
was called beyond connection/current-user inspection, and no service or database was restarted.
The live destination/type crosswalk therefore remains `NOT_VERIFIED`; the operator owns restoring
or identifying the usable licensed client on the authorized host, while Codex continues independent
S13 source closure.
