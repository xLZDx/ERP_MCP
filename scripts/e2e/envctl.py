"""Helper for the disposable local E2E environment (see docs/E2E_ENVIRONMENT.md).

Subcommands are called by the PowerShell scripts in this directory. Secrets are generated
randomly once and stored only under the git-ignored ``.e2e/`` directory; nothing here prints
a secret.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = Path(os.environ.get("E2E_DIR") or ROOT / ".e2e")

HOST = "127.0.0.1"
PORTS = {"postgres": 15432, "redis": 16379, "fake1c": 18766, "idp": 18080, "gateway": 18000}
REALM = "erp-mcp-test"
ISSUER = f"http://{HOST}:{PORTS['idp']}/realms/{REALM}"
MCP_AUDIENCE = f"http://{HOST}:{PORTS['gateway']}/mcp"
ADMIN_AUDIENCE = f"http://{HOST}:{PORTS['gateway']}/admin"
STEP_UP_ACR = "urn:local-test:step-up"
BASIC_ACR = "urn:local-test:basic"
ADMIN_CLIENT = "erp-mcp-admin-e2e"
DATA_CLIENT = "erp-mcp-data-e2e"
HEADLESS_CLIENT = "erp-mcp-headless-e2e"
SOURCE_ID = "fake1c-e2e"
COMPANY_ONE = "00000000-0000-0000-0000-000000000001"
COMPANY_TWO = "00000000-0000-0000-0000-000000000002"
BOOTSTRAP_BINDING_ID = "00000000-0000-4000-8000-0000000000a1"
GROUP_ONE = "erp-company-one-readers"
GROUP_TWO = "erp-company-two-readers"
SEED_MODES = ("baseline", "bootstrap-only", "none")

# username -> groups. The subject (sub) equals the username and is stable.
IDENTITIES = {
    "user_company_one": [GROUP_ONE],
    "user_company_two": [GROUP_TWO],
    "user_no_access": [],
    "platform_admin": ["erp-platform-admins"],
    "source_admin": ["erp-source-admins"],
    "access_admin": ["erp-access-admins"],
    "profile_admin": ["erp-profile-admins"],
    "auditor": ["erp-auditors"],
    "admin_no_role": [],
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load(name: str) -> dict:
    return json.loads((E2E_DIR / name).read_text(encoding="utf-8"))


def _token() -> str:
    return secrets.token_hex(24)


def init_secrets() -> None:
    """Generate secrets/credentials/IdP config once; never regenerate existing files."""
    if not (E2E_DIR / "secrets.json").exists():
        _write(E2E_DIR / "secrets.json", json.dumps({
            "pg_owner_password": _token(), "pg_app_password": _token(),
            "pg_admin_password": _token(), "pg_control_password": _token(),
            "redis_password": _token(), "fake1c_username": "e2e-" + secrets.token_hex(4),
            "fake1c_password": _token(), "admin_client_secret": _token(),
            "headless_client_secret": _token(), "idp_cookie_secret": _token(),
        }, indent=2))
    if not (E2E_DIR / "credentials.json").exists():
        _write(E2E_DIR / "credentials.json", json.dumps({
            "users": {n: {"sub": n, "username": n, "password": _token()} for n in IDENTITIES},
        }, indent=2))
    sec = _load("secrets.json")
    if not (E2E_DIR / "idp-config.json").exists():
        _write(E2E_DIR / "idp-config.json", json.dumps({
            "issuer": ISSUER, "host": HOST, "port": PORTS["idp"],
            "key_path": str(E2E_DIR / "idp-signing-key.pem"),
            "credentials_path": str(E2E_DIR / "credentials.json"),
            "cookie_secret": sec["idp_cookie_secret"],
            "step_up_acr": STEP_UP_ACR, "basic_acr": BASIC_ACR,
            "access_token_ttl": 3600, "id_token_ttl": 3600, "refresh_ttl": 1800,
            "sso_session_ttl": 28800,
            "audiences": {"data": MCP_AUDIENCE, "admin": ADMIN_AUDIENCE},
            "groups": {n: g for n, g in IDENTITIES.items()},
            "clients": [
                {"client_id": ADMIN_CLIENT, "secret": sec["admin_client_secret"],
                 "redirect_uris": [f"http://{HOST}:{PORTS['gateway']}/admin/callback"],
                 "post_logout_redirect_uris": [f"http://{HOST}:{PORTS['gateway']}/admin/"],
                 "audiences": [ADMIN_AUDIENCE],
                 "scopes": ["openid", "profile", "erp_mcp:admin"],
                 "grant_types": ["authorization_code", "refresh_token"]},
                {"client_id": DATA_CLIENT, "secret": None,
                 "redirect_uris": [f"http://{HOST}:{PORTS['idp']}/e2e/callback"],
                 "post_logout_redirect_uris": [f"http://{HOST}:{PORTS['idp']}/e2e/callback"],
                 "audiences": [MCP_AUDIENCE],
                 "scopes": ["openid", "profile", "onec:read"],
                 "grant_types": ["authorization_code", "refresh_token"]},
                {"client_id": HEADLESS_CLIENT, "secret": sec["headless_client_secret"],
                 "redirect_uris": [], "post_logout_redirect_uris": [],
                 "audiences": [MCP_AUDIENCE, ADMIN_AUDIENCE],
                 "scopes": ["openid", "profile", "onec:read", "erp_mcp:admin"],
                 "grant_types": ["password"]},
            ],
        }, indent=2))
    _write(E2E_DIR / "compose.env", "\n".join([
        f"E2E_PG_OWNER_PASSWORD={sec['pg_owner_password']}",
        f"E2E_REDIS_PASSWORD={sec['redis_password']}", ""]))


def dsn(role: str) -> str:
    sec = _load("secrets.json")
    user, key = {
        "owner": ("business_ai", "pg_owner_password"),
        "app": ("business_ai_app", "pg_app_password"),
        "admin": ("business_ai_admin", "pg_admin_password"),
        "control": ("business_ai_control_api", "pg_control_password"),
    }[role]
    return f"postgresql://{user}:{sec[key]}@{HOST}:{PORTS['postgres']}/business_ai"


def redis_url() -> str:
    return f"redis://:{_load('secrets.json')['redis_password']}@{HOST}:{PORTS['redis']}/0"


def env_vars() -> dict[str, str]:
    sec = _load("secrets.json")
    gw = PORTS["gateway"]
    return {
        "BAG_ENVIRONMENT": "development",
        "BAG_PUBLIC_MCP_URL": MCP_AUDIENCE,
        "BAG_DATABASE_URL": dsn("app"),
        "BAG_ADMIN_DATABASE_URL": dsn("admin"),
        "BAG_ADMIN_CONTROL_DATABASE_URL": dsn("control"),
        "BAG_REDIS_URL": redis_url(),
        "BAG_OAUTH_ENABLED": "true",
        "BAG_OAUTH_ISSUER": ISSUER,
        "BAG_OAUTH_AUDIENCE": MCP_AUDIENCE,
        "BAG_OAUTH_JWKS_URL": f"{ISSUER}/protocol/openid-connect/certs",
        "BAG_ADMIN_API_ENABLED": "true",
        "BAG_ADMIN_UI_ENABLED": "true",
        "BAG_ADMIN_MUTATIONS_ENABLED": "true",
        "BAG_ADMIN_OAUTH_AUDIENCE": ADMIN_AUDIENCE,
        "BAG_ADMIN_OAUTH_REQUIRED_SCOPE": "erp_mcp:admin",
        "BAG_ADMIN_OIDC_AUTHORIZATION_URL": f"{ISSUER}/protocol/openid-connect/auth",
        "BAG_ADMIN_OIDC_TOKEN_URL": f"{ISSUER}/protocol/openid-connect/token",
        "BAG_ADMIN_OIDC_CLIENT_ID": ADMIN_CLIENT,
        "BAG_ADMIN_OIDC_CLIENT_SECRET": sec["admin_client_secret"],
        "BAG_ADMIN_OIDC_REDIRECT_URI": f"http://{HOST}:{gw}/admin/callback",
        "BAG_ADMIN_STEP_UP_ACR_VALUES": STEP_UP_ACR,
        "BAG_ADMIN_SOURCE_ALLOWED_HOSTS": f"{HOST}:{PORTS['fake1c']}",
        "BAG_ADMIN_SOURCE_ALLOWED_CIDRS": "127.0.0.1/32",
        "BAG_SECRET_PROVIDER": "env",
        "BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED": "false",
        "FAKE1C_USERNAME": sec["fake1c_username"],
        "FAKE1C_PASSWORD": sec["fake1c_password"],
        "NO_PROXY": f"{HOST},localhost",
        "no_proxy": f"{HOST},localhost",
    }


def write_env(seed: str) -> None:
    """Write env.json (non-secret topology) and env.ps1 (secret-bearing, for consumers)."""
    lines = ["# Generated by scripts/e2e/envctl.py - contains secrets, never commit."]
    for key, value in env_vars().items():
        lines.append(f"$env:{key} = '{value}'")
    lines.append(f"$env:BAG_MIGRATION_DATABASE_URL = '{dsn('owner')}'")
    lines.append(f"$env:BAG_PRIVILEGE_TEST_DATABASE_URL = '{dsn('owner')}'")
    lines.append(f"$env:E2E_DIR = '{E2E_DIR}'")
    _write(E2E_DIR / "env.ps1", "\r\n".join(lines) + "\r\n")
    ports = dict(PORTS)
    _write(E2E_DIR / "env.json", json.dumps({
        "project": "erpmcp-e2e", "host": HOST, "ports": ports, "seed_mode": seed,
        "issuer": ISSUER, "realm": REALM,
        "idp": {"authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
                "logout_endpoint": f"{ISSUER}/protocol/openid-connect/logout",
                "data_client_id": DATA_CLIENT, "admin_client_id": ADMIN_CLIENT,
                "headless_client_id": HEADLESS_CLIENT,
                "data_redirect_uri": f"http://{HOST}:{PORTS['idp']}/e2e/callback"},
        "audiences": {"data": MCP_AUDIENCE, "admin": ADMIN_AUDIENCE},
        "scopes": {"data": "onec:read", "admin": "erp_mcp:admin"},
        "step_up_acr": STEP_UP_ACR, "basic_acr": BASIC_ACR,
        "urls": {"gateway": f"http://{HOST}:{PORTS['gateway']}",
                 "mcp": MCP_AUDIENCE, "admin": ADMIN_AUDIENCE + "/",
                 "fake1c": f"http://{HOST}:{PORTS['fake1c']}/odata/standard.odata",
                 "idp": f"http://{HOST}:{PORTS['idp']}"},
        "identities": {n: {"sub": n, "groups": g} for n, g in IDENTITIES.items()},
        "source_id": SOURCE_ID, "companies": {"one": COMPANY_ONE, "two": COMPANY_TWO},
        "schema_version": 14,
    }, indent=2))


async def _owner():
    return await asyncpg.connect(dsn("owner"), timeout=10)


async def ensure_roles() -> None:
    sec = _load("secrets.json")
    conn = await _owner()
    try:
        for role, key in (("business_ai_app", "pg_app_password"),
                          ("business_ai_admin", "pg_admin_password"),
                          ("business_ai_control_api", "pg_control_password")):
            password = sec[key]
            if not password.isalnum():
                raise SystemExit("generated password must be alphanumeric")
            exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", role)
            verb = "ALTER" if exists else "CREATE"
            await conn.execute(f"{verb} ROLE {role} LOGIN PASSWORD '{password}'")
        print("roles ready: business_ai_app business_ai_admin business_ai_control_api")
    finally:
        await conn.close()


async def verify() -> None:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    from scripts.verify_schema import verify_schema

    conn = await _owner()
    try:
        await verify_schema(conn)
        print("verify_schema: PASS")
    finally:
        await conn.close()


async def status_json() -> dict:
    out: dict = {}
    try:
        conn = await asyncpg.connect(dsn("app"), timeout=5)
        try:
            out["postgres"] = {
                "ok": True, "server_version": await conn.fetchval("SHOW server_version"),
                "schema_version": await conn.fetchval(
                    "SELECT max(version) FROM bag.schema_migrations")}
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001 - status must report, not raise
        out["postgres"] = {"ok": False, "error": type(exc).__name__}
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(redis_url(), socket_connect_timeout=3)
        try:
            info = await client.info("server")
            out["redis"] = {"ok": bool(await client.ping()), "server_version": info["redis_version"]}
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        out["redis"] = {"ok": False, "error": type(exc).__name__}
    return out


async def drop_schema() -> None:
    conn = await _owner()
    try:
        await conn.execute("DROP SCHEMA IF EXISTS bag CASCADE")
        print("schema bag dropped")
    finally:
        await conn.close()


async def schema_version() -> int | None:
    conn = await _owner()
    try:
        if not await conn.fetchval("SELECT to_regclass('bag.schema_migrations') IS NOT NULL"):
            return None
        return await conn.fetchval("SELECT max(version) FROM bag.schema_migrations")
    finally:
        await conn.close()


async def flush_redis() -> None:
    from redis.asyncio import Redis

    client = Redis.from_url(redis_url())
    try:
        await client.flushall()
        print("redis flushed")
    finally:
        await client.aclose()


def _admin_cli(*args: str) -> None:
    env = {**os.environ, **env_vars(), "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "admin.py"), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"admin.py {args[0]} failed: {result.stderr.strip()[-400:]}")
    print(f"admin.py {args[0]}: ok")


async def seed(mode: str) -> None:
    if mode not in SEED_MODES:
        raise SystemExit(f"unknown seed mode {mode}")
    if mode == "none":
        print("seed: none")
        return
    conn = await _owner()
    try:
        has_admin = await conn.fetchval(
            "SELECT 1 FROM bag.platform_role_bindings WHERE principal_kind='subject' "
            "AND principal_id='platform_admin' AND role_name='PLATFORM_ADMIN' "
            "AND revoked_at IS NULL")
        grants = {
            (r["principal_kind"], r["principal_id"], r["company_id"]) for r in await conn.fetch(
                "SELECT principal_kind, principal_id, company_id::text AS company_id "
                "FROM bag.access_grants WHERE revoked_at IS NULL"
            )
        } if mode == "baseline" else set()
    finally:
        await conn.close()
    if not has_admin:
        _admin_cli("platform-role-add", "--binding-id", BOOTSTRAP_BINDING_ID, "--kind", "subject",
                   "--principal", "platform_admin", "--role", "PLATFORM_ADMIN",
                   "--created-by", "e2e-bootstrap", "--reason",
                   "Disposable local E2E bootstrap platform administrator")
    if mode == "bootstrap-only":
        return
    _admin_cli("source-upsert", "--source-id", SOURCE_ID, "--display-name",
               "Fake1C E2E synthetic source", "--base-url",
               f"http://{HOST}:{PORTS['fake1c']}/odata/standard.odata",
               "--username-secret", "FAKE1C_USERNAME", "--password-secret", "FAKE1C_PASSWORD",
               "--allow", "Catalog_*", "Document_*", "AccumulationRegister_*")
    _admin_cli("company-upsert", "--company-id", COMPANY_ONE, "--source-id", SOURCE_ID,
               "--external-ref", COMPANY_ONE, "--display-name", "Synthetic organization one",
               "--default")
    _admin_cli("company-upsert", "--company-id", COMPANY_TWO, "--source-id", SOURCE_ID,
               "--external-ref", COMPANY_TWO, "--display-name", "Synthetic organization two")
    if ("subject", "user_company_one", COMPANY_ONE) not in grants:
        _admin_cli("grant-add", "--kind", "subject", "--principal", "user_company_one",
                   "--source-id", SOURCE_ID, "--company-id", COMPANY_ONE)
    if ("group", GROUP_TWO, COMPANY_TWO) not in grants:
        _admin_cli("grant-add", "--kind", "group", "--principal", GROUP_TWO,
                   "--source-id", SOURCE_ID, "--company-id", COMPANY_TWO)


def mint(user: str, audience: str, scope: str) -> str:
    """Mint a token for `user` through the IdP headless client (password grant)."""
    import httpx

    sec, creds = _load("secrets.json"), _load("credentials.json")
    response = httpx.post(
        f"{ISSUER}/protocol/openid-connect/token", trust_env=False, timeout=10,
        data={"grant_type": "password", "client_id": HEADLESS_CLIENT,
              "client_secret": sec["headless_client_secret"], "username": user,
              "password": creds["users"][user]["password"], "audience": audience,
              "scope": scope})
    response.raise_for_status()
    return response.json()["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("init-secrets", "ensure-roles", "drop-schema", "schema-version", "flush-redis",
                 "verify-schema", "status-json"):
        sub.add_parser(name)
    w = sub.add_parser("write-env")
    w.add_argument("--seed", choices=SEED_MODES, required=True)
    s = sub.add_parser("seed")
    s.add_argument("--mode", choices=SEED_MODES, required=True)
    m = sub.add_parser("mint")
    m.add_argument("--user", required=True)
    m.add_argument("--audience", choices=("data", "admin"), default="data")
    args = parser.parse_args()
    if args.cmd == "init-secrets":
        init_secrets()
    elif args.cmd == "write-env":
        write_env(args.seed)
    elif args.cmd == "ensure-roles":
        asyncio.run(ensure_roles())
    elif args.cmd == "drop-schema":
        asyncio.run(drop_schema())
    elif args.cmd == "schema-version":
        print(asyncio.run(schema_version()))
    elif args.cmd == "flush-redis":
        asyncio.run(flush_redis())
    elif args.cmd == "verify-schema":
        asyncio.run(verify())
    elif args.cmd == "status-json":
        print(json.dumps(asyncio.run(status_json())))
    elif args.cmd == "seed":
        asyncio.run(seed(args.mode))
    elif args.cmd == "mint":
        aud, scope = (MCP_AUDIENCE, "onec:read") if args.audience == "data" else (
            ADMIN_AUDIENCE, "erp_mcp:admin")
        print(mint(args.user, aud, scope))


if __name__ == "__main__":
    _ = uuid  # keep import for deterministic id helpers used by tests
    main()
