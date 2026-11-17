"""S0 R2-US-001 TC002/M2: the app role cannot forge accepted observations."""

from __future__ import annotations

import asyncio
from argparse import Namespace
from contextlib import contextmanager
import uuid
from urllib.parse import quote

import asyncpg
import httpx
import pytest

from admin_support import attempt_sql, expect, fault, wait_until


WRITER_SIGNATURE = (
    "bag.record_capability_observation(text,uuid,bigint,text,text,text,text,boolean,"
    "boolean,boolean,boolean,integer,jsonb,jsonb)"
)
ACCEPTOR_SIGNATURE = "bag.accept_capability_observation(text,uuid,bigint)"
READER_SIGNATURE = "bag.read_accepted_capability_observation(text,uuid,bigint)"


@contextmanager
def acceptor_unavailable(e2e_env):
    url = f"http://{e2e_env.raw['host']}:{e2e_env.raw['ports']['capability_acceptor']}/healthz"

    def healthy():
        try:
            return httpx.get(url, trust_env=False, timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    fault("capability_acceptor", "stop")
    try:
        wait_until(lambda: not healthy(), timeout=15, interval=0.25,
                   what="capability acceptor stopped")
        yield
    finally:
        fault("capability_acceptor", "start")
        wait_until(healthy, timeout=30, interval=0.25, what="capability acceptor healthy")


def _capability_dsn(e2e_env, username: str, secret_key: str) -> str:
    password = quote(e2e_env.secrets[secret_key], safe="")
    port = e2e_env.raw["ports"]["postgres"]
    return f"postgresql://{username}:{password}@{e2e_env.raw['host']}:{port}/business_ai"


async def _exercise_source_version_and_readback(e2e_env, source_id: str) -> None:
    owner = await asyncpg.connect(e2e_env.dsn("owner"), timeout=10)
    writer = await asyncpg.connect(
        _capability_dsn(e2e_env, "business_ai_capability_writer_login",
                        "pg_capability_writer_password"), timeout=10,
    )
    acceptor = await asyncpg.connect(
        _capability_dsn(e2e_env, "business_ai_capability_acceptor_login",
                        "pg_capability_acceptor_password"), timeout=10,
    )
    app = await asyncpg.connect(e2e_env.dsn("app"), timeout=10)

    async def record(request_id: uuid.UUID, row_version: int, fingerprint: str) -> int:
        return await writer.fetchval(
            """
            SELECT bag.record_capability_observation(
                $1, $2::uuid, $3::bigint, $4, '8.3.synthetic', 'SUPPORTED',
                'ODATA_JSON_V3', true, true, false, false, 1, '{}'::jsonb, '{}'::jsonb
            )
            """,
            source_id,
            request_id,
            row_version,
            fingerprint,
        )

    async def read(request_id: uuid.UUID, observation_id: int):
        return await app.fetch(
            "SELECT drift_status FROM bag.read_accepted_capability_observation($1, $2::uuid, $3::bigint)",
            source_id,
            request_id,
            observation_id,
        )

    try:
        initial = await owner.fetchrow(
            """SELECT s.row_version,c.metadata_fingerprint FROM bag.sources s
               JOIN bag.source_capabilities c USING(source_id) WHERE s.source_id=$1""",
            source_id,
        )
        assert initial is not None and initial["row_version"] > 0
        assert initial["metadata_fingerprint"]

        trigger_version = await owner.fetchval(
            """UPDATE bag.sources SET display_name=display_name || ' M2 trigger probe'
               WHERE source_id=$1 RETURNING row_version""",
            source_id,
        )
        assert trigger_version == initial["row_version"] + 1, (
            "sources_row_version_bump must advance row_version for a direct SQL mutator"
        )

        # Persist against version N, mutate the registered source to N+1, then prove acceptor
        # refuses the observation produced against the stale source configuration.
        race_request = uuid.uuid4()
        race_observation = await record(
            race_request, trigger_version, initial["metadata_fingerprint"]
        )
        source = await owner.fetchrow(
            """SELECT display_name,base_url,username_secret_ref,password_secret_ref,tags,
                      entity_allow_patterns,entity_deny_patterns,platform_version_hint,
                      fallback_kind,fallback_base_url
               FROM bag.sources WHERE source_id=$1""",
            source_id,
        )
        from scripts.admin import source_upsert

        await source_upsert(
            Namespace(
                source_id=source_id,
                display_name=source["display_name"] + " M2 CLI upsert",
                base_url=source["base_url"],
                username_secret=source["username_secret_ref"],
                password_secret=source["password_secret_ref"],
                tags=list(source["tags"] or []),
                allow=list(source["entity_allow_patterns"] or []),
                deny=list(source["entity_deny_patterns"] or []),
                platform_version_hint=source["platform_version_hint"],
                fallback_kind=source["fallback_kind"],
                fallback_base_url=source["fallback_base_url"],
            ),
            owner,
            production=False,
        )
        next_version = await owner.fetchval(
            "SELECT row_version FROM bag.sources WHERE source_id=$1", source_id
        )
        assert next_version == trigger_version + 1, (
            "source-upsert CLI plus the row-version trigger must increment exactly once"
        )
        try:
            await acceptor.fetchrow(
                "SELECT * FROM bag.accept_capability_observation($1, $2::uuid, $3::bigint)",
                source_id,
                race_request,
                race_observation,
            )
        except asyncpg.PostgresError as exc:
            assert exc.sqlstate == "P0001"
            assert "changed after observation" in str(exc)
        else:
            raise AssertionError("acceptor accepted an observation for an obsolete source row_version")

        # Force a same-request pending observation past its five-minute validity window. A
        # fresh writer call must replace it with a new identity and the acceptor must accept it.
        retry_request = uuid.uuid4()
        stale_observation = await record(
            retry_request, next_version, initial["metadata_fingerprint"]
        )
        updated = await owner.execute(
            """UPDATE bag.capability_observations
               SET observed_at=clock_timestamp()-interval '6 minutes'
               WHERE source_id=$1 AND request_id=$2""",
            source_id,
            retry_request,
        )
        assert updated == "UPDATE 1"
        fresh_observation = await record(
            retry_request, next_version, initial["metadata_fingerprint"]
        )
        assert fresh_observation != stale_observation
        accepted = await acceptor.fetchrow(
            "SELECT * FROM bag.accept_capability_observation($1, $2::uuid, $3::bigint)",
            source_id,
            retry_request,
            fresh_observation,
        )
        assert accepted is not None and accepted["drift_status"] == "STABLE"

        # The app may read only the exact accepted identity. Wrong request/observation IDs and
        # a superseded identity return no row even while the source capability status is stable.
        assert [row["drift_status"] for row in await read(retry_request, fresh_observation)] == ["STABLE"]
        assert await read(uuid.uuid4(), fresh_observation) == []
        assert await read(retry_request, fresh_observation + 1) == []
        assert await owner.fetchval(
            "SELECT drift_status FROM bag.source_capabilities WHERE source_id=$1", source_id
        ) == "STABLE"

        superseding_request = uuid.uuid4()
        superseding_observation = await record(
            superseding_request, next_version, initial["metadata_fingerprint"]
        )
        assert superseding_observation != fresh_observation
        assert await read(retry_request, fresh_observation) == []
        assert await read(superseding_request, superseding_observation) == []
        assert await owner.fetchval(
            "SELECT drift_status FROM bag.source_capabilities WHERE source_id=$1", source_id
        ) == "STABLE"
    finally:
        await app.close()
        await acceptor.close()
        await writer.close()
        await owner.close()


def test_M2_app_cannot_forge_stable_capability_observation(e2e_env, world, evidence):
    world.need("source", "caps")
    source_id = world.source_id

    # The actual application login has neither privileged routine nor direct status mutation.
    assert evidence.scalar(
        "SELECT has_function_privilege(current_user, $1::regprocedure, 'EXECUTE')",
        WRITER_SIGNATURE,
        role="app",
    ) is False
    assert evidence.scalar(
        "SELECT has_function_privilege(current_user, $1::regprocedure, 'EXECUTE')",
        ACCEPTOR_SIGNATURE,
        role="app",
    ) is False
    assert evidence.scalar(
        "SELECT has_function_privilege(current_user, $1::regprocedure, 'EXECUTE')",
        READER_SIGNATURE,
        role="app",
    ) is True
    for role in ("admin", "control"):
        assert evidence.scalar(
            "SELECT has_function_privilege(current_user, $1::regprocedure, 'EXECUTE')",
            READER_SIGNATURE,
            role=role,
        ) is False
    for sql, args in (
        ("SELECT bag.record_capability_observation('forged', gen_random_uuid(), NULL::bigint, "
         "NULL::text, NULL::text, 'SUPPORTED', 'ODATA_JSON_V3', true, true, "
         "false, false, 0, '{}'::jsonb, '{}'::jsonb)", ()),
        ("SELECT * FROM bag.accept_capability_observation('forged', gen_random_uuid(), 1)", ()),
        ("UPDATE bag.source_capabilities SET drift_status='STABLE' WHERE source_id=$1", (source_id,)),
    ):
        outcome = attempt_sql(e2e_env, "app", sql, *args)
        assert outcome[:2] == ("error", "42501"), f"app privilege boundary allowed SQL: {outcome}"

    # A caller may send arbitrary fields to the Admin route; only the observer's live probe
    # result may become the accepted observation.
    probe = expect(world.pa.post("/admin/v1/source-probes", {
        "base_url": e2e_env.fake1c_url,
        "username_secret_ref": "FAKE1C_USERNAME",
        "password_secret_ref": "FAKE1C_PASSWORD",
    }), 200, "independent live source probe")
    fabricated_fingerprint = "a" * 64
    refreshed = expect(world.pa.post(
        f"/admin/v1/sources/{source_id}/capability-refresh",
        {"reason": "M2 boundary refresh", "metadata_fingerprint": fabricated_fingerprint,
         "metadata_supported": True, "entity_set_count": 999999},
    ), 200, "authorized observer refresh")
    assert refreshed.body["metadata_fingerprint"] == probe.body["capabilities"]["metadata_fingerprint"]
    assert refreshed.body["metadata_fingerprint"] != fabricated_fingerprint

    row = evidence.one(
        "SELECT request_id, observation_id, metadata_fingerprint, observed_by, accepted_by, "
        "accepted_at FROM bag.capability_observations WHERE source_id=$1",
        source_id,
        role="owner",
    )
    assert row is not None
    assert row["metadata_fingerprint"] == probe.body["capabilities"]["metadata_fingerprint"]
    assert row["observed_by"] == "business_ai_capability_writer_login"
    assert row["accepted_by"] == "business_ai_capability_acceptor_login"
    assert row["accepted_at"] is not None

    # The private observer API rejects capability-shaped caller input; it accepts only the
    # source and request identity and independently resolves/probes the registered source.
    observer_url = f"http://{e2e_env.raw['host']}:{e2e_env.raw['ports']['capability_observer']}"
    observer_response = httpx.post(
        observer_url + "/internal/v1/observe-capabilities",
        headers={
            "x-capability-worker-token": e2e_env.secrets["capability_worker_api_token"],
            "Authorization": f"Bearer {world.idp.token('platform_admin', audience='admin')}",
        },
        json={"source_id": source_id, "request_id": str(uuid.uuid4()),
              "metadata_fingerprint": fabricated_fingerprint, "metadata_supported": True},
        trust_env=False,
        timeout=10,
    )
    assert observer_response.status_code == 422, observer_response.text[:300]

    # An acceptor invocation must match all three provenance keys. Mismatches fail without
    # changing the already accepted source state.
    acceptor_url = f"http://{e2e_env.raw['host']}:{e2e_env.raw['ports']['capability_acceptor']}"
    acceptor_headers = {
        "x-capability-worker-token": e2e_env.secrets["capability_acceptor_api_token"]
    }
    for candidate in (
        {"source_id": source_id + "-wrong", "request_id": str(row["request_id"]),
         "observation_id": row["observation_id"]},
        {"source_id": source_id, "request_id": str(uuid.uuid4()),
         "observation_id": row["observation_id"]},
        {"source_id": source_id, "request_id": str(row["request_id"]),
         "observation_id": row["observation_id"] + 1},
    ):
        response = httpx.post(
            acceptor_url + "/internal/v1/accept-capability-observation",
            headers=acceptor_headers, json=candidate, trust_env=False, timeout=10,
        )
        assert response.status_code >= 400, response.text[:300]
    current = evidence.one(
        "SELECT drift_status, metadata_fingerprint FROM bag.source_capabilities WHERE source_id=$1",
        source_id,
    )
    assert current["metadata_fingerprint"] == row["metadata_fingerprint"]

    # If the acceptor boundary is unavailable, refresh fails and the accepted capability row
    # remains unchanged even though the writer may have recorded a pending observation.
    before = dict(current)
    with acceptor_unavailable(e2e_env):
        unavailable = world.pa.post(
            f"/admin/v1/sources/{source_id}/capability-refresh",
            {"reason": "M2 acceptor unavailable"},
        )
        assert unavailable.status >= 400, unavailable.describe()
        after = evidence.one(
            "SELECT drift_status, metadata_fingerprint FROM bag.source_capabilities WHERE source_id=$1",
            source_id,
        )
        assert after == before

    asyncio.run(_exercise_source_version_and_readback(e2e_env, source_id))
