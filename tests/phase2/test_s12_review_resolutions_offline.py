"""CR-395 review resolutions (S12 contract amendment 2026-10-28, section "Review resolutions").

Offline and pure: no PostgreSQL, no 1C, no network, no clock, no randomness.

Contracts covered:
  (a) BEGIN_APPLY fails closed on missing period evidence (``period_observed_open``): closed -> PERIOD_CLOSED,
      not observed -> DIGEST_MISMATCH, observed open -> proceeds. Every kind of claimed change is covered.
  (b) an unknown ``vat_rate_code`` is AMOUNT_INCONSISTENT on both parsers; the engine VAT table equals the writer table.
  (c) an ArithmeticError inside the amount check is SCHEMA_INVALID and never escapes a parser.
  (d) ``map_executor_refusal`` against the codes the executor really defines.

Run: .venv\\Scripts\\python.exe -m pytest -p no:cacheprovider -q tests/phase2/test_s12_review_resolutions_offline.py
"""
from __future__ import annotations

import ast
import copy
import decimal
import pathlib
import re
from decimal import ROUND_HALF_UP, Context, Decimal

import pytest

import business_ai_gateway.phase2.change as ch
import business_ai_gateway.phase2.change.proposal as proposal_module
from business_ai_gateway.phase2.change import (
    Applied,
    ChangeKind,
    ErrorCode,
    Event,
    Execution,
    Refusal,
    apply_transition,
)
from business_ai_gateway.phase2.change.proposal import (
    DraftPayload,
    parse_writer_payload,
    vat_rate_percent_table,
)
from business_ai_gateway.phase2.change.transitions import BeginApplyEvidence
from erp_mcp_private_writer import com_vat_table
from erp_mcp_private_writer.refusal_mapping import (
    EXECUTOR_REFUSAL_CODES,
    RefusalEvent,
    map_executor_refusal,
)
from tests.phase2 import _change_helpers as h
from tests.phase2._change_helpers import T0, claimed, raw_create

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXECUTOR_SOURCE = ROOT / "src" / "erp_mcp_private_writer" / "com_draft_executor.py"
VAT_TABLE_SOURCE = ROOT / "src" / "erp_mcp_private_writer" / "com_vat_table.py"


def _step(record, event, now=T0, **over):
    return apply_transition(record, event, h.good(event, record, now, **over))


def _refused(res, code, transition=None):
    assert type(res) is Refusal, res
    assert res.code is ErrorCode(code), (res.code, code)
    if transition is not None:
        assert res.transition == transition


def _line(code="VAT20", amount="21.00", vat="3.50", quantity="2", price="10.50") -> dict:
    return {"item_ref": "it-1", "quantity": quantity, "price": price, "vat_rate_code": code, "amount": amount,
            "vat_amount": vat}


def _raw(line: dict, kind: str = "CREATE_DRAFT") -> dict:
    raw = raw_create()
    raw["payload"]["lines"] = [line]
    if kind == "UPDATE_DRAFT":
        raw.update(kind=kind, target_ref="doc1", target_version="v1")
        raw["payload"]["expected_target_version"] = "v1"
    return raw


def _both(raw: dict):
    """The proposal path and the writer path for the same payload (the writer path takes CREATE_DRAFT payloads)."""
    via_proposal = ch.parse_proposal(raw, h.ctx())
    via_writer = parse_writer_payload(copy.deepcopy(raw["payload"]), ChangeKind.CREATE_DRAFT, h.SCOPE)
    return via_proposal, via_writer


# ---------------------------------------------------------------------------------------------------------------------
# (a) BEGIN_APPLY needs a positive "period observed open"
# ---------------------------------------------------------------------------------------------------------------------

def _unpost_repair_claim():
    return h.repair_live(claimed)


CLAIMED_KINDS = {
    "create": claimed,
    "update": lambda: claimed(kind=ChangeKind.UPDATE_DRAFT, target_ref="doc9"),
    "post": lambda: claimed(kind=ChangeKind.POST, parent_change_id="parent9", target_ref="doc9"),
    "unpost_repair": _unpost_repair_claim,
}


