"""Phase 2 sprint S12: the typed ``ChangeProposal`` of section 3 (purchase receipt only), canonical JSON and digests.

Offline and pure (stdlib only). ``parse_proposal`` is the only way caller input becomes a proposal: unknown keys
are refused (I2), numeric fields are exact decimal strings (never floats), identity fields are never accepted from
the caller (they come from the server-side ``ProposalContext``), and ``allowed_effects`` is derived from the
operation rule table constant ``OPERATION_RULES`` - a caller-supplied ``allowed_effects`` anywhere in the input is
refused with ``SCHEMA_INVALID``. ``payload_digest`` is the SHA-256 of the canonical payload plus the target version
(CT2); ``approval_digest`` covers the extended set of section 3. Refusals carry a code only, never input content.
Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Final

from .errors import ErrorCode, Refusal
from .types import ChangeKind, Scope, is_aware_datetime, is_identity_text

__all__ = [
    "ChangeProposal", "DraftPayload", "DuplicateOverride", "Line", "MEASURED_SHAPE_MAX_LINES", "OPERATION_RULES",
    "ProposalContext", "RULE_TABLE_VERSION", "APPROVAL_DIGEST_VERSION", "approval_canonical_text", "approval_digest",
    "canonical_json", "derive_allowed_effects", "digest_of_canonical_text",
    "payload_digest", "payload_to_dict", "parse_proposal", "sha256_hex",
]

RULE_TABLE_VERSION: Final = "S11-RULES-2026-10-12"
MEASURED_SHAPE_MAX_LINES: Final = 1  # the single measured receipt shape; anything wider is SHAPE_NOT_QUALIFIED
MAX_LINES_SCHEMA: Final = 100
MAX_COMMENT_CHARS: Final = 2000
MAX_REASON_CHARS: Final = 500
MAX_REF_CHARS: Final = 128
_ACCOUNTING_REGISTER: Final = "Хозрасчетный"
_VAT_ACCUMULATION_REGISTER: Final = (
    "НДСПредъявленный")


@dataclass(frozen=True, slots=True)
class _OperationRule:
    permitted_registers: tuple[str, ...]  # registers that may carry rows; every other recorder register is EMPTY


# Operation rule table (S11 section 1): the permitted register set per kind for the measured shape.
OPERATION_RULES: Final = MappingProxyType({
    ChangeKind.CREATE_DRAFT: _OperationRule(()),
    ChangeKind.UPDATE_DRAFT: _OperationRule(()),
    ChangeKind.POST: _OperationRule(tuple(sorted((_ACCOUNTING_REGISTER, _VAT_ACCUMULATION_REGISTER)))),
    ChangeKind.UNPOST: _OperationRule(()),
})
if set(OPERATION_RULES) != set(ChangeKind):
    # import-time guard: every change kind has an operation rule
    raise RuntimeError("OPERATION_RULES_INCOMPLETE")


def derive_allowed_effects(kind: object) -> tuple[str, ...]:
    """The server-derived permitted register set for ``kind`` (never caller-supplied)."""
    if type(kind) is not ChangeKind:
        raise ValueError("KIND_INVALID")
    return OPERATION_RULES[kind].permitted_registers


# ---- canonical JSON and digests -----------------------------------------------------------------------------

def _encode(value: object) -> object:
    if isinstance(value, Enum):
        return _encode(value.value)
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError("NON_CANONICAL_VALUE")
        return format(value.normalize(), "f")
    if type(value) is datetime:
        if not is_aware_datetime(value):
            raise ValueError("NON_CANONICAL_VALUE")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if type(value) in (tuple, list):
        return [_encode(v) for v in value]  # type: ignore[attr-defined]
    if type(value) in (frozenset, set):
        return sorted((_encode(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))  # type: ignore[attr-defined]
    if type(value) in (dict, MappingProxyType):
        if not all(type(k) is str for k in value):  # type: ignore[attr-defined]
            raise ValueError("NON_CANONICAL_VALUE")
        return {k: _encode(v) for k, v in value.items()}  # type: ignore[attr-defined]
    raise ValueError("NON_CANONICAL_VALUE")  # floats and every other type


def canonical_json(value: object) -> str:
    """Sorted-key, compact, ASCII JSON; decimals normalized, datetimes aware-UTC; floats are refused."""
    return json.dumps(_encode(value), sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


# ---- typed payload -------------------------------------------------------------------------------------------

_DECIMAL_RE: Final = re.compile(r"(0|[1-9][0-9]{0,17})(\.[0-9]{1,6})?")


def _decimal_text(value: object, positive: bool = False) -> str | None:
    """Canonical decimal text (no trailing zeros) of an exact decimal string, else ``None``."""
    if type(value) is not str or _DECIMAL_RE.fullmatch(value) is None:
        return None
    number = Decimal(value)
    if positive and number <= 0:
        return None
    return format(number.normalize(), "f") if number != 0 else "0"


def _ref(value: object) -> bool:
    return is_identity_text(value, MAX_REF_CHARS)


def _printable(value: object, max_chars: int, allow_empty: bool = False) -> bool:
    return (type(value) is str and (allow_empty or len(value) > 0) and len(value) <= max_chars
            and all(c.isprintable() or c in "\n\t" for c in value))


@dataclass(frozen=True, slots=True)
class Line:
    item_ref: str
    quantity: str
    price: str
    vat_rate_code: str
    amount: str

    def __post_init__(self) -> None:
        if (not _ref(self.item_ref) or not is_identity_text(self.vat_rate_code, 32)
                or _decimal_text(self.quantity, positive=True) != self.quantity
                or _decimal_text(self.price) != self.price or _decimal_text(self.amount) != self.amount):
            raise ValueError("LINE_INVALID")


@dataclass(frozen=True, slots=True)
class DuplicateOverride:
    duplicate_of_change_or_ref: str
    justification: str

    def __post_init__(self) -> None:
        if not _ref(self.duplicate_of_change_or_ref) or not _printable(self.justification, 500):
            raise ValueError("DUPLICATE_OVERRIDE_INVALID")


@dataclass(frozen=True, slots=True)
class DraftPayload:
    """CREATE_DRAFT / UPDATE_DRAFT payload (UPDATE is a full replacement plus ``expected_target_version``)."""

    organization_ref: str
    counterparty_ref: str
    contract_ref: str
    supplier_document_number: str
    supplier_document_date: str
    currency: str
    lines: tuple[Line, ...]
    comment: str
    duplicate_override: DuplicateOverride | None = None
    expected_target_version: str | None = None

    def __post_init__(self) -> None:
        try:
            parsed_date = date.fromisoformat(self.supplier_document_date)
        except (TypeError, ValueError):
            raise ValueError("DRAFT_PAYLOAD_INVALID") from None
        if (not all(_ref(v) for v in (self.organization_ref, self.counterparty_ref, self.contract_ref))
                or not _printable(self.supplier_document_number, 64)
                or parsed_date.isoformat() != self.supplier_document_date
                or not is_identity_text(self.currency, 8)
                or type(self.lines) is not tuple or not 1 <= len(self.lines) <= MAX_LINES_SCHEMA
                or not all(type(x) is Line for x in self.lines)
                or not _printable(self.comment, MAX_COMMENT_CHARS, allow_empty=True)
                or (self.duplicate_override is not None and type(self.duplicate_override) is not DuplicateOverride)
                or (self.expected_target_version is not None and not _ref(self.expected_target_version))):
            raise ValueError("DRAFT_PAYLOAD_INVALID")

    def __repr__(self) -> str:
        return "DraftPayload(<redacted>)"


def payload_to_dict(payload: DraftPayload | None) -> dict[str, object]:
    """Canonicalizable dict of a payload; POST and UNPOST carry the empty payload."""
    if payload is None:
        return {}
    override = payload.duplicate_override
    return {
        "organization_ref": payload.organization_ref, "counterparty_ref": payload.counterparty_ref,
        "contract_ref": payload.contract_ref, "supplier_document_number": payload.supplier_document_number,
        "supplier_document_date": payload.supplier_document_date, "currency": payload.currency,
        "lines": [{"item_ref": x.item_ref, "quantity": x.quantity, "price": x.price,
                   "vat_rate_code": x.vat_rate_code, "amount": x.amount} for x in payload.lines],
        "comment": payload.comment,
        "duplicate_override": None if override is None else {
            "duplicate_of_change_or_ref": override.duplicate_of_change_or_ref, "justification": override.justification},
        "expected_target_version": payload.expected_target_version,
    }


def payload_digest(payload: DraftPayload | None, target_version: str | None) -> str:
    """SHA-256 of the canonical payload plus the target version (CT2)."""
    return sha256_hex(canonical_json({"payload": payload_to_dict(payload), "target_version": target_version}))


# ---- the proposal --------------------------------------------------------------------------------------------

def _digest_text(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _epoch_pairs(value: object) -> bool:
    return (type(value) is tuple and all(type(p) is tuple and len(p) == 2 and is_identity_text(p[0], 64)
                                         and type(p[1]) is int and p[1] >= 0 for p in value)
            and list(value) == sorted(value) and len({p[0] for p in value}) == len(value))


@dataclass(frozen=True, slots=True)
class ChangeProposal:
    """The envelope of section 3. Direct construction re-validates every invariant (``ValueError``)."""

    change_id: str
    kind: ChangeKind
    scope: Scope
    requester_principal: str
    requester_person_id: str
    request_id: str
    payload: DraftPayload | None
    payload_digest: str
    preview_digest: str
    allowed_effects: tuple[str, ...]
    rule_table_version: str
    auth_epoch_at_proposal: int
    epoch_dependencies: tuple[tuple[str, int], ...]
    created_at: datetime
    expires_at: datetime
    claim_generation: int = 0
    parent_change_id: str | None = None
    target_ref: str | None = None
    target_version: str | None = None
    business_state_digest: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        kind = self.kind
        if type(kind) is not ChangeKind or type(self.scope) is not Scope:
            raise ValueError("PROPOSAL_INVALID")
        draft = kind in (ChangeKind.CREATE_DRAFT, ChangeKind.UPDATE_DRAFT)
        ok = (all(is_identity_text(v) for v in (self.change_id, self.requester_principal, self.requester_person_id))
              and is_identity_text(self.request_id, 128) and self.claim_generation == 0
              and _digest_text(self.preview_digest) and self.rule_table_version == RULE_TABLE_VERSION
              and self.allowed_effects == derive_allowed_effects(kind)  # server-derived, never caller-supplied
              and type(self.auth_epoch_at_proposal) is int and self.auth_epoch_at_proposal >= 0
              and _epoch_pairs(self.epoch_dependencies)
              and is_aware_datetime(self.created_at) and is_aware_datetime(self.expires_at)
              and self.expires_at > self.created_at
              and _printable(self.reason, MAX_REASON_CHARS, allow_empty=True)
              and all(v is None or _ref(v) for v in (self.parent_change_id, self.target_ref, self.target_version))
              and (self.business_state_digest is None or _digest_text(self.business_state_digest)))
        if ok and draft:
            ok = (type(self.payload) is DraftPayload and self.business_state_digest is None
                  and self.payload.organization_ref == self.scope.organization)
            if ok and kind is ChangeKind.CREATE_DRAFT:
                ok = (self.parent_change_id is None and self.target_ref is None and self.target_version is None
                      and self.payload.expected_target_version is None)
            elif ok:
                ok = (self.target_ref is not None and self.target_version is not None
                      and self.payload.expected_target_version == self.target_version)
        elif ok:
            ok = (self.payload is None and self.parent_change_id is not None and self.target_ref is not None
                  and self.target_version is not None and self.business_state_digest is not None)
        if not ok or self.payload_digest != payload_digest(self.payload, self.target_version):
            raise ValueError("PROPOSAL_INVALID")

    @property
    def logical_key(self) -> tuple[str, str, tuple[str, str, str, str], str]:
        """(requester principal, change kind, scope tuple, request_id)."""
        return (self.requester_principal, self.kind.value, self.scope.as_tuple(), self.request_id)

    @property
    def duplicate_override(self) -> DuplicateOverride | None:
        return None if self.payload is None else self.payload.duplicate_override

    def __repr__(self) -> str:
        return "ChangeProposal(<redacted>)"


APPROVAL_DIGEST_VERSION: Final = "S12-APPROVAL-2"
PRINCIPAL_EPOCH_PREFIX: Final = "principal:"  # principal epoch entries are not part of the digest (see spec 3, item 5)


def _budget_envelope(budget: Mapping[str, object] | None) -> dict[str, object] | None:
    """The declared budget in canonical form (amount as canonical decimal text), or ``None`` when none is declared."""
    if budget is None:
        return None
    keys = {"grant_id", "currency", "amount", "counts_create_update", "counts_post"}
    if (not isinstance(budget, Mapping) or set(budget) != keys or type(budget["grant_id"]) is not str
            or type(budget["currency"]) is not str or type(budget["counts_create_update"]) is not bool
            or type(budget["counts_post"]) is not bool or type(budget["amount"]) not in (str, Decimal)):
        raise ValueError("PROPOSAL_INVALID")
    amount = Decimal(str(budget["amount"]))
    if not amount.is_finite() or amount < 0:
        raise ValueError("PROPOSAL_INVALID")
    return {"grant_id": budget["grant_id"], "currency": budget["currency"],
            "amount": format(amount.normalize(), "f") if amount != 0 else "0",
            "counts_create_update": budget["counts_create_update"], "counts_post": budget["counts_post"]}


def approval_canonical_text(proposal: ChangeProposal, *, approval_nonce: str | None = None,
                            repair_for: str | None = None, declared_target_class: str | None = None,
                            budget: Mapping[str, object] | None = None) -> str:
    """The canonical approval text of S12-APPROVAL-2 (docs/phase2/S12_APPROVAL_DIGEST_2_SPEC.md section 3).

    The closed field list has exactly 20 top-level keys; absent optional values are JSON ``null``. The SQL ledger
    stores this text as given and hashes its UTF-8 bytes (``change_ledger.store_approval_text``). Fields a
    ``ChangeProposal`` does not carry (nonce, repair link, declared class, declared budget) are keyword arguments.
    ``payload`` is ``null`` for the kinds that carry none. Principal epoch entries are excluded; the rest are sorted pairs.
    """
    if type(proposal) is not ChangeProposal:
        raise ValueError("PROPOSAL_INVALID")
    if any(v is not None and type(v) is not str for v in (approval_nonce, repair_for, declared_target_class)):
        raise ValueError("PROPOSAL_INVALID")
    override = proposal.duplicate_override
    pairs = sorted([k, v] for k, v in proposal.epoch_dependencies if not k.startswith(PRINCIPAL_EPOCH_PREFIX))
    return canonical_json({
        "digest_version": APPROVAL_DIGEST_VERSION,
        "change_id": proposal.change_id,
        "kind": proposal.kind,
        "scope": {"tenant": proposal.scope.tenant, "company": proposal.scope.company,
                  "organization": proposal.scope.organization, "base_fingerprint": proposal.scope.base_fingerprint},
        "payload": None if proposal.payload is None else payload_to_dict(proposal.payload),
        "payload_digest": proposal.payload_digest,
        "target_ref": proposal.target_ref,
        "target_version": proposal.target_version,
        "business_state_digest": proposal.business_state_digest,
        "parent_change_id": proposal.parent_change_id,
        "repair_for": repair_for,
        "declared_target_class": declared_target_class,
        "allowed_effects": sorted(proposal.allowed_effects),
        "budget": _budget_envelope(budget),
        "duplicate_override": None if override is None else {
            "duplicate_of_change_or_ref": override.duplicate_of_change_or_ref, "justification": override.justification},
        "rule_table_version": proposal.rule_table_version,
        "epoch_dependencies": pairs,
        "preview_digest": proposal.preview_digest,
        "approval_nonce": approval_nonce,
        "expires_at": proposal.expires_at,
    })


def digest_of_canonical_text(text: str) -> str:
    """SHA-256 (hex) of the UTF-8 bytes of a canonical approval text: the S12-APPROVAL-2 digest."""
    if type(text) is not str:
        raise ValueError("PROPOSAL_INVALID")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def approval_digest(proposal: ChangeProposal, *, approval_nonce: str | None = None, repair_for: str | None = None,
                    declared_target_class: str | None = None, budget: Mapping[str, object] | None = None) -> str:
    """S12-APPROVAL-2: sha256 of ``approval_canonical_text`` (same arguments)."""
    return digest_of_canonical_text(approval_canonical_text(
        proposal, approval_nonce=approval_nonce, repair_for=repair_for,
        declared_target_class=declared_target_class, budget=budget))


# ---- parsing caller input ------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ProposalContext:
    """Everything the server derives itself; none of it is ever read from the caller's input."""

    change_id: str
    requester_principal: str
    requester_person_id: str
    scope: Scope
    created_at: datetime
    expires_at: datetime
    auth_epoch_at_proposal: int
    epoch_dependencies: tuple[tuple[str, int], ...]
    preview_digest: str
    business_state_digest: str | None = None  # POST and UNPOST: from the authenticated target read at propose
    qualified_currencies: frozenset[str] = frozenset()  # measured-shape qualification; empty refuses every draft
    in_scope_refs: frozenset[str] | None = None  # None: ref resolution is not part of this offline check

    def __repr__(self) -> str:
        return "ProposalContext(<redacted>)"


