"""Inert, server-rendered approver application for the isolated S16 slice."""
from __future__ import annotations

import hashlib
import html
import inspect
import json
import re
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from business_ai_gateway.phase2.change.errors import ErrorCode, render

from .contracts import ApproverSession, AuthenticatedPrincipal, DecisionPage, PrincipalRole, Result

__all__ = ["create_approval_app", "SESSION_COOKIE_NAME"]

SESSION_COOKIE_NAME = "__Secure-s16_approval"
SESSION_COOKIE_ATTRIBUTES = "Path=/approval; Secure; HttpOnly; SameSite=Strict"
_MAX_FORM_BYTES = 8192
_TICKET_RE = re.compile(r"[A-Za-z0-9_-]{16,512}\Z")
_CSP = ("default-src 'none'; script-src 'none'; style-src 'self'; img-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
_STYLESHEET = b"""html{color-scheme:light}body{margin:0;background:#fff;color:#111;font:1rem/1.55 system-ui,sans-serif}main{max-width:72ch;margin:0 auto;padding:1rem}h1,h2{line-height:1.2}pre{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;border:1px solid #555;padding:.75rem}dl{display:grid;grid-template-columns:minmax(8rem,1fr) 2fr;gap:.25rem 1rem}dt{font-weight:700}dd{margin:0;overflow-wrap:anywhere}button,input{font:inherit;min-height:44px;max-width:100%}button{margin:.5rem .5rem .5rem 0;padding:.5rem 1rem}input{width:100%;padding:.5rem;border:1px solid #333}button:focus-visible,input:focus-visible,a:focus-visible{outline:3px solid #174ea6;outline-offset:2px}code{overflow-wrap:anywhere}form{margin-top:1.5rem}@media(max-width:36rem){dl{grid-template-columns:1fr;gap:0}dd{margin-bottom:.75rem}main{padding:.75rem}}"""


class ApprovalServicePort(Protocol):
    def open_preview(self, approver: AuthenticatedPrincipal, session: ApproverSession,
                     ticket: str, *, now: datetime | None = None) -> Result[DecisionPage, ErrorCode]: ...
    def submit_decision(self, approver: AuthenticatedPrincipal, session: ApproverSession,
                        decision_ref: str, decision: str, *, confirmation_text: str,
                        origin: str, referer: str,
                        now: datetime | None = None) -> Result[Any, ErrorCode]: ...


class ApproverSessionAuthenticator(Protocol):
    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> ApproverSession | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


def _safe_text(value: object, *, limit: int = 4096) -> str:
    if type(value) not in (str, int, float, bool) or len(str(value)) > limit:
        return "Unavailable"
    return html.escape(str(value), quote=True)


def _canonical_object(raw: bytes, digest: str) -> tuple[str, dict[str, Any]] | None:
    if type(raw) is not bytes or len(raw) > 1_048_576:
        return None
    if hashlib.sha256(raw).hexdigest() != digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None
    try:
        text = raw.decode("utf-8", errors="strict")
        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate")
                result[key] = value
            return result
        value = json.loads(text, object_pairs_hook=reject_duplicates,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
        if type(value) is not dict:
            return None
        canonical = json.dumps(value, ensure_ascii=True, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
        if canonical.encode("utf-8") != raw:
            return None
        return text, value
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return None


def _page(title: str, body: str, status: int = 200, *, extra_headers: list[tuple[bytes, bytes]] | None = None
          ) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    document = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                "<link rel=\"stylesheet\" href=\"/approval/s16.css\">"
                f"<title>{html.escape(title)}</title></head><body><main><h1 tabindex=\"-1\">"
                f"{html.escape(title)}</h1>{body}</main></body></html>").encode("utf-8")
    headers = [
        (b"content-type", b"text/html; charset=utf-8"),
        (b"content-length", str(len(document)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"referrer-policy", b"no-referrer"),
        (b"content-security-policy", _CSP.encode("ascii")),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    ]
    headers.extend(extra_headers or [])
    return status, headers, document


def _error(code: ErrorCode, status: int = 403) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    info = render(code)
    body = ("<section aria-labelledby=\"error-title\"><h2 id=\"error-title\" tabindex=\"-1\">"
            "Review unavailable</h2><p role=\"alert\">" + html.escape(info.message) +
            "</p><p>Next step: " + html.escape(info.next_action.value.replace("_", " ").lower()) +
            ".</p></section>")
    return _page("Review unavailable", body, status)


async def _invoke(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    value = function(*args, **kwargs)
    return await value if inspect.isawaitable(value) else value


def _live_session(session: object, now: datetime) -> bool:
    try:
        return (type(session) is ApproverSession
                and type(session.principal) is AuthenticatedPrincipal
                and session.principal.token_class.value == "APPROVER_SESSION"
                and PrincipalRole.APPROVER in session.principal.roles
                and session.principal.session_id == session.session_id
                and now.tzinfo is not None and now.utcoffset() is not None
                and session.idle_expires_at.tzinfo is not None
                and session.expires_at.tzinfo is not None
                and now < session.idle_expires_at and now < session.expires_at)
    except (AttributeError, TypeError, ValueError):
        return False


def _origin_matches(origin: str, referer: str, expected: str) -> bool:
    try:
        wanted = urlsplit(expected)
        origin_parts = urlsplit(origin)
        ref_parts = urlsplit(referer)
        if (wanted.scheme not in {"https", "http"} or not wanted.netloc or wanted.path
                or wanted.query or wanted.fragment or wanted.username or wanted.password):
            return False
        if origin != f"{wanted.scheme}://{wanted.netloc}" or origin_parts.netloc != wanted.netloc:
            return False
        if (ref_parts.scheme != wanted.scheme or ref_parts.netloc != wanted.netloc
                or ref_parts.username or ref_parts.password or ref_parts.fragment):
            return False
        return ref_parts.path.startswith("/approval/")
    except (ValueError, TypeError):
        return False


def _render_preview(page: DecisionPage) -> tuple[str, dict[str, Any]] | None:
    verified = _canonical_object(page.canonical_preview_bytes, page.preview_digest)
    if verified is None:
        return None
    preview_text, payload = verified
    # Scope and other summaries are read from the verified service bytes, never request input.
    entries = []
    for key, label in (("change_id", "Change reference"), ("kind", "Change type"),
                       ("requester_person_id", "Requester"), ("target_version", "Target version"),
                       ("reason", "Reason"), ("expires_at", "Expires")):
        if key in payload:
            entries.append(f"<dt>{label}</dt><dd>{_safe_text(payload[key])}</dd>")
    scope = payload.get("scope")
    if type(scope) is dict:
        for key, label in (("tenant", "Tenant"), ("company", "Company"),
                           ("organization", "Organization"), ("base_fingerprint", "Target fingerprint"),
                           ("target_class", "Target class")):
            if key in scope:
                entries.append(f"<dt>{label}</dt><dd>{_safe_text(scope[key])}</dd>")
    dl = "<dl>" + "".join(entries) + "</dl>" if entries else ""
    return ("<p><strong>Preview only — no change has been applied.</strong></p>" + dl +
            "<section aria-labelledby=\"canonical-preview\"><h2 id=\"canonical-preview\">"
            "Canonical preview</h2><p>SHA-256 preview digest: <code>" +
            html.escape(page.preview_digest) + "</code></p><pre>" + html.escape(preview_text) +
            "</pre></section>"), payload


def _current_context(page: DecisionPage, session: ApproverSession) -> str | None:
    """Validate and render authoritative service metadata outside immutable preview bytes."""
    lifecycle = page.lifecycle_status
    authorization = page.authorization_status
    label = page.approver_person_label
    created = page.created_at
    version = page.snapshot_version
    if (type(lifecycle) is not str or not lifecycle or len(lifecycle) > 64
            or type(authorization) is not str or not authorization or len(authorization) > 64
            or type(label) is not str or not label.strip() or len(label) > 256
            or any(ord(char) < 32 for char in label)
            or label in {session.session_id, session.principal.principal_id, session.principal.person_id}
            or type(created) is not datetime or created.tzinfo is None or created.utcoffset() is None
            or type(version) is not int or version < 1 or type(page.decision_allowed) is not bool):
        return None
    created_text = created.isoformat()
    return ("<section aria-labelledby=\"current-record-heading\"><h2 id=\"current-record-heading\">"
            "Current record status</h2><dl>"
            "<dt>Lifecycle status</dt><dd>" + _safe_text(lifecycle) + "</dd>"
            "<dt>Authorization status</dt><dd>" + _safe_text(authorization) + "</dd>"
            "<dt>Version</dt><dd>" + str(version) + "</dd>"
            "<dt>Proposal created</dt><dd><time datetime=\"" + html.escape(created_text, quote=True) + "\">"
            + html.escape(created_text) + "</time></dd>"
            "<dt>Current approver</dt><dd>" + _safe_text(label) + "</dd>"
            "</dl></section>")


def create_approval_app(service: ApprovalServicePort,
                        authenticator: ApproverSessionAuthenticator, *, origin: str,
                        clock: Clock) -> Callable[..., Any]:
    """Return an inert ASGI app. No socket or gateway route is created here."""
    expected = urlsplit(origin)
    if (expected.scheme != "https" or not expected.netloc or expected.path
            or expected.query or expected.fragment or expected.username or expected.password):
        raise ValueError("APPROVAL_ORIGIN_INVALID")

    async def app(scope: Mapping[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if scope.get("type") != "http":
            return
        method = scope.get("method")
        path = scope.get("path")
        raw_headers = scope.get("headers", ())
        header_lists: dict[str, list[str]] = {}
        try:
            for key, value in raw_headers:
                name = key.decode("latin-1").casefold()
                header_lists.setdefault(name, []).append(value.decode("latin-1"))
        except (AttributeError, UnicodeError, ValueError):
            response = _error(ErrorCode.SCHEMA_INVALID, 400)
        else:
            headers = {key: values[0] for key, values in header_lists.items() if len(values) == 1}
            if any(len(values) != 1 for values in header_lists.values()):
                response = _error(ErrorCode.SCHEMA_INVALID, 400)
            elif type(path) is str and path == "/approval/s16.css" and method == "GET":
                try:
                    style_session = await _invoke(authenticator.authenticate, scope, headers)
                    style_now = clock.now()
                except Exception:
                    style_session = None
                    style_now = datetime.min
                if not _live_session(style_session, style_now):
                    response = _error(ErrorCode.NOT_ENTITLED, 401)
                else:
                    response = (200, [(b"content-type", b"text/css; charset=utf-8"),
                                      (b"content-length", str(len(_STYLESHEET)).encode("ascii")),
                                      (b"cache-control", b"no-store"),
                                      (b"referrer-policy", b"no-referrer"),
                                      (b"content-security-policy", _CSP.encode("ascii")),
                                      (b"x-content-type-options", b"nosniff"),
                                      (b"x-frame-options", b"DENY")], _STYLESHEET)
            elif type(path) is not str or not path.startswith("/approval/"):
                response = _error(ErrorCode.REF_OUT_OF_SCOPE, 404)
            else:
                ticket_match = re.fullmatch(r"/approval/([^/]+)(?:/decision)?", path)
                ticket = ticket_match.group(1) if ticket_match else ""
                if not ticket or not _TICKET_RE.fullmatch(ticket):
                    response = _error(ErrorCode.REF_OUT_OF_SCOPE, 404)
                else:
                    try:
                        session = await _invoke(authenticator.authenticate, scope, headers)
                    except Exception:
                        session = None
                    try:
                        now = clock.now()
                    except Exception:
                        now = datetime.min
                    if not _live_session(session, now):
                        response = _error(ErrorCode.NOT_ENTITLED, 401)
                    elif method == "GET" and path == f"/approval/{ticket}":
                        try:
                            parsed_ticket = UUID(ticket)
                        except ValueError:
                            parsed_ticket = None
                        if parsed_ticket is None or str(parsed_ticket) != ticket:
                            response = _error(ErrorCode.REF_OUT_OF_SCOPE, 404)
                        else:
                            try:
                                result = await _invoke(service.open_preview, session.principal, session, parsed_ticket,
                                                       now=now)
                            except Exception:
                                result = None
                        if parsed_ticket is not None and str(parsed_ticket) == ticket and (
                                type(result) is not Result or result.error is not None
                                or type(result.value) is not DecisionPage):
                            response = _error(result.error if type(result) is Result and result.error else
                                              ErrorCode.AUDIT_UNAVAILABLE)
                        elif parsed_ticket is not None and str(parsed_ticket) == ticket:
                            current_context = _current_context(result.value, session)
                            rendered = _render_preview(result.value)
                            if current_context is None:
                                response = _error(ErrorCode.NOT_ENTITLED)
                            elif rendered is None:
                                response = _error(ErrorCode.DIGEST_MISMATCH)
                            else:
                                preview_content, _payload = rendered
                                content = current_context + preview_content
                                confirmation_required = result.value.confirmation_required
                                confirmation_phrase = result.value.confirmation_phrase
                                if (type(confirmation_required) is not bool
                                        or type(result.value.decision_allowed) is not bool
                                        or (confirmation_required and
                                            (type(confirmation_phrase) is not str or not confirmation_phrase))
                                        or (not confirmation_required and confirmation_phrase is not None)):
                                    response = _error(ErrorCode.TARGET_REJECTED)
                                elif not result.value.decision_allowed:
                                    content += ("<p role=\"status\">This change no longer requires a decision. "
                                                "The current record status is shown above.</p>")
                                    response = _page("Review change", content)
                                else:
                                    confirmation = ""
                                    if confirmation_required:
                                        confirmation = (
                                            "<p>Policy requires an additional confirmation. Type <strong>“" +
                                            html.escape(confirmation_phrase, quote=True) + "”</strong>.</p>"
                                            "<label for=\"confirmation_text\">Type the exact confirmation phrase</label>"
                                            "<input id=\"confirmation_text\" name=\"confirmation_text\" "
                                            "type=\"text\" autocomplete=\"off\" required maxlength=\"256\" "
                                            "aria-describedby=\"confirmation-help\">"
                                            "<p id=\"confirmation-help\">Enter the phrase shown by the approval policy.</p>")
                                    action = "/approval/" + html.escape(ticket, quote=True) + "/decision"
                                    ref_input = ("<input type=\"hidden\" name=\"decision_ref\" value=\"" +
                                                 html.escape(result.value.decision_ref, quote=True) + "\">")
                                    content += ("<form method=\"post\" action=\"" + action + "\">" +
                                                ref_input + confirmation +
                                                "<button type=\"submit\" name=\"decision\" value=\"APPROVE\">Approve</button>"
                                                "</form><form method=\"post\" action=\"" + action + "\">" +
                                                ref_input +
                                                "<button type=\"submit\" name=\"decision\" value=\"REJECT\">Reject</button>"
                                                "</form>")
                                    response = _page("Review change", content)
                    elif method == "POST" and path == f"/approval/{ticket}/decision":
                        content_types = header_lists.get("content-type", [])
                        if content_types != ["application/x-www-form-urlencoded"]:
                            response = _error(ErrorCode.SCHEMA_INVALID, 415)
                        elif not _origin_matches(headers.get("origin", ""), headers.get("referer", ""), origin):
                            response = _error(ErrorCode.NOT_ENTITLED, 403)
                        else:
                            body = bytearray()
                            try:
                                while True:
                                    message = await receive()
                                    if message.get("type") != "http.request":
                                        continue
                                    body.extend(message.get("body", b""))
                                    if len(body) > _MAX_FORM_BYTES:
                                        raise OverflowError
                                    if not message.get("more_body", False):
                                        break
                                form = parse_qsl(bytes(body).decode("ascii"), keep_blank_values=True,
                                                 strict_parsing=True, max_num_fields=3,
                                                 encoding="utf-8", errors="strict")
                                data: dict[str, str] = {}
                                for key, value in form:
                                    if key in data or key not in {"decision_ref", "decision", "confirmation_text"}:
                                        raise ValueError("FORM_FIELDS_INVALID")
                                    data[key] = value
                                if (set(data) - {"decision_ref", "decision", "confirmation_text"}
                                        or not {"decision_ref", "decision"}.issubset(data)):
                                    raise ValueError("FORM_FIELDS_INVALID")
                                if len(data["decision_ref"]) > 512 or data["decision"] not in {"APPROVE", "REJECT"}:
                                    raise ValueError("FORM_VALUE_INVALID")
                            except (UnicodeError, ValueError, OverflowError, TypeError):
                                data = {}
                            if not data:
                                response = _error(ErrorCode.SCHEMA_INVALID, 400)
                            else:
                                try:
                                    result = await _invoke(
                                        service.submit_decision, session.principal, session,
                                        data["decision_ref"], data["decision"],
                                        confirmation_text=data.get("confirmation_text", ""),
                                        origin=headers.get("origin", ""), referer=headers.get("referer", ""), now=now)
                                except Exception:
                                    result = None
                                if type(result) is not Result or result.error is not None:
                                    response = _error(result.error if type(result) is Result and result.error else
                                                      ErrorCode.AUDIT_UNAVAILABLE)
                                else:
                                    message = ("Rejection recorded." if data["decision"] == "REJECT"
                                               else "Decision recorded.")
                                    response = _page("Decision recorded", "<p role=\"status\">" + message +
                                                     "</p><p>Return to pending changes.</p>")
                    else:
                        response = _error(ErrorCode.SCHEMA_INVALID, 405)
        status, response_headers, content = response
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": content})

    return app

