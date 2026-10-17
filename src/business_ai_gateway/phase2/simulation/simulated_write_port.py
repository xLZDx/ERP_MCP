"""Opt-in protocol-shaped writer for the in-memory TEST clone only.

This is a local simulation aid, not an authorization provider or production writer.
Its synthetic permit MAC has a TEST-specific domain and requires an explicitly
provided test key. The result and error types below are deliberately distinct from
the production writer's signed evidence types.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any, Final

from ..change.proposal import canonical_json, payload_digest
from ..change.types import ChangeKind, is_aware_datetime, is_identity_text
from ..change_ledger.write_port import ApplyTicket, DispatchPermit
from .clone_1c import (
    CloneCrash,
    CloneError,
    CloneRejected,
    CloneTimeout,
    LANE,
    SYNTHETIC_MARKER,
    SimulatedOneC,
    decode_payload,
)

__all__ = [
    "SimulatedOneCWritePort",
    "SyntheticPermitAuthority",
    "SyntheticPortResult",
    "SyntheticPortRefusal",
    "SyntheticOutcomeUnknown",
]

_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_ALLOWED_KINDS: Final = frozenset({ChangeKind.CREATE_DRAFT, ChangeKind.POST, ChangeKind.UNPOST})
_PERMIT_DOMAIN: Final = b"ERP_MCP_R2:S14:SIMULATED-WRITE-PERMIT:TEST:v1\n"


class SyntheticPortRefusal(Exception):
    """Simulation-only refusal; it is not signed no-effect evidence and implies no T8 decision."""

    lane = LANE
    synthetic_marker = SYNTHETIC_MARKER
    certainty = "SIMULATION_REFUSAL_ONLY"

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SyntheticOutcomeUnknown(Exception):
    """The simulated call was entered and its outcome is unknown; no retry is authorized by this type."""

    lane = LANE
    synthetic_marker = SYNTHETIC_MARKER
    certainty = "UNKNOWN_AFTER_INVOCATION"
    retry_permitted = False

    def __init__(self) -> None:
        super().__init__("SIMULATED_OUTCOME_UNKNOWN")


class SyntheticPortResult(dict[str, Any]):
    """Protocol-shaped TEST mapping; excludes clone signatures and oracle state."""

    def __init__(self, *, operation: str, target_ref: str, new_version: str,
                 received_payload_sha256: str, effects: dict[str, int]) -> None:
        super().__init__(
            lane=LANE,
            synthetic_marker=SYNTHETIC_MARKER,
            outcome="APPLIED_TEST_ONLY",
            operation=operation,
            target_ref=target_ref,
            new_version=new_version,
            received_payload_sha256=received_payload_sha256,
            effects=dict(effects),
        )


class SyntheticPermitAuthority:
    """Issue and verify local permits using an explicitly supplied TEST fixture key."""

    def __init__(self, simulator_identity: str, test_key: bytes) -> None:
        if not is_identity_text(simulator_identity) or type(test_key) is not bytes or len(test_key) < 32:
            raise ValueError("SYNTHETIC_PERMIT_CONFIGURATION_INVALID")
        self.simulator_identity = simulator_identity
        self._test_key = bytes(test_key)
        self._signer_key_id = "SIM-TEST:" + simulator_identity

    def issue(self, ticket: ApplyTicket, expires_at: datetime, *, checkpoint_seq: int = 0) -> DispatchPermit:
        """Create a synthetic fixture permit. Never suitable for a real writer or ledger."""
        if (type(ticket) is not ApplyTicket or not is_aware_datetime(expires_at)
                or not self._valid_ticket_binding(ticket)):
            raise ValueError("SYNTHETIC_PERMIT_INPUT_INVALID")
        if type(checkpoint_seq) is not int or checkpoint_seq < 0:
            raise ValueError("SYNTHETIC_PERMIT_INPUT_INVALID")
        permit_id = "SIM-PERMIT:" + ticket.call_id
        permit_digest = _ticket_digest(ticket, self.simulator_identity)
        unsigned = DispatchPermit(
            permit_id=permit_id,
            permit_digest=permit_digest,
            change_id=ticket.change_id,
            generation=ticket.generation,
            call_id=ticket.call_id,
            expires_at=expires_at,
            checkpoint_seq=checkpoint_seq,
            signer_key_id=self._signer_key_id,
            signature="",
            repair_authorization_id=ticket.repair_authorization_id,
            lifecycle_epoch=0,
        )
        signature = hmac.new(self._test_key, _permit_message(unsigned, ticket, self.simulator_identity), hashlib.sha256).hexdigest()
        return DispatchPermit(**{**unsigned.__dict__, "signature": signature})

    def verify(self, ticket: ApplyTicket, permit: DispatchPermit, now: datetime) -> bool:
        if (type(ticket) is not ApplyTicket or type(permit) is not DispatchPermit
                or not is_aware_datetime(now) or not is_aware_datetime(permit.expires_at)
                or not self._valid_ticket_binding(ticket)):
            return False
        if now.utcoffset() is None or permit.expires_at.utcoffset() is None or permit.expires_at <= now:
            return False
        if (permit.permit_id != "SIM-PERMIT:" + ticket.call_id
                or permit.permit_digest != _ticket_digest(ticket, self.simulator_identity)
                or permit.change_id != ticket.change_id or permit.generation != ticket.generation
                or permit.call_id != ticket.call_id or permit.signer_key_id != self._signer_key_id
                or permit.repair_authorization_id != ticket.repair_authorization_id
                or type(permit.lifecycle_epoch) is not int or permit.lifecycle_epoch != 0
                or type(permit.checkpoint_seq) is not int or permit.checkpoint_seq < 0
                or type(permit.signature) is not str or _HEX64.fullmatch(permit.signature) is None):
            return False
        expected = hmac.new(self._test_key, _permit_message(permit, ticket, self.simulator_identity), hashlib.sha256).hexdigest()
        return hmac.compare_digest(permit.signature, expected)

    @staticmethod
    def _valid_ticket_binding(ticket: ApplyTicket) -> bool:
        return (
            all(is_identity_text(value) for value in
                (ticket.change_id, ticket.call_id, ticket.tenant_id, ticket.company_id,
                 ticket.organization, ticket.kind))
            and type(ticket.generation) is int and ticket.generation > 0
            and type(ticket.base_fingerprint) is str and _HEX64.fullmatch(ticket.base_fingerprint) is not None
            and type(ticket.digest_set_hash) is str and _HEX64.fullmatch(ticket.digest_set_hash) is not None
            and (ticket.target_ref is None or is_identity_text(ticket.target_ref))
            and (ticket.target_version is None or is_identity_text(ticket.target_version))
            and (ticket.repair_authorization_id is None or is_identity_text(ticket.repair_authorization_id))
        )


class SimulatedOneCWritePort:
    """Narrow CREATE_DRAFT/POST/UNPOST adapter over one ``SimulatedOneC`` instance."""

    def __init__(self, clone: SimulatedOneC, *, tenant_id: str, company_id: str,
                 organization: str, permit_authority: SyntheticPermitAuthority) -> None:
        if (type(clone) is not SimulatedOneC or type(permit_authority) is not SyntheticPermitAuthority
                or not all(is_identity_text(x) for x in (tenant_id, company_id, organization))
                or permit_authority.simulator_identity != clone.label
                or not is_identity_text(clone.label)):
            raise ValueError("SIMULATED_WRITE_PORT_CONFIGURATION_INVALID")
        self._clone = clone
        self._tenant_id = tenant_id
        self._company_id = company_id
        self._organization = organization
        self._permit_authority = permit_authority
        clone.bind_simulation_scope(tenant_id, company_id, organization)

    async def verify_ticket(self, ticket: ApplyTicket) -> None:
        self._validate_ticket_shape(ticket)
        if ticket.kind not in {kind.value for kind in _ALLOWED_KINDS}:
            raise SyntheticPortRefusal("OPERATION_NOT_ALLOWED")
        if (ticket.tenant_id != self._tenant_id or ticket.company_id != self._company_id
                or ticket.organization != self._organization):
            raise SyntheticPortRefusal("SCOPE_MISMATCH")
        if ticket.base_fingerprint != self._clone.state_fingerprint():
            raise SyntheticPortRefusal("BASE_FINGERPRINT_MISMATCH")
        self._validate_target(ticket)

    async def verify_permit(self, ticket: ApplyTicket, permit: DispatchPermit) -> None:
        await self.verify_ticket(ticket)
        if not self._permit_authority.verify(ticket, permit, datetime.now(timezone.utc)):
            raise SyntheticPortRefusal("SYNTHETIC_PERMIT_INVALID_OR_EXPIRED")

    async def authenticate_base(self, ticket: ApplyTicket) -> str:
        await self.verify_ticket(ticket)
        # Explicitly distinguish this synthetic identity from production authentication.
        return f"TEST:{SYNTHETIC_MARKER}:{self._clone.label}:{ticket.base_fingerprint}"

    async def create_draft(self, ticket: ApplyTicket, permit: DispatchPermit,
                           payload: dict[str, Any]) -> SyntheticPortResult:
        return await self._invoke(ticket, permit, ChangeKind.CREATE_DRAFT, payload)

    async def post(self, ticket: ApplyTicket, permit: DispatchPermit) -> SyntheticPortResult:
        return await self._invoke(ticket, permit, ChangeKind.POST, None)

    async def unpost(self, ticket: ApplyTicket, permit: DispatchPermit) -> SyntheticPortResult:
        return await self._invoke(ticket, permit, ChangeKind.UNPOST, None)

    async def update_draft(self, ticket: ApplyTicket, permit: DispatchPermit,
                           payload: dict[str, Any]) -> SyntheticPortResult:
        # Deliberately reject before consulting caller data or entering the clone.
        raise SyntheticPortRefusal("OPERATION_NOT_ALLOWED")

    async def _invoke(self, ticket: ApplyTicket, permit: DispatchPermit, kind: ChangeKind,
                      payload: dict[str, Any] | None) -> SyntheticPortResult:
        await self.verify_permit(ticket, permit)
        if ticket.kind != kind.value:
            raise SyntheticPortRefusal("OPERATION_MISMATCH")
        payload_bytes = _payload_bytes(payload)
        parsed_payload = decode_payload(payload_bytes)
        if payload_digest(parsed_payload, ticket.target_version) != ticket.digest_set_hash:
            raise SyntheticPortRefusal("DIGEST_MISMATCH")
        if kind is ChangeKind.CREATE_DRAFT and ticket.target_ref is not None:
            raise SyntheticPortRefusal("CREATE_TARGET_INVALID")
        if kind is not ChangeKind.CREATE_DRAFT and ticket.target_ref is None:
            raise SyntheticPortRefusal("TARGET_REQUIRED")
        try:
            applied = self._clone.apply_for_simulation(
                kind, payload_bytes, ticket.target_ref, ticket.target_version, ticket.base_fingerprint,
                expected_tenant_id=self._tenant_id,
                expected_company_id=self._company_id,
                expected_organization=self._organization,
                permit_expires_at=permit.expires_at,
                change_id=ticket.change_id,
                generation=ticket.generation,
                call_id=ticket.call_id,
                digest_set_hash=ticket.digest_set_hash,
            )
        except CloneRejected as exc:
            raise SyntheticPortRefusal("CLONE_REFUSED:" + exc.code) from None
        except (CloneTimeout, CloneCrash, CloneError):
            raise SyntheticOutcomeUnknown() from None
        except Exception:
            # Once the mutating method was entered, an unexpected exception is not
            # evidence that no write occurred and must never trigger an automatic retry.
            raise SyntheticOutcomeUnknown() from None
        return SyntheticPortResult(
            operation=kind.value,
            target_ref=applied.target_ref,
            new_version=applied.new_version,
            received_payload_sha256=applied.received_payload_sha256,
            effects=dict(applied.effects),
        )

    def _validate_ticket_shape(self, ticket: ApplyTicket) -> None:
        if type(ticket) is not ApplyTicket:
            raise SyntheticPortRefusal("TICKET_INVALID")
        if (not all(is_identity_text(value) for value in
                    (ticket.change_id, ticket.call_id, ticket.tenant_id, ticket.company_id,
                     ticket.organization, ticket.base_fingerprint, ticket.kind))
                or type(ticket.generation) is not int or ticket.generation <= 0
                or type(ticket.base_fingerprint) is not str or _HEX64.fullmatch(ticket.base_fingerprint) is None
                or type(ticket.digest_set_hash) is not str or _HEX64.fullmatch(ticket.digest_set_hash) is None
                or ticket.repair_authorization_id is not None
                and not is_identity_text(ticket.repair_authorization_id)):
            raise SyntheticPortRefusal("TICKET_INVALID")

    @staticmethod
    def _validate_target(ticket: ApplyTicket) -> None:
        if ticket.kind == ChangeKind.CREATE_DRAFT.value:
            if ticket.target_ref is not None or ticket.target_version is not None:
                raise SyntheticPortRefusal("CREATE_TARGET_INVALID")
            return
        if (type(ticket.target_ref) is not str or not re.fullmatch(r"SIM-DOC-[0-9]{6}", ticket.target_ref)
                or type(ticket.target_version) is not str
                or not re.fullmatch(r"V[1-9][0-9]*", ticket.target_version)):
            raise SyntheticPortRefusal("TARGET_VERSION_INVALID")


def _payload_bytes(payload: dict[str, Any] | None) -> bytes:
    if payload is None:
        return b"{}"
    if type(payload) is not dict:
        raise SyntheticPortRefusal("PAYLOAD_INVALID")
    try:
        encoded = canonical_json(payload).encode("ascii")
        decoded = decode_payload(encoded)
    except (CloneRejected, TypeError, ValueError, UnicodeError):
        raise SyntheticPortRefusal("PAYLOAD_INVALID") from None
    if decoded is None:
        raise SyntheticPortRefusal("PAYLOAD_INVALID")
    return encoded


def _ticket_body(ticket: ApplyTicket) -> dict[str, object]:
    return {
        "change_id": ticket.change_id,
        "generation": ticket.generation,
        "call_id": ticket.call_id,
        "kind": ticket.kind,
        "tenant_id": ticket.tenant_id,
        "company_id": ticket.company_id,
        "organization": ticket.organization,
        "base_fingerprint": ticket.base_fingerprint,
        "target_ref": ticket.target_ref,
        "target_version": ticket.target_version,
        "digest_set_hash": ticket.digest_set_hash,
        "repair_authorization_id": ticket.repair_authorization_id,
    }


def _ticket_digest(ticket: ApplyTicket, simulator_identity: str) -> str:
    body = {"simulator_identity": simulator_identity, "ticket": _ticket_body(ticket)}
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(_PERMIT_DOMAIN + encoded).hexdigest()


def _permit_message(permit: DispatchPermit, ticket: ApplyTicket, simulator_identity: str) -> bytes:
    body = {
        "simulator_identity": simulator_identity,
        "ticket": _ticket_body(ticket),
        "permit": {
            "permit_id": permit.permit_id,
            "permit_digest": permit.permit_digest,
            "change_id": permit.change_id,
            "generation": permit.generation,
            "call_id": permit.call_id,
            "expires_at": permit.expires_at.isoformat(),
            "checkpoint_seq": permit.checkpoint_seq,
            "signer_key_id": permit.signer_key_id,
            "repair_authorization_id": permit.repair_authorization_id,
            "lifecycle_epoch": permit.lifecycle_epoch,
        },
    }
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return _PERMIT_DOMAIN + encoded
