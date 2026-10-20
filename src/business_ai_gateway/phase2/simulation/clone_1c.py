"""Deterministic in-memory stand-in of the 1C test clone for the supplier-document use case.

Offline and pure (stdlib only). ``SimulatedOneC`` stores supplier documents with versions, answers ``read_state``,
``preview`` and ``observed_state_digest``, and performs ``apply`` ONLY on its own in-memory state. Failure injection
(``fail_next``) and the ``tamper`` hook let scenarios simulate partial failure, unknown outcome and a bad transport.

Conventions
-----------
* Every record carries ``lane='TEST'`` and ``synthetic_marker`` (no real names anywhere).
* Payload bytes are the canonical JSON (ASCII) of ``payload_to_dict`` (``encode_payload``); POST and UNPOST carry
  ``b"{}"``. The clone parses the bytes it RECEIVED, so a tampered transport changes what is written or is refused.
* ``received_payload_sha256`` is the SHA-256 of the exact bytes received (after the optional tamper hook).
* The business state digest covers the document content (status, payload, movements) and excludes the version, so
  a rewrite with identical content changes the version but not the digest.
* Injected failures are consumed FIFO, one per ``apply`` call, before any other check. ``timeout`` and
  ``crash_before_write`` never write; ``crash_after_write`` writes and then raises (unknown outcome for the caller);
  ``reject`` and ``duplicate`` refuse without writing. The ground truth is visible only via ``truth_log``,
  ``read_state`` and ``write_count`` (scenario oracles), never through the raised exception.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Final

from ..change.proposal import (
    DraftPayload, DuplicateOverride, Line, canonical_json, derive_allowed_effects, payload_digest, payload_to_dict,
)
from ..change.types import ChangeKind, is_aware_datetime, is_identity_text
from ..ed25519 import public_key_from_seed, sign, verify

__all__ = [
    "CloneCrash", "CloneError", "CloneRejected", "CloneTimeout", "ApplyResult", "FAILURE_MODES", "LANE",
    "PreviewResult", "RECEIPT_TEXT_PREFIX", "SYNTHETIC_MARKER", "SimulatedOneC", "decode_payload", "encode_payload",
    "receipt_signing_text", "verify_clone_receipt",
]

LANE: Final = "TEST"
# The text the clone signs for one applied dispatch. change_ledger.record_dispatch_receipt (migration 016) rebuilds
# exactly this text from its own columns, so the signature binds change, dispatch, received bytes and new version.
RECEIPT_TEXT_PREFIX: Final = "change-ledger-receipt|v1|"
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_RECEIPT_FIELDS: Final = frozenset({
    "type", "lane", "key_id", "change_id", "dispatch_id", "received_payload_sha256", "new_version", "signature"})
SYNTHETIC_MARKER: Final = "SYNTHETIC-SIM-ONEC-V1"
FAILURE_MODES: Final = ("timeout", "reject", "duplicate", "crash_after_write", "crash_before_write")
STATUS_DRAFT: Final = "DRAFT"
STATUS_POSTED: Final = "POSTED"
_DRAFT_KINDS: Final = (ChangeKind.CREATE_DRAFT, ChangeKind.UPDATE_DRAFT)


class CloneError(Exception):
    """Base of every simulated-clone failure; carries a code only, never payload content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CloneRejected(CloneError):
    """A definite refusal: the clone did NOT write. ``received_payload_sha256`` is set when bytes were received."""

    def __init__(self, code: str, received_payload_sha256: str | None = None) -> None:
        super().__init__(code)
        self.received_payload_sha256 = received_payload_sha256


class CloneTimeout(CloneError):
    """The caller saw a timeout. The simulated clone did not write, but the caller cannot know that."""

    def __init__(self) -> None:
        super().__init__("TIMEOUT")


class CloneCrash(CloneError):
    """The clone session died. ``crash_after_write`` raises this AFTER the write was applied (unknown outcome)."""

    def __init__(self) -> None:
        super().__init__("CRASH")


