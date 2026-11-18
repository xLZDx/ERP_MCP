"""Registry contracts and deliberately in-memory fakes; no production identity source is wired."""
from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import secrets

from .contracts import (
    AuthenticatedPrincipal, PrincipalRecord, PrincipalRegistryPort, TargetRecord,
    TargetRegistryPort, TargetScope,
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


class TestIdP:
    """Minimal fixture issuer; it accepts only a registry-authenticated approver principal."""
    def __init__(self, principals: PrincipalRegistryPort, *, nonce_source=None) -> None:
        self.principals = principals
        self.nonce_source = nonce_source
        self._revoked_sessions: set[str] = set()
        self._sessions: dict[str, object] = {}
        self._lock = threading.RLock()

    def issue(self, principal: AuthenticatedPrincipal, now):
        from .contracts import ApproverSession, PrincipalRole, TokenClass
        if (type(principal) is not AuthenticatedPrincipal or principal.token_class is not TokenClass.APPROVER_SESSION
                or PrincipalRole.APPROVER not in principal.roles or principal.mfa_authenticated is not True
                or type(principal.lane) is not str or principal.lane != "TEST"
                or type(principal.scope) is not TargetScope or type(principal.scope.target_class) is not str
                or principal.scope.target_class != "TEST"
                or not self.authenticate(principal)):
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
            session = ApproverSession(sid, session_principal, now, now, expiry, expiry, secret)
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
                        or not self.authenticate(session.principal)):
                    return None
            except Exception:
                return None
            return session

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._revoked_sessions.add(session_id)

    def rotate_session(self, session, now):
        with self._lock:
            current = self.validate_session(session, now)
            if current is None:
                return None
            try:
                replacement = self.issue(current.principal, now)
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
