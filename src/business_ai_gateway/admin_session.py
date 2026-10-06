from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from .auth import JWTTokenVerifier
from .rate_limit import RateLimiter, RateLimitExceeded
from .settings import Settings


def _token_urlsafe(size: int = 32) -> str:
    return secrets.token_urlsafe(size)


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class AdminSession:
    session_id: str
    access_token: str
    csrf_token: str


class AdminSessionManager:
    LOGIN_TTL_SECONDS = 600
    IDLE_TTL_SECONDS = 1800
    SESSION_COOKIE = "erp_mcp_admin_session"
    LOGIN_COOKIE = "erp_mcp_admin_login"

    def __init__(
        self,
        settings: Settings,
        redis,
        verifier: JWTTokenVerifier,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings
        self.redis = redis
        self.verifier = verifier
        self.transport = transport
        self.login_limiter = RateLimiter(redis, per_minute=10)
        # Optional async callable(event, subject, client_id, request) used for audit evidence.
        self.audit_hook = None

    async def _audit(self, event: str, subject: str, client_id: str | None, request: Request):
        if self.audit_hook is None:
            return
        try:
            await self.audit_hook(event, subject, client_id or "unknown", request)
        except Exception:  # noqa: BLE001 - audit write must not break login/logout flow
            logging.getLogger("uvicorn.error").warning("admin session audit write failed event=%s", event)

    @property
    def secure_cookie(self) -> bool:
        return self.settings.environment == "production"

    def _login_key(self, state: str) -> str:
        return f"erp_mcp:admin:login:{state}"

    def _session_key(self, session_id: str) -> str:
        return f"erp_mcp:admin:session:{session_id}"

    async def login(self, request: Request):
        try:
            await self.login_limiter.check(
                subject=request.client.host if request.client else "unknown",
                source_id="__admin_login__", tool="login",
            )
        except RateLimitExceeded:
            return JSONResponse({"error": "RATE_LIMITED"}, status_code=429)
        except Exception:  # noqa: BLE001 - fail closed without Redis
            return JSONResponse({"error": "ADMIN_DEPENDENCY_UNAVAILABLE"}, status_code=503)
        state = _token_urlsafe()
        nonce = _token_urlsafe()
        verifier = _token_urlsafe(48)
        record = {
            "nonce": nonce,
            "verifier": verifier,
            "created_at": int(time.time()),
            "previous_session_id": request.cookies.get(self.SESSION_COOKIE),
        }
        await self.redis.setex(
            self._login_key(state),
            self.LOGIN_TTL_SECONDS,
            json.dumps(record),
        )
        parameters = {
                "response_type": "code",
                "client_id": self.settings.admin_oidc_client_id,
                "redirect_uri": self.settings.admin_oidc_redirect_uri,
                "scope": f"openid profile {self.settings.admin_oauth_required_scope}",
                "state": state,
                "nonce": nonce,
                "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
            }
        if request.query_params.get("step_up") == "1" and self.settings.admin_step_up_acr_values.strip():
            parameters.update(acr_values=" ".join(
                value.strip() for value in self.settings.admin_step_up_acr_values.split(",") if value.strip()
            ), max_age="0", prompt="login")
        query = urlencode(parameters)
        response = RedirectResponse(
            f"{self.settings.admin_oidc_authorization_url}?{query}",
            status_code=302,
        )
        response.set_cookie(
            self.LOGIN_COOKIE,
            state,
            max_age=self.LOGIN_TTL_SECONDS,
            secure=self.secure_cookie,
            httponly=True,
            samesite="lax",
            path="/admin",
        )
        return response

    async def _verify_id_token(self, raw_token: str, *, nonce: str) -> dict:
        try:
            signing_key = (await asyncio.to_thread(
                self.verifier._jwks.get_signing_key_from_jwt, raw_token
            )).key
            claims = jwt.decode(
                raw_token,
                signing_key,
                algorithms=self.settings.oauth_algorithm_list,
                issuer=self.settings.oauth_issuer,
                audience=self.settings.admin_oidc_client_id,
                options={
                    "require": ["exp", "iat", "iss", "sub", "aud", "nonce"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except jwt.PyJWTError as exc:
            raise PermissionError("invalid OIDC id_token") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")).encode(), nonce.encode()):
            raise PermissionError("OIDC nonce mismatch")
        if (isinstance(claims.get("aud"), list) and len(claims["aud"]) > 1
                and claims.get("azp") != self.settings.admin_oidc_client_id):
            raise PermissionError("OIDC authorized party mismatch")
        return claims

    async def callback(self, request: Request):
        error = request.query_params.get("error")
        if error:
            return JSONResponse({"error": "OIDC_LOGIN_FAILED"}, status_code=401)
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        cookie_state = request.cookies.get(self.LOGIN_COOKIE)
        if not code or not state or not cookie_state:
            return JSONResponse({"error": "OIDC_STATE_INVALID"}, status_code=400)
        if not secrets.compare_digest(state.encode(), cookie_state.encode()):
            return JSONResponse({"error": "OIDC_STATE_INVALID"}, status_code=400)

        key = self._login_key(state)
        raw = await self.redis.getdel(key)
        if not raw:
            return JSONResponse({"error": "OIDC_STATE_EXPIRED"}, status_code=400)
        record = json.loads(raw)
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.admin_oidc_redirect_uri,
            "client_id": self.settings.admin_oidc_client_id,
            "code_verifier": record["verifier"],
        }
        if self.settings.admin_oidc_client_secret:
            form["client_secret"] = (
                self.settings.admin_oidc_client_secret.get_secret_value()
            )

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client, client.stream(
                "POST", self.settings.admin_oidc_token_url, data=form,
                headers={"Accept-Encoding": "identity"},
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("encoded token response is unsupported")
                raw_response = bytearray()
                async for chunk in response.aiter_bytes():
                    raw_response.extend(chunk)
                    if len(raw_response) > 256_000:
                        raise ValueError("token response exceeds limit")
                token_response = json.loads(raw_response)
            if not isinstance(token_response, dict):
                raise TypeError("invalid token response")
        except (httpx.HTTPError, ValueError, TypeError):
            return JSONResponse({"error": "OIDC_TOKEN_EXCHANGE_FAILED"}, status_code=502)

        access_token = token_response.get("access_token")
        id_token = token_response.get("id_token")
        if not isinstance(access_token, str) or not isinstance(id_token, str):
            return JSONResponse({"error": "OIDC_TOKEN_INVALID"}, status_code=401)

        verified = await self.verifier.verify_token(access_token)
        if verified is None:
            return JSONResponse({"error": "OIDC_TOKEN_INVALID"}, status_code=401)
        try:
            id_claims = await self._verify_id_token(id_token, nonce=record["nonce"])
        except PermissionError:
            return JSONResponse({"error": "OIDC_TOKEN_INVALID"}, status_code=401)
        if id_claims.get("sub") != verified.subject:
            return JSONResponse({"error": "OIDC_SUBJECT_MISMATCH"}, status_code=401)

        session_id = _token_urlsafe(40)
        csrf_token = _token_urlsafe(32)
        now = int(time.time())
        access_expires_at = int(verified.expires_at)
        if access_expires_at <= now:
            return JSONResponse({"error": "OIDC_TOKEN_INVALID"}, status_code=401)
        absolute_expires_at = min(
            now + self.settings.admin_session_ttl_seconds,
            access_expires_at,
        )
        session = {
            "access_token": access_token,
            "csrf_token": csrf_token,
            "subject": verified.subject,
            "client_id": verified.client_id,
            "last_seen": now,
            "absolute_expires_at": absolute_expires_at,
        }
        await self.redis.setex(
            self._session_key(session_id),
            min(self.IDLE_TTL_SECONDS, absolute_expires_at - now),
            json.dumps(session),
        )
        await self._audit("session.login", verified.subject or "", verified.client_id, request)

        redirect = RedirectResponse("/admin/", status_code=302)
        old_session = record.get("previous_session_id") or request.cookies.get(self.SESSION_COOKIE)
        if old_session:
            await self.redis.delete(self._session_key(old_session))
        redirect.delete_cookie(self.LOGIN_COOKIE, path="/admin")
        redirect.set_cookie(
            self.SESSION_COOKIE,
            session_id,
            max_age=max(1, absolute_expires_at - now),
            secure=self.secure_cookie,
            httponly=True,
            samesite="strict",
            path="/admin",
        )
        return redirect

    async def resolve(self, request: Request) -> AdminSession | None:
        session_id = request.cookies.get(self.SESSION_COOKIE)
        if not session_id:
            return None
        raw = await self.redis.get(self._session_key(session_id))
        if not raw:
            return None
        try:
            record = json.loads(raw)
            now = int(time.time())
            absolute = int(record["absolute_expires_at"])
            last_seen = int(record["last_seen"])
            if now >= absolute or now - last_seen >= self.IDLE_TTL_SECONDS:
                await self.redis.delete(self._session_key(session_id))
                return None
            access_token = str(record["access_token"])
            csrf_token = str(record["csrf_token"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await self.redis.delete(self._session_key(session_id))
            return None

        record["last_seen"] = now
        remaining = max(1, absolute - now)
        # Compare-and-refresh cannot recreate a session deleted by a concurrent logout.
        refreshed = await self.redis.eval(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
            "redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3]); return 1 "
            "else return redis.call('EXISTS', KEYS[1]) end",
            1, self._session_key(session_id), raw, json.dumps(record),
            min(self.IDLE_TTL_SECONDS, remaining),
        )
        if not refreshed:
            return None
        return AdminSession(
            session_id=session_id,
            access_token=access_token,
            csrf_token=csrf_token,
        )

    async def logout(self, request: Request):
        session_id = request.cookies.get(self.SESSION_COOKIE)
        if session_id:
            raw = await self.redis.get(self._session_key(session_id))
            await self.redis.delete(self._session_key(session_id))
            if raw:
                try:
                    record = json.loads(raw)
                    subject = str(record.get("subject") or "")
                    client_id = record.get("client_id")
                except (TypeError, ValueError, AttributeError):
                    subject, client_id = "", None
                if subject:
                    await self._audit("session.logout", subject, client_id, request)
        response = RedirectResponse("/admin/", status_code=302)
        response.delete_cookie(self.SESSION_COOKIE, path="/admin")
        return response
