from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from business_ai_gateway.admin_api import AdminAPI, AdminContext, AdminRoleBinding

ROLES = ['PLATFORM_ADMIN', 'SOURCE_ADMIN', 'ACCESS_ADMIN', 'PROFILE_ADMIN', 'AUDITOR', 'NONE']
SOURCE = {'PLATFORM_ADMIN', 'SOURCE_ADMIN'}
ACCESS = {'PLATFORM_ADMIN', 'ACCESS_ADMIN'}
PROFILE = {'PLATFORM_ADMIN', 'PROFILE_ADMIN'}
READ = set(ROLES) - {'NONE'}
ENDPOINTS = {
    'me': READ, 'overview_view': READ, 'sources': READ, 'companies': READ, 'capabilities': READ,
    'business_roles': READ, 'source_detail_view': READ, 'company_detail_view': READ,
    'profile_detail': PROFILE | {'AUDITOR'},
    'source_probe': SOURCE, 'source_create': SOURCE, 'source_update': SOURCE,
    'capability_refresh': SOURCE, 'company_create': SOURCE, 'company_update': SOURCE, 'drift_ack': SOURCE,
    'grant_create': ACCESS, 'grant_revoke': ACCESS,
    'platform_role_create': {'PLATFORM_ADMIN'}, 'platform_role_revoke': {'PLATFORM_ADMIN'},
    'business_role_assign': ACCESS, 'business_role_revoke': ACCESS,
    'capability_override_create': ACCESS, 'capability_override_revoke': ACCESS,
    'semantic_profile_create': PROFILE, 'semantic_mapping_create': PROFILE,
    'semantic_profile_validate': PROFILE, 'semantic_profile_retire': PROFILE, 'company_scope_mapping_create': PROFILE,
    'grants': ACCESS | {'AUDITOR'}, 'platform_role_bindings': {'PLATFORM_ADMIN', 'AUDITOR'},
    'principal_resolve': ACCESS | {'AUDITOR'}, 'business_role_assignments': ACCESS | {'AUDITOR'},
    'effective_access': ACCESS | {'AUDITOR'},
    'capability_overrides': ACCESS | {'AUDITOR'}, 'profiles': PROFILE | {'AUDITOR'},
    'company_scope_mappings': PROFILE | {'AUDITOR'}, 'audit': {'PLATFORM_ADMIN', 'AUDITOR'},
}


def req(source='s1'):
    target = str(uuid4())
    body = json.dumps({'source_id': source, 'principal_kind': 'subject', 'principal_id': 'exact-id',
                       'display_name': 'Test', 'base_url': 'https://approved.test/odata',
                       'enabled': True, 'reason': 'matrix', 'expected_version': 1, 'profile_id': target}).encode()

    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return Request({'type': 'http', 'method': 'POST', 'path': '/admin/v1/test', 'query_string': b'kind=subject&id=exact-id&source_id=s1',
                    'headers': [(b'idempotency-key', str(uuid4()).encode())],
                    'path_params': {'source_id': source, **{key: target for key in
                                    ('company_id', 'grant_id', 'binding_id', 'assignment_id', 'override_id', 'profile_id')}}}, receive)