_ENVELOPE_KEYS: Final = frozenset({"kind", "request_id", "parent_change_id", "target_ref", "target_version",
                                   "payload", "reason"})
_PAYLOAD_KEYS: Final = frozenset({"organization_ref", "counterparty_ref", "contract_ref", "supplier_document_number",
                                  "supplier_document_date", "currency", "lines", "comment", "duplicate_override"})
_LINE_KEYS: Final = frozenset({"item_ref", "quantity", "price", "vat_rate_code", "amount"})
_OVERRIDE_KEYS: Final = frozenset({"duplicate_of_change_or_ref", "justification"})
_BAD: Final = Refusal(ErrorCode.SCHEMA_INVALID, "propose")


def _exact_keys(raw: object, allowed: frozenset[str], required: frozenset[str]) -> bool:
    return (isinstance(raw, Mapping) and all(type(k) is str for k in raw)
            and set(raw) <= allowed and required <= set(raw))


def _parse_lines(raw: object) -> tuple[Line, ...] | None:
    if type(raw) not in (list, tuple) or not 1 <= len(raw) <= MAX_LINES_SCHEMA:  # type: ignore[arg-type]
        return None
    out: list[Line] = []
    for item in raw:  # type: ignore[attr-defined]
        if not _exact_keys(item, _LINE_KEYS, _LINE_KEYS):
            return None
        quantity, price, amount = (_decimal_text(item[k], positive=(k == "quantity"))  # type: ignore[index]
                                   for k in ("quantity", "price", "amount"))
        if quantity is None or price is None or amount is None:
            return None
        try:
            out.append(Line(item["item_ref"], quantity, price, item["vat_rate_code"], amount))  # type: ignore[index]
        except ValueError:
            return None
    return tuple(out)


