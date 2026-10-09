"""R2-US-026 artifact vault: TC076 opaque immutable versions, TC077 evidence needs a real blob,
TC078 current-ACL reads. Pure, deterministic, injected clock and id source."""
from __future__ import annotations

import dataclasses
import hashlib
import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from business_ai_gateway.phase2 import artifact_vault as av
from business_ai_gateway.phase2.artifact_vault import (
    ArtifactRef,
    ArtifactScope,
    ArtifactVault,
    AuditKind,
    Principal,
    PutStatus,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ADMIN = Principal("admin")
ALICE = Principal("alice")
BOB = Principal("bob")
S1 = ArtifactScope("t1", "src1")
S2 = ArtifactScope("t1", "src2")
PDF = "application/pdf"


def make(ids=None, **kw) -> ArtifactVault:
    if ids is None:
        counter = itertools.count(1)
        lock = threading.Lock()

        def src() -> bytes:
            with lock:
                return next(counter).to_bytes(16, "big")
    else:
        it = iter(ids)

        def src() -> bytes:
            return next(it)
    return ArtifactVault(lambda: NOW, id_source=src, admins=["admin"], **kw)


def ready(**kw) -> ArtifactVault:
    v = make(**kw)
    assert v.grant(S1, ALICE, ADMIN) == av.OK
    return v


def put(v, data=b"hello", scope=S1, who=ALICE):
    return v.put(scope, data, who, PDF)


def idb(n: int) -> bytes:
    return bytes([n]) * 16


# ------------------------------------------------------------------ TC076
def test_tc076_ids_are_random_and_not_derived_from_digest():
    a, b = (ArtifactVault(lambda: NOW, admins=["admin"]) for _ in range(2))  # default random ids
    a.grant(S1, ALICE, ADMIN)
    b.grant(S1, ALICE, ADMIN)
    ra, rb = put(a).ref, put(b).ref
    assert ra.digest == rb.digest == hashlib.sha256(b"hello").hexdigest()
    assert ra.version_id != rb.version_id
    assert ra.version_id.startswith("av_")
    assert ra.digest[:8] not in ra.version_id and ra.digest not in ra.version_id


def test_tc076_same_bytes_same_scope_is_idempotent():
    v = ready()
    first, second = put(v), put(v)
    assert first.status is PutStatus.STORED and second.status is PutStatus.DUPLICATE
    assert first.ref == second.ref and second.code == av.DUPLICATE


def test_tc076_same_bytes_other_scope_is_independent_artifact():
    v = ready()
    v.grant(S2, ALICE, ADMIN)
    assert put(v).ref.version_id != put(v, scope=S2).ref.version_id


def test_tc076_different_bytes_new_version_old_ref_keeps_old_bytes():
    v = ready()
    old = put(v, b"v1").ref
    new = put(v, b"v2")
    assert new.status is PutStatus.STORED and new.ref.version_id != old.version_id
    assert v.read(old, ALICE).content == b"v1"
    assert v.read(new.ref, ALICE).content == b"v2"


def test_tc076_no_mutation_api_exposed():
    public = [n for n in dir(ArtifactVault) if not n.startswith("_")]
    banned = ("update", "delete", "overwrite", "remove")
    assert not [n for n in public if any(b in n.lower() for b in banned)]


def test_tc076_refs_and_results_are_frozen():
    ref = put(ready()).ref
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.digest = "x"  # type: ignore[misc]


def test_id_collision_is_refused_not_overwritten():
    v = ready(ids=[idb(1), idb(1)])
    first = put(v, b"one")
    second = put(v, b"two")
    assert second.status is PutStatus.REFUSED and second.code == av.ID_COLLISION
    assert v.read(first.ref, ALICE).content == b"one"


def test_bad_id_source_output_refused():
    for bad in (b"short", "x" * 16, None):
        v = ready(ids=[bad])
        r = put(v)
        assert r.status is PutStatus.REFUSED and r.code == av.ID_SOURCE_INVALID


def test_failing_id_source_refused_without_text():
    def boom():
        raise RuntimeError("secret detail")
    v = ArtifactVault(lambda: NOW, id_source=boom, admins=["admin"])
    v.grant(S1, ALICE, ADMIN)
    r = put(v)
    assert r.code == av.ID_SOURCE_INVALID and "secret" not in repr(r)


# --------------------------------------------------------- input refusals
def test_oversize_empty_and_non_bytes_refused():
    v = ready(max_bytes=4)
    assert put(v, b"12345").code == av.CONTENT_TOO_LARGE
    assert put(v, b"1234").status is PutStatus.STORED
    assert put(v, b"").code == av.EMPTY_CONTENT
    for bad in (bytearray(b"abc"), memoryview(b"abc"), "abc", None, 5):
        assert put(v, bad).code == av.CONTENT_TYPE_REFUSED


def test_bytes_copied_from_bytearray_is_not_aliased():
    v = ready()
    ba = bytearray(b"secret-original")
    ref = put(v, bytes(ba)).ref
    ba[:] = b"X" * 15
    assert v.read(ref, ALICE).content == b"secret-original"


def test_media_type_scope_principal_validation():
    v = ready()
    assert v.put(S1, b"a", ALICE, "application/x-evil").code == av.MEDIA_TYPE_REFUSED
    assert v.put(S1, b"a", ALICE, None).code == av.MEDIA_TYPE_REFUSED  # type: ignore[arg-type]
    assert v.put(ArtifactScope("", "s"), b"a", ALICE, PDF).code == av.INVALID_SCOPE
    assert v.put("S1", b"a", ALICE, PDF).code == av.INVALID_SCOPE  # type: ignore[arg-type]
    assert v.put(S1, b"a", Principal("al\u200bice"), PDF).code == av.INVALID_PRINCIPAL
    assert v.put(S1, b"a", "alice", PDF).code == av.INVALID_PRINCIPAL  # type: ignore[arg-type]
    assert v.put(S1, b"a", BOB, PDF).code == av.UPLOAD_NOT_ALLOWED


def test_uploader_in_other_scope_cannot_put():
    v = ready()
    assert v.put(S2, b"a", ALICE, PDF).code == av.UPLOAD_NOT_ALLOWED


# ------------------------------------------------------------------ TC077
def test_tc077_real_ref_and_digest_is_evidence():
    v = ready()
    ref = put(v).ref
    r = v.verify_evidence(ref, ref.digest, ALICE)
    assert r.valid and r.code == av.OK


def test_tc077_nothing_else_is_evidence_and_codes_are_identical():
    v = ready()
    ref = put(v).ref
    good = ref.digest
    cases = [
        v.verify_evidence(ArtifactRef("av_nonexistent", good, ref.size, S1), good, ALICE),
        v.verify_evidence(ref, "0" * 64, ALICE),
        v.verify_evidence(good, good, ALICE),  # hash-only claim, no ref
        v.verify_evidence(None, good, ALICE),
        v.verify_evidence(ArtifactRef(good, good, ref.size, S1), good, ALICE),  # id guessed from digest
        v.verify_evidence(ArtifactRef("av_" + good[:22], good, ref.size, S1), good, ALICE),
        v.verify_evidence(dataclasses.replace(ref, scope=S2), good, ALICE),
        v.verify_evidence(dataclasses.replace(ref, size=ref.size + 1), good, ALICE),
        v.verify_evidence(dataclasses.replace(ref, digest="f" * 64), good, ALICE),
        v.verify_evidence(ref, None, ALICE),  # type: ignore[arg-type]
        v.verify_evidence(ref, good, BOB),  # no access
        v.verify_evidence(ref, good, None),  # type: ignore[arg-type]
    ]
    assert all(not c.valid for c in cases)
    assert {c.code for c in cases} == {av.NOT_EVIDENCE}


def test_tc077_forged_ref_with_real_digest_and_fake_version():
    v = ready()
    real = put(v).ref
    forged = ArtifactRef("av_AAAAAAAAAAAAAAAAAAAAAA", real.digest, real.size, S1)
    assert not v.verify_evidence(forged, real.digest, ALICE).valid
    assert v.read(forged, ALICE) == v.read(
        ArtifactRef("av_BBBBBBBBBBBBBBBBBBBBBB", real.digest, real.size, S1), ALICE
    )


def test_tc077_valid_evidence_stops_after_revoke():
    v = ready()
    ref = put(v).ref
    v.revoke(S1, ALICE, ADMIN)
    assert not v.verify_evidence(ref, ref.digest, ALICE).valid


# ------------------------------------------------------------------ TC078
def test_tc078_revoke_denies_historical_ref_regrant_restores():
    v = ready()
    old = put(v, b"v1").ref
    put(v, b"v2")
    assert v.read(old, ALICE).allowed
    epoch = v.acl_epoch(S1)
    assert v.revoke(S1, ALICE, ADMIN) == av.OK
    assert v.acl_epoch(S1) == epoch + 1
    denied = v.read(old, ALICE)
    assert not denied.allowed and denied.content is None and denied.code == av.ACCESS_DENIED
    assert v.grant(S1, ALICE, ADMIN) == av.OK
    assert v.read(old, ALICE).content == b"v1"


def test_tc078_other_scope_reader_and_grants_do_not_leak():
    v = ready()
    ref = put(v).ref
    v.grant(S2, BOB, ADMIN)
    unknown = v.read(ArtifactRef("av_zzzzzzzzzzzzzzzzzzzzzz", ref.digest, ref.size, S1), BOB)
    for r in (
        v.read(ref, BOB),
        v.read(dataclasses.replace(ref, scope=S2), BOB),  # tampered scope to the reader's own
    ):
        assert r == unknown and not r.allowed and r.content is None


def test_tc078_acl_changes_are_idempotent_and_admin_only():
    v = make()
    assert v.grant(S1, ALICE, ALICE) == av.ADMIN_REQUIRED
    assert v.grant(S1, ALICE, "admin") == av.ADMIN_REQUIRED  # type: ignore[arg-type]
    assert v.grant(S1, ALICE, ADMIN) == av.OK
    assert v.grant(S1, ALICE, ADMIN) == av.UNCHANGED
    assert v.acl_epoch(S1) == 1
    assert v.revoke(S1, BOB, ADMIN) == av.UNCHANGED
    assert v.revoke(S1, BOB, BOB) == av.ADMIN_REQUIRED
    assert v.grant(ArtifactScope("", ""), ALICE, ADMIN) == av.INVALID_SCOPE
    assert v.grant(S1, Principal(""), ADMIN) == av.INVALID_PRINCIPAL
    assert v.acl_epoch(S1) == 1 and v.acl_epoch(S2) == 0


def test_identity_normalisation_applies_to_principals_and_scopes():
    v = ready()
    ref = put(v).ref
    assert v.read(dataclasses.replace(ref, scope=ArtifactScope(" T1 ", "SRC1")), Principal(" ALICE ")).allowed


# ------------------------------------------------------------------ audit
def test_audit_trail_has_no_content_and_only_normalised_ids():
    v = ready()
    ref = put(v, b"TOP-SECRET-BYTES").ref
    v.read(ref, Principal(" BOB "))
    v.read(ref, ALICE)
    v.revoke(S1, ALICE, ADMIN)
    v.grant(S1, Principal("bad\u200bid"), ADMIN)
    events = v.audit()
    assert isinstance(events, tuple)
    assert [e.kind for e in events] == [
        AuditKind.GRANT, AuditKind.PUT, AuditKind.DENY, AuditKind.READ, AuditKind.REVOKE,
        AuditKind.DENY,
    ]
    text = repr(events)
    assert "TOP-SECRET" not in text and "bad" not in text and ref.version_id not in text
    assert events[2].principal == "bob" and events[2].scope == ("t1", "src1")
    assert events[5].principal == "" and events[0].at == NOW


def test_clock_failure_does_not_break_operations():
    def bad_clock():
        raise RuntimeError("x")
    v = ArtifactVault(bad_clock, admins=["admin"])
    assert v.grant(S1, ALICE, ADMIN) == av.OK
    assert v.audit()[0].at is None


def test_constructor_validation():
    with pytest.raises(TypeError):
        ArtifactVault("not callable")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ArtifactVault(lambda: NOW, max_bytes=0)


def test_admins_must_be_iterable_of_str():
    for bad in ("alice", b"alice", bytearray(b"ab"), ["ok", 5], [None], ["ok", b"x"]):
        with pytest.raises(ValueError) as exc:
            ArtifactVault(lambda: NOW, admins=bad)  # type: ignore[arg-type]
        assert str(exc.value) == "admins must be an iterable of str"
    v = ArtifactVault(lambda: NOW, admins=iter(["admin"]))
    assert v.grant(S1, ALICE, ADMIN) == av.OK
    assert v.grant(S1, BOB, Principal("a")) == av.ADMIN_REQUIRED


def test_naive_or_non_datetime_clock_gives_none_in_audit():
    for clock_value in (datetime(2026, 1, 1), "2026", None):  # noqa: DTZ001 - naive on purpose
        v = ArtifactVault(lambda cv=clock_value: cv, admins=["admin"])  # type: ignore[misc]
        assert v.grant(S1, ALICE, ADMIN) == av.OK
        assert v.audit()[0].at is None


# ------------------------------------------------- digest hardening (no oracle)
def test_malformed_digests_get_fixed_denial_and_deny_audit():
    v = ready()
    ref = put(v).ref
    bad_digests = ["\ud800" * 64, "\udc00", "é" * 64, ref.digest.upper(), ref.digest[:-1],
                   ref.digest + "0", "", " " + ref.digest]
    for bad in bad_digests:
        forged = dataclasses.replace(ref, digest=bad)
        before = len(v.audit())
        r = v.read(forged, ALICE)
        assert (r.allowed, r.code, r.content) == (False, av.ACCESS_DENIED, None)
        e = v.verify_evidence(ref, bad, ALICE)
        assert (e.valid, e.code) == (False, av.NOT_EVIDENCE)
        e2 = v.verify_evidence(forged, ref.digest, ALICE)
        assert (e2.valid, e2.code) == (False, av.NOT_EVIDENCE)
        new = v.audit()[before:]
        assert [x.kind for x in new] == [AuditKind.DENY] * 3
        assert [x.code for x in new] == [av.ACCESS_DENIED, av.NOT_EVIDENCE, av.NOT_EVIDENCE]
    assert v.read(ref, ALICE).allowed


# ------------------------------------------------------------- concurrency
def test_parallel_identical_puts_store_once():
    v = ready()
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: put(v, b"same-bytes"), range(16)))
    assert [r.status for r in results].count(PutStatus.STORED) == 1
    assert [r.status for r in results].count(PutStatus.DUPLICATE) == 15
    assert len({r.ref.version_id for r in results}) == 1
    puts = [e for e in v.audit() if e.kind is AuditKind.PUT]
    assert len(puts) == 16


