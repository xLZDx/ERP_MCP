"""S9 E4 / R2-US-046 / TC136: restore verification by manifest comparison."""
import ast
import copy
import dataclasses
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from business_ai_gateway.phase2 import restore_verify as rv
from business_ai_gateway.phase2.evidence_attestation import (
    AttestationDecision,
    AttestationRequest,
    AttestationStore,
    Signer,
    SignerKind,
)
from business_ai_gateway.phase2.ops_types import (
    FakeCorrelationSource,
    FakeEntitlements,
    FakeOwnership,
    OpsReason,
    OpsRefusal,
    OpsScope,
)
from business_ai_gateway.phase2.restore_verify import (
    LIVING_FK_CATALOGUE,
    LIVING_TABLES,
    MAX_ROWS_PER_TABLE,
    TABLE_KEYS,
    CheckName,
    FkEdge,
    RestoreCheck,
    RestoreManifest,
    RestoreReport,
    build_manifest,
    is_valid_manifest,
    verify_restore,
)

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "business_ai_gateway" / "phase2"
_SQL = _ROOT / "db" / "phase2"

NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)
D1, D2, P1, P2 = "a" * 64, "b" * 64, "c" * 64, "d" * 64
R1, R2, R3 = UUID(int=11), UUID(int=12), UUID(int=13)
O1, O2 = UUID(int=21), UUID(int=22)
SCOPE = OpsScope("t1", "c1", "a1")
SOURCES = ("s1",)
NAIVE = datetime(2026, 1, 1)  # noqa: DTZ001 - naive on purpose


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class EvilDict(dict):
    pass


class Ports:
    """One shared call log for entitlement and ownership; the real fakes answer."""

    def __init__(self):
        self.log = []
        self.owner = FakeOwnership()
        self.ent = FakeEntitlements()
        self.ent.grant("t1", "a1", "c1")
        self.owner.add("t1", "c1", "source_id", "s1")
        self.owner.add("t2", "c2", "source_id", "s9")

    def entitled(self, tenant_id, actor_id, company_id):
        self.log.append(("entitled", tenant_id, actor_id, company_id))
        return self.ent.entitled(tenant_id, actor_id, company_id)

    def owns(self, tenant_id, company_id, kind, ref):
        self.log.append(("owns", tenant_id, company_id, kind, ref))
        return self.owner.owns(tenant_id, company_id, kind, ref)


def _pattern(ports):
    return [(c[0], c[1], c[2], c[3] if c[0] == "owns" else None) for c in ports.log]


def _clock():
    return NOW


class World:
    def __init__(self):
        self.store = AttestationStore(_clock, accountants={"t1": {"acct"}}, id_source=iter(["att-1", "att-2"]).__next__)
        signed = self.store.sign(
            AttestationRequest("t1", D2, "v1", P1, "prop", "req", AttestationDecision.PASS),
            Signer(SignerKind.HUMAN, "acct"))
        assert signed.signed
        self.att_id = signed.attestation.attestation_id
        self.rows = self._rows()
        self.ports = Ports()
        self.ids = FakeCorrelationSource()

    def _rows(self):
        base = {"tenant_id": "t1", "source_id": "s1"}
        return {
            "tenants": [{"tenant_id": "t1"}],
            "sources": [{**base, "company_id": "c1", "scope_epoch": 0, "status": "ACTIVE"}],
            "observations": [
                {**base, "observation_id": O1, "object_id": "obj1", "revision_id": R1, "kind": "OBSERVED",
                 "digest": D1, "supersedes": None, "provenance": {"k": ["v", 1, None]}},
                {**base, "observation_id": O2, "object_id": "obj1", "revision_id": R2, "kind": "OBSERVED",
                 "digest": D2, "supersedes": O1, "provenance": {}},
            ],
            "accepted_heads": [
                {**base, "model_key": "m1", "revision_id": R2, "version": 2},
                {**base, "model_key": "m2", "revision_id": None, "version": 0},
            ],
            "acceptance_events": [
                {**base, "acceptance_id": UUID(int=31), "model_key": "m1", "from_version": 0, "to_version": 1,
                 "accepted_revision": R1},
                {**base, "acceptance_id": UUID(int=32), "model_key": "m1", "from_version": 1, "to_version": 2,
                 "accepted_revision": R2},
            ],
            "jobs": [{**base, "job_id": UUID(int=41), "state": "PENDING", "fence": 0}],
            "cursors": [{**base, "connection_id": "cn1", "cursor_value": "x", "version": 0}],
            "outbox": [{**base, "connection_id": "cn1", "event_id": f"e{i}", "seq": i, "status": "PENDING"}
                       for i in (1, 2, 3)],
            "role_scope": [{"role_name": "living_worker", **base, "company_id": None}],
            "trusted_reviewers": [{"role_name": "living_promoter", **base, "active": True,
                                   "expires_at": NOW + timedelta(days=30)}],
            "attestations": [{**base, "attestation_id": self.att_id, "revision_id": R2, "policy_version": "v1",
                              "policy_digest": P1, "expires_at": NOW + timedelta(days=30), "revoked_at": None}],
        }

    def build(self, rows, scope=SCOPE, sources=SOURCES, catalogue=LIVING_FK_CATALOGUE):
        return build_manifest(scope, sources, rows, self.ports, self.ports, self.ids, catalogue)

    def verify(self, source, restored, *, scope=SCOPE, sources=SOURCES, attestations=None, clock=_clock,
               catalogue=LIVING_FK_CATALOGUE):
        return verify_restore(scope, sources, source, restored, self.ports, self.ports, self.ids,
                              self.store if attestations is None else attestations, clock, catalogue)

    def pair(self, mutate=None, **kw):
        restored_rows = copy.deepcopy(self.rows)
        if mutate is not None:
            mutate(restored_rows)
        source = self.build(self.rows)
        restored = self.build(restored_rows)
        assert isinstance(source, RestoreManifest) and isinstance(restored, RestoreManifest)
        return self.verify(source, restored, **kw)


