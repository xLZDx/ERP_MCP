"""Fixture support for S12-APPROVAL-2 (db/phase2/009_approval_digest_2.sql) in the PostgreSQL ledger tests.

Since 009 the ledger approves only the digest of a canonical text that the trusted service stored for one issued
nonce (``change_ledger.store_approval_text``), and the stored text must equal the ledger's own state, including
``payload_digest == sha256(canonical({payload, target_version}))``. The legacy fixtures propose many changes with one
constant ``DIGEST`` and target version ``v1``; ``DIGEST`` is therefore the REAL digest of ``FIXTURE_PAYLOAD`` with
target version ``v1`` (``FIXTURE_DIGEST``), and ``ensure_envelope`` builds and stores the text for the newest issued
nonce of a change, exactly as the production service would, then returns the ledger-computed digest.
"""
import json
from decimal import Decimal

from business_ai_gateway.phase2.change import canonical_json, sha256_hex

FIXTURE_PAYLOAD = {
    "organization_ref": "org-1", "counterparty_ref": "cp-1", "contract_ref": "ct-1",
    "supplier_document_number": "N-1", "supplier_document_date": "2026-10-01", "currency": "EUR",
    "lines": [{"item_ref": "it-1", "quantity": "2", "price": "10.5", "vat_rate_code": "VAT20", "amount": "21",
               "vat_amount": "3.5"}],
    "comment": "fixture", "duplicate_override": None, "expected_target_version": None,
}
FIXTURE_TARGET_VERSION = "v1"
FIXTURE_DIGEST = sha256_hex(canonical_json({"payload": FIXTURE_PAYLOAD, "target_version": FIXTURE_TARGET_VERSION}))
FIXTURE_NULL_DIGEST = sha256_hex(canonical_json({"payload": {}, "target_version": FIXTURE_TARGET_VERSION}))
FIXTURE_PREVIEW = "c" * 64


def decimal_text(value):
    d = Decimal(str(value))
    return format(d.normalize(), "f") if d != 0 else "0"


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def fixture_digest_for(kind):
    """The payload digest the legacy fixtures propose with: drafts carry FIXTURE_PAYLOAD, every other kind none."""
    return FIXTURE_DIGEST if kind in ("CREATE_DRAFT", "UPDATE_DRAFT") else FIXTURE_NULL_DIGEST


_DEFAULT = object()


async def envelope_dict(conn, cid, nonce, *, payload=_DEFAULT, preview=FIXTURE_PREVIEW,
                        business_state_digest=None):
    """The closed 20-key envelope of the spec, built from the ledger's stored change (superuser read)."""
    rec = await conn.fetchrow("SELECT * FROM change_ledger.records WHERE change_id=$1", cid)
    if payload is _DEFAULT:    # 009 payload rule: drafts carry an object, POST / UNPOST carry JSON null
        payload = FIXTURE_PAYLOAD if rec["kind"] in ("CREATE_DRAFT", "UPDATE_DRAFT") else None
    cb = await conn.fetchrow("SELECT * FROM change_ledger.change_budget WHERE change_id=$1", cid)
    bk = await conn.fetchrow("SELECT * FROM change_ledger.business_keys WHERE change_id=$1", cid)
    effects = _json(await conn.fetchval("SELECT change_ledger.allowed_effects($1)", rec["kind"]))
    deps = sorted([k, v] for k, v in _json(rec["epoch_dependencies"]).items() if not k.startswith("principal:"))
    return {
        "digest_version": "S12-APPROVAL-2", "change_id": str(cid), "kind": rec["kind"],
        "scope": {"tenant": rec["tenant_id"], "company": rec["company_id"], "organization": rec["organization_ref"],
                  "base_fingerprint": rec["base_fingerprint"]},
        "payload": payload, "payload_digest": rec["payload_digest"], "target_ref": rec["target_ref"],
        "target_version": rec["target_version"], "business_state_digest": business_state_digest,
        "parent_change_id": None if rec["parent_change_id"] is None else str(rec["parent_change_id"]),
        "repair_for": None if rec["repair_for"] is None else str(rec["repair_for"]),
        "declared_target_class": rec["declared_target_class"], "allowed_effects": effects,
        "budget": None if cb is None else {
            "grant_id": str(cb["grant_id"]), "currency": cb["currency"], "amount": decimal_text(cb["amount"]),
            "counts_create_update": cb["counts_create_update"], "counts_post": cb["counts_post"]},
        "duplicate_override": None if bk is None or bk["override_of"] is None else {
            "duplicate_of_change_or_ref": bk["override_of"], "justification": bk["override_justification"]},
        "rule_table_version": "S11-RULES-2026-10-12", "epoch_dependencies": deps, "preview_digest": preview,
        "approval_nonce": nonce, "expires_at": rec["expires_at"],
    }


async def ensure_envelope(led, cid, requester=None):
    """Store the canonical text for the newest ISSUED nonce of `cid` (if none is stored for it) and return the digest.

    Returns the ledger's current ``approval_digest`` (None when no nonce was issued yet and nothing is stored)."""
    conn = led.conn
    nonce = await conn.fetchval(
        "SELECT nonce FROM change_ledger.approval_nonces WHERE change_id=$1 AND state='ISSUED' "
        "ORDER BY issued_at DESC LIMIT 1", cid)
    if nonce is not None and not await conn.fetchval(
            "SELECT 1 FROM change_ledger.approval_envelopes WHERE change_id=$1 AND approval_nonce=$2", cid, nonce):
        who = requester or await conn.fetchval("SELECT requester FROM change_ledger.records WHERE change_id=$1", cid)
        t, c = await conn.fetchrow("SELECT tenant_id, company_id FROM change_ledger.records WHERE change_id=$1", cid)
        text = canonical_json(await envelope_dict(conn, cid, nonce))
        await led.call(who, "store_approval_text", cid, nonce, text, t=t, c=c)
    return await conn.fetchval("SELECT change_ledger.approval_digest($1)", cid)
