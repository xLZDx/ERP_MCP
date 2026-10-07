"""Redaction and secret scanning for result artefacts (pure)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

_GUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_ASSIGN = re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key)(\s*[=:]\s*)\S+")
_BASIC = re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=_-]{6,}")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{6,}")
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]*@")
_KEYWORD_BLOB = re.compile(
    r"(?i)\b(key|secret|token|blob|cred\w*|auth\w*)\b[\s:=\"']{1,4}"
    r"(?=[A-Za-z0-9+/_-]*\d)[A-Za-z0-9+/_-]{16,}={0,2}"
)
_SECRET_PATH = re.compile(r"(?i)\bD:\\secrets(?:\\[^\s\"']*)?")
_ADMIN_CRED = re.compile(r"(?i)Admin_1C.{0,40}?(password|passwd|pwd)\s*[=:]\s*\S+")

SECRET_PATTERNS = {
    "admin_credential": _ADMIN_CRED,
    "credential_assignment": _ASSIGN,
    "basic_auth_header": _BASIC,
    "bearer_token": _BEARER,
    "url_userinfo": _USERINFO,
    "keyword_base64_blob": _KEYWORD_BLOB,
}


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _guid_sub(m: re.Match[str]) -> str:
    return "guid:" + sha256_hex(m.group(0).lower())[:8]


def redact_text(s: str) -> str:
    s = _USERINFO.sub(lambda m: m.group(1) + "<redacted>@", s)
    s = _BASIC.sub("Basic <redacted>", s)
    s = _BEARER.sub("Bearer <redacted>", s)
    s = _ASSIGN.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", s)
    s = _KEYWORD_BLOB.sub(lambda m: m.group(1) + " <redacted>", s)
    s = _SECRET_PATH.sub("<secret-path>", s)
    return _GUID.sub(_guid_sub, s)


def scan_for_secrets(text: str) -> list[str]:
    """Return names of secret patterns found. A secrets-directory path alone is not a hit."""
    return [name for name, rx in SECRET_PATTERNS.items() if rx.search(text)]


def sanitize_observation(d: Any) -> Any:
    """Recursively redact every string inside dicts/lists/tuples."""
    if isinstance(d, str):
        return redact_text(d)
    if isinstance(d, dict):
        return {k: sanitize_observation(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)):
        return [sanitize_observation(v) for v in d]
    return d
