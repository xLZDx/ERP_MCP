"""Synthetic fail-closed helper coverage for AC-2; does not prove live-source AC-1."""
from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2.change.observations import (
    AuthenticatedPeriodSnapshot, ObservationUnavailable, SourceBinding,
    build_begin_apply_evidence, derive_period_observation,
)
from business_ai_gateway.phase2.change.killswitch import SWITCH_OFF
from business_ai_gateway.phase2.change.transitions import BeginApplyEvidence
from business_ai_gateway.phase2.change.types import CallerClass

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
BINDING = SourceBinding("tenant", "company", "registered-source", "org", "base")


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

