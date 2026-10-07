import ast
import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.audit import (
    Audit,
    AuditUnavailable,
    begin_request_correlation_id,
    current_request_correlation_id,
    end_request_correlation_id,
)
from business_ai_gateway.observability import HTTPMetrics, OperationalMetrics, trace_span
from business_ai_gateway.principal import Principal
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings


def test_fixed_metric_tools_exactly_cover_registered_mcp_plus_internal_audit():
    source = Path('src/business_ai_gateway/server.py').read_text(encoding='utf-8')
    names = {node.name for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.AsyncFunctionDef) and any(
                 isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                 and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == 'mcp'
                 and decorator.func.attr == 'tool' for decorator in node.decorator_list)}
    assert OperationalMetrics.TOOLS == names | {'audit'}


def test_alphanumeric_source_company_query_labels_cannot_expand_tool_cardinality():
    metrics = OperationalMetrics()
    for index in range(2000):
        metrics.record_operation(f'PrivateCompany{index}', 'success')
        metrics.record_dependency(f'PrivateSource{index}', 'error')
    metrics.record_operation(['private-payload'], ['private-outcome'])
    metrics.record_dependency({'private': 'url'}, ['private-outcome'])
    rendered = metrics.render()
    assert 'Private' not in rendered and 'private' not in rendered
    assert len(metrics._operations) == 2 and len(metrics._dependencies) == 1
    assert 'tool="other",outcome="success"} 2000' in rendered


@pytest.mark.parametrize('duration', [float('nan'), float('inf'), True, None, 'private-duration', -1])
def test_dependency_duration_does_not_emit_non_measurements(duration):
    metrics = OperationalMetrics()
    metrics.record_dependency('audit', 'error', duration)
    assert 'dependency="audit",outcome="error"} 0.000000000' in metrics.render()
    assert 'private-duration' not in metrics.render()


def test_extreme_duration_cannot_overflow_exposed_sum():
    metrics = OperationalMetrics()
    metrics.record_dependency('audit', 'error', 1e308)
    metrics.record_dependency('audit', 'error', 1e308)
    assert 'dependency="audit",outcome="error"} 7200.000000000' in metrics.render()


@pytest.mark.parametrize('status', [True, 999999, -1, 'private-status', None])
async def test_malformed_asgi_status_cannot_expand_metric_labels(status):
    async def app(_scope, _receive, send):
        await send({'type': 'http.response.start', 'status': status})

    async def sink(_message):
        pass

    metrics = HTTPMetrics().bind(app)
    await metrics({'type': 'http', 'method': 'private-method', 'path': '/private-company'}, sink, sink)
    assert 'method="OTHER",route="other",status="500"' in metrics.render()
    assert 'private' not in metrics.render()


async def test_unknown_trace_names_and_alphanumeric_private_values_are_not_logged(caplog):
    with caplog.at_level(logging.INFO):
        async with trace_span('PrivateCompany', tool='PrivateToken123', adapter='PrivateSource',
                              dependency='PrivateDocument', outcome=['private'], query='raw-private'):
            pass
    assert 'Private' not in caplog.text and 'raw-private' not in caplog.text
    assert '"name":"other"' in caplog.text


PRINCIPAL = Principal('synthetic-subject', 'synthetic-client', frozenset({'onec:read'}), frozenset(), {})


async def write(audit, outcome='success'):
    await audit.write(principal=PRINCIPAL, tool='source_health', source_id='synthetic-source',
                      outcome=outcome, started_at=time.monotonic(), query={'private': 'raw-document'})


@pytest.mark.parametrize('outcome', ['success', 'denied', 'error'])
async def test_operation_outcome_is_recorded_only_after_actual_append(outcome):
    metrics = OperationalMetrics()
    rows = []

    async def execute(_sql, *values):
        assert not metrics._operations
        rows.append(values)

    audit = Audit(SimpleNamespace(require_pool=lambda: SimpleNamespace(execute=execute)),
                  include_query=False, metrics=metrics)
    await write(audit, outcome)
    assert len(rows) == 1 and rows[0][7] is None
    body = metrics.render()
    assert f'tool="source_health",outcome="{outcome}"}} 1' in body
    assert 'tool="audit",outcome="success"} 1' in body
    assert 'dependency="audit",outcome="success"} 1' in body
    assert 'raw-document' not in body


async def test_actual_append_failure_emits_existing_audit_alert_selector_without_false_success(caplog):
    metrics = OperationalMetrics()

    async def execute(*_args):
        raise RuntimeError('private-dsn-password-token')

    audit = Audit(SimpleNamespace(require_pool=lambda: SimpleNamespace(execute=execute)),
                  include_query=False, metrics=metrics)
    with caplog.at_level(logging.INFO), pytest.raises(AuditUnavailable, match='^AUDIT_UNAVAILABLE$') as failure:
        await write(audit)
    assert failure.value.__suppress_context__ is True and failure.value.__cause__ is None
    body = metrics.render()
    assert 'tool="audit",outcome="error"} 1' in body
    assert 'tool="source_health",outcome="error"} 1' in body
    assert 'dependency="audit",outcome="error"} 1' in body
    assert 'outcome="success"' not in body
    assert 'private-dsn-password-token' not in body + caplog.text


async def test_access_receipt_success_never_counts_as_completed_business_success():
    metrics = OperationalMetrics()

    async def execute(*_args):
        pass

    audit = Audit(SimpleNamespace(require_pool=lambda: SimpleNamespace(execute=execute)),
                  include_query=False, metrics=metrics)
    await audit.write(principal=PRINCIPAL, tool='source_health', source_id='synthetic-source',
                      outcome='success', started_at=time.monotonic(), detail_code='ACCESS_AUTHORIZED',
                      record_tool_outcome=False)
    assert 'tool="source_health"' not in metrics.render()
    assert 'tool="audit",outcome="success"} 1' in metrics.render()


