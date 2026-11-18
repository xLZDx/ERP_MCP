"""Registry contracts and deliberately in-memory fakes; no production identity source is wired."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .contracts import (
    AuthenticatedPrincipal, PrincipalRecord, PrincipalRegistryPort, TargetRecord,
    CredentialGenerationEvidence, TargetRegistryPort, TargetScope, TestCredentialGenerationPort,
)


class InMemoryPrincipalRegistry(PrincipalRegistryPort):
    def __init__(self, records: tuple[PrincipalRecord, ...] = ()) -> None:
        self._lock = threading.RLock()
        self._records = {r.principal_id: r for r in records}

    def current(self, principal_id: str) -> PrincipalRecord | None:
        with self._lock:
            return self._records.get(principal_id)

    def epochs_current(self, dependencies: tuple[tuple[str, int], ...]) -> bool:
        with self._lock:
            return all((record := self._records.get(principal)) is not None
                       and type(record.lane) is str and record.lane == "TEST"
                       and not record.revoked and record.epoch == epoch
                       for principal, epoch in dependencies)

    def are_independent(self, requester_person_id: str, approver_person_id: str) -> bool:
        return bool(requester_person_id and approver_person_id and requester_person_id != approver_person_id)

    def put(self, record: PrincipalRecord) -> None:
        with self._lock:
            self._records[record.principal_id] = record

    def revoke(self, principal_id: str) -> None:
        with self._lock:
            record = self._records.get(principal_id)
            if record is not None:
                self._records[principal_id] = replace(record, revoked=True)

    def bump_epoch(self, principal_id: str) -> None:
        with self._lock:
            record = self._records.get(principal_id)
            if record is not None:
                self._records[principal_id] = replace(record, epoch=record.epoch + 1)

    def alias_person(self, principal_id: str, person_id: str) -> None:
        with self._lock:
            record = self._records.get(principal_id)
            if record is not None:
                self._records[principal_id] = replace(record, person_id=person_id)


class InMemoryTargetRegistry(TargetRegistryPort):
    def __init__(self, records: tuple[TargetRecord, ...] = ()) -> None:
        self._lock = threading.RLock()
        self._records = {r.scope.as_tuple(): r for r in records}

    def current(self, scope: TargetScope) -> TargetRecord | None:
        with self._lock:
            return self._records.get(scope.as_tuple())

    def resolve_fingerprint(self, scope: TargetScope) -> str | None:
        record = self.current(scope)
        return None if record is None or not record.allowed else record.scope.base_fingerprint

    def put(self, record: TargetRecord) -> None:
        with self._lock:
            self._records[record.scope.as_tuple()] = record

    def change_version(self, scope: TargetScope, version: object) -> None:
        from dataclasses import replace
        with self._lock:
            record = self._records.get(scope.as_tuple())
            if record is not None:
                self._records[scope.as_tuple()] = replace(record, version=version)


class InMemoryTestCredentialAuthority(TestCredentialGenerationPort):
    """Isolated TEST credential verifier; stores keyed digests, never credential values."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._key = secrets.token_bytes(32)
        self._records: dict[str, tuple[bytes, bytes, int, bool]] = {}

    def enroll(self, principal_id: str, credential: str) -> bool:
        return self._set_credential(principal_id, credential, rotate=False)

    def rotate(self, principal_id: str, credential: str) -> bool:
        return self._set_credential(principal_id, credential, rotate=True)

    def _set_credential(self, principal_id: str, credential: str, *, rotate: bool) -> bool:
        if (type(principal_id) is not str or not principal_id
                or type(credential) is not str or not credential):
            return False
        try:
            salt = secrets.token_bytes(16)
            digest = hmac.new(self._key, salt + credential.encode("utf-8"), hashlib.sha256).digest()
        except Exception:
            return False
        with self._lock:
            current = self._records.get(principal_id)
            if ((current is None and rotate) or (current is not None and not rotate)
                    or (current is not None and current[3])):
                return False
            generation = 1 if current is None else current[2] + 1
            self._records[principal_id] = (salt, digest, generation, False)
        return True

    def verify(self, principal_id: str, credential: str) -> CredentialGenerationEvidence | None:
        if type(principal_id) is not str or not principal_id or type(credential) is not str:
            return None
        with self._lock:
            record = self._records.get(principal_id)
            if (type(record) is not tuple or len(record) != 4
                    or type(record[0]) is not bytes or type(record[1]) is not bytes
                    or type(record[2]) is not int or record[2] <= 0
                    or type(record[3]) is not bool or record[3]):
                return None
            salt, expected, generation, _ = record
            try:
                candidate = hmac.new(self._key, salt + credential.encode("utf-8"), hashlib.sha256).digest()
            except Exception:
                return None
            if not hmac.compare_digest(candidate, expected):
                return None
            return CredentialGenerationEvidence(principal_id, generation)

    def current_generation(self, principal_id: str) -> int | None:
        if type(principal_id) is not str or not principal_id:
            return None
        with self._lock:
            record = self._records.get(principal_id)
            if (type(record) is not tuple or len(record) != 4
                    or type(record[0]) is not bytes or type(record[1]) is not bytes
                    or type(record[2]) is not int or record[2] <= 0
                    or type(record[3]) is not bool or record[3]):
                return None
            return record[2]

    def revoke(self, principal_id: str) -> None:
        with self._lock:
            current = self._records.get(principal_id)
            if current is not None:
                self._records[principal_id] = (current[0], current[1], current[2] + 1, True)


