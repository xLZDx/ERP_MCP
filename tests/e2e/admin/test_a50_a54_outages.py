"""A50-A54: dependency outages during Admin use, each followed by recovery without a restart.

Components are stopped with scripts/e2e/fault.ps1 through ``admin_support.outage`` (or the
explicit try/finally in A54) and ALWAYS restored and re-verified healthy. Failure responses must
be sanitized (``{"error": CODE}`` only), bounded in time and free of internals or secrets.
"""

from __future__ import annotations

import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from admin_support import (
    E2E_DIR,
    AdminSession,
    anonymous,
    bearer,
    data_view,
    expect,
    fault,
    find_leaks,
    outage,
    secret_values,
    shot,
    unique,
    wait_healthy,
    wait_until,
)

pytestmark = [pytest.mark.admin]

INTERNALS = ("127.0.0.1", "18766", "Traceback", "httpx", "asyncpg", "redis", "sqlalchemy",
             "psycopg", "File \"")
BOUND_SECONDS = 60


def _clean_failure(env, resp, *, status=None):
    assert resp.status >= 400 and (status is None or resp.status == status), resp.describe()
    assert isinstance(resp.body, dict) and set(resp.body) == {"error"}, resp.describe()
    assert not find_leaks(resp.text, secret_values(env)), f"secret in {resp.describe()}"
    for marker in INTERNALS:
        assert marker not in resp.text, f"internal detail {marker!r} leaked: {resp.describe()}"


def _timed(call):
    started = time.monotonic()
    result = call()
    return result, time.monotonic() - started


# --------------------------------------------------------------------------------------- A50
def _ui_refresh(page, source_id, reason):
    card = page.locator(".card", has_text="Registered sources")
    card.locator("tr", has_text=source_id).get_by_role("button",
                                                       name="Refresh metadata").click()
    page.wait_for_selector(".modal")
    page.fill("#wf_reason", reason)
    page.click(".modalf button.primary")


def test_A50_fake1c_outage_gives_clear_failure_then_recovers(e2e_env, world, evidence,
                                                              browser_login):
    world.need("source", "caps")
    pa = world.pa
    page = browser_login("platform_admin")
    page.click('.nav button[data-page="sources"]')
    page.wait_for_selector(".content table")
    original = evidence.one("SELECT metadata_fingerprint FROM bag.source_capabilities "
                            "WHERE source_id=$1", world.source_id)["metadata_fingerprint"]
    with outage(e2e_env, "fake1c"):
        refresh, took = _timed(lambda: pa.post(
            f"/admin/v1/sources/{world.source_id}/capability-refresh",
            {"reason": "A50 refresh during outage"}))
        _clean_failure(e2e_env, refresh)
        assert took < BOUND_SECONDS, f"refresh hung for {took:.0f}s"
        probe, took = _timed(lambda: pa.post("/admin/v1/source-probes", {
            "base_url": e2e_env.fake1c_url, "username_secret_ref": "FAKE1C_USERNAME",
            "password_secret_ref": "FAKE1C_PASSWORD"}))
        _clean_failure(e2e_env, probe)
        assert took < BOUND_SECONDS
        expect(pa.get("/admin/v1/sources"), 200, "admin reads keep working during the outage")
        _ui_refresh(page, world.source_id, "A50 UI refresh during outage")
        page.wait_for_function("() => document.querySelector('#workflow_error')"
                               "?.innerText.length > 0", timeout=BOUND_SECONDS * 1000)
        message = page.inner_text("#workflow_error")
        assert message and not any(m in message for m in INTERNALS), message
        shot(page, "A50-outage-error")
        page.keyboard.press("Escape")
    recovered = expect(pa.post(f"/admin/v1/sources/{world.source_id}/capability-refresh",
                               {"reason": "A50 refresh after recovery"}), 200, "A50 recovery")
    assert recovered.body["metadata_fingerprint"] == original
    events = evidence.rows("SELECT outcome FROM bag.admin_audit_events WHERE source_id=$1 AND "
                           "action='capability.refresh' AND occurred_at >= $2 "
                           "ORDER BY occurred_at", world.source_id, world.t0)
    outcomes = [e["outcome"] for e in events]
    assert "error" in outcomes and outcomes[-1] == "success", (
        f"expected an audited failure followed by a success, got {outcomes}")
    assert evidence.admin_events(refresh)[0]["outcome"] == "error"


