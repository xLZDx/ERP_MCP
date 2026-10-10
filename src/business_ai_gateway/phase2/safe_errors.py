"""Phase 2 sprint S8 (R2-US-041, TC121): safe error rendering over a closed vocabulary.

Offline and pure. A ``SafeError`` (from ``workbench_types``) is two fixed enums plus an injected
opaque correlation id. This module only maps those enums to constant message text:

* ``MESSAGES`` / ``ACTION_TEXT`` - constant tables, one entry per ``ReasonCode`` / ``NextAction``.
* ``render_safe_error`` - takes ONE ``SafeError`` and nothing else (no free text, no exception object,
  no foreign source name, stack text, secret reference, SQL fragment or provider text can be passed in).
  Anything that is not a valid ``SafeError`` renders as the fixed ``INTERNAL_REFUSED`` message.
* ``CorrelationSource`` / ``FakeCorrelationSource`` - ids come from an injected source, never from input.
  ``new_safe_error`` never raises: a failing or hostile source degrades to the fixed default id.

Authority is ``EVALUATION_ONLY``. Display strings are fixed English constants, not localized UI text.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol

from .workbench_types import (
    AUTHORITY,
    DEFAULT_CORRELATION_ID,
    NextAction,
    ReasonCode,
    SafeError,
    is_valid_safe_error,
    safe_error,
)

__all__ = [
    "ACTION_TEXT", "MESSAGES", "CorrelationSource", "FakeCorrelationSource", "RenderedError",
    "new_safe_error", "render_safe_error",
]

_R, _N = ReasonCode, NextAction
MESSAGES: Final = MappingProxyType({
    _R.ORIGINAL_NUMBERS_IMMUTABLE: "Original numbers cannot be changed; request a new run instead.",
    _R.ORIGINAL_INTACT: "Original numbers are intact.",
    _R.ORIGINAL_TAMPERED: "The displayed numbers do not match the recorded run.",
    _R.ROW_DETAIL_UNAVAILABLE: "Row-level detail is not available for this run.",
    _R.OWNER_UNASSIGNED: "No owner is assigned to this item.",
    _R.DELTA_PRECISION_EXCEEDED: "The difference cannot be shown exactly.",
    _R.NO_NEW_EVIDENCE: "A rerun needs new evidence; none was supplied.",
    _R.RERUN_TARGET_STALE: "This run is no longer the latest; refresh and try again.",
    _R.RERUN_TARGET_UNKNOWN: "The run to rerun was not found.",
    _R.NOT_IN_SCOPE: "This item is outside your scope.",
    _R.SCOPE_EPOCH_STALE: "Your access changed; refresh the page.",
    _R.ANNOTATION_INVALID: "The annotation is not valid.",
    _R.INPUT_INVALID: "The request is not valid.",
    _R.EFFECTIVE_UNKNOWN: "The effective date is unknown.",
    _R.HIDDEN_BY_SCOPE: "Some entries are hidden by your access scope.",
    _R.SUPERSEDED_BY_RUN: "This result was superseded by a newer run.",
    _R.REVISION_CHANGED: "The underlying revision changed.",
    _R.ATTESTATION_REVOKED: "The attestation was revoked.",
    _R.STALE: "This result is older than the freshness window.",
    _R.SOURCE_PAUSED: "The source is paused.",
    _R.NOT_COVERED: "This claim is not covered by validation.",
    _R.UNKNOWN: "The status cannot be determined.",
    _R.CSRF_REJECTED: "The request could not be verified; refresh the page and try again.",
    _R.SESSION_INVALID: "Your session is not valid; sign in again.",
    _R.IDEMPOTENCY_KEY_REQUIRED: "A valid idempotency key is required for this request.",
    _R.IDEMPOTENCY_CONFLICT: "This idempotency key was already used for a different request.",
    _R.REPLAYED: "This request was already processed; the original result is returned.",
    _R.OPERATION_UNCLASSIFIED: "This operation is not recognized and is refused.",
    _R.OPERATION_DENIED: "This operation is not permitted.",
    _R.PARAMETER_SCHEMA_INVALID: "The request parameters are not valid.",
    _R.NOT_FOUND: "The requested item was not found.",
    _R.RATE_LIMITED: "Too many requests; try again later.",
    _R.INTERNAL_REFUSED: "The request was refused because of an internal condition.",
})
ACTION_TEXT: Final = MappingProxyType({
    _N.RETRY_LATER: "Try again later.",
    _N.CONTACT_OWNER: "Contact the owner of this item.",
    _N.REAUTHENTICATE: "Sign in again.",
    _N.REFRESH_PAGE: "Refresh the page.",
    _N.NO_ACTION: "No action is needed.",
})


@dataclass(frozen=True, slots=True)
class RenderedError:
    """What a UI may show for a refusal: constants from the tables plus the injected correlation id."""

    reason_code: str
    message: str
    next_action: str
    next_action_text: str
    correlation_id: str
    authority: str = AUTHORITY


class CorrelationSource(Protocol):
    def next_id(self) -> str: ...


class FakeCorrelationSource:
    """Deterministic, thread-safe id source for tests: CORR-000001, CORR-000002, ..."""

    def __init__(self, prefix: str = "CORR") -> None:
        self._prefix = prefix if type(prefix) is str and prefix.isalnum() and len(prefix) <= 16 else "CORR"
        self._n = 0
        self._lock = threading.Lock()

    def next_id(self) -> str:
        with self._lock:
            self._n += 1
            return f"{self._prefix}-{self._n:06d}"

    def __repr__(self) -> str:
        return "FakeCorrelationSource()"


def render_safe_error(error: object) -> RenderedError:
    """Render a ``SafeError`` with constant text; any other object renders as ``INTERNAL_REFUSED``."""
    if not is_valid_safe_error(error):
        error = safe_error(_R.INTERNAL_REFUSED)
    return RenderedError(
        reason_code=error.reason_code.value, message=MESSAGES[error.reason_code],
        next_action=error.next_action.value, next_action_text=ACTION_TEXT[error.next_action],
        correlation_id=error.correlation_id)


def new_safe_error(reason: object, source: object) -> SafeError:
    """A ``SafeError`` for ``reason`` with an id drawn from ``source``; never raises, never echoes."""
    try:
        corr = source.next_id()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a broken source must not turn a refusal into a crash
        corr = DEFAULT_CORRELATION_ID
    return safe_error(reason, corr)
