"""Contract validation everywhere; actual Ferma generation requires an approved private snapshot."""
import json
import os
import sys
from pathlib import Path

import pytest

from testbed.ferma_onec.exporter import build, export, logical_utc, validate_snapshot
from testbed.ferma_onec.package_loader import load_seed_inputs

PIN = os.getenv('BAG_FERMA_PINNED_ROOT')


def test_empty_snapshot_is_refused_before_any_output(tmp_path):
    with pytest.raises(ValueError, match='SNAPSHOT_UNCONFIRMED'):
        export(tmp_path, tmp_path / 'new', seed=42, scenario='bakery-cafe', created_at='2026-01-01T00:00:00+00:00')
    assert not (tmp_path / 'new').exists()


def test_cached_bytecode_is_not_a_way_around_pinned_source_validation(tmp_path):
    (tmp_path / '__pycache__').mkdir()
    with pytest.raises(ValueError, match='SNAPSHOT_INVALID'):
        validate_snapshot(tmp_path)


def test_export_refuses_a_git_worktree_and_never_overwrites(tmp_path):
    (tmp_path / '.git').write_text('gitdir: fixture')
    with pytest.raises(ValueError, match='PRIVATE_TARGET_REQUIRED'):
        export(tmp_path, tmp_path / 'new', seed=42, scenario='bakery-cafe', created_at='2026-01-01T00:00:00+00:00')
    assert not (tmp_path / 'new').exists()
    other = tmp_path.parent / (tmp_path.name + '-existing')
    other.mkdir()
    with pytest.raises(ValueError, match='TARGET_EXISTS'):
        export(tmp_path, other, seed=42, scenario='bakery-cafe', created_at='2026-01-01T00:00:00+00:00')


@pytest.mark.parametrize('seed,scenario,created_at', [(True, 'bakery-cafe', 'invalid'), (-1, 'bakery-cafe', 'invalid'),
                          (2**31, 'bakery-cafe', 'invalid'), (42, 'new-scenario-family', 'invalid'),
                          (42, 'bakery-cafe', '2026-01-01T00:00:00')])
def test_unknown_family_unbounded_seed_or_naive_wall_clock_are_rejected(tmp_path, seed, scenario, created_at):
    with pytest.raises(ValueError, match='PARAMETERS_INVALID'):
        build(tmp_path, seed=seed, scenario=scenario, created_at=created_at)


def test_logical_axis_timezone_mapping_is_explicit_and_not_host_local():
    assert logical_utc('2020-01-01T00:00:00') == '2020-01-01T00:00:00+00:00'
    assert logical_utc('2020-01-01T02:00:00+02:00') == '2020-01-01T00:00:00+00:00'


@pytest.mark.skipif(not PIN, reason='requires approved private Ferma snapshot')
@pytest.mark.parametrize('scenario,event_count', [('bakery-cafe', 4), ('three-company-chain', 9)])
def test_actual_pinned_generator_exports_independent_oracle_and_reproducible_seed_inputs(tmp_path, monkeypatch, scenario, event_count):
    root = Path(PIN)
    validate_snapshot(root)
    # The first build loads the approved modules; break the ACTUAL projector, never the oracle.
    first = build(root, seed=42, scenario=scenario, created_at='2026-01-01T00:00:00+00:00')
    actual_module = sys.modules['ferma.actual.projector']

    def actual_must_not_be_constructed(*_args, **_kwargs):
        raise AssertionError('actual calculation reached exporter')

    monkeypatch.setattr(actual_module.ActualProjector, '__init__', actual_must_not_be_constructed)
    second = build(root, seed=42, scenario=scenario, created_at='2026-02-01T00:00:00+00:00')
    for name in ('master-data.jsonl', 'events.jsonl', 'expected/positions.jsonl'):
        assert first[name] == second[name]
    left, right = json.loads(first['manifest.json']), json.loads(second['manifest.json'])
    assert left['semantic_digest'] == right['semantic_digest']
    assert len(left['ferma_event_stream_digest']) == 32 and left['semantic_digest'].startswith('sha256:')
    assert left['ferma_digest_scheme'] == 'SEMANTIC_V3'
    assert left['ferma_clock_timezone_policy'] == 'NAIVE_LOGICAL_AS_UTC_V1'
    result = export(root, tmp_path / scenario, seed=42, scenario=scenario, created_at='2026-01-01T00:00:00+00:00')
    assert result['events'] == event_count and result['native_1c_called'] is False
    seed = load_seed_inputs(tmp_path / scenario)
    assert len(seed.events) == event_count and not hasattr(seed, 'expected')
    assert all('line_total' not in event for event in seed.events)
    expected = [json.loads(line) for line in first['expected/positions.jsonl'].splitlines()]
    assert expected and all(item['source'] == 'oracle' for item in expected)


@pytest.mark.skipif(not PIN, reason='requires approved private Ferma snapshot')
def test_oracle_unavailable_fails_before_creating_package(tmp_path, monkeypatch):
    root = Path(PIN)
    build(root, seed=42, scenario='bakery-cafe', created_at='2026-01-01T00:00:00+00:00')
    oracle = sys.modules['ferma.oracle.projector']

    def unavailable(*_args, **_kwargs):
        raise RuntimeError('fixture oracle unavailable')

    monkeypatch.setattr(oracle.OracleProjector, 'expect', unavailable)
    with pytest.raises(RuntimeError, match='oracle unavailable'):
        export(root, tmp_path / 'unavailable', seed=42, scenario='bakery-cafe', created_at='2026-01-01T00:00:00+00:00')
    assert not (tmp_path / 'unavailable').exists()