@pytest.fixture
def world():
    return World()


def _failed(report):
    return {c.name: c for c in report.checks if c.ran and not c.passed}


# ---- the happy path is green by value ------------------------------------------------------------

def test_identical_copy_verifies_with_every_check_run_and_passed(world):
    report = world.pair()
    assert isinstance(report, RestoreReport)
    assert report.verified is True and report.codes == ()
    assert [c.name for c in report.checks] == list(CheckName) and len(report.checks) == 8
    assert all(c.ran and c.passed and c.code is None for c in report.checks)
    assert report.authority == "EVALUATION_ONLY"


def test_report_digest_is_stable_and_binds_both_manifests(world):
    a, b = world.pair(), world.pair()
    assert a.report_digest == b.report_digest and a.source_digest == a.restored_digest
    other = world.pair(lambda r: r["jobs"].pop())
    assert other.report_digest != a.report_digest and other.source_digest != other.restored_digest


def test_manifest_is_a_snapshot_not_a_view_of_the_callers_rows(world):
    manifest = world.build(world.rows)
    digest = manifest.manifest_digest
    world.rows["jobs"][0]["state"] = "CHANGED"
    world.rows["jobs"].append({"tenant_id": "t1", "source_id": "s1", "job_id": UUID(int=99)})
    assert manifest.manifest_digest == digest and is_valid_manifest(manifest)
    assert world.build(world.rows).manifest_digest != digest


def test_row_order_and_dict_key_order_do_not_change_the_digest(world):
    a = world.build(world.rows)
    shuffled = copy.deepcopy(world.rows)
    for table in shuffled.values():
        table.reverse()
    shuffled["outbox"] = [dict(reversed(list(r.items()))) for r in shuffled["outbox"]]
    assert world.build(shuffled).manifest_digest == a.manifest_digest


def test_every_value_type_is_digested_distinctly(world):
    def with_state(value):
        rows = copy.deepcopy(world.rows)
        rows["jobs"][0]["state"] = value
        return world.build(rows).manifest_digest
    digests = {with_state(v) for v in ("1", 1, True, None, Decimal(1), UUID(int=1), NOW, [1], {"a": 1})}
    assert len(digests) == 9


# ---- TC136: one injected defect per code ----------------------------------------------------------

def _drop_job(rows):
    rows["jobs"].pop()


def _flip_cursor(rows):
    rows["cursors"][0]["cursor_value"] = "y"


def _orphan(edge):
    def mutate(rows):
        row = rows[edge.child_table][0]
        row[edge.child_columns[-1]] = "ORPHAN-REF" if edge.child_columns[-1] not in (
            "revision_id", "supersedes", "accepted_revision") else R3
    return mutate


def test_missing_row_is_count_mismatch_and_only_that(world):
    report = world.pair(_drop_job)
    assert report.verified is False and report.codes == (OpsReason.RESTORE_COUNT_MISMATCH,)
    assert _failed(report)[CheckName.COUNT].tables == ("jobs",)


def test_flipped_value_is_digest_mismatch_and_only_that(world):
    report = world.pair(_flip_cursor)
    assert report.codes == (OpsReason.RESTORE_DIGEST_MISMATCH,)
    assert _failed(report)[CheckName.DIGEST].tables == ("cursors",)


def test_flipped_value_inside_nested_jsonb_is_digest_mismatch(world):
    report = world.pair(lambda r: r["observations"][0]["provenance"]["k"].__setitem__(0, "w"))
    assert report.codes == (OpsReason.RESTORE_DIGEST_MISMATCH,)


def test_the_catalogue_has_thirteen_edges_and_each_orphan_case_is_distinct():
    assert len(LIVING_FK_CATALOGUE) == 13 and len(set(LIVING_FK_CATALOGUE)) == 13


@pytest.mark.parametrize("index", range(len(LIVING_FK_CATALOGUE)))
def test_orphan_child_row_for_every_catalogue_edge(world, index):
    edge = LIVING_FK_CATALOGUE[index]
    report = world.pair(_orphan(edge))
    assert OpsReason.RESTORE_FK_ORPHAN in report.codes, edge
    assert edge.child_table in _failed(report)[CheckName.FK].tables
    assert report.verified is False