@pytest.mark.parametrize('flag', [None, 1, 'false'])
async def test_receipt_metric_policy_rejects_non_boolean_before_append(flag):
    execute = AsyncMock()
    audit = Audit(SimpleNamespace(require_pool=lambda: SimpleNamespace(execute=execute)), include_query=False)
    with pytest.raises(ValueError, match='^AUDIT_METRIC_POLICY_INVALID$'):
        await audit.write(principal=PRINCIPAL, tool='source_health', source_id='synthetic-source',
                          outcome='success', started_at=time.monotonic(), record_tool_outcome=flag)
    execute.assert_not_awaited()


async def test_append_cancellation_propagates_and_never_becomes_success():
    metrics = OperationalMetrics()
    entered = asyncio.Event()

    async def execute(*_args):
        entered.set()
        await asyncio.Event().wait()

    audit = Audit(SimpleNamespace(require_pool=lambda: SimpleNamespace(execute=execute)),
                  include_query=False, metrics=metrics)
    task = asyncio.create_task(write(audit))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert 'outcome="success"' not in metrics.render()
    assert 'tool="audit",outcome="error"} 1' in metrics.render()


@pytest.mark.skipif(not os.getenv('BAG_PRIVILEGE_TEST_DATABASE_URL'), reason='requires disposable PostgreSQL')
async def test_real_database_receipt_precedes_dispatch_and_readonly_outage_blocks_it():
    connection = await asyncpg.connect(os.environ['BAG_PRIVILEGE_TEST_DATABASE_URL'])
    metrics = OperationalMetrics()
    audit = Audit(SimpleNamespace(require_pool=lambda: connection), include_query=False, metrics=metrics)
    rate = SimpleNamespace(check=AsyncMock())
    registry = SimpleNamespace(require_source=AsyncMock(return_value=SimpleNamespace(id='synthetic-source')))
    receipt = []

    async def adapter(_source):
        # Role SELECT grant permits checking the durable receipt in the adapter itself.
        row = await connection.fetchrow(
            "SELECT request_id, query_json, outcome FROM bag.audit_events "
            "WHERE request_id=$1 AND tool_name='source_health' "
            "AND detail_code='ACCESS_AUTHORIZED'", current_request_correlation_id())
        assert row is not None and row['query_json'] is None and row['outcome'] == 'success'
        receipt.append(row['request_id'])
        return {'status': 'ok'}

    onec = SimpleNamespace(health=AsyncMock(side_effect=adapter))
    mcp = build_mcp(Settings(), SimpleNamespace(audit=audit, registry=registry, rate_limit=rate, onec=onec))
    # Direct SDK calls omit transport middleware; explicitly establish its request context.
    token, _ = begin_request_correlation_id()
    try:
        await connection.execute('SET ROLE business_ai_app')
        result = await mcp.call_tool('source_health', {'source_id': 'synthetic-source'})
        assert not result.is_error and len(receipt) == 1
        rows = await connection.fetch(
            'SELECT detail_code, query_json FROM bag.audit_events WHERE request_id=$1', receipt[0])
        assert len(rows) == 2 and all(row['query_json'] is None for row in rows)
        assert sum(row['detail_code'] == 'ACCESS_AUTHORIZED' for row in rows) == 1
        onec.health.reset_mock()
        async with connection.transaction(readonly=True):
            with pytest.raises(UnexpectedToolError):
                await mcp.call_tool('source_health', {'source_id': 'synthetic-source'})
        onec.health.assert_not_awaited()
        body = metrics.render()
        assert 'tool="source_health",outcome="success"} 1' in body
        assert 'tool="audit",outcome="error"} 1' in body
        assert 'dependency="audit",outcome="error"} 1' in body
    finally:
        end_request_correlation_id(token)
        await connection.close()


@pytest.mark.skipif(not os.getenv('BAG_PRIVILEGE_TEST_DATABASE_URL'), reason='requires disposable PostgreSQL')
async def test_actual_runtime_role_insert_and_readonly_failure_drive_audit_alert():
    connection = await asyncpg.connect(os.environ['BAG_PRIVILEGE_TEST_DATABASE_URL'])
    metrics = OperationalMetrics()
    principal = Principal(f'audit-drill-{uuid.uuid4()}', 'synthetic', frozenset(), frozenset(), {})
    audit = Audit(SimpleNamespace(require_pool=lambda: connection), include_query=False, metrics=metrics)
    try:
        await connection.execute('SET ROLE business_ai_app')
        await audit.write(principal=principal, tool='system_status', source_id=None,
                          outcome='success', started_at=time.monotonic())
        with pytest.raises(AuditUnavailable, match='^AUDIT_UNAVAILABLE$'):
            async with connection.transaction(readonly=True):
                await audit.write(principal=principal, tool='system_status', source_id=None,
                                  outcome='success', started_at=time.monotonic())
        await connection.execute('RESET ROLE')
        count = await connection.fetchval('SELECT count(*) FROM bag.audit_events WHERE principal_subject=$1',
                                          principal.subject)
        assert count == 1  # append-only synthetic audit row retained, never deleted
        body = metrics.render()
        assert 'tool="system_status",outcome="success"} 1' in body
        assert 'tool="system_status",outcome="error"} 1' in body
        assert 'tool="audit",outcome="error"} 1' in body
        assert 'dependency="audit",outcome="error"} 1' in body
        assert principal.subject not in body
    finally:
        await connection.close()
