"""Recording ASGI wrapper in front of the synthetic Fake1C application (test harness only).

Every request that reaches the wrapper is appended to an in-memory list (method + path +
query keys, never headers or bodies, so credentials cannot leak into the evidence). The
functional suite reads the list through ``GET /__ft__/requests`` to prove that the gateway
only ever sent GET/HEAD requests to 1C and that denied calls produced no upstream traffic.

This module is a harness: it does not change what Fake1C answers.
"""

from __future__ import annotations

import os
import threading
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from business_ai_gateway.testbed.fake1c import create_app

_LOCK = threading.Lock()
_REQUESTS: list[dict] = []
_SEQ = 0


def _record(method: str, path: str, query: str) -> None:
    global _SEQ
    keys = sorted({part.split("=", 1)[0] for part in query.split("&") if part})
    with _LOCK:
        _SEQ += 1
        _REQUESTS.append(
            {"seq": _SEQ, "t": time.time(), "method": method, "path": path, "query_keys": keys}
        )


class RecordingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope["path"].startswith("/__ft__/"):
            _record(
                scope["method"],
                scope["path"],
                (scope.get("query_string") or b"").decode("latin-1"),
            )
        await self.app(scope, receive, send)


async def _requests(request: Request):
    since = int(request.query_params.get("since", "0"))
    with _LOCK:
        items = [r for r in _REQUESTS if r["seq"] > since]
        last = _SEQ
    return JSONResponse({"last_seq": last, "requests": items})


_inner = create_app(os.getenv("FAKE1C_PROFILE", "json"))
_outer = Starlette(routes=[Route("/__ft__/requests", _requests, methods=["GET"])])


async def app(scope, receive, send):
    if scope["type"] == "http" and scope["path"].startswith("/__ft__/"):
        await _outer(scope, receive, send)
    else:
        await RecordingMiddleware(_inner)(scope, receive, send)
