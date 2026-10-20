"""S13 migration-025/026 checkpoint suffix E2E over a disposable PostgreSQL cluster.

Run directly after coding is complete:
    .venv/Scripts/python.exe tests/phase2/test_s13_checkpoint_suffix_e2e.py

The database and migration chain are real. Checkpoint signer/sink are authenticated test doubles,
and malformed suffixes are adapter fault-injections around the real SQL reader.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from _pg_harness import disposable_cluster, throwaway_db
from test_change_ledger_sql import C, T, L, _setup
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord, FakeSigner, FakeVerifier, InMemoryCheckpointSink,
)
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    LifecycleCoordinator, LifecycleReason, LifecycleStatus,
)
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"
POST_BASE_MIGRATIONS = (
    "019_ed25519_action_only.sql", "020_kill_switch_recovery_guard.sql",
    "021_ed25519_consumer_cutover.sql", "022_lifecycle_epoch_fence.sql",
    "023_lifecycle_activation_cap.sql", "024_restore_caller_lock_timeout.sql",
    "025_lifecycle_checkpoint_suffix.sql", "026_lifecycle_checkpoint_payload_minimization.sql",
)


async def apply(conn, filename: str) -> None:
    raw = (MIGRATIONS / filename).read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                       hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))
    print(f"PROGRESS: applied {filename}", flush=True)


class LatestSink(InMemoryCheckpointSink):
    """In-memory test sink with an authenticated latest record for this test scope."""


class SuffixOverride:
    def __init__(self, ledger, suffix):
        self.ledger, self.suffix = ledger, suffix

    async def verify_chain(self, scope):
        return await self.ledger.verify_chain(scope)

    async def lifecycle_checkpoint_suffix(self, scope, checkpoint_seq, checkpoint_hash, limit=128):
        return self.suffix


def coordinator(ledger, sink, verifier):
    return LifecycleCoordinator(ledger, sink, verifier, dependency_timeout_seconds=10)


async def signed_record(ledger, scope, sink, signer):
    head = await ledger.ledger_head(scope)
    signed_at = datetime.now(UTC)
    unsigned = CheckpointRecord(scope.tenant_id, scope.company_id, int(head["seq"]),
                                head["head_hash"], signed_at, signer.key_id, "",
                                sink.sink_id, sink.kind)
    record = CheckpointRecord(**{**unsigned.__dict__,
                                 "signature": signer.sign(unsigned.signing_payload())})
    await sink.write(record)
    return record


async def suffix_with_temporary_payload(db, ledger, scope, event, anchor, payload):
    """Corrupt one payload in the owned throwaway DB, read the sanitized API result, restore it."""
    event_id = event["event_id"]
    original = await db.conn.fetchval(
        "SELECT payload::text FROM change_ledger.events WHERE event_id=$1::uuid", event_id)
    assert original is not None, event_id

    async def write_payload(serialized: str) -> None:
        await db.conn.execute("SET session_replication_role = replica")
        try:
            await db.conn.execute(
                "UPDATE change_ledger.events SET payload=$2::jsonb WHERE event_id=$1::uuid",
                event_id, serialized)
        finally:
            await db.conn.execute("SET session_replication_role = origin")

    # The fixture is a dedicated disposable database; bypass append-only triggers only for this
    # malformed-row probe. The original signed payload is restored before any further preflight.
    try:
        await write_payload(json.dumps(payload))
        return await ledger.lifecycle_checkpoint_suffix(scope, anchor.seq, anchor.head_hash)
    finally:
        await write_payload(original)


def assert_not_ready(result, reason, suffix_count=None):
    assert result.status is LifecycleStatus.NOT_READY, result
    assert result.reason is reason, result
    if suffix_count is not None:
        assert result.suffix_event_count == suffix_count, result


async def journey(db) -> None:
    scope = Scope(T, C)
    actor_map = {"worker": "clt_wrk", "auditor": "clt_aud"}
    ledger = SqlChangeLedger(db.conn, actor_map)
    signer, verifier = FakeSigner("s13-e2e"), FakeVerifier()
    sink = LatestSink("s13-e2e-disposable")
    fixture = L(db)

    # Empty suffix: real chain verification, authenticated latest checkpoint, and SQL adapter.
    empty_change = await fixture.propose(request_id="s13-empty-suffix")
    empty_head = await ledger.ledger_head(scope)
    empty_record = await signed_record(ledger, scope, sink, signer)
    assert empty_record.seq == empty_head["seq"]
    event_count_before = await db.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C)
    empty_result = await coordinator(ledger, sink, verifier).preflight(scope)
    assert_not_ready(empty_result, LifecycleReason.SHARED_FENCE_UNAVAILABLE, 0)
    assert empty_result.suffix_head_seq == empty_record.seq
    empty_suffix = await ledger.lifecycle_checkpoint_suffix(scope, empty_record.seq,
                                                            empty_record.head_hash)
    assert empty_suffix["events"] == [] and empty_suffix["anchor_matches"] is True
    assert "head_hash" not in empty_suffix
    assert await db.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C
    ) == event_count_before, "empty suffix read mutated the event log"
    print("PASS: authenticated empty suffix is read-only and remains NOT_READY/SHARED_FENCE_UNAVAILABLE")

    # Produce a genuine terminal T13 event via existing SQL-backed test fixture flows.
    change_id, token, call_id = await fixture.dispatched(request_id="s13-t13-suffix", base="base-2")
    assert await fixture.complete(change_id, token["generation"], "SUCCESS") == "APPLIED"
    # T13 emits three evidence events followed by VERIFY_VERIFIED. Anchor after evidence so the
    # only event in the suffix is the actual terminal T13 event.
    verification_ids = [
        await fixture.evidence(change_id, kind, {"matches": True}, role="clt_wrk",
                               gen=token["generation"], call_id=call_id)
        for kind in ("FIELD", "MOVEMENT", "VERSION")
    ]
    t13_anchor = await signed_record(ledger, scope, sink, signer)
    assert await fixture.call("clt_wrk", "verify_signed", change_id, *verification_ids) == "VERIFIED"
    count_before = await db.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C)
    t13_result = await coordinator(ledger, sink, verifier).preflight(scope)
    assert_not_ready(t13_result, LifecycleReason.SHARED_FENCE_UNAVAILABLE, 1)
    assert t13_result.suffix_head_seq == t13_anchor.seq + 1
    actual_suffix = await ledger.lifecycle_checkpoint_suffix(scope, t13_anchor.seq,
                                                             t13_anchor.head_hash)
    assert "head_hash" not in actual_suffix
    assert [event["event_type"] for event in actual_suffix["events"]] == ["VERIFY_VERIFIED"]
    t13_event = actual_suffix["events"][0]
    assert "hash" not in t13_event
    assert "payload" not in t13_event
    assert t13_event["payload_found"] is None
    assert t13_event["payload_nonempty"] is True
    assert await db.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C
    ) == count_before, "T13 suffix read mutated the event log"
    print("PASS: real terminal VERIFY_VERIFIED/T13 suffix remains NOT_READY/SHARED_FENCE_UNAVAILABLE")

    # Build one real bounded response, then inject malformed/unsupported tails at the adapter
    # boundary to exercise the classifier without fabricating database rows.
    base = actual_suffix
    tail_event = base["events"][0]

    def changed(**updates):
        value = {**base, "events": [dict(tail_event)]}
        value.update(updates)
        return value

    cases = [
        ("explicit checkpoint-required event", LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT,
         changed(events=[{**tail_event, "event_type": "APPROVED"}])),
        ("unsupported event", LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED,
         changed(events=[{**tail_event, "event_type": "UNRECOGNIZED_EVENT",
                         "payload_found": None, "payload_nonempty": False}])),
        ("RESOLVE_UNKNOWN without found=false proof", LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED,
         changed(events=[{**tail_event, "event_type": "RESOLVE_UNKNOWN",
                         "payload_found": True, "payload_nonempty": False}])),
        ("RESOLVE_UNKNOWN with found=false proof", LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT,
         changed(events=[{**tail_event, "event_type": "RESOLVE_UNKNOWN",
                         "payload_found": False, "payload_nonempty": False}])),
        ("raw payload contract regression", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(events=[{**tail_event, "payload": {"sensitive": "must-not-cross"}}])),
        ("head hash response regression", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(head_hash=t13_anchor.head_hash)),
        ("per-event hash response regression", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(events=[{**tail_event, "hash": "a" * 64}])),
        ("empty T13 payload summary", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(events=[{**tail_event, "payload_nonempty": False}])),
        ("foreign/non-ancestor anchor", LifecycleReason.CHECKPOINT_NOT_ANCESTOR,
         changed(anchor_matches=False)),
        ("foreign scope response", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(tenant_id="OTHER_TENANT")),
        ("oversized/truncated suffix", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(has_more=True)),
        ("truncated sequence", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(events=[{**tail_event, "seq": tail_event["seq"] + 1}])),
    ]
    for label, expected, suffix in cases:
        result = await coordinator(SuffixOverride(ledger, suffix), sink, verifier).preflight(scope)
        assert_not_ready(result, expected)
        print(f"PASS: rejects {label} as {expected.value}")

    # Verify SQL summaries for non-object VERIFY payloads without exposing the underlying value.
    for label, malformed_payload in (
        ("scalar", "S13_SECRET_VERIFY_SCALAR"),
        ("array", ["S13_SECRET_VERIFY_ARRAY"]),
    ):
        sanitized = await suffix_with_temporary_payload(
            db, ledger, scope, tail_event, t13_anchor, malformed_payload)
        event = sanitized["events"][0]
        assert event["payload_nonempty"] is False, event
        assert "payload" not in event and "payload_found" in event, event
        assert "S13_SECRET_VERIFY_" not in repr(sanitized), sanitized
        rejected_suffix = changed(events=[{**tail_event, "payload_nonempty": False}])
        result = await coordinator(SuffixOverride(ledger, rejected_suffix), sink, verifier).preflight(scope)
        assert_not_ready(result, LifecycleReason.CHECKPOINT_SUFFIX_INVALID)
        print(f"PASS: {label} VERIFY payload is summarized as empty, undisclosed, and NOT_READY")

    # A signed RESOLVE_UNKNOWN event normally carries a boolean. Probe malformed found values in
    # the disposable row and verify SQL returns NULL only, while the classifier rejects it.
    unknown_change, unknown_token, unknown_call = await fixture.unknown(
        request_id="s13-malformed-found", base="base-3")
    observation_id = await fixture.observation(unknown_change, True)
    unknown_anchor = await signed_record(ledger, scope, sink, signer)
    assert await fixture.call("clt_wrk", "resolve_unknown_signed", unknown_change, observation_id,
                              None, True, True) == "TRIAGE_REQUIRED"
    unknown_suffix = await ledger.lifecycle_checkpoint_suffix(
        scope, unknown_anchor.seq, unknown_anchor.head_hash)
    assert len(unknown_suffix["events"]) == 1
    unknown_event = unknown_suffix["events"][0]
    assert unknown_event["event_type"] == "RESOLVE_UNKNOWN"
    for label, found_value in (
        ("object", {"secret": "S13_SECRET_FOUND_OBJECT"}),
        ("string", "S13_SECRET_FOUND_STRING"),
    ):
        sanitized = await suffix_with_temporary_payload(
            db, ledger, scope, unknown_event, unknown_anchor,
            {"found": found_value, "marker": "S13_SECRET_FOUND_MARKER"})
        event = sanitized["events"][0]
        assert event["payload_found"] is None, event
        assert event["payload_nonempty"] is False, event
        assert "payload" not in event, event
        assert "S13_SECRET_FOUND_" not in repr(sanitized), sanitized
        rejected_events = [{**unknown_event, "payload_found": None}]
        rejected = {**unknown_suffix, "events": rejected_events}
        result = await coordinator(SuffixOverride(ledger, rejected), sink, verifier).preflight(scope)
        assert_not_ready(result, LifecycleReason.CHECKPOINT_SUFFIX_INVALID)
        print(f"PASS: object/string RESOLVE_UNKNOWN found is summarized as NULL, undisclosed, and NOT_READY ({label})")

    # Verify the SECURITY DEFINER wrapper is executable only for worker/auditor and returns no
    # data to other runtime roles. Direct execution is scoped as an application role in a tx.
    for role in ("clt_wrk", "clt_aud"):
        async with db.conn.transaction():
            await db.conn.execute(f'SET LOCAL ROLE "{role}"')
            await db.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
            value = await db.conn.fetchval(
                "SELECT change_ledger.lifecycle_checkpoint_suffix($1,$2,$3,$4,128)",
                T, C, t13_anchor.seq, t13_anchor.head_hash)
            if isinstance(value, str):
                value = json.loads(value)
            assert value["anchor_matches"] is True
            assert "head_hash" not in value
            for event in value["events"]:
                assert "payload" not in event
                assert "payload_found" in event and "payload_nonempty" in event
                assert "hash" not in event
    async with db.conn.transaction():
        await db.conn.execute('SET LOCAL ROLE "clt_alice"')
        await db.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        try:
            await db.conn.fetchval(
                "SELECT change_ledger.lifecycle_checkpoint_suffix($1,$2,$3,$4,128)",
                T, C, t13_anchor.seq, t13_anchor.head_hash)
        except Exception as error:
            assert "permission denied" in str(error).lower(), error
        else:
            raise AssertionError("requester unexpectedly executed checkpoint suffix function")
    print("PASS: worker/auditor execute; requester denied by PostgreSQL privileges")

    assert await db.conn.fetchval("SELECT count(*) FROM living.schema_migrations WHERE version='026'") == 1
    assert (empty_change is not None and call_id is not None and unknown_token is not None
            and unknown_call is not None)


async def main() -> int:
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    async with disposable_cluster() as (dsn, container_name, token):
        async with throwaway_db(dsn, seed=False) as db:
            for filename in POST_BASE_MIGRATIONS[:3]:
                await apply(db.conn, filename)
            await _setup(db.conn)
            await db.conn.execute("SELECT change_ledger.add_role_scope('ledger_owner',$1,$2)", T, C)
            for filename in POST_BASE_MIGRATIONS[3:]:
                await apply(db.conn, filename)
            chain = await db.conn.fetch("SELECT version FROM living.schema_migrations WHERE version >= '019'")
            versions = {row["version"] for row in chain}
            assert {"019", "020", "021", "022", "023", "024", "025", "026"} <= versions, versions
            print(f"PROGRESS: PostgreSQL {await db.conn.fetchval('SHOW server_version')} ready", flush=True)
            await journey(db)
    from _pg_harness import docker
    assert docker("inspect", container_name, timeout=30).returncode != 0, "owned container remains after cleanup"
    print(f"Suite: PASS — S13 checkpoint suffix E2E; container={container_name}")
    print(f"CLEANUP: owned container absent; ownership token={token[:8]}")
    print("LIMIT: authenticated sink/signer are test doubles; no external anti-rollback provider or READY admission is proven")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
