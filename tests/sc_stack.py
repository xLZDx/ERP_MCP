"""Integration-chain harness: MCP tools -> registry/profile -> real adapter -> Fake1C over HTTP
-> audit rows in a disposable PostgreSQL (BAG_PRIVILEGE_TEST_DATABASE_URL)."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import uvicorn

from business_ai_gateway.adapters.onec.adapter import OneCAdapter
from business_ai_gateway.adapters.onec.client import OneCReadClient
from business_ai_gateway.adapters.onec.sidecar_client import ODataSidecarClient
from business_ai_gateway.audit import Audit
from business_ai_gateway.db import Database
from business_ai_gateway.fixture_profiles import SyntheticFixtureProfiles
from business_ai_gateway.registry import Registry
from business_ai_gateway.secrets import EnvSecrets
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings
from scripts import synthetic_fixture_profiles as fixture_gen

# ERP_MCP_REQUIRE_DB_TESTS=1 (set in CI) turns a missing database into a failure, never a skip.
REQUIRE_DB_TESTS = os.getenv("ERP_MCP_REQUIRE_DB_TESTS") == "1"
PG_MARKS = [
    pytest.mark.skipif(
        not os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL") and not REQUIRE_DB_TESTS,
        reason="requires disposable PostgreSQL",
    ),
    pytest.mark.usefixtures("require_pg_database"),
]


def needs_pg(function):
    for mark in reversed(PG_MARKS):
        function = mark(function)
    return function


ORG_ONE = "00000000-0000-0000-0000-000000000001"
ORG_TWO = "00000000-0000-0000-0000-000000000002"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ServerThread:
    def __init__(self, app):
        self.port = free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 15
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        assert self.server.started
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def write_fixture_file(path: Path, document: dict) -> str:
    data = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def fixture_document(source_id: str, company_ids: dict[str, uuid.UUID] | None = None) -> dict:
    """The committed fixture document re-keyed to a per-test source id and company ids."""
    document = fixture_gen.build_document()
    entry = document["sources"].pop(fixture_gen.SOURCE_ID)
    if company_ids:
        entry["companies"] = {
            str(company_ids[ref]): value for ref, value in entry["companies"].items()
        }
    document["sources"][source_id] = entry
    return document


@dataclass
class Stack:
    mcp: object
    db: Database
    registry: Registry
    source_id: str
    companies: dict[str, uuid.UUID]
    fake_url: str
    settings: Settings
    runtime: object = None

    async def call(self, tool: str, **arguments):
        result = await self.mcp.call_tool(tool, arguments)
        return result

    @staticmethod
    def payload(result) -> dict:
        return json.loads(result.content[0].text)

    async def audit_rows(self, tool: str, since: float | None = None):
        return await self.db.require_pool().fetch(
            "SELECT outcome, detail_code, profile_fingerprint, company_id FROM bag.audit_events "
            "WHERE tool_name=$1 AND source_id=$2 ORDER BY occurred_at, event_id",
            tool,
            self.source_id,
        )


async def build_stack(
    url: str,
    fake_url: str,
    sidecar_url: str,
    *,
    fixture_file: Path | None,
    fixture_sha: str | None,
    tags: tuple[str, ...] = ("synthetic-fixture",),
    environment: str = "test",
    source_id: str | None = None,
    companies: dict[str, uuid.UUID] | None = None,
    env_setter=None,
) -> Stack:
    source_id = source_id or f"psc-{uuid.uuid4().hex[:12]}"
    companies = companies or {ORG_ONE: uuid.uuid4(), ORG_TWO: uuid.uuid4()}
    if env_setter:
        env_setter("PSC_USER", "synthetic-user")
        env_setter("PSC_PASSWORD", "synthetic-password")
    db = Database(url)
    await db.start()
    pool = db.require_pool()
    await pool.execute(
        """INSERT INTO bag.sources(source_id, project, kind, display_name, base_url, tags,
               username_secret_ref, password_secret_ref, entity_allow_patterns)
           VALUES($1,'onec','onec_odata','psc fake1c',$2,$3,'PSC_USER','PSC_PASSWORD',
                  ARRAY['Catalog_*','Document_*','AccumulationRegister_*','AccountingRegister_*'])""",
        source_id, fake_url + "/odata/standard.odata", list(tags),
    )
    for ref, company_id in companies.items():
        await pool.execute(
            "INSERT INTO bag.companies(company_id, source_id, external_ref, display_name) "
            "VALUES($1,$2,$3,$4)",
            company_id, source_id, ref, f"org {ref[-1]}",
        )
    await pool.execute(
        "INSERT INTO bag.access_grants(grant_id, principal_kind, principal_id, source_id, effect) "
        "VALUES($1,'subject','development-local',$2,'allow')",
        uuid.uuid4(), source_id,
    )
    settings = Settings(_env_file=None, environment=environment, max_rows=200)
    provider = None
    if fixture_file is not None:
        provider = SyntheticFixtureProfiles(fixture_file, fixture_sha, environment="test")
    registry = Registry(db, production=environment == "production", synthetic_profiles=provider)
    runtime = SimpleNamespace(
        audit=Audit(db, include_query=False),
        registry=registry,
        rate_limit=SimpleNamespace(check=AsyncMock()),
        onec=OneCAdapter(
            settings,
            EnvSecrets(),
            OneCReadClient(timeout_seconds=10, max_response_bytes=5_000_000),
            ODataSidecarClient(
                base_url=sidecar_url,
                token="t" * 40,
                timeout_seconds=10,
                max_response_bytes=5_000_000,
                max_rows=settings.max_rows,
            ),
            None,
        ),
        capability_policy=None,
    )
    return Stack(
        build_mcp(settings, runtime), db, registry, source_id, companies, fake_url, settings, runtime
    )