def test_null_foreign_key_column_is_not_an_orphan_like_sql_match_simple(world):
    report = world.pair()  # observation o1 has supersedes=None and head m2 has revision_id=None
    assert report.verified is True


@pytest.mark.parametrize("mutate", [
    lambda r: r["accepted_heads"][0].__setitem__("version", 3),
    lambda r: r["accepted_heads"][0].__setitem__("revision_id", R3),       # missing revision
    lambda r: r["accepted_heads"][0].__setitem__("revision_id", R1),       # exists, but not what version 2 accepted
    lambda r: r["accepted_heads"][1].__setitem__("revision_id", R1),       # version 0 must have no revision
    lambda r: r["accepted_heads"][1].__setitem__("version", 1),            # version without an acceptance event
])
def test_head_defects_are_head_mismatch(world, mutate):
    report = world.pair(mutate)
    assert OpsReason.RESTORE_HEAD_MISMATCH in report.codes
    assert _failed(report)[CheckName.HEAD].tables == ("accepted_heads",)


def test_head_of_another_source_revision_is_head_mismatch(world):
    world.ports.owner.add("t1", "c1", "source_id", "s2")

    def two_sources(rows):
        rows["sources"].append({"tenant_id": "t1", "source_id": "s2", "company_id": "c1", "scope_epoch": 0,
                                "status": "ACTIVE"})
        rows["observations"].append({"tenant_id": "t1", "source_id": "s2", "observation_id": UUID(int=23),
                                     "object_id": "o", "revision_id": R3, "kind": "OBSERVED", "digest": D1,
                                     "supersedes": None, "provenance": {}})
    two_sources(world.rows)
    source = world.build(world.rows, sources=("s1", "s2"))
    restored_rows = copy.deepcopy(world.rows)
    restored_rows["accepted_heads"][0]["revision_id"] = R3  # exists, but in source s2
    restored = world.build(restored_rows, sources=("s1", "s2"))
    report = world.verify(source, restored, sources=("s1", "s2"))
    assert OpsReason.RESTORE_HEAD_MISMATCH in report.codes and OpsReason.RESTORE_FK_ORPHAN in report.codes


@pytest.mark.parametrize("mutate", [
    lambda r: r["outbox"].pop(1),                                  # a hole in the middle
    lambda r: r["outbox"][2].__setitem__("seq", 2),                # a duplicate sequence number
])
def test_outbox_sequence_defects(world, mutate):
    report = world.pair(mutate)
    assert OpsReason.RESTORE_SEQUENCE_GAP in report.codes
    assert _failed(report)[CheckName.SEQUENCE].tables == ("outbox",)


def test_missing_tail_event_is_a_count_problem_not_a_sequence_gap(world):
    report = world.pair(lambda r: r["outbox"].pop())
    assert OpsReason.RESTORE_COUNT_MISMATCH in report.codes and OpsReason.RESTORE_SEQUENCE_GAP not in report.codes


def test_acceptance_version_gap_is_a_sequence_gap(world):
    report = world.pair(lambda r: r["acceptance_events"][1].__setitem__("to_version", 3))
    assert OpsReason.RESTORE_SEQUENCE_GAP in report.codes
    assert _failed(report)[CheckName.SEQUENCE].tables == ("acceptance_events",)


def test_revoked_attestation_in_the_store_is_stale_even_though_the_backup_row_says_current(world):
    assert world.store.revoke(world.att_id, "t1", Signer(SignerKind.HUMAN, "acct")).revoked
    report = world.pair()
    assert report.codes == (OpsReason.RESTORE_ATTESTATION_STALE,)
    assert _failed(report)[CheckName.ATTESTATION].tables == ("attestations",)


def test_attestation_is_rechecked_as_current_against_its_own_policy_binding(world):
    report = world.pair(lambda r: r["attestations"][0].__setitem__("policy_digest", P2))
    assert OpsReason.RESTORE_ATTESTATION_STALE in report.codes


def test_attestation_unknown_to_the_current_store_is_stale(world):
    report = world.pair(lambda r: r["attestations"][0].__setitem__("attestation_id", "att-unknown"))
    assert OpsReason.RESTORE_ATTESTATION_STALE in report.codes


@pytest.mark.parametrize("mutate", [
    lambda r: r["attestations"][0].__setitem__("revoked_at", NOW),
    lambda r: r["attestations"][0].__setitem__("expires_at", NOW - timedelta(seconds=1)),
    lambda r: r["attestations"][0].__setitem__("expires_at", None),
    lambda r: r["attestations"][0].__setitem__("revision_id", R3),  # no observation: no digest to bind to
])
def test_attestation_row_that_is_not_current_on_its_face_is_stale(world, mutate):
    report = world.pair(mutate)
    assert OpsReason.RESTORE_ATTESTATION_STALE in report.codes


def test_attestation_is_never_trusted_from_the_backup_when_the_clock_moves_past_expiry(world):
    later = lambda: NOW + timedelta(days=31)
    report = world.pair(clock=later)
    assert report.codes == (OpsReason.RESTORE_ATTESTATION_STALE,)