def test_A50_ui_retry_in_same_dialog_recovers_after_outage(e2e_env, world, browser_login):
    """After a failed submit, resubmitting the open dialog once the source is back must work."""
    world.need("source", "caps")
    page = browser_login("platform_admin")
    page.click('.nav button[data-page="sources"]')
    page.wait_for_selector(".content table")
    with outage(e2e_env, "fake1c"):
        _ui_refresh(page, world.source_id, "A50 retry same dialog")
        page.wait_for_function("() => document.querySelector('#workflow_error')"
                               "?.innerText.length > 0", timeout=BOUND_SECONDS * 1000)
    page.click(".modalf button.primary")
    page.wait_for_function(
        "() => document.querySelector('#toast .toast')?.innerText.startsWith('Success') || "
        "document.querySelector('#workflow_error')?.innerText.length > 0",
        timeout=BOUND_SECONDS * 1000)
    toast = page.evaluate("() => document.querySelector('#toast .toast')?.innerText || ''")
    error = page.evaluate("() => document.querySelector('#workflow_error')?.innerText || ''")
    assert toast.startswith("Success"), (
        f"retry of the same dialog after recovery did not succeed: error={error!r}")


# --------------------------------------------------------------------------------------- A51
def test_A51_redis_outage_fails_closed_and_recovers(e2e_env, idp, world, evidence):
    world.need("source", "company_one")
    pa = world.pa
    token = idp.token("platform_admin", audience="admin")
    principal = unique("e2e-redis-down")
    expect(bearer(e2e_env, token, "GET", "/admin/v1/me", subject="platform_admin"), 200,
           "A51 baseline bearer call")
    mutation_key = unique("redis-down")
    with outage(e2e_env, "redis"):
        responses, took = _timed(lambda: [
            pa.get("/admin/v1/me"),
            bearer(e2e_env, token, "GET", "/admin/v1/sources", subject="platform_admin"),
            pa.post("/admin/v1/grants", {
                "principal_kind": "subject", "principal_id": principal,
                "source_id": world.source_id, "company_id": None, "effect": "allow",
                "reason": "A51 mutation during Redis outage"}, key=mutation_key),
            anonymous(e2e_env, "GET", "/admin/login"),
        ])
        for resp in responses:
            _clean_failure(e2e_env, resp, status=503)
            assert resp.error == "ADMIN_DEPENDENCY_UNAVAILABLE", resp.describe()
        assert took < BOUND_SECONDS, f"fail-closed responses took {took:.0f}s"
    wait_until(lambda: bearer(e2e_env, token, "GET", "/admin/v1/me",
                              subject="platform_admin").status == 200,
               timeout=60, interval=1.0, what="bearer admin calls to recover after Redis restart")
    assert evidence.count("access_grants", "principal_id=$1", principal) == 0, (
        "a mutation was applied while Redis was down")
    assert evidence.count("admin_audit_events", "idempotency_key=$1 AND outcome='success'",
                          mutation_key) == 0
    # Sessions live only in Redis (no persistence): the old cookie is gone, a new login works.
    assert pa.get("/admin/v1/me").status == 401, "session survived a Redis restart"
    fresh = AdminSession(e2e_env, "platform_admin")
    try:
        grant = expect(world.scratch_grant(fresh, principal=principal), 201,
                       "A51 mutation after recovery")
        assert evidence.admin_events(grant)[0]["outcome"] == "success"
        expect(world.revoke_grant(fresh, grant.body["id"]), 200, "A51 cleanup")
    finally:
        fresh.close()
    world.sessions.clear()  # cached sessions died with Redis; log in again on demand


