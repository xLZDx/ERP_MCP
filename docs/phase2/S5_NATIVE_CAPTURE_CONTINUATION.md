# S5 native capture continuation

Status: design candidate for review. The four bounded acceptances in `SPRINT_S5_PLAN.md` are historical evidence. This continuation takes the two open stories in plan order. Canonical TC061–TC066 remain `NOT_RUN` until the applicable native execution is evidenced.

## R2-US-021: manual baseline (REQ13, REQ16, REQ19)

Accept an original artifact plus a structured manifest. The expected tenant, source, database identity and company come from trusted capture context. The manifest carries claims about the report, variant, period, filters, columns, totals and row-limit state. Record declared values as claims. Compute byte count and SHA-256 from the supplied original and bind them to its immutable version and media type. No caller flag, file path, or asserted origin establishes completeness or authenticity.

- **TC061:** With the exact scope, required manifest fields and permitted original bytes, create or recover a scoped immutable version. The intake result is `UNATTESTED`, with completeness `UNVERIFIED`; native origin and acceptance require separate evidence.
- **TC062:** A partial screenshot, missing headers/settings/totals, known truncation, or wrong source/company cannot yield a complete baseline. Reject incomplete or mismatched inputs. Supplemental screenshots may remain separate private evidence. An uploader's claimed completion never advances `UNVERIFIED`.
- **TC063:** Reject candidate bytes whose digest differs from the stored original digest before parsing or returning a baseline. Changed bytes require a distinct intake and version. The offline test uses a permitted fixture type. Verify the native XLSX substitution case only once an original-byte storage adapter supports XLSX without conversion. The parser remains values-only and bounded.

The first adapter runs offline with synthetic CSV/PDF originals and the existing in-memory vault. That vault does not accept XLSX or MXL. Reject those types until a separate immutable original-byte storage contract is reviewed. Never convert or relabel a native export to fit the allow-list.

Publish an intake record for the exact trusted tenant, source, database, company and report context. It binds a private vault reference to the store's version, digest, byte count and media type. The public intake result uses a separate opaque baseline ID. Tenant/source ACLs in the vault do not provide company isolation. The intake layer reauthorizes the full scope before each baseline read or byte verification; no raw vault reference or broad store credential is returned. The vault principal remains test-only. Identical intake may reuse a stored vault version. Publish no baseline record unless the artifact exists and the store read-back scope, metadata and bytes all match. After a failed response, recover only the exact baseline or return failure. The first adapter avoids user-supplied filesystem paths and any 1C call.

## R2-US-022: controlled UI capture (REQ13, REQ15)

Reuse the manual intake contract. Introduce an offline executor interface for a versioned recipe on an explicitly selected disposable, read-only 1C copy. An exact observed database/configuration and company must match the trusted recipe context before a report action. Before dispatch, require a capture permit and a read-only boundary decision for every operation and probe. Unknown or uncatalogued operations deny; the reference registry is illustrative and does not qualify runtime. Derive the permit digest from canonical recipe hash and version, database and configuration identity, company, and all normalized parameters. The existing permit API does not calculate or verify that digest. The adapter can perform only known actions on known states, and export only a newly generated artifact tied to that attempt.

- **TC064:** Compare manual and automated artifacts for the same stable database, configuration, report object, variant, parameters, columns, totals and normalized rows. Synthetic equivalence verifies the comparator only. A real paired capture establishes native equivalence separately.
- **TC065:** A wrong, missing, or unverified database identity or company refuses capture before generating or publishing any artifact.
- **TC066:** An unrecognized selector, modal dialog, timeout, or stale export candidate refuses capture without guessed actions. A retry starts from a verified idle state with a new attempt identity. Concurrent capture attempts may not share a mutable UI session or output path. A crash leaves no complete evidence without a scoped, validated fresh artifact.

The offline state machine and comparator can proceed after the manual contract is available. Native qualification requires a selected read-only account, a supported UI automation mechanism, a stable qualified copy and recipe, and independent manual evidence. Keep any unmet dependency in the backlog. Automatic production capture remains off.