# ------------------------------------------------------------- media type
def test_read_returns_media_type_and_duplicate_mismatch_is_refused():
    v = ready()
    ref = put(v, b"data").ref
    assert v.read(ref, ALICE).media_type == PDF
    r = v.put(S1, b"data", ALICE, "text/plain")
    assert r.status is PutStatus.REFUSED and r.code == av.MEDIA_TYPE_MISMATCH and r.ref is None
    assert v.put(S1, b"data", ALICE, PDF).status is PutStatus.DUPLICATE
    assert v.read(ref, ALICE).media_type == PDF
    assert v.read(ref, BOB).media_type is None


# ----------------------------------------------------- access edge cases
def test_put_after_revoke_is_refused():
    v = ready()
    v.revoke(S1, ALICE, ADMIN)
    assert put(v, b"new").code == av.UPLOAD_NOT_ALLOWED


def test_no_access_put_of_existing_bytes_gets_no_duplicate_signal():
    v = ready()
    put(v, b"known")
    known = v.put(S1, b"known", BOB, PDF)
    unknown = v.put(S1, b"never-stored", BOB, PDF)
    assert known == unknown
    assert known.status is PutStatus.REFUSED and known.code == av.UPLOAD_NOT_ALLOWED
    assert known.ref is None


def test_read_with_wrong_types_returns_fixed_denial():
    v = ready()
    ref = put(v).ref
    expected = v.read(ArtifactRef("av_nonexistent", ref.digest, ref.size, S1), ALICE)
    assert v.read("not-a-ref", ALICE) == expected  # type: ignore[arg-type]
    assert v.read(None, ALICE) == expected  # type: ignore[arg-type]
    assert v.read(ref, "alice") == expected  # type: ignore[arg-type]
    assert v.read(ref, None) == expected  # type: ignore[arg-type]
    assert expected.code == av.ACCESS_DENIED and not expected.allowed


def test_duplicate_and_verify_evidence_audit_without_content():
    v = ready()
    ref = put(v, b"TOP-SECRET-BYTES").ref
    put(v, b"TOP-SECRET-BYTES")
    assert v.verify_evidence(ref, ref.digest, ALICE).valid
    events = v.audit()
    assert [e.kind for e in events] == [
        AuditKind.GRANT, AuditKind.PUT, AuditKind.PUT, AuditKind.READ,
    ]
    assert [e.code for e in events] == [av.OK, av.OK, av.DUPLICATE, av.OK]
    text = repr(events)
    assert "TOP-SECRET" not in text and ref.digest not in text and ref.version_id not in text


def test_revoking_one_principal_keeps_another():
    v = ready()
    v.grant(S1, BOB, ADMIN)
    ref = put(v).ref
    assert v.revoke(S1, ALICE, ADMIN) == av.OK
    assert not v.read(ref, ALICE).allowed
    assert v.read(ref, BOB).content == b"hello"
    assert v.put(S1, b"by-bob", BOB, PDF).status is PutStatus.STORED