def test_foreign_tenant_row_in_a_tenant_scoped_restore_is_scope_foreign(world):
    report = world.pair(lambda r: r["jobs"][0].__setitem__("tenant_id", "t2"))
    assert OpsReason.RESTORE_SCOPE_FOREIGN in report.codes
    assert _failed(report)[CheckName.SCOPE].tables == ("jobs",)


def test_row_of_an_undeclared_source_is_scope_foreign(world):
    report = world.pair(lambda r: r["jobs"][0].__setitem__("source_id", "s-other"))
    assert OpsReason.RESTORE_SCOPE_FOREIGN in report.codes


def test_report_names_no_value_id_or_count_of_the_defect(world):
    report = world.pair(lambda r: r["jobs"][0].__setitem__("tenant_id", "tenant-LEAK-77"))
    text = repr(report) + repr(report.checks) + str([c.tables for c in report.checks])
    assert "LEAK" not in text and "77" not in text


# ---- incomplete manifests never verify ------------------------------------------------------------

def _empty_rows():
    return {name: [] for name in LIVING_TABLES if name in rv.REQUIRED_TABLES}


def test_empty_manifest_never_verifies(world):
    empty = world.build(_empty_rows())
    assert isinstance(empty, RestoreManifest)
    report = world.verify(empty, empty)
    assert report.verified is False and report.codes == (OpsReason.RESTORE_INCOMPLETE,)
    assert [c.ran for c in report.checks] == [True] + [False] * 7
    assert not any(c.passed for c in report.checks[1:])


def test_manifest_with_no_tables_never_verifies(world):
    empty = world.build({})
    report = world.verify(empty, empty)
    assert report.verified is False and report.codes == (OpsReason.RESTORE_INCOMPLETE,)


@pytest.mark.parametrize("table", sorted(rv.REQUIRED_TABLES))
def test_restore_missing_a_required_table_is_incomplete(world, table):
    report = world.pair(lambda r: r.pop(table))
    assert report.verified is False and report.codes == (OpsReason.RESTORE_INCOMPLETE,)


def test_source_missing_a_required_table_is_incomplete_too(world):
    partial = copy.deepcopy(world.rows)
    partial.pop("outbox")
    src = world.build(partial)
    report = world.verify(src, src)
    assert report.codes == (OpsReason.RESTORE_INCOMPLETE,)


def test_restore_with_an_extra_optional_table_is_incomplete_because_the_table_sets_differ(world):
    report = world.pair(lambda r: r.pop("role_scope"))
    assert report.codes == (OpsReason.RESTORE_INCOMPLETE,)


def test_manifest_lacking_the_columns_a_catalogue_needs_is_incomplete(world):
    narrow = (FkEdge("jobs", ("tenant_id", "source_id"), "sources", ("tenant_id", "source_id")),)
    src = world.build(world.rows, catalogue=narrow)
    report = world.verify(src, src)  # verified with the full catalogue: the manifests do not carry its columns
    assert report.verified is False and report.codes == (OpsReason.RESTORE_INCOMPLETE,)


def test_forged_or_tampered_manifests_are_refused_not_trusted(world):
    good = world.build(world.rows)
    forged = object.__new__(RestoreManifest)
    tampered = world.build(world.rows)
    object.__setattr__(tampered, "manifest_digest", "e" * 64)
    wrong_table = world.build(world.rows)
    first = wrong_table.tables[0]
    object.__setattr__(first, "table_digest", "f" * 64)
    for bad in (forged, tampered, wrong_table, None, "x", {}, 5):
        assert not is_valid_manifest(bad)
        for args in ((good, bad), (bad, good)):
            result = world.verify(*args)
            assert isinstance(result, OpsRefusal) and result.reason is OpsReason.INPUT_INVALID
    with pytest.raises(ValueError, match="RESTORE_MANIFEST_INVALID"):
        RestoreManifest("t1", ("s1",), (), "9" * 64)


# ---- ownership and entitlement come first, foreign == unknown -----------------------------------

class Explodes:
    """Any use at all fails the test: proves a manifest/rows argument was not read."""

    def __getattribute__(self, name):
        raise AssertionError("READ_BEFORE_OWNERSHIP")

    def __iter__(self):
        raise AssertionError("READ_BEFORE_OWNERSHIP")


def test_foreign_and_unknown_source_give_identical_refusal_and_port_pattern_without_reading_input():
    results, patterns = [], []
    for source in ("s9", "s-unknown"):
        w = World()
        out = build_manifest(SCOPE, (source,), Explodes(), w.ports, w.ports, FakeCorrelationSource())
        results.append(out)
        patterns.append(_pattern(w.ports))
        verified = verify_restore(SCOPE, (source,), Explodes(), Explodes(), w.ports, w.ports,
                                  FakeCorrelationSource(), Explodes(), Explodes())
        assert verified == out
    assert results[0] == results[1] and results[0].reason is OpsReason.NOT_FOUND
    assert patterns[0] == patterns[1] and [p[0] for p in patterns[0]] == ["entitled", "owns"]


