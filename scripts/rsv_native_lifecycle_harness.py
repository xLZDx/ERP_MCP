"""Opt-in local Windows proof for the existing disposable base; never a second COM bridge."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.execute_evidence_tests import execute


def run() -> dict:
    if os.name != 'nt':
        raise RuntimeError('NATIVE_WINDOWS_REQUIRED')
    previous = os.environ.get('BAG_RSV_NATIVE_LIFECYCLE')
    os.environ['BAG_RSV_NATIVE_LIFECYCLE'] = '1'
    try:
        result = execute(['tests/test_rsv_native_lifecycle.py'], timeout_seconds=180)
    finally:
        if previous is None:
            os.environ.pop('BAG_RSV_NATIVE_LIFECYCLE', None)
        else:
            os.environ['BAG_RSV_NATIVE_LIFECYCLE'] = previous
    result.update(
        evidence_kind='LOCAL_DISPOSABLE_NATIVE_METADATA_LIFECYCLE',
        real_1c_call_status='CONFIRMED_BY_EXECUTED_NATIVE_TEST' if result['passed'] else 'NOT_PROVEN',
        operations=['ping', 'config'], killed_process_scope='TEST_OWNED_BRIDGE_HANDLE_ONLY',
        business_queries_enabled=False, native_engine_killed=False,
        binary_sha256='5c14b7db16e5dbf8cd20e2619255fe849edc75ac514bd6a21dedb1599710d728',
        upstream_source_sha='76fed8e6e16833fee1514969841b8d9a61c7c152',
        binary_source_parity_proven=False, native_accounting_reconciliation_proven=False,
        not_covered=['native_engine_crash', 'production_target', 'business_queries',
                     'zero_write_snapshot_proof', 'stdout_preparser_memory_limit'])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm-disposable-base', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    with args.output.open('x', encoding='utf-8') as output:
        output.write(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('Native metadata bridge lifecycle:', 'PASS' if result['passed'] else 'FAIL')
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