def fake_api(role, scope=None):
    api = object.__new__(AdminAPI)
    api.settings = SimpleNamespace(admin_step_up_acr_values='urn:mfa', business_capability_enforcement_enabled=True)
    token = SimpleNamespace(subject='actor', client_id='client', claims={'acr': 'urn:mfa', 'auth_time': int(time.time())})
    ctx = AdminContext(token=token, groups=frozenset(), bindings=(AdminRoleBinding(role, scope),))
    api.authenticate = AsyncMock(return_value=JSONResponse({'error': 'PLATFORM_ROLE_DENIED'}, status_code=403) if role == 'NONE' else ctx)
    methods = ['source_detail', 'company_detail', 'source_model', 'visible_target', 'resolve_principal',
               'list_sources', 'list_companies', 'list_capabilities', 'list_business_roles', 'overview',
               'list_grants', 'list_platform_role_bindings', 'list_business_role_assignments', 'list_capability_overrides',
               'list_profiles', 'list_company_scope_mappings', 'list_access_audit', 'list_admin_audit']
    api.repository = SimpleNamespace(**{name: AsyncMock(return_value=[]) for name in methods})
    api.repository.db = SimpleNamespace(require_pool=lambda: SimpleNamespace(fetch=AsyncMock(return_value=[]),
        fetchrow=AsyncMock(return_value={'source_id': 's1'})))
    api.repository.visible_target.return_value = scope is None or scope == 's1'
    api.repository.company_detail.return_value = {'source_id': 's1'}
    api.repository.source_model.return_value = SimpleNamespace(base_url='https://approved.test/odata')
    api.repository.resolve_principal.return_value = {'mode': 'exact-id'}
    api.mutations = SimpleNamespace(**{name: AsyncMock(return_value={'id': 'result'}) for name in
        ['update_source','update_company','create_source','create_company','create_grant','revoke_grant',
         'create_platform_role','revoke_platform_role','assign_business_role','revoke_business_role',
         'create_capability_override','revoke_capability_override','create_semantic_profile','add_semantic_mapping',
         'validate_semantic_profile','retire_semantic_profile','create_company_scope_mapping','acknowledge_drift','record_admin_event','refresh_capabilities']})
    capabilities = SimpleNamespace(metadata_supported=True, metadata_fingerprint='fp', adapter_profile=SimpleNamespace(value='ODATA_JSON_V3'), as_dict=dict)

    @asynccontextmanager
    async def approved(_url):
        yield SimpleNamespace(capabilities=AsyncMock(return_value=capabilities)), {}

    api.probe = SimpleNamespace(probe=AsyncMock(return_value={}), approved_adapter=approved)
    api.runtime = SimpleNamespace(admin_db=True, registry=SimpleNamespace(save_capabilities=AsyncMock(return_value={'drift_status': 'STABLE'})))
    return api


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('endpoint', ENDPOINTS)
async def test_every_restricted_admin_endpoint_role_matrix(role, endpoint):
    api = fake_api(role)
    result = await getattr(api, endpoint)(req())
    assert result.status_code in ({200, 201} if role in ENDPOINTS[endpoint] else {403}), (role, endpoint, result.body)


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', ['source_update', 'capability_refresh', 'company_update', 'company_create', 'grant_create', 'business_role_assign', 'capability_override_create', 'semantic_profile_create', 'drift_ack'])
async def test_delegated_roles_cannot_cross_source_boundary(endpoint):
    role = 'SOURCE_ADMIN' if endpoint in {'source_update', 'capability_refresh', 'company_update', 'company_create', 'drift_ack'} else ('PROFILE_ADMIN' if endpoint == 'semantic_profile_create' else 'ACCESS_ADMIN')
    api = fake_api(role, scope='other-source')
    result = await getattr(api, endpoint)(req())
    assert result.status_code == 403
    for method in vars(api.mutations).values():
        method.assert_not_awaited()


@pytest.mark.asyncio
async def test_delegated_source_admin_cannot_repoint_own_source_to_another_credential_or_base():
    api = fake_api('SOURCE_ADMIN', scope='s1')
    api.repository.source_detail.return_value = {
        'source_id': 's1', 'base_url': 'https://assigned.test/odata',
        'username_secret_ref': 'ASSIGNED_USER', 'password_secret_ref': 'ASSIGNED_PASSWORD',
    }
    result = await api.source_update(req())
    assert result.status_code == 403
    api.probe.probe.assert_not_awaited()
    api.mutations.update_source.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [0, False, [], {}])
async def test_invalid_company_identifier_cannot_be_coerced_into_a_source_wide_grant(value):
    api = fake_api('ACCESS_ADMIN')
    request = req()
    body = json.loads(await request.body())
    body['company_id'] = value
    request._body = json.dumps(body).encode()
    async def receive():
        return {'type': 'http.request', 'body': request._body, 'more_body': False}
    request._receive = receive
    request._stream_consumed = False
    result = await api.grant_create(request)
    assert result.status_code == 400
    api.mutations.create_grant.assert_not_awaited()
