from __future__ import annotations

from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .runtime import Runtime
from .server import build_mcp
from .settings import Settings

settings = Settings()
runtime = Runtime(settings)
mcp = build_mcp(settings, runtime)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request):
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/readyz", methods=["GET"])
async def readyz(_: Request):
    try:
        ready = await runtime.ready()
        return JSONResponse(
            {"status": "ready" if ready else "not-ready"},
            status_code=200 if ready else 503,
        )
    except Exception as exc:  # noqa: BLE001 - readiness must degrade to 503
        return JSONResponse(
            {"status": "not-ready", "error": type(exc).__name__},
            status_code=503,
        )


parsed = urlparse(settings.public_mcp_url)
hostname = parsed.hostname or "127.0.0.1"
host_with_port = parsed.netloc
origin = f"{parsed.scheme}://{parsed.netloc}"
allowed_hosts = [host_with_port]
if parsed.port is None:
    allowed_hosts.append(f"{hostname}:*")

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=allowed_hosts,
    allowed_origins=[origin],
)

app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    max_request_body_size=1_048_576,
    session_idle_timeout=300,
    max_sessions=1000,
    transport_security=transport_security,
)