def test_the_evidence_default_is_not_observed_so_a_producer_that_forgets_the_field_cannot_pass():
    assert BeginApplyEvidence.__dataclass_fields__["period_observed_open"].default is False
    assert BeginApplyEvidence.__dataclass_fields__["period_closed"].default is False


@pytest.mark.parametrize("kind", list(CLAIMED_KINDS))
def test_positive_control_an_observed_open_period_begins_the_apply_for_every_kind(kind):
    record = CLAIMED_KINDS[kind]()
    res = _step(record, Event.BEGIN_APPLY)  # helper evidence carries period_observed_open=True
    assert type(res) is Applied, (kind, res)
    assert res.record.execution is Execution.APPLYING


@pytest.mark.parametrize("kind", list(CLAIMED_KINDS))
def test_missing_period_observation_refuses_begin_apply_with_digest_mismatch_for_every_kind(kind):
    record = CLAIMED_KINDS[kind]()
    before = copy.deepcopy(record)
    for extra in ({}, {"period_closed": False}, {"state_digest_equal": False}):
        res = _step(record, Event.BEGIN_APPLY, period_observed_open=False, **extra)
        _refused(res, "DIGEST_MISMATCH", "T6")
    assert record == before and record.execution is Execution.NOT_STARTED


@pytest.mark.parametrize("not_true", [None, 1, "True", 0, ()], ids=repr)
def test_only_the_exact_bool_true_counts_as_an_observation(not_true):
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_observed_open=not_true), "DIGEST_MISMATCH", "T6")


@pytest.mark.parametrize("kind", list(CLAIMED_KINDS))
def test_closed_period_is_period_closed_even_when_the_open_observation_is_also_set(kind):
    # contradictory evidence resolves to the refusal, never to a pass
    for observed in (True, False):
        for digest_equal in (True, False):
            res = _step(CLAIMED_KINDS[kind](), Event.BEGIN_APPLY, period_closed=True, period_observed_open=observed,
                        state_digest_equal=digest_equal)
            _refused(res, "PERIOD_CLOSED", "T6")


def test_observed_open_does_not_replace_the_state_digest_guard():
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_observed_open=True, state_digest_equal=False),
             "DIGEST_MISMATCH", "T6")


def test_the_observation_does_not_outrank_earlier_guards():
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_observed_open=False, version_equals_approved=False),
             "STALE_VERSION")
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_observed_open=False, fingerprint_authenticated=False),
             "TARGET_REJECTED")
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_observed_open=False, kill=h.UNREADABLE), "KILL_SWITCH_ACTIVE")
    # and it outranks the later guards (lock and ownership row are checked after the period)
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_observed_open=False, writer_lock_held=False), "DIGEST_MISMATCH")
    _refused(_step(claimed(), Event.BEGIN_APPLY, period_observed_open=False, ownership_row_committed=False),
             "DIGEST_MISMATCH")


def test_full_path_without_the_observation_never_reaches_applying_and_no_permit_follows():
    record = claimed()
    res = _step(record, Event.BEGIN_APPLY, period_observed_open=False)
    _refused(res, "DIGEST_MISMATCH")
    assert type(_step(record, Event.ISSUE_PERMIT)) is Refusal
    assert type(_step(record, Event.MARK_DISPATCHED)) is Refusal
    # the same record with the observation proceeds, so the refusal above is caused by the missing observation only
    applied = _step(record, Event.BEGIN_APPLY)
    assert type(applied) is Applied and type(_step(applied.record, Event.ISSUE_PERMIT)) is Applied


def test_replay_of_an_existing_ticket_is_not_re_gated_by_the_observation():
    started = _step(claimed(), Event.BEGIN_APPLY)
    assert type(started) is Applied
    replay = _step(started.record, Event.BEGIN_APPLY, period_observed_open=False)
    assert type(replay) is Applied and replay.record == started.record


# ---------------------------------------------------------------------------------------------------------------------
# (b) unknown VAT code and the engine / writer VAT tables
# ---------------------------------------------------------------------------------------------------------------------

