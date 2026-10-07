"""Stable, sanitized failure codes. Nothing here ever carries exception text, paths or credentials."""
from __future__ import annotations

COM_UNAVAILABLE = "COM_UNAVAILABLE"
COM_TIMEOUT = "COM_TIMEOUT"
COM_BINDING_MISMATCH = "COM_BINDING_MISMATCH"
COM_COMPANY_DENIED = "COM_COMPANY_DENIED"
COM_BAD_REQUEST = "COM_BAD_REQUEST"
COM_UNAUTHORIZED = "COM_UNAUTHORIZED"
COM_INTERNAL = "COM_INTERNAL"

STATUS_BY_CODE = {
    COM_UNAVAILABLE: 503,
    COM_TIMEOUT: 504,
    COM_BINDING_MISMATCH: 403,
    COM_COMPANY_DENIED: 403,
    COM_BAD_REQUEST: 400,
    COM_UNAUTHORIZED: 401,
    COM_INTERNAL: 500,
}


class BridgeFault(Exception):
    """A failure that maps to one stable code; the message is the code itself."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
