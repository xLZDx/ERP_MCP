"""S13 migration 020 operator recovery journey through the SQL application adapter.

Run directly, never through pytest:
    .venv/Scripts/python.exe tests/phase2/s13_migration020_e2e.py

The runner owns one loopback-only disposable PostgreSQL container, applies migrations 001-020,
and verifies that an OFF request remains STOP while sweep work or recovery holds remain. It then
repairs/retries the failed item, resolves the pending call, reaches OFF, and checks repeated-OFF
compatibility without another sweep.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from _pg_harness import disposable_cluster, docker, throwaway_db
from test_change_ledger_sql import C, L, ORG, T, _setup
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"
M019 = MIGRATIONS / "019_ed25519_action_only.sql"
M020 = MIGRATIONS / "020_kill_switch_recovery_guard.sql"


async def _apply(conn, path: Path) -> None:
    import hashlib

    raw = path.read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                       hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


def _payload(row) -> dict:
    return row if isinstance(row, dict) else json.loads(row)


async def _journey(conn) -> dict[str, str]:
    fixtures = L(type("Db", (), {"conn": conn})())
    scope = Scope(T, C)
    api = SqlChangeLedger(conn, actors={"operator": "clt_dave"})

    # One claimed item will fail during the STOP sweep, and one dispatched item has an expired
    # hard deadline so the same sweep records real recovery progress and retains unresolved work.
    bad_base = "s13-e2e-poison"
    await conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class) "
        "VALUES($1,$2,$3,$4,'DISPOSABLE_CLONE')", T, C, bad_base, ORG)
    bad = await fixtures.approved(request_id="s13-e2e-poison", base=bad_base)
    bad_token = await fixtures.claimed(bad)
    good, _, _ = await fixtures.dispatched(request_id="s13-e2e-deadline", base="base-1")
    await conn.execute(
        "UPDATE change_ledger.call_deadlines SET hard_deadline_at=now()-interval '1 second' "
        "WHERE change_id=$1", good)

    poison_function = "s13_e2e_poison_claim"
    poison_trigger = "s13_e2e_poison_claim_trigger"
    await conn.execute(
        f"CREATE FUNCTION public.{poison_function}() RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN IF OLD.change_id='{bad}'::uuid AND NEW.authorization_state='APPROVED' "
        "THEN RAISE EXCEPTION 'S13_E2E_POISON'; END IF; RETURN NEW; END $$")
    await conn.execute(
        f"CREATE TRIGGER {poison_trigger} BEFORE UPDATE ON change_ledger.records "
        f"FOR EACH ROW EXECUTE FUNCTION public.{poison_function}()")

    assert await api.kill_switch(scope, "STOP_ADMIT") == "STOP_ADMIT"
    assert await api.kill_switch(scope, "OFF") == "STOP_ADMIT"

    first_event = await conn.fetchrow(
        "SELECT seq,payload FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND event_type='KILL_SWITCH' ORDER BY seq DESC LIMIT 1", T, C)
    first_payload = _payload(first_event["payload"])
    assert first_payload["outcome"] == "BLOCKED", first_payload
    assert first_payload["requested_mode"] == "OFF" and first_payload["effective_mode"] == "STOP_ADMIT"
    assert first_payload["failed_count"] == 1 and first_payload["has_unresolved"] is True, first_payload
    assert first_payload["run_id"], first_payload
    sweep_run = await conn.fetchrow(
        "SELECT run_id,changed,finished_at FROM change_ledger.sweep_runs WHERE run_id=$1",
        first_payload["run_id"])
    assert sweep_run and sweep_run["finished_at"] is not None, "blocked request has no committed sweep run"
    failure = await conn.fetchrow(
        "SELECT failures,last_sqlstate,last_error FROM change_ledger.sweep_failures "
        "WHERE tenant_id=$1 AND company_id=$2 AND subject_id=$3 AND stage='T5x'", T, C, bad)
    assert failure and failure["failures"] == 1 and failure["last_sqlstate"] == "P0001"
    assert "S13_E2E_POISON" in failure["last_error"]
    assert await conn.fetchval(
        "SELECT mode FROM change_ledger.kill_switch_state WHERE tenant_id=$1 AND company_id=$2", T, C
    ) == "STOP_ADMIT"
    unknown = await fixtures.rec(good)
    assert unknown["execution_state"] == "APPLY_UNKNOWN"
    assert await conn.fetchval(
        "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", bad_token["token_id"]
    ) == "ISSUED"

    # Repair the deterministic fixture fault. The retry clears T5x and supersedes the claim, but
    # STOP remains while the independently unresolved dispatched call still needs operator proof.
    await conn.execute(f"DROP TRIGGER {poison_trigger} ON change_ledger.records")
    await conn.execute(f"DROP FUNCTION public.{poison_function}()")
    assert await api.kill_switch(scope, "OFF") == "STOP_ADMIT"
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.sweep_failures WHERE tenant_id=$1 AND company_id=$2 "
        "AND subject_id=$3 AND stage='T5x'", T, C, bad) == 0
    assert await conn.fetchval(
        "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", bad_token["token_id"]
    ) == "SUPERSEDED"
    retry_event = await conn.fetchrow(
        "SELECT payload FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND event_type='KILL_SWITCH' ORDER BY seq DESC LIMIT 1", T, C)
    retry_payload = _payload(retry_event["payload"])
    assert retry_payload["outcome"] == "BLOCKED" and retry_payload["failed_count"] == 0
    assert retry_payload["has_unresolved"] is True

    assert await fixtures.resolve_unknown(good, False, proof="b") == "FAILED_APPLY"
    assert await api.kill_switch(scope, "OFF") == "OFF"
    assert await conn.fetchval(
        "SELECT mode FROM change_ledger.kill_switch_state WHERE tenant_id=$1 AND company_id=$2", T, C
    ) == "OFF"

    run_count = await conn.fetchval(
        "SELECT count(*) FROM change_ledger.sweep_runs WHERE tenant_id=$1 AND company_id=$2", T, C)
    assert await api.kill_switch(scope, "OFF") == "OFF"
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.sweep_runs WHERE tenant_id=$1 AND company_id=$2", T, C
    ) == run_count, "repeated OFF compatibility call unexpectedly started another sweep"

    return {
        "journey": "SqlChangeLedger.kill_switch over PostgreSQL migrations 001-020",
        "first_off": "BLOCKED; STOP retained; failed T5x plus unresolved call recorded",
        "repair_retry": "T5x failure cleared and claim superseded; STOP retained until call resolution",
        "clear_off": "OFF only after unresolved work resolved",
        "repeated_off": "OFF is a no-op and starts no sweep",
        "progress": f"sweep_run={first_payload['run_id']}, changed={sweep_run['changed']}",
    }


async def main() -> int:
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    container_name = image_id = volume_name = None
    async with disposable_cluster() as (dsn, container_name, _token):
        identity = docker("inspect", "--format", "{{.Config.Image}}|{{.Image}}|{{range .Mounts}}{{if eq .Type \"volume\"}}{{.Name}}{{end}}{{end}}",
                          container_name, timeout=30)
        assert identity.returncode == 0, identity.stderr.decode(errors="replace")
        image_tag, image_id, volume_name = identity.stdout.decode().strip().split("|", 2)
        async with throwaway_db(dsn) as db:
            await _setup(db.conn)
            await _apply(db.conn, M019)
            await _apply(db.conn, M020)
            for version in ("019", "020"):
                count = await db.conn.fetchval(
                    "SELECT count(*) FROM living.schema_migrations WHERE version=$1", version)
                assert count == 1, f"migration {version} record count is {count}"
            result = await _journey(db.conn)

    # The fixture context verified the random ownership label before using `docker rm --volumes`.
    # Confirm the exact container and its anonymous database volume are absent after teardown.
    assert docker("inspect", container_name, timeout=30).returncode != 0, "owned container remains after cleanup"
    assert docker("volume", "inspect", volume_name, timeout=30).returncode != 0, "owned anonymous volume remains"
    digest = docker("image", "inspect", image_tag, "--format", "{{.Id}}", timeout=30)
    assert digest.returncode == 0 and digest.stdout.decode().strip() == image_id
    print(f"E2E: {result}")
    print(f"CLEANUP: container={container_name} absent; anonymous_volume={volume_name} absent")
    print(f"IMAGE: {image_tag} {image_id}")
    print(f"PASS: S13 STOP/OFF recovery journey on migrations 001-020, owned container {container_name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except pytest.skip.Exception as unavailable:
        print(f"NOT_RUN: {unavailable}")
        raise SystemExit(0)
