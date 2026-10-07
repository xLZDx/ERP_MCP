"""Test-only package exporter using exact pinned Ferma generator/oracle, never actual positions.

No Ferma code is copied into the production package. Supply a private immutable git-archive
snapshot containing src/ferma, architecture/independence_policy.toml and tests/archcheck.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from .package_loader import MAX_FILE_BYTES, MAX_RECORDS, MAX_TOTAL_BYTES, load_seed_inputs
from .schema import ScenarioManifest

FERMA_COMMIT = 'd361fab0c3b251ff3c55f681bd2e192bb36c0019'
SNAPSHOT_SHA256 = 'b96e4cde74427e3bbf54ac6f6dd453b8c120ff0e23285c05f9cfc050ceeef4be'


def validate_snapshot(root: Path):
    if not root.is_dir() or root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError('FERMA_SNAPSHOT_INVALID')
    paths = []
    total = 0
    for entries, path in enumerate(root.rglob('*'), start=1):
        if entries > 512 or path.is_symlink() or path.name == '__pycache__' or path.suffix in {'.pyc', '.pyo'}:
            raise ValueError('FERMA_SNAPSHOT_INVALID')
        if path.is_file():
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError('FERMA_SNAPSHOT_INVALID')
            paths.append(path)
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        with path.open('rb') as source:
            content = source.read(MAX_FILE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('FERMA_SNAPSHOT_INVALID')
        digest.update(hashlib.sha256(content).digest())
    if len(paths) != 132 or digest.hexdigest() != SNAPSHOT_SHA256:
        raise ValueError('FERMA_SNAPSHOT_UNCONFIRMED')


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def jsonl(rows) -> bytes:
    if len(rows) > MAX_RECORDS:
        raise ValueError('FERMA_EXPORT_LIMIT')
    return b''.join(encoded(row) + b'\n' for row in rows)


def logical_utc(value: str) -> str:
    """Declared synthetic test-plane axis, NOT inference of a native company's timezone."""
    parsed = datetime.fromisoformat(value)
    return (parsed.replace(tzinfo=UTC) if parsed.utcoffset() is None else parsed.astimezone(UTC)).isoformat()