# Valid identity texts (non-empty, printable, no whitespace, at most 32 characters) that are not table codes.
UNKNOWN_CODES = ["VAT18", "VATX", "vat20", "VAT_20", "NOVAT", "0", "-", "_", ".", "x", "V" * 32]


@pytest.mark.parametrize("code", UNKNOWN_CODES)
@pytest.mark.parametrize("kind", ["CREATE_DRAFT", "UPDATE_DRAFT"])
def test_unknown_vat_code_is_amount_inconsistent_on_both_parsers_whatever_the_vat_amount(code, kind):
    for vat in ("0", "3.5", "17", "999999.123456"):
        raw = _raw(_line(code=code, vat=vat), kind)
        via_proposal = ch.parse_proposal(raw, h.ctx())
        assert type(via_proposal) is Refusal and via_proposal.code is ErrorCode.AMOUNT_INCONSISTENT, (code, vat)
        if kind == "CREATE_DRAFT":
            via_writer = parse_writer_payload(copy.deepcopy(raw["payload"]), ChangeKind.CREATE_DRAFT, h.SCOPE)
            assert type(via_writer) is Refusal and via_writer.code is ErrorCode.AMOUNT_INCONSISTENT, (code, vat)


@pytest.mark.parametrize("code", ["", " ", "VAT 20", "V" * 33])
def test_a_vat_code_that_is_not_identity_text_is_still_a_schema_refusal_not_an_amount_refusal(code):
    for res in _both(_raw(_line(code=code))):
        assert type(res) is Refusal and res.code is ErrorCode.SCHEMA_INVALID, (code, res)


def test_positive_control_the_table_codes_with_consistent_amounts_still_parse():
    for code, vat in (("VAT0", "0"), ("VAT10", "1.91"), ("VAT20", "3.5")):
        proposal, writer = _both(_raw(_line(code=code, vat=vat)))
        assert type(proposal) is ch.ChangeProposal, (code, proposal)
        assert type(writer) is DraftPayload, (code, writer)


def test_vat_on_top_documents_are_refused_like_unknown_rates():
    # vat_amount = amount x rate / 100 (VAT on top of the amount) is not the supported convention
    _, writer = _both(_raw(_line(code="VAT20", amount="21.00", vat="4.20")))
    assert type(writer) is Refusal and writer.code is ErrorCode.AMOUNT_INCONSISTENT


def test_engine_vat_table_has_the_expected_closed_content():
    assert vat_rate_percent_table() == {"VAT0": "0", "VAT10": "10", "VAT20": "20"}


def test_engine_vat_table_is_a_copy_so_callers_cannot_change_the_rates():
    table = vat_rate_percent_table()
    table["VAT20"] = "18"
    table["VAT18"] = "18"
    assert vat_rate_percent_table() == {"VAT0": "0", "VAT10": "10", "VAT20": "20"}


def _writer_table_percent_from_its_documentation() -> dict[str, str]:
    """The rate each writer table entry documents, read from the writer source (the enum names are legacy: НДС18 = 20)."""
    pattern = re.compile(r'^\s*\("(?P<code>VAT[0-9]+)",\s*"[^"]+"\),\s*#\s*(?P<percent>[0-9]+) percent', re.MULTILINE)
    found = {m["code"]: m["percent"] for m in pattern.finditer(VAT_TABLE_SOURCE.read_text(encoding="utf-8"))}
    return found


def test_engine_vat_table_equals_the_rates_implied_by_the_writer_vat_table():
    writer_codes = {code for code, _ in com_vat_table.VAT_RATE_CODE_TO_ENUM_VALUE}
    documented = _writer_table_percent_from_its_documentation()
    # every writer entry has a documented percent (guards the parsing above against a silent format change)
    assert set(documented) == writer_codes and len(writer_codes) >= 3
    engine = vat_rate_percent_table()
    assert set(engine) == writer_codes  # same keys: a code added on one side only fails here
    assert engine == documented         # same rates
    assert engine["VAT20"] == "20" and dict(com_vat_table.VAT_RATE_CODE_TO_ENUM_VALUE)["VAT20"] == "НДС18"


