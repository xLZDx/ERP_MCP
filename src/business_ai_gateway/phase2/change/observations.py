"""Fail-closed boundary for authenticated, source-bound accounting-period snapshots.

No concrete qualified ERP period-read operation exists yet. Implementations of the reader
protocol must be server configured and authenticate to the registered source; caller-supplied
URLs, SQL, COM dispatch, and unverified booleans are deliberately absent from this API.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class ObservationUnavailable(ValueError):
    """The source observation cannot safely authorize a begin-apply decision."""


@dataclass(frozen=True, slots=True)
class SourceBinding:
    tenant_id: str
    company_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class AuthenticatedPeriodSnapshot:
    binding: SourceBinding
    period_id: str
    source_version: str
    observed_at: datetime
    closed: bool
    authentication_ref: str


class PeriodSnapshotReader(Protocol):
    """Trusted adapter boundary for a fixed, authenticated period-status read."""

    async def read_period(self, binding: SourceBinding, period_id: str) -> AuthenticatedPeriodSnapshot: ...


def _validate_request(binding: SourceBinding, period_id: str, expected_version: str,
                      now: datetime, max_age: timedelta) -> None:
    if (type(binding) is not SourceBinding
            or any(type(value) is not str or not value.strip()
                   for value in (binding.tenant_id, binding.company_id, binding.source_id))
            or type(period_id) is not str or not period_id.strip()
            or type(expected_version) is not str or not expected_version.strip()
            or not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
            or not isinstance(max_age, timedelta) or max_age <= timedelta(0)):
        raise ObservationUnavailable("PERIOD_OBSERVATION_UNSUPPORTED")


def derive_period_observation(
    snapshot: AuthenticatedPeriodSnapshot,
    *,
    binding: SourceBinding,
    period_id: str,
    expected_version: str,
    now: datetime,
    max_age: timedelta,
) -> tuple[bool, bool]:
    """Return ``(closed, observed_open)`` only for fresh, scope/version-bound evidence.

    The caller must obtain ``snapshot`` from the trusted configured adapter. A missing or
    unqualified source read must not call this function and must leave both flags false,
    which the existing T6 guard refuses as ``DIGEST_MISMATCH``.
    """
    if type(snapshot) is not AuthenticatedPeriodSnapshot:
        raise ObservationUnavailable("PERIOD_OBSERVATION_UNSUPPORTED")
    _validate_request(binding, period_id, expected_version, now, max_age)
    if (snapshot.binding != binding
            or snapshot.period_id != period_id or not period_id
            or snapshot.source_version != expected_version or not expected_version
            or type(snapshot.closed) is not bool
            or not isinstance(snapshot.authentication_ref, str) or not snapshot.authentication_ref.strip()
            or not isinstance(snapshot.observed_at, datetime) or snapshot.observed_at.tzinfo is None
            or snapshot.observed_at.utcoffset() is None):
        raise ObservationUnavailable("PERIOD_OBSERVATION_UNSUPPORTED")
    age = now - snapshot.observed_at
    if age < timedelta(0) or age > max_age:
        raise ObservationUnavailable("PERIOD_OBSERVATION_STALE")
    return (True, False) if snapshot.closed else (False, True)


async def build_begin_apply_evidence(
    reader: PeriodSnapshotReader,
    evidence: object,
    *,
    binding: SourceBinding,
    period_id: str,
    expected_version: str,
    now: datetime,
    max_age: timedelta,
):
    """Call the configured authenticated reader and bind its fresh result to T6 evidence.

    ``binding``, ``expected_version``, ``now`` and ``max_age`` must come from the application's
    trusted source registry, approval/version context and injected clock/policy. This function
    deliberately ignores and clears any period flags already present on ``evidence``. Reader
    exceptions and malformed replies are converted to fixed safe refusals without exposing
    provider text, credentials, or source data. The function is an integration boundary; no
    qualified concrete 1C reader is currently supplied by this repository.
    """
    from dataclasses import replace

    from .transitions import BeginApplyEvidence

    read_period = getattr(reader, "read_period", None)
    if not callable(read_period):
        raise ObservationUnavailable("PERIOD_OBSERVATION_UNSUPPORTED")
    if type(evidence) is not BeginApplyEvidence:
        raise ObservationUnavailable("PERIOD_OBSERVATION_UNSUPPORTED")
    _validate_request(binding, period_id, expected_version, now, max_age)
    try:
        clean_evidence = replace(evidence, period_closed=False, period_observed_open=False)
    except Exception:
        raise ObservationUnavailable("PERIOD_OBSERVATION_UNSUPPORTED") from None
    try:
        snapshot = await read_period(binding, period_id)
    except Exception:
        raise ObservationUnavailable("PERIOD_OBSERVATION_UNAVAILABLE") from None
    closed, opened = derive_period_observation(
        snapshot, binding=binding, period_id=period_id, expected_version=expected_version,
        now=now, max_age=max_age,
    )
    try:
        return replace(clean_evidence, period_closed=closed, period_observed_open=opened)
    except Exception:
        raise ObservationUnavailable("PERIOD_OBSERVATION_UNSUPPORTED") from None
