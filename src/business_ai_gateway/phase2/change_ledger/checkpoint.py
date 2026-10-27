"""External checkpoint contract (CT5, S12 section 4/6) and the dispatch gate.

The required ``PyJWT[crypto]`` project dependency supplies the ``cryptography`` Ed25519 backend.
``Ed25519SignatureVerifier`` performs cryptographic verification against an injected immutable key
set; key provenance, scope and role authorization remain the responsibility of its trusted caller
and the database. ``UnwiredVerifier`` still fails closed until that trust source is composed.
``InMemoryCheckpointSink``, ``FakeSigner`` and
``FakeVerifier`` are TEST ONLY: ``DispatchGate`` stays DISABLED while any of them is wired, whatever
the ``real_checkpoint_sink`` flag says. It also stays disabled until a trusted runtime authority is
composed to authenticate provider capability/policy and current startup admission readiness.
Migration 007 establishes the checkpoint path; migration 015
replaces ``signature_ok`` with Ed25519 verification for Ed25519 keys while retaining keyed-hash
verification for legacy keys, and migration 019 requires Ed25519 at new signed-write boundaries.
Migration 021 also requires Ed25519 when attaching a permit signature. The checkpoint SQL path
requires the dedicated ``checkpoint_role`` identity and an ACTIVE scope-bound key with that role,
verifies the v2 ``checkpoint_payload`` (including sink kind and ID), then marks the row verified.
``issue_permit`` accepts only a verified REAL checkpoint with read-back confirmed, the ledger head at
its sequence, and a sequence at or after the change's APPLYING event; a TEST sink is refused. The
gate writes through the port's checkpoint identity (``as_class='checkpoint'`` by default) and leaves
authorization to SQL. A signer must produce canonical lowercase 128-character Ed25519 signature hex.
The test doubles in this module are not accepted by the operational gate. No real sink, trusted
checkpoint-key source, authenticated provider-policy authority, or signer is composed into the
product runtime. The lifecycle coordinator remains diagnostic and has no READY state; successful
single-checkpoint write/read-back cannot override missing startup/restore readiness.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID, uuid4

from ._common import LedgerError, Scope

_DISPATCH_GATE_IMMUTABLE_CONFIGURATION = frozenset({
    "_ledger", "_sink", "_signer", "_verifier", "_flag",
    "_private_writer_schema_enabled", "_runtime_authority",
})
_CHECKPOINT_RUNTIME_AUTHORITY_TIMEOUT_SECONDS = 5.0


class GateDisabled(Exception):
    """The gate refuses a permit when trusted checkpoint dependencies are incomplete."""

    code = "CHECKPOINT_UNAVAILABLE"


class CheckpointUnavailable(Exception):
    code = "CHECKPOINT_UNAVAILABLE"


class PermitRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _ts(value: datetime) -> str:
    """UTC, microseconds, no zone suffix (checkpoint signing payload)."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def content_hash_of(payload_text: str) -> str:
    """sha256 of the exact payload text that is signed and sent to change_ledger.record_evidence."""
    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()


def evidence_binding(change_id: str, kind: str, content_hash: str, observed_at: datetime,
                     generation: int | None = None, call_id: str | None = None) -> str:
    """Mirror of change_ledger.evidence_binding (007): ``id:kind:hash:UTC-microseconds-Z:generation:call_id``
    where a missing generation / call id is the empty string (AUTH_RECEIPT carries neither)."""
    gen = "" if generation is None else str(generation)
    call = "" if call_id is None else str(call_id)
    raw = f"{change_id}:{kind}:{content_hash}:{_ts(observed_at)}Z:{gen}:{call}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def permit_signing_payload(permit_digest: str) -> bytes:
    """Exact text attach_permit_signature checks the signature of (007): ``change-ledger-permit|v1|digest``."""
    return f"change-ledger-permit|v1|{permit_digest}".encode()


@dataclass(frozen=True)
class CheckpointRecord:
    tenant_id: str
    company_id: str
    seq: int
    head_hash: str
    signed_at: datetime
    key_id: str
    signature: str
    sink_id: str
    sink_kind: str

    def signing_payload(self) -> bytes:
        """Mirror of change_ledger.checkpoint_payload (007, v2): sink kind and id are part of the signed text."""
        return (f"change-ledger-checkpoint|v2|{self.tenant_id}|{self.company_id}|{self.seq}|{self.head_hash}|"
                f"{_ts(self.signed_at)}|{self.key_id}|{self.sink_kind}|{self.sink_id}").encode()