def test_every_writer_table_code_is_accepted_by_the_engine_with_a_consistent_vat_amount():
    for code, percent in vat_rate_percent_table().items():
        rate = Decimal(percent)
        vat = (Decimal("21.00") * rate / (100 + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        text = format(vat.normalize(), "f") if vat else "0"
        proposal, writer = _both(_raw(_line(code=code, vat=text)))
        assert type(proposal) is ch.ChangeProposal and type(writer) is DraftPayload, (code, text, proposal, writer)


# ---------------------------------------------------------------------------------------------------------------------
# (c) ArithmeticError inside the amount check
# ---------------------------------------------------------------------------------------------------------------------

def _strict_context() -> Context:
    # prec=1 cannot hold 2 x 10.50 = 21; with Inexact trapped the context raises decimal.Inexact (an ArithmeticError)
    return Context(prec=1, rounding=ROUND_HALF_UP, traps=[decimal.InvalidOperation, decimal.Inexact])


def test_the_provoked_error_really_is_an_arithmetic_error_of_the_decimal_module():
    with pytest.raises(ArithmeticError):
        _strict_context().multiply(Decimal("2"), Decimal("10.50"))


def test_control_the_same_input_parses_with_the_real_context():
    proposal, writer = _both(_raw(_line()))
    assert type(proposal) is ch.ChangeProposal and type(writer) is DraftPayload


def test_arithmetic_error_in_the_amount_check_is_schema_invalid_on_every_parser_entry(monkeypatch):
    monkeypatch.setattr(proposal_module, "_MONEY_CONTEXT", _strict_context())
    raw = _raw(_line())
    # parse_proposal (CREATE_DRAFT and UPDATE_DRAFT)
    for kind in ("CREATE_DRAFT", "UPDATE_DRAFT"):
        res = ch.parse_proposal(_raw(_line(), kind), h.ctx())
        assert type(res) is Refusal and res.code is ErrorCode.SCHEMA_INVALID, (kind, res)
    # parse_writer_payload
    res = parse_writer_payload(copy.deepcopy(raw["payload"]), ChangeKind.CREATE_DRAFT, h.SCOPE)
    assert type(res) is Refusal and res.code is ErrorCode.SCHEMA_INVALID
    # _parse_draft itself (the shared helper): it returns the refusal, it does not raise
    res = proposal_module._parse_draft(copy.deepcopy(raw["payload"]), ChangeKind.CREATE_DRAFT, h.SCOPE, None)
    assert type(res) is Refusal and res.code is ErrorCode.SCHEMA_INVALID


def test_arithmetic_error_is_not_reported_as_an_amount_mismatch_or_a_pass(monkeypatch):
    monkeypatch.setattr(proposal_module, "_MONEY_CONTEXT", _strict_context())
    res = parse_writer_payload(copy.deepcopy(_raw(_line())["payload"]), ChangeKind.CREATE_DRAFT, h.SCOPE)
    assert res.code is not ErrorCode.AMOUNT_INCONSISTENT
    # and an unrelated honest refusal still wins where it is decided before the arithmetic (structure)
    broken = _raw(_line())
    broken["payload"]["lines"][0]["extra"] = "1"
    res2 = parse_writer_payload(copy.deepcopy(broken["payload"]), ChangeKind.CREATE_DRAFT, h.SCOPE)
    assert res2.code is ErrorCode.SCHEMA_INVALID


# ---------------------------------------------------------------------------------------------------------------------
# (d) executor refusal mapping, checked against the codes com_draft_executor really defines
# ---------------------------------------------------------------------------------------------------------------------

def _executor_codes_with_flags() -> dict[str, bool]:
    """Every COM_* code literal in the executor source, with True when any raise site passes outcome_unknown=True."""
    tree = ast.parse(EXECUTOR_SOURCE.read_text(encoding="utf-8"))
    codes: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r"COM_[A-Z_]+", node.value):
            codes.setdefault(node.value, False)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"_refusal", "_guarded"}
                and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[1], ast.Constant) and node.args[1].value is True):
            codes[node.args[0].value] = True
    return codes


EXECUTOR_CODES = _executor_codes_with_flags()