# --------------------------------------------------------------------------------------- A52
def _forged(env, kid, key=None):
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    claims = {"iss": env.issuer, "sub": "platform_admin", "aud": env.raw["audiences"]["admin"],
              "scope": env.raw["scopes"]["admin"], "iat": now, "nbf": now, "exp": now + 300,
              "jti": str(uuid.uuid4()), "client_id": env.raw["idp"]["admin_client_id"],
              "groups": env.raw["identities"]["platform_admin"]["groups"]}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def test_A52_idp_outage_is_fail_closed_for_new_tokens_and_recovers(e2e_env, idp, world):
    world.need("source")
    jwks = httpx.get(e2e_env.raw["idp"]["jwks_uri"], trust_env=False, timeout=10).json()
    real_kid = jwks["keys"][0]["kid"]
    unknown_kid_token = _forged(e2e_env, "e2e-unknown-kid")
    bad_signature_token = _forged(e2e_env, real_kid)
    good = idp.token("platform_admin", audience="admin")
    expect(bearer(e2e_env, good, "GET", "/admin/v1/me", subject="platform_admin"), 200,
           "A52 baseline (also warms the JWKS cache)")

    browser = httpx.Client(base_url=e2e_env.gateway, follow_redirects=False, trust_env=False,
                           timeout=30)
    try:
        start = browser.get("/admin/login")
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        with outage(e2e_env, "idp"):
            with pytest.raises(httpx.TransportError):
                idp.token("platform_admin", audience="admin")  # no new tokens can be minted
            for label, token in (("unknown kid", unknown_kid_token),
                                 ("bad signature", bad_signature_token)):
                resp, took = _timed(lambda token=token: bearer(
                    e2e_env, token, "GET", "/admin/v1/me", subject="platform_admin"))
                assert resp.status == 401, f"{label} accepted during IdP outage: {resp.describe()}"
                assert took < 20, f"{label}: verification took {took:.0f}s"
            callback, took = _timed(lambda: browser.get(
                "/admin/callback", params={"code": "e2e-fake-code", "state": state}))
            assert callback.status_code == 502 and callback.json() == {
                "error": "OIDC_TOKEN_EXCHANGE_FAILED"}, callback.text
            assert took < 30 and "erp_mcp_admin_session" not in browser.cookies
    finally:
        browser.close()

    after = idp.token("platform_admin", audience="admin")
    expect(bearer(e2e_env, after, "GET", "/admin/v1/me", subject="platform_admin"), 200,
           "A52 new tokens accepted after the IdP is back (no gateway restart)")
    for token in (unknown_kid_token, bad_signature_token):
        assert bearer(e2e_env, token, "GET", "/admin/v1/me",
                      subject="platform_admin").status == 401, "unverifiable token accepted"
    login = AdminSession(e2e_env, "platform_admin")
    try:
        expect(login.get("/admin/v1/me"), 200, "A52 login works again")
    finally:
        login.close()


# --------------------------------------------------------------------------------------- A53
def test_A53_postgres_outage_fails_closed_and_recovers(e2e_env, idp, world, evidence):
    world.need("source", "company_one", "uc1_grant")
    world.ensure_uc1_access()
    pa = world.pa  # captured before the outage: session state lives in Redis
    principal, key = unique("e2e-pg-down"), unique("pg-down")
    with outage(e2e_env, "postgres"):
        read, took = _timed(lambda: pa.get("/admin/v1/sources"))
        write = pa.post("/admin/v1/grants", {
            "principal_kind": "subject", "principal_id": principal,
            "source_id": world.source_id, "company_id": None, "effect": "allow",
            "reason": "A53 mutation during PostgreSQL outage"}, key=key)
        for resp in (read, write):
            _clean_failure(e2e_env, resp, status=503)
        assert took < BOUND_SECONDS, f"read took {took:.0f}s"
        denied = data_view(e2e_env, idp.token("user_company_one"), world.source_id)
        assert not denied.sees_source(world.source_id) and not denied.companies, (
            f"data plane allowed access without a database: {denied}")
    wait_until(lambda: pa.get("/admin/v1/me").status == 200, timeout=120, interval=1.0,
               what="Admin API to recover after PostgreSQL restart")
    assert evidence.count("access_grants", "principal_id=$1", principal) == 0, (
        "a grant was written while PostgreSQL was down")
    assert evidence.count("admin_audit_events", "idempotency_key=$1", key) == 0
    grant = expect(world.scratch_grant(pa, principal=principal), 201, "A53 write after recovery")
    audit = evidence.admin_events(grant)
    assert audit and audit[0]["outcome"] == "success", "mutation after recovery has no audit"
    expect(world.revoke_grant(pa, grant.body["id"]), 200, "A53 cleanup")
    wait_until(lambda: data_view(e2e_env, idp.token("user_company_one"), world.source_id
                                 ).sees_company(world.company_id("one")),
               timeout=60, interval=2.0, what="data plane to recover after PostgreSQL restart")


