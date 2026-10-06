from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from starlette.applications import Starlette
from starlette.authentication import requires
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from business_ai_gateway.auth import JWTTokenVerifier
from business_ai_gateway.settings import Settings


def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key()
    return private, public


def jwk(public, kid: str) -> dict:
    result = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public))
    result.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return result


class JWKSState:
    def __init__(self):
        self.lock = threading.Lock()
        self.keys: list[dict] = []
        self.status = 200
        self.delay = 0.0
        self.requests = 0


@pytest.fixture
def mock_idp():
    state = JWKSState()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with state.lock:
                state.requests += 1
                body = json.dumps({"keys": state.keys}).encode()
                status, delay = state.status, state.delay
            if delay:
                time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if status == 200:
                self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}/jwks"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def verifier_for(mock_idp, *, timeout=0.5, ttl=300):
    return JWTTokenVerifier(
        Settings(
            oauth_enabled=True,
            oauth_issuer="http://127.0.0.1:8001/",
            oauth_audience="http://127.0.0.1:8000/mcp",
            oauth_jwks_url=mock_idp.url,
            oauth_required_scope="onec:read",
            oauth_jwks_timeout_seconds=timeout,
            oauth_jwks_cache_ttl_seconds=ttl,
        )
    )


def token(private, kid: str):
    now = int(time.time())
    claims = {
        "iss": "http://127.0.0.1:8001/",
        "aud": "http://127.0.0.1:8000/mcp",
        "sub": "synthetic-user",
        "iat": now,
        "exp": now + 60,
        "scope": "onec:read",
        "azp": "synthetic-mcp-client",
    }
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})


def set_keys(mock_idp, *keys):
    with mock_idp.lock:
        mock_idp.keys = list(keys)


def test_jwks_client_uses_configured_timeout_and_fails_closed(mock_idp):
    private, public = keypair()
    set_keys(mock_idp, jwk(public, "key-1"))
    with mock_idp.lock:
        mock_idp.delay = 0.3
    verifier = verifier_for(mock_idp, timeout=0.05)

    started = time.perf_counter()
    assert verifier._verify_sync(token(private, "key-1")) is None

    assert time.perf_counter() - started < 0.25


def test_jwks_cache_is_ttl_bounded_and_unknown_kid_refreshes_for_rotation(mock_idp):
    old_private, old_public = keypair()
    new_private, new_public = keypair()
    set_keys(mock_idp, jwk(old_public, "old-key"))
    verifier = verifier_for(mock_idp, ttl=1)

    assert verifier._verify_sync(token(old_private, "old-key")) is not None
    assert mock_idp.requests == 1

    # A newly introduced kid forces an immediate refresh despite a warm JWKS cache.
    set_keys(mock_idp, jwk(new_public, "new-key"))
    time.sleep(1.05)  # honor the bounded unknown-kid refresh cooldown
    assert verifier._verify_sync(token(new_private, "new-key")) is not None
    assert mock_idp.requests == 2  # cached-set miss, then one forced refresh

    # Once the bounded cache expires, an unavailable IdP does not fall back to a stale key set.
    with mock_idp.lock:
        mock_idp.status = 503
    time.sleep(1.05)
    assert verifier._verify_sync(token(old_private, "old-key")) is None
    assert mock_idp.requests == 3


def test_framework_bearer_auth_uses_local_mock_idp(mock_idp):
    private, public = keypair()
    set_keys(mock_idp, jwk(public, "framework-key"))
    verifier = verifier_for(mock_idp)

    @requires("onec:read")
    async def protected(request: Request):
        return JSONResponse({"subject": request.user.display_name})

    app = Starlette(
        routes=[Route("/protected", protected)],
        middleware=[Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier))],
    )

    with TestClient(app) as client:
        denied = client.get("/protected")
        accepted = client.get(
            "/protected", headers={"Authorization": f"Bearer {token(private, 'framework-key')}"}
        )

    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {"subject": "synthetic-mcp-client"}


def test_actual_jwks_http_outage_after_cache_expiry_returns_401_and_recovers(mock_idp):
    private, public = keypair()
    set_keys(mock_idp, jwk(public, "outage-key"))
    verifier = verifier_for(mock_idp, ttl=1)

    async def protected(_request):
        return JSONResponse({"status": "authorized"})

    inner = Starlette(routes=[Route("/protected", protected)])
    app = Starlette(routes=[Mount("/guard", app=RequireAuthMiddleware(inner, required_scopes=["onec:read"]))],
                    middleware=[Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier))])
    bearer = token(private, "outage-key")
    with TestClient(app) as client:
        assert client.get("/guard/protected", headers={"Authorization": f"Bearer {bearer}"}).status_code == 200
        with mock_idp.lock:
            mock_idp.status = 503
        time.sleep(1.05)  # actual TTL expiration; no stale key bypass
        denied = client.get("/guard/protected", headers={"Authorization": f"Bearer {bearer}"})
        assert denied.status_code == 401
        assert bearer not in denied.text and "outage-key" not in denied.text
        with mock_idp.lock:
            mock_idp.status = 200
        recovered = client.get("/guard/protected", headers={"Authorization": f"Bearer {bearer}"})
        assert recovered.status_code == 200 and recovered.json() == {"status": "authorized"}
    assert mock_idp.requests == 3