def test_every_declared_source_is_asked_even_when_the_first_is_foreign(world):
    world.ports.owner.add("t1", "c1", "source_id", "s2")
    out = build_manifest(SCOPE, ("s9", "s1", "s2"), Explodes(), world.ports, world.ports, world.ids)
    assert out.reason is OpsReason.NOT_FOUND
    assert [c[0] for c in world.ports.log] == ["entitled", "owns", "owns", "owns"]


def test_unentitled_actor_is_refused_before_ownership_is_queried(world):
    stranger = OpsScope("t1", "c1", "stranger")
    out = build_manifest(stranger, SOURCES, Explodes(), world.ports, world.ports, world.ids)
    assert out.reason is OpsReason.NOT_ENTITLED
    assert [c[0] for c in world.ports.log] == ["entitled"]
    out = verify_restore(stranger, SOURCES, Explodes(), Explodes(), world.ports, world.ports, world.ids,
                         Explodes(), Explodes())
    assert out.reason is OpsReason.NOT_ENTITLED


def test_structure_is_refused_before_any_port_call(world):
    for scope, sources in [(None, SOURCES), (object.__new__(OpsScope), SOURCES), (SCOPE, None), (SCOPE, ()),
                           (SCOPE, "s1"), (SCOPE, ("s1", "s1")), (SCOPE, (EvilStr("s1"),)), (SCOPE, (None,)),
                           (SCOPE, tuple(f"s{i}" for i in range(65))), (SCOPE, ("s\x001",))]:
        out = build_manifest(scope, sources, {}, world.ports, world.ports, world.ids)
        assert out.reason is OpsReason.INPUT_INVALID, (scope, sources)
        out = verify_restore(scope, sources, None, None, world.ports, world.ports, world.ids, None, _clock)
        assert out.reason is OpsReason.INPUT_INVALID
    assert world.ports.log == []


def test_manifest_of_another_tenant_is_not_found_exactly_like_a_foreign_one(world):
    other = World()
    other.ports.ent.grant("t2", "a2", "c2")
    other.ports.owner.add("t2", "c2", "source_id", "s1")
    foreign_rows = {name: [{**r, "tenant_id": "t2"} if "tenant_id" in r else r for r in rows]
                    for name, rows in other.rows.items()}
    foreign = build_manifest(OpsScope("t2", "c2", "a2"), SOURCES, foreign_rows, other.ports, other.ports, other.ids)
    assert isinstance(foreign, RestoreManifest)
    mine = world.build(world.rows)
    for args in ((foreign, mine), (mine, foreign)):
        out = world.verify(*args)
        assert isinstance(out, OpsRefusal) and out.reason is OpsReason.NOT_FOUND
    # a manifest built for different declared sources is the same refusal
    world.ports.owner.add("t1", "c1", "source_id", "s2")
    two = world.build(world.rows, sources=("s1", "s2"))
    assert world.verify(two, mine).reason is OpsReason.NOT_FOUND


# ---- hostile input -------------------------------------------------------------------------------

def _rows_with(value):
    return {"jobs": [{"tenant_id": "t1", "source_id": "s1", "job_id": value}]}


_RECURSIVE = []
_RECURSIVE.append(_RECURSIVE)
_DEEP = current = []
for _ in range(50):
    nxt = []
    current.append(nxt)
    current = nxt


@pytest.mark.parametrize("value", [
    1.5, float("nan"), Decimal("NaN"), Decimal("Infinity"), EvilStr("j"), "j\x00j", "x" * 70_000, b"bytes",
    object(), {1, 2}, NAIVE, _RECURSIVE, _DEEP, {"a": {"$ts": 1}}, {"": 1}, {1: "x"}, 2**70,
    [object()], EvilDict(a=1),
], ids=lambda v: type(v).__name__)
def test_hostile_cell_values_are_refused_with_no_echo(world, value):
    out = world.build(_rows_with(value))
    assert isinstance(out, OpsRefusal) and out.reason is OpsReason.INPUT_INVALID
    assert "bytes" not in repr(out) and "x" * 20 not in repr(out)


@pytest.mark.parametrize("rows", [
    None, [], "rows", {"unknown_table": []}, {"jobs": None}, {"jobs": "x"}, {"jobs": [None]}, {"jobs": [[]]},
    {"jobs": [EvilDict(tenant_id="t1", source_id="s1", job_id="j")]},
    {"jobs": [{"tenant_id": "t1", "source_id": "s1"}]},                       # key column absent
    {"jobs": [{"tenant_id": "t1", "source_id": None, "job_id": "j"}]},        # NULL key column
    {"jobs": [{"tenant_id": "t1", "source_id": "s1", "job_id": True}]},       # bool key
    {"jobs": [{"tenant_id": "t1", "source_id": "s1", "job_id": {"a": 1}}]},   # container as key
    {"jobs": [{"tenant_id": "t1", "source_id": "s1", "job_id": "j", 5: 1}]},  # non-text column name
    {EvilStr("jobs"): []},
    {"jobs": [{"tenant_id": "t1", "source_id": "s1", "job_id": "j"}] * 2, "jobs ": []},
    {"jobs": [{f"c{i}": 1 for i in range(80)}]},                              # too many columns
])
def test_hostile_row_containers_are_refused_not_raised(world, rows):
    out = world.build(rows)
    assert isinstance(out, OpsRefusal) and out.reason is OpsReason.INPUT_INVALID