# --------------------------------------------------------------------------------------- A54
def test_A54_secret_provider_failure_fails_closed_then_recovers(e2e_env, world, evidence):
    """The env secret provider is made to fail by restarting the gateway without the 1C
    credential variables (``.e2e/env.ps1`` is restored byte-for-byte in ``finally``)."""
    world.need("source", "caps")
    pa = world.pa  # sessions live in Redis and survive the gateway restart
    env_file = E2E_DIR / "env.ps1"
    original = env_file.read_bytes()
    broken = (original.replace(b"$env:FAKE1C_PASSWORD", b"$env:E2E_DISABLED_FAKE1C_PASSWORD")
              .replace(b"$env:FAKE1C_USERNAME", b"$env:E2E_DISABLED_FAKE1C_USERNAME"))
    assert broken != original, "env.ps1 does not define the FAKE1C credential variables"
    drop = ("FAKE1C_USERNAME", "FAKE1C_PASSWORD")
    before_sources = evidence.count("sources")
    failures = {}
    try:
        env_file.write_bytes(broken)
        fault("gateway", "restart", drop_env=drop)
        wait_healthy(e2e_env, "gateway")
        failures["probe"] = pa.post("/admin/v1/source-probes", {
            "base_url": e2e_env.fake1c_url, "username_secret_ref": "FAKE1C_USERNAME",
            "password_secret_ref": "FAKE1C_PASSWORD"})
        failures["refresh"] = pa.post(f"/admin/v1/sources/{world.source_id}/capability-refresh",
                                      {"reason": "A54 refresh while the secret provider fails"})
        failures["register"] = pa.post("/admin/v1/sources", {
            "source_id": unique("e2e-a54"), "display_name": "A54", "base_url": e2e_env.fake1c_url,
            "username_secret_ref": "FAKE1C_USERNAME", "password_secret_ref": "FAKE1C_PASSWORD",
            "tags": [], "reason": "A54 registration while the secret provider fails"})
    finally:
        env_file.write_bytes(original)
        fault("gateway", "restart")
        wait_healthy(e2e_env, "gateway")
    for name, resp in failures.items():
        _clean_failure(e2e_env, resp)
        assert "FAKE1C" not in resp.text, f"{name}: secret reference name leaked"
    assert evidence.count("sources") == before_sources, "a source was registered without secrets"
    audit = evidence.admin_events(failures["refresh"])
    assert audit and audit[0]["outcome"] == "error", "provider failure not audited"

    recovered_probe = expect(pa.post("/admin/v1/source-probes", {
        "base_url": e2e_env.fake1c_url, "username_secret_ref": "FAKE1C_USERNAME",
        "password_secret_ref": "FAKE1C_PASSWORD"}), 200, "A54 probe after recovery")
    assert recovered_probe.body["capabilities"]["metadata_fingerprint"]
    expect(pa.post(f"/admin/v1/sources/{world.source_id}/capability-refresh",
                   {"reason": "A54 refresh after recovery"}), 200, "A54 refresh after recovery")
