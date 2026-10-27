"""Exact client-to-scope authorization for the private writer HTTP boundary.

The allowlist is deployment input from an authenticated provisioning source. It contains no
wildcards, and this module does not load configuration or start a listener. Ticket and permit
verification stays delegated to the trusted writer verifier; a token's signature alone does not
authorize caller-supplied ledger fields.
"""
from __future__ import annotations

import asyncio
import math
import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from business_ai_gateway.phase2.change_ledger.write_port import ApplyTicket, DispatchPermit

from .dependency_shape import has_static_callable_method
from .private_auth import PRIVATE_WRITER_SCOPE, PrivateWriterCaller


_BASE_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
_MAX_VERIFICATION_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class PrivateWriterScopeGrant:
    """One exact physical-base and ledger-scope grant; wildcard fields are impossible."""

    tenant_id: str
    company_id: str
    organization: str
    base_fingerprint: str

    def __post_init__(self) -> None:
        if any(
            type(value) is not str
            or not value
            or value != value.strip()
            or len(value) > 512
            or any(unicodedata.category(character) == "Cc" for character in value)
            for value in (self.tenant_id, self.company_id, self.organization)
        ):
            raise ValueError("PRIVATE_WRITER_SCOPE_GRANT_INVALID")
        if (
            type(self.base_fingerprint) is not str
            or _BASE_FINGERPRINT.fullmatch(self.base_fingerprint) is None
        ):
            raise ValueError("PRIVATE_WRITER_SCOPE_GRANT_INVALID")


@dataclass(frozen=True, slots=True)
class PrivateWriterPrincipal:
    """Exact verified OAuth client/subject pair used as the grant key."""

    client_id: str
    subject: str

    def __post_init__(self) -> None:
        if any(
            type(value) is not str
            or not value
            or value != value.strip()
            or len(value) > 512
            or any(unicodedata.category(character) == "Cc" for character in value)
            for value in (self.client_id, self.subject)
        ):
            raise ValueError("PRIVATE_WRITER_PRINCIPAL_INVALID")


class TicketPermitVerifier(Protocol):
    """Trusted, read-only checks against the ticket and permit authorities."""

    async def verify_ticket(self, ticket: ApplyTicket) -> None: ...

    async def verify_permit(self, ticket: ApplyTicket, permit: DispatchPermit) -> None: ...


class PrivateWriterAuthorizationUnavailable(RuntimeError):
    """The authoritative ticket/permit verification dependency could not establish a result."""


class ConfiguredPrivateWriterAuthorizer:
    """Authorize every call using an exact OAuth client grant and trusted ticket/permit checks."""

    __slots__ = ("_verifier", "_grants", "_verification_timeout_seconds")

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("WRITER_AUTHORIZATION_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("WRITER_AUTHORIZATION_CONFIGURATION_IMMUTABLE")

    def __init__(
        self,
        verifier: TicketPermitVerifier,
        *,
        grants_by_principal: Mapping[PrivateWriterPrincipal, frozenset[PrivateWriterScopeGrant]],
        verification_timeout_seconds: float = _MAX_VERIFICATION_SECONDS,
    ) -> None:
        if (not has_static_callable_method(verifier, "verify_ticket")
                or not has_static_callable_method(verifier, "verify_permit")):
            raise ValueError("WRITER_TICKET_PERMIT_VERIFIER_REQUIRED")
        if type(grants_by_principal) is not dict or not grants_by_principal:
            raise ValueError("WRITER_CALLER_SCOPE_GRANTS_REQUIRED")
        if (
            isinstance(verification_timeout_seconds, bool)
            or not isinstance(verification_timeout_seconds, (int, float))
            or not 0 < verification_timeout_seconds <= _MAX_VERIFICATION_SECONDS
            or not math.isfinite(verification_timeout_seconds)
        ):
            raise ValueError("WRITER_AUTHORIZATION_TIMEOUT_INVALID")

        grants: dict[PrivateWriterPrincipal, frozenset[PrivateWriterScopeGrant]] = {}
        for principal, principal_grants in grants_by_principal.items():
            if (
                type(principal) is not PrivateWriterPrincipal
                or type(principal_grants) is not frozenset
                or not principal_grants
                or any(type(grant) is not PrivateWriterScopeGrant for grant in principal_grants)
            ):
                raise ValueError("WRITER_CALLER_SCOPE_GRANTS_INVALID")
            grants[principal] = principal_grants

        self._verifier = verifier
        self._grants = MappingProxyType(grants)
        self._verification_timeout_seconds = float(verification_timeout_seconds)

    async def authorize_call(
        self,
        caller: PrivateWriterCaller,
        ticket: ApplyTicket,
        permit: DispatchPermit,
    ) -> None:
        """Require the exact client scope and current ticket/signed-permit checks for dispatch."""
        self.authorize_lookup(caller, ticket)
        try:
            async with asyncio.timeout(self._verification_timeout_seconds):
                await self._verifier.verify_ticket(ticket)
                await self._verifier.verify_permit(ticket, permit)
        except Exception:
            raise PrivateWriterAuthorizationUnavailable(
                "CALL_AUTHORIZATION_UNAVAILABLE"
            ) from None

    def authorize_lookup(
        self,
        caller: PrivateWriterCaller,
        ticket: ApplyTicket,
    ) -> None:
        """Authorize scope only; the subsequent store read proves exact historical admission.

        Outcome lookup deliberately does not require an unexpired permit. The immutable stored
        admission identity includes its ticket and permit IDs/digests; ``PrivateWriterService``
        asks that authoritative store for the exact tuple and never dispatches from this route.
        """
        if (
            type(caller) is not PrivateWriterCaller
            or type(caller.subject) is not str
            or not caller.subject
            or caller.subject != caller.subject.strip()
            or type(caller.client_id) is not str
            or not caller.client_id
            or caller.client_id != caller.client_id.strip()
            or type(caller.scopes) is not frozenset
            or any(
                type(scope) is not str
                or not scope
                or scope != scope.strip()
                or len(scope) > 512
                or any(unicodedata.category(character) == "Cc" for character in scope)
                for scope in caller.scopes
            )
            or PRIVATE_WRITER_SCOPE not in caller.scopes
            or type(ticket) is not ApplyTicket
        ):
            raise PermissionError("CALL_NOT_AUTHORIZED")

        try:
            grant = PrivateWriterScopeGrant(
                tenant_id=ticket.tenant_id,
                company_id=ticket.company_id,
                organization=ticket.organization,
                base_fingerprint=ticket.base_fingerprint,
            )
        except (TypeError, ValueError):
            raise PermissionError("CALL_NOT_AUTHORIZED") from None
        try:
            principal = PrivateWriterPrincipal(caller.client_id, caller.subject)
        except ValueError:
            raise PermissionError("CALL_NOT_AUTHORIZED") from None
        if grant not in self._grants.get(principal, frozenset()):
            raise PermissionError("CALL_NOT_AUTHORIZED")


__all__ = [
    "ConfiguredPrivateWriterAuthorizer",
    "PrivateWriterAuthorizationUnavailable",
    "PrivateWriterPrincipal",
    "PrivateWriterScopeGrant",
    "TicketPermitVerifier",
]
