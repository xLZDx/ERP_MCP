# COM bridge and parity harness runbook (ADR-0008)

The COM bridge is a separate, local, read-only process on the Windows host that holds the 1C platform. The gateway
never loads COM; it only calls the bridge over loopback HTTP. The bridge is used only when the gateway routes a
balance-by-analytics request to COM from persisted evidence (OData proven unsupported). It is never an automatic
fallback of an OData failure.

## Layout

- Bridge package: `onec_com_bridge/` (top-level, outside `src`, not packaged into the gateway image, not imported by
  the gateway). Start it with `python -m onec_com_bridge --config <file>` using an interpreter that has `pywin32`
  (the gateway dependency set deliberately does not).
- Gateway client: `src/business_ai_gateway/adapters/onec/com_bridge_client.py`.
- Parity harness: `scripts/real1c/parity_analytics.py` (offline logic only).

## Configuration file (JSON, strict: unknown keys are rejected)

```json
{
  "listen_host": "127.0.0.1",
  "listen_port": 8765,
  "token_file": "C:\\bridge\\token.txt",
  "call_timeout_seconds": 30,
  "bindings": [
    {
      "binding_id": "example-binding",
      "version": 1,
      "source_id": "example-source",
      "base_path": "C:\\bases\\example_clone",
      "reader_user": "example_reader",
      "reader_secret_file": "C:\\bridge\\example_reader.dpapi",
      "allowed_company_refs": ["00000000-0000-0000-0000-000000000000"],
      "clone_identity": "example-clone",
      "metadata_fingerprint": "<64 lowercase hex>"
    }
  ]
}
```

- `listen_host` must be a loopback address (`127.0.0.1`, `::1`, `localhost`); anything else fails at startup.
- `token_file`: one line, at least 32 characters, no whitespace. The gateway holds the same token as a secret.
- `reader_secret_file`: a DPAPI (CurrentUser) blob of the reader password, created by the operator under the account
  that runs the bridge. Place config, token and blob outside Git. The bridge never returns or logs them.
- `base_path`: absolute path of the FILE infobase directory. `reader_user` is the only identity ever used.
- `allowed_company_refs`: lowercase GUIDs of the companies this binding may answer for.
- `metadata_fingerprint`: attested by the operator (computed and approved when the binding is confirmed). If it is
  absent the bridge answers `COM_UNAVAILABLE` for balance calls, because the response contract carries it.
  The bridge does not recompute it.

## Relation to a gateway binding (ADR-0008 section 6)

The gateway binding (approved server-side) and the bridge binding table must agree on `binding_id`, `version` and
`source_id`; the bridge refuses any request that does not match its own table exactly (`COM_BINDING_MISMATCH`).
Changing the source base URL, credential identity, configuration or metadata fingerprint invalidates the gateway
binding until re-approval; change `version` in both places together. The caller can never supply a path, secret
reference, user, route or query text: the request has exactly the fields of the ADR wire contract.

## End-to-end check and what it showed (2026-10-07)

The public tool was run end to end on the disposable probe clone, read-only: tool -> `OneCAdapter` -> real OData sidecar
-> GET/HEAD-only lane proxy -> real Apache publication (OData leg), and tool -> `ComBridgeClient` -> real bridge process
-> real COM (COM leg; the OData capability was forced to UNSUPPORTED because the real base answers AVAILABLE, so this leg
proves the wiring, not the route decision). Registry and audit were the test fakes; the mappings were built from live keys.

| Mapping | Route | Rows | Analytics returned |
|---|---|---|---|
| accounts 521.* | odata and com | 15 and 15 | counterparty, contract |
| account 211.1 | odata and com | 6 and 6 | item, warehouse |

Findings that shape operations:

- **One mapping per account family.** Accounts with different analytics layouts must not share a mapping that sets
  `expected_type`: a mapping of 521 and 211 together correctly failed closed (`SOURCE_RESPONSE_INVALID`) on the first 211
  row. Create one confirmed profile per family (counterparties, items and warehouses, ...).
- **The COM route needs a known platform version.** `configuration_fingerprint` is built from the platform version and the
  adapter profile. The real publication does not report a version by itself, so the registered source must carry
  `platform_version_hint`; without it a binding cannot be created (`COM_BINDING_CONFIGURATION_UNKNOWN`).
- **The sidecar allow-list is `host:port`.** `ONEC_ALLOWED_HOSTS=127.0.0.1` answered 403; `127.0.0.1:<port>` works.
- **No binding file or bridge is configured for any real source yet.** On the real reference base `Balance` is AVAILABLE,
  so the gateway routes to OData; the COM route is exercised only where OData is proven absent and the operator has
  approved a binding.

## Enabling the COM route for one real source (operator procedure)

The COM route is used only for a source whose OData publication is **proven** not to offer `Balance` for the current
metadata fingerprint, and only with a binding that the operator approved. Nothing below is done by the gateway or by a
tool on its own: approval is a manual edit. On the reference base `Balance` is available, so it stays on OData.

1. **Confirm the need.** The capability report of the source must show `Balance` absent for the register
   (`metadata-function-import-absent-or-not-read-only`) at the current metadata fingerprint. If it is `AVAILABLE`, stop.
2. **Give the source a platform version.** Set `platform_version_hint` (for example `8.3.27.2342`) on the registered
   source; without it no binding can be created (`COM_BINDING_CONFIGURATION_UNKNOWN`).
3. **Create a confirmed semantic profile** for `account.balance_by_analytics`, one per account family (counterparties,
   items and warehouses, ...), with the register `AccountingRegister_Хозрасчетный` and company field `Организация_Key`
   (the bridge serves only these; any other mapping answers `CAPABILITY_UNSUPPORTED`).