def test_the_mapping_table_lists_exactly_the_codes_the_executor_defines_with_the_same_flag():
    assert len(EXECUTOR_CODES) >= 17  # the scan found the codes (guards against an empty scan passing vacuously)
    assert set(EXECUTOR_REFUSAL_CODES) == set(EXECUTOR_CODES), (
        set(EXECUTOR_CODES) - set(EXECUTOR_REFUSAL_CODES), set(EXECUTOR_REFUSAL_CODES) - set(EXECUTOR_CODES))
    assert dict(EXECUTOR_REFUSAL_CODES) == EXECUTOR_CODES
    assert len(EXECUTOR_REFUSAL_CODES) == 17


def test_event_names_are_members_of_the_change_engine_event_enum():
    assert {e.value for e in RefusalEvent} == {"CALL_UNKNOWN", "REFUSED_BEFORE_WRITE"}
    for member in RefusalEvent:
        assert Event[member.value] is not None


@pytest.mark.parametrize("code", sorted(EXECUTOR_CODES))
def test_every_executor_code_maps_pre_write_refusals_to_refused_before_write_and_the_rest_to_unknown(code):
    unknown_flag = EXECUTOR_CODES[code]
    expected = RefusalEvent.CALL_UNKNOWN if unknown_flag else RefusalEvent.REFUSED_BEFORE_WRITE
    assert map_executor_refusal(code, unknown_flag) is expected
    # the flag the executor did not use for this code is never trusted: ambiguity stays UNKNOWN
    assert map_executor_refusal(code, not unknown_flag) is RefusalEvent.CALL_UNKNOWN


@pytest.mark.parametrize("code", sorted(EXECUTOR_CODES))
def test_outcome_unknown_true_is_always_call_unknown(code):
    assert map_executor_refusal(code, True) is RefusalEvent.CALL_UNKNOWN


def test_the_two_post_write_codes_are_the_only_unknown_ones():
    unknown = {c for c, flag in EXECUTOR_CODES.items() if flag}
    assert unknown == {"COM_WRITE_OUTCOME_UNKNOWN", "COM_WRITTEN_READBACK_MISMATCH"}
    assert {c for c in EXECUTOR_CODES if map_executor_refusal(c, EXECUTOR_CODES[c]) is RefusalEvent.CALL_UNKNOWN} == unknown


@pytest.mark.parametrize("code", ["", "COM_NEW_CODE", "com_reference_not_found", "COM_REFERENCE_NOT_FOUND ",
                                  "SCHEMA_INVALID", "PERIOD_CLOSED", "0"])
@pytest.mark.parametrize("outcome_unknown", [False, True])
def test_unknown_code_is_call_unknown_whatever_the_flag(code, outcome_unknown):
    assert map_executor_refusal(code, outcome_unknown) is RefusalEvent.CALL_UNKNOWN


@pytest.mark.parametrize("code,flag", [(None, False), (b"COM_REFERENCE_NOT_FOUND", False), (1, False),
                                       ("COM_REFERENCE_NOT_FOUND", None), ("COM_REFERENCE_NOT_FOUND", 0),
                                       ("COM_REFERENCE_NOT_FOUND", "False")], ids=repr)
def test_malformed_input_never_fails_open_to_a_definite_failure(code, flag):
    assert map_executor_refusal(code, flag) is RefusalEvent.CALL_UNKNOWN  # type: ignore[arg-type]


def test_a_mapped_event_drives_the_engine_to_the_state_the_name_promises():
    dispatched = h.dispatched()
    pre = apply_transition(dispatched, Event[map_executor_refusal("COM_REFERENCE_NOT_FOUND", False).value],
                           h.good(Event.REFUSED_BEFORE_WRITE, dispatched))
    assert type(pre) is Applied and pre.record.execution is Execution.FAILED_APPLY
    post = apply_transition(dispatched, Event[map_executor_refusal("COM_WRITE_OUTCOME_UNKNOWN", True).value],
                            h.good(Event.CALL_UNKNOWN, dispatched))
    assert type(post) is Applied and post.record.execution is Execution.APPLY_UNKNOWN