@dataclass(frozen=True, slots=True)
class PreviewResult:
    text: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ApplyResult:
    kind: ChangeKind
    target_ref: str
    new_version: str
    received_payload_sha256: str
    effects: dict[str, int]
    lane: str = LANE
    synthetic_marker: str = SYNTHETIC_MARKER
    receipt: dict[str, object] | None = None  # signed by the clone's own key when change_id and dispatch_id were given


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def receipt_signing_text(change_id: str, dispatch_id: str, received_payload_sha256: str, new_version: str) -> str:
    """The exact text a clone receipt signs (UTF-8 bytes of this string)."""
    for value in (change_id, dispatch_id, new_version):
        if not is_identity_text(value) or "|" in value:
            raise ValueError("RECEIPT_FIELD_INVALID")
    if type(received_payload_sha256) is not str or _HEX64.fullmatch(received_payload_sha256) is None:
        raise ValueError("RECEIPT_FIELD_INVALID")
    return f"{RECEIPT_TEXT_PREFIX}{change_id}|{dispatch_id}|{received_payload_sha256}|{new_version}"


def verify_clone_receipt(public_key_hex: str, receipt: object) -> bool:
    """True only for a well-formed clone receipt whose signature verifies under ``public_key_hex``. Never raises."""
    try:
        if type(receipt) is not dict or type(public_key_hex) is not str or set(receipt) != _RECEIPT_FIELDS:
            return False
        if receipt["type"] != "CLONE_RECEIPT" or receipt["lane"] != LANE:
            return False
        text = receipt_signing_text(receipt["change_id"], receipt["dispatch_id"],
                                    receipt["received_payload_sha256"], receipt["new_version"])
        signature = receipt["signature"]
        if type(signature) is not str:
            return False
        return verify(bytes.fromhex(public_key_hex), text.encode("utf-8"), bytes.fromhex(signature))
    except (ValueError, TypeError, KeyError):
        return False


def encode_payload(payload: DraftPayload | None) -> bytes:
    """The exact wire bytes of a payload: canonical ASCII JSON; ``b"{}"`` for POST and UNPOST."""
    return canonical_json(payload_to_dict(payload)).encode("ascii")