def build(root: Path, *, seed: int, scenario: str, created_at: str) -> dict[str, bytes]:
    """All values derived inside Ferma; this boundary only serializes/checksums them."""
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1 or scenario not in {'bakery-cafe', 'three-company-chain'}:
        raise ValueError('FERMA_EXPORT_PARAMETERS_INVALID')
    if not isinstance(created_at, str) or datetime.fromisoformat(created_at).utcoffset() is None:
        raise ValueError('FERMA_EXPORT_PARAMETERS_INVALID')
    validate_snapshot(root)
    for name, module in tuple(sys.modules.items()):
        if name == 'ferma' or name.startswith('ferma.') or name == 'archcheck':
            path = Path(getattr(module, '__file__', '')).resolve()
            if not path.is_relative_to(root):
                raise ValueError('FERMA_IMPORT_SOURCE_UNCONFIRMED')
    previous_bytecode = sys.dont_write_bytecode
    previous_path = sys.path[:]
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root / 'src'), str(root / 'tests')]
    try:
        from archcheck import evaluate_boundary
        from ferma.clock import EPOCH
        from ferma.oracle.projector import OracleProjector
        from ferma.runtime.session import prepare_canonical
        from ferma.testdata.generators.profiles import BAKERY_CAFE_ECONOMY, THREE_TIER_CHAIN_ECONOMY
        from ferma.testdata.manifest import semantic_digest

        policy = tomllib.loads((root / 'architecture/independence_policy.toml').read_text(encoding='utf-8'))
        boundary = next(item for item in policy['boundary'] if item['package'] == 'ferma/oracle')
        proof = evaluate_boundary(boundary, root / 'src')
        if not proof.ok or proof.files_checked == 0:
            raise ValueError('FERMA_ORACLE_BOUNDARY_FAILED')
        if scenario == 'bakery-cafe':
            from ferma.scenarios.bakery_cafe_validated import provenance_for
            profile = BAKERY_CAFE_ECONOMY
            prepared = prepare_canonical(provenance_for(seed))
        else:
            from ferma.scenarios.bakery_distributor_retail_validated import (
                chain_generator,
                provenance_for,
            )
            profile = THREE_TIER_CHAIN_ECONOMY
            prepared = prepare_canonical(provenance_for(seed), generator=chain_generator())
        prepared.require()  # actual Ferma integrity + source-usage policy, not a declared PASS
        oracle = OracleProjector()
        for event in prepared.events:
            if not oracle.accept(event):
                raise ValueError('FERMA_EVENT_REPLAY_IN_EXPORT')
        ticks = sorted({event.simulation_tick for event in prepared.events})
        expected = [oracle.expect(as_of_tick=tick).model_dump(mode='json') for tick in ticks]
        if not expected or any(item['source'] != 'oracle' for item in expected):
            raise ValueError('FERMA_ORACLE_OUTPUT_INVALID')
        master = [{'record_type': type(record).__name__, 'data': record.model_dump(mode='json')}
                  for record in prepared.dataset.records()]
        events = [event.model_dump(mode='json') for event in prepared.events]
        for event in events:
            event['business_date'] = logical_utc(event['business_date'])
        profile_json = profile.model_dump(mode='json')
        payloads = {'master-data.jsonl': jsonl(master), 'events.jsonl': jsonl(events),
                    'expected/positions.jsonl': jsonl(expected)}
        # Package SHA-256 is NOT Ferma's 128-bit truncated BLAKE2b SEMANTIC_V3 identity.
        economic = {'profile': profile_json, 'master_data': master, 'events': events, 'expected': expected}
        manifest = ScenarioManifest(
            schema_version='ferma-1c-scenario/v1', scenario_id=prepared.provenance.scenario_id,
            run_id=prepared.run_id, universe_id=prepared.provenance.universe_id, master_seed=seed,
            generator_version=prepared.manifest.dataset.generator_version, ferma_commit=FERMA_COMMIT,
            profile_id=prepared.manifest.dataset.profile_id,
            profile_digest='sha256:' + hashlib.sha256(encoded(profile_json)).hexdigest(),
            logical_clock_epoch=logical_utc(EPOCH.isoformat()), mapping_contract_version='1', created_at_wall_clock=created_at,
            semantic_digest='sha256:' + hashlib.sha256(encoded(economic)).hexdigest(),
            semantic_digest_scheme='ERP_MCP_EXPORT_SHA256_JSON_V1',
            ferma_digest_scheme=prepared.manifest.dataset.digest_scheme.value,
            ferma_event_stream_digest=prepared.event_stream_digest,
            ferma_dataset_digest=prepared.manifest.dataset.dataset_digest,
            ferma_profile_digest=semantic_digest(profile), oracle_rules_version=expected[0]['oracle_rules_version'],
            ferma_clock_timezone_policy='NAIVE_LOGICAL_AS_UTC_V1',
            output_class='INTERNAL_TEST_ONLY')
        payloads['manifest.json'] = encoded(manifest.model_dump()) + b'\n'
        if any(len(value) > MAX_FILE_BYTES for value in payloads.values()) or sum(map(len, payloads.values())) > MAX_TOTAL_BYTES:
            raise ValueError('FERMA_EXPORT_LIMIT')
        validate_snapshot(root)  # fail if execution source changed during the run
        return payloads
    finally:
        sys.dont_write_bytecode = previous_bytecode
        sys.path[:] = previous_path


def export(root: Path, output: Path, *, seed: int, scenario: str, created_at: str) -> dict:
    resolved_output = output.resolve()
    if any((parent / '.git').exists() for parent in (resolved_output, *resolved_output.parents)):
        raise ValueError('FERMA_EXPORT_PRIVATE_TARGET_REQUIRED')
    if output.exists() or output.is_symlink():
        raise ValueError('FERMA_EXPORT_TARGET_EXISTS')
    # No directory/artifact exists if generation/oracle/policy/boundary validation fails.
    payloads = build(root, seed=seed, scenario=scenario, created_at=created_at)
    output.mkdir(parents=False, exist_ok=False)
    (output / 'expected').mkdir()
    for name, content in payloads.items():
        with (output / name).open('xb') as stream:
            stream.write(content)
    checksums = '\n'.join(f'{hashlib.sha256(payloads[name]).hexdigest()}  {name}' for name in sorted(payloads)) + '\n'
    with (output / 'checksums.sha256').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(checksums)  # final verification marker, never overwrite an existing package
    seeded = load_seed_inputs(output)
    return {'status': 'PASS', 'ferma_commit': FERMA_COMMIT, 'snapshot_sha256': SNAPSHOT_SHA256,
            'scenario_id': seeded.manifest.scenario_id, 'events': len(seeded.events),
            'master_records': len(seeded.master_data), 'test_level': 'L1',
            'native_1c_called': False, 'production_approval': False, 'output_class': 'INTERNAL_TEST_ONLY'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ferma-snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--scenario', choices=['bakery-cafe', 'three-company-chain'], default='bakery-cafe')
    parser.add_argument('--created-at', required=True)
    args = parser.parse_args()
    try:
        result = export(args.ferma_snapshot, args.output, seed=args.seed,
                        scenario=args.scenario, created_at=args.created_at)
    except Exception:  # noqa: BLE001 - no private path/generated payload/provider errors in CLI output
        raise SystemExit('FERMA_EXPORT_FAILED: private diagnostics withheld') from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
