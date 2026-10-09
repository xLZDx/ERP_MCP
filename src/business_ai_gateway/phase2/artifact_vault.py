"""Phase 2 immutable private artifact vault (R2-US-026, REQ16/17): in-memory, no I/O, UNWIRED from Release 1.

Rules
- Every artifact lives in exactly one scope (tenant_id + source_id, normalised via ``_identity``).
  The same bytes in the same scope are stored once (idempotent, DUPLICATE, same ref); the same bytes
  in another scope are an independent artifact with its own version id.
- A version id is an opaque ``prefix + url-safe base64`` of 16 random bytes from the injected
  ``id_source``. It is NOT derived from the digest or the content, so a digest never lets anybody
  guess or forge a version id. An id that is already taken is REFUSED, never overwritten.
- Versions are append-only: different bytes always create a new version; the vault exposes no
  update / delete / overwrite API. Stored bytes are an immutable ``bytes`` object; only exact
  ``bytes`` are accepted (bytearray / memoryview / str are refused, so no mutable alias exists).
- Access is decided by the CURRENT per-scope ACL at read time (historical versions are not
  grandfathered). ``grant`` / ``revoke`` need a principal listed in the vault's ``admins`` and bump
  a per-scope ACL epoch only when the ACL really changed. ``put`` also needs the uploader in the ACL.
- ``read`` and ``verify_evidence`` answer every failure (unknown id, scope mismatch, tampered
  digest/size, no access, wrong claim, hash-only claim, wrong types) with the SAME fixed code, so
  there is no existence oracle across scopes. Evidence is valid only if the ref names a stored blob,
  the ref matches the stored record exactly, the claimed digest equals the stored digest
  (constant-time) and the reader currently has access. A bare hash is never evidence.
- The audit trail is an append-only tuple of events holding only normalised ids and fixed codes;
  never content, never raw caller text.
- Result codes are fixed constants; caller input is never echoed.
- RESIDUAL RISK / KNOWN GAPS: principals are caller-asserted (no authentication); in-memory only
  (no persistence, no encryption at rest); no retention or quota per scope; the size limit is the
  only resource bound; the ACL and the audit trail are unbounded in memory.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ._identity import clean_identity, scope_key

__all__ = [
    "ALLOWED_MEDIA_TYPES", "ArtifactRef", "ArtifactScope", "ArtifactVault", "AuditEvent",
    "AuditKind", "EvidenceResult", "Principal", "PutResult", "PutStatus", "ReadResult",
]

ALLOWED_MEDIA_TYPES = frozenset({
    "application/pdf", "application/json", "text/plain", "text/csv", "image/png", "image/jpeg",
})
_ID_PREFIX = "av_"
_ID_BYTES = 16

# fixed result codes
OK = "OK"
DUPLICATE = "DUPLICATE"
INVALID_INPUT = "INVALID_INPUT"
INVALID_SCOPE = "INVALID_SCOPE"
INVALID_PRINCIPAL = "INVALID_PRINCIPAL"
MEDIA_TYPE_REFUSED = "MEDIA_TYPE_REFUSED"
CONTENT_TYPE_REFUSED = "CONTENT_TYPE_REFUSED"
EMPTY_CONTENT = "EMPTY_CONTENT"
CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
UPLOAD_NOT_ALLOWED = "UPLOAD_NOT_ALLOWED"
ID_COLLISION = "ID_COLLISION"
ID_SOURCE_INVALID = "ID_SOURCE_INVALID"
CLOCK_INVALID = "CLOCK_INVALID"
ADMIN_REQUIRED = "ADMIN_REQUIRED"
ACCESS_DENIED = "ACCESS_DENIED"  # ONE code for unknown / mismatched / revoked / foreign scope
NOT_EVIDENCE = "NOT_EVIDENCE"  # ONE code for every invalid evidence claim
UNCHANGED = "UNCHANGED"


class PutStatus(StrEnum):
    STORED = "STORED"
    DUPLICATE = "DUPLICATE"
    REFUSED = "REFUSED"


class AuditKind(StrEnum):
    PUT = "PUT"
    READ = "READ"
    DENY = "DENY"
    GRANT = "GRANT"
    REVOKE = "REVOKE"


@dataclass(frozen=True, slots=True)
class ArtifactScope:
    tenant_id: str
    source_id: str

    def key(self) -> tuple[str, str] | None:
        return scope_key(self.tenant_id, self.source_id)


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str

    def key(self) -> str:
        return clean_identity(self.principal_id)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    version_id: str
    digest: str
    size: int
    scope: ArtifactScope


@dataclass(frozen=True, slots=True)
class PutResult:
    status: PutStatus
    ref: ArtifactRef | None
    code: str


@dataclass(frozen=True, slots=True)
class ReadResult:
    allowed: bool
    code: str
    content: bytes | None = None


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    valid: bool
    code: str


@dataclass(frozen=True, slots=True)
class AuditEvent:
    kind: AuditKind
    scope: tuple[str, str] | None
    principal: str
    code: str
    at: datetime | None


@dataclass(frozen=True, slots=True)
class _Record:
    scope: tuple[str, str]
    digest: str
    size: int
    media_type: str
    content: bytes


def _skey(scope: object) -> tuple[str, str] | None:
    return scope.key() if type(scope) is ArtifactScope else None


def _pkey(principal: object) -> str:
    return principal.key() if type(principal) is Principal else ""


def _random_id() -> bytes:
    return secrets.token_bytes(_ID_BYTES)


class ArtifactVault:
    def __init__(
        self,
        clock: Callable[[], datetime],
        *,
        max_bytes: int = 5_000_000,
        id_source: Callable[[], bytes] = _random_id,
        admins: Iterable[str] = (),
    ) -> None:
        if not callable(clock) or not callable(id_source):
            raise TypeError("clock and id_source must be callable")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive int")
        self._clock = clock
        self._max_bytes = max_bytes
        self._id_source = id_source
        self._admins = frozenset(k for k in (clean_identity(a) for a in admins) if k)
        self._records: dict[str, _Record] = {}
        self._by_digest: dict[tuple[tuple[str, str], str], str] = {}
        self._acl: dict[tuple[str, str], set[str]] = {}
        self._epoch: dict[tuple[str, str], int] = {}
        self._audit: list[AuditEvent] = []

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime | None:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - clock failures must not leak text
            return None
        return value if type(value) is datetime else None

    def _log(self, kind: AuditKind, scope: object, principal: object, code: str) -> None:
        self._audit.append(AuditEvent(kind, _skey(scope), _pkey(principal), code, self._now()))

    def _has_access(self, skey: tuple[str, str], pkey: str) -> bool:
        return bool(pkey) and pkey in self._acl.get(skey, ())

    def _refuse(self, scope: object, uploader: object, code: str) -> PutResult:
        self._log(AuditKind.DENY, scope, uploader, code)
        return PutResult(PutStatus.REFUSED, None, code)

    # --------------------------------------------------------------------- put
    def put(self, scope: ArtifactScope, content: bytes, uploader: Principal,
            media_type: str) -> PutResult:
        skey = _skey(scope)
        if skey is None:
            return self._refuse(scope, uploader, INVALID_SCOPE)
        pkey = _pkey(uploader)
        if not pkey:
            return self._refuse(scope, uploader, INVALID_PRINCIPAL)
        if type(media_type) is not str or media_type not in ALLOWED_MEDIA_TYPES:
            return self._refuse(scope, uploader, MEDIA_TYPE_REFUSED)
        if type(content) is not bytes:
            return self._refuse(scope, uploader, CONTENT_TYPE_REFUSED)
        if not content:
            return self._refuse(scope, uploader, EMPTY_CONTENT)
        if len(content) > self._max_bytes:
            return self._refuse(scope, uploader, CONTENT_TOO_LARGE)
        if not self._has_access(skey, pkey):
            return self._refuse(scope, uploader, UPLOAD_NOT_ALLOWED)
        digest = hashlib.sha256(content).hexdigest()
        existing_id = self._by_digest.get((skey, digest))
        if existing_id is not None:
            rec = self._records[existing_id]
            if rec.content == content and rec.scope == skey:
                ref = ArtifactRef(existing_id, digest, rec.size, scope)
                self._log(AuditKind.PUT, scope, uploader, DUPLICATE)
                return PutResult(PutStatus.DUPLICATE, ref, DUPLICATE)
        try:
            raw = self._id_source()
        except Exception:  # noqa: BLE001
            return self._refuse(scope, uploader, ID_SOURCE_INVALID)
        if type(raw) is not bytes or len(raw) != _ID_BYTES:
            return self._refuse(scope, uploader, ID_SOURCE_INVALID)
        version_id = _ID_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        if version_id in self._records:
            return self._refuse(scope, uploader, ID_COLLISION)
        self._records[version_id] = _Record(skey, digest, len(content), media_type, content)
        self._by_digest[(skey, digest)] = version_id
        self._log(AuditKind.PUT, scope, uploader, OK)
        return PutResult(PutStatus.STORED, ArtifactRef(version_id, digest, len(content), scope), OK)

    # --------------------------------------------------------------------- ACL
    def _admin_ok(self, by_admin: object) -> bool:
        key = _pkey(by_admin)
        return bool(key) and key in self._admins

    def grant(self, scope: ArtifactScope, principal: Principal, by_admin: Principal) -> str:
        return self._change_acl(AuditKind.GRANT, scope, principal, by_admin)

    def revoke(self, scope: ArtifactScope, principal: Principal, by_admin: Principal) -> str:
        return self._change_acl(AuditKind.REVOKE, scope, principal, by_admin)

    def _change_acl(self, kind: AuditKind, scope: object, principal: object, by_admin: object) -> str:
        skey = _skey(scope)
        pkey = _pkey(principal)
        if skey is None:
            code = INVALID_SCOPE
        elif not pkey:
            code = INVALID_PRINCIPAL
        elif not self._admin_ok(by_admin):
            code = ADMIN_REQUIRED
        else:
            members = self._acl.setdefault(skey, set())
            if kind is AuditKind.GRANT and pkey not in members:
                members.add(pkey)
                code = OK
            elif kind is AuditKind.REVOKE and pkey in members:
                members.discard(pkey)
                code = OK
            else:
                code = UNCHANGED
            if code == OK:
                self._epoch[skey] = self._epoch.get(skey, 0) + 1
        self._log(kind if code in (OK, UNCHANGED) else AuditKind.DENY, scope, principal, code)
        return code

    def acl_epoch(self, scope: ArtifactScope) -> int:
        skey = _skey(scope)
        return self._epoch.get(skey, 0) if skey is not None else 0

    # -------------------------------------------------------------------- read
    def _lookup(self, ref: object, reader: object) -> _Record | None:
        """The stored record iff ref matches it exactly AND the reader currently has access."""
        if type(ref) is not ArtifactRef or type(ref.version_id) is not str:
            return None
        rskey = _skey(ref.scope)
        rec = self._records.get(ref.version_id)
        if rec is None or rskey is None or rskey != rec.scope:
            return None
        if type(ref.digest) is not str or type(ref.size) is not int or ref.size != rec.size:
            return None
        if not hmac.compare_digest(ref.digest.encode("utf-8"), rec.digest.encode("ascii")):
            return None
        return rec if self._has_access(rec.scope, _pkey(reader)) else None

    def read(self, ref: ArtifactRef, reader: Principal) -> ReadResult:
        rec = self._lookup(ref, reader)
        if rec is None:
            self._log(AuditKind.DENY, getattr(ref, "scope", None), reader, ACCESS_DENIED)
            return ReadResult(False, ACCESS_DENIED, None)
        self._log(AuditKind.READ, ref.scope, reader, OK)
        return ReadResult(True, OK, rec.content)

    def verify_evidence(self, ref: object, claimed_digest: str, reader: Principal) -> EvidenceResult:
        rec = self._lookup(ref, reader)
        ok = (
            rec is not None
            and type(claimed_digest) is str
            and hmac.compare_digest(claimed_digest.encode("utf-8", "replace"),
                                    rec.digest.encode("ascii"))
        )
        scope = getattr(ref, "scope", None)
        if not ok:
            self._log(AuditKind.DENY, scope, reader, NOT_EVIDENCE)
            return EvidenceResult(False, NOT_EVIDENCE)
        self._log(AuditKind.READ, scope, reader, OK)
        return EvidenceResult(True, OK)

    # ------------------------------------------------------------------- audit
    def audit(self) -> tuple[AuditEvent, ...]:
        return tuple(self._audit)
