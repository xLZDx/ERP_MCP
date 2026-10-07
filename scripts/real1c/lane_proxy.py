"""Loopback fault/recording proxy between the lane gateway and the real read-only 1C OData publication.

* Binds 127.0.0.1 only; forwards ONLY GET and HEAD upstream, any other method is answered 405 here and counted
  as a refused write attempt (the upstream never sees it).
* Records method/path counts (never headers, bodies or credentials) at ``/__lane__/requests``.
* Modes (switch with ``POST /__lane__/mode?name=...``): ``passthrough`` (HEAD is forwarded as HEAD; the real 1C
  publication answers it with 405), ``head_compat`` (default: HEAD is served as GET with the body dropped), ``down``
  (503), ``slow`` (adds a delay), ``truncate`` (cuts a response in half), ``drift`` (adds one synthetic EntitySet to
  $metadata).  Every mode except ``passthrough`` keeps the HEAD compatibility shim.
* This is a TEST ADAPTER: it exists to inject faults and to record that no write verb ever reaches 1C.
  Using ``head_compat`` hides a real product finding (HEAD 405); the report states it explicitly.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections import Counter

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

UPSTREAM = os.environ.get("LANE_PROXY_UPSTREAM", "http://127.0.0.1:8088")
PORT = int(os.environ.get("LANE_PROXY_PORT", "8191"))
MODES = {"passthrough", "head_compat", "down", "slow", "truncate", "drift"}
STATE = {"mode": os.environ.get("LANE_PROXY_MODE", "head_compat"), "delay": 3.0}
REQUESTS: Counter[str] = Counter()
REFUSED: Counter[str] = Counter()
PATHS: Counter[str] = Counter()
DRIFT_SET = '<EntitySet Name="Catalog_LaneDriftProbe" EntityType="StandardODATA.Catalog_LaneDriftProbe"/>'
_CLIENT = httpx.AsyncClient(timeout=180, trust_env=False)
_HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "content-encoding", "host"}


async def control(request: Request) -> Response:
    sub = request.path_params["sub"]
    if sub == "mode" and request.method == "POST":
        name = request.query_params.get("name", "")
        if name not in MODES:
            return JSONResponse({"error": "unknown mode"}, status_code=400)
        STATE["mode"] = name
        if request.query_params.get("delay"):
            STATE["delay"] = float(request.query_params["delay"])
        return JSONResponse({"mode": STATE["mode"], "delay": STATE["delay"]})
    if sub == "requests":
        return JSONResponse({"mode": STATE["mode"], "by_method": dict(REQUESTS), "refused_methods": dict(REFUSED),
                             "paths": dict(PATHS.most_common(120))})
    if sub == "reset" and request.method == "POST":
        REQUESTS.clear()
        REFUSED.clear()
        PATHS.clear()
        return JSONResponse({"ok": True})
    return JSONResponse({"error": "not found"}, status_code=404)


def _method_bucket(method: str, path: str) -> str:
    return f"{method} {re.sub(r'[0-9a-fA-F-]{36}', '<guid>', path.split('?')[0])[:120]}"


async def forward(request: Request) -> Response:
    method = request.method.upper()
    if method not in {"GET", "HEAD"}:
        REFUSED[method] += 1
        return JSONResponse({"error": "lane proxy forwards GET/HEAD only"}, status_code=405)
    REQUESTS[method] += 1
    if len(PATHS) < 400:
        PATHS[_method_bucket(method, request.url.path)] += 1
    mode = STATE["mode"]
    if mode == "down":
        return JSONResponse({"error": "lane proxy: source down"}, status_code=503)
    if mode == "slow":
        await asyncio.sleep(STATE["delay"])
    upstream_method = "GET" if (method == "HEAD" and mode != "passthrough") else method
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
    headers["Accept-Encoding"] = "identity"
    url = UPSTREAM + request.url.path + (("?" + request.url.query) if request.url.query else "")
    try:
        r = await _CLIENT.request(upstream_method, url, headers=headers)
    except httpx.HTTPError:
        return JSONResponse({"error": "lane proxy: upstream unreachable"}, status_code=502)
    body = r.content
    out_headers = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
    if method == "HEAD":
        body = b""
    elif mode == "truncate" and len(body) > 2:
        body = body[: len(body) // 2]
    elif mode == "drift" and request.url.path.endswith("$metadata"):
        text = body.decode("utf-8", "replace")
        body = re.sub(r"(<EntityContainer[^>]*>)", lambda m: m.group(1) + DRIFT_SET, text, count=1).encode("utf-8")
    return Response(content=body, status_code=r.status_code, headers=out_headers,
                    media_type=r.headers.get("content-type"))


app = Starlette(routes=[
    Route("/__lane__/{sub}", control, methods=["GET", "POST"]),
    Route("/{path:path}", forward, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
