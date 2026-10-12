"""External checkpoint contract (CT5, S12 section 4/6) and the dispatch gate.

``cryptography`` is NOT a dependency in pyproject.toml, so no Ed25519 code is imported here. Signature
verification is a ``SignatureVerifier`` Protocol; ``UnwiredVerifier`` fails closed. A real Ed25519
verifier needs a separate dependency decision. ``InMemoryCheckpointSink``, ``FakeSigner`` and
``FakeVerifier`` are TEST ONLY: ``DispatchGate`` stays DISABLED while any of them is wired, whatever
the ``real_checkpoint_sink`` flag says, and the SQL refuses sink_kind TEST for permits.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ._common import Scope


class GateDisabled(Exception):
    """The gate refuses to issue a permit (no real checkpoint sink wired)."""

    code = "CHECKPOINT_UNAVAILABLE"


class CheckpointUnavailable(Exception):
    code = "CHECKPOINT_UNAVAILABLE"


class PermitRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _ts(value: datetime) -> str:
    """Same rendering as chg._ts in SQL: UTC, microseconds, no zone suffix."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def content_hash_of(payload_text: str) -> str:
    """sha256 of the exact payload text that is signed and sent to chg.record_evidence."""
    return hashlib.sha256(payload_text.encode("utf-8")).hexdigest()


def evidence_binding(change_id: str, kind: str, content_hash: str, observed_at: datetime) -> str:
    """Mirror of chg.evidence_binding: the digest a verifier/writer signs."""
    raw = f"{change_id}|{kind}|{content_hash}|{_ts(observed_at)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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

    def signing_payload(self) -> bytes:
        return (f"chg-checkpoint|v1|{self.tenant_id}|{self.company_id}|{self.seq}|{self.head_hash}|"
                f"{_ts(self.signed_at)}|{self.key_id}").encode()


class CheckpointSigner(Protocol):
    key_id: str
    is_test_double: bool

    def sign(self, payload: bytes) -> str: ...


class SignatureVerifier(Protocol):
    is_test_double: bool

    def verify(self, key_id: str, payload: bytes, signature: str) -> bool: ...


class CheckpointSink(Protocol):
    """External append-only store outside the DB administrator's trust boundary (D9)."""

    kind: str  # 'REAL' or 'TEST'
    sink_id: str

    async def write(self, record: CheckpointRecord) -> None: ...

    async def read_back(self, scope: Scope, seq: int) -> CheckpointRecord | None: ...


class UnwiredVerifier:
    """Fail-closed placeholder until an Ed25519 verifier is wired (needs a dependency decision)."""

    is_test_double = False

    def verify(self, key_id: str, payload: bytes, signature: str) -> bool:
        return False


class FakeSigner:
    """TEST ONLY. Not a signature scheme."""

    is_test_double = True

    def __init__(self, key_id: str = "test-key"):
        self.key_id = key_id

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


class LedgerPort(Protocol):
    """The slice of the SQL port the gate needs (satisfied by sql_ledger.SqlChangeLedger)."""

    async def ledger_head(self, scope: Scope) -> dict[str, Any]: ...

    async def record_checkpoint(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                sink_id: str, key_id: str, signature: str, signed_at: datetime,
                                read_back: bool) -> dict[str, Any]: ...

    async def issue_permit(self, scope: Scope, change_id: Any, generation: int) -> dict[str, Any]: ...

    async def attach_permit_signature(self, scope: Scope, change_id: Any, generation: int,
                                      key_id: str, signature: str) -> None: ...


class DispatchGate:
    """Refuses to issue a dispatch permit unless a checkpoint covering the head was written AND read back.

    Disabled unless ``real_checkpoint_sink`` is True and the sink, signer and verifier are all real.
    """

    def __init__(self, ledger: LedgerPort, sink: CheckpointSink, signer: CheckpointSigner,
                 verifier: SignatureVerifier, *, real_checkpoint_sink: bool = False):
        self._ledger, self._sink, self._signer, self._verifier = ledger, sink, signer, verifier
        self._flag = real_checkpoint_sink is True

    @property
    def enabled(self) -> bool:
        return (self._flag and self._sink.kind == "REAL"
                and not getattr(self._signer, "is_test_double", True)
                and not getattr(self._verifier, "is_test_double", True))

    async def issue_permit(self, scope: Scope, change_id: Any, generation: int,
                           apply_event_seq: int) -> dict[str, Any]:
        if not self.enabled:
            raise GateDisabled("GATE_DISABLED")
        head = await self._ledger.ledger_head(scope)
        if int(head["seq"]) < apply_event_seq:
            raise CheckpointUnavailable("HEAD_BEHIND_APPLY_EVENT")
        signed_at = datetime.now(UTC)
        unsigned = CheckpointRecord(scope.tenant_id, scope.company_id, int(head["seq"]),
                                    head["head_hash"], signed_at, self._signer.key_id, "",
                                    self._sink.sink_id)
        record = CheckpointRecord(**{**unsigned.__dict__,
                                     "signature": self._signer.sign(unsigned.signing_payload())})
        await self._sink.write(record)
        back = await self._sink.read_back(scope, record.seq)
        if back != record or not self._verifier.verify(back.key_id, back.signing_payload(),
                                                       back.signature):
            raise CheckpointUnavailable("READ_BACK_MISMATCH")
        await self._ledger.record_checkpoint(scope, record.seq, record.head_hash, self._sink.kind,
                                             record.sink_id, record.key_id, record.signature,
                                             record.signed_at, True)
        permit = await self._ledger.issue_permit(scope, change_id, generation)
        if permit.get("refused"):
            raise PermitRefused(str(permit.get("code")))
        sig = self._signer.sign(f"chg-permit|v1|{permit['permit_digest']}".encode())
        await self._ledger.attach_permit_signature(scope, change_id, generation,
                                                   self._signer.key_id, sig)
        return {**permit, "signature": sig, "signer_key_id": self._signer.key_id}
