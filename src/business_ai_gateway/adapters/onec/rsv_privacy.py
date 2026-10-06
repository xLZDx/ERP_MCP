"""Scoped SDK diagnostic sanitization and discarded raw stderr; SDK retains transport ownership."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from functools import wraps

from mcp.client.stdio import stdio_client

_PRIVATE = ContextVar("erp_mcp_rsv_private_diagnostics", default=False)
_STANDARD_FIELDS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))


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