class TestIdP:
    """Minimal fixture issuer; it accepts only a registry-authenticated approver principal."""
    def __init__(self, principals: PrincipalRegistryPort, *, nonce_source=None,
                 credential_authority: TestCredentialGenerationPort | None = None) -> None:
        self.principals = principals
        self.nonce_source = nonce_source
        self.credential_authority = credential_authority
        self._revoked_sessions: set[str] = set()
        self._sessions: dict[str, object] = {}
        self._lock = threading.RLock()

    def issue(self, principal: AuthenticatedPrincipal, now, *, credential: str | None = None):
        from .contracts import ApproverSession, PrincipalRole, TokenClass
        if (type(principal) is not AuthenticatedPrincipal or principal.token_class is not TokenClass.APPROVER_SESSION
                or PrincipalRole.APPROVER not in principal.roles or principal.mfa_authenticated is not True
                or type(principal.lane) is not str or principal.lane != "TEST"
                or type(principal.scope) is not TargetScope or type(principal.scope.target_class) is not str
                or principal.scope.target_class != "TEST"
                or not self.authenticate(principal)):
            return None
        credential_generation = None
        if self.credential_authority is not None:
            try:
                if credential is None:
                    return None
                evidence = self.credential_authority.verify(principal.principal_id, credential)
                if (type(evidence) is not CredentialGenerationEvidence
                        or evidence.principal_id != principal.principal_id
                        or type(evidence.generation) is not int or evidence.generation <= 0):
                    return None
                credential_generation = evidence.generation
                if type(credential_generation) is not int or credential_generation <= 0:
                    return None
            except Exception:
                return None
        return self._issue_for_generation(principal, now, credential_generation)

    def _issue_for_generation(self, principal: AuthenticatedPrincipal, now, generation: int | None):
        from .contracts import ApproverSession
        if self.credential_authority is not None:
            try:
                current_generation = self.credential_authority.current_generation(principal.principal_id)
                if (type(generation) is not int or generation <= 0
                        or type(current_generation) is not int or current_generation != generation):
                    return None
            except Exception:
                return None
        secret = self.nonce_source.issue() if self.nonce_source else secrets.token_urlsafe(32)
        with self._lock:
            sid = None
            for _ in range(8):
                candidate = secrets.token_urlsafe(32)
                if candidate not in self._sessions and candidate not in self._revoked_sessions:
                    sid = candidate
                    break
            if sid is None:
                return None
            expiry = now + timedelta(minutes=15)
            session_principal = replace(principal, session_id=sid, expires_at=expiry)
            session = ApproverSession(sid, session_principal, now, now, expiry, expiry, secret,
                                      generation)
            self._sessions[sid] = session
        return session

    def validate_session(self, session, now):
        from .contracts import ApproverSession
        with self._lock:
            try:
                if type(session) is not ApproverSession:
                    return None
                session_id = session.session_id
                if type(session_id) is not str or not session_id:
                    return None
                current = self._sessions.get(session_id)
                if (current != session or session_id in self._revoked_sessions
                        or not self._session_metadata_valid(session)
                        or not self._session_time_valid(session, now)
                        or not self._credential_generation_current(session)
                        or not self.authenticate(session.principal)):
                    return None
            except Exception:
                return None
            return session

    def reauthenticate(self, session, decision_ref: str, now,
                       credential: str | None = None):
        """Issue TEST-only proof for one decision after checking the fixture credential."""
        from .contracts import ApproverSession
        if (self.credential_authority is None or type(session) is not ApproverSession
                or type(decision_ref) is not str or not 32 <= len(decision_ref) <= 512
                or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
                       for character in decision_ref)
                or type(credential) is not str or not credential):
            return None
        with self._lock:
            current = self.validate_session(session, now)
            if current is None:
                return None
            try:
                evidence = self.credential_authority.verify(
                    current.principal.principal_id, credential)
                if (type(evidence) is not CredentialGenerationEvidence
                        or evidence.principal_id != current.principal.principal_id
                        or type(evidence.generation) is not int
                        or evidence.generation <= 0
                        or evidence.generation != current.credential_generation
                        or not self._credential_generation_current(current)):
                    return None
                encoded = decision_ref.encode("ascii", errors="strict")
                digest = hashlib.sha256(encoded).hexdigest()
                replacement = replace(current, reauthenticated_at=now,
                                      reauthentication_digest=digest)
            except Exception:
                return None
            self._sessions[current.session_id] = replacement
            return replacement

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._revoked_sessions.add(session_id)

    def rotate_session(self, session, now):
        with self._lock:
            current = self.validate_session(session, now)
            if current is None:
                return None
            try:
                replacement = self._issue_for_generation(
                    current.principal, now, current.credential_generation
                )
            except Exception:
                return None
            from .contracts import ApproverSession
            if type(replacement) is not ApproverSession:
                return None
            if (replacement.session_id == current.session_id
                    or self.validate_session(replacement, now) is None):
                if (type(replacement.session_id) is str
                        and replacement.session_id != current.session_id
                        and self._sessions.get(replacement.session_id) is replacement):
                    self._sessions.pop(replacement.session_id, None)
                return None
            self._revoked_sessions.add(current.session_id)
            return replacement

    def authenticate(self, principal: AuthenticatedPrincipal) -> bool:
        from .contracts import PrincipalRole, TokenClass
        try:
            if (type(principal) is not AuthenticatedPrincipal
                    or principal.token_class is not TokenClass.APPROVER_SESSION
                    or type(principal.principal_id) is not str or not principal.principal_id
                    or type(principal.person_id) is not str or not principal.person_id
                    or type(principal.epoch) is not int or principal.epoch < 0
                    or type(principal.roles) is not frozenset
                    or any(type(role) is not PrincipalRole for role in principal.roles)
                    or PrincipalRole.APPROVER not in principal.roles
                    or principal.mfa_authenticated is not True
                    or type(principal.lane) is not str or principal.lane != "TEST"
                    or type(principal.scope) is not TargetScope
                    or type(principal.scope.target_class) is not str
                    or principal.scope.target_class != "TEST"):
                return False
            record = self.principals.current(principal.principal_id)
            return (type(record) is PrincipalRecord
                    and type(record.principal_id) is str and record.principal_id == principal.principal_id
                    and type(record.person_id) is str and record.person_id == principal.person_id
                    and type(record.epoch) is int and record.epoch >= 0 and record.epoch == principal.epoch
                    and type(record.revoked) is bool and record.revoked is False
                    and type(record.roles) is frozenset
                    and all(type(role) is PrincipalRole for role in record.roles)
                    and PrincipalRole.APPROVER in record.roles
                    and type(record.lane) is str and record.lane == "TEST")
        except Exception:
            return False

    def _credential_generation_current(self, session) -> bool:
        if self.credential_authority is None:
            return session.credential_generation is None
        try:
            generation = session.credential_generation
            current_generation = self.credential_authority.current_generation(session.principal.principal_id)
            return (type(generation) is int and generation > 0
                    and type(current_generation) is int and current_generation == generation)
        except Exception:
            return False

    @staticmethod
    def _session_metadata_valid(session) -> bool:
        from .contracts import ApproverSession
        return (type(session) is ApproverSession
                and type(session.session_id) is str and bool(session.session_id)
                and type(session.csrf_secret) is str and bool(session.csrf_secret)
                and type(session.principal) is AuthenticatedPrincipal
                and session.principal.session_id == session.session_id
                and session.principal.expires_at == session.expires_at)

    @staticmethod
    def _session_time_valid(session, now) -> bool:
        try:
            if type(now) is not datetime or type(session.created_at) is not datetime:
                return False
            if (type(session.last_seen_at) is not datetime
                    or type(session.idle_expires_at) is not datetime
                    or type(session.expires_at) is not datetime):
                return False
            values = (now, session.created_at, session.last_seen_at,
                      session.idle_expires_at, session.expires_at)
            if any(value.tzinfo is None or value.utcoffset() is None for value in values):
                return False
            current, created, last_seen, idle_expires, expires = (
                value.astimezone(timezone.utc) for value in values
            )
            return (created <= last_seen <= current < idle_expires <= expires
                    and current - last_seen <= timedelta(minutes=15)
                    and expires - created <= timedelta(minutes=15))
        except Exception:
            return False