4. **Prepare the bridge host** (Windows, 1C platform and COM connector installed): a DPAPI blob of the reader password
   created by the operator under the account that runs the bridge, a token file, and the bridge configuration described
   above with `base_path`, `reader_user`, `allowed_company_refs`, `clone_identity` and the attested `metadata_fingerprint`.
   Start it with `python -m onec_com_bridge --config <file>`; it listens on loopback only.
5. **Draft the gateway binding** in a private directory (owner-only, outside Git):
   `python -m scripts.real1c.com_binding_tool draft --out <private dir>/com_bindings.json --source-id ... --binding-id ...
   --version 1 --base-url <source base url> --credential-identity <username secret ref> --clone-identity ...
   --platform-version 8.3.27.2342 --metadata-fingerprint <64 hex> --company <external company guid>`.
   The draft is written with `status: REVOKED`.
6. **Review and approve by hand.** Check every field against the bridge configuration (`binding_id`, `version`,
   `source_id`, `clone_identity`, `metadata_fingerprint`, company list), then change `status` to `APPROVED` yourself.
7. **Pin it.** `python -m scripts.real1c.com_binding_tool pin --file <private dir>/com_bindings.json` prints the sha256.
8. **Configure the gateway:** `BAG_COM_BINDINGS_FILE` (absolute path), `BAG_COM_BINDINGS_SHA256` (the printed digest),
   `BAG_COM_BRIDGE_URL` (loopback URL of the bridge) and `BAG_COM_BRIDGE_TOKEN_SECRET_REF` (secret reference of the
   bridge token). The settings are validated together: a file without a digest, or a URL without a token reference, is
   refused at start.
9. **Verify on a disposable clone first** (parity run above) and keep the printed digest and the approval in the
   decision log. Any change of the source base URL, credential identity, platform version or metadata fingerprint
   invalidates the binding until a new version is approved: change `version` in the bridge configuration and the
   binding file together.

## Behaviour after a timeout, admission and identity

- A call that exceeds `call_timeout_seconds` answers `COM_TIMEOUT`. The query may still run inside 1C, so the binding
  stays poisoned: every request answers `COM_UNAVAILABLE` at once and no second 1C session (licence) is opened until the
  abandoned query returns. Then the next request opens a fresh connection.
- At most two requests per binding are admitted (one running, one waiting). Further requests get `COM_UNAVAILABLE`
  immediately, so a slow binding never occupies the shared thread pool. Retry with back-off.
- A request body is refused on `Content-Length` (64 KiB cap) before it is read; `as_of` must be in 1990-2100.
- Every row carries `company_ref`; the bridge fails closed on a row of another company and the gateway compares it again.
- `clone_identity` and `metadata_fingerprint` are operator attestation. The bridge does not refuse the reference clone
  path itself: confirm when approving a binding that `base_path` is a disposable clone or the intended client base.

## Endpoints

`POST /v1/balance_by_analytics` (bearer), `GET /v1/identity?binding_id=` (bearer; ids, clone identity and
fingerprint only), `GET /healthz` (no auth, no data).

## Failure codes (HTTP status)

| Code | Status | Meaning |
|---|---|---|
| COM_UNAUTHORIZED | 401 | missing or wrong bearer token |
| COM_BAD_REQUEST | 400 | schema violation, unknown field, bad GUID, naive `as_of`, bounds |
| COM_BINDING_MISMATCH | 403 | binding id, version or source id differs from the bridge table |
| COM_COMPANY_DENIED | 403 | company not in the binding's allowed set (no COM call was made) |
| COM_UNAVAILABLE | 503 | cannot open the base as the reader, or fingerprint not attested |
| COM_TIMEOUT | 504 | call exceeded `call_timeout_seconds`; the connection is dropped and reopened next time |
| COM_INTERNAL | 500 | unexpected 1C value (unknown metadata kind, row outside the requested accounts) |

Error bodies contain the code only. Logs carry the binding id and exception class names, never request values,
paths or credentials.

## Running the parity harness

1. Make a dedicated disposable clone; choose an immutable run id.
2. Publish a SEPARATE OData publication whose `default.vrd` `ib="File=...;"` points at that same clone; bind the COM
   bridge to that clone. Neither may be the reference clone.
3. Call `run_parity(context=..., com_base_path=..., reference_path=..., publication_descriptor_path=...,
   odata_fetch=..., com_fetch=..., manifest_path=...)`. The same-database proof runs first and raises
   `ParityRefused` before either fetcher is called when the pair is not the same physical `1Cv8.1CD`.
4. The manifest records run id, clone and publication identity, metadata fingerprints and pre/post fingerprints
   (supplied by the caller) and a label: `parity_proof` only with a passed descriptor proof, otherwise
   `cross_copy_comparison`. It reports counts and sha256 digests only, never values. Changed fingerprints void
   equality.

## Open items

- Production topology and licensing for 30-150 bases (one bridge per host, COM license consumption) are undecided.
- COM-only sources (no OData publication) need a source kind in the registry; out of scope here.
- The as-of instant is passed to 1C as the wall-clock value of the supplied offset time (1C dates are naive).
- Live status (2026-10-07): row reading, GUID conversion, type names and the split amounts were checked on a disposable
  clone; the connector has no `Type()`, so refs are built through `TypeDescription` and `XMLValue`. A parity proof on
  one database (publication descriptor path equal to the COM clone path) matched 21 of 21 canonical rows. The metadata
  fingerprint was not compared live; compare it when the gateway profile for that clone is registered.