def test_structural_columns_must_be_scalars(world):
    rows = world.rows
    rows["attestations"][0]["policy_version"] = ["v1"]
    out = world.build(rows)
    assert out.reason is OpsReason.INPUT_INVALID
    rows = _rows_with("j")
    rows["jobs"][0]["state"] = {"nested": [1, {"deep": None}]}  # non-structural columns may be jsonb
    assert isinstance(world.build(rows), RestoreManifest)


def test_per_table_row_bound_is_an_explicit_quota_refusal(world):
    rows = {"jobs": [{"tenant_id": "t1", "source_id": "s1", "job_id": f"j{i}"} for i in range(MAX_ROWS_PER_TABLE + 1)]}
    out = world.build(rows)
    assert isinstance(out, OpsRefusal) and out.reason is OpsReason.QUOTA_EXCEEDED
    rows["jobs"].pop()
    assert isinstance(world.build(rows), RestoreManifest)


def test_total_row_bound_is_an_explicit_quota_refusal(world):
    rows = {name: [{"tenant_id": "t1", "source_id": "s1", "connection_id": "c", "event_id": f"e{i}", "seq": i,
                    "job_id": f"j{i}", "role_name": "r", "attestation_id": f"a{i}", "revision_id": None,
                    "observation_id": f"o{i}", "acceptance_id": f"x{i}", "model_key": f"m{i}", "company_id": None}
                   for i in range(rv.MAX_ROWS_PER_TABLE)] for name in ("jobs", "cursors", "outbox", "sources",
                                                                      "observations")}
    out = world.build(rows)
    assert isinstance(out, OpsRefusal) and out.reason is OpsReason.QUOTA_EXCEEDED


def test_bad_catalogues_are_refused(world):
    for bad in (None, "x", [object()], [FkEdge("jobs", ("tenant_id",), "tenants", ("tenant_id",)), None],
                [object.__new__(FkEdge)], [FkEdge("jobs", ("tenant_id",), "not_a_table", ("tenant_id",))],
                [LIVING_FK_CATALOGUE[0]] * 65):
        assert world.build(world.rows, catalogue=bad).reason is OpsReason.INPUT_INVALID


def test_fk_edge_validation_has_a_fixed_code_and_no_echo():
    for args in (("jobs", (), "sources", ()), ("jobs", ("a",), "sources", ("a", "b")), ("Jobs", ("a",), "x", ("a",)),
                 ("jobs", ["a"], "sources", ["a"]), ("jobs", ("a; DROP",), "sources", ("a",)),
                 (EvilStr("jobs"), ("a",), "sources", ("a",)), ("jobs", ("a", "a"), "sources", ("a", "b"))):
        with pytest.raises(ValueError, match="FK_EDGE_INVALID") as info:
            FkEdge(*args)
        assert "DROP" not in str(info.value)


def test_clock_and_attestation_port_failures_are_dependency_failures_not_green_results(world):
    src = world.build(world.rows)

    class Boom:
        def check_current(self, *a):
            raise RuntimeError("POISON-TEXT")

    class Garbage:
        def check_current(self, *a):
            return object()

    for clock in (lambda: (_ for _ in ()).throw(RuntimeError("POISON-TEXT")), lambda: NAIVE,
                  lambda: "2026", None, 5):
        out = world.verify(src, src, clock=clock)
        assert isinstance(out, OpsRefusal)
        assert out.reason in (OpsReason.DEPENDENCY_FAILED, OpsReason.INPUT_INVALID)
        assert "POISON" not in repr(out)
    for port in (Boom(), Garbage(), object(), None):
        out = verify_restore(SCOPE, SOURCES, src, src, world.ports, world.ports, world.ids, port, _clock)
        assert isinstance(out, OpsRefusal) and out.reason is OpsReason.DEPENDENCY_FAILED
        assert "POISON" not in repr(out)


def test_attestation_port_answering_valid_with_a_wrong_code_is_still_stale(world):
    class Liar:
        def check_current(self, *a):
            return type("R", (), {"valid": True, "code": "VALID_HISTORICAL"})()

    report = world.pair(attestations=Liar())
    assert OpsReason.RESTORE_ATTESTATION_STALE in report.codes

    class Truthy:
        def check_current(self, *a):
            return type("R", (), {"valid": 1, "code": "VALID"})()

    assert OpsReason.RESTORE_ATTESTATION_STALE in world.pair(attestations=Truthy()).codes


def test_attestation_port_is_not_needed_when_the_restore_has_no_attestation_rows(world):
    rows = copy.deepcopy(world.rows)
    rows["attestations"] = []
    src = world.build(rows)
    report = world.verify(src, src, attestations=None)
    assert report.verified is True


