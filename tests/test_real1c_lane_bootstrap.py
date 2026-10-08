"""Regression checks for the real-1C disposable auditor-grant bootstrap.

No real 1C, PostgreSQL, credentials or network is touched here.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.real1c.lane_setup import SOURCE_DRIFT, SOURCE_REAL, ensure_auditor_source_grant


def test_fixture_auditor_grant_created_only_for_real_source():
    env = SimpleNamespace(raw={
        "environment": "test", "real1c": True, "seed_mode": "bootstrap-only",
        "identities": {"auditor": {"sub": "auditor"}},
    })
    access = Mock()
    access.get.return_value = SimpleNamespace(status_code=200, json=lambda: {"items": []})
    access.post.return_value = SimpleNamespace(status_code=201, json=lambda: {"id": "new-grant"})

    assert ensure_auditor_source_grant(env, access) == "new-grant"
    access.get.assert_called_once_with("/admin/v1/grants")
    args, _ = access.post.call_args
    assert args[0] == "/admin/v1/grants"
    body = args[1]
    assert body["principal_kind"] == "subject"
    assert body["principal_id"] == "auditor"
    assert body["source_id"] == SOURCE_REAL
    assert body["company_id"] is None
    assert body["all_sources"] is False
    assert body["effect"] == "allow"
    assert SOURCE_DRIFT not in str(body)


def test_existing_exact_source_grant_is_idempotent():
    env = SimpleNamespace(raw={
        "environment": "test", "real1c": True, "seed_mode": "bootstrap-only",
        "identities": {"auditor": {"sub": "auditor"}},
    })
    access = Mock()
    access.get.return_value = SimpleNamespace(status_code=200, json=lambda: {
        "items": [
            {"grant_id": "irrelevant", "principal_kind": "subject", "principal_id": "auditor",
             "source_id": SOURCE_DRIFT, "company_id": None, "all_sources": False,
             "effect": "allow", "revoked_at": None, "expires_at": None},
            {"grant_id": "existing", "principal_kind": "subject", "principal_id": "auditor",
             "source_id": SOURCE_REAL, "company_id": None, "all_sources": False,
             "effect": "allow", "revoked_at": None, "expires_at": None},
        ],
    })
    assert ensure_auditor_source_grant(env, access) == "existing"
    access.post.assert_not_called()


@pytest.mark.parametrize("environment,real1c,seed", [
    ("production", True, "bootstrap-only"),
    ("development", True, "bootstrap-only"),
    ("test", False, "bootstrap-only"),
    ("test", True, "baseline"),
])
def test_refuses_any_non_disposable_real1c_bootstrap(environment, real1c, seed):
    env = SimpleNamespace(raw={
        "environment": environment, "real1c": real1c, "seed_mode": seed,
        "identities": {"auditor": {"sub": "auditor"}},
    })
    access = Mock()
    with pytest.raises(RuntimeError, match="AUDITOR_GRANT_REQUIRES_"):
        ensure_auditor_source_grant(env, access)
    access.get.assert_not_called()
    access.post.assert_not_called()


def test_refuses_when_grants_cannot_be_verified():
    env = SimpleNamespace(raw={
        "environment": "test", "real1c": True, "seed_mode": "bootstrap-only",
        "identities": {"auditor": {"sub": "auditor"}},
    })
    access = Mock()
    access.get.return_value = SimpleNamespace(status_code=403)
    with pytest.raises(RuntimeError, match="AUDITOR_GRANT_LIST_UNAVAILABLE"):
        ensure_auditor_source_grant(env, access)
    access.post.assert_not_called()


def test_does_not_reuse_company_scoped_or_revoked_grants():
    env = SimpleNamespace(raw={
        "environment": "test", "real1c": True, "seed_mode": "bootstrap-only",
        "identities": {"auditor": {"sub": "auditor"}},
    })
    access = Mock()
    access.get.return_value = SimpleNamespace(status_code=200, json=lambda: {
        "items": [
            {"grant_id": "company", "principal_kind": "subject", "principal_id": "auditor",
             "source_id": SOURCE_REAL, "company_id": "some-company-id", "all_sources": False,
             "effect": "allow", "revoked_at": None, "expires_at": None},
            {"grant_id": "revoked", "principal_kind": "subject", "principal_id": "auditor",
             "source_id": SOURCE_REAL, "company_id": None, "all_sources": False,
             "effect": "allow", "revoked_at": "2026-10-09", "expires_at": None},
        ],
    })
    access.post.return_value = SimpleNamespace(status_code=201, json=lambda: {"id": "fresh"})
    assert ensure_auditor_source_grant(env, access) == "fresh"
    access.post.assert_called_once()

def test_smoke_tool_enforces_real1c_loopback_and_exact_negative_coverage():
    from scripts.real1c.verify_install import CHECKS, ensure_disposable

    assert len(CHECKS) == 7
    assert sum(case.should_allow for case in CHECKS) == 2
    assert all(case.source_id == SOURCE_REAL for case in CHECKS if case.should_allow)
    assert {case.source_id for case in CHECKS if not case.should_allow} >= {SOURCE_DRIFT, "onec-818ha-down"}
    safe = {
        "environment": "test", "real1c": True, "seed_mode": "bootstrap-only",
        "host": "127.0.0.1", "project": "erpmcp-e2e-installreal-20261009",
        "urls": {"gateway": "http://127.0.0.1:28500"},
    }
    ensure_disposable(SimpleNamespace(raw=safe))
    for unsafe in (
        {**safe, "environment": "production"},
        {**safe, "real1c": False},
        {**safe, "host": "192.0.2.2"},
        {**safe, "project": "production"},
        {**safe, "urls": {"gateway": "https://example.com"}},
    ):
        with pytest.raises(RuntimeError, match="DISPOSABLE_LOOPBACK_TEST"):
            ensure_disposable(SimpleNamespace(raw=unsafe))