class CheckpointSigner(Protocol):
    key_id: str
    key_version: str
    is_test_double: bool

    def sign(self, payload: bytes) -> str: ...


class SignatureVerifier(Protocol):
    is_test_double: bool

    def verify(self, key_id: str, payload: bytes, signature: str) -> bool: ...


class CheckpointSink(Protocol):
    """External append-only store outside the DB administrator's trust boundary (D9).

    ``latest`` must return the authenticated, anti-rollback latest record for exactly the
    requested scope. Signature verification alone does not establish that it is the newest
    retained record; implementations must preserve that provider guarantee independently.
    """

    kind: str  # 'REAL' or 'TEST'
    sink_id: str

    async def write(self, record: CheckpointRecord) -> None: ...

    async def read_back(self, scope: Scope, seq: int) -> CheckpointRecord | None: ...

    async def latest(self, scope: Scope) -> CheckpointRecord | None: ...


class CheckpointRuntimeAuthority(Protocol):
    """Trusted production authority for provider policy and startup admission readiness.

    Implementations must authenticate the configured provider capability under an approved
    deployment policy. They must also independently verify the provider's authoritative latest
    checkpoint and current lifecycle readiness before admission. A sink's ``kind`` string or a
    successful per-call write/read-back is not evidence for either property. No production
    implementation is currently composed; absence therefore keeps the dispatch gate disabled.
    """

    is_test_double: bool

    async def require_provider_qualified(
            self, scope: Scope, *, sink_id: str, sink_kind: str,
            signer_key_id: str, signer_key_version: str | None) -> None: ...

    async def require_admission_ready(self, scope: Scope) -> None: ...


class UnwiredVerifier:
    """Fail-closed verifier used when no trusted checkpoint-key source is composed."""

    is_test_double = False

    def verify(self, key_id: str, payload: bytes, signature: str) -> bool:
        return False