def decode_payload(data: bytes) -> DraftPayload | None:
    """Parse wire bytes back to a typed payload (``None`` for ``{}``); ``CloneRejected('PAYLOAD_INVALID')`` otherwise."""
    bad = CloneRejected("PAYLOAD_INVALID")
    try:
        raw = json.loads(bytes(data).decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        raise bad from None
    if type(raw) is not dict:
        raise bad
    if raw == {}:
        return None
    if set(raw) != _FULL_KEYS:
        raise bad
    try:
        lines_raw = raw["lines"]
        if type(lines_raw) is not list:
            raise bad
        lines = []
        for item in lines_raw:
            if type(item) is not dict or set(item) != _LINE_KEYS:
                raise bad
            lines.append(Line(item["item_ref"], item["quantity"], item["price"], item["vat_rate_code"], item["amount"]))
        override_raw = raw["duplicate_override"]
        override = None
        if override_raw is not None:
            if type(override_raw) is not dict or set(override_raw) != {"duplicate_of_change_or_ref", "justification"}:
                raise bad
            override = DuplicateOverride(override_raw["duplicate_of_change_or_ref"], override_raw["justification"])
        return DraftPayload(
            raw["organization_ref"], raw["counterparty_ref"], raw["contract_ref"], raw["supplier_document_number"],
            raw["supplier_document_date"], raw["currency"], tuple(lines), raw["comment"], override,
            raw["expected_target_version"])
    except (ValueError, TypeError, KeyError):
        raise bad from None


_FULL_KEYS: Final = frozenset({
    "organization_ref", "counterparty_ref", "contract_ref", "supplier_document_number", "supplier_document_date",
    "currency", "lines", "comment", "duplicate_override", "expected_target_version"})
_LINE_KEYS: Final = frozenset({"item_ref", "quantity", "price", "vat_rate_code", "amount"})


@dataclass(slots=True)
class _Document:
    target_ref: str
    version: int
    status: str
    payload: DraftPayload  # stored without the transport-only ``expected_target_version``


class SimulatedOneC:
    """Deterministic simulated 1C test clone (see module docstring)."""

    def __init__(self, label: str = "SIM-CLONE-A") -> None:
        self.label = label
        # The receipt key belongs to the clone alone: the seed never leaves this object and is never given to a writer.
        self._receipt_seed = hashlib.sha256(("SIM-ONEC-RECEIPT-KEY|" + label).encode("utf-8")).digest()
        self.receipt_public_key_hex = public_key_from_seed(self._receipt_seed).hex()
        self.receipt_key_id = "sim-clone-key-" + _sha256_bytes(bytes.fromhex(self.receipt_public_key_hex))[:16]
        self._docs: dict[str, _Document] = {}
        self._next_doc = 1
        self._injections: deque[str] = deque()
        self._tamper_next = False
        self._log: list[dict[str, object]] = []
        self._writes = 0
        # Owned by the clone so every adapter sharing this instance serializes the
        # final base-fingerprint/version check with the mutation itself.
        self._write_lock = RLock()
        self._simulation_calls: dict[str, tuple[object, ...]] = {}
        self._simulation_scope: tuple[str, str, str] | None = None

    def bind_simulation_scope(self, tenant_id: str, company_id: str, organization: str) -> None:
        """Permanently bind this clone instance to one synthetic tenant/company/org tuple."""
        scope = (tenant_id, company_id, organization)
        if not all(is_identity_text(value) for value in scope):
            raise ValueError("SIMULATION_SCOPE_INVALID")
        with self._write_lock:
            if self._simulation_scope is None:
                self._simulation_scope = scope
            elif self._simulation_scope != scope:
                raise ValueError("SIMULATION_SCOPE_ALREADY_BOUND")

    # ---- scenario hooks ---------------------------------------------------------------------------------------

    def fail_next(self, mode: str) -> None:
        """Queue one injected failure for the next ``apply`` call (FIFO)."""
        if mode not in FAILURE_MODES:
            raise ValueError("FAILURE_MODE_INVALID")
        with self._write_lock:
            self._injections.append(mode)

    def tamper(self) -> None:
        """Flip one byte of the payload received by the next ``apply`` call (bad transport)."""
        with self._write_lock:
            self._tamper_next = True

    # ---- reads ------------------------------------------------------------------------------------------------

    @property
    def write_count(self) -> int:
        with self._write_lock:
            return self._writes

    def truth_log(self) -> tuple[dict[str, object], ...]:
        """Ground-truth record of every apply attempt (scenario oracle; not visible to the caller under test)."""
        with self._write_lock:
            return tuple(dict(e) for e in self._log)

    def target_refs(self) -> tuple[str, ...]:
        with self._write_lock:
            return tuple(sorted(self._docs))

    def read_state(self, target_ref: str) -> dict[str, object]:
        with self._write_lock:
            return self._state_of(self._doc(target_ref))

    def observed_state_digest(self, target_ref: str) -> str:
        """SHA-256 of the canonical business state (status, payload, movements); excludes the version."""
        with self._write_lock:
            state = self._state_of(self._doc(target_ref))
            state.pop("version")
            return _sha256_bytes(canonical_json(state).encode("ascii"))

    def state_fingerprint(self) -> str:
        """Deterministic fingerprint of the whole clone (every document incl. versions)."""
        with self._write_lock:
            body = {"clone": self.label, "lane": LANE, "documents": [self._state_of(self._docs[r]) for r in sorted(self._docs)]}
            return _sha256_bytes(canonical_json(body).encode("ascii"))

    def find_duplicates(self, payload: DraftPayload, exclude_ref: str | None = None) -> tuple[str, ...]:
        """Documents with the same (counterparty, supplier document number, supplier document date)."""
        with self._write_lock:
            key = _dup_key(payload)
            return tuple(sorted(r for r, d in self._docs.items() if r != exclude_ref and _dup_key(d.payload) == key))

    def preview(self, kind: ChangeKind, payload: DraftPayload | None, target_ref: str | None) -> PreviewResult:
        """Canonical preview text and its SHA-256. Pure: writes nothing and consumes no injected failure."""
        with self._write_lock:
            return self._preview_locked(kind, payload, target_ref)

    def _preview_locked(self, kind: ChangeKind, payload: DraftPayload | None,
                        target_ref: str | None) -> PreviewResult:
        if type(kind) is not ChangeKind:
            raise ValueError("KIND_INVALID")
        doc = self._docs.get(target_ref) if target_ref is not None else None
        refusal = self._plan(kind, payload, target_ref, expected_version=None, check_version=False)
        predicted: dict[str, object] = {"refusal": refusal, "resulting_status": _resulting_status(kind, doc)}
        if kind is ChangeKind.POST and refusal is None:
            predicted["movements"] = _movements_for(doc.payload if doc else payload)
        body = {
            "lane": LANE, "synthetic_marker": SYNTHETIC_MARKER, "kind": kind, "target_ref": target_ref,
            "base_version": None if doc is None else _version_text(doc.version),
            "base_state": None if doc is None else self._state_of(doc),
            "payload": payload_to_dict(payload), "predicted": predicted,
        }
        text = canonical_json(body)
        return PreviewResult(text, _sha256_bytes(text.encode("ascii")))

    # ---- the only write path ----------------------------------------------------------------------------------

    def apply(self, kind: ChangeKind, payload_bytes: bytes, target_ref: str | None,
              expected_version: str | None, *, change_id: str | None = None,
              dispatch_id: str | None = None) -> ApplyResult:
        """Apply one change ONLY on this simulated clone. See the module docstring for failure semantics.

        With ``change_id`` and ``dispatch_id`` the successful result carries a receipt signed by the clone's own key
        over (change id, dispatch id, received payload sha256, new version); a caller only forwards it."""
        with self._write_lock:
            return self._apply_locked(kind, payload_bytes, target_ref, expected_version,
                                      change_id=change_id, dispatch_id=dispatch_id)

    def apply_for_simulation(self, kind: ChangeKind, payload_bytes: bytes, target_ref: str | None,
                             expected_version: str | None, expected_base_fingerprint: str,
                             *, expected_tenant_id: str, expected_company_id: str,
                             expected_organization: str, permit_expires_at: datetime,
                             change_id: str, generation: int,
                             call_id: str, digest_set_hash: str) -> ApplyResult:
        """Simulation-only compare-and-apply under the clone-owned write lock.

        Unlike a caller-side preflight check, the base fingerprint and target version
        are checked while holding the same lock used for the write.
        """
        with self._write_lock:
            if not is_aware_datetime(permit_expires_at):
                raise CloneRejected("PERMIT_EXPIRY_INVALID")
            if datetime.now(timezone.utc) >= permit_expires_at:
                raise CloneRejected("PERMIT_EXPIRED")
            if type(kind) is not ChangeKind or kind not in (ChangeKind.CREATE_DRAFT, ChangeKind.POST, ChangeKind.UNPOST):
                raise CloneRejected("OPERATION_NOT_ALLOWED")
            if (not is_identity_text(change_id) or not is_identity_text(call_id)
                    or type(generation) is not int or generation <= 0
                    or type(digest_set_hash) is not str or _HEX64.fullmatch(digest_set_hash) is None):
                raise CloneRejected("CALL_BINDING_INVALID")
            if type(expected_base_fingerprint) is not str or expected_base_fingerprint != self.state_fingerprint():
                raise CloneRejected("BASE_FINGERPRINT_MISMATCH")
            expected_scope = (expected_tenant_id, expected_company_id, expected_organization)
            if (not all(is_identity_text(value) for value in expected_scope)
                    or self._simulation_scope is None or self._simulation_scope != expected_scope):
                raise CloneRejected("SCOPE_MISMATCH")
            if not is_identity_text(expected_organization):
                raise CloneRejected("ORGANIZATION_INVALID")
            try:
                if not isinstance(payload_bytes, (bytes, bytearray)):
                    raise CloneRejected("PAYLOAD_INVALID")
                payload = decode_payload(bytes(payload_bytes))
            except (CloneRejected, TypeError, ValueError):
                raise CloneRejected("PAYLOAD_INVALID") from None
            if payload_digest(payload, expected_version) != digest_set_hash:
                raise CloneRejected("DIGEST_MISMATCH")
            if kind is ChangeKind.CREATE_DRAFT:
                if payload is None or payload.organization_ref != expected_organization:
                    raise CloneRejected("ORGANIZATION_MISMATCH")
            else:
                if payload is not None:
                    raise CloneRejected("PAYLOAD_INVALID")
                doc = self._docs.get(target_ref) if type(target_ref) is str else None
                if doc is not None and doc.payload.organization_ref != expected_organization:
                    raise CloneRejected("ORGANIZATION_MISMATCH")
            call_identity = (
                change_id, generation, kind.value, target_ref, expected_version,
                expected_base_fingerprint, expected_organization, digest_set_hash,
            )
            previous = self._simulation_calls.get(call_id)
            if previous is not None:
                if previous == call_identity:
                    raise CloneRejected("CALL_REPLAYED")
                raise CloneRejected("CALL_ID_CONFLICT")
            # Consume the synthetic call identity before entering the mutation path.
            # Any uncertain or refused attempt therefore cannot be replayed under a
            # changed ticket/base to produce a second side effect.
            self._simulation_calls[call_id] = call_identity
            return self._apply_locked(kind, payload_bytes, target_ref, expected_version)

    def _apply_locked(self, kind: ChangeKind, payload_bytes: bytes, target_ref: str | None,
                      expected_version: str | None, *, change_id: str | None = None,
                      dispatch_id: str | None = None) -> ApplyResult:
        if type(kind) is not ChangeKind or not isinstance(payload_bytes, (bytes, bytearray)):
            raise ValueError("APPLY_ARGUMENTS_INVALID")
        if (change_id is None) != (dispatch_id is None):
            raise ValueError("APPLY_ARGUMENTS_INVALID")
        if change_id is not None:
            receipt_signing_text(change_id, dispatch_id, "0" * 64, "V0")  # validates the identities before any effect
        received = bytes(payload_bytes)
        if self._tamper_next:
            self._tamper_next = False
            received = _flip_one_byte(received)
        digest = _sha256_bytes(received)
        injected = self._injections.popleft() if self._injections else None
        entry: dict[str, object] = {
            "seq": len(self._log) + 1, "kind": kind.value, "target_ref": target_ref, "injected": injected,
            "received_payload_sha256": digest, "write_applied": False, "outcome": "",
        }
        self._log.append(entry)
        if injected == "timeout":
            entry["outcome"] = "TIMEOUT_NO_WRITE"
            raise CloneTimeout()
        if injected == "crash_before_write":
            entry["outcome"] = "CRASH_BEFORE_WRITE"
            raise CloneCrash()
        if injected == "reject":
            entry["outcome"] = "REFUSED:INJECTED_REJECT"
            raise CloneRejected("REJECTED", digest)
        if injected == "duplicate":
            entry["outcome"] = "REFUSED:INJECTED_DUPLICATE"
            raise CloneRejected("DUPLICATE", digest)
        try:
            payload = decode_payload(received)
        except CloneRejected as exc:
            entry["outcome"] = "REFUSED:" + exc.code
            raise CloneRejected(exc.code, digest) from None
        refusal = self._plan(kind, payload, target_ref, expected_version, check_version=True)
        if refusal is not None:
            entry["outcome"] = "REFUSED:" + refusal
            raise CloneRejected(refusal, digest)
        result = self._write(kind, payload, target_ref, digest)
        entry["write_applied"] = True
        entry["outcome"] = "APPLIED"
        if injected == "crash_after_write":
            entry["outcome"] = "CRASH_AFTER_WRITE"
            raise CloneCrash()
        if change_id is not None:
            result = replace(result, receipt=self._sign_receipt(change_id, dispatch_id, digest, result.new_version))
        return result

    def _sign_receipt(self, change_id: str, dispatch_id: str, digest: str, new_version: str) -> dict[str, object]:
        text = receipt_signing_text(change_id, dispatch_id, digest, new_version)
        return {"type": "CLONE_RECEIPT", "lane": LANE, "key_id": self.receipt_key_id, "change_id": change_id,
                "dispatch_id": dispatch_id, "received_payload_sha256": digest, "new_version": new_version,
                "signature": sign(self._receipt_seed, text.encode("utf-8")).hex()}

    # ---- internals --------------------------------------------------------------------------------------------

    def _doc(self, target_ref: str) -> _Document:
        doc = self._docs.get(target_ref) if type(target_ref) is str else None
        if doc is None:
            raise CloneRejected("NOT_FOUND")
        return doc

    def _state_of(self, doc: _Document) -> dict[str, object]:
        return {
            "target_ref": doc.target_ref, "lane": LANE, "synthetic_marker": SYNTHETIC_MARKER,
            "version": _version_text(doc.version), "status": doc.status, "payload": payload_to_dict(doc.payload),
            "movements": _movements_for(doc.payload) if doc.status == STATUS_POSTED else {},
        }

    def _plan(self, kind: ChangeKind, payload: DraftPayload | None, target_ref: str | None,
              expected_version: str | None, check_version: bool) -> str | None:
        """The refusal code the clone would give, or ``None`` when the change is admissible."""
        doc = self._docs.get(target_ref) if type(target_ref) is str else None
        if kind in _DRAFT_KINDS:
            if payload is None:
                return "PAYLOAD_INVALID"
            if kind is ChangeKind.CREATE_DRAFT:
                if target_ref is not None or expected_version is not None or payload.expected_target_version is not None:
                    return "CREATE_ARGUMENTS_INVALID"
            else:
                if doc is None:
                    return "NOT_FOUND"
                if doc.status != STATUS_DRAFT:
                    return "NOT_DRAFT"
                if check_version and (expected_version is None or expected_version != _version_text(doc.version)
                                      or payload.expected_target_version != expected_version):
                    return "STALE_VERSION"
            if payload.duplicate_override is None and self.find_duplicates(payload, exclude_ref=target_ref):
                return "DUPLICATE"
            return None
        if payload is not None:
            return "PAYLOAD_INVALID"
        if doc is None:
            return "NOT_FOUND"
        if check_version and (expected_version is None or expected_version != _version_text(doc.version)):
            return "STALE_VERSION"
        if kind is ChangeKind.POST and doc.status != STATUS_DRAFT:
            return "NOT_DRAFT"
        if kind is ChangeKind.UNPOST and doc.status != STATUS_POSTED:
            return "NOT_POSTED"
        return None

    def _write(self, kind: ChangeKind, payload: DraftPayload | None, target_ref: str | None, digest: str) -> ApplyResult:
        effects = {"documents_created": 0, "documents_updated": 0, "movement_rows_added": 0, "movement_rows_removed": 0}
        if kind is ChangeKind.CREATE_DRAFT:
            ref = f"SIM-DOC-{self._next_doc:06d}"
            self._next_doc += 1
            doc = _Document(ref, 1, STATUS_DRAFT, replace(payload, expected_target_version=None))
            self._docs[ref] = doc
            effects["documents_created"] = 1
        else:
            doc = self._docs[target_ref]
            doc.version += 1
            effects["documents_updated"] = 1
            if kind is ChangeKind.UPDATE_DRAFT:
                doc.payload = replace(payload, expected_target_version=None)
            elif kind is ChangeKind.POST:
                doc.status = STATUS_POSTED
                effects["movement_rows_added"] = sum(_movements_for(doc.payload).values())
            else:
                effects["movement_rows_removed"] = sum(_movements_for(doc.payload).values())
                doc.status = STATUS_DRAFT
        self._writes += 1
        return ApplyResult(kind, doc.target_ref, _version_text(doc.version), digest, effects)


def _version_text(version: int) -> str:
    return f"V{version}"


def _dup_key(payload: DraftPayload) -> tuple[str, str, str]:
    return (payload.counterparty_ref, payload.supplier_document_number, payload.supplier_document_date)


def _movements_for(payload: DraftPayload) -> dict[str, int]:
    """Register rows a POST produces: one row per document line in every permitted register."""
    return {register: len(payload.lines) for register in derive_allowed_effects(ChangeKind.POST)}


def _resulting_status(kind: ChangeKind, doc: _Document | None) -> str:
    if kind is ChangeKind.POST:
        return STATUS_POSTED
    if kind is ChangeKind.UNPOST or kind in _DRAFT_KINDS:
        return STATUS_DRAFT
    return doc.status if doc else STATUS_DRAFT  # pragma: no cover - closed enum


def _flip_one_byte(data: bytes) -> bytes:
    """Flip the lowest bit of the first ASCII digit (keeps JSON well-formed); else of the first byte."""
    buf = bytearray(data)
    if not buf:
        return b"\x00"
    for i, b in enumerate(buf):
        if 0x30 <= b <= 0x39:
            buf[i] = b ^ 1
            return bytes(buf)
    buf[0] ^= 1
    return bytes(buf)