def _parse_draft(raw: object, kind: ChangeKind, scope: Scope, target_version: str | None) -> DraftPayload | Refusal:
    keys = _PAYLOAD_KEYS | ({"expected_target_version"} if kind is ChangeKind.UPDATE_DRAFT else frozenset())
    required = keys - {"duplicate_override"}
    if not _exact_keys(raw, keys, required):
        return _BAD
    lines = _parse_lines(raw["lines"])  # type: ignore[index]
    override_raw = raw.get("duplicate_override")  # type: ignore[attr-defined]
    override = None
    if override_raw is not None:
        if not _exact_keys(override_raw, _OVERRIDE_KEYS, _OVERRIDE_KEYS):
            return _BAD
        try:
            override = DuplicateOverride(override_raw["duplicate_of_change_or_ref"], override_raw["justification"])
        except ValueError:
            return _BAD
    if lines is None:
        return _BAD
    if raw["organization_ref"] != scope.organization:  # type: ignore[index]
        return Refusal(ErrorCode.SCOPE_MISMATCH, "propose")
    try:
        return DraftPayload(
            raw["organization_ref"], raw["counterparty_ref"], raw["contract_ref"],  # type: ignore[index]
            raw["supplier_document_number"], raw["supplier_document_date"], raw["currency"], lines,  # type: ignore[index]
            raw["comment"], override, raw.get("expected_target_version"))  # type: ignore[index,attr-defined]
    except ValueError:
        return _BAD


