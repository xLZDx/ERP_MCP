"""HTTP client for the separate S13 development anchor service.

This adapter deliberately advertises a TEST sink: the dev service is outside the PostgreSQL
process, but it is not qualified for production retention or host-administrator rollback. Signed
authority responses are verified here before they are converted into the coordinator's evidence
envelopes. Latestness and checkpoint-key authorization use distinct pinned public roots.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ._common import Scope
from .checkpoint import (
    CheckpointKeyAuthorization,
    CheckpointKeyAuthorizationBasis,
    CheckpointLatestnessEvidence,
    CheckpointRecord,
    checkpoint_identity,
)

_LATESTNESS_DOMAIN = b"ERP_MCP:S13:ANCHOR-LATESTNESS:v1"
_KEY_AUTH_DOMAIN = b"ERP_MCP:S13:ANCHOR-KEY-AUTH:v1"
_LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_LOWER_HEX_128 = re.compile(r"^[0-9a-f]{128}$")
_LATESTNESS_FIELDS = frozenset({
    "tenant_id", "company_id", "checkpoint_digest", "challenge_nonce", "provider_id",
    "provider_revision", "authority_id", "authority_revision", "authority_event_id",
    "policy_version", "proof_digest",
})
_KEY_AUTH_FIELDS = frozenset({
    "tenant_id", "company_id", "key_id", "public_key_digest", "checkpoint_digest",
    "challenge_nonce", "authority_id", "authority_revision", "authority_event_id",
    "policy_version", "basis", "receipt_id", "accepted_at",
})
_MAX_RESPONSE_BYTES = 1024 * 1024


class DevAnchorClientError(RuntimeError):
    """Stable, sanitized client error for the dev anchor boundary."""

    def __init__(self, code: str = "ANCHOR_SERVICE_UNAVAILABLE") -> None:
        super().__init__(code)
        self.code = code


def _is_loopback_url(value: str) -> bool:
    if type(value) is not str or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return False
        if parsed.query or parsed.fragment or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if host == "localhost":
            return True
        return ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _signature_preimage(domain: bytes, evidence: dict[str, Any]) -> bytes:
    return domain + b"\n" + _canonical_json(evidence)


def latestness_proof_preimage(evidence: dict[str, Any]) -> bytes:
    """Canonical unsigned bytes hashed into ``proof_digest`` (excluding that field)."""
    if type(evidence) is not dict or set(evidence) != _LATESTNESS_FIELDS:
        raise DevAnchorClientError("ANCHOR_PROOF_INVALID")
    unsigned = {key: value for key, value in evidence.items() if key != "proof_digest"}
    return _signature_preimage(_LATESTNESS_DOMAIN, unsigned)


def latestness_signature_preimage(evidence: dict[str, Any]) -> bytes:
    """Canonical bytes signed by the service, including the non-self-referential proof digest."""
    if type(evidence) is not dict or set(evidence) != _LATESTNESS_FIELDS:
        raise DevAnchorClientError("ANCHOR_PROOF_INVALID")
    return _signature_preimage(_LATESTNESS_DOMAIN, evidence)


def key_authorization_preimage(evidence: dict[str, Any]) -> bytes:
    """Canonical bytes signed by the separate checkpoint-key authority."""
    if type(evidence) is not dict or set(evidence) != _KEY_AUTH_FIELDS:
        raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID")
    return _signature_preimage(_KEY_AUTH_DOMAIN, evidence)


def _verify_ed25519(public_key: bytes, preimage: bytes, signature_hex: Any) -> bool:
    if (type(public_key) is not bytes or len(public_key) != 32
            or type(signature_hex) is not str or _LOWER_HEX_128.fullmatch(signature_hex) is None):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(bytes.fromhex(signature_hex), preimage)
        return True
    except Exception:
        return False


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if type(value) is not str or len(value) > 64:
        raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID")
    return parsed.astimezone(UTC)


def _parse_record_timestamp(value: Any) -> datetime:
    """Parse the anchor service's canonical UTC ISO timestamp."""
    if type(value) is not str or len(value) > 64:
        raise DevAnchorClientError("ANCHOR_RECORD_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise DevAnchorClientError("ANCHOR_RECORD_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DevAnchorClientError("ANCHOR_RECORD_INVALID")
    return parsed.astimezone(UTC)


def _record_json(record: CheckpointRecord) -> dict[str, Any]:
    if (type(record) is not CheckpointRecord or type(record.signed_at) is not datetime
            or record.signed_at.tzinfo is None or record.signed_at.utcoffset() is None):
        raise DevAnchorClientError("CHECKPOINT_INVALID")
    try:
        signed_at = record.signed_at.astimezone(UTC).isoformat(timespec="microseconds").replace(
            "+00:00", "Z",
        )
        payload = {
            "tenant_id": record.tenant_id,
            "company_id": record.company_id,
            "seq": record.seq,
            "head_hash": record.head_hash,
            "signed_at": signed_at,
            "key_id": record.key_id,
            "signature": record.signature,
            "sink_id": record.sink_id,
            "sink_kind": record.sink_kind,
        }
        if (any(type(payload[key]) is not str for key in (
                    "tenant_id", "company_id", "head_hash", "key_id", "signature", "sink_id", "sink_kind"))
                or type(record.seq) is not int or record.seq < 1
                or _LOWER_HEX_64.fullmatch(record.head_hash) is None
                or _LOWER_HEX_128.fullmatch(record.signature) is None
                or record.sink_kind != "TEST"):
            raise DevAnchorClientError("CHECKPOINT_INVALID")
        return payload
    except DevAnchorClientError:
        raise
    except Exception:
        raise DevAnchorClientError("CHECKPOINT_INVALID") from None


def _parse_record(value: Any, *, scope: Scope, service_id: str, seq: int | None = None) -> CheckpointRecord:
    fields = {"tenant_id", "company_id", "seq", "head_hash", "signed_at", "key_id", "signature",
              "sink_id", "sink_kind"}
    if type(value) is not dict or set(value) != fields:
        raise DevAnchorClientError("ANCHOR_RECORD_INVALID")
    try:
        signed_at = _parse_record_timestamp(value["signed_at"])
        record = CheckpointRecord(
            tenant_id=value["tenant_id"], company_id=value["company_id"], seq=value["seq"],
            head_hash=value["head_hash"], signed_at=signed_at, key_id=value["key_id"],
            signature=value["signature"], sink_id=value["sink_id"], sink_kind=value["sink_kind"],
        )
    except (TypeError, ValueError):
        raise DevAnchorClientError("ANCHOR_RECORD_INVALID") from None
    if (type(record.tenant_id) is not str or record.tenant_id != scope.tenant_id
            or type(record.company_id) is not str or record.company_id != scope.company_id
            or type(record.seq) is not int or record.seq < 1
            or (seq is not None and record.seq != seq)
            or type(record.head_hash) is not str or _LOWER_HEX_64.fullmatch(record.head_hash) is None
            or type(record.key_id) is not str or not record.key_id or len(record.key_id) > 128
            or type(record.signature) is not str or _LOWER_HEX_128.fullmatch(record.signature) is None
            or record.sink_id != service_id or record.sink_kind != "TEST"):
        raise DevAnchorClientError("ANCHOR_RECORD_INVALID")
    return record


class DevAnchorClient:
    """TEST-sink client plus separately verified latestness/key-history authorities.

    The service is a real separate dev process, not an in-memory test double. The TEST sink kind
    intentionally keeps it ineligible for production dispatch and permit issuance.
    """

    is_test_double = False
    kind = "TEST"

    __slots__ = (
        "sink_id", "_base_url", "_service_token", "_latestness_public_key",
        "_key_authority_public_key", "_latestness_authority_id", "_key_authority_id", "_http",
        "_owns_http",
    )

    def __init__(self, *, base_url: str, service_id: str, service_token: str,
                 latestness_authority_id: str, latestness_public_key: bytes,
                 key_authority_id: str, key_authority_public_key: bytes,
                 http_client: httpx.AsyncClient | None = None) -> None:
        if (not _is_loopback_url(base_url) or type(service_id) is not str or not service_id
                or len(service_id) > 128 or type(service_token) is not str or not service_token
                or len(service_token) > 512 or type(latestness_authority_id) is not str
                or not latestness_authority_id or len(latestness_authority_id) > 128
                or type(key_authority_id) is not str or not key_authority_id or len(key_authority_id) > 128
                or type(latestness_public_key) is not bytes or len(latestness_public_key) != 32
                or type(key_authority_public_key) is not bytes or len(key_authority_public_key) != 32
                or hmac.compare_digest(latestness_public_key, key_authority_public_key)):
            raise ValueError("ANCHOR_CLIENT_CONFIGURATION_INVALID")
        self.sink_id = service_id
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._latestness_authority_id = latestness_authority_id
        self._latestness_public_key = latestness_public_key
        self._key_authority_id = key_authority_id
        self._key_authority_public_key = key_authority_public_key
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(5.0), follow_redirects=False)
        self._owns_http = http_client is None

    def __repr__(self) -> str:
        return f"DevAnchorClient(sink_id={self.sink_id!r}, credentials=<redacted>)"

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def write(self, record: CheckpointRecord) -> None:
        payload = _record_json(record)
        if record.sink_id != self.sink_id:
            raise DevAnchorClientError("CHECKPOINT_SCOPE_INVALID")
        await self._request("POST", "/v1/checkpoints", json={"record": payload})

    async def read_back(self, scope: Scope, seq: int) -> CheckpointRecord | None:
        if type(seq) is not int or seq < 1:
            raise DevAnchorClientError("CHECKPOINT_SCOPE_INVALID")
        response = await self._request(
            "GET", "/v1/checkpoints/read-back",
            params={"tenant_id": scope.tenant_id, "company_id": scope.company_id, "seq": str(seq)},
            allow_not_found=True,
        )
        if response is None:
            return None
        if set(response) != {"record"}:
            raise DevAnchorClientError("ANCHOR_RESPONSE_INVALID")
        return _parse_record(response["record"], scope=scope, service_id=self.sink_id, seq=seq)

    async def latest(self, scope: Scope) -> CheckpointRecord | None:
        response = await self._request(
            "GET", "/v1/checkpoints/latest",
            params={"tenant_id": scope.tenant_id, "company_id": scope.company_id},
            allow_not_found=True,
        )
        if response is None:
            return None
        if set(response) != {"record"}:
            raise DevAnchorClientError("ANCHOR_RESPONSE_INVALID")
        return _parse_record(response["record"], scope=scope, service_id=self.sink_id)

    async def attest_latest(self, scope: Scope, record: CheckpointRecord,
                            challenge_nonce: str) -> CheckpointLatestnessEvidence | None:
        try:
            digest = checkpoint_identity(record)
        except Exception:
            raise DevAnchorClientError("CHECKPOINT_INVALID") from None
        if (_LOWER_HEX_64.fullmatch(digest) is None or type(challenge_nonce) is not str
                or _LOWER_HEX_64.fullmatch(challenge_nonce) is None
                or record.tenant_id != scope.tenant_id or record.company_id != scope.company_id
                or record.sink_id != self.sink_id or record.sink_kind != "TEST"):
            raise DevAnchorClientError("CHECKPOINT_SCOPE_INVALID")
        response = await self._request("POST", "/v1/latestness", json={
            "tenant_id": scope.tenant_id,
            "company_id": scope.company_id,
            "checkpoint_digest": digest,
            "challenge_nonce": challenge_nonce,
        })
        evidence, signature = self._signed_envelope(response, _LATESTNESS_FIELDS)
        proof_preimage = latestness_proof_preimage(evidence)
        proof_digest = hashlib.sha256(proof_preimage).hexdigest()
        signature_preimage = latestness_signature_preimage(evidence)
        if (not _verify_ed25519(self._latestness_public_key, signature_preimage, signature)
                or evidence.get("proof_digest") != proof_digest):
            raise DevAnchorClientError("ANCHOR_PROOF_INVALID")
        expected = {
            "tenant_id": scope.tenant_id,
            "company_id": scope.company_id,
            "checkpoint_digest": digest,
            "challenge_nonce": challenge_nonce,
            "provider_id": self.sink_id,
            "authority_id": self._latestness_authority_id,
        }
        if any(evidence.get(key) != value for key, value in expected.items()):
            raise DevAnchorClientError("ANCHOR_PROOF_INVALID")
        if (type(evidence.get("provider_revision")) is not int or evidence["provider_revision"] < 1
                or type(evidence.get("authority_revision")) is not int or evidence["authority_revision"] < 1
                or not self._bounded_text(evidence.get("authority_event_id"))
                or not self._bounded_text(evidence.get("policy_version"))):
            raise DevAnchorClientError("ANCHOR_PROOF_INVALID")
        return CheckpointLatestnessEvidence(**evidence)

    async def authorize_checkpoint(self, scope: Scope, record: CheckpointRecord,
                                  challenge_nonce: str) -> CheckpointKeyAuthorization | None:
        try:
            checkpoint_digest = checkpoint_identity(record)
        except Exception:
            raise DevAnchorClientError("CHECKPOINT_INVALID") from None
        if (type(challenge_nonce) is not str or _LOWER_HEX_64.fullmatch(challenge_nonce) is None
                or record.tenant_id != scope.tenant_id or record.company_id != scope.company_id
                or record.sink_id != self.sink_id or record.sink_kind != "TEST"):
            raise DevAnchorClientError("CHECKPOINT_SCOPE_INVALID")
        response = await self._request("POST", "/v1/key-authorizations", json={
            "record": _record_json(record),
            "challenge_nonce": challenge_nonce,
        }, allow_denied=True)
        if response is None:
            return None
        evidence, signature = self._signed_envelope(response, _KEY_AUTH_FIELDS)
        preimage = key_authorization_preimage(evidence)
        if not _verify_ed25519(self._key_authority_public_key, preimage, signature):
            raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID")
        expected = {
            "tenant_id": scope.tenant_id,
            "company_id": scope.company_id,
            "key_id": record.key_id,
            "checkpoint_digest": checkpoint_digest,
            "challenge_nonce": challenge_nonce,
            "authority_id": self._key_authority_id,
        }
        if any(evidence.get(key) != value for key, value in expected.items()):
            raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID")
        basis = evidence.get("basis")
        try:
            parsed_basis = CheckpointKeyAuthorizationBasis(basis)
        except (TypeError, ValueError):
            raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID") from None
        accepted_at = _parse_timestamp(evidence.get("accepted_at"))
        receipt_id = evidence.get("receipt_id")
        if parsed_basis is CheckpointKeyAuthorizationBasis.ACTIVE:
            if receipt_id is not None or accepted_at is not None:
                raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID")
        elif (type(receipt_id) is not str or not receipt_id or len(receipt_id) > 256
              or accepted_at is None):
            raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID")
        if (not _LOWER_HEX_64.fullmatch(str(evidence.get("public_key_digest", "")))
                or not self._bounded_text(evidence.get("authority_event_id"))
                or type(evidence.get("authority_revision")) is not int
                or evidence["authority_revision"] < 1
                or not self._bounded_text(evidence.get("policy_version"))):
            raise DevAnchorClientError("ANCHOR_KEY_AUTH_INVALID")
        return CheckpointKeyAuthorization(
            tenant_id=evidence["tenant_id"], company_id=evidence["company_id"],
            key_id=evidence["key_id"], public_key_digest=evidence["public_key_digest"],
            checkpoint_digest=evidence["checkpoint_digest"],
            challenge_nonce=evidence["challenge_nonce"], authority_id=evidence["authority_id"],
            authority_revision=evidence["authority_revision"],
            authority_event_id=evidence["authority_event_id"], policy_version=evidence["policy_version"],
            basis=parsed_basis, receipt_id=receipt_id, accepted_at=accepted_at,
        )

    async def _request(self, method: str, path: str, *, params: dict[str, str] | None = None,
                       json: dict[str, Any] | None = None, allow_not_found: bool = False,
                       allow_denied: bool = False) -> dict[str, Any] | None:
        try:
            response = await self._http.request(
                method, self._base_url + path, params=params, json=json,
                headers={"Authorization": "Bearer " + self._service_token},
            )
        except Exception:
            raise DevAnchorClientError() from None
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise DevAnchorClientError("ANCHOR_RESPONSE_INVALID")
        if allow_not_found and response.status_code == 404:
            return None
        if allow_denied and response.status_code in {403, 404}:
            return None
        if not response.is_success:
            code = "ANCHOR_SERVICE_UNAVAILABLE"
            try:
                body = response.json()
                candidate = (body.get("error", body.get("code"))
                             if type(body) is dict else None)
                if type(candidate) is str and re.fullmatch(r"[A-Z0-9_]{1,64}", candidate):
                    code = candidate
            except Exception:
                pass
            raise DevAnchorClientError(code)
        try:
            body = response.json()
        except Exception:
            raise DevAnchorClientError("ANCHOR_RESPONSE_INVALID") from None
        if type(body) is not dict:
            raise DevAnchorClientError("ANCHOR_RESPONSE_INVALID")
        return body

    @staticmethod
    def _signed_envelope(body: dict[str, Any] | None,
                         fields: frozenset[str]) -> tuple[dict[str, Any], str]:
        if type(body) is not dict or set(body) != {"evidence", "signature"}:
            raise DevAnchorClientError("ANCHOR_PROOF_INVALID")
        evidence, signature = body["evidence"], body["signature"]
        if (type(evidence) is not dict or set(evidence) != fields
                or type(signature) is not str or _LOWER_HEX_128.fullmatch(signature) is None):
            raise DevAnchorClientError("ANCHOR_PROOF_INVALID")
        return evidence, signature

    @staticmethod
    def _bounded_text(value: Any) -> bool:
        return type(value) is str and bool(value) and len(value) <= 128