class Ed25519SignatureVerifier:
    """Verify checkpoint signatures against an immutable set of registered public keys.

    The caller must build this object from an authenticated, scope-appropriate snapshot of active
    ``checkpoint_role`` keys. This class proves only the signature; it does not establish key
    provenance, scope, role, validity, revocation, or anti-rollback freshness. Database routines
    remain authoritative for those checks.
    """

    __slots__ = ("_public_keys",)
    is_test_double = False
    _MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
    _KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    _SIGNATURE_HEX = re.compile(r"^[0-9a-f]{128}$")

    def __init__(self, public_keys: dict[str, bytes]) -> None:
        if type(public_keys) is not dict or not public_keys:
            raise ValueError("CHECKPOINT_KEY_SET_INVALID")
        validated: dict[str, bytes] = {}
        for key_id, public_key in public_keys.items():
            if (type(key_id) is not str or self._KEY_ID.fullmatch(key_id) is None
                    or type(public_key) is not bytes or len(public_key) != 32):
                raise ValueError("CHECKPOINT_KEY_SET_INVALID")
            validated[key_id] = bytes(public_key)
        self._public_keys = MappingProxyType(validated)

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("CHECKPOINT_VERIFIER_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("CHECKPOINT_VERIFIER_IMMUTABLE")

    def verify(self, key_id: str, payload: bytes, signature: str) -> bool:
        if (type(key_id) is not str or self._KEY_ID.fullmatch(key_id) is None
                or type(payload) is not bytes or not payload
                or len(payload) > self._MAX_PAYLOAD_BYTES
                or type(signature) is not str or self._SIGNATURE_HEX.fullmatch(signature) is None):
            return False
        public_key = self._public_keys.get(key_id)
        if public_key is None:
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            Ed25519PublicKey.from_public_bytes(public_key).verify(bytes.fromhex(signature), payload)
            return True
        except Exception:
            return False


class FakeSigner:
    """TEST ONLY. Not a signature scheme."""

    is_test_double = True

    def __init__(self, key_id: str = "test-key", key_version: str = "test-version"):
        self.key_id = key_id
        self.key_version = key_version

    def sign(self, payload: bytes) -> str:
        return hashlib.sha256(b"FAKE|" + self.key_id.encode() + b"|" + payload).hexdigest()


class FakeVerifier:
    """TEST ONLY: verifies FakeSigner output."""

    is_test_double = True

    def verify(self, key_id: str, payload: bytes, signature: str) -> bool:
        return signature == hashlib.sha256(b"FAKE|" + key_id.encode() + b"|" + payload).hexdigest()


class InMemoryCheckpointSink:
    """TEST ONLY. Always reports kind TEST."""

    kind = "TEST"

    def __init__(self, sink_id: str = "in-memory-test"):
        self.sink_id = sink_id
        self._rows: dict[tuple[str, str, int], CheckpointRecord] = {}

    async def write(self, record: CheckpointRecord) -> None:
        self._rows[(record.tenant_id, record.company_id, record.seq)] = record

    async def read_back(self, scope: Scope, seq: int) -> CheckpointRecord | None:
        return self._rows.get((scope.tenant_id, scope.company_id, seq))

    async def latest(self, scope: Scope) -> CheckpointRecord | None:
        """Return the highest-sequence record for this exact scope (TEST ONLY)."""
        records = (record for (tenant_id, company_id, _), record in self._rows.items()
                   if tenant_id == scope.tenant_id and company_id == scope.company_id)
        return max(records, key=lambda record: record.seq, default=None)


class LedgerPort(Protocol):
    """The slice of the SQL port the gate needs (satisfied by sql_ledger.SqlChangeLedger).

    ``record_checkpoint`` and ``attach_permit_signature`` run as the checkpoint identity, ``ledger_head`` and
    ``issue_permit`` as the worker identity; the SQL port selects these by its per-method default class.
    """

    async def ledger_head(self, scope: Scope) -> dict[str, Any]: ...

    async def record_checkpoint(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                sink_id: str, key_id: str, signature: str, signed_at: datetime,
                                read_back: bool) -> int: ...

    async def record_checkpoint_s13(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                    sink_id: str, key_id: str, signature: str, signed_at: datetime,
                                    read_back: bool) -> int: ...

    async def release_hold(self, scope: Scope, hold_id: UUID,
                           release_evidence: dict[str, Any]) -> datetime: ...

    async def operator_resolve_s13(self, scope: Scope, change_id: UUID,
                                   dispatch_cas_id: UUID, cosign_id: UUID,
                                   receipt_ref: str, completion_ref: str,
                                   outcome_ref: str, challenge_ref: str | None = None,
                                   read_attestation_ref: str | None = None) -> dict[str, Any]: ...

    async def issue_permit(self, scope: Scope, change_id: Any, generation: int) -> dict[str, Any]: ...

    async def attach_permit_signature(self, scope: Scope, change_id: Any, generation: int,
                                      key_id: str, signature: str) -> None: ...

    async def dispatch_intent_for_call(self, scope: Scope, call_id: UUID,
                                       as_class: str = "worker") -> dict[str, Any] | None: ...

    async def permit_binding_for_intent(self, scope: Scope, dispatch_intent_id: UUID,
                                        as_class: str = "worker") -> dict[str, Any] | None: ...

    async def issue_permit_s13(self, scope: Scope, change_id: UUID, generation: int,
                               dispatch_intent_id: UUID, permit_id: UUID,
                               signer_key_id: str, signer_key_version: str,
                               signature: str) -> dict[str, Any]: ...


class DispatchGate:
    """Refuses to issue a dispatch permit unless a checkpoint covering the head was written AND read back.

    Disabled unless ``real_checkpoint_sink`` is True, the sink is REAL, signer and verifier are not
    test doubles, and a runtime authority is supplied. That authority must authenticate provider
    capability and approved policy, and establish current admission readiness. The structural
    protocol and ``enabled`` property do not prove those claims; only a trusted production
    composition may supply the authority. No such implementation is currently composed, so product
    dispatch remains DISABLED. SQL raises (never returns) a refusal; it is surfaced as
    CheckpointUnavailable (CHECKPOINT_UNAVAILABLE) or PermitRefused(code).
    """

    __slots__ = (
        "_ledger", "_sink", "_signer", "_verifier", "_flag",
        "_private_writer_schema_enabled", "_runtime_authority",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if name in _DISPATCH_GATE_IMMUTABLE_CONFIGURATION and hasattr(self, name):
            raise AttributeError("S13_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in _DISPATCH_GATE_IMMUTABLE_CONFIGURATION:
            raise AttributeError("S13_CONFIGURATION_IMMUTABLE")
        object.__delattr__(self, name)

    def __init__(self, ledger: LedgerPort, sink: CheckpointSink, signer: CheckpointSigner,
                 verifier: SignatureVerifier, *, real_checkpoint_sink: bool = False,
                 private_writer_schema_enabled: bool = False,
                 runtime_authority: CheckpointRuntimeAuthority | None = None):
        if type(real_checkpoint_sink) is not bool or type(private_writer_schema_enabled) is not bool:
            raise ValueError("S13_CONFIGURATION_INVALID")
        ledger_s13 = getattr(ledger, "private_writer_schema_enabled", False)
        if (type(ledger_s13) is not bool
                or ledger_s13 is not private_writer_schema_enabled):
            raise ValueError("S13_CONFIGURATION_MISMATCH")
        self._ledger, self._sink, self._signer, self._verifier = ledger, sink, signer, verifier
        self._flag = real_checkpoint_sink
        self._private_writer_schema_enabled = private_writer_schema_enabled
        if runtime_authority is not None and (
                not callable(getattr(type(runtime_authority), "require_provider_qualified", None))
                or not callable(getattr(type(runtime_authority), "require_admission_ready", None))):
            raise ValueError("S13_CHECKPOINT_RUNTIME_AUTHORITY_INCOMPLETE")
        self._runtime_authority = runtime_authority

    @property
    def enabled(self) -> bool:
        return (self._flag and self._sink.kind == "REAL"
                and not getattr(self._signer, "is_test_double", True)
                and not getattr(self._verifier, "is_test_double", True)
                and self._runtime_authority is not None
                and getattr(self._runtime_authority, "is_test_double", True) is False)

    async def _require_runtime_authority(self, scope: Scope, *, admission: bool) -> None:
        """Require provider policy on every path and fresh readiness before admission.

        Each result must be exactly ``None``; a returned false/denial value is never interpreted as
        success. The bounded call is still only a preflight: production activation remains blocked
        until readiness is bound to a durable lifecycle epoch or fence consumed by permit SQL.
        """
        if not self.enabled or self._runtime_authority is None:
            raise CheckpointUnavailable("CHECKPOINT_UNAVAILABLE")
        try:
            async with asyncio.timeout(_CHECKPOINT_RUNTIME_AUTHORITY_TIMEOUT_SECONDS):
                provider_result = await self._runtime_authority.require_provider_qualified(
                    scope,
                    sink_id=self._sink.sink_id,
                    sink_kind=self._sink.kind,
                    signer_key_id=self._signer.key_id,
                    signer_key_version=getattr(self._signer, "key_version", None),
                )
                if provider_result is not None:
                    raise CheckpointUnavailable("CHECKPOINT_UNAVAILABLE")
                if admission:
                    readiness_result = await self._runtime_authority.require_admission_ready(scope)
                    if readiness_result is not None:
                        raise CheckpointUnavailable("CHECKPOINT_UNAVAILABLE")
        except CheckpointUnavailable:
            raise
        except Exception:
            # Provider and deployment-policy details are not exposed through the dispatch surface.
            raise CheckpointUnavailable("CHECKPOINT_UNAVAILABLE") from None

    async def resolve_t16_s13(
            self, scope: Scope, change_id: UUID, dispatch_cas_id: UUID, cosign_id: UUID,
            receipt_ref: str, completion_ref: str, outcome_ref: str,
            challenge_ref: str | None = None,
            read_attestation_ref: str | None = None) -> dict[str, Any]:
        """Commit T16, checkpoint its exact event, then release its linked stop-effects holds.

        The SQL call is deliberately first: it authenticates the operator and independent
        recovery witness and commits the terminal state plus holds in one transaction. The
        external write/read-back and checkpoint registration happen afterward, outside that
        transaction. A provider failure therefore leaves the database holds in force. Repeating
        the same request is safe because SQL replays by cosign ID and the checkpoint timestamp is
        taken from the immutable event row.
        """
        if not self.enabled or not self._private_writer_schema_enabled:
            raise CheckpointUnavailable("CHECKPOINT_UNAVAILABLE")
        await self._require_runtime_authority(scope, admission=True)
        try:
            resolution = await self._ledger.operator_resolve_s13(
                scope, change_id, dispatch_cas_id, cosign_id, receipt_ref, completion_ref,
                outcome_ref, challenge_ref, read_attestation_ref,
            )
        except CheckpointUnavailable:
            raise
        except LedgerError as exc:
            raise CheckpointUnavailable(exc.code) from None
        except Exception:
            # The SQL transaction may have committed before transport failure. The caller can
            # retry with the same cosign/evidence tuple; the database replay key is stable.
            raise CheckpointUnavailable("S13_RESOLUTION_OUTCOME_UNKNOWN") from None
        checkpoint = await self.checkpoint_operator_resolution(scope, resolution)
        return {"resolution": resolution, "checkpoint": checkpoint}

    async def checkpoint_operator_resolution(self, scope: Scope,
                                             resolution: dict[str, Any]) -> dict[str, Any]:
        """Checkpoint the exact T16 terminal event before releasing its stop-effects holds.

        The database transition commits first and returns an immutable event identity. Provider
        I/O then happens outside a transaction. Any failure before exact read-back and checkpoint
        persistence leaves every ANCHOR_GAP hold open; a partial hold-release failure also leaves
        at least one scope base blocked and is safe to retry with the same resolution result.
        """
        if not self.enabled or not self._private_writer_schema_enabled:
            raise CheckpointUnavailable("CHECKPOINT_UNAVAILABLE")
        await self._require_runtime_authority(scope, admission=False)
        if not isinstance(resolution, dict) or resolution.get("checkpoint_required") is not True:
            raise CheckpointUnavailable("S13_RESOLUTION_CHECKPOINT_INVALID")
        if resolution.get("execution_state") not in {"APPLIED", "FAILED_APPLY"}:
            raise CheckpointUnavailable("S13_RESOLUTION_CHECKPOINT_INVALID")
        try:
            event_id_raw = resolution["event_id"]
            call_hold_id_raw = resolution["hold_id"]
            event_id = UUID(event_id_raw)
            event_seq = resolution["event_seq"]
            event_hash = resolution["event_hash"]
            signed_at_raw = resolution["checkpoint_signed_at"]
            call_hold_id = UUID(call_hold_id_raw)
            hold_ids_raw = resolution["checkpoint_hold_ids"]
            signed_at = (signed_at_raw if isinstance(signed_at_raw, datetime)
                         else datetime.fromisoformat(signed_at_raw))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise CheckpointUnavailable("S13_RESOLUTION_CHECKPOINT_INVALID") from None
        if (type(event_id_raw) is not str or str(event_id) != event_id_raw
                or type(call_hold_id_raw) is not str or str(call_hold_id) != call_hold_id_raw
                or event_id.int == 0 or call_hold_id.int == 0
                or type(event_seq) is not int or event_seq < 1
                or type(event_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", event_hash) is None
                or signed_at.tzinfo is None or signed_at.utcoffset() is None
                or type(hold_ids_raw) is not list or not hold_ids_raw):
            raise CheckpointUnavailable("S13_RESOLUTION_CHECKPOINT_INVALID")
        try:
            if any(type(value) is not str for value in hold_ids_raw):
                raise ValueError("hold UUID must be canonical text")
            hold_ids = [UUID(value) for value in hold_ids_raw]
        except (TypeError, ValueError, AttributeError):
            raise CheckpointUnavailable("S13_RESOLUTION_CHECKPOINT_INVALID") from None
        if (any(hold_id.int == 0 for hold_id in hold_ids)
                or any(str(hold_id) != raw for hold_id, raw in zip(hold_ids, hold_ids_raw, strict=True))
                or len(set(hold_ids)) != len(hold_ids)
                or call_hold_id in hold_ids):
            raise CheckpointUnavailable("S13_RESOLUTION_CHECKPOINT_INVALID")
        # Keep the call-owned hold until every scope ANCHOR_GAP hold is released. It is the
        # final stop-effects latch for this change if release is interrupted mid-batch.
        hold_ids.append(call_hold_id)

        signed_at = signed_at.astimezone(UTC)
        try:
            # A prior attempt may have written and verified this exact event checkpoint, then
            # failed while recording it or releasing the linked holds. Reuse that immutable
            # provider record before consulting the current signer: the database accepts exact
            # verified Ed25519-row replay even when its key was revoked for new checkpoints.
            record = await self._sink.read_back(scope, event_seq)
            reused_existing = record is not None
            if reused_existing:
                if (type(record) is not CheckpointRecord
                        or record.tenant_id != scope.tenant_id
                        or record.company_id != scope.company_id
                        or type(record.seq) is not int or record.seq != event_seq
                        or type(record.head_hash) is not str or record.head_hash != event_hash
                        or type(record.signed_at) is not datetime
                        or record.signed_at.tzinfo is None
                        or record.signed_at.utcoffset() is None
                        or record.signed_at != signed_at
                        or type(record.sink_id) is not str
                        or record.sink_id != self._sink.sink_id
                        or type(record.sink_kind) is not str
                        or record.sink_kind != self._sink.kind
                        or type(record.key_id) is not str or not record.key_id
                        or type(record.signature) is not str
                        or Ed25519SignatureVerifier._SIGNATURE_HEX.fullmatch(
                            record.signature) is None):
                    raise CheckpointUnavailable("READ_BACK_MISMATCH")
            else:
                unsigned = CheckpointRecord(scope.tenant_id, scope.company_id, event_seq,
                                            event_hash, signed_at, self._signer.key_id, "",
                                            self._sink.sink_id, self._sink.kind)
                signature = self._signer.sign(unsigned.signing_payload())
                if (type(signature) is not str
                        or Ed25519SignatureVerifier._SIGNATURE_HEX.fullmatch(signature) is None):
                    raise CheckpointUnavailable("S13_CHECKPOINT_SIGNATURE_INVALID")
                record = CheckpointRecord(**{**unsigned.__dict__, "signature": signature})
                try:
                    await self._sink.write(record)
                except Exception:
                    # The provider may have durably accepted the append before losing its response.
                    # Accept only an exact signed record on read-back; never turn an ambiguous write
                    # into permission to release the database holds.
                    back = await self._sink.read_back(scope, event_seq)
                    if back != record:
                        raise
                else:
                    back = await self._sink.read_back(scope, event_seq)
                if type(back) is not CheckpointRecord or back != record:
                    raise CheckpointUnavailable("READ_BACK_MISMATCH")
            if (not reused_existing
                    and not self._verifier.verify(record.key_id, record.signing_payload(),
                                                  record.signature)):
                raise CheckpointUnavailable("READ_BACK_MISMATCH")
            stored_checkpoint_seq = await self._ledger.record_checkpoint_s13(
                scope, event_seq, event_hash, record.sink_kind, record.sink_id,
                record.key_id, record.signature, record.signed_at, True,
            )
            if type(stored_checkpoint_seq) is not int or stored_checkpoint_seq < 1:
                raise CheckpointUnavailable("S13_CHECKPOINT_SEQUENCE_INVALID")
            released = []
            for hold_id in hold_ids:
                released_at = await self._ledger.release_hold(
                    scope, hold_id, {"store_accepted": True,
                                     "resolution_event_id": str(event_id)},
                )
                if not isinstance(released_at, datetime):
                    raise CheckpointUnavailable("S13_RESOLUTION_HOLD_RELEASE_INVALID")
                released.append(str(hold_id))
            return {"event_id": str(event_id), "event_seq": event_seq,
                    "checkpoint_seq": stored_checkpoint_seq,
                    "released_hold_ids": released}
        except CheckpointUnavailable:
            raise
        except LedgerError as exc:
            raise CheckpointUnavailable(exc.code) from None
        except Exception:
            raise CheckpointUnavailable("CHECKPOINT_UNAVAILABLE") from None

    async def issue_permit(self, scope: Scope, change_id: Any, generation: int,
                           apply_event_seq: int | None = None,
                           call_id: UUID | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise GateDisabled("GATE_DISABLED")
        try:
            await self._require_runtime_authority(scope, admission=True)
        except CheckpointUnavailable:
            raise GateDisabled("GATE_DISABLED") from None
        if (apply_event_seq is not None
                and (type(apply_event_seq) is not int or apply_event_seq < 1)):
            raise PermitRefused("APPLY_EVENT_SEQUENCE_INVALID")
        if self._private_writer_schema_enabled:
            if type(call_id) is not UUID or type(change_id) is not UUID:
                raise PermitRefused("S13_CALL_ID_REQUIRED")
            if type(generation) is not int or generation < 1:
                raise PermitRefused("S13_GENERATION_INVALID")
            if (type(self._signer.key_id) is not str or not self._signer.key_id
                    or type(self._signer.key_version) is not str or not self._signer.key_version):
                raise CheckpointUnavailable("S13_SIGNER_VERSION_REQUIRED")
        signer_key_id = self._signer.key_id
        signer_key_version = getattr(self._signer, "key_version", None)
        try:
            intent = None
            existing = None
            intent_id = None
            auth_epoch = None
            permit_id = None
            checkpoint_seq = None
            if self._private_writer_schema_enabled:
                intent = await self._ledger.dispatch_intent_for_call(scope, call_id, as_class="worker")
                if not isinstance(intent, dict):
                    raise CheckpointUnavailable("S13_DISPATCH_INTENT_UNAVAILABLE")
                try:
                    intent_id = UUID(str(intent["dispatch_intent_id"]))
                except (KeyError, TypeError, ValueError):
                    raise CheckpointUnavailable("S13_DISPATCH_INTENT_INVALID") from None
                if (intent.get("tenant_id") != scope.tenant_id
                        or intent.get("company_id") != scope.company_id
                        or intent.get("change_id") != str(change_id)
                        or type(intent.get("claim_generation")) is not int
                        or intent.get("claim_generation") != generation
                        or intent.get("call_id") != str(call_id)):
                    raise CheckpointUnavailable("S13_DISPATCH_INTENT_MISMATCH")
                auth_epoch = intent.get("auth_epoch")
                if type(auth_epoch) is not int or auth_epoch < 1:
                    raise CheckpointUnavailable("S13_DISPATCH_INTENT_INVALID")
                existing = await self._ledger.permit_binding_for_intent(
                    scope, intent_id, as_class="worker",
                )
                if existing is not None:
                    if not isinstance(existing, dict):
                        raise CheckpointUnavailable("S13_PERMIT_BINDING_INVALID")
                    try:
                        permit_id = UUID(str(existing["permit_id"]))
                        stored_intent_id = existing["dispatch_intent_id"]
                        checkpoint_seq = existing["checkpoint_seq"]
                    except (KeyError, TypeError, ValueError):
                        raise CheckpointUnavailable("S13_PERMIT_BINDING_INVALID") from None
                    if (str(permit_id) != existing["permit_id"] or permit_id.int == 0
                            or stored_intent_id != str(intent_id)
                            or type(checkpoint_seq) is not int or checkpoint_seq < 1
                            or existing.get("signer_key_id") != self._signer.key_id
                            or existing.get("signer_key_version") != self._signer.key_version):
                        raise PermitRefused("S13_PERMIT_BINDING_CONFLICT")
            if self._private_writer_schema_enabled and existing is not None:
                if apply_event_seq is not None:
                    head = await self._ledger.ledger_head(scope)
                    if not isinstance(head, dict):
                        raise CheckpointUnavailable("LEDGER_HEAD_INVALID")
                    head_seq = head.get("seq")
                    if type(head_seq) is not int or head_seq < 1:
                        raise CheckpointUnavailable("LEDGER_HEAD_INVALID")
                    if head_seq < apply_event_seq:
                        raise CheckpointUnavailable("HEAD_BEHIND_APPLY_EVENT")
                permit_digest = hashlib.sha256(
                    f"{change_id}:{generation}:{checkpoint_seq}".encode("utf-8")
                ).hexdigest()
                if existing.get("permit_digest") != permit_digest:
                    raise PermitRefused("S13_PERMIT_DIGEST_CONFLICT")
            else:
                head = await self._ledger.ledger_head(scope)
                if not isinstance(head, dict):
                    raise CheckpointUnavailable("LEDGER_HEAD_INVALID")
                checkpoint_seq = head.get("seq")
                head_hash = head.get("head_hash")
                if (type(checkpoint_seq) is not int or checkpoint_seq < 1
                        or type(head_hash) is not str or len(head_hash) != 64
                        or any(char not in "0123456789abcdef" for char in head_hash)):
                    raise CheckpointUnavailable("LEDGER_HEAD_INVALID")
                if apply_event_seq is not None and checkpoint_seq < apply_event_seq:
                    raise CheckpointUnavailable("HEAD_BEHIND_APPLY_EVENT")
                signed_at = datetime.now(UTC)
                unsigned = CheckpointRecord(scope.tenant_id, scope.company_id, checkpoint_seq,
                                            head_hash, signed_at, self._signer.key_id, "",
                                            self._sink.sink_id, self._sink.kind)
                record = CheckpointRecord(**{**unsigned.__dict__,
                                             "signature": self._signer.sign(unsigned.signing_payload())})
                await self._sink.write(record)
                back = await self._sink.read_back(scope, record.seq)
                if back != record or not self._verifier.verify(back.key_id, back.signing_payload(),
                                                               back.signature):
                    raise CheckpointUnavailable("READ_BACK_MISMATCH")
                record_checkpoint = (self._ledger.record_checkpoint_s13
                                     if self._private_writer_schema_enabled
                                     else self._ledger.record_checkpoint)
                stored_checkpoint_seq = await record_checkpoint(
                    scope, record.seq, record.head_hash, self._sink.kind,
                    record.sink_id, record.key_id, record.signature, record.signed_at, True,
                )
                if self._private_writer_schema_enabled:
                    if type(stored_checkpoint_seq) is not int or stored_checkpoint_seq < 1:
                        raise CheckpointUnavailable("S13_CHECKPOINT_SEQUENCE_INVALID")
                    checkpoint_seq = stored_checkpoint_seq
                    permit_id = uuid4()

            if self._private_writer_schema_enabled:
                permit_digest = hashlib.sha256(
                    f"{change_id}:{generation}:{checkpoint_seq}".encode("utf-8")
                ).hexdigest()
                sig = self._signer.sign(permit_signing_payload(permit_digest))
                if (type(sig) is not str or len(sig) != 128
                        or any(char not in "0123456789abcdef" for char in sig)):
                    raise CheckpointUnavailable("S13_PERMIT_SIGNATURE_INVALID")
                binding = await self._ledger.issue_permit_s13(
                    scope, change_id, generation, intent_id, permit_id,
                    signer_key_id, signer_key_version, sig,
                )
                if (binding.get("dispatch_intent_id") != str(intent_id)
                        or binding.get("permit_id") != str(permit_id)
                        or binding.get("permit_digest") != permit_digest
                        or binding.get("checkpoint_seq") != checkpoint_seq
                        or binding.get("signer_key_id") != signer_key_id
                        or binding.get("signer_key_version") != signer_key_version):
                    raise CheckpointUnavailable("S13_PERMIT_BINDING_MISMATCH")
                return {
                    **binding,
                    "signature": sig,
                    "lifecycle_epoch": auth_epoch,
                }
            permit = await self._ledger.issue_permit(scope, change_id, generation)
            sig = self._signer.sign(permit_signing_payload(permit["permit_digest"]))
            await self._ledger.attach_permit_signature(scope, change_id, generation,
                                                       self._signer.key_id, sig)
        except PermitRefused:
            # Preserve deliberate, stable admission refusals raised by this gate above.
            # The broad provider boundary below is for collaborator failures; converting a
            # permit conflict into CHECKPOINT_UNAVAILABLE would erase the non-retryable cause.
            raise
        except LedgerError as e:
            if e.code == "CHECKPOINT_UNAVAILABLE":
                raise CheckpointUnavailable(e.code) from None
            raise PermitRefused(e.code) from None
        except Exception:
            # External sink, signer and malformed collaborator failures must not leak provider
            # details through the writer-facing boundary or be mistaken for a usable permit.
            raise CheckpointUnavailable("CHECKPOINT_UNAVAILABLE") from None
        return {**permit, "signature": sig, "signer_key_id": self._signer.key_id}
