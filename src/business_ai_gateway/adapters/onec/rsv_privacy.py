"""Scoped SDK diagnostic sanitization and discarded raw stderr; SDK retains transport ownership."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from functools import wraps

import mcp.client.stdio as sdk_stdio
from mcp.client.stdio import stdio_client

_PRIVATE = ContextVar("erp_mcp_rsv_private_diagnostics", default=False)
_STANDARD_FIELDS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))
MAX_RSV_WIRE_LINE_BYTES = 5_000_000
MAX_RSV_SESSION_WIRE_BYTES = 10_000_000
MAX_RSV_SESSION_FRAMES = 64


class RSVWireLimitExceeded(RuntimeError):
    """Fixed-code pre-parser rejection, never includes untrusted stdout."""


def _install_text_guard() -> None:
    # The locked official SDK owns spawning, decoding, framing, JSON parsing and teardown.
    # Its TextReceiveStream has no wire budget hook. Wrap that seam once; activation is
    # captured per stream from this task's private ContextVar, never a global enable toggle.
    original = sdk_stdio.TextReceiveStream
    if getattr(original, '_erp_mcp_rsv_wire_guard', False):
        return

    class ScopedBoundedTextReceiveStream(original):
        _erp_mcp_rsv_wire_guard = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._rsv_active = _PRIVATE.get()
            self._rsv_line_bytes = self._rsv_session_bytes = self._rsv_frames = 0

        async def receive(self):
            text = await super().receive()
            if not self._rsv_active:
                return text  # unrelated SDK sessions remain byte-for-byte unchanged
            self._rsv_session_bytes += len(text.encode('utf-8'))
            segments = text.split('\n')
            exceeded = self._rsv_session_bytes > MAX_RSV_SESSION_WIRE_BYTES
            for index, segment in enumerate(segments):
                self._rsv_line_bytes += len(segment.encode('utf-8'))
                exceeded |= self._rsv_line_bytes > MAX_RSV_WIRE_LINE_BYTES
                if index < len(segments) - 1:
                    self._rsv_frames += 1
                    self._rsv_line_bytes = 0
            exceeded |= self._rsv_frames > MAX_RSV_SESSION_FRAMES
            if exceeded:
                # Close only this SDK-owned receive pipe so the SDK's shielded stdout drain
                # cannot wait for a malicious writer forever before propagating the failure.
                try:
                    await self.transport_stream.aclose()
                except Exception:  # noqa: BLE001 - never expose receive-pipe cleanup diagnostics
                    raise RSVWireLimitExceeded('RSV_WIRE_LIMIT_EXCEEDED') from None
                raise RSVWireLimitExceeded('RSV_WIRE_LIMIT_EXCEEDED')
            return text

    sdk_stdio.TextReceiveStream = ScopedBoundedTextReceiveStream


def _scrub_record(record):
    record.name = "business_ai_gateway.rsv_diagnostic"
    record.msg, record.args = "RSV_ADAPTER_DIAGNOSTIC", ()
    record.exc_info = record.exc_text = record.stack_info = None
    record.pathname = "<rsv-adapter>"
    record.filename = record.module = "rsv-adapter"
    record.funcName = "rsv_adapter"
    if hasattr(record, "taskName"):
        record.taskName = "rsv_adapter"
    for name in set(vars(record)) - _STANDARD_FIELDS:
        delattr(record, name)


class _PrivateDiagnosticFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            _scrub_record(record)  # `extra` is merged after the record factory runs.
        return True


_FILTER = _PrivateDiagnosticFilter()


def _install_factory() -> None:
    # Loaded SDK loggers are filtered before handlers, including structured `extra` fields.
    for logger in (logging.getLogger(), *logging.Logger.manager.loggerDict.copy().values()):
        if isinstance(logger, logging.Logger) and _FILTER not in logger.filters:
            logger.addFilter(_FILTER)
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_erp_mcp_rsv_sanitizer", False):
        return

    def sanitized_factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if _PRIVATE.get():
            _scrub_record(record)
        return record

    sanitized_factory._erp_mcp_rsv_sanitizer = True
    logging.setLogRecordFactory(sanitized_factory)


@contextmanager
def private_rsv_diagnostics():
    _install_factory()
    _install_text_guard()
    token = _PRIVATE.set(True)
    try:
        yield
    finally:
        _PRIVATE.reset(token)


def private_rsv_operation(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        with private_rsv_diagnostics():
            return await function(*args, **kwargs)
    return wrapped


@asynccontextmanager
async def quiet_stdio_client(parameters):
    with await asyncio.to_thread(open, os.devnull, "w", encoding="utf-8") as error_sink:
        async with stdio_client(parameters, errlog=error_sink) as streams:
            yield streams