def test_forged_report_pieces_are_rejected():
    with pytest.raises(ValueError, match="RESTORE_CHECK_INVALID"):
        RestoreCheck(CheckName.FK, True, False, OpsReason.RESTORE_COUNT_MISMATCH)   # wrong code for the check
    with pytest.raises(ValueError, match="RESTORE_CHECK_INVALID"):
        RestoreCheck(CheckName.FK, True, True, OpsReason.RESTORE_FK_ORPHAN)         # passed but carries a code
    with pytest.raises(ValueError, match="RESTORE_CHECK_INVALID"):
        RestoreCheck(CheckName.FK, False, True, None)                                # not run cannot pass
    with pytest.raises(ValueError, match="RESTORE_CHECK_INVALID"):
        RestoreCheck(CheckName.FK, True, False, OpsReason.RESTORE_FK_ORPHAN, ("not_a_table",))
    with pytest.raises(ValueError, match="RESTORE_CHECK_INVALID"):
        RestoreCheck("FK", True, True, None)  # type: ignore[arg-type]
    green = tuple(RestoreCheck(n, True, True, None) for n in CheckName)
    with pytest.raises(ValueError, match="RESTORE_REPORT_INVALID"):
        RestoreReport(green[:-1], "a" * 64, "a" * 64, "a" * 64)
    with pytest.raises(ValueError, match="RESTORE_REPORT_INVALID"):
        RestoreReport(tuple(reversed(green)), "a" * 64, "a" * 64, "a" * 64)
    with pytest.raises(ValueError, match="RESTORE_REPORT_INVALID"):
        RestoreReport(green, "a" * 64, "a" * 64, "a" * 64, "OTHER")
    assert RestoreReport(green, "a" * 64, "a" * 64, "a" * 64).verified is True  # derived, never a field
    assert "verified" not in {f.name for f in dataclasses.fields(RestoreReport)}


def test_outputs_are_frozen_and_redacted(world):
    manifest = world.build(world.rows)
    report = world.pair()
    for obj in (manifest, manifest.tables[0], manifest.tables[0].entries[0], report, report.checks[0]):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, dataclasses.fields(obj)[0].name, "x")
    for text in (repr(manifest), repr(manifest.tables[0]), repr(manifest.tables[0].entries[0]), repr(report)):
        assert "t1" not in text and "s1" not in text and "obj1" not in text
    assert not hasattr(report, "__dict__")


def test_public_functions_never_raise_on_garbage(world):
    junk = (None, 0, "", object(), [], {}, (), Explodes(), EvilStr("x"), float("nan"))
    for a in junk:
        for b in junk:
            assert isinstance(build_manifest(a, b, a, a, b, a), OpsRefusal)
            assert isinstance(verify_restore(a, b, a, b, a, b, a, b, a), OpsRefusal)


def test_a_failing_id_source_never_turns_a_refusal_into_a_crash(world):
    class Broken:
        def next_id(self):
            raise RuntimeError("POISON")

    out = build_manifest(SCOPE, ("s9",), {}, world.ports, world.ports, Broken())
    assert out.reason is OpsReason.NOT_FOUND and out.correlation_id == "CORR-UNASSIGNED"


def test_ownership_and_entitlement_ports_that_raise_give_dependency_failed(world):
    class Raising:
        def entitled(self, *a):
            raise RuntimeError("POISON")

        def owns(self, *a):
            raise RuntimeError("POISON")

    out = build_manifest(SCOPE, SOURCES, {}, Raising(), Raising(), world.ids)
    assert out.reason is OpsReason.DEPENDENCY_FAILED and "POISON" not in repr(out)


# ---- catalogue == real SQL REFERENCES --------------------------------------------------------------

def _strip_comments(text):
    return re.sub(r"--[^\n]*", "", text)


def _matching_paren(text, start):
    depth, quote = 0, False
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "'":
            quote = not quote
        elif not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError("unbalanced parentheses in SQL text")


def _split_top_level(body):
    items, depth, quote, cur = [], 0, False, []
    for ch in body:
        if ch == "'":
            quote = not quote
        if not quote and ch == "(":
            depth += 1
        elif not quote and ch == ")":
            depth -= 1
        if ch == "," and depth == 0 and not quote:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    items.append("".join(cur))
    return [" ".join(i.split()) for i in items if i.strip()]


def _cols(text):
    return tuple(c.strip() for c in text.split(","))


def parse_sql_tables(sql_text):
    """``{table: (primary_key | None, [(child_cols, parent_table, parent_cols | None)])}`` from CREATE TABLE text."""
    text = _strip_comments(sql_text)
    tables = {}
    for match in re.finditer(r"CREATE TABLE IF NOT EXISTS living\.(\w+)\s*\(", text):
        start = match.end() - 1
        body = text[start + 1:_matching_paren(text, start)]
        pk, fks = None, []
        for item in _split_top_level(body):
            fk = re.match(r"FOREIGN KEY\s*\(([^)]*)\)\s*REFERENCES\s+living\.(\w+)\s*(?:\(([^)]*)\))?", item, re.IGNORECASE)
            pkm = re.match(r"PRIMARY KEY\s*\(([^)]*)\)", item, re.IGNORECASE)
            if fk:
                fks.append((_cols(fk.group(1)), fk.group(2), _cols(fk.group(3)) if fk.group(3) else None))
            elif pkm:
                pk = _cols(pkm.group(1))
            elif re.match(r"(UNIQUE|CHECK|CONSTRAINT)\b", item, re.IGNORECASE):
                continue
            else:
                col = item.split(" ", 1)[0]
                inline = re.search(r"REFERENCES\s+living\.(\w+)\s*(?:\(([^)]*)\))?", item, re.IGNORECASE)
                if inline:
                    fks.append(((col,), inline.group(1), _cols(inline.group(2)) if inline.group(2) else None))
                if re.search(r"\bPRIMARY KEY\b", item, re.IGNORECASE):
                    pk = (col,)
        tables[match.group(1)] = (pk, fks)
    return tables