def parse_proposal(raw: object, ctx: object) -> ChangeProposal | Refusal:
    """Build a ``ChangeProposal`` from caller input plus server-derived context, or return a code-only refusal.

    Order: structure (unknown keys, including any caller ``allowed_effects``) -> scope -> reference scope ->
    shape qualification. Never raises and never echoes input.
    """
    try:
        return _parse(raw, ctx)
    except (ValueError, TypeError, KeyError):
        return _BAD


def _parse(raw: object, ctx: object) -> ChangeProposal | Refusal:
    if type(ctx) is not ProposalContext or not _exact_keys(raw, _ENVELOPE_KEYS, frozenset({"kind", "request_id"})):
        return _BAD
    kind_text = raw["kind"]  # type: ignore[index]
    if type(kind_text) is not str or kind_text not in ChangeKind.__members__:
        return _BAD
    kind = ChangeKind(kind_text)
    draft = kind in (ChangeKind.CREATE_DRAFT, ChangeKind.UPDATE_DRAFT)
    target_version = raw.get("target_version")  # type: ignore[attr-defined]
    payload_raw = raw.get("payload")  # type: ignore[attr-defined]
    payload: DraftPayload | None = None
    if draft:
        parsed = _parse_draft(payload_raw, kind, ctx.scope, target_version)
        if type(parsed) is Refusal:
            return parsed
        payload = parsed  # type: ignore[assignment]
        shape = _shape_refusal(payload, ctx)  # type: ignore[arg-type]
        scope_refusal = _ref_scope_refusal(payload, raw, ctx)  # type: ignore[arg-type]
        if scope_refusal is not None:
            return scope_refusal
        if shape is not None:
            return shape
    elif payload_raw not in (None, {}):
        return _BAD  # POST and UNPOST carry the empty payload
    elif type(raw.get("target_ref")) is not str:  # type: ignore[attr-defined]
        return _BAD
    elif ctx.in_scope_refs is not None and raw["target_ref"] not in ctx.in_scope_refs:  # type: ignore[index]
        return Refusal(ErrorCode.REF_OUT_OF_SCOPE, "propose")
    return ChangeProposal(
        change_id=ctx.change_id, kind=kind, scope=ctx.scope, requester_principal=ctx.requester_principal,
        requester_person_id=ctx.requester_person_id, request_id=raw["request_id"],  # type: ignore[index]
        payload=payload, payload_digest=payload_digest(payload, target_version),
        preview_digest=ctx.preview_digest, allowed_effects=derive_allowed_effects(kind),
        rule_table_version=RULE_TABLE_VERSION, auth_epoch_at_proposal=ctx.auth_epoch_at_proposal,
        epoch_dependencies=tuple(sorted(ctx.epoch_dependencies)), created_at=ctx.created_at,
        expires_at=ctx.expires_at, claim_generation=0, parent_change_id=raw.get("parent_change_id"),  # type: ignore[attr-defined]
        target_ref=raw.get("target_ref"), target_version=target_version,  # type: ignore[attr-defined]
        business_state_digest=None if draft else ctx.business_state_digest, reason=raw.get("reason", ""))  # type: ignore[attr-defined]


def _shape_refusal(payload: DraftPayload, ctx: ProposalContext) -> Refusal | None:
    """Only the measured shape is admitted: one line, a qualified currency (measured fixtures only)."""
    if (len(payload.lines) > MEASURED_SHAPE_MAX_LINES or payload.currency not in ctx.qualified_currencies):
        return Refusal(ErrorCode.SHAPE_NOT_QUALIFIED, "propose")
    return None


def _ref_scope_refusal(payload: DraftPayload, raw: Mapping[str, object], ctx: ProposalContext) -> Refusal | None:
    if ctx.in_scope_refs is None:
        return None
    refs = {payload.organization_ref, payload.counterparty_ref, payload.contract_ref}
    refs.update(x.item_ref for x in payload.lines)
    if isinstance(raw.get("target_ref"), str):
        refs.add(raw["target_ref"])  # type: ignore[arg-type]
    return None if refs <= ctx.in_scope_refs else Refusal(ErrorCode.REF_OUT_OF_SCOPE, "propose")
