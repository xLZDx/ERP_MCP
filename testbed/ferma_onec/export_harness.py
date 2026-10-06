"""Execute actual private pinned-Ferma contracts; retain only sanitized counts/hash evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.execute_evidence_tests import execute

from .exporter import FERMA_COMMIT, SNAPSHOT_SHA256, validate_snapshot


def run(snapshot: Path) -> dict:
    validate_snapshot(snapshot)
    prior = os.environ.get('BAG_FERMA_PINNED_ROOT')
    prior_bytecode = os.environ.get('PYTHONDONTWRITEBYTECODE')
    os.environ['BAG_FERMA_PINNED_ROOT'] = str(snapshot)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        result = execute(['tests/test_ferma_exporter.py', 'tests/test_ferma_package_boundary.py',
                          'tests/test_ferma_reconcile.py', 'tests/test_engineering_checkpoint.py'],
                         timeout_seconds=180)
    finally:
        for key, value in [('BAG_FERMA_PINNED_ROOT', prior), ('PYTHONDONTWRITEBYTECODE', prior_bytecode)]:
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    result.update(ferma_commit=FERMA_COMMIT, source_snapshot_sha256=SNAPSHOT_SHA256,
                  observed_values_relabelled_as_expected=False, native_1c_called=False,
                  test_level='L1', output_class='INTERNAL_TEST_ONLY', production_approval=False,
                  scenarios=['bakery-cafe', 'three-company-chain'],
                  not_covered=['full_frozen_scenario_matrix', 'native_seeder', 'native_observer',
                               'gateway_observer', 'native_L2_reconciliation'])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ferma-snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.ferma_snapshot)
    with args.output.open('x', encoding='utf-8') as output:
        output.write(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('Pinned Ferma export contracts:', 'PASS' if result['passed'] else 'FAIL')
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
