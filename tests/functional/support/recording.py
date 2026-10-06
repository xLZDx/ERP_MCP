"""Generic request-recording ASGI wrapper (method + path + query KEYS only; no headers/bodies).

`wrap(inner)` returns an ASGI app that records every request that reaches `inner` and serves the
log at GET /__ft__/requests?since=N. Used in front of Fake1C and of the test-only fake sidecar.
"""

from __future__ import annotations

import threading
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def wrap(inner):
    lock = threading.Lock()
    requests: list[dict] = []
    seq = [0]

    async def log_view(request: Request):
        since = int(request.query_params.get("since", "0"))
        with lock:
            items = [r for r in requests if r["seq"] > since]
            last = seq[0]
        return JSONResponse({"last_seq": last, "requests": items})

    control = Starlette(routes=[Route("/__ft__/requests", log_view, methods=["GET"])])

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/__ft__/"):
            await control(scope, receive, send)
            return
        if scope["type"] == "http":
            query = (scope.get("query_string") or b"").decode("latin-1")
            keys = sorted({p.split("=", 1)[0] for p in query.split("&") if p})
            with lock:
                seq[0] += 1
                requests.append({"seq": seq[0], "t": time.time(), "method": scope["method"],
                                 "path": scope["path"], "query_keys": keys})
        await inner(scope, receive, send)

    return app
