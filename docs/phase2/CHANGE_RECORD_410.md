# Change Record 410 - Accept validated ASGI address pairs

Sprint: beea27520b33

## Trigger and change

The e2e-runner's native Starlette TestClient request to the private S16 ingress
returned HTTP 400 before authentication/downstream handling: its server address
pair was a list, while the ingress accepted only an exact tuple. A temporary test
wrapper converted the list to a tuple and masked the compatibility failure.
The coordinator required retaining the original unwrapped positive request.

`src/erp_mcp_s16/ingress.py` now accepts exact tuple or list address pairs. It
retains the existing length, host type, integer port/range, literal IP/network,
configured origin, Host, forwarding, route and positive-authentication checks.
This expands representation compatibility without accepting a different network
identity or bypassing a private-route safeguard.

## Verification and provenance

The primary agent applied this narrow source fix. The e2e-runner owns regression
execution and keeps the unwrapped request and negative network/authentication
cases; no assertion is weakened. Its previous wrapper-based passing result is not
proof of native-client interoperability. Post-fix execution is pending at source
commit time. No primary-session test or runtime request was executed.

No listener, gateway route, writer capability, deployment or production binding
is added. Concurrent tests and pre-existing worktree changes are preserved.
