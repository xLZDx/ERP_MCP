"""Registry contracts and deliberately in-memory fakes; no production identity source is wired."""
from __future__ import annotations

import secrets
import threading
from dataclasses import replace
from datetime import timedelta

from .contracts import (
    AuthenticatedPrincipal,
    PrincipalRecord,
    PrincipalRegistryPort,
    TargetRecord,
    TargetRegistryPort,
    TargetScope,
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
                or not self.authenticate(principal)):
            return None
        secret = self.nonce_source.issue() if self.nonce_source else secrets.token_urlsafe(32)
        sid = secrets.token_urlsafe(32)
        expiry = now + timedelta(minutes=15)
        session_principal = replace(principal, session_id=sid, expires_at=expiry)
        session = ApproverSession(sid, session_principal, now, now, expiry, expiry, secret)
        with self._lock:
            self._sessions[sid] = session
        return session

    def validate_session(self, session, now):
        from .contracts import ApproverSession
        with self._lock:
            current = self._sessions.get(getattr(session, "session_id", ""))
            if (type(session) is not ApproverSession or current != session
                    or session.session_id in self._revoked_sessions
                    or now >= session.expires_at or now >= session.idle_expires_at
                    or now - session.created_at > timedelta(minutes=15)):
                return None
            return session

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._revoked_sessions.add(session_id)

    def rotate_session(self, session, now):
        self.revoke_session(session.session_id)
        return self.issue(session.principal, now)

    def authenticate(self, principal: AuthenticatedPrincipal) -> bool:
        from .contracts import PrincipalRole, TokenClass
        if (type(principal) is not AuthenticatedPrincipal or principal.token_class is not TokenClass.APPROVER_SESSION
                or PrincipalRole.APPROVER not in principal.roles):
            return False
        record = self.principals.current(principal.principal_id)
        return (record is not None and not record.revoked and record.epoch == principal.epoch
                and record.person_id == principal.person_id and PrincipalRole.APPROVER in record.roles)
