"""Simulated identity provider for simulation scenarios (TEST lane only, offline, stdlib only).

``SimulatedIdP`` provisions deterministic synthetic persons (each with a distinct login, an Ed25519 key derived from
a seed, and separate sessions) and issues IdP-signed MFA attestations. ``verify_mfa_attestation`` fails closed with a
stable ``MfaAttestationError.code``. Helpers build two-person approval material and refuse the same person, login or
session. Persons are never production entitlements: ``lane`` is always TEST and ``synthetic`` is always True.
The signer is the reference Ed25519 implementation (not audited): synthetic keys only.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final

from ..ed25519 import public_key_from_seed, sign, verify

__all__ = [
    "LANE", "MfaAttestationError", "SimulatedIdP", "SyntheticPerson", "TwoPersonError",
    "build_two_person_approval", "verify_mfa_attestation",
]

LANE: Final = "TEST"
_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_METHODS: Final = frozenset({"TOTP", "WEBAUTHN", "PUSH"})
_UNSIGNED: Final = frozenset({"signature"})
_FIELDS: Final = frozenset({
    "type", "lane", "person_id", "session_id", "method", "issued_at", "expires_at", "nonce", "signature"})
DEFAULT_TTL_SECONDS: Final = 300


class MfaAttestationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TwoPersonError(ValueError):
    pass


def _ident(value: object, code: str = "IDENTITY_INVALID") -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(code)
    return value


def _message(body: dict[str, object]) -> bytes:
    unsigned = {k: v for k, v in body.items() if k not in _UNSIGNED}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


@dataclass(frozen=True)
class SyntheticPerson:
    person_id: str
    login: str
    public_key_hex: str
    lane: str = LANE
    synthetic: bool = True
    production_entitlement: bool = False


class SimulatedIdP:
    """Deterministic synthetic IdP: all key material derives from ``label`` and the person id."""

    def __init__(self, label: str = "SIM-IDP-A") -> None:
        self.label = _ident(label, "IDP_LABEL_INVALID")
        self._seed = hashlib.sha256(("idp|" + label).encode("ascii")).digest()
        self.public_key_hex = public_key_from_seed(self._seed).hex()
        self._persons: dict[str, SyntheticPerson] = {}
        self._sessions: dict[str, str] = {}  # session_id -> person_id
        self._session_counter: dict[str, int] = {}
        self._nonce_counter = 0
        self._seen_nonces: set[str] = set()

    def _person_seed(self, person_id: str) -> bytes:
        return hashlib.sha256(("person|" + self.label + "|" + person_id).encode("ascii")).digest()

    def provision_person(self, person_id: str) -> SyntheticPerson:
        _ident(person_id, "PERSON_ID_INVALID")
        if person_id in self._persons:
            return self._persons[person_id]
        person = SyntheticPerson(
            person_id=person_id, login=f"sim.{person_id.lower()}@synthetic.invalid",
            public_key_hex=public_key_from_seed(self._person_seed(person_id)).hex())
        self._persons[person_id] = person
        return person

    def person_signing_seed(self, person_id: str) -> bytes:
        if person_id not in self._persons:
            raise KeyError("PERSON_UNKNOWN")
        return self._person_seed(person_id)

    def open_session(self, person_id: str) -> str:
        if person_id not in self._persons:
            raise KeyError("PERSON_UNKNOWN")
        n = self._session_counter.get(person_id, 0) + 1
        self._session_counter[person_id] = n
        digest = hashlib.sha256(f"session|{self.label}|{person_id}|{n}".encode("ascii")).hexdigest()[:16]
        session_id = f"sess-{digest}"
        self._sessions[session_id] = person_id
        return session_id

    def session_owner(self, session_id: str) -> str | None:
        return self._sessions.get(session_id)

    def issue_mfa_attestation(self, person_id: str, session_id: str, issued_at: int, *,
                              method: str = "TOTP", ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict[str, object]:
        if person_id not in self._persons:
            raise KeyError("PERSON_UNKNOWN")
        if self._sessions.get(session_id) != person_id:
            raise ValueError("SESSION_NOT_OWNED_BY_PERSON")
        if method not in _METHODS:
            raise ValueError("MFA_METHOD_INVALID")
        if type(issued_at) is not int or type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("MFA_TIME_INVALID")
        self._nonce_counter += 1
        nonce = hashlib.sha256(f"nonce|{self.label}|{self._nonce_counter}".encode("ascii")).hexdigest()
        body: dict[str, object] = {
            "type": "MFA", "lane": LANE, "person_id": person_id, "session_id": session_id, "method": method,
            "issued_at": issued_at, "expires_at": issued_at + ttl_seconds, "nonce": nonce}
        body["signature"] = sign(self._seed, _message(body)).hex()
        return body

    def verify(self, attestation: dict[str, object], now: int, expected_person: str,
               expected_session: str) -> bool:
        """Verify against this IdP's key and its own replay ledger (a nonce is accepted once)."""
        return verify_mfa_attestation(self.public_key_hex, attestation, now, expected_person, expected_session,
                                      seen_nonces=self._seen_nonces)


