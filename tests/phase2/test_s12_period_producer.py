"""REQ-002 / S1.2 AC-1..2: period evidence is derived from one fresh authenticated read."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from business_ai_gateway.phase2.change.observations import (
    AuthenticatedPeriodSnapshot, ObservationUnavailable, SourceBinding,
    build_begin_apply_evidence, derive_period_observation,
)
from business_ai_gateway.phase2.change.killswitch import SWITCH_OFF
from business_ai_gateway.phase2.change.transitions import BeginApplyEvidence
from business_ai_gateway.phase2.change.types import CallerClass
from business_ai_gateway.phase2.change.errors import ErrorCode, Refusal
from business_ai_gateway.phase2.change.transitions import Event, apply_transition
from tests.phase2 import _change_helpers as transition_fixtures

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
BINDING = SourceBinding("tenant", "company", "registered-source", "org", "base")
SYNTHETIC_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "s12_period_observations.synthetic.json").read_text(
        encoding="utf-8"
    )
)


def synthetic_snapshot(name):
    binding = SourceBinding(**SYNTHETIC_FIXTURE["binding"])
    observation = SYNTHETIC_FIXTURE["observations"][name]
    return AuthenticatedPeriodSnapshot(
        binding=binding,
        period_id=SYNTHETIC_FIXTURE["period_id"],
        source_version=SYNTHETIC_FIXTURE["source_version"],
        observed_at=datetime.fromisoformat(observation["observed_at"]),
        closed=observation["closed"],
        authentication_ref=SYNTHETIC_FIXTURE["authentication_ref"],
    )


class Reader:
    def __init__(self, snapshot=None, error=None):
        self.snapshot, self.error, self.calls = snapshot, error, []

    async def read_period(self, binding, period_id):
        self.calls.append((binding, period_id))
        if self.error:
            raise self.error
        return self.snapshot


def snapshot(*, closed=False, binding=BINDING, period_id="2026-10", version="v1",
             observed_at=NOW, auth_ref="auth-ref"):
    return AuthenticatedPeriodSnapshot(binding, period_id, version, observed_at, closed, auth_ref)


def evidence(**overrides):
    fields = dict(now=NOW, kill=SWITCH_OFF, generation=1, caller=CallerClass.REQUESTER,
                  own_change=True, epoch_deps_equal_claim_epoch=True, holds=(),
                  version_equals_approved=True, fingerprint_authenticated=True,
                  period_closed=False, period_observed_open=False, state_digest_equal=True,
                  writer_lock_held=True, ownership_row_committed=True)
    fields.update(overrides)
    return BeginApplyEvidence(**fields)


def test_fresh_authenticated_open_and_closed_observations_are_distinct():
    args = dict(binding=BINDING, period_id="2026-10", expected_version="v1", now=NOW,
                max_age=timedelta(minutes=5))
    assert derive_period_observation(snapshot(), **args) == (False, True)
    assert derive_period_observation(snapshot(closed=True), **args) == (True, False)


@pytest.mark.parametrize("bad", [
    snapshot(binding=SourceBinding("other", "company", "registered-source", "org", "base")),
    snapshot(period_id="2026-09"), snapshot(version="v2"), snapshot(auth_ref=" "),
    snapshot(observed_at=NOW + timedelta(seconds=1)),
    snapshot(observed_at=NOW - timedelta(minutes=5, microseconds=1)),
    None, object(),
])
def test_mismatched_missing_or_stale_snapshot_cannot_produce_period_evidence(bad):
    with pytest.raises(ObservationUnavailable):
        derive_period_observation(bad, binding=BINDING, period_id="2026-10", expected_version="v1",
                                  now=NOW, max_age=timedelta(minutes=5))


@pytest.mark.asyncio
async def test_begin_apply_builder_clears_caller_flags_and_uses_one_bound_read():
    forged = evidence(period_closed=True)
    reader = Reader(snapshot())
    result = await build_begin_apply_evidence(reader, forged, binding=BINDING, period_id="2026-10",
                                              expected_version="v1", now=NOW,
                                              max_age=timedelta(minutes=5))
    assert (result.period_closed, result.period_observed_open) == (False, True)
    assert reader.calls == [(BINDING, "2026-10")]


@pytest.mark.asyncio
async def test_closed_period_flows_from_observation_but_reader_failure_fails_closed():
    source_evidence = evidence(period_observed_open=True)
    closed = await build_begin_apply_evidence(Reader(snapshot(closed=True)), source_evidence, binding=BINDING,
        period_id="2026-10", expected_version="v1", now=NOW, max_age=timedelta(minutes=5))
    assert (closed.period_closed, closed.period_observed_open) == (True, False)
    with pytest.raises(ObservationUnavailable, match="PERIOD_OBSERVATION_UNAVAILABLE"):
        await build_begin_apply_evidence(Reader(error=RuntimeError("provider secret detail")), source_evidence,
            binding=BINDING, period_id="2026-10", expected_version="v1", now=NOW,
            max_age=timedelta(minutes=5))


@pytest.mark.asyncio
async def test_synthetic_closed_observation_refuses_begin_apply_as_period_closed():
    now = datetime.fromisoformat(SYNTHETIC_FIXTURE["observed_now"])
    observed = await build_begin_apply_evidence(
        Reader(synthetic_snapshot("CLOSED")),
        evidence(now=now, period_observed_open=True),
        binding=SourceBinding(**SYNTHETIC_FIXTURE["binding"]),
        period_id=SYNTHETIC_FIXTURE["period_id"],
        expected_version=SYNTHETIC_FIXTURE["source_version"],
        now=now,
        max_age=timedelta(seconds=SYNTHETIC_FIXTURE["max_age_seconds"]),
    )

    result = apply_transition(
        transition_fixtures.claimed(), Event.BEGIN_APPLY, observed
    )

    assert isinstance(result, Refusal)
    assert result.code is ErrorCode.PERIOD_CLOSED


@pytest.mark.asyncio
async def test_synthetic_open_observation_allows_begin_apply():
    now = datetime.fromisoformat(SYNTHETIC_FIXTURE["observed_now"])
    observed = await build_begin_apply_evidence(
        Reader(synthetic_snapshot("OPEN")), evidence(now=now),
        binding=SourceBinding(**SYNTHETIC_FIXTURE["binding"]),
        period_id=SYNTHETIC_FIXTURE["period_id"],
        expected_version=SYNTHETIC_FIXTURE["source_version"], now=now,
        max_age=timedelta(seconds=SYNTHETIC_FIXTURE["max_age_seconds"]),
    )

    result = apply_transition(
        transition_fixtures.claimed(), Event.BEGIN_APPLY, observed
    )

    assert type(result).__name__ == "Applied"
    assert (observed.period_closed, observed.period_observed_open) == (False, True)


@pytest.mark.asyncio
async def test_synthetic_stale_observation_fails_closed():
    now = datetime.fromisoformat(SYNTHETIC_FIXTURE["observed_now"])
    binding = SourceBinding(**SYNTHETIC_FIXTURE["binding"])
    with pytest.raises(ObservationUnavailable, match="PERIOD_OBSERVATION_STALE"):
        await build_begin_apply_evidence(
            Reader(synthetic_snapshot("STALE")), evidence(now=now), binding=binding,
            period_id=SYNTHETIC_FIXTURE["period_id"],
            expected_version=SYNTHETIC_FIXTURE["source_version"], now=now,
            max_age=timedelta(seconds=SYNTHETIC_FIXTURE["max_age_seconds"]),
        )

    result = apply_transition(
        transition_fixtures.claimed(), Event.BEGIN_APPLY,
        evidence(now=now, period_observed_open=False),
    )
    assert isinstance(result, Refusal)
    assert result.code is ErrorCode.DIGEST_MISMATCH