def sql_edges(sql_text):
    """Resolved ``(child, child_cols, parent, parent_cols)`` set; an implicit parent column list is its primary key."""
    tables = parse_sql_tables(sql_text)
    edges = set()
    for child, (_pk, fks) in tables.items():
        for ccols, parent, pcols in fks:
            resolved = pcols if pcols is not None else tables[parent][0]
            assert resolved is not None, (child, parent)
            edges.add((child, ccols, parent, resolved))
    return edges


def catalogue_edges(catalogue):
    return {(e.child_table, e.child_columns, e.parent_table, e.parent_columns) for e in catalogue}


def _all_sql():
    return "\n".join((_SQL / name).read_text(encoding="utf-8") for name in
                     ("001_living_registry.sql", "002_job_cursor_functions.sql", "003_security_hardening.sql"))


def test_catalogue_equals_the_real_sql_references_in_both_directions():
    parsed = sql_edges(_all_sql())
    mine = catalogue_edges(LIVING_FK_CATALOGUE)
    assert len(parsed) >= 10, "the parser must see the real edges (a broken instrument would see none)"
    assert not (parsed - mine), f"SQL has edges the catalogue lacks: {sorted(parsed - mine)}"
    assert not (mine - parsed), f"catalogue has edges the SQL lacks: {sorted(mine - parsed)}"


def test_every_sql_table_is_in_the_vocabulary_with_the_same_primary_key():
    tables = parse_sql_tables(_all_sql())
    sql_tables = {n for n in tables if n != "schema_migrations"}
    assert sql_tables == set(LIVING_TABLES)
    for name, (pk, _fks) in tables.items():
        if name != "schema_migrations" and pk is not None:
            assert TABLE_KEYS[name] == pk, name


def test_the_comparison_instrument_can_fail_in_either_direction():
    sql = """
    CREATE TABLE IF NOT EXISTS living.p(a text NOT NULL, b text NOT NULL, PRIMARY KEY(a,b));
    CREATE TABLE IF NOT EXISTS living.q(
     a text NOT NULL REFERENCES living.r(a), b text NOT NULL, c text, CHECK(c IN ('x','y')),
     FOREIGN KEY(a,b) REFERENCES living.p,
     FOREIGN KEY(a,b,c) REFERENCES living.p(a,b,z) -- trailing comment, with a comma
    );
    CREATE TABLE IF NOT EXISTS living.r(a text PRIMARY KEY);
    """
    edges = sql_edges(sql)
    assert edges == {("q", ("a",), "r", ("a",)), ("q", ("a", "b"), "p", ("a", "b")),
                     ("q", ("a", "b", "c"), "p", ("a", "b", "z"))}
    real = catalogue_edges(LIVING_FK_CATALOGUE)
    assert real - {next(iter(real))} != real and (real | {("jobs", ("a",), "b", ("a",))}) != real


# ---- source boundaries ----------------------------------------------------------------------------

_FORBIDDEN = {"httpx", "requests", "socket", "subprocess", "os", "pathlib", "random", "secrets", "time", "shutil",
              "threading", "sqlite3", "psycopg", "psycopg2", "asyncpg", "urllib", "http", "ctypes", "io"}
_DELETE_WORDS = ("delete", "remove", "unlink", "rmtree", "rmdir", "truncate", "drop")


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append(("." * node.level) + (node.module or ""))
    return out


def test_module_has_no_forbidden_import_no_release1_and_no_delete_call():
    path = _SRC / "restore_verify.py"
    for name in _imports(path):
        root = name.lstrip(".").split(".")[0]
        low = name.lower()
        assert root not in _FORBIDDEN, name
        assert "release1" not in low and "release_1" not in low and "pdcc" not in low, name
        assert not name.startswith(".."), name  # leaving the phase2 package is the Release 1 side
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            assert not any(w in called.lower() for w in _DELETE_WORDS), called
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not any(w in node.name.lower() for w in _DELETE_WORDS), node.name
    text = path.read_text(encoding="utf-8")
    assert "open(" not in text.replace("# open(", "") and "read_text" not in text and "environ" not in text


def test_module_has_no_module_level_mutable_collection():
    tree = ast.parse((_SRC / "restore_verify.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if any(getattr(t, "id", "") == "__all__" for t in getattr(node, "targets", [])):
                continue
            assert not isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)), \
                ast.dump(node)[:80]