def verify_mfa_attestation(idp_public_key_hex: str, attestation: object, now: int, expected_person: str,
                           expected_session: str, *, seen_nonces: set[str] | None = None) -> bool:
    """Return True or raise ``MfaAttestationError``. The nonce is recorded in ``seen_nonces`` only on success.

    Replay protection exists only across calls that share the same ``seen_nonces`` set.
    """
    if not isinstance(attestation, dict) or set(attestation) != _FIELDS:
        raise MfaAttestationError("MFA_SHAPE_INVALID")
    if attestation["lane"] != LANE or attestation["type"] != "MFA":
        raise MfaAttestationError("MFA_LANE_MARKER_MISSING")
    try:
        key = bytes.fromhex(idp_public_key_hex)
        sig = bytes.fromhex(attestation["signature"])  # type: ignore[arg-type]
        message = _message(attestation)
    except (ValueError, TypeError):
        raise MfaAttestationError("MFA_SIGNATURE_INVALID") from None
    if not verify(key, message, sig):
        raise MfaAttestationError("MFA_SIGNATURE_INVALID")
    issued, expires, nonce = attestation["issued_at"], attestation["expires_at"], attestation["nonce"]
    if (type(issued) is not int or type(expires) is not int or type(now) is not int
            or type(nonce) is not str or _HEX64.fullmatch(nonce) is None
            or attestation["method"] not in _METHODS):
        raise MfaAttestationError("MFA_SHAPE_INVALID")
    if now < issued or now >= expires:
        raise MfaAttestationError("MFA_EXPIRED")
    if attestation["person_id"] != expected_person:
        raise MfaAttestationError("MFA_PERSON_MISMATCH")
    if attestation["session_id"] != expected_session:
        raise MfaAttestationError("MFA_SESSION_MISMATCH")
    if seen_nonces is None:
        seen_nonces = set()
    if nonce in seen_nonces:
        raise MfaAttestationError("MFA_NONCE_REPLAYED")
    seen_nonces.add(nonce)
    return True


def build_two_person_approval(idp: SimulatedIdP, requester_id: str, requester_session: str,
                              approver_id: str, approver_session: str, now: int) -> dict[str, object]:
    """Build approval material for a requester and a distinct approver, each with a fresh MFA attestation."""
    if requester_id == approver_id:
        raise TwoPersonError("SAME_PERSON")
    if requester_session == approver_session:
        raise TwoPersonError("SAME_SESSION")
    req, app = idp.provision_person(requester_id), idp.provision_person(approver_id)
    if req.login == app.login:
        raise TwoPersonError("SAME_LOGIN")
    if idp.session_owner(requester_session) != requester_id or idp.session_owner(approver_session) != approver_id:
        raise TwoPersonError("SESSION_OWNER_MISMATCH")
    return {
        "lane": LANE,
        "requester": {"person_id": requester_id, "login": req.login, "session_id": requester_session,
                      "mfa": idp.issue_mfa_attestation(requester_id, requester_session, now)},
        "approver": {"person_id": approver_id, "login": app.login, "session_id": approver_session,
                     "mfa": idp.issue_mfa_attestation(approver_id, approver_session, now)},
    }
