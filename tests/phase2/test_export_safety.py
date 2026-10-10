"""S9 E4 / R2-US-046 / TC137: tenant-bounded, deny-by-default, formula-safe export building."""
import ast
import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from business_ai_gateway.phase2.export_safety import (
    DENIED_TOKEN,
    MASK_TOKEN,
    MAX_INPUT_ROWS,
    ExportColumnPolicy,
    ExportPolicy,
    ExportRequest,
    ExportResult,
    build_export,
    looks_like_credential,
    neutralize_cell,
)
from business_ai_gateway.phase2.ops_types import (
    FakeCorrelationSource,
    FakeEntitlements,
    FakeOwnership,
    OpsReason,
    OpsRefusal,
    OpsScope,
    TenantSlotCounter,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "business_ai_gateway" / "phase2"
P, M, H, D = (ExportColumnPolicy.PUBLIC, ExportColumnPolicy.MASKED, ExportColumnPolicy.HASHED,
              ExportColumnPolicy.DENIED)
SCOPE = OpsScope("t1", "c1", "a1")
SCOPE2 = OpsScope("t2", "c2", "a2")
REQ = ExportRequest("EXP-1")
NAIVE = datetime(2026, 1, 1)  # noqa: DTZ001 - naive on purpose


class EvilStr(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class EvilDict(dict):
    pass


class Ports:
    def __init__(self):
        self.log = []
        self.owner = FakeOwnership()
        self.ent = FakeEntitlements()
        self.ent.grant("t1", "a1", "c1")
        self.ent.grant("t2", "a2", "c2")
        self.owner.add("t1", "c1", "report_id", "EXP-1")
        self.owner.add("t2", "c2", "report_id", "EXP-2")

    def entitled(self, tenant_id, actor_id, company_id):
        self.log.append(("entitled", tenant_id, actor_id, company_id))
        return self.ent.entitled(tenant_id, actor_id, company_id)

    def owns(self, tenant_id, company_id, kind, ref):
        self.log.append(("owns", tenant_id, company_id, kind, ref))
        return self.owner.owns(tenant_id, company_id, kind, ref)


def _policy(**limits):
    return ExportPolicy.from_mapping(
        {"name": P, "email": M, "ssn": H, "internal": D, "note": P, "amount": P}, **limits)


def _row(**cells):
    return {"tenant_id": "t1", "company_id": "c1", **cells}


def _own_rows():
    return [_row(name="Alice", email="alice@example.com", ssn="123-45-6789", internal="x", note="hello", amount=5),
            _row(name="Bob", email="bob@example.com", ssn="987-65-4321", internal="y", note="world", amount=7)]


def export(rows, *, scope=SCOPE, request=REQ, policy=None, ports=None, concurrency=None, ids=None):
    ports = ports or Ports()
    return build_export(scope, request, rows, policy if policy is not None else _policy(), ports, ports, ids or FakeCorrelationSource(),
                        concurrency)


def _text(result):
    return repr(result) + repr(result.header) + repr(result.rows) + repr(result.findings)


# ---- the happy path ------------------------------------------------------------------------------

def test_basic_export_is_derived_sorted_and_evaluation_only():
    result = export(_own_rows())
    assert isinstance(result, ExportResult)
    assert result.header == ("amount", "email", "name", "note", "ssn")
    assert result.rows[0][0] == "5" and result.rows[0][1] == MASK_TOKEN and result.rows[0][2] == "Alice"
    assert result.rows[0][4].startswith("h:") and len(result.rows[0][4]) == 18
    assert result.findings == () and result.hidden_by_scope is False
    assert result.authority == "EVALUATION_ONLY" and "internal" not in result.header
    assert all(type(c) is str for row in result.rows for c in row)


def test_digest_is_stable_across_runs_and_binds_content_and_policy():
    a, b = export(_own_rows()), export(_own_rows())
    assert a.export_digest == b.export_digest and a.policy_digest == b.policy_digest
    changed = _own_rows()
    changed[1]["note"] = "WORLD"
    assert export(changed).export_digest != a.export_digest
    assert export(_own_rows(), policy=_policy(max_rows=5)).export_digest != a.export_digest


def test_empty_input_gives_an_empty_export_not_a_fixed_header():
    result = export([])
    assert result.header == () and result.rows == () and result.findings == ()


def test_value_types_render_as_text_deterministically():
    row = _row(name=UUID(int=5), note=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), amount=Decimal("-1.50"))
    result = export([row])
    assert result.rows[0] == ("-1.50", "00000000-0000-0000-0000-000000000005", "2026-01-02T03:04:05+00:00")
    assert result.neutralized_cells == 0  # typed numbers are not text


# ---- TC137: tenant and company isolation ---------------------------------------------------------

FOREIGN = "FOREIGN-NAME-xyz"


def _mixed():
    own = _own_rows()
    foreign = [
        {"tenant_id": "t2", "company_id": "c2", "name": FOREIGN, "note": "n2", "amount": 1},
        {"tenant_id": "t1", "company_id": "c2", "name": FOREIGN + "-other-company", "amount": 2},
        {"tenant_id": "t2", "company_id": "c1", "name": FOREIGN + "-other-tenant", "zzz_foreign_col": object()},
    ]
    return [foreign[0], own[0], foreign[1], own[1], foreign[2]]


def test_only_the_viewers_rows_survive_two_tenants_and_two_companies():
    clean, mixed = export(_own_rows()), export(_mixed())
    assert mixed.header == clean.header and mixed.rows == clean.rows
    assert mixed.export_digest == clean.export_digest  # nothing of the foreign rows reaches the digest
    assert clean.hidden_by_scope is False and mixed.hidden_by_scope is True
    assert mixed.findings == (OpsReason.HIDDEN_BY_SCOPE,)
    assert "FOREIGN" not in _text(mixed) and "zzz" not in _text(mixed) and "other-" not in _text(mixed)


def test_hidden_flag_is_opaque_no_count_no_id():
    one = export([_row(name="A"), {"tenant_id": "t2", "company_id": "c2", "name": "B"}])
    many = export([_row(name="A")] + [{"tenant_id": "t2", "company_id": "c2", "name": f"B{i}"}
                                     for i in range(500)])
    assert one == many  # not even the count of dropped rows is observable
    assert [f.name for f in dataclasses.fields(ExportResult)].count("hidden_by_scope") == 1
    assert not [f for f in dataclasses.fields(ExportResult) if "hidden" in f.name and f.type != "bool"]


def test_a_foreign_row_is_dropped_uninspected_so_it_cannot_fail_or_change_the_result():
    rows = _own_rows() + [{"tenant_id": "t2", "company_id": "c2", "name": object(), "weird": float("nan"),
                           "x" * 300: 1, 5: "non-text key"}]
    assert export(rows).header == export(_own_rows()).header
    assert export(rows).hidden_by_scope is True
    # but a foreign-looking row that cannot even be attributed to a tenant is invalid input, not silently dropped
    assert export(_own_rows() + [{"name": "no tenant"}]).reason is OpsReason.INPUT_INVALID


def test_the_other_viewer_sees_only_the_other_rows():
    result = export(_mixed(), scope=SCOPE2, request=ExportRequest("EXP-2"))
    assert result.rows == (("1", "FOREIGN-NAME-xyz", "n2"),) or result.rows[0][1] == FOREIGN
    assert len(result.rows) == 1 and "Alice" not in _text(result) and "Bob" not in _text(result)


def test_foreign_and_unknown_export_id_are_identical_refusals_and_rows_are_not_read():
    class Explodes:
        def __iter__(self):
            raise AssertionError("READ_BEFORE_OWNERSHIP")

        def __len__(self):
            raise AssertionError("READ_BEFORE_OWNERSHIP")

    out, patterns = [], []
    for export_id in ("EXP-2", "EXP-NOPE"):
        ports = Ports()
        out.append(export(Explodes(), request=ExportRequest(export_id), ports=ports, policy=Explodes()))
        patterns.append([(c[0], c[1], c[2], c[3] if c[0] == "owns" else None) for c in ports.log])
    assert out[0] == out[1] and out[0].reason is OpsReason.NOT_FOUND
    assert patterns[0] == patterns[1] and [p[0] for p in patterns[0]] == ["entitled", "owns"]


def test_unentitled_actor_is_refused_before_ownership_and_before_any_read():
    ports = Ports()
    out = export(object(), scope=OpsScope("t1", "c1", "stranger"), ports=ports, policy=object())
    assert out.reason is OpsReason.NOT_ENTITLED and [c[0] for c in ports.log] == ["entitled"]


def test_structure_is_refused_before_any_port_call():
    ports = Ports()
    for scope, request, concurrency in [(None, REQ, None), (object.__new__(OpsScope), REQ, None),
                                        (SCOPE, None, None), (SCOPE, "EXP-1", None), (SCOPE, object.__new__(ExportRequest), None),
                                        (SCOPE, REQ, object()), (SCOPE, REQ, TenantSlotCounter)]:
        out = build_export(scope, request, [], _policy(), ports, ports, FakeCorrelationSource(), concurrency)
        assert isinstance(out, OpsRefusal) and out.reason is OpsReason.INPUT_INVALID
    assert ports.log == []


# ---- column policy -------------------------------------------------------------------------------

def test_undeclared_column_is_unclassified_and_absent_without_its_name():
    rows = _own_rows()
    rows[0]["secret_extra_col"] = "value-SENSITIVE"
    result = export(rows)
    assert OpsReason.COLUMN_UNCLASSIFIED in result.findings and result.unclassified_columns == 1
    assert "secret_extra_col" not in _text(result) and "SENSITIVE" not in _text(result)
    assert result.header == export(_own_rows()).header


def test_undeclared_column_only_in_a_foreign_row_is_not_reported():
    result = export(_own_rows() + [{"tenant_id": "t2", "company_id": "c2", "undeclared": "x"}])
    assert result.unclassified_columns == 0 and OpsReason.COLUMN_UNCLASSIFIED not in result.findings


def test_denied_column_is_absent_and_not_reported_as_unclassified():
    result = export(_own_rows())
    assert "internal" not in result.header and result.unclassified_columns == 0
    assert all("internal" not in c for row in result.rows for c in row)


def test_hostile_cell_in_an_undeclared_or_denied_column_is_never_read():
    rows = _own_rows()
    rows[0]["undeclared"] = object()
    rows[0]["internal"] = object()
    assert export(rows).findings == (OpsReason.COLUMN_UNCLASSIFIED,)


def test_masking_is_a_fixed_token_independent_of_the_value_and_its_length():
    one = export([_row(email="a")]).rows[0][0]
    long = export([_row(email="a" * 4000)]).rows[0][0]
    none = export([_row(email=None)]).rows[0][0]
    assert one == long == none == MASK_TOKEN


def test_hashing_is_deterministic_fixed_length_and_free_of_the_original():
    a1 = export([_row(ssn="123-45-6789")]).rows[0][0]
    a2 = export([_row(ssn="123-45-6789")]).rows[0][0]
    b = export([_row(ssn="123-45-678")]).rows[0][0]
    long = export([_row(ssn="1" * 4000)]).rows[0][0]
    assert a1 == a2 and a1 != b and len(a1) == len(b) == len(long) == 18
    assert "123" not in a1 and "6789" not in a1


def test_hashing_is_domain_separated_by_column_and_tenant():
    policy = ExportPolicy.from_mapping({"a": H, "b": H})
    row = _row(a="same", b="same")
    cells = export([row], policy=policy).rows[0]
    assert cells[0] != cells[1]
    other = export([{"tenant_id": "t2", "company_id": "c2", "a": "same", "b": "same"}], scope=SCOPE2,
                   request=ExportRequest("EXP-2"), policy=policy).rows[0]
    assert other[0] != cells[0]


def test_masked_and_hashed_cells_do_not_run_the_credential_detector():
    token = "AK" + "IA" + "FAKE" * 4
    result = export([_row(email=token, ssn=token)])
    assert result.denied_values == 0 and result.rows[0][0] == MASK_TOKEN and token not in _text(result)


# ---- formula injection ---------------------------------------------------------------------------

DANGEROUS = [
    "=1+1", "+1", "-1", "@SUM(A1)", "\t=1", "\r=1", "\n=1", "\tabc", "\rabc", " =1", "   +1", "\u200b=1", "﻿-1",
    "\x01=1", " @x", " =1", "\u200b ‍=cmd", "＝1+1", "＋1", "－1", "＠x", "− 1",
    "‐x", "–x", "—x", "﹦x", "⁼x", "₌x", "﹢x", "﹣x", "⠀=1", "ㅤ+1",
    "  =HYPERLINK(\"http://x\")", "=cmd|' /C calc'!A0", "\x00=1".replace("\x00", "\x1f"),
    " \t=1", "\u200b\u200b\u200b" * 50 + "=1",
]
SAFE = ["hello", "a=b", "1+1", "x-1", "'=1", "'+1", "", "  hello", "5", "email@x", "(=1)", "#=1", "é=1", "a\t=1",
        "−" "".join([]) + "a"]


@pytest.mark.parametrize("text", DANGEROUS, ids=lambda t: repr(t)[:24])
def test_neutralize_cell_matrix_dangerous(text):
    out, changed = neutralize_cell(text)
    assert changed is True and out == "'" + text
    again, changed_again = neutralize_cell(out)
    assert again == out and changed_again is False  # idempotent


@pytest.mark.parametrize("text", SAFE, ids=lambda t: repr(t)[:24])
def test_neutralize_cell_matrix_safe(text):
    assert neutralize_cell(text) == (text, False)


def test_neutralize_cell_never_raises_and_non_text_is_blank():
    for bad in (None, 5, b"=1", EvilStr("=1"), object(), ["=1"], 1.5):
        assert neutralize_cell(bad) == ("", False)
    assert neutralize_cell("=" * 100_000)[1] is True


def test_formula_cells_in_values_and_headers_are_neutralized_counted_and_never_evaluated():
    policy = ExportPolicy.from_mapping({"=cmd": P, "ok": P, "@h": P})
    rows = [_row(**{"=cmd": "=1+1", "ok": "fine", "@h": "-1"}), _row(**{"=cmd": "  +2", "ok": "\u200b@x", "@h": "x"})]
    result = export(rows, policy=policy)
    assert result.header == ("'=cmd", "'@h", "ok") and result.neutralized_headers == 2
    assert result.rows == (("'=1+1", "'-1", "fine"), ("'  +2", "x", "'\u200b@x"))
    assert result.neutralized_cells == 4 and result.findings == (OpsReason.CELL_NEUTRALIZED,)
    # building the export twice (idempotent) over its own neutralized output changes nothing further
    again = export([dict(zip(("tenant_id", "company_id", *result.header), ("t1", "c1", *r), strict=True))
                    for r in result.rows], policy=ExportPolicy.from_mapping({h: P for h in result.header}))
    assert again.rows == result.rows and again.neutralized_cells == 0


def test_typed_numbers_are_exempt_but_numeric_looking_text_is_neutralized():
    result = export([_row(amount=-5), _row(amount=Decimal("-1.5")), _row(amount="-5"), _row(amount="=-5")])
    assert [r[0] for r in result.rows] == ["-5", "-1.5", "'-5", "'=-5"] and result.neutralized_cells == 2


# ---- credentials ---------------------------------------------------------------------------------

def _secrets():
    return {
        "aws": "AK" + "IA" + "FAKEFAKEFAKEFAKE",
        "sk": "sk" + "-" + "FAKE" * 6,
        "gh": "gh" + "p_" + "FAKE" * 8,
        "slack": "xo" + "xb-" + "FAKE" * 5,
        "jwt": "ey" + "JhbGciOi.ey" + "JzdWIiOiIx.c2lnbmF0dXJl",
        "pem": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "bearer": "Bear" + "er " + "FAKE" * 6,
        "assign": "pass" + "word=hunter2",
        "assign_colon": "api_" + "key: FAKE-KEY-1",
        "url": "postgres://user:FAKEPASS@host/db",
        "long_run": "FAKE" + "1" * 12 + "FAKE" + "2" * 14,
        "fullwidth": "ｐａｓｓｗｏｒｄ＝hunter2",
        "zero_width": "pass\u200bword=hunter2",
        "embedded": "contact me, token = FAKETOKENVALUE thanks",
    }


@pytest.mark.parametrize("name", sorted(_secrets()))
def test_credential_shaped_values_are_denied_and_never_appear(name):
    secret = _secrets()[name]
    assert looks_like_credential(secret) is True
    result = export([_row(note=secret, name="plain")])
    assert result.rows[0][1] == DENIED_TOKEN and result.denied_values == 1
    assert OpsReason.VALUE_DENIED in result.findings
    assert secret not in _text(result) and "hunter2" not in _text(result) and "FAKE" not in "".join(result.rows[0])


def test_ordinary_values_and_bare_digests_are_not_denied():
    for fine in ("hello world", "2026-01-01", "invoice 12345", "a" * 64, "0123456789abcdef" * 4, "alice@example.com",
                 "token", "password policy updated", "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGH"):
        assert looks_like_credential(fine) is False, fine
        assert export([_row(note=fine)]).denied_values == 0
    assert looks_like_credential(None) is False and looks_like_credential(EvilStr("password=1")) is False


def test_credential_inside_a_formula_cell_is_denied_before_neutralization():
    result = export([_row(note="=" + _secrets()["sk"])])
    assert result.rows[0][0] == DENIED_TOKEN and result.neutralized_cells == 0


# ---- limits and per-tenant caps ------------------------------------------------------------------

def test_row_cap_counts_admitted_rows_only():
    rows = [_row(name=f"n{i}") for i in range(3)]
    assert export(rows, policy=_policy(max_rows=3)).hidden_by_scope is False
    out = export(rows + [_row(name="n4")], policy=_policy(max_rows=3))
    assert out.reason is OpsReason.EXPORT_LIMIT_EXCEEDED
    foreign = [{"tenant_id": "t2", "company_id": "c2", "name": f"f{i}"} for i in range(50)]
    ok = export(rows + foreign, policy=_policy(max_rows=3))  # foreign rows never count against the viewer
    assert isinstance(ok, ExportResult) and len(ok.rows) == 3


def test_cell_and_byte_caps_are_fixed_refusals_without_echo():
    out = export([_row(name="x" * 11)], policy=_policy(max_cell_chars=10))
    assert out.reason is OpsReason.EXPORT_LIMIT_EXCEEDED and "xxx" not in repr(out)
    assert isinstance(export([_row(name="x" * 10)], policy=_policy(max_cell_chars=10)), ExportResult)
    big = [_row(name="y" * 100) for _ in range(20)]
    assert export(big, policy=_policy(max_bytes=1000)).reason is OpsReason.EXPORT_LIMIT_EXCEEDED
    assert isinstance(export(big, policy=_policy(max_bytes=4000)), ExportResult)


def test_oversize_raw_input_is_refused_without_walking_it():
    row = _row(name="a")
    out = export([row] * (MAX_INPUT_ROWS + 1))
    assert out.reason is OpsReason.EXPORT_LIMIT_EXCEEDED


def test_too_many_columns_in_one_row_is_invalid_input():
    assert export([_row(**{f"c{i}": 1 for i in range(80)})]).reason is OpsReason.INPUT_INVALID


def test_tenant_a_at_its_slot_cap_is_refused_and_tenant_b_is_untouched():
    slots = TenantSlotCounter(1)
    assert slots.try_acquire("t1", "export")  # A is at its cap
    a = export(_own_rows(), concurrency=slots)
    b = export(_mixed(), scope=SCOPE2, request=ExportRequest("EXP-2"), concurrency=slots)
    assert isinstance(a, OpsRefusal) and a.reason is OpsReason.QUOTA_EXCEEDED
    assert isinstance(b, ExportResult) and slots.active("t2", "export") == 0
    assert slots.active("t1", "export") == 1  # the refused call took nothing
    slots.release("t1", "export")
    assert isinstance(export(_own_rows(), concurrency=slots), ExportResult)


def test_the_slot_is_released_after_success_and_after_every_failure_path():
    slots = TenantSlotCounter(1)
    assert isinstance(export(_own_rows(), concurrency=slots), ExportResult) and slots.active("t1", "export") == 0
    for rows, policy in ((object(), None), ([_row(name=object())], None), ([_row(name="z" * 9000)], _policy()),
                         ([_row(name="a")], object())):
        out = export(rows, policy=policy or _policy(), concurrency=slots) if policy is not object() else \
            build_export(SCOPE, REQ, rows, policy, Ports(), Ports(), FakeCorrelationSource(), slots)
        assert isinstance(out, OpsRefusal) and slots.active("t1", "export") == 0
    ports = Ports()
    ports.owner = FakeOwnership()  # nothing owned: refused before the slot is taken
    assert export(_own_rows(), ports=ports, concurrency=slots).reason is OpsReason.NOT_FOUND
    assert slots.active("t1", "export") == 0


# ---- hostile input -------------------------------------------------------------------------------

_RECURSIVE = []
_RECURSIVE.append(_RECURSIVE)


@pytest.mark.parametrize("value", [1.5, float("nan"), Decimal("NaN"), Decimal("Infinity"), b"bytes", object(),
                                   EvilStr("v"), "v\x00v", NAIVE, [1], {"a": 1}, _RECURSIVE, {1, 2}, 1j], ids=lambda v: type(v).__name__)
def test_hostile_cell_values_are_refused_without_echo(value):
    out = export([_row(name=value)])
    assert isinstance(out, OpsRefusal) and out.reason is OpsReason.INPUT_INVALID
    assert "bytes" not in repr(out)


@pytest.mark.parametrize("rows", [None, "rows", 5, {"a": 1}, [None], [[]], ["x"], [EvilDict(tenant_id="t1", company_id="c1")],
                                  [{"company_id": "c1"}], [{"tenant_id": "t1"}], [{"tenant_id": EvilStr("t1"), "company_id": "c1"}],
                                  [{"tenant_id": 1, "company_id": "c1"}], [{"tenant_id": "t1", "company_id": None}],
                                  [_row(**{"": 1})], [_row(**{"a\x00": 1})], [{**_row(), 5: 1}]])
def test_hostile_row_containers_are_refused_not_raised(rows):
    out = export(rows)
    assert isinstance(out, OpsRefusal) and out.reason is OpsReason.INPUT_INVALID


def test_hostile_policy_and_request_objects_are_refused():
    for policy in (None, {}, "p", object(), object.__new__(ExportPolicy)):
        out = build_export(SCOPE, REQ, [], policy, Ports(), Ports(), FakeCorrelationSource())
        assert isinstance(out, OpsRefusal) and out.reason is OpsReason.INPUT_INVALID
    forged = object.__new__(ExportPolicy)
    object.__setattr__(forged, "columns", (("a", "PUBLIC"),))
    for attr, value in (("max_rows", 1), ("max_cell_chars", 1), ("max_bytes", 1)):
        object.__setattr__(forged, attr, value)
    assert build_export(SCOPE, REQ, [], forged, Ports(), Ports(), FakeCorrelationSource()).reason is OpsReason.INPUT_INVALID
    forged_req = object.__new__(ExportRequest)
    assert build_export(SCOPE, forged_req, [], _policy(), Ports(), Ports(), FakeCorrelationSource()).reason is OpsReason.INPUT_INVALID


@pytest.mark.parametrize("bad", [None, 5, "", "  ", "a\x00b", "x" * 10_000, EvilStr("e"), b"e", ["e"], "e\u200b1"])
def test_export_request_rejects_hostile_ids_with_a_fixed_code(bad):
    with pytest.raises(ValueError, match="EXPORT_REQUEST_INVALID") as info:
        ExportRequest(bad)
    assert "xxxx" not in str(info.value)


def test_policy_validation_has_one_fixed_code_and_no_echo():
    good = {"a": P}
    for mapping in (None, [], {"tenant_id": P}, {"company_id": P}, {"": P}, {"a\x00": P}, {"x" * 129: P}, {5: P},
                    {"a": "PUBLIC"}, {"a": None}, {EvilStr("a"): P}, {f"c{i}": P for i in range(65)}, EvilDict(a=P)):
        with pytest.raises(ValueError, match="EXPORT_POLICY_INVALID"):
            ExportPolicy.from_mapping(mapping)
    for limits in ({"max_rows": 0}, {"max_rows": True}, {"max_rows": 10**9}, {"max_cell_chars": 0},
                   {"max_cell_chars": 1.5}, {"max_bytes": -1}, {"max_bytes": 10**10}):
        with pytest.raises(ValueError, match="EXPORT_POLICY_INVALID"):
            ExportPolicy.from_mapping(good, **limits)
    with pytest.raises(ValueError, match="EXPORT_POLICY_INVALID"):
        ExportPolicy((("b", P), ("a", P)))  # unsorted
    with pytest.raises(ValueError, match="EXPORT_POLICY_INVALID"):
        ExportPolicy((("a", P), ("a", M)))  # duplicate
    assert "tenant_id" not in repr(ExportPolicy.from_mapping(good))
    assert ExportPolicy.from_mapping(good).policy_digest == ExportPolicy.from_mapping(dict(good)).policy_digest


def test_result_cannot_be_forged_or_given_a_caller_verdict():
    good = export(_own_rows())
    kwargs = {f.name: getattr(good, f.name) for f in dataclasses.fields(ExportResult)}
    assert ExportResult(**kwargs) == good
    for name, value in (("export_digest", "e" * 64), ("neutralized_cells", 3), ("header", ("x",)),
                        ("authority", "OTHER"), ("hidden_by_scope", 1), ("denied_values", -1),
                        ("rows", (("only-one",),))):
        with pytest.raises(ValueError, match="EXPORT_RESULT_INVALID"):
            ExportResult(**{**kwargs, name: value})
    assert {f.name for f in dataclasses.fields(ExportResult)}.isdisjoint({"verdict", "safe", "approved", "findings"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        good.header = ()  # type: ignore[misc]
    assert repr(good) == "ExportResult(<redacted>)" and not hasattr(good, "__dict__")


def test_public_functions_never_raise_on_garbage():
    junk = (None, 0, "", object(), [], {}, (), EvilStr("x"), float("nan"), b"x")
    for a in junk:
        for b in junk:
            assert isinstance(build_export(a, b, a, b, a, b, a, b), OpsRefusal)


def test_ports_that_raise_give_dependency_failed_and_a_failing_id_source_still_refuses():
    class Raising:
        def entitled(self, *a):
            raise RuntimeError("POISON")

        def owns(self, *a):
            raise RuntimeError("POISON")

    class Broken:
        def next_id(self):
            raise RuntimeError("POISON")

    out = build_export(SCOPE, REQ, [], _policy(), Raising(), Raising(), Broken())
    assert out.reason is OpsReason.DEPENDENCY_FAILED and out.correlation_id == "CORR-UNASSIGNED"
    assert "POISON" not in repr(out)


def test_rows_are_snapshotted_so_later_caller_mutation_cannot_change_the_result():
    rows = _own_rows()
    result = export(rows)
    rows[0]["note"] = "CHANGED"
    rows.append(_row(name="late"))
    assert "CHANGED" not in _text(result) and len(result.rows) == 2


# ---- source boundaries ---------------------------------------------------------------------------

_FORBIDDEN = {"httpx", "requests", "socket", "subprocess", "os", "pathlib", "random", "secrets", "time", "shutil",
              "threading", "sqlite3", "psycopg", "psycopg2", "asyncpg", "urllib", "http", "ctypes", "io", "csv",
              "zipfile"}
_DELETE_WORDS = ("delete", "remove", "unlink", "rmtree", "rmdir", "truncate", "drop")


def test_module_has_no_forbidden_import_no_release1_no_delete_call_and_never_evaluates():
    path = _SRC / "export_safety.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [("." * node.level) + (node.module or "")]
        for name in names:
            low = name.lower()
            assert name.lstrip(".").split(".")[0] not in _FORBIDDEN, name
            assert "release1" not in low and "release_1" not in low and "pdcc" not in low, name
            assert not name.startswith(".."), name
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            assert not any(w in called.lower() for w in _DELETE_WORDS), called
            if isinstance(func, ast.Name):
                assert called not in {"eval", "exec", "compile", "__import__", "open"}, called
            assert called not in {"system", "popen"}, called
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not any(w in node.name.lower() for w in _DELETE_WORDS), node.name
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not any(
                getattr(t, "id", "") == "__all__" for t in getattr(node, "targets", [])):
            assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp))
