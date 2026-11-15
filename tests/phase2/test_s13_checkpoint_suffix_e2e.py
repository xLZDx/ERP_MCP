"""S13 migration-025–029 checkpoint suffix E2E over a disposable PostgreSQL cluster.

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
from uuid import uuid4

from _pg_harness import disposable_cluster, throwaway_db
from test_change_ledger_sql import C, T, L, _setup
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointKeyAuthorization, CheckpointKeyAuthorizationBasis,
    CheckpointLatestnessEvidence, CheckpointRecord, FakeSigner, FakeVerifier,
    InMemoryCheckpointSink, checkpoint_identity,
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
    "027_private_writer_admission_schema.sql", "028_refusal_codes_parity.sql",
    "029_scoped_operator_reads.sql",
)


async def apply(conn, filename: str) -> None:
    raw = (MIGRATIONS / filename).read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                       hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))
    print(f"PROGRESS: applied {filename}", flush=True)


class LatestSink(InMemoryCheckpointSink):
    """TEST sink for exact-scope latest selection; it cannot authenticate anti-rollback freshness."""

    def __init__(self, sink_id: str):
        super().__init__(sink_id)
        self.write_calls = 0
        self.read_back_calls = 0
        self.latest_calls = 0

    async def write(self, record):
        self.write_calls += 1
        await super().write(record)

    async def read_back(self, scope, seq):
        self.read_back_calls += 1
        return await super().read_back(scope, seq)

    async def latest(self, scope):
        self.latest_calls += 1
        return await super().latest(scope)


class SuffixOverride:
    def __init__(self, ledger, suffix):
        self.ledger, self.suffix = ledger, suffix

    async def verify_chain(self, scope):
        return await self.ledger.verify_chain(scope)

    async def lifecycle_checkpoint_suffix(self, scope, checkpoint_seq, checkpoint_hash, limit=128):
        return self.suffix


class SyntheticLatestnessAuthority:
    """Test-only claim for the in-memory sink; never evidence of external freshness."""

    is_test_double = True

    def __init__(self, sink):
        self.sink = sink

    async def latest_checkpoint(self, scope):
        record = await self.sink.latest(scope)
        if record is None:
            return None, CheckpointLatestnessEvidence(
                scope.tenant_id, scope.company_id, None, "synthetic-test-authority",
                0, None, None,
            )
        digest = checkpoint_identity(record)
        return record, CheckpointLatestnessEvidence(
            scope.tenant_id, scope.company_id, digest, "synthetic-test-authority",
            max(1, record.seq), str(uuid4()),
            hashlib.sha256(digest.encode("ascii")).hexdigest(),
        )


class SyntheticKeyAuthority:
    """Test-only active-key assertion for exercising the suffix reader boundary."""

    is_test_double = True

    def __init__(self, verifier):
        self.verifier = verifier

    async def authorize_checkpoint(self, scope, record):
        digest = checkpoint_identity(record)
        return CheckpointKeyAuthorization(
            scope.tenant_id, scope.company_id, record.key_id,
            self.verifier.public_key_digest(record.key_id), digest,
            "synthetic-test-key-authority", 1, "test-key-event", "test-only-v1",
            CheckpointKeyAuthorizationBasis.ACTIVE,
        )


def coordinator(ledger, sink, verifier):
    return LifecycleCoordinator(
        ledger, verifier,
        key_authority=SyntheticKeyAuthority(verifier),
        latestness_authority=SyntheticLatestnessAuthority(sink),
        dependency_timeout_seconds=10,
    )


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
    # Migration 027 has moved this disposable schema onto the S13 service contract. This
    # scenario still stops at diagnostic preflight and never exercises a writer/READY path.
    ledger = SqlChangeLedger(db.conn, actor_map, private_writer_schema_enabled=True)
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

    # Append an approval after a TEST checkpoint. This exercises a real SQL suffix that must
    # remain NOT_READY without beginning an apply, dispatching a physical write, or entering READY.
    change_id = await fixture.validated(request_id="s13-approved-suffix", base="base-2")
    nonce = await fixture.call("clt_bob", "issue_approval_nonce", change_id)
    approval_digest = await fixture.approval_digest(change_id)
    suffix_anchor = await signed_record(ledger, scope, sink, signer)
    await fixture.call("clt_bob", "approve", change_id, nonce, approval_digest)
    count_before = await db.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C)
    suffix_result = await coordinator(ledger, sink, verifier).preflight(scope)
    assert_not_ready(suffix_result, LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT, 1)
    assert suffix_result.suffix_head_seq == suffix_anchor.seq + 1
    actual_suffix = await ledger.lifecycle_checkpoint_suffix(scope, suffix_anchor.seq,
                                                              suffix_anchor.head_hash)
    assert "head_hash" not in actual_suffix
    assert [event["event_type"] for event in actual_suffix["events"]] == ["APPROVED"]
    suffix_event = actual_suffix["events"][0]
    assert "hash" not in suffix_event
    assert "payload" not in suffix_event
    assert suffix_event["payload_found"] is None
    assert suffix_event["payload_nonempty"] is False
    assert await db.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C
    ) == count_before, "checkpoint suffix read mutated the event log"
    print("PASS: real APPROVED suffix requires a checkpoint; diagnostic path performs no apply or dispatch")

    # A cryptographically valid TEST checkpoint that is ahead of the disposable PostgreSQL
    # database's current ledger head is not an ancestor. The real SQL suffix reader must reject it; preflight remains
    # read-only and cannot recover, authorize a writer, or dispatch.
    restored_head = await ledger.ledger_head(scope)
    future_seq = int(restored_head["seq"]) + 1
    ahead_sink = LatestSink("s13-ahead-anchor-disposable")
    future_unsigned = CheckpointRecord(
        scope.tenant_id, scope.company_id, future_seq, "f" * 64, datetime.now(UTC),
        signer.key_id, "", ahead_sink.sink_id, ahead_sink.kind,
    )
    future_record = CheckpointRecord(**{
        **future_unsigned.__dict__,
        "signature": signer.sign(future_unsigned.signing_payload()),
    })
    await ahead_sink.write(future_record)
    event_count_before = await db.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
        T, C,
    )
    write_calls_before = ahead_sink.write_calls
    read_back_calls_before = ahead_sink.read_back_calls
    latest_calls_before = ahead_sink.latest_calls
    class RecordingLedger:
        def __init__(self, delegate):
            self.delegate = delegate
            self.calls = []

        async def verify_chain(self, requested_scope):
            self.calls.append("verify_chain")
            return await self.delegate.verify_chain(requested_scope)

        async def lifecycle_checkpoint_suffix(self, requested_scope, checkpoint_seq,
                                              checkpoint_hash, limit=128):
            self.calls.append("lifecycle_checkpoint_suffix")
            return await self.delegate.lifecycle_checkpoint_suffix(
                requested_scope, checkpoint_seq, checkpoint_hash, limit,
            )

    recording_ledger = RecordingLedger(ledger)
    future_result = await coordinator(recording_ledger, ahead_sink, verifier).preflight(scope)
    assert_not_ready(future_result, LifecycleReason.CHECKPOINT_NOT_ANCESTOR)
    assert recording_ledger.calls == ["verify_chain", "lifecycle_checkpoint_suffix"]
    assert ahead_sink.latest_calls == latest_calls_before + 1
    assert ahead_sink.write_calls == write_calls_before, "preflight must not write checkpoints"
    assert ahead_sink.read_back_calls == read_back_calls_before, "preflight must not read back/write checkpoints"
    assert await db.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2",
        T, C,
    ) == event_count_before, "ahead-of-chain anchor check mutated the ledger"
    print("PASS: valid TEST signature on ahead-of-chain anchor is rejected by real PostgreSQL ancestry check; no recovery/writer/dispatch effect")

    # Build one real bounded response, then inject malformed/unsupported tails at the adapter
    # boundary to exercise the classifier without fabricating database rows.
    base = actual_suffix
    tail_event = base["events"][0]
    verify_event = {
        **tail_event,
        "event_type": "VERIFY_VERIFIED",
        "payload_found": None,
        "payload_nonempty": True,
        "record": {
            "execution_state": "APPLIED",
            "verification_state": "VERIFIED",
            "call_ownership": "PROVEN_FINISHED",
            "reservation_state": "CONSUMED",
            "dispatch_state": "DISPATCHED",
        },
    }

    def changed(**updates):
        value = {**base, "events": [dict(verify_event)]}
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
         changed(head_hash=suffix_anchor.head_hash)),
        ("per-event hash response regression", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(events=[{**tail_event, "hash": "a" * 64}])),
        ("empty VERIFY payload summary", LifecycleReason.CHECKPOINT_SUFFIX_INVALID,
         changed(events=[{**verify_event, "payload_nonempty": False}])),
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
            db, ledger, scope, tail_event, suffix_anchor, malformed_payload)
        event = sanitized["events"][0]
        assert event["payload_nonempty"] is False, event
        assert "payload" not in event and "payload_found" in event, event
        assert "S13_SECRET_VERIFY_" not in repr(sanitized), sanitized
        rejected_suffix = changed(events=[{**verify_event, "payload_nonempty": False}])
        result = await coordinator(SuffixOverride(ledger, rejected_suffix), sink, verifier).preflight(scope)
        assert_not_ready(result, LifecycleReason.CHECKPOINT_SUFFIX_INVALID)
        print(f"PASS: {label} VERIFY payload is summarized as empty, undisclosed, and NOT_READY")

    # Arrange a hash-chained synthetic RESOLVE_UNKNOWN row directly in the owned disposable DB.
    # This isolates suffix sanitization without opening the writer/dispatch path, which migration
    # 027 intentionally disables for this diagnostic-only scenario.
    unknown_anchor = await signed_record(ledger, scope, sink, signer)
    await db.conn.fetchval(
        "SELECT change_ledger.append_event($1,$2,$3,'RESOLVE_UNKNOWN',$4::jsonb)",
        T, C, change_id, json.dumps({"found": True}),
    )
    unknown_suffix = await ledger.lifecycle_checkpoint_suffix(
        scope, unknown_anchor.seq, unknown_anchor.head_hash)
    assert len(unknown_suffix["events"]) == 1
    unknown_event = unknown_suffix["events"][0]
    assert unknown_event["event_type"] == "RESOLVE_UNKNOWN"
    assert unknown_event["payload_found"] is True
    assert unknown_event["payload_nonempty"] is False
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
                T, C, suffix_anchor.seq, suffix_anchor.head_hash)
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
                T, C, suffix_anchor.seq, suffix_anchor.head_hash)
        except Exception as error:
            assert "permission denied" in str(error).lower(), error
        else:
            raise AssertionError("requester unexpectedly executed checkpoint suffix function")
    print("PASS: worker/auditor execute; requester denied by PostgreSQL privileges")

    assert await db.conn.fetchval("SELECT count(*) FROM living.schema_migrations WHERE version='026'") == 1
    assert empty_change is not None and change_id is not None


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
            assert {"019", "020", "021", "022", "023", "024", "025", "026", "027"} <= versions, versions
            assert await db.conn.fetchval(
                "SELECT to_regclass('change_ledger.refusal_code_registry') IS NOT NULL")
            assert await db.conn.fetchval(
                "SELECT to_regprocedure('change_ledger.list_inflight(text,text,integer,integer)') IS NOT NULL "
                "AND to_regprocedure('change_ledger.operator_status(text,text,uuid)') IS NOT NULL "
                "AND to_regprocedure('change_ledger.budget_snapshot(text,text,uuid,numeric,text)') IS NOT NULL")
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
