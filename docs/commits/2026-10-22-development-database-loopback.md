# Change record: Bind development databases to loopback

## Change

- Updated `compose.development.yml` so PostgreSQL on host port 5432 and Redis on host port 6379 publish only on `127.0.0.1`.
- Development PostgreSQL and Redis were started for the operator. Their initial Compose port mappings listened on all host interfaces, so the containers must be recreated after applying this mapping to make the running configuration match the source.
- The development gateway was not started: this checkout has no `.env` or `.env.development` configuration, and the documented startup sequence also requires database migrations. No migration was run.
- The Phase 2 MCP remains loopback-only on port 21200. Its configured gateway flags are both false, so it exposes capabilities but cannot reconcile two bases.

## Why

The development Compose profile is documented as local-only. Publishing its database ports on every host interface was broader than required for local development. Loopback bindings preserve local access while preventing LAN access through these published ports.

## Affected contracts and paths

- `compose.development.yml`: host binding for the `postgres` and `redis` services.
- `README.md` quick-start section describes the development profile as local-only; no gateway or data model contract changed.

## Decision

- Keep both databases available to local applications on the documented ports, bound to `127.0.0.1`.
- Recreate only `erp_mcp-postgres-1` and `erp_mcp-redis-1` through the development Compose project. Do not restart the separate real-1C lane databases or Docker Desktop.
- Do not run migrations or seed data as part of service startup.

## Verification state

- Before recreation, both development containers were healthy, PostgreSQL accepted connections, and Redis returned `PONG`; Docker published both ports on all interfaces.
- Applied with `docker compose -f compose.development.yml up -d --force-recreate postgres redis` (without `--renew-anon-volumes` or `down -v`).
- After recreation, both containers reported `healthy`; PostgreSQL `pg_isready` reported accepting connections and Redis `redis-cli ping` returned `PONG`.
- `docker inspect` reported `HostIp=127.0.0.1` for ports 5432 and 6379. `Get-NetTCPConnection` reported only `127.0.0.1` listeners for both host ports.
- Existing anonymous volume IDs were unchanged: PostgreSQL `cae7e21ee4018f84cb15ba0e7ec2b0ba934c4355adc0c224a02388c76e83455e`; Redis `8a7647e10802774bd66dab1485f15d26a44bf1f6254455569b1fa599862dc327`.
- A read-only `code-reviewer` agent review (GPT-6 Luna, low effort) identified the need to verify runtime mappings and preserve anonymous volumes. Follow-up confirmed both mappings, listener addresses, volume identities and health; its documentation-accuracy finding is resolved in this record.
- The separate Codex review wrapper was attempted before commit, but its configured `gpt-6-luna` model was rejected by the ChatGPT-account route (`model is not supported when using Codex with a ChatGPT account`). No model substitution was made.
- No test suite, migration, or seed operation is part of this change.

## Lesson

When a Compose profile is intended for local-only use, make the host IP explicit in each published port mapping. Container health does not prove that the host binding has the intended network scope.
