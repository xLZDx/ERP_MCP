"""Test-only OpenID Connect provider for the disposable local E2E environment.

NOT an identity-provider product and never for production: users, groups and clients are
fixed by a generated config under ``.e2e/``. ERP_MCP itself never creates users; it only
binds subjects/groups (taken from tokens issued here) to roles and grants.

Implemented: discovery, JWKS, authorization-code flow (PKCE S256 mandatory, state mandatory,
nonce mandatory with ``openid``), RS256 access/ID tokens, refresh tokens (rotating), SSO
session cookie with ``prompt=login`` / ``max_age`` / ``acr_values`` re-authentication,
RP-initiated logout, userinfo, and a ``password`` grant on the headless client for test
automation (with test-only ``acr``, ``auth_age`` and ``ttl`` parameters).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
SESSION_COOKIE = "e2e_idp_session"
LOGIN_ATTEMPTS = 5


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class Client:
    client_id: str
    secret: str | None
    redirect_uris: tuple[str, ...]
    post_logout_redirect_uris: tuple[str, ...]
    audiences: tuple[str, ...]
    scopes: frozenset[str]
    grant_types: frozenset[str]


@dataclass(frozen=True)
class User:
    sub: str
    username: str
    password: str
    groups: tuple[str, ...]


class Provider:
    def __init__(self, config: dict):
        self.config = config
        self.issuer: str = config["issuer"].rstrip("/")
        self.realm_path = "/" + self.issuer.split("/", 3)[3]
        self.step_up_acr: str = config["step_up_acr"]
        self.basic_acr: str = config["basic_acr"]
        self.access_ttl = int(config.get("access_token_ttl", 3600))
        self.id_ttl = int(config.get("id_token_ttl", 3600))
        self.refresh_ttl = int(config.get("refresh_ttl", 1800))
        self.sso_ttl = int(config.get("sso_session_ttl", 28800))
        self.cookie_secret = config["cookie_secret"].encode()
        credentials = json.loads(Path(config["credentials_path"]).read_text(encoding="utf-8"))
        self.users = {
            name: User(name, name, data["password"], tuple(config["groups"].get(name, ())))
            for name, data in credentials["users"].items()
        }
        self.clients = {
            c["client_id"]: Client(
                c["client_id"], c.get("secret"), tuple(c["redirect_uris"]),
                tuple(c["post_logout_redirect_uris"]), tuple(c["audiences"]),
                frozenset(c["scopes"]), frozenset(c["grant_types"]),
            )
            for c in config["clients"]
        }
        self.key = self._load_key(Path(config["key_path"]))
        public = self.key.public_key()
        numbers = public.public_numbers()
        jwk = {"kty": "RSA", "n": _b64u(numbers.n.to_bytes(256, "big")),
               "e": _b64u(numbers.e.to_bytes(3, "big"))}
        canonical = json.dumps({k: jwk[k] for k in ("e", "kty", "n")}, separators=(",", ":"))
        self.kid = _b64u(hashlib.sha256(canonical.encode()).digest())
        self.jwk = {**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}
        self.pem = self.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        self.pending: dict[str, dict] = {}
        self.codes: dict[str, dict] = {}
        self.refresh: dict[str, dict] = {}
        self.revoked_sids: set[str] = set()

    @staticmethod
    def _load_key(path: Path):
        if path.exists():
            return serialization.load_pem_private_key(path.read_bytes(), password=None)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key

    @staticmethod
    def now() -> int:
        return int(time.time())

    def url(self, suffix: str) -> str:
        return f"{self.issuer}/{suffix}"

    # ---- tokens -----------------------------------------------------------------------
    def _sign(self, claims: dict, typ: str) -> str:
        return jwt.encode(claims, self.pem, algorithm="RS256",
                          headers={"kid": self.kid, "typ": typ})

    def _times(self, ttl: int) -> dict:
        now = self.now()
        exp = now + ttl
        issued = min(now, exp - 1)
        return {"iat": issued, "nbf": issued, "exp": exp}

    def access_token(self, user: User, client: Client, audience: str, scopes: list[str], *,
                     sid: str, auth_time: int, acr: str, ttl: int | None = None) -> str:
        claims = {
            "iss": self.issuer, "sub": user.sub, "aud": audience,
            **self._times(self.access_ttl if ttl is None else ttl),
            "jti": str(uuid.uuid4()), "scope": " ".join(scopes), "client_id": client.client_id,
            "azp": client.client_id, "sid": sid, "auth_time": auth_time, "acr": acr,
            "groups": list(user.groups), "preferred_username": user.username,
        }
        return self._sign(claims, "at+jwt")

    def id_token(self, user: User, client: Client, *, nonce: str | None, sid: str,
                 auth_time: int, acr: str, access_token: str) -> str:
        digest = hashlib.sha256(access_token.encode()).digest()
        claims = {
            "iss": self.issuer, "sub": user.sub, "aud": client.client_id,
            **self._times(self.id_ttl), "auth_time": auth_time, "acr": acr, "sid": sid,
            "azp": client.client_id, "groups": list(user.groups),
            "preferred_username": user.username, "at_hash": _b64u(digest[:16]),
        }
        if nonce:
            claims["nonce"] = nonce
        return self._sign(claims, "JWT")

    # ---- SSO session cookie (stateless, HMAC-signed) ----------------------------------
    def make_session(self, sub: str, sid: str, auth_time: int, acr: str) -> str:
        body = _b64u(json.dumps({"sub": sub, "sid": sid, "auth_time": auth_time, "acr": acr,
                                 "exp": self.now() + self.sso_ttl}).encode())
        mac = hmac.new(self.cookie_secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{mac}"

    def read_session(self, request: Request) -> dict | None:
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw or "." not in raw:
            return None
        body, _, mac = raw.partition(".")
        expected = hmac.new(self.cookie_secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except ValueError:
            return None
        if data.get("exp", 0) <= self.now() or data.get("sid") in self.revoked_sids:
            return None
        if data.get("sub") not in self.users:
            return None
        return data


def _form(body: bytes) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace"),
                                          keep_blank_values=True).items()}


def _json(payload: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status,
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return _json({"error": error, "error_description": description}, status)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    text = (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title></head><body><main><h1>{html.escape(title)}</h1>"
            f"{body}</main></body></html>")
    return HTMLResponse(text, status_code=status,
                        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


def create_app(config: dict) -> Starlette:
    p = Provider(config)

    def redirect_error(pending: dict, error: str, description: str) -> RedirectResponse:
        query = urlencode({"error": error, "error_description": description,
                           "state": pending["state"], "iss": p.issuer})
        return RedirectResponse(f"{pending['redirect_uri']}?{query}", status_code=302)

    def finish(pending: dict, session: dict) -> RedirectResponse:
        code = secrets.token_urlsafe(32)
        p.codes[code] = {**pending, "sub": session["sub"], "sid": session["sid"],
                         "auth_time": session["auth_time"], "acr": session["acr"],
                         "exp": p.now() + 60}
        query = urlencode({"code": code, "state": pending["state"], "iss": p.issuer})
        return RedirectResponse(f"{pending['redirect_uri']}?{query}", status_code=302)

    def login_form(req: str, pending: dict, error: str | None = None, status: int = 200):
        notice = ""
        if p.step_up_acr in pending["acr_values"]:
            notice = "<p>Step-up re-authentication is required for this action.</p>"
        if error:
            notice += f"<p role=\"alert\">{html.escape(error)}</p>"
        body = (
            f"{notice}<form method=\"post\" action=\"{p.realm_path}/protocol/openid-connect/login\">"
            f"<input type=\"hidden\" name=\"req\" value=\"{html.escape(req)}\">"
            "<label for=\"username\">Username</label>"
            "<input id=\"username\" name=\"username\" autocomplete=\"username\" required>"
            "<label for=\"password\">Password</label>"
            "<input id=\"password\" name=\"password\" type=\"password\" "
            "autocomplete=\"current-password\" required>"
            "<button id=\"login-submit\" type=\"submit\">Sign in</button></form>"
            "<p>Test identity provider - local E2E only.</p>")
        return _page("Sign in (ERP_MCP test IdP)", body, status)

    async def discovery(_: Request):
        return JSONResponse({
            "issuer": p.issuer,
            "authorization_endpoint": p.url("protocol/openid-connect/auth"),
            "token_endpoint": p.url("protocol/openid-connect/token"),
            "userinfo_endpoint": p.url("protocol/openid-connect/userinfo"),
            "jwks_uri": p.url("protocol/openid-connect/certs"),
            "end_session_endpoint": p.url("protocol/openid-connect/logout"),
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token", "password"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "onec:read", "erp_mcp:admin"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic",
                                                      "none"],
            "code_challenge_methods_supported": ["S256"],
            "acr_values_supported": [p.basic_acr, p.step_up_acr],
            "claims_supported": ["sub", "iss", "aud", "exp", "iat", "auth_time", "acr", "groups",
                                 "preferred_username", "nonce", "sid", "azp"],
            "authorization_response_iss_parameter_supported": True,
        })

    async def jwks(_: Request):
        return JSONResponse({"keys": [p.jwk]})

    async def health(_: Request):
        return JSONResponse({"status": "ok", "issuer": p.issuer, "kid": p.kid})

    async def authorize(request: Request):
        q = request.query_params
        client = p.clients.get(q.get("client_id", ""))
        if client is None or "authorization_code" not in client.grant_types:
            return _page("Invalid request", "<p>Unknown client.</p>", 400)
        redirect_uri = q.get("redirect_uri", "")
        if redirect_uri not in client.redirect_uris:
            return _page("Invalid request", "<p>redirect_uri is not registered.</p>", 400)
        state = q.get("state", "")
        pending = {"client_id": client.client_id, "redirect_uri": redirect_uri,
                   "state": state, "acr_values": (q.get("acr_values") or "").split(),
                   "attempts": 0, "exp": p.now() + 600}
        if q.get("response_type") != "code":
            return redirect_error(pending, "unsupported_response_type", "only code is supported")
        if not state:
            return redirect_error({**pending, "state": ""}, "invalid_request", "state is required")
        challenge = q.get("code_challenge", "")
        if q.get("code_challenge_method") != "S256" or not _CHALLENGE.fullmatch(challenge):
            return redirect_error(pending, "invalid_request", "PKCE with S256 is required")
        scopes = (q.get("scope") or "").split()
        if not scopes or any(s not in client.scopes for s in scopes):
            return redirect_error(pending, "invalid_scope", "scope not permitted for this client")
        nonce = q.get("nonce") or None
        if "openid" in scopes and not nonce:
            return redirect_error(pending, "invalid_request", "nonce is required with openid")
        resources = q.getlist("resource")
        if len(resources) > 1 or (resources and resources[0] not in client.audiences):
            return redirect_error(pending, "invalid_target", "resource not permitted")
        max_age = q.get("max_age")
        if max_age is not None and (not max_age.isdigit()):
            return redirect_error(pending, "invalid_request", "max_age must be a non-negative integer")
        prompt = (q.get("prompt") or "").split()
        pending.update(challenge=challenge, scopes=scopes, nonce=nonce,
                       audience=resources[0] if resources else client.audiences[0])
        session = p.read_session(request)
        needs_login = session is None
        if session is not None:
            age = p.now() - int(session["auth_time"])
            if "login" in prompt or (max_age is not None and (int(max_age) == 0
                                                              or age > int(max_age))):
                needs_login = True
            if p.step_up_acr in pending["acr_values"] and session["acr"] != p.step_up_acr:
                needs_login = True
        if "none" in prompt and needs_login:
            return redirect_error(pending, "login_required", "authentication is required")
        if not needs_login:
            return finish(pending, session)
        req = secrets.token_urlsafe(24)
        p.pending[req] = pending
        return login_form(req, pending)

    async def login(request: Request):
        form = _form(await request.body())
        req = form.get("req", "")
        pending = p.pending.get(req)
        if pending is None or pending["exp"] <= p.now():
            p.pending.pop(req, None)
            return _page("Session expired", "<p>Restart the sign-in from the application.</p>", 400)
        user = p.users.get(form.get("username", ""))
        supplied = form.get("password", "").encode()
        expected = (user.password if user else secrets.token_hex(8)).encode()
        if user is None or not hmac.compare_digest(supplied, expected):
            pending["attempts"] += 1
            if pending["attempts"] >= LOGIN_ATTEMPTS:
                del p.pending[req]
                return redirect_error(pending, "access_denied", "too many failed attempts")
            return login_form(req, pending, "Invalid username or password.", 401)
        del p.pending[req]
        acr = p.step_up_acr if p.step_up_acr in pending["acr_values"] else p.basic_acr
        session = {"sub": user.sub, "sid": str(uuid.uuid4()), "auth_time": p.now(), "acr": acr}
        response = finish(pending, session)
        response.set_cookie(SESSION_COOKIE, p.make_session(**session), httponly=True,
                            samesite="lax", path=p.realm_path, max_age=p.sso_ttl)
        return response

    def authenticate_client(request: Request, form: dict) -> Client | JSONResponse:
        header = request.headers.get("authorization", "")
        client_id, secret = form.get("client_id", ""), form.get("client_secret")
        if header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode()
                client_id, _, secret = decoded.partition(":")
            except ValueError:
                return _oauth_error("invalid_client", "malformed basic credentials", 401)
        client = p.clients.get(client_id)
        if client is None:
            return _oauth_error("invalid_client", "unknown client", 401)
        if client.secret is not None and not (
                secret and hmac.compare_digest(secret.encode(), client.secret.encode())):
            return _oauth_error("invalid_client", "client authentication failed", 401)
        return client

    def issue(user: User, client: Client, *, audience: str, scopes: list[str], sid: str,
              auth_time: int, acr: str, nonce: str | None, ttl: int | None = None,
              with_refresh: bool = True) -> JSONResponse:
        access = p.access_token(user, client, audience, scopes, sid=sid, auth_time=auth_time,
                                acr=acr, ttl=ttl)
        body = {"access_token": access, "token_type": "Bearer", "scope": " ".join(scopes),
                "expires_in": p.access_ttl if ttl is None else ttl}
        if "openid" in scopes:
            body["id_token"] = p.id_token(user, client, nonce=nonce, sid=sid,
                                          auth_time=auth_time, acr=acr, access_token=access)
        if with_refresh and "refresh_token" in client.grant_types:
            token = secrets.token_urlsafe(40)
            p.refresh[token] = {"client_id": client.client_id, "sub": user.sub, "sid": sid,
                                "scopes": scopes, "audience": audience, "auth_time": auth_time,
                                "acr": acr, "nonce": nonce, "exp": p.now() + p.refresh_ttl}
            body["refresh_token"] = token
            body["refresh_expires_in"] = p.refresh_ttl
        return _json(body)

    async def token(request: Request):
        form = _form(await request.body())
        client = authenticate_client(request, form)
        if isinstance(client, JSONResponse):
            return client
        grant = form.get("grant_type", "")
        if grant not in client.grant_types:
            return _oauth_error("unauthorized_client", "grant type not allowed for client")
        if grant == "authorization_code":
            record = p.codes.pop(form.get("code", ""), None)
            if (record is None or record["exp"] <= p.now()
                    or record["client_id"] != client.client_id
                    or record["redirect_uri"] != form.get("redirect_uri")):
                return _oauth_error("invalid_grant", "authorization code is invalid or expired")
            verifier = form.get("code_verifier", "")
            if not verifier:
                return _oauth_error("invalid_request", "code_verifier is required")
            computed = _b64u(hashlib.sha256(verifier.encode("ascii", "replace")).digest())
            if not hmac.compare_digest(computed, record["challenge"]):
                return _oauth_error("invalid_grant", "PKCE verification failed")
            user = p.users[record["sub"]]
            return issue(user, client, audience=record["audience"], scopes=record["scopes"],
                         sid=record["sid"], auth_time=record["auth_time"], acr=record["acr"],
                         nonce=record["nonce"])
        if grant == "refresh_token":
            record = p.refresh.pop(form.get("refresh_token", ""), None)
            if (record is None or record["exp"] <= p.now()
                    or record["client_id"] != client.client_id
                    or record["sid"] in p.revoked_sids):
                return _oauth_error("invalid_grant", "refresh token is invalid or expired")
            requested = (form.get("scope") or "").split() or record["scopes"]
            if any(s not in record["scopes"] for s in requested):
                return _oauth_error("invalid_scope", "cannot widen scope on refresh")
            return issue(p.users[record["sub"]], client, audience=record["audience"],
                         scopes=requested, sid=record["sid"], auth_time=record["auth_time"],
                         acr=record["acr"], nonce=record["nonce"])
        # password grant: headless test automation only
        user = p.users.get(form.get("username", ""))
        supplied = form.get("password", "").encode()
        expected = (user.password if user else secrets.token_hex(8)).encode()
        if user is None or not hmac.compare_digest(supplied, expected):
            return _oauth_error("invalid_grant", "invalid user credentials")
        scopes = (form.get("scope") or "").split()
        if not scopes or any(s not in client.scopes for s in scopes):
            return _oauth_error("invalid_scope", "scope not permitted for this client")
        audience = form.get("audience") or form.get("resource") or client.audiences[0]
        if audience not in client.audiences:
            return _oauth_error("invalid_target", "audience not permitted")
        acr = form.get("acr") or p.basic_acr
        try:
            auth_age = int(form.get("auth_age", "0"))
            ttl = int(form["ttl"]) if "ttl" in form else None
        except ValueError:
            return _oauth_error("invalid_request", "auth_age and ttl must be integers")
        return issue(user, client, audience=audience, scopes=scopes, sid=str(uuid.uuid4()),
                     auth_time=p.now() - auth_age, acr=acr, nonce=None, ttl=ttl,
                     with_refresh=False)

    async def userinfo(request: Request):
        bearer = request.headers.get("authorization", "")
        try:
            claims = jwt.decode(bearer[7:], p.key.public_key(), algorithms=["RS256"],
                                issuer=p.issuer, options={"verify_aud": False})
        except jwt.PyJWTError:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        return JSONResponse({k: claims[k] for k in ("sub", "groups", "preferred_username")})

    async def logout(request: Request):
        params = dict(request.query_params)
        if request.method == "POST":
            params.update(_form(await request.body()))
        session = p.read_session(request)
        target = None
        hint = params.get("id_token_hint")
        if hint:
            try:
                claims = jwt.decode(hint, p.key.public_key(), algorithms=["RS256"],
                                    issuer=p.issuer, options={"verify_aud": False,
                                                              "verify_exp": False})
            except jwt.PyJWTError:
                return _page("Invalid request", "<p>Invalid id_token_hint.</p>", 400)
            if claims.get("sid"):
                p.revoked_sids.add(claims["sid"])
            client = p.clients.get(str(claims.get("azp")))
            uri = params.get("post_logout_redirect_uri")
            if uri and client and uri in client.post_logout_redirect_uris:
                target = uri + (("?" + urlencode({"state": params["state"]}))
                                if params.get("state") else "")
        if session:
            p.revoked_sids.add(session["sid"])
        for token_value, record in list(p.refresh.items()):
            if record["sid"] in p.revoked_sids:
                del p.refresh[token_value]
        response: Response = (RedirectResponse(target, status_code=302) if target
                              else _page("Signed out", "<p>You have been signed out.</p>"))
        response.delete_cookie(SESSION_COOKIE, path=p.realm_path)
        return response

    async def callback_echo(request: Request):
        code = html.escape(request.query_params.get("code", ""))
        error = html.escape(request.query_params.get("error", ""))
        return _page("Callback received", f"<p id=\"code\">{code}</p><p id=\"error\">{error}</p>")

    realm = p.realm_path
    oidc = f"{realm}/protocol/openid-connect"
    return Starlette(routes=[
        Route("/healthz", health, methods=["GET"]),
        Route(f"{realm}/.well-known/openid-configuration", discovery, methods=["GET"]),
        Route(f"{realm}/.well-known/oauth-authorization-server", discovery, methods=["GET"]),
        Route(f"/.well-known/oauth-authorization-server{realm}", discovery, methods=["GET"]),
        Route(f"/.well-known/openid-configuration{realm}", discovery, methods=["GET"]),
        Route(f"{oidc}/certs", jwks, methods=["GET"]),
        Route(f"{oidc}/auth", authorize, methods=["GET"]),
        Route(f"{oidc}/login", login, methods=["POST"]),
        Route(f"{oidc}/token", token, methods=["POST"]),
        Route(f"{oidc}/userinfo", userinfo, methods=["GET"]),
        Route(f"{oidc}/logout", logout, methods=["GET", "POST"]),
        Route("/e2e/callback", callback_echo, methods=["GET"]),
    ])


def app_from_env() -> Starlette:
    path = os.environ.get("E2E_IDP_CONFIG")
    if not path:
        raise RuntimeError("E2E_IDP_CONFIG must point to the generated .e2e/idp-config.json")
    return create_app(json.loads(Path(path).read_text(encoding="utf-8")))
