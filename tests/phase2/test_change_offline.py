"""S12 offline change package: focused functional tests against contract revision 6.

Contract: docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md. Every expectation below is written from the contract
text (sections 2, 3, 4, 4.1, 4.2, 6, 8, 10), not read back from the implementation tables.
"""
from __future__ import annotations

import dataclasses
import hashlib
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import business_ai_gateway.phase2.change as ch
import business_ai_gateway.phase2.change.killswitch as kill_mod
import business_ai_gateway.phase2.change.policy as policy_mod
import business_ai_gateway.phase2.change.proposal as proposal_mod
import business_ai_gateway.phase2.change.transitions as tr_mod
import business_ai_gateway.phase2.change.types as types_mod
from business_ai_gateway.phase2.change import (
    SWITCH_OFF,
    Applied,
    ApprovalType,
    Attribution,
    Authorization,
    BudgetCheck,
    CallerClass,
    CallOwnership,
    ChangeKind,
    ChangeProposal,
    ChangeRecord,
    Dispatch,
    EffectKind,
    EffectKnown,
    ErrorCode,
    Event,
    Execution,
    FailureStage,
    Grant,
    Hold,
    HoldCause,
    KillDecision,
    KillMode,
    KillSubject,
    LedgerOperation,
    Lifecycle,
    LogicalKeyState,
    NonceState,
    ProofClass,
    Refusal,
    ReleaseReason,
    RepairAuth,
    Reservation,
    ResolveOutcome,
    RevokeCause,
    Scope,
    SwitchReading,
    TokenState,
    Verification,
    apply_transition,
)
from tests.phase2 import _change_helpers as h
from tests.phase2._change_helpers import (
    APPROVAL_EXPIRES,
    APPROVER,
    HALT,
    OPERATOR,
    REPAIR_APPROVER,
    REPAIR_AUTH,
    REPAIR_ID,
    REQUESTER,
    SCOPE,
    T0,
    UNREADABLE,
    applied,
    applying,
    approved,
    claimed,
    dispatched,
    failed_verify,
    good,
    kill,
    proposed,
    raw_create,
    raw_post,
    repair_ctx,
    repair_live,
    repair_rec,
    triage,
    unknown,
    validated,
)

CONTRACT_ERROR_CODES = (
    "SCHEMA_INVALID", "SHAPE_NOT_QUALIFIED", "SCOPE_MISMATCH", "REF_OUT_OF_SCOPE", "NOT_ENTITLED",
    "APPROVER_NOT_INDEPENDENT", "APPROVAL_MISSING", "APPROVAL_EXPIRED", "APPROVAL_VOIDED", "APPROVAL_NONCE_INVALID",
    "COMPLETION_PROOF_MISSING", "ATTRIBUTION_UNPROVEN", "PERMIT_MISSING", "TICKET_SUPERSEDED", "DIGEST_MISMATCH",
    "STALE_VERSION", "IDEMPOTENCY_CONFLICT", "DUPLICATE_SUSPECTED", "EPOCH_CHANGED", "TARGET_REJECTED",
    "KILL_SWITCH_ACTIVE", "BASE_HOLD", "PARENT_NOT_VERIFIED", "CLAIM_EXPIRED", "BUDGET_EXCEEDED",
    "CURRENCY_NOT_BUDGETED", "AUDIT_UNAVAILABLE", "CHECKPOINT_UNAVAILABLE", "LOCK_BUSY", "WRITE_REFUSED",
    "APPLY_UNKNOWN", "TRIAGE_REQUIRED", "ROLLBACK_REFUSED", "VERIFY_FAILED", "MARKER_UNTRUSTED", "EVIDENCE_UNSIGNED",
)


def step(record, event, now=T0, **over):
    return apply_transition(record, event, good(event, record, now, **over))


def ok(res, tid=None) -> ChangeRecord:
    assert type(res) is Applied, res
    if tid is not None:
        assert res.transition == tid
    return res.record


def refused(res, code, tid=None) -> None:
    assert type(res) is Refusal, res
    assert res.code is ErrorCode(code), (res.code, code)
    if tid is not None:
        assert res.transition == tid


# =====================================================================================================================
# 1. import and import-time completeness guards
# =====================================================================================================================

def test_package_imports_and_exports_resolve():
    assert ch.__all__
    for name in ch.__all__:
        assert hasattr(ch, name), name
    assert len(set(ch.__all__)) == len(ch.__all__)


def _enums_of(module):
    import enum
    return [v for v in vars(module).values()
            if isinstance(v, type) and issubclass(v, enum.Enum) and v.__module__ == module.__name__]


@pytest.mark.parametrize("module, guard", [(types_mod, "_EXPECTED"), (tr_mod, "_EXPECTED_ENUMS")])
def test_every_enum_of_a_module_is_covered_by_its_completeness_guard(module, guard):
    guarded = {cls for cls, _ in getattr(module, guard)}
    assert set(_enums_of(module)) <= guarded


def test_closed_dimension_vocabularies_equal_contract_section_4():
    expected = {
        types_mod.Lifecycle: {"PROPOSED", "VALIDATED", "REJECTED", "EXPIRED_QUEUED", "DUPLICATE_PARKED"},
        types_mod.Authorization: {"NONE", "APPROVED", "CLAIMED", "VOIDED", "REVOKED", "EXPIRED"},
        types_mod.Execution: {"NOT_STARTED", "APPLYING", "APPLY_UNKNOWN", "APPLIED", "FAILED_APPLY",
                              "TRIAGE_REQUIRED", "ROLLBACK_REFUSED"},
        types_mod.Verification: {"NOT_VERIFIED", "VERIFIED", "FAILED_VERIFY"},
        types_mod.CallOwnership: {"NONE", "PROVEN_FINISHED", "POSSIBLY_EXECUTING"},
        types_mod.Attribution: {"NOT_APPLICABLE", "PROVEN", "UNPROVEN_OPERATOR_ATTESTED"},
        types_mod.EffectKnown: {"YES", "NO", "UNKNOWN"},
        types_mod.Reservation: {"NONE", "RESERVED", "CONSUMED", "RELEASED"},
        types_mod.Dispatch: {"NOT_PERMITTED", "PERMITTED", "CANCELLED_UNDISPATCHED", "DISPATCHED"},
        types_mod.HoldCause: {"CALL_OWNERSHIP", "ANCHOR_GAP", "FAILED_VERIFY_HALT", "RLC_UNCLEAN"},
        types_mod.ChangeKind: {"CREATE_DRAFT", "UPDATE_DRAFT", "POST", "UNPOST"},
        types_mod.KillMode: {"STOP_ADMIT", "STOP_EFFECTS", "REVOKE"},
        types_mod.CallerClass: {"REQUESTER", "APPROVER", "OPERATOR", "RECOVERY_WITNESS", "WRITER",
                                "RECOVERY_WORKER", "AUDITOR"},
        types_mod.TokenState: {"NONE", "ISSUED", "CONSUMED", "SUPERSEDED", "REVOKED"},
        types_mod.NonceState: {"ISSUED", "CONSUMED", "EXPIRED"} | {"INVALID"},
        types_mod.EvidenceKind: {"FIELD", "MOVEMENT", "VERSION", "AUTHORIZATION_RECEIPT"},
    }
    for cls, names in expected.items():
        assert {m.name for m in cls} == names, cls
        assert all(m.value == m.name for m in cls)


def test_import_time_guards_are_live_not_vacuous():
    # the guard tables must reference real classes with real members (a vacuous guard would never fire)
    assert len(types_mod._EXPECTED) >= 15 and all(len(names) >= 2 for _, names in types_mod._EXPECTED)
    assert len(tr_mod._EXPECTED_ENUMS) >= 8
    # table / handler / guard / evidence completeness holds on the live module
    keys = [r.key for r in tr_mod.TRANSITION_TABLE]
    assert len(keys) == len(set(keys)) and set(keys) == set(tr_mod._HANDLERS)
    assert {g for r in tr_mod.TRANSITION_TABLE for g in r.guards} == set(tr_mod._GUARDS)
    assert set(tr_mod.EVENT_EVIDENCE) == set(Event) == {r.event for r in tr_mod.TRANSITION_TABLE}
    assert set(kill_mod.KILL_MATRIX) == {(s, m) for s in KillSubject for m in KillMode}
    assert set(proposal_mod.OPERATION_RULES) == set(ChangeKind)
    assert set(policy_mod.CALLER_MATRIX) == set(CallerClass)


# =====================================================================================================================
# 2. error registry (contract section 10)
# =====================================================================================================================

def test_error_registry_has_exactly_the_contract_codes():
    assert [c.value for c in ErrorCode] == list(CONTRACT_ERROR_CODES)
    assert len(CONTRACT_ERROR_CODES) == 36
    assert set(ch.ERROR_INFO) == set(ErrorCode)


def test_every_code_has_one_fixed_safe_message_and_next_action():
    for code in ErrorCode:
        info = ch.render(code)
        assert info is ch.ERROR_INFO[code]
        assert type(info.message) is str and info.message and info.message.isascii()
        assert info.message.endswith(".") and not any(c in info.message for c in "{}%$\\/")
        assert type(info.next_action) is ch.NextAction
        assert ch.render(code) == info  # constant
        assert Refusal(code, "T1").message == info.message and Refusal(code).next_action is info.next_action


def test_render_of_a_non_code_is_schema_invalid_and_never_echoes():
    secret = "super-secret-token-123"
    for bogus in (secret, None, 5, ["SCHEMA_INVALID"], object()):
        assert ch.render(bogus) is ch.ERROR_INFO[ErrorCode.SCHEMA_INVALID]
    # a plain string equal to a code name is not an ErrorCode instance either
    assert ch.render("NOT_ENTITLED") is ch.ERROR_INFO[ErrorCode.SCHEMA_INVALID]


def test_refusal_is_code_only_and_validates_its_inputs():
    with pytest.raises(ValueError):
        Refusal("SCHEMA_INVALID")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Refusal(ErrorCode.SCHEMA_INVALID, "x" * 17)
    assert repr(Refusal(ErrorCode.BASE_HOLD, "T5")) == "Refusal(BASE_HOLD)"


def test_refusals_never_echo_caller_input():
    secret = "SECRET-PAYLOAD-VALUE-777"
    raw = raw_create(payload_over={"comment": secret, "currency": secret, "unknown_key": secret})
    res = ch.parse_proposal(raw, h.ctx())
    refused(res, "SCHEMA_INVALID")
    assert secret not in repr(res) and secret not in res.message
    raw = raw_create(payload_over={"organization_ref": secret})
    res = ch.parse_proposal(raw, h.ctx())
    refused(res, "SCOPE_MISMATCH")
    assert secret not in repr(res) and secret not in res.message


# =====================================================================================================================
# 3. proposal parsing, canonical digest, scope
# =====================================================================================================================

def test_parse_valid_create_canonicalizes_decimals_and_derives_effects():
    p = h.proposal()
    assert type(p) is ChangeProposal and p.kind is ChangeKind.CREATE_DRAFT
    line = p.payload.lines[0]
    assert (line.quantity, line.price, line.amount) == ("2", "10.5", "21")
    assert p.allowed_effects == () and p.claim_generation == 0 and p.rule_table_version == ch.RULE_TABLE_VERSION
    assert p.target_ref is None and p.business_state_digest is None
    assert p.epoch_dependencies == (("approver", 2), ("requester", 1))
    assert p.duplicate_override is None


def test_post_and_unpost_have_empty_payload_and_server_derived_effects():
    post = h.proposal(raw_post("POST"))
    unpost = h.proposal(raw_post("UNPOST"))
    assert post.payload is None and unpost.payload is None
    assert len(post.allowed_effects) == 2 and post.allowed_effects == ch.derive_allowed_effects(ChangeKind.POST)
    assert unpost.allowed_effects == () == ch.derive_allowed_effects(ChangeKind.CREATE_DRAFT) \
        == ch.derive_allowed_effects(ChangeKind.UPDATE_DRAFT)
    assert post.business_state_digest == "b" * 64


@pytest.mark.parametrize("raw", [
    raw_create(extra_key="x"),
    raw_create(payload_over={"unknown": 1}),
    raw_create(payload_over={"lines": [{"item_ref": "i", "quantity": "1", "price": "1", "vat_rate_code": "V",
                                        "amount": "1", "vat_amount": "0", "extra": "x"}]}),
    raw_create(payload_over={"lines": [{"item_ref": "i", "quantity": "1", "price": "1", "vat_rate_code": "V",
                                        "amount": "1"}]}),  # vat_amount missing
    raw_create(payload_over={"duplicate_override": {"duplicate_of_change_or_ref": "c0", "justification": "j",
                                                    "extra": 1}}),
    raw_create(payload_over={"duplicate_override": {"duplicate_of_change_or_ref": "c0"}}),
])
def test_unknown_or_missing_keys_are_refused(raw):
    refused(ch.parse_proposal(raw, h.ctx()), "SCHEMA_INVALID", "propose")


@pytest.mark.parametrize("where", ["envelope", "payload", "line"])
def test_caller_supplied_allowed_effects_is_refused_with_schema_invalid(where):
    raw = raw_create()
    if where == "envelope":
        raw["allowed_effects"] = []
    elif where == "payload":
        raw["payload"]["allowed_effects"] = []
    else:
        raw["payload"]["lines"][0]["allowed_effects"] = []
    refused(ch.parse_proposal(raw, h.ctx()), "SCHEMA_INVALID")
    post = raw_post("POST", allowed_effects=["anything"])
    refused(ch.parse_proposal(post, h.ctx()), "SCHEMA_INVALID")


@pytest.mark.parametrize("field", ["change_id", "requester_person_id", "requester_principal", "scope",
                                   "claim_generation", "payload_digest", "business_state_digest"])
def test_identity_and_digest_fields_are_never_accepted_from_the_caller(field):
    raw = raw_create()
    raw[field] = "forged"
    refused(ch.parse_proposal(raw, h.ctx()), "SCHEMA_INVALID")


@pytest.mark.parametrize("field, value", [
    ("quantity", 2), ("quantity", 2.0), ("quantity", Decimal(2)), ("quantity", "2.0000001"), ("quantity", "1e3"),
    ("quantity", "1,5"), ("quantity", " 1"), ("quantity", "-1"), ("quantity", "0"), ("quantity", "01"),
    ("quantity", ""), ("quantity", "NaN"), ("price", 10.5), ("price", "-0.01"), ("price", "1.1234567"),
    ("amount", 21.0), ("amount", "abc"), ("amount", None), ("price", "1" * 19),
    ("vat_amount", 3.5), ("vat_amount", "abc"), ("vat_amount", None), ("vat_amount", "-0.01"),
    ("vat_amount", "1e3"), ("vat_amount", Decimal(1)), ("vat_amount", "1.1234567"), ("vat_amount", ""),
])
def test_numeric_fields_must_be_exact_decimal_strings(field, value):
    raw = raw_create()
    raw["payload"]["lines"][0][field] = value
    refused(ch.parse_proposal(raw, h.ctx()), "SCHEMA_INVALID")


def test_zero_price_and_zero_amount_are_valid_decimal_strings():
    raw = raw_create()
    raw["payload"]["lines"][0].update(price="0", amount="0.00", vat_amount="0.000")
    p = h.proposal(raw)
    assert (p.payload.lines[0].price, p.payload.lines[0].amount, p.payload.lines[0].vat_amount) == ("0", "0", "0")


def test_organization_mismatch_is_scope_mismatch_and_other_scope_refs_are_out_of_scope():
    raw = raw_create(payload_over={"organization_ref": "org-2"})
    refused(ch.parse_proposal(raw, h.ctx()), "SCOPE_MISMATCH", "propose")
    refs = frozenset({"org-1", "cp-1", "ct-1", "it-1"})
    assert type(ch.parse_proposal(raw_create(), h.ctx(in_scope_refs=refs))) is ChangeProposal
    for missing in refs - {"org-1"}:
        refused(ch.parse_proposal(raw_create(), h.ctx(in_scope_refs=refs - {missing})), "REF_OUT_OF_SCOPE")
    refused(ch.parse_proposal(raw_post("POST"), h.ctx(in_scope_refs=frozenset({"other"}))), "REF_OUT_OF_SCOPE")
    assert type(ch.parse_proposal(raw_post("POST"), h.ctx(in_scope_refs=frozenset({"doc1"})))) is ChangeProposal


def test_only_the_measured_shape_is_admitted():
    two = raw_create()
    two["payload"]["lines"].append(dict(two["payload"]["lines"][0]))
    refused(ch.parse_proposal(two, h.ctx()), "SHAPE_NOT_QUALIFIED")
    refused(ch.parse_proposal(raw_create(payload_over={"currency": "USD"}), h.ctx()), "SHAPE_NOT_QUALIFIED")
    refused(ch.parse_proposal(raw_create(), h.ctx(qualified_currencies=frozenset())), "SHAPE_NOT_QUALIFIED")


def test_update_draft_is_a_full_replacement_with_matching_expected_version():
    payload_over = {"expected_target_version": "v1"}
    raw = raw_create(kind="UPDATE_DRAFT", target_ref="doc1", target_version="v1", payload_over=payload_over)
    p = h.proposal(raw)
    assert p.kind is ChangeKind.UPDATE_DRAFT and p.payload.expected_target_version == "v1"
    bad = raw_create(kind="UPDATE_DRAFT", target_ref="doc1", target_version="v2", payload_over=payload_over)
    refused(ch.parse_proposal(bad, h.ctx()), "SCHEMA_INVALID")
    no_ver = raw_create(kind="UPDATE_DRAFT", target_ref="doc1", target_version="v1")
    refused(ch.parse_proposal(no_ver, h.ctx()), "SCHEMA_INVALID")
    refused(ch.parse_proposal(raw_create(payload_over=payload_over), h.ctx()), "SCHEMA_INVALID")  # CREATE has none


def test_create_cannot_carry_a_target_and_post_needs_one():
    refused(ch.parse_proposal(raw_create(target_ref="doc1", target_version="v1"), h.ctx()), "SCHEMA_INVALID")
    no_target = raw_post("POST")
    del no_target["target_ref"]
    refused(ch.parse_proposal(no_target, h.ctx()), "SCHEMA_INVALID")
    no_parent = raw_post("POST")
    del no_parent["parent_change_id"]
    refused(ch.parse_proposal(no_parent, h.ctx()), "SCHEMA_INVALID")
    refused(ch.parse_proposal(raw_post("POST"), h.ctx(business_state_digest=None)), "SCHEMA_INVALID")
    with_payload = raw_post("POST", payload={"organization_ref": "org-1"})
    refused(ch.parse_proposal(with_payload, h.ctx()), "SCHEMA_INVALID")


@pytest.mark.parametrize("garbage", [None, [], 5, "x", {}, {"kind": "CREATE_DRAFT"}, {"kind": 7, "request_id": "r"},
                                     {"kind": "NOPE", "request_id": "r"}, {1: 2}])
def test_parse_never_raises_on_garbage(garbage):
    refused(ch.parse_proposal(garbage, h.ctx()), "SCHEMA_INVALID")
    refused(ch.parse_proposal(raw_create(), None), "SCHEMA_INVALID")
    refused(ch.parse_proposal(raw_create(), "ctx"), "SCHEMA_INVALID")


def test_direct_construction_revalidates_derived_fields():
    p = h.proposal()
    with pytest.raises(ValueError):
        replace(p, allowed_effects=("Register",))
    with pytest.raises(ValueError):
        replace(p, payload_digest="0" * 64)
    with pytest.raises(ValueError):
        replace(p, claim_generation=1)
    with pytest.raises(ValueError):
        replace(p, expires_at=p.created_at)
    with pytest.raises(ValueError):
        replace(p, rule_table_version="OTHER")
    post = h.proposal(raw_post("POST"))
    with pytest.raises(ValueError):
        replace(post, allowed_effects=())
    with pytest.raises(ValueError):
        replace(post, business_state_digest=None)


def test_logical_key_and_scope_tuple_include_organization():
    p = h.proposal()
    assert p.logical_key == ("sub-req", "CREATE_DRAFT", ("tenant-1", "company-1", "org-1", "base-1"), "req-1")
    assert SCOPE.as_tuple()[2] == "org-1" and len(SCOPE.as_tuple()) == 4
    other = h.proposal(h.raw_create(payload_over={"organization_ref": "org-9"}),
                       scope=Scope("tenant-1", "company-1", "org-9", "base-1"))
    assert other.logical_key != p.logical_key and other.logical_key[2][2] == "org-9"


@pytest.mark.parametrize("bad", ["", " ", "a b", "a\nb", "x" * 201, None, 5])
def test_scope_fields_are_validated_identity_text(bad):
    for i in range(4):
        values = ["t", "c", "o", "b"]
        values[i] = bad
        with pytest.raises(ValueError):
            Scope(*values)


def test_scope_is_immutable_and_redacted():
    with pytest.raises(dataclasses.FrozenInstanceError):
        SCOPE.organization = "other"  # type: ignore[misc]
    assert "org-1" not in repr(SCOPE)


# ---- canonical form and digests ---------------------------------------------------------------------------------

def test_canonical_json_is_sorted_compact_ascii_and_normalizes_decimals():
    assert ch.canonical_json({"b": Decimal("1.50"), "a": [Decimal(100), None, True, 3]}) == \
        '{"a":["100",null,true,3],"b":"1.5"}'
    assert ch.canonical_json({"k": "я"}) == '{"k":"\\u044f"}'
    same_instant_utc = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    same_instant_plus3 = datetime(2026, 10, 12, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    assert ch.canonical_json(same_instant_utc) == ch.canonical_json(same_instant_plus3)
    assert ch.canonical_json({"z": 1, "a": 2}) == ch.canonical_json({"a": 2, "z": 1})


@pytest.mark.parametrize("value", [1.5, float("nan"), Decimal("NaN"), Decimal("Infinity"), datetime(2026, 1, 1),
                                   object(), {1: 2}, b"x"])
def test_canonical_json_refuses_floats_naive_datetimes_and_foreign_types(value):
    with pytest.raises(ValueError):
        ch.canonical_json({"v": value})


def test_payload_digest_matches_independent_computation_and_covers_target_version():
    expected = hashlib.sha256(b'{"payload":{},"target_version":null}').hexdigest()
    assert ch.payload_digest(None, None) == expected
    assert ch.payload_digest(None, "v1") != ch.payload_digest(None, "v2") != expected
    p = h.proposal()
    assert p.payload_digest == ch.payload_digest(p.payload, None)
    assert len(p.payload_digest) == 64 and set(p.payload_digest) <= set("0123456789abcdef")


def test_approval_digest_is_stable_across_rebuilds_and_input_key_order():
    a = h.proposal()
    reordered = dict(reversed(list(raw_create().items())))
    reordered["payload"] = dict(reversed(list(raw_create()["payload"].items())))
    b = h.proposal(reordered)
    assert ch.approval_digest(a) == ch.approval_digest(b) == ch.approval_digest(h.proposal())
    # the same instant expressed in another zone yields the same digest
    plus3 = h.proposal(expires_at=h.APPROVAL_EXPIRES.astimezone(timezone(timedelta(hours=3))))
    assert ch.approval_digest(plus3) == ch.approval_digest(a)
    # decimal spelling is normalized before it is digested
    spelled = raw_create()
    spelled["payload"]["lines"][0].update(price="10.500", amount="21.000")
    assert ch.approval_digest(h.proposal(spelled)) == ch.approval_digest(a)
    with pytest.raises(ValueError):
        ch.approval_digest("not a proposal")  # type: ignore[arg-type]


def _vary(p: ChangeProposal, **over) -> ChangeProposal:
    if "target_version" in over or "payload" in over:
        tv = over.get("target_version", p.target_version)
        pl = over.get("payload", p.payload)
        over["payload_digest"] = ch.payload_digest(pl, tv)
    return replace(p, **over)


def test_approval_digest_covers_the_whole_section_3_digest_set():
    post = h.proposal(raw_post("POST"))
    base = ch.approval_digest(post)
    variants = {
        "change_id": _vary(post, change_id="c2"),
        "scope.tenant": _vary(post, scope=Scope("t2", "company-1", "org-1", "base-1")),
        "scope.company": _vary(post, scope=Scope("tenant-1", "co2", "org-1", "base-1")),
        "scope.organization": _vary(post, scope=Scope("tenant-1", "company-1", "org-2", "base-1")),
        "scope.base": _vary(post, scope=Scope("tenant-1", "company-1", "org-1", "base-2")),
        "target_ref": _vary(post, target_ref="doc2"),
        "target_version": _vary(post, target_version="v8"),
        "business_state_digest": _vary(post, business_state_digest="c" * 64),
        "epoch_dependencies": _vary(post, epoch_dependencies=(("approver", 3), ("requester", 1))),
        "parent_change_id": _vary(post, parent_change_id="parent2"),
        "expires_at": _vary(post, expires_at=post.expires_at + timedelta(seconds=1)),
        "kind": h.proposal(raw_post("UNPOST")),
    }
    for name, variant in variants.items():
        assert ch.approval_digest(variant) != base, name
    assert len({ch.approval_digest(v) for v in variants.values()} | {base}) == len(variants) + 1


def test_approval_digest_covers_payload_and_duplicate_override():
    p = h.proposal()
    base = ch.approval_digest(p)
    other_payload = replace(p.payload, comment="changed")
    assert ch.approval_digest(_vary(p, payload=other_payload)) != base
    ov = ch.DuplicateOverride("c0", "reason one")
    with_override = _vary(p, payload=replace(p.payload, duplicate_override=ov))
    assert ch.approval_digest(with_override) != base
    ov2 = ch.DuplicateOverride("c0", "reason two")
    assert ch.approval_digest(_vary(p, payload=replace(p.payload, duplicate_override=ov2))) \
        != ch.approval_digest(with_override)


def test_approval_digest_covers_rule_table_version_and_server_derived_allowed_effects(monkeypatch):
    post = h.proposal(raw_post("POST"))
    base = ch.approval_digest(post)
    monkeypatch.setattr(proposal_mod, "RULE_TABLE_VERSION", "S99-OTHER")
    assert ch.approval_digest(replace(post, rule_table_version="S99-OTHER")) != base
    monkeypatch.undo()
    rules = dict(proposal_mod.OPERATION_RULES)
    rules[ChangeKind.POST] = proposal_mod._OperationRule(("OnlyOneRegister",))
    monkeypatch.setattr(proposal_mod, "OPERATION_RULES", rules)
    changed = replace(post, allowed_effects=("OnlyOneRegister",))
    assert ch.approval_digest(changed) != base


# =====================================================================================================================
# 4. transitions T1..T17
# =====================================================================================================================

# ---- T1 propose -------------------------------------------------------------------------------------------------

def test_t1_propose_creates_a_proposed_record_from_the_proposal():
    p = h.proposal()
    res = apply_transition(None, Event.PROPOSE, good(Event.PROPOSE, None, proposal=p))
    r = ok(res, "T1")
    assert (r.lifecycle, r.authorization, r.execution, r.verification) == (
        Lifecycle.PROPOSED, Authorization.NONE, Execution.NOT_STARTED, Verification.NOT_VERIFIED)
    assert (r.change_id, r.kind, r.scope, r.requester_person_id) == ("c1", ChangeKind.CREATE_DRAFT, SCOPE, REQUESTER)
    assert r.claim_generation == 0 and r.reservation is Reservation.NONE and r.expires_at == p.expires_at
    assert not (r.target_lock or r.key_lock or r.lease) and res.effects == ()


def test_t1_same_logical_key_same_digest_returns_the_earlier_receipt():
    res = apply_transition(None, Event.PROPOSE, good(Event.PROPOSE, None, logical_key=LogicalKeyState.SAME_DIGEST))
    assert type(res) is Applied and res.record is None and res.effects == (EffectKind.REPLAY_EARLIER_RECEIPT,)


@pytest.mark.parametrize("over, code", [
    ({"logical_key": LogicalKeyState.OTHER_DIGEST}, "IDEMPOTENCY_CONFLICT"),
    ({"schema_valid": False}, "SCHEMA_INVALID"), ({"proposal": None}, "SCHEMA_INVALID"),
    ({"scope_resolved": False}, "SCOPE_MISMATCH"), ({"requester_entitled": False}, "NOT_ENTITLED"),
    ({"epoch_read": False}, "EPOCH_CHANGED"), ({"kill": UNREADABLE}, "KILL_SWITCH_ACTIVE"),
    ({"kill": kill(KillMode.STOP_ADMIT)}, "KILL_SWITCH_ACTIVE"), ({"logical_key": "UNUSED"}, "SCHEMA_INVALID"),
])
def test_t1_refusals(over, code):
    refused(apply_transition(None, Event.PROPOSE, good(Event.PROPOSE, None, **over)), code, "T1")


def test_t1_carries_the_unproven_parent_flag_and_override_into_the_record():
    ov = ch.DuplicateOverride("c0", "reason")
    p = h.proposal(raw_create(payload_over={"duplicate_override": {
        "duplicate_of_change_or_ref": "c0", "justification": "reason"}}))
    r = ok(apply_transition(None, Event.PROPOSE, good(Event.PROPOSE, None, proposal=p,
                                                      parent_attribution_unproven=True)))
    assert r.has_duplicate_override is True and r.parent_attribution_unproven is True
    assert ov.justification == "reason"


def test_propose_with_an_existing_record_or_other_events_without_one_is_refused():
    refused(apply_transition(proposed(), Event.PROPOSE, good(Event.PROPOSE)), "SCHEMA_INVALID")
    for event in Event:
        if event is not Event.PROPOSE:
            refused(apply_transition(None, event, good(event)), "SCHEMA_INVALID")


# ---- T2 validate ------------------------------------------------------------------------------------------------

def test_t2_validate_moves_proposed_to_validated():
    res = step(proposed(), Event.VALIDATE)
    assert ok(res, "T2").lifecycle is Lifecycle.VALIDATED and ok(res).reservation is Reservation.NONE


def test_t2_business_key_collision_parks_the_change_unless_an_override_is_bound():
    parked = ok(step(proposed(), Event.VALIDATE, key_state=h.BusinessKeyState.COLLISION))
    assert parked.lifecycle is Lifecycle.DUPLICATE_PARKED
    with_override = ok(step(proposed(has_duplicate_override=True), Event.VALIDATE,
                            key_state=h.BusinessKeyState.COLLISION))
    assert with_override.lifecycle is Lifecycle.VALIDATED
    # POST/UNPOST are not business-key checked
    post = proposed(kind=ChangeKind.POST, parent_change_id="parent9", target_ref="doc9")
    ok(step(post, Event.VALIDATE, key_state=h.BusinessKeyState.NOT_CHECKED))


@pytest.mark.parametrize("over, code", [
    ({"preview_built": False}, "SCHEMA_INVALID"), ({"shape_qualified": False}, "SHAPE_NOT_QUALIFIED"),
    ({"allowed_effects_derived": False}, "SCHEMA_INVALID"), ({"budget": BudgetCheck.EXCEEDED}, "BUDGET_EXCEEDED"),
    ({"budget": BudgetCheck.NOT_CHECKED}, "BUDGET_EXCEEDED"),
    ({"budget": BudgetCheck.CURRENCY_NOT_BUDGETED}, "CURRENCY_NOT_BUDGETED"),
    ({"key_state": h.BusinessKeyState.NOT_CHECKED}, "DUPLICATE_SUSPECTED"),
    ({"kill": UNREADABLE}, "KILL_SWITCH_ACTIVE"),
])
def test_t2_refusals(over, code):
    refused(step(proposed(), Event.VALIDATE, **over), code, "T2")


@pytest.mark.parametrize("state", [validated(), approved(), claimed(), applied()])
def test_t2_only_from_proposed(state):
    assert type(step(state, Event.VALIDATE)) is Refusal


# ---- T3 reject / expire -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("state", [proposed(), validated(), approved()])
def test_t3_reject_reaches_rejected_with_no_reservation_or_locks(state):
    r = ok(step(state, Event.REJECT), "T3")
    assert r.lifecycle is Lifecycle.REJECTED and r.reservation is Reservation.NONE
    assert not (r.target_lock or r.key_lock or r.lease)
    if state.authorization is Authorization.APPROVED:
        assert r.authorization is Authorization.REVOKED


@pytest.mark.parametrize("state", [proposed(), validated(), approved()])
def test_t3_expiry_is_sweep_driven_and_needs_the_deadline(state):
    r = ok(step(state, Event.EXPIRE), "T3")
    assert (r.lifecycle, r.authorization) == (Lifecycle.EXPIRED_QUEUED, Authorization.EXPIRED)
    refused(step(state, Event.EXPIRE, now=APPROVAL_EXPIRES - timedelta(seconds=1)), "SCHEMA_INVALID", "T3")
    refused(step(state, Event.EXPIRE, now=None), "SCHEMA_INVALID", "T3")


def test_t3_reject_needs_an_approver_and_is_not_available_once_claimed():
    refused(step(validated(), Event.REJECT, actor_is_approver=False), "NOT_ENTITLED", "T3")
    for state in (claimed(), applying(), applied(), unknown()):
        assert type(step(state, Event.REJECT)) is Refusal
        assert type(step(state, Event.EXPIRE)) is Refusal


# ---- T4 approve -------------------------------------------------------------------------------------------------

def test_t4_approve_records_the_approver_and_consumes_the_nonce():
    res = step(validated(), Event.APPROVE)
    r = ok(res, "T4")
    assert (r.authorization, r.lifecycle, r.approver_person_id, r.approval_id, r.approval_type) == (
        Authorization.APPROVED, Lifecycle.VALIDATED, APPROVER, "ap1", ApprovalType.HUMAN)
    assert res.effects == (EffectKind.CONSUME_NONCE,) and r.reservation is Reservation.NONE


def test_t4_test_lane_auto_approval_is_a_distinct_recorded_type_without_mfa():
    r = ok(step(validated(), Event.APPROVE, approval_type=ApprovalType.TEST_LANE_AUTO, approver_mfa=False))
    assert r.approval_type is ApprovalType.TEST_LANE_AUTO


@pytest.mark.parametrize("over, code", [
    ({"approver_person_id": REQUESTER}, "APPROVER_NOT_INDEPENDENT"),
    ({"approver_person_id": ""}, "APPROVER_NOT_INDEPENDENT"),
    ({"approver_entitled": False}, "NOT_ENTITLED"), ({"approver_mfa": False}, "NOT_ENTITLED"),
    ({"approval_id": ""}, "SCHEMA_INVALID"), ({"epoch_dependencies_current": False}, "EPOCH_CHANGED"),
    ({"nonce": NonceState.CONSUMED}, "APPROVAL_NONCE_INVALID"),
    ({"nonce": NonceState.EXPIRED}, "APPROVAL_NONCE_INVALID"),
    ({"nonce": NonceState.INVALID}, "APPROVAL_NONCE_INVALID"),
    ({"digest_bound": False}, "DIGEST_MISMATCH"), ({"checkpoint_ok": False}, "CHECKPOINT_UNAVAILABLE"),
    ({"now": APPROVAL_EXPIRES}, "APPROVAL_EXPIRED"), ({"now": None}, "APPROVAL_EXPIRED"),
    ({"kill": UNREADABLE}, "KILL_SWITCH_ACTIVE"), ({"kill": kill(KillMode.REVOKE)}, "KILL_SWITCH_ACTIVE"),
])
def test_t4_refusals(over, code):
    refused(step(validated(), Event.APPROVE, **over), code, "T4")


def test_t4_binds_override_and_unproven_flag_explicitly():
    refused(step(validated(has_duplicate_override=True), Event.APPROVE, override_bound=False),
            "DIGEST_MISMATCH", "T4")
    ok(step(validated(has_duplicate_override=True), Event.APPROVE, override_bound=True))
    refused(step(validated(parent_attribution_unproven=True), Event.APPROVE, unproven_flag_bound=False),
            "ATTRIBUTION_UNPROVEN", "T4")
    ok(step(validated(parent_attribution_unproven=True), Event.APPROVE, unproven_flag_bound=True))
    # an unneeded binding is not required
    ok(step(validated(), Event.APPROVE, override_bound=False, unproven_flag_bound=False))


@pytest.mark.parametrize("state", [proposed(), approved(), claimed(), validated(lifecycle=Lifecycle.DUPLICATE_PARKED),
                                   applied()])
def test_t4_only_from_validated_without_authorization(state):
    assert type(step(state, Event.APPROVE)) is Refusal


# ---- T5 claim ---------------------------------------------------------------------------------------------------

def test_t5_claim_is_one_transition_that_takes_locks_budget_and_a_generation():
    res = step(approved(), Event.CLAIM)
    r = ok(res, "T5")
    assert (r.authorization, r.execution, r.token, r.claim_generation) == (
        Authorization.CLAIMED, Execution.NOT_STARTED, TokenState.ISSUED, 1)
    assert (r.target_lock, r.key_lock, r.lease) == (True, True, True) and r.reservation is Reservation.RESERVED
    assert r.claim_expires_at == T0 + timedelta(seconds=120) and r.dispatch is Dispatch.NOT_PERMITTED
    assert {EffectKind.RESERVE_BUDGET, EffectKind.MINT_CLAIM_TOKEN, EffectKind.ACQUIRE_LOCKS} <= set(res.effects)
    assert r.repair is None and r.repair_for is None


@pytest.mark.parametrize("over, code", [
    ({"caller_is_requester": False}, "NOT_ENTITLED"), ({"now": APPROVAL_EXPIRES}, "APPROVAL_EXPIRED"),
    ({"epoch_deps_unchanged": False}, "EPOCH_CHANGED"), ({"kill": UNREADABLE}, "KILL_SWITCH_ACTIVE"),
    ({"kill": kill(KillMode.STOP_ADMIT)}, "KILL_SWITCH_ACTIVE"),
    ({"holds": (Hold("x", HoldCause.ANCHOR_GAP, "c9"),)}, "BASE_HOLD"),
    ({"holds": (Hold("x", HoldCause.CALL_OWNERSHIP, "c9"),)}, "BASE_HOLD"),
    ({"holds": (Hold("x", HoldCause.FAILED_VERIFY_HALT, "c9", "doc1", "v7"),)}, "BASE_HOLD"),
    ({"holds": None}, "BASE_HOLD"), ({"scope_equal": False}, "SCOPE_MISMATCH"),
    ({"target_class_equal": False}, "TARGET_REJECTED"), ({"locks_read": False}, "LOCK_BUSY"),
    ({"target_lock_owner": "other"}, "LOCK_BUSY"), ({"key_lock_free": False}, "LOCK_BUSY"),
    ({"lease_free": False}, "LOCK_BUSY"), ({"budget": BudgetCheck.EXCEEDED}, "BUDGET_EXCEEDED"),
    ({"budget": BudgetCheck.NOT_CHECKED}, "BUDGET_EXCEEDED"),
    ({"budget": BudgetCheck.CURRENCY_NOT_BUDGETED}, "CURRENCY_NOT_BUDGETED"),
])
def test_t5_refusals_per_guard(over, code):
    refused(step(approved(), Event.CLAIM, **over), code, "T5")


def test_t5_a_released_hold_does_not_block_and_parent_is_only_needed_for_post_and_unpost():
    ok(step(approved(), Event.CLAIM, holds=(Hold("x", HoldCause.ANCHOR_GAP, "c9", released=True),)))
    ok(step(approved(), Event.CLAIM, parent_verified=False))  # CREATE_DRAFT has no parent
    for kind in (ChangeKind.POST, ChangeKind.UNPOST):
        state = approved(kind=kind, parent_change_id="parent9", target_ref="doc9")
        ok(step(state, Event.CLAIM, parent_verified=True))
        refused(step(state, Event.CLAIM, parent_verified=False), "PARENT_NOT_VERIFIED", "T5")


@pytest.mark.parametrize("state", [proposed(), validated(), claimed(), applying(), applied(),
                                   approved(execution=Execution.APPLYING)])
def test_t5_only_from_validated_approved(state):
    assert type(step(state, Event.CLAIM)) is Refusal


def test_t5_unapproved_or_voided_or_expired_authorizations_cannot_claim():
    for auth in (Authorization.NONE, Authorization.VOIDED, Authorization.REVOKED, Authorization.EXPIRED):
        assert type(step(validated(authorization=auth), Event.CLAIM)) is Refusal


def test_t5_reclaim_after_release_increments_the_generation_and_reserves_again():
    first = ok(step(approved(), Event.CLAIM))
    released = ok(step(first, Event.RELEASE_CLAIM))
    assert released.reservation is Reservation.RELEASED and released.claim_generation == 1
    second = ok(step(released, Event.CLAIM))
    assert second.claim_generation == 2 and second.reservation is Reservation.RESERVED
    assert second.token is TokenState.ISSUED and second.dispatch is Dispatch.NOT_PERMITTED


# ---- T5 repair claim (section 4.2) -------------------------------------------------------------------------------

def test_t5_matching_repair_claim_passes_and_hands_the_lock_over():
    res = step(repair_rec(), Event.CLAIM)
    r = ok(res, "T5")
    assert r.repair == RepairAuth("r1", "parent1", "doc1", "v7", "h1", "ap2", 1) and r.repair_for == "parent1"
    assert r.authorization is Authorization.CLAIMED and r.claim_generation == 1 and r.target_lock is True
    assert (r.key_lock, r.lease, r.reservation) == (True, True, Reservation.RESERVED)
    assert EffectKind.HAND_LOCK_TO_REPAIR in res.effects and EffectKind.HAND_LOCK_BACK_TO_PARENT not in res.effects


def _claim_repair(ctx_over=None, **over):
    ctx = repair_ctx(**(ctx_over or {}))
    return step(repair_rec(), Event.CLAIM, repair_ctx=ctx, **over)


@pytest.mark.parametrize("ctx_over, code", [
    ({"current_target_ref": "doc2"}, "TARGET_REJECTED"),
    ({"current_version": "v8"}, "STALE_VERSION"),
    ({"halt": dataclasses.replace(HALT, observed_version=None)}, "STALE_VERSION"),
    ({"halt": dataclasses.replace(HALT, released=True)}, "PARENT_NOT_VERIFIED"),
    ({"halt": None}, "PARENT_NOT_VERIFIED"),
    ({"halt": dataclasses.replace(HALT, change_id="other")}, "PARENT_NOT_VERIFIED"),
    ({"halt": dataclasses.replace(HALT, cause=HoldCause.ANCHOR_GAP)}, "PARENT_NOT_VERIFIED"),
    ({"halt": dataclasses.replace(HALT, target_ref="doc2")}, "TARGET_REJECTED"),
    ({"approval_revoked": True}, "APPROVAL_VOIDED"), ({"approval_fresh": False}, "APPROVAL_VOIDED"),
    ({"other_repair_exists": True}, "LOCK_BUSY"), ({"target_lock_owner": "rival"}, "LOCK_BUSY"),
    ({"target_lock_owner": None}, "LOCK_BUSY"), ({"target_lock_owner": REPAIR_ID}, "LOCK_BUSY"),
    ({"parent_requester_person_id": REPAIR_APPROVER}, "APPROVER_NOT_INDEPENDENT"),
    ({"parent_verification": Verification.VERIFIED}, "PARENT_NOT_VERIFIED"),
    ({"parent_verification": Verification.NOT_VERIFIED}, "PARENT_NOT_VERIFIED"),
    ({"parent_effect_known": EffectKnown.NO}, "PARENT_NOT_VERIFIED"),
    ({"parent_effect_known": EffectKnown.UNKNOWN}, "PARENT_NOT_VERIFIED"),
    ({"parent_effect_known": None}, "PARENT_NOT_VERIFIED"),
    ({"parent_change_id": "parent2"}, "PARENT_NOT_VERIFIED"),
])
def test_t5_repair_refusals_each_leave_the_record_untouched(ctx_over, code):
    before = repair_rec()
    refused(step(before, Event.CLAIM, repair_ctx=repair_ctx(**ctx_over)), code, "T5")
    assert before.authorization is Authorization.APPROVED and before.target_lock is False


def test_t5_repair_other_open_hold_unreadable_holds_and_kill_refuse():
    other = Hold("h2", HoldCause.ANCHOR_GAP, "c9")
    refused(step(repair_rec(), Event.CLAIM, repair_ctx=repair_ctx(), holds=(HALT, other)), "BASE_HOLD", "T5")
    refused(step(repair_rec(), Event.CLAIM, repair_ctx=repair_ctx(), holds=None), "BASE_HOLD", "T5")
    ok(step(repair_rec(), Event.CLAIM, repair_ctx=repair_ctx(), holds=(HALT, dataclasses.replace(other, released=True))))
    refused(step(repair_rec(), Event.CLAIM, repair_ctx=repair_ctx(), kill=kill(KillMode.STOP_ADMIT)),
            "KILL_SWITCH_ACTIVE", "T5")


def test_t5_repair_requires_independent_approver_and_unpost_kind():
    refused(step(repair_rec(approver_person_id=REQUESTER), Event.CLAIM, repair_ctx=repair_ctx()),
            "APPROVER_NOT_INDEPENDENT", "T5")
    refused(step(repair_rec(approver_person_id=None), Event.CLAIM, repair_ctx=repair_ctx()),
            "APPROVER_NOT_INDEPENDENT", "T5")
    post = repair_rec(kind=ChangeKind.POST)
    refused(step(post, Event.CLAIM, repair_ctx=repair_ctx()), "PARENT_NOT_VERIFIED", "T5")
    draft = approved(kind=ChangeKind.CREATE_DRAFT)
    refused(step(draft, Event.CLAIM, repair_ctx=repair_ctx()), "PARENT_NOT_VERIFIED", "T5")


def test_t5_the_repair_exception_is_not_available_without_the_repair_context():
    state = repair_rec()
    refused(step(state, Event.CLAIM, parent_verified=False, holds=(), repair_ctx=None), "PARENT_NOT_VERIFIED", "T5")
    refused(step(state, Event.CLAIM, parent_verified=False, holds=(HALT,), repair_ctx=None), "BASE_HOLD", "T5")
    refused(step(state, Event.CLAIM, parent_verified=True, holds=(HALT,), repair_ctx=None), "BASE_HOLD", "T5")
    # the exception exempts only the parent guard and that one halt: CALL_OWNERSHIP etc. still block
    for cause in (HoldCause.CALL_OWNERSHIP, HoldCause.ANCHOR_GAP, HoldCause.RLC_UNCLEAN):
        refused(step(state, Event.CLAIM, repair_ctx=repair_ctx(), holds=(HALT, Hold("h9", cause, "c9"))),
                "BASE_HOLD", "T5")
    # the budget and locks are still checked on the repair path
    refused(step(state, Event.CLAIM, repair_ctx=repair_ctx(), budget=BudgetCheck.EXCEEDED, holds=(HALT,)),
            "BUDGET_EXCEEDED", "T5")
    refused(step(state, Event.CLAIM, repair_ctx=repair_ctx(), key_lock_free=False, holds=(HALT,)), "LOCK_BUSY", "T5")


# ---- T5x release_claim ------------------------------------------------------------------------------------------

def test_t5x_ttl_expiry_releases_everything_and_supersedes_the_token():
    res = step(claimed(), Event.RELEASE_CLAIM, now=T0 + timedelta(seconds=120))
    r = ok(res, "T5x")
    assert (r.authorization, r.execution, r.token) == (Authorization.APPROVED, Execution.NOT_STARTED,
                                                       TokenState.SUPERSEDED)
    assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (False, False, False, Reservation.RELEASED)
    assert r.claim_expires_at is None and r.claim_generation == 1
    assert EffectKind.INVALIDATE_REPAIR_AUTH not in res.effects and EffectKind.HAND_LOCK_BACK_TO_PARENT not in res.effects


def test_t5x_requires_a_real_cause():
    refused(step(claimed(), Event.RELEASE_CLAIM, now=T0 + timedelta(seconds=119)), "SCHEMA_INVALID", "T5x")
    refused(step(claimed(), Event.RELEASE_CLAIM, reason=None), "SCHEMA_INVALID", "T5x")
    refused(step(claimed(), Event.RELEASE_CLAIM, reason=ReleaseReason.KILL_SWITCH), "SCHEMA_INVALID", "T5x")
    ok(step(claimed(), Event.RELEASE_CLAIM, reason=ReleaseReason.KILL_SWITCH, kill=kill(KillMode.STOP_ADMIT)))
    ok(step(claimed(), Event.RELEASE_CLAIM, reason=ReleaseReason.KILL_SWITCH, kill=UNREADABLE))
    ok(step(claimed(), Event.RELEASE_CLAIM, reason=ReleaseReason.T6_GUARD_FAILED))


def test_t5x_lands_in_expired_when_approval_lapsed_and_voided_under_revoke():
    late = APPROVAL_EXPIRES + timedelta(seconds=1)
    assert ok(step(claimed(), Event.RELEASE_CLAIM, now=late)).authorization is Authorization.EXPIRED
    r = ok(step(claimed(), Event.RELEASE_CLAIM, reason=ReleaseReason.KILL_SWITCH, kill=kill(KillMode.REVOKE)))
    assert r.authorization is Authorization.VOIDED
    r = ok(step(claimed(), Event.RELEASE_CLAIM, reason=ReleaseReason.KILL_SWITCH, kill=kill(KillMode.STOP_EFFECTS)))
    assert r.authorization is Authorization.APPROVED


@pytest.mark.parametrize("state", [approved(), validated(), applying(), applied(), proposed()])
def test_t5x_only_from_claimed_not_started(state):
    assert type(step(state, Event.RELEASE_CLAIM)) is Refusal


# ---- T6 begin_apply ---------------------------------------------------------------------------------------------

def test_t6_begin_apply_opens_applying_without_a_permit_and_keeps_every_lock():
    res = step(claimed(), Event.BEGIN_APPLY, now=T0 + timedelta(seconds=10))
    r = ok(res, "T6")
    assert (r.execution, r.dispatch, r.token) == (Execution.APPLYING, Dispatch.NOT_PERMITTED, TokenState.CONSUMED)
    assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (True, True, True, Reservation.RESERVED)
    assert r.permit_expires_at == T0 + timedelta(seconds=70) and r.claim_generation == 1
    assert res.effects == (EffectKind.COMMIT_APPLYING_AND_OWNERSHIP_ROW,)


@pytest.mark.parametrize("over, code", [
    ({"generation": 0}, "TICKET_SUPERSEDED"), ({"generation": 2}, "TICKET_SUPERSEDED"),
    ({"generation": -1}, "TICKET_SUPERSEDED"),
    ({"caller": None}, "NOT_ENTITLED"), ({"caller": CallerClass.APPROVER}, "NOT_ENTITLED"),
    ({"caller": CallerClass.OPERATOR}, "NOT_ENTITLED"), ({"caller": CallerClass.RECOVERY_WORKER}, "NOT_ENTITLED"),
    ({"own_change": False}, "NOT_ENTITLED"),
    ({"now": T0 + timedelta(seconds=120)}, "CLAIM_EXPIRED"), ({"now": None}, "CLAIM_EXPIRED"),
    ({"epoch_deps_equal_claim_epoch": False}, "EPOCH_CHANGED"), ({"kill": UNREADABLE}, "KILL_SWITCH_ACTIVE"),
    ({"kill": kill(KillMode.STOP_EFFECTS)}, "KILL_SWITCH_ACTIVE"),
    ({"holds": (Hold("x", HoldCause.RLC_UNCLEAN, "c9"),)}, "BASE_HOLD"), ({"holds": None}, "BASE_HOLD"),
    ({"version_equals_approved": False}, "STALE_VERSION"),
    ({"fingerprint_authenticated": False}, "TARGET_REJECTED"), ({"state_digest_equal": False}, "DIGEST_MISMATCH"),
    ({"writer_lock_held": False}, "LOCK_BUSY"), ({"ownership_row_committed": False}, "AUDIT_UNAVAILABLE"),
])
def test_t6_refusals_per_guard(over, code):
    refused(step(claimed(), Event.BEGIN_APPLY, **over), code, "T6")


def test_t6_writer_may_act_on_behalf_of_a_token_and_approval_must_still_be_open():
    ok(step(claimed(), Event.BEGIN_APPLY, caller=CallerClass.WRITER, own_change=False))
    short = claimed(expires_at=T0 + timedelta(seconds=30))
    refused(step(short, Event.BEGIN_APPLY, now=T0 + timedelta(seconds=40)), "APPROVAL_EXPIRED", "T6")


def test_t6_superseded_or_revoked_token_gets_no_ticket():
    for token in (TokenState.SUPERSEDED, TokenState.REVOKED, TokenState.NONE):
        refused(step(claimed(token=token), Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")
    # a stale generation after a re-claim: generation 1 against a record at generation 2
    refused(step(claimed(claim_generation=2), Event.BEGIN_APPLY, generation=1), "TICKET_SUPERSEDED", "T6")


def test_t6_replay_returns_the_existing_ticket_only_while_not_dispatched():
    for dispatch in (Dispatch.NOT_PERMITTED, Dispatch.PERMITTED):
        state = applying(dispatch)
        res = step(state, Event.BEGIN_APPLY)
        assert type(res) is Applied and res.record == state and res.effects == (EffectKind.REPLAY_EXISTING_TICKET,)
        assert res.record.dispatch is dispatch  # never a second permit
    refused(step(dispatched(), Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")
    refused(step(applying(Dispatch.CANCELLED_UNDISPATCHED), Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")
    refused(step(applying(), Event.BEGIN_APPLY, generation=9), "TICKET_SUPERSEDED", "T6")
    refused(step(applying(), Event.BEGIN_APPLY, caller=CallerClass.APPROVER), "NOT_ENTITLED", "T6")


def test_t6_repair_passes_and_is_rechecked_identically():
    state = repair_live(claimed)
    r = ok(step(state, Event.BEGIN_APPLY), "T6")
    assert r.execution is Execution.APPLYING and r.repair == REPAIR_AUTH


@pytest.mark.parametrize("ctx_over, code", [
    ({"current_version": "v8"}, "STALE_VERSION"),
    ({"halt": dataclasses.replace(HALT, released=True)}, "PARENT_NOT_VERIFIED"),
    ({"approval_revoked": True}, "APPROVAL_VOIDED"), ({"approval_fresh": False}, "APPROVAL_VOIDED"),
    ({"other_repair_exists": True}, "LOCK_BUSY"), ({"target_lock_owner": "parent1"}, "LOCK_BUSY"),
    ({"target_lock_owner": "rival"}, "LOCK_BUSY"), ({"parent_verification": Verification.VERIFIED}, "PARENT_NOT_VERIFIED"),
    ({"parent_effect_known": EffectKnown.NO}, "PARENT_NOT_VERIFIED"),
    ({"current_target_ref": "doc2"}, "TARGET_REJECTED"),
])
def test_t6_repair_revalidation_failures(ctx_over, code):
    refused(step(repair_live(claimed), Event.BEGIN_APPLY, repair_ctx=repair_ctx(REPAIR_ID, **ctx_over)), code, "T6")


def test_t6_repair_other_hold_and_stale_authorization_refuse():
    other = Hold("h2", HoldCause.CALL_OWNERSHIP, "c9")
    refused(step(repair_live(claimed), Event.BEGIN_APPLY, holds=(HALT, other)), "BASE_HOLD", "T6")
    refused(step(repair_live(claimed), Event.BEGIN_APPLY, holds=None), "BASE_HOLD", "T6")
    stale_gen = dataclasses.replace(REPAIR_AUTH, claim_generation=2)
    refused(step(repair_live(claimed, repair=stale_gen), Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")
    refused(step(repair_live(claimed, repair=None), Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")
    wrong_halt = dataclasses.replace(REPAIR_AUTH, halt_id="h-other")
    refused(step(repair_live(claimed, repair=wrong_halt), Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")
    wrong_version = dataclasses.replace(REPAIR_AUTH, observed_version="v6")
    refused(step(repair_live(claimed, repair=wrong_version), Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")
    refused(step(repair_live(claimed, approval_id="ap-other"), Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")
    # a non-repair change gets no halt exemption at T6
    refused(step(claimed(), Event.BEGIN_APPLY, holds=(HALT,)), "BASE_HOLD", "T6")
    refused(step(repair_live(claimed), Event.BEGIN_APPLY, kill=kill(KillMode.STOP_ADMIT)), "KILL_SWITCH_ACTIVE", "T6")


# ---- T6p permit and dispatch; T6c cancel; dispatch CAS ------------------------------------------------------------

def test_t6p_permit_is_issued_after_the_checkpoint_and_keeps_locks():
    res = step(applying(), Event.ISSUE_PERMIT)
    r = ok(res, "T6p")
    assert r.dispatch is Dispatch.PERMITTED and r.permit_expires_at == T0 + timedelta(seconds=60)
    assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (True, True, True, Reservation.RESERVED)
    assert res.effects == (EffectKind.SIGN_PERMIT,)


@pytest.mark.parametrize("over, code", [
    ({"generation": 0}, "TICKET_SUPERSEDED"), ({"kill": UNREADABLE}, "KILL_SWITCH_ACTIVE"),
    ({"kill": kill(KillMode.STOP_ADMIT)}, "KILL_SWITCH_ACTIVE"),
    ({"checkpoint_covers_head": False}, "CHECKPOINT_UNAVAILABLE"),
    ({"now": T0 + timedelta(seconds=60)}, "PERMIT_MISSING"),
    ({"holds": (Hold("x", HoldCause.ANCHOR_GAP, "c9"),)}, "BASE_HOLD"), ({"holds": None}, "BASE_HOLD"),
])
def test_t6p_issue_refusals(over, code):
    refused(step(applying(), Event.ISSUE_PERMIT, **over), code, "T6p")


@pytest.mark.parametrize("state", [claimed(), applying(Dispatch.PERMITTED), dispatched(), applied(),
                                   applying(Dispatch.CANCELLED_UNDISPATCHED)])
def test_t6p_no_second_permit_and_none_outside_applying_not_permitted(state):
    assert type(step(state, Event.ISSUE_PERMIT)) is Refusal


def test_dispatch_is_set_by_the_writer_only_with_a_valid_permit():
    res = step(applying(Dispatch.PERMITTED), Event.MARK_DISPATCHED)
    r = ok(res, "T6p")
    assert r.dispatch is Dispatch.DISPATCHED and res.effects == (EffectKind.RECORD_DISPATCHED,)
    assert (r.target_lock, r.key_lock, r.lease) == (True, True, True)


@pytest.mark.parametrize("over, code", [
    ({"caller": CallerClass.REQUESTER}, "NOT_ENTITLED"), ({"caller": None}, "NOT_ENTITLED"),
    ({"caller": CallerClass.RECOVERY_WORKER}, "NOT_ENTITLED"),
    ({"generation": 5}, "TICKET_SUPERSEDED"), ({"kill": UNREADABLE}, "KILL_SWITCH_ACTIVE"),
    ({"kill": kill(KillMode.REVOKE)}, "KILL_SWITCH_ACTIVE"),
    ({"permit_signature_valid": False}, "PERMIT_MISSING"),
    ({"checkpoint_sequence_verified": False}, "CHECKPOINT_UNAVAILABLE"),
    ({"holds": (Hold("x", HoldCause.CALL_OWNERSHIP, "c9"),)}, "BASE_HOLD"),
])
def test_dispatch_refusals(over, code):
    refused(step(applying(Dispatch.PERMITTED), Event.MARK_DISPATCHED, **over), code, "T6p")


@pytest.mark.parametrize("state", [claimed(), applying(Dispatch.NOT_PERMITTED), dispatched(),
                                   applying(Dispatch.CANCELLED_UNDISPATCHED), applied()])
def test_no_dispatch_without_a_permit_and_at_most_one_dispatch(state):
    assert type(step(state, Event.MARK_DISPATCHED)) is Refusal


def test_t6r_permit_not_issued_returns_to_approved_with_everything_released():
    res = step(applying(), Event.PERMIT_NOT_ISSUED)
    r = ok(res, "T6r")
    assert (r.authorization, r.execution, r.token) == (Authorization.APPROVED, Execution.NOT_STARTED,
                                                       TokenState.SUPERSEDED)
    assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (False, False, False, Reservation.RELEASED)
    assert r.permit_expires_at is None
    assert EffectKind.HAND_LOCK_BACK_TO_PARENT not in res.effects


@pytest.mark.parametrize("over", [
    {"checkpoint_unavailable": True, "kill": SWITCH_OFF}, {"checkpoint_unavailable": False, "hold_open": True},
    {"checkpoint_unavailable": False, "kill": kill(KillMode.STOP_EFFECTS)},
    {"checkpoint_unavailable": False, "kill": UNREADABLE},
    {"checkpoint_unavailable": False, "now": T0 + timedelta(seconds=60)},
])
def test_t6r_each_cause_is_accepted(over):
    ok(step(applying(), Event.PERMIT_NOT_ISSUED, **over), "T6r")


def test_t6r_refusals_a_permit_event_or_no_cause():
    refused(step(applying(), Event.PERMIT_NOT_ISSUED, permitted_event_exists=True), "TICKET_SUPERSEDED", "T6r")
    refused(step(applying(), Event.PERMIT_NOT_ISSUED, checkpoint_unavailable=False), "SCHEMA_INVALID", "T6r")
    for state in (applying(Dispatch.PERMITTED), dispatched(), claimed(), applied()):
        assert type(step(state, Event.PERMIT_NOT_ISSUED)) is Refusal


def test_t6c_cancel_wins_the_cas_and_unwinds_the_claim():
    res = step(applying(Dispatch.PERMITTED), Event.CANCEL_PERMIT)
    r = ok(res, "T6c")
    assert (r.dispatch, r.authorization, r.execution, r.token) == (
        Dispatch.CANCELLED_UNDISPATCHED, Authorization.APPROVED, Execution.NOT_STARTED, TokenState.SUPERSEDED)
    assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (False, False, False, Reservation.RELEASED)
    assert EffectKind.INVALIDATE_PERMIT in res.effects


@pytest.mark.parametrize("over", [
    {"kill": kill(KillMode.STOP_ADMIT)}, {"kill": UNREADABLE}, {"kill": SWITCH_OFF, "hold_open": True},
    {"kill": SWITCH_OFF, "generation": 7}, {"kill": SWITCH_OFF, "now": T0 + timedelta(seconds=60)},
])
def test_t6c_each_cause_is_accepted(over):
    ok(step(applying(Dispatch.PERMITTED), Event.CANCEL_PERMIT, **over), "T6c")


def test_t6c_refusals():
    state = applying(Dispatch.PERMITTED)
    refused(step(state, Event.CANCEL_PERMIT, kill=SWITCH_OFF), "SCHEMA_INVALID", "T6c")  # no cause
    refused(step(state, Event.CANCEL_PERMIT, cancel_cas_won=False), "LOCK_BUSY", "T6c")
    refused(step(state, Event.CANCEL_PERMIT, permit_invalidated=False), "PERMIT_MISSING", "T6c")
    for other in (applying(), dispatched(), claimed(), applied(), applying(Dispatch.CANCELLED_UNDISPATCHED)):
        assert type(step(other, Event.CANCEL_PERMIT)) is Refusal


def test_dispatch_cas_cancel_and_dispatch_are_mutually_exclusive_exactly_one_wins():
    permitted = applying(Dispatch.PERMITTED)
    # order A: cancel first -> the writer's DISPATCHED can no longer happen
    cancelled = ok(step(permitted, Event.CANCEL_PERMIT))
    refused(step(cancelled, Event.MARK_DISPATCHED), "PERMIT_MISSING", "T6p")
    assert cancelled.dispatch is Dispatch.CANCELLED_UNDISPATCHED and cancelled.execution is Execution.NOT_STARTED
    # order B: dispatch first -> the cancel is impossible and the call follows T7/T9
    sent = ok(step(permitted, Event.MARK_DISPATCHED))
    refused(step(sent, Event.CANCEL_PERMIT), "LOCK_BUSY", "T6c")
    assert sent.dispatch is Dispatch.DISPATCHED and sent.execution is Execution.APPLYING
    # a permit can be cancelled at most once and dispatched at most once
    refused(step(cancelled, Event.CANCEL_PERMIT), "LOCK_BUSY", "T6c")
    refused(step(sent, Event.MARK_DISPATCHED), "PERMIT_MISSING", "T6p")
    outcomes = [ok(step(sent, Event.CALL_SUCCESS)).execution, ok(step(sent, Event.CALL_UNKNOWN)).execution]
    assert outcomes == [Execution.APPLIED, Execution.APPLY_UNKNOWN]


def test_after_cancel_a_new_claim_gets_a_new_generation_and_no_permit():
    cancelled = ok(step(applying(Dispatch.PERMITTED), Event.CANCEL_PERMIT))
    again = ok(step(cancelled, Event.CLAIM))
    assert again.claim_generation == 2 and again.dispatch is Dispatch.NOT_PERMITTED and again.token is TokenState.ISSUED


# ---- T7 / T8 / T9 -----------------------------------------------------------------------------------------------

def test_t7_success_applies_with_proven_attribution_and_consumes_the_reservation():
    r = ok(step(dispatched(), Event.CALL_SUCCESS), "T7")
    assert (r.execution, r.call_ownership, r.attribution, r.reservation) == (
        Execution.APPLIED, CallOwnership.PROVEN_FINISHED, Attribution.PROVEN, Reservation.CONSUMED)
    assert (r.target_lock, r.key_lock, r.lease) == (True, False, False)
    assert r.verification is Verification.NOT_VERIFIED


@pytest.mark.parametrize("over, code", [
    ({"caller": CallerClass.RECOVERY_WORKER}, "NOT_ENTITLED"), ({"caller": CallerClass.REQUESTER}, "NOT_ENTITLED"),
    ({"generation": 0}, "TICKET_SUPERSEDED"), ({"signed": False}, "EVIDENCE_UNSIGNED"),
    ({"call_id_matches": False}, "EVIDENCE_UNSIGNED"), ({"result_returned": False}, "SCHEMA_INVALID"),
    ({"stage": FailureStage.WRITE_STARTED}, "SCHEMA_INVALID"), ({"checkpoint_ok": False}, "CHECKPOINT_UNAVAILABLE"),
])
def test_t7_refusals(over, code):
    refused(step(dispatched(), Event.CALL_SUCCESS, **over), code, "T7")


@pytest.mark.parametrize("state", [applying(), applying(Dispatch.PERMITTED), claimed(), unknown(), applied()])
def test_t7_only_after_dispatch(state):
    assert type(step(state, Event.CALL_SUCCESS)) is Refusal


def test_t8_definite_pre_write_refusal_fails_apply_and_releases_everything():
    res = step(dispatched(), Event.REFUSED_BEFORE_WRITE)
    r = ok(res, "T8")
    assert r.execution is Execution.FAILED_APPLY and r.call_ownership is CallOwnership.NONE
    assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (False, False, False, Reservation.RELEASED)


def test_t8_rollback_refused_applies_only_to_unpost_precondition_refusals():
    unpost = dispatched(kind=ChangeKind.UNPOST, parent_change_id="parent9", target_ref="doc9")
    r = ok(step(unpost, Event.REFUSED_BEFORE_WRITE, refusal_code=ErrorCode.ROLLBACK_REFUSED))
    assert r.execution is Execution.ROLLBACK_REFUSED and r.reservation is Reservation.RELEASED
    r = ok(step(dispatched(), Event.REFUSED_BEFORE_WRITE, refusal_code=ErrorCode.ROLLBACK_REFUSED))
    assert r.execution is Execution.FAILED_APPLY


@pytest.mark.parametrize("code", [ErrorCode.STALE_VERSION, ErrorCode.DUPLICATE_SUSPECTED, ErrorCode.WRITE_REFUSED,
                                  ErrorCode.ROLLBACK_REFUSED])
def test_t8_accepts_each_writer_refusal_code(code):
    assert ok(step(dispatched(), Event.REFUSED_BEFORE_WRITE, refusal_code=code)).execution in (
        Execution.FAILED_APPLY, Execution.ROLLBACK_REFUSED)


@pytest.mark.parametrize("over", [
    {"no_effect_proof": False}, {"refusal_code": None}, {"refusal_code": ErrorCode.SCHEMA_INVALID},
    {"refusal_code": ErrorCode.APPLY_UNKNOWN}, {"stage": FailureStage.WRITE_STARTED},
    {"stage": FailureStage.UNCLASSIFIED}, {"stage": None}, {"result_returned": True},
])
def test_t8_a_refusal_code_alone_or_a_late_stage_is_never_enough(over):
    refused(step(dispatched(), Event.REFUSED_BEFORE_WRITE, **over), "SCHEMA_INVALID", "T8")
    # the same evidence routes to T9 (unknown) instead, never to FAILED_APPLY
    evidence = good(Event.REFUSED_BEFORE_WRITE, dispatched(), **over)
    assert ch.classify_completion(evidence) is not Event.REFUSED_BEFORE_WRITE


@pytest.mark.parametrize("over, code", [
    ({"signed": False}, "EVIDENCE_UNSIGNED"), ({"call_id_matches": False}, "EVIDENCE_UNSIGNED"),
    ({"caller": CallerClass.RECOVERY_WORKER}, "NOT_ENTITLED"), ({"generation": 3}, "TICKET_SUPERSEDED"),
    ({"checkpoint_ok": False}, "CHECKPOINT_UNAVAILABLE"),
])
def test_t8_other_refusals(over, code):
    refused(step(dispatched(), Event.REFUSED_BEFORE_WRITE, **over), code, "T8")


def test_t8_transient_lock_busy_goes_back_to_approved_with_a_durable_counter():
    res = step(dispatched(), Event.REFUSED_BEFORE_WRITE, refusal_code=ErrorCode.LOCK_BUSY)
    r = ok(res, "T8")
    assert (r.authorization, r.execution, r.lock_busy_attempts, r.first_attempt_at) == (
        Authorization.APPROVED, Execution.NOT_STARTED, 1, T0)
    assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (False, False, False, Reservation.RELEASED)
    later = ok(step(r, Event.CLAIM, now=T0 + timedelta(minutes=3)))
    assert later.claim_generation == 2
    d = replace(later, execution=Execution.APPLYING, token=TokenState.CONSUMED, dispatch=Dispatch.DISPATCHED)
    again = ok(step(d, Event.REFUSED_BEFORE_WRITE, refusal_code=ErrorCode.LOCK_BUSY, now=T0 + timedelta(minutes=6)))
    assert again.lock_busy_attempts == 2 and again.first_attempt_at == T0 and again.execution is Execution.NOT_STARTED


def test_t8_lock_busy_becomes_definite_after_five_attempts_or_fifteen_minutes():
    state = dispatched(lock_busy_attempts=3, first_attempt_at=T0)
    assert ok(step(state, Event.REFUSED_BEFORE_WRITE, refusal_code=ErrorCode.LOCK_BUSY,
                   now=T0 + timedelta(minutes=5))).execution is Execution.NOT_STARTED
    state = dispatched(lock_busy_attempts=4, first_attempt_at=T0)
    assert ok(step(state, Event.REFUSED_BEFORE_WRITE, refusal_code=ErrorCode.LOCK_BUSY,
                   now=T0 + timedelta(minutes=5))).execution is Execution.FAILED_APPLY
    state = dispatched(lock_busy_attempts=1, first_attempt_at=T0)
    assert ok(step(state, Event.REFUSED_BEFORE_WRITE, refusal_code=ErrorCode.LOCK_BUSY,
                   now=T0 + timedelta(minutes=16))).execution is Execution.FAILED_APPLY


@pytest.mark.parametrize("over", [
    {"signed": False}, {"call_id_matches": False},
    {"result_returned": False, "stage": FailureStage.WRITE_STARTED},
    {"result_returned": False, "stage": FailureStage.UNCLASSIFIED},
    {"result_returned": False, "stage": None},
    {"result_returned": False, "stage": FailureStage.PRE_WRITE, "no_effect_proof": False,
     "refusal_code": ErrorCode.STALE_VERSION},
    {"result_returned": False, "stage": FailureStage.PRE_WRITE, "no_effect_proof": True, "refusal_code": None},
    {"result_returned": False, "stage": FailureStage.PRE_WRITE, "no_effect_proof": True,
     "refusal_code": ErrorCode.SCHEMA_INVALID},
    {"result_returned": True, "stage": FailureStage.WRITE_STARTED},
])
def test_t9_every_unclear_outcome_is_unknown_never_failed_apply(over):
    evidence = good(Event.CALL_SUCCESS, dispatched(), **over)
    assert ch.classify_completion(evidence) is Event.CALL_UNKNOWN
    res = apply_transition(dispatched(), Event.CALL_UNKNOWN, evidence)
    r = ok(res, "T9")
    assert (r.execution, r.call_ownership, r.attribution) == (
        Execution.APPLY_UNKNOWN, CallOwnership.POSSIBLY_EXECUTING, Attribution.NOT_APPLICABLE)
    assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (True, True, True, Reservation.RESERVED)
    assert EffectKind.OPEN_HOLD_CALL_OWNERSHIP in res.effects
    # the same evidence cannot be forced through T7 or T8
    assert type(apply_transition(dispatched(), Event.CALL_SUCCESS, evidence)) is Refusal
    assert type(apply_transition(dispatched(), Event.REFUSED_BEFORE_WRITE, evidence)) is Refusal


def test_classify_completion_picks_the_transition_by_evidence_class():
    d = dispatched()
    assert ch.classify_completion(good(Event.CALL_SUCCESS, d)) is Event.CALL_SUCCESS
    assert ch.classify_completion(good(Event.REFUSED_BEFORE_WRITE, d)) is Event.REFUSED_BEFORE_WRITE
    assert ch.classify_completion(good(Event.CALL_UNKNOWN, d)) is Event.CALL_UNKNOWN
    for bogus in (None, "x", object(), good(Event.VERIFY_OK, d)):
        assert ch.classify_completion(bogus) is Event.CALL_UNKNOWN


def test_t9_callers_generation_and_state():
    ok(step(dispatched(), Event.CALL_UNKNOWN, caller=CallerClass.RECOVERY_WORKER))
    refused(step(dispatched(), Event.CALL_UNKNOWN, caller=CallerClass.REQUESTER), "NOT_ENTITLED", "T9")
    refused(step(dispatched(), Event.CALL_UNKNOWN, generation=0), "TICKET_SUPERSEDED", "T9")
    # a clean success is never recorded as T9
    refused(step(dispatched(), Event.CALL_UNKNOWN, signed=True, call_id_matches=True, result_returned=True),
            "SCHEMA_INVALID", "T9")
    for state in (applying(), applying(Dispatch.PERMITTED), claimed()):
        assert type(step(state, Event.CALL_UNKNOWN)) is Refusal


# ---- T10 / T11 / T12 --------------------------------------------------------------------------------------------

def test_t10_found_with_independent_proof_and_attribution_applies():
    res = step(unknown(), Event.RESOLVE_FOUND)
    r = ok(res, "T10")
    assert (r.execution, r.call_ownership, r.attribution, r.reservation) == (
        Execution.APPLIED, CallOwnership.PROVEN_FINISHED, Attribution.PROVEN, Reservation.CONSUMED)
    assert (r.target_lock, r.key_lock, r.lease) == (True, False, False)
    assert res.effects == (EffectKind.RELEASE_HOLD_CALL_OWNERSHIP,)


@pytest.mark.parametrize("over, code", [
    ({"caller": CallerClass.WRITER}, "NOT_ENTITLED"), ({"caller": CallerClass.REQUESTER}, "NOT_ENTITLED"),
    ({"signed": False}, "EVIDENCE_UNSIGNED"),
    ({"proof_class": ProofClass.NONE}, "COMPLETION_PROOF_MISSING"),
    ({"proof_class": ProofClass.FORCED_TERMINATION}, "COMPLETION_PROOF_MISSING"),
    ({"reader_healthy": False}, "COMPLETION_PROOF_MISSING"), ({"settle_elapsed": False}, "COMPLETION_PROOF_MISSING"),
    ({"observation_complete": False}, "COMPLETION_PROOF_MISSING"), ({"effect_present": False}, "SCHEMA_INVALID"),
    ({"effect_identity_match": False}, "ATTRIBUTION_UNPROVEN"), ({"exclusivity_proven": False}, "ATTRIBUTION_UNPROVEN"),
])
def test_t10_refusals(over, code):
    refused(step(unknown(), Event.RESOLVE_FOUND, **over), code, "T10")


def test_t10_session_end_observed_is_an_independent_proof_class():
    ok(step(unknown(), Event.RESOLVE_FOUND, proof_class=ProofClass.SESSION_END_OBSERVED))


def test_in_this_contract_version_an_unknown_outcome_effect_cannot_be_attributed_so_it_goes_to_triage():
    # exclusivity is UNPROVEN for every unknown-outcome resolution (section 5): T10 refuses, T12 accepts
    unattributed = {"exclusivity_proven": False}
    refused(step(unknown(), Event.RESOLVE_FOUND, **unattributed), "ATTRIBUTION_UNPROVEN", "T10")
    res = step(unknown(), Event.AGE_LIMIT, attempts=0, first_attempt_at=None, effect_present=True,
               observation_complete=True, signed=True, effect_identity_match=True, exclusivity_proven=False)
    r = ok(res, "T12")
    assert r.execution is Execution.TRIAGE_REQUIRED and EffectKind.ALERT_HUMAN in res.effects
    # a key/content mismatch also goes to triage
    ok(step(unknown(), Event.AGE_LIMIT, attempts=0, first_attempt_at=None, effect_present=True,
            observation_complete=True, signed=True, effect_identity_match=False, exclusivity_proven=False), "T12")


def test_t11_absent_with_independent_proof_fails_the_apply_and_releases():
    res = step(unknown(), Event.RESOLVE_ABSENT)
    r = ok(res, "T11")
    assert (r.execution, r.call_ownership, r.reservation) == (
        Execution.FAILED_APPLY, CallOwnership.PROVEN_FINISHED, Reservation.RELEASED)
    assert (r.target_lock, r.key_lock, r.lease) == (False, False, False)
    assert res.effects == (EffectKind.RELEASE_HOLD_CALL_OWNERSHIP,)


@pytest.mark.parametrize("over, code", [
    ({"caller": CallerClass.WRITER}, "NOT_ENTITLED"), ({"signed": False}, "EVIDENCE_UNSIGNED"),
    ({"proof_class": ProofClass.NONE}, "COMPLETION_PROOF_MISSING"),
    ({"proof_class": ProofClass.FORCED_TERMINATION}, "COMPLETION_PROOF_MISSING"),
    ({"reader_healthy": False}, "COMPLETION_PROOF_MISSING"), ({"settle_elapsed": False}, "COMPLETION_PROOF_MISSING"),
    ({"observation_complete": False}, "COMPLETION_PROOF_MISSING"), ({"effect_present": True}, "SCHEMA_INVALID"),
    ({"checkpoint_ok": False}, "CHECKPOINT_UNAVAILABLE"),
])
def test_t11_refusals_a_missing_marker_or_a_deadline_never_qualifies(over, code):
    refused(step(unknown(), Event.RESOLVE_ABSENT, **over), code, "T11")
    far_future = T0 + timedelta(days=30)
    refused(step(unknown(), Event.RESOLVE_ABSENT, now=far_future, proof_class=ProofClass.NONE),
            "COMPLETION_PROOF_MISSING", "T11")


@pytest.mark.parametrize("event", [Event.RESOLVE_FOUND, Event.RESOLVE_ABSENT, Event.AGE_LIMIT])
@pytest.mark.parametrize("state", [dispatched(), triage(), applied(), applying()])
def test_resolution_only_from_apply_unknown(event, state):
    assert type(step(state, event)) is Refusal


def test_t12_age_limit_needs_five_attempts_over_fifteen_minutes_and_keeps_everything():
    res = step(unknown(), Event.AGE_LIMIT)
    r = ok(res, "T12")
    assert (r.execution, r.call_ownership, r.reservation) == (
        Execution.TRIAGE_REQUIRED, CallOwnership.POSSIBLY_EXECUTING, Reservation.RESERVED)
    assert (r.target_lock, r.key_lock, r.lease) == (True, True, True)
    assert EffectKind.ALERT_HUMAN in res.effects
    refused(step(unknown(), Event.AGE_LIMIT, attempts=4), "SCHEMA_INVALID", "T12")
    refused(step(unknown(), Event.AGE_LIMIT, first_attempt_at=T0 - timedelta(minutes=14)), "SCHEMA_INVALID", "T12")
    refused(step(unknown(), Event.AGE_LIMIT, first_attempt_at=None), "SCHEMA_INVALID", "T12")
    refused(step(unknown(), Event.AGE_LIMIT, caller=CallerClass.WRITER), "NOT_ENTITLED", "T12")
    ok(step(unknown(), Event.AGE_LIMIT, first_attempt_at=T0 - timedelta(minutes=15)))


def test_t12_present_effect_rules():
    present = {"attempts": 0, "first_attempt_at": None, "effect_present": True, "observation_complete": True}
    refused(step(unknown(), Event.AGE_LIMIT, signed=False, **present), "EVIDENCE_UNSIGNED", "T12")
    # an attributable effect must go through T10, not triage
    refused(step(unknown(), Event.AGE_LIMIT, signed=True, effect_identity_match=True, exclusivity_proven=True,
                 **present), "SCHEMA_INVALID", "T12")
    refused(step(unknown(), Event.AGE_LIMIT, attempts=0, first_attempt_at=None), "SCHEMA_INVALID", "T12")


# ---- T13 / T14 --------------------------------------------------------------------------------------------------

def test_t13_verification_releases_target_and_key_locks_and_keeps_consumed():
    r = ok(step(applied(target_lock=True, key_lock=True), Event.VERIFY_OK), "T13")
    assert r.verification is Verification.VERIFIED and r.execution is Execution.APPLIED
    assert (r.target_lock, r.key_lock, r.reservation) == (False, False, Reservation.CONSUMED)


@pytest.mark.parametrize("over, code", [
    ({"caller": CallerClass.WRITER}, "NOT_ENTITLED"), ({"caller": CallerClass.REQUESTER}, "NOT_ENTITLED"),
    ({"bound": False}, "EVIDENCE_UNSIGNED"), ({"signed_kinds": frozenset()}, "EVIDENCE_UNSIGNED"),
    ({"signed_kinds": h.VERIFY_KINDS - {h.EvidenceKind.FIELD}}, "EVIDENCE_UNSIGNED"),
    ({"signed_kinds": h.VERIFY_KINDS - {h.EvidenceKind.MOVEMENT}}, "EVIDENCE_UNSIGNED"),
    ({"signed_kinds": h.VERIFY_KINDS - {h.EvidenceKind.VERSION}}, "EVIDENCE_UNSIGNED"),
    ({"signed_kinds": {h.EvidenceKind.FIELD}}, "EVIDENCE_UNSIGNED"),
    ({"matches": False}, "VERIFY_FAILED"),
])
def test_t13_refusals_need_signed_bound_field_movement_and_version_evidence(over, code):
    refused(step(applied(), Event.VERIFY_OK, **over), code, "T13")


@pytest.mark.parametrize("state", [dispatched(), unknown(), triage(), failed_verify(),
                                   applied(verification=Verification.VERIFIED), applying()])
def test_t13_only_from_applied_not_verified(state):
    assert type(step(state, Event.VERIFY_OK)) is Refusal


def test_t14_failed_verification_records_effect_known_and_opens_the_halt():
    for known in EffectKnown:
        res = step(applied(target_lock=True, key_lock=True), Event.VERIFY_FAILED, effect_known=known)
        r = ok(res, "T14")
        assert (r.verification, r.effect_known, r.reservation) == (Verification.FAILED_VERIFY, known,
                                                                  Reservation.CONSUMED)
        assert (r.target_lock, r.key_lock) == (True, False)
        assert {EffectKind.OPEN_HOLD_FAILED_VERIFY_HALT, EffectKind.ALERT_HUMAN} <= set(res.effects)


@pytest.mark.parametrize("over, code", [
    ({"matches": True}, "SCHEMA_INVALID"), ({"effect_known": None}, "SCHEMA_INVALID"),
    ({"bound": False}, "EVIDENCE_UNSIGNED"), ({"caller": CallerClass.WRITER}, "NOT_ENTITLED"),
    ({"signed_kinds": frozenset()}, "EVIDENCE_UNSIGNED"),
])
def test_t14_refusals(over, code):
    refused(step(applied(), Event.VERIFY_FAILED, **over), code, "T14")


def test_verified_repair_reconciles_the_failed_parent():
    res = step(repair_live(applied), Event.VERIFY_OK)
    assert {EffectKind.MARK_PARENT_SUPERSEDED, EffectKind.RELEASE_HOLD_FAILED_VERIFY_HALT,
            EffectKind.RECONCILE_AMOUNT_CONSUMED} <= set(res.effects)
    plain = step(applied(), Event.VERIFY_OK)
    assert EffectKind.MARK_PARENT_SUPERSEDED not in plain.effects


# ---- T15 revoke -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cause, auth", [
    (RevokeCause.SESSION_REVOKED, Authorization.REVOKED), (RevokeCause.ROLE_REVOKED, Authorization.REVOKED),
    (RevokeCause.APPROVER_REVOKED, Authorization.REVOKED),
    (RevokeCause.EPOCH_DEPENDENCY_CHANGED, Authorization.VOIDED),
    (RevokeCause.KILL_SWITCH_REVOKE, Authorization.VOIDED),
])
def test_t15_revoke_before_claim_and_while_claimed(cause, auth):
    r = ok(step(approved(), Event.REVOKE, cause=cause), "T15")
    assert r.authorization is auth and r.reservation is Reservation.NONE and r.execution is Execution.NOT_STARTED
    res = step(claimed(), Event.REVOKE, cause=cause)
    c = ok(res, "T15")
    assert c.authorization is auth and c.token is TokenState.REVOKED
    assert (c.target_lock, c.key_lock, c.lease, c.reservation) == (False, False, False, Reservation.RELEASED)
    assert c.claim_expires_at is None
    assert EffectKind.HAND_LOCK_BACK_TO_PARENT not in res.effects


def test_t15_refusals_and_pre_dispatch_only():
    refused(step(approved(), Event.REVOKE, cause=None), "SCHEMA_INVALID", "T15")
    refused(step(approved(), Event.REVOKE, cause="SESSION_REVOKED"), "SCHEMA_INVALID", "T15")
    for state in (applying(), applying(Dispatch.PERMITTED), dispatched(), unknown(), applied(), proposed(),
                  validated()):
        assert type(step(state, Event.REVOKE)) is Refusal


def test_revoked_or_voided_change_cannot_be_claimed_or_begun_again():
    for cause in RevokeCause:
        dead = ok(step(claimed(), Event.REVOKE, cause=cause))
        for event in (Event.CLAIM, Event.BEGIN_APPLY, Event.RELEASE_CLAIM, Event.APPROVE, Event.REVOKE):
            assert type(step(dead, event)) is Refusal


# ---- T16 operator_resolve ---------------------------------------------------------------------------------------

def test_t16_absent_fails_the_apply_and_releases_with_completion_proof():
    res = step(triage(), Event.OPERATOR_RESOLVE)
    r = ok(res, "T16")
    assert (r.execution, r.call_ownership, r.reservation) == (
        Execution.FAILED_APPLY, CallOwnership.PROVEN_FINISHED, Reservation.RELEASED)
    assert (r.target_lock, r.key_lock, r.lease) == (False, False, False)
    assert res.effects == (EffectKind.RELEASE_HOLD_CALL_OWNERSHIP,)


def test_t16_present_unattributed_is_marked_and_consumes_but_keeps_the_target_lock():
    r = ok(step(triage(), Event.OPERATOR_RESOLVE, outcome=ResolveOutcome.PRESENT_UNATTRIBUTED), "T16")
    assert (r.execution, r.attribution, r.reservation, r.call_ownership) == (
        Execution.APPLIED, Attribution.UNPROVEN_OPERATOR_ATTESTED, Reservation.CONSUMED,
        CallOwnership.PROVEN_FINISHED)
    assert (r.target_lock, r.key_lock, r.lease) == (True, False, False)
    assert r.verification is Verification.NOT_VERIFIED  # still needs T13


def test_t16_present_attributed_needs_identity_and_exclusivity():
    attributed = {"outcome": ResolveOutcome.PRESENT_ATTRIBUTED}
    refused(step(triage(), Event.OPERATOR_RESOLVE, **attributed), "ATTRIBUTION_UNPROVEN", "T16")
    refused(step(triage(), Event.OPERATOR_RESOLVE, effect_identity_match=True, **attributed),
            "ATTRIBUTION_UNPROVEN", "T16")
    r = ok(step(triage(), Event.OPERATOR_RESOLVE, effect_identity_match=True, exclusivity_proven=True, **attributed))
    assert r.attribution is Attribution.PROVEN


@pytest.mark.parametrize("over, code", [
    ({"proof_class": ProofClass.NONE}, "COMPLETION_PROOF_MISSING"),
    ({"proof_class": ProofClass.FORCED_TERMINATION}, "COMPLETION_PROOF_MISSING"),
    ({"reader_healthy": False}, "COMPLETION_PROOF_MISSING"), ({"settle_elapsed": False}, "COMPLETION_PROOF_MISSING"),
    ({"observation_complete": False}, "COMPLETION_PROOF_MISSING"),
    ({"operator_person_id": REQUESTER}, "APPROVER_NOT_INDEPENDENT"),
    ({"witness_person_id": REQUESTER}, "APPROVER_NOT_INDEPENDENT"),
    ({"witness_person_id": OPERATOR}, "APPROVER_NOT_INDEPENDENT"),
    ({"operator_class": CallerClass.APPROVER}, "NOT_ENTITLED"), ({"operator_class": None}, "NOT_ENTITLED"),
    ({"witness_class": None}, "NOT_ENTITLED"), ({"witness_class": CallerClass.OPERATOR}, "NOT_ENTITLED"),
    ({"witness_person_id": ""}, "NOT_ENTITLED"), ({"operator_person_id": ""}, "NOT_ENTITLED"),
    ({"outcome": None}, "SCHEMA_INVALID"), ({"signed": False}, "EVIDENCE_UNSIGNED"),
    ({"checkpoint_ok": False}, "CHECKPOINT_UNAVAILABLE"),
])
def test_t16_refusals_leave_the_change_in_triage_with_nothing_released(over, code):
    state = triage()
    res = step(state, Event.OPERATOR_RESOLVE, **over)
    refused(res, code, "T16")
    assert state.execution is Execution.TRIAGE_REQUIRED and state.lease and state.target_lock


def test_t16_without_completion_proof_is_completion_proof_missing_even_when_everything_else_is_valid():
    refused(step(triage(), Event.OPERATOR_RESOLVE, proof_class=ProofClass.NONE, outcome=ResolveOutcome.ABSENT),
            "COMPLETION_PROOF_MISSING", "T16")
    for outcome in ResolveOutcome:
        refused(step(triage(), Event.OPERATOR_RESOLVE, proof_class=ProofClass.NONE, outcome=outcome),
                "COMPLETION_PROOF_MISSING", "T16")


def test_t16_same_person_twice_and_requester_as_operator_are_refused_and_the_approver_rule():
    refused(step(triage(), Event.OPERATOR_RESOLVE, operator_person_id="p-x", witness_person_id="p-x"),
            "APPROVER_NOT_INDEPENDENT", "T16")
    refused(step(triage(), Event.OPERATOR_RESOLVE, operator_person_id=REQUESTER), "APPROVER_NOT_INDEPENDENT", "T16")
    # the operator who approved the change may co-sign only with an independent witness (S12-M05)
    ok(step(triage(), Event.OPERATOR_RESOLVE, operator_person_id=APPROVER))
    ok(step(triage(), Event.OPERATOR_RESOLVE, witness_person_id=APPROVER))
    refused(step(triage(), Event.OPERATOR_RESOLVE, operator_person_id=APPROVER, witness_person_id=APPROVER),
            "APPROVER_NOT_INDEPENDENT", "T16")


@pytest.mark.parametrize("state", [unknown(), dispatched(), applied(), failed_verify(), approved()])
def test_t16_only_from_triage_required(state):
    assert type(step(state, Event.OPERATOR_RESOLVE)) is Refusal


def test_t16_repeated_resolution_is_idempotent_and_cannot_change_reservation():
    first = ok(step(triage(), Event.OPERATOR_RESOLVE))
    assert type(step(first, Event.OPERATOR_RESOLVE)) is Refusal
    assert first.reservation is Reservation.RELEASED
    assert type(step(first, Event.OPERATOR_RESOLVE, outcome=ResolveOutcome.PRESENT_UNATTRIBUTED)) is Refusal


# ---- T17 ----------------------------------------------------------------------------------------------------------

def test_t17_retry_verify_success_releases_the_halt_and_the_target_lock():
    res = step(failed_verify(target_lock=True), Event.RETRY_VERIFY)
    r = ok(res, "T17")
    assert r.verification is Verification.VERIFIED and r.target_lock is False and r.reservation is Reservation.CONSUMED
    assert EffectKind.RELEASE_HOLD_FAILED_VERIFY_HALT in res.effects


def test_t17_retry_that_still_fails_counts_attempts_up_to_the_bound_of_three():
    state = failed_verify(target_lock=True)
    for expected in (1, 2, 3):
        state = ok(step(state, Event.RETRY_VERIFY, matches=False), "T17")
        assert state.verification is Verification.FAILED_VERIFY and state.verify_attempts == expected
        assert state.target_lock is True
    refused(step(state, Event.RETRY_VERIFY, matches=False), "VERIFY_FAILED", "T17")
    refused(step(state, Event.RETRY_VERIFY, matches=True), "VERIFY_FAILED", "T17")


@pytest.mark.parametrize("over, code", [
    ({"caller": CallerClass.WRITER}, "NOT_ENTITLED"), ({"bound": False}, "EVIDENCE_UNSIGNED"),
    ({"signed_kinds": frozenset()}, "EVIDENCE_UNSIGNED"),
])
def test_t17_retry_refusals(over, code):
    refused(step(failed_verify(), Event.RETRY_VERIFY, **over), code, "T17")


def test_t17_close_by_two_people_releases_the_halt_and_closes_the_change():
    res = step(failed_verify(target_lock=True), Event.CLOSE_FAILED_VERIFY)
    r = ok(res, "T17")
    assert r.closed is True and r.verification is Verification.FAILED_VERIFY and r.target_lock is False
    assert EffectKind.RELEASE_HOLD_FAILED_VERIFY_HALT in res.effects
    for event in Event:
        if event is not Event.PROPOSE:
            assert type(step(r, event)) is Refusal, event


@pytest.mark.parametrize("over, code", [
    ({"operator_person_id": REQUESTER}, "APPROVER_NOT_INDEPENDENT"),
    ({"witness_person_id": OPERATOR}, "APPROVER_NOT_INDEPENDENT"),
    ({"witness_class": None}, "NOT_ENTITLED"), ({"signed": False}, "EVIDENCE_UNSIGNED"),
    ({"observation_complete": False}, "COMPLETION_PROOF_MISSING"),
])
def test_t17_close_refusals(over, code):
    refused(step(failed_verify(), Event.CLOSE_FAILED_VERIFY, **over), code, "T17")


@pytest.mark.parametrize("event", [Event.RETRY_VERIFY, Event.CLOSE_FAILED_VERIFY])
@pytest.mark.parametrize("state", [applied(), unknown(), applied(verification=Verification.VERIFIED)])
def test_t17_only_from_open_failed_verify(event, state):
    assert type(step(state, event)) is Refusal


# =====================================================================================================================
# 5. forbidden transitions (literal list, section 4)
# =====================================================================================================================

def test_forbidden_list_is_the_literal_contract_list():
    assert [f.fid for f in ch.FORBIDDEN_TRANSITIONS] == ["F1", "F2", "F3", "F4", "F5"]
    text = " | ".join(f.description for f in ch.FORBIDDEN_TRANSITIONS)
    for phrase in ("timeout", "APPLY_UNKNOWN", "independent PROVEN_FINISHED", "APPLIED to VERIFIED", "REJECTED",
                   "EXPIRED_QUEUED", "DUPLICATE_PARKED", "ROLLBACK_REFUSED", "FAILED_APPLY", "VERIFIED to anything"):
        assert phrase in text, phrase


def test_f1_failed_apply_from_a_timeout_is_forbidden_and_unreachable():
    before = dispatched()
    after = replace(before, execution=Execution.FAILED_APPLY)
    assert ch.forbidden_transition(before, after, Event.CALL_UNKNOWN, True).fid == "F1"
    # every timeout-class evidence ends in APPLY_UNKNOWN, never FAILED_APPLY
    for over in ({"signed": False}, {"result_returned": False, "stage": FailureStage.UNCLASSIFIED},
                 {"result_returned": False, "stage": FailureStage.WRITE_STARTED}):
        res = apply_transition(before, Event.CALL_UNKNOWN, good(Event.CALL_SUCCESS, before, **over))
        assert ok(res).execution is Execution.APPLY_UNKNOWN


def test_f2_unknown_to_applied_or_failed_apply_needs_independent_proof():
    before = unknown()
    for target in (Execution.APPLIED, Execution.FAILED_APPLY):
        after = replace(before, execution=target)
        assert ch.forbidden_transition(before, after, Event.RESOLVE_FOUND, False).fid == "F2"
        assert ch.forbidden_transition(before, after, Event.RESOLVE_FOUND, True) is None
    for proof in (ProofClass.NONE, ProofClass.FORCED_TERMINATION):
        refused(step(before, Event.RESOLVE_FOUND, proof_class=proof), "COMPLETION_PROOF_MISSING")
        refused(step(before, Event.RESOLVE_ABSENT, proof_class=proof), "COMPLETION_PROOF_MISSING")


def test_f3_applied_to_verified_only_through_t13():
    before = applied()
    after = replace(before, verification=Verification.VERIFIED)
    assert ch.forbidden_transition(before, after, Event.CALL_SUCCESS, True).fid == "F3"
    assert ch.forbidden_transition(before, after, Event.OPERATOR_RESOLVE, True).fid == "F3"
    assert ch.forbidden_transition(before, after, Event.VERIFY_OK, True) is None
    for event in Event:
        if event in (Event.VERIFY_OK, Event.RETRY_VERIFY, Event.PROPOSE):
            continue
        res = step(before, event)
        if type(res) is Applied:
            assert res.record.verification is not Verification.VERIFIED, event


@pytest.mark.parametrize("terminal", [
    validated(lifecycle=Lifecycle.REJECTED), validated(lifecycle=Lifecycle.EXPIRED_QUEUED),
    validated(lifecycle=Lifecycle.DUPLICATE_PARKED), dispatched(execution=Execution.ROLLBACK_REFUSED),
    dispatched(execution=Execution.FAILED_APPLY),
    ok(step(approved(), Event.REJECT)), ok(step(proposed(), Event.EXPIRE)),
    ok(step(proposed(), Event.VALIDATE, key_state=h.BusinessKeyState.COLLISION)),
    ok(step(dispatched(), Event.REFUSED_BEFORE_WRITE)), ok(step(unknown(), Event.RESOLVE_ABSENT)),
    ok(step(triage(), Event.OPERATOR_RESOLVE)),
])
def test_f4_nothing_leaves_a_terminal_state_except_a_new_proposal(terminal):
    for event in Event:
        assert type(step(terminal, event)) is Refusal, event
    changed = replace(terminal, lifecycle=Lifecycle.VALIDATED, execution=Execution.NOT_STARTED)
    assert ch.forbidden_transition(terminal, changed, Event.CLAIM, True).fid == "F4"


def test_f5_verified_goes_nowhere():
    verified = ok(step(applied(), Event.VERIFY_OK))
    assert verified.verification is Verification.VERIFIED
    for event in Event:
        assert type(step(verified, event)) is Refusal, event
    assert ch.forbidden_transition(verified, replace(verified, closed=True), Event.CLOSE_FAILED_VERIFY, True).fid == "F5"


def test_forbidden_transition_ignores_non_records_and_identity_transitions():
    assert ch.forbidden_transition(None, None, Event.CLAIM, True) is None
    r = applied()
    assert ch.forbidden_transition(r, r, Event.VERIFY_OK, True) is None


# =====================================================================================================================
# 6. zero-effect exits of a repair hand the lock back; no handback after dispatch or unknown (section 4.2)
# =====================================================================================================================

HANDBACK = {EffectKind.INVALIDATE_REPAIR_AUTH, EffectKind.HAND_LOCK_BACK_TO_PARENT}


def _assert_handback(res, tid):
    r = ok(res, tid)
    assert HANDBACK <= set(res.effects)
    assert r.repair is None  # the repair authorization is invalidated
    assert (r.target_lock, r.key_lock, r.lease) == (False, False, False)  # only the repair's own rows are released
    assert r.reservation is Reservation.RELEASED  # the repair's own reservation
    return r


def _assert_no_handback(res, tid):
    r = ok(res, tid)
    assert not (HANDBACK & set(res.effects))
    assert r.repair == REPAIR_AUTH and r.target_lock is True  # the repair keeps its ownership
    return r


@pytest.mark.parametrize("label, state, event, over, tid", [
    ("T5x ttl", repair_live(claimed), Event.RELEASE_CLAIM, {}, "T5x"),
    ("T5x kill", repair_live(claimed), Event.RELEASE_CLAIM,
     {"reason": ReleaseReason.KILL_SWITCH, "kill": kill(KillMode.STOP_EFFECTS)}, "T5x"),
    ("T6r", repair_live(applying), Event.PERMIT_NOT_ISSUED, {}, "T6r"),
    ("T6c", repair_live(applying, dispatch=Dispatch.PERMITTED), Event.CANCEL_PERMIT, {}, "T6c"),
    ("T8 definite", repair_live(dispatched), Event.REFUSED_BEFORE_WRITE, {}, "T8"),
    ("T8 rollback refused", repair_live(dispatched), Event.REFUSED_BEFORE_WRITE,
     {"refusal_code": ErrorCode.ROLLBACK_REFUSED}, "T8"),
    ("T8 transient", repair_live(dispatched), Event.REFUSED_BEFORE_WRITE,
     {"refusal_code": ErrorCode.LOCK_BUSY}, "T8"),
    ("T15 approved-claimed", repair_live(claimed), Event.REVOKE, {}, "T15"),
])
def test_every_zero_effect_exit_of_a_repair_hands_the_lock_back(label, state, event, over, tid):
    _assert_handback(step(state, event, **over), tid)


def test_t8_rollback_refused_for_a_repair_is_terminal_and_hands_back():
    r = _assert_handback(step(repair_live(dispatched), Event.REFUSED_BEFORE_WRITE,
                              refusal_code=ErrorCode.ROLLBACK_REFUSED), "T8")
    assert r.execution is Execution.ROLLBACK_REFUSED


def test_a_non_repair_change_never_emits_handback_effects():
    for state, event, over in [(claimed(), Event.RELEASE_CLAIM, {}), (applying(), Event.PERMIT_NOT_ISSUED, {}),
                               (applying(Dispatch.PERMITTED), Event.CANCEL_PERMIT, {}),
                               (dispatched(), Event.REFUSED_BEFORE_WRITE, {}), (claimed(), Event.REVOKE, {})]:
        assert not (HANDBACK & set(step(state, event, **over).effects))


def test_no_handback_after_dispatch_or_unknown_outcome():
    sent = _assert_no_handback(step(repair_live(applying, dispatch=Dispatch.PERMITTED), Event.MARK_DISPATCHED), "T6p")
    assert sent.dispatch is Dispatch.DISPATCHED
    r7 = ok(step(repair_live(dispatched), Event.CALL_SUCCESS), "T7")
    assert r7.repair == REPAIR_AUTH and r7.target_lock is True
    r9 = _assert_no_handback(step(repair_live(dispatched), Event.CALL_UNKNOWN), "T9")
    assert r9.execution is Execution.APPLY_UNKNOWN and (r9.key_lock, r9.lease) == (True, True)
    assert r9.reservation is Reservation.RESERVED
    r12 = _assert_no_handback(step(repair_live(unknown), Event.AGE_LIMIT), "T12")
    assert r12.execution is Execution.TRIAGE_REQUIRED
    # the first repair stays bound: a second repair cannot claim the same halt while one is unresolved
    refused(step(repair_rec(change_id="r2"), Event.CLAIM, repair_ctx=repair_ctx(other_repair_exists=True)),
            "LOCK_BUSY", "T5")
    refused(step(repair_rec(change_id="r2"), Event.CLAIM, repair_ctx=repair_ctx(target_lock_owner=REPAIR_ID)),
            "LOCK_BUSY", "T5")


def test_repair_after_handback_can_be_claimed_again_with_a_new_authorization():
    back = _assert_handback(step(repair_live(claimed), Event.RELEASE_CLAIM), "T5x")
    again = ok(step(back, Event.CLAIM, repair_ctx=repair_ctx()), "T5")
    assert again.claim_generation == 2 and again.repair == dataclasses.replace(REPAIR_AUTH, claim_generation=2)


# =====================================================================================================================
# 7. kill-switch matrix (section 6) and fail-closed reading
# =====================================================================================================================

S, K = KillSubject, KillMode
_REFUSE3 = ("REFUSED",) * 3
EXPECTED_KILL = {
    S.PROPOSE_VALIDATE_APPROVE: _REFUSE3, S.CLAIM: _REFUSE3,
    S.CLAIMED_CHANGE: ("RELEASE_T5X", "RELEASE_T5X", "RELEASE_T5X_VOID_APPROVAL"),
    S.BEGIN_APPLY_ISSUE_PERMIT: _REFUSE3, S.APPLYING_NOT_PERMITTED: ("T6R",) * 3,
    S.APPLYING_PERMITTED_UNDISPATCHED: ("T6C_CANCEL_CAS",) * 3,
    S.APPLYING_DISPATCHED: ("FOLLOW_CALL_NO_NEW_CALL",) * 3,
    S.APPROVED_UNCLAIMED: ("KEPT", "KEPT", "VOIDED"),
    S.OBSERVATION: ("ALLOWED", "ALLOWED", "OBSERVATION_OPERATOR_GATED"),
    S.OPERATOR_OPERATIONS: ("ALLOWED",) * 3,
}
MODES = (K.STOP_ADMIT, K.STOP_EFFECTS, K.REVOKE)


def test_kill_matrix_equals_the_contract_table_for_every_subject_and_mode():
    assert set(EXPECTED_KILL) == set(KillSubject)
    for subject, decisions in EXPECTED_KILL.items():
        for mode, decision in zip(MODES, decisions, strict=True):
            assert ch.KILL_MATRIX[(subject, mode)] == decision, (subject, mode)
            assert ch.evaluate(subject, kill(mode)) == decision


def test_kill_off_proceeds_for_every_subject_and_unavailable_store_is_stop_effects():
    for subject in KillSubject:
        assert ch.evaluate(subject, SWITCH_OFF) is KillDecision.PROCEED
        assert ch.evaluate(subject, UNREADABLE) == ch.evaluate(subject, kill(K.STOP_EFFECTS))
        assert ch.evaluate(subject, UNREADABLE) is not KillDecision.PROCEED
    assert ch.effective_mode(UNREADABLE) is K.STOP_EFFECTS
    assert ch.effective_mode(SWITCH_OFF) is None
    for bogus in (None, "STOP_ADMIT", 5, SwitchReading(True, "STOP_ADMIT"), SwitchReading(False, K.REVOKE),
                  SwitchReading(available=1, mode=None)):
        assert ch.effective_mode(bogus) is K.STOP_EFFECTS, bogus
    assert ch.evaluate("CLAIM", kill(K.STOP_ADMIT)) is KillDecision.REFUSED
    assert ch.evaluate(None, SWITCH_OFF) is KillDecision.REFUSED  # unknown subject fails closed


def test_modes_are_ordered_and_each_includes_the_previous():
    assert ch.mode_rank(None) == 0
    assert ch.mode_rank(K.STOP_ADMIT) < ch.mode_rank(K.STOP_EFFECTS) < ch.mode_rank(K.REVOKE)
    assert ch.mode_rank("something-unknown") == ch.mode_rank(K.STOP_EFFECTS)
    for subject in KillSubject:
        decisions = [ch.KILL_MATRIX[(subject, m)] for m in MODES]
        if subject in (S.PROPOSE_VALIDATE_APPROVE, S.CLAIM, S.BEGIN_APPLY_ISSUE_PERMIT):
            assert set(decisions) == {KillDecision.REFUSED}


READINGS = [kill(K.STOP_ADMIT), kill(K.STOP_EFFECTS), kill(K.REVOKE), UNREADABLE]


@pytest.mark.parametrize("reading", READINGS)
def test_engine_refuses_admission_claim_begin_permit_and_dispatch_under_every_mode(reading):
    refused(step(proposed(), Event.VALIDATE, kill=reading), "KILL_SWITCH_ACTIVE")
    refused(step(validated(), Event.APPROVE, kill=reading), "KILL_SWITCH_ACTIVE")
    refused(step(approved(), Event.CLAIM, kill=reading), "KILL_SWITCH_ACTIVE")
    refused(step(claimed(), Event.BEGIN_APPLY, kill=reading), "KILL_SWITCH_ACTIVE")
    refused(step(applying(), Event.ISSUE_PERMIT, kill=reading), "KILL_SWITCH_ACTIVE")
    refused(step(applying(Dispatch.PERMITTED), Event.MARK_DISPATCHED, kill=reading), "KILL_SWITCH_ACTIVE")
    refused(apply_transition(None, Event.PROPOSE, good(Event.PROPOSE, None, kill=reading)), "KILL_SWITCH_ACTIVE")


@pytest.mark.parametrize("reading", READINGS)
def test_engine_unwinds_claimed_and_undispatched_changes_under_every_mode(reading):
    void = reading.available and reading.mode is K.REVOKE
    expected = Authorization.VOIDED if void else Authorization.APPROVED
    r = ok(step(claimed(), Event.RELEASE_CLAIM, reason=ReleaseReason.KILL_SWITCH, kill=reading), "T5x")
    assert r.authorization is expected and r.lease is False
    ok(step(applying(), Event.PERMIT_NOT_ISSUED, checkpoint_unavailable=False, kill=reading), "T6r")
    r = ok(step(applying(Dispatch.PERMITTED), Event.CANCEL_PERMIT, kill=reading), "T6c")
    assert r.dispatch is Dispatch.CANCELLED_UNDISPATCHED


@pytest.mark.parametrize("reading", READINGS)
def test_a_dispatched_call_follows_its_outcome_and_observation_and_operator_work_continue(reading):
    assert ok(step(dispatched(), Event.CALL_SUCCESS, kill=reading)).execution is Execution.APPLIED
    assert ok(step(dispatched(), Event.CALL_UNKNOWN, kill=reading)).execution is Execution.APPLY_UNKNOWN
    ok(step(dispatched(), Event.REFUSED_BEFORE_WRITE, kill=reading), "T8")
    assert type(step(dispatched(), Event.MARK_DISPATCHED, kill=reading)) is Refusal  # no new call
    ok(step(unknown(), Event.RESOLVE_ABSENT, kill=reading), "T11")
    ok(step(unknown(), Event.RESOLVE_FOUND, kill=reading), "T10")
    ok(step(applied(), Event.VERIFY_OK, kill=reading), "T13")
    ok(step(applied(), Event.VERIFY_FAILED, kill=reading), "T14")
    ok(step(triage(), Event.OPERATOR_RESOLVE, kill=reading), "T16")


def test_revoke_voids_an_unclaimed_approval_via_t15():
    r = ok(step(approved(), Event.REVOKE, cause=RevokeCause.KILL_SWITCH_REVOKE), "T15")
    assert r.authorization is Authorization.VOIDED


# =====================================================================================================================
# 8. caller-class matrix (section 2) and operation policy
# =====================================================================================================================

O, C = LedgerOperation, CallerClass
_ALL_OPS = set(LedgerOperation)
EXPECTED_ALLOWED = {
    C.REQUESTER: {O.PROPOSE, O.VALIDATE, O.CLAIM, O.RELEASE_CLAIM, O.BEGIN_APPLY, O.READ_STATUS},
    C.APPROVER: {O.APPROVE, O.REJECT, O.READ_STATUS},
    C.OPERATOR: {O.KILL_SWITCH, O.RELEASE_HOLD, O.BUDGET_ADMIN, O.OPERATOR_RESOLVE},
    C.RECOVERY_WITNESS: {O.OPERATOR_RESOLVE},
    C.WRITER: {O.COMPLETE, O.READ_OBSERVATION, O.RECORD_CALL, O.BEGIN_APPLY},
    C.RECOVERY_WORKER: {O.RECOVER_SWEEP, O.RESOLVE_UNKNOWN, O.VERIFY, O.RELEASE_CLAIM, O.COMPLETE, O.READ_OBSERVATION},
    C.AUDITOR: {O.READ_STATUS, O.READ_EVIDENCE},
}
INTERNAL = {O.ISSUE_PERMIT, O.BUDGET_RESERVE, O.BUDGET_CONSUME, O.BUDGET_RELEASE}


def test_operation_list_equals_the_contract_endpoint_list():
    names = {"PROPOSE", "VALIDATE", "APPROVE", "REJECT", "CLAIM", "RELEASE_CLAIM", "BEGIN_APPLY", "ISSUE_PERMIT",
             "RECORD_CALL", "COMPLETE", "RECOVER_SWEEP", "RESOLVE_UNKNOWN", "OPERATOR_RESOLVE", "RELEASE_HOLD",
             "VERIFY", "KILL_SWITCH", "BUDGET_RESERVE", "BUDGET_CONSUME", "BUDGET_RELEASE", "BUDGET_ADMIN",
             "READ_STATUS", "READ_EVIDENCE", "READ_OBSERVATION"}
    assert {o.name for o in LedgerOperation} == names


def test_full_caller_by_operation_matrix_equals_the_contract():
    for caller in CallerClass:
        for op in LedgerOperation:
            expected = None if op in EXPECTED_ALLOWED[caller] else ErrorCode.NOT_ENTITLED
            assert ch.check_operation(caller, op) is expected, (caller, op)
            res = ch.authorize_operation(caller, op)
            assert (res is None) if expected is None else (res.code is ErrorCode.NOT_ENTITLED)


def test_named_cross_class_prohibitions_from_section_2():
    for op in (O.APPROVE, O.REJECT, O.COMPLETE, O.VERIFY, O.RESOLVE_UNKNOWN, O.KILL_SWITCH, O.OPERATOR_RESOLVE,
               O.RELEASE_HOLD, O.BUDGET_ADMIN, O.RECOVER_SWEEP):
        assert ch.check_operation(C.REQUESTER, op) is ErrorCode.NOT_ENTITLED, op
    for op in (O.CLAIM, O.BEGIN_APPLY, O.PROPOSE, O.VALIDATE, O.COMPLETE, O.VERIFY, O.KILL_SWITCH):
        assert ch.check_operation(C.APPROVER, op) is ErrorCode.NOT_ENTITLED, op
    for op in (O.APPROVE, O.REJECT, O.CLAIM, O.PROPOSE, O.COMPLETE, O.VERIFY):
        assert ch.check_operation(C.OPERATOR, op) is ErrorCode.NOT_ENTITLED, op
    for op in (O.PROPOSE, O.APPROVE, O.CLAIM, O.KILL_SWITCH, O.VERIFY, O.OPERATOR_RESOLVE):
        assert ch.check_operation(C.WRITER, op) is ErrorCode.NOT_ENTITLED, op
    for op in (O.APPROVE, O.PROPOSE, O.CLAIM, O.KILL_SWITCH, O.OPERATOR_RESOLVE, O.BEGIN_APPLY):
        assert ch.check_operation(C.RECOVERY_WORKER, op) is ErrorCode.NOT_ENTITLED, op
    mutations = _ALL_OPS - EXPECTED_ALLOWED[C.AUDITOR]
    assert all(ch.check_operation(C.AUDITOR, op) is ErrorCode.NOT_ENTITLED for op in mutations)
    assert ch.check_operation(C.RECOVERY_WITNESS, O.OPERATOR_RESOLVE) is None
    assert all(ch.check_operation(C.RECOVERY_WITNESS, op) is ErrorCode.NOT_ENTITLED for op in _ALL_OPS - {O.OPERATOR_RESOLVE})


def test_internal_operations_are_unreachable_for_every_external_class():
    assert set(ch.INTERNAL_OPERATIONS) == INTERNAL
    for caller in CallerClass:
        for op in INTERNAL:
            assert ch.check_operation(caller, op) is ErrorCode.NOT_ENTITLED


def test_requester_may_begin_apply_own_changes_only():
    assert ch.check_operation(C.REQUESTER, O.BEGIN_APPLY, own_change=True) is None
    assert ch.check_operation(C.REQUESTER, O.BEGIN_APPLY, own_change=False) is ErrorCode.NOT_ENTITLED
    assert ch.check_operation(C.REQUESTER, O.BEGIN_APPLY, own_change="yes") is ErrorCode.NOT_ENTITLED
    assert ch.check_operation(C.WRITER, O.BEGIN_APPLY, own_change=False) is None  # on behalf of a token


@pytest.mark.parametrize("caller, op", [("REQUESTER", O.PROPOSE), (C.REQUESTER, "PROPOSE"), (None, O.PROPOSE),
                                        (C.REQUESTER, None), (7, 7)])
def test_untyped_caller_or_operation_is_not_entitled(caller, op):
    assert ch.check_operation(caller, op) is ErrorCode.NOT_ENTITLED
    assert ch.authorize_operation(caller, op).code is ErrorCode.NOT_ENTITLED


def test_release_hold_evidence_rules():
    HC = HoldCause
    assert policy_mod.release_hold_error(HC.ANCHOR_GAP, True, False) is None
    assert policy_mod.release_hold_error(HC.RLC_UNCLEAN, True, False) is None
    assert policy_mod.release_hold_error(HC.ANCHOR_GAP, False, False) is ErrorCode.EVIDENCE_UNSIGNED
    assert policy_mod.release_hold_error(HC.RLC_UNCLEAN, False, True) is ErrorCode.EVIDENCE_UNSIGNED
    assert policy_mod.release_hold_error(HC.CALL_OWNERSHIP, True, False) is ErrorCode.COMPLETION_PROOF_MISSING
    assert policy_mod.release_hold_error(HC.CALL_OWNERSHIP, False, True) is ErrorCode.COMPLETION_PROOF_MISSING
    assert policy_mod.release_hold_error(HC.CALL_OWNERSHIP, True, True) is None
    assert policy_mod.release_hold_error(HC.FAILED_VERIFY_HALT, True, True) is ErrorCode.NOT_ENTITLED
    assert policy_mod.release_hold_error("ANCHOR_GAP", True, True) is ErrorCode.SCHEMA_INVALID


# =====================================================================================================================
# 9. reservation arithmetic and ledger invariant (section 8)
# =====================================================================================================================

D = Decimal
VALID_FROM = T0
VALID_TO = T0 + timedelta(days=30)


def grant(limit="100", reserved="0", consumed="0", currency="RUB"):
    return Grant("g1", currency, D(limit), VALID_FROM, VALID_TO, D(reserved), D(consumed))


def test_reserve_respects_limit_currency_and_window():
    g = ch.reserve(grant(), D("40"), "RUB", T0)
    assert type(g) is Grant and g.reserved == D("40") and g.consumed == D(0)
    g = ch.reserve(g, D("60"), "RUB", T0)  # exactly at the limit
    assert type(g) is Grant and g.reserved == D("100")
    assert ch.reserve(g, D("0.01"), "RUB", T0) is ErrorCode.BUDGET_EXCEEDED
    assert ch.reserve(grant(), D("100.01"), "RUB", T0) is ErrorCode.BUDGET_EXCEEDED
    assert ch.reserve(grant(consumed="70"), D("30.01"), "RUB", T0) is ErrorCode.BUDGET_EXCEEDED
    assert type(ch.reserve(grant(consumed="70"), D("30"), "RUB", T0)) is Grant
    assert ch.reserve(grant(), D("1"), "USD", T0) is ErrorCode.CURRENCY_NOT_BUDGETED
    assert ch.reserve(grant(), D("1"), "RUB", VALID_FROM - timedelta(seconds=1)) is ErrorCode.BUDGET_EXCEEDED
    assert ch.reserve(grant(), D("1"), "RUB", VALID_TO) is ErrorCode.BUDGET_EXCEEDED
    assert type(ch.reserve(grant(), D("1"), "RUB", VALID_FROM)) is Grant


@pytest.mark.parametrize("amount", [1.5, 1, "1", None, D("-1"), D("NaN"), D("Infinity")])
def test_reserve_refuses_non_decimal_negative_or_non_finite_amounts(amount):
    assert ch.reserve(grant(), amount, "RUB", T0) is ErrorCode.SCHEMA_INVALID


def test_reserve_refuses_naive_time_and_foreign_grant():
    assert ch.reserve(grant(), D("1"), "RUB", datetime(2026, 10, 12)) is ErrorCode.SCHEMA_INVALID
    assert ch.reserve("grant", D("1"), "RUB", T0) is ErrorCode.SCHEMA_INVALID


def test_consume_and_release_move_only_reserved_amounts():
    g = ch.reserve(grant(), D("40"), "RUB", T0)
    c = ch.consume(g, D("25"))
    assert (c.reserved, c.consumed) == (D("15"), D("25"))
    r = ch.release(c, D("15"))
    assert (r.reserved, r.consumed) == (D(0), D("25"))
    assert ch.consume(g, D("40.01")) is ErrorCode.SCHEMA_INVALID
    assert ch.release(g, D("40.01")) is ErrorCode.SCHEMA_INVALID
    assert ch.consume(g, 5) is ErrorCode.SCHEMA_INVALID and ch.release(g, -1) is ErrorCode.SCHEMA_INVALID
    assert g.reserved == D("40")  # inputs are immutable values


def test_grant_construction_enforces_reserved_plus_consumed_within_limit():
    for bad in ({"limit": "10", "reserved": "6", "consumed": "5"}, {"limit": "-1"}, {"reserved": "-1"}):
        with pytest.raises(ValueError):
            grant(**bad)
    with pytest.raises(ValueError):
        Grant("g", "RUB", 100, VALID_FROM, VALID_TO)  # float/int limit refused
    with pytest.raises(ValueError):
        Grant("g", "RUB", D(1), VALID_TO, VALID_FROM)
    with pytest.raises(ValueError):
        Grant("g", "RUB", D(1), datetime(2026, 1, 1), VALID_TO)


def test_post_reserves_only_the_unconsumed_part_of_the_document_amount():
    assert ch.amount_to_reserve(D("100"), D("30")) == D("70")
    assert ch.amount_to_reserve(D("100"), D("0")) == D("100")
    assert ch.amount_to_reserve(D("100"), D("100")) == D("0")
    assert ch.amount_to_reserve(D("100"), D("130")) == D("0")
    for bad in ((100, D(1)), (D(1), 1.0), (D("-1"), D(0)), (D(1), D("-1")), (D("NaN"), D(0))):
        with pytest.raises(ValueError):
            ch.amount_to_reserve(*bad)


def test_reservation_is_a_function_of_the_proven_effect_state():
    E = ch.EffectState
    assert ch.reservation_for_effect(E.PROVEN_ABSENT) is Reservation.RELEASED
    assert ch.reservation_for_effect(E.EXISTS) is Reservation.CONSUMED
    assert ch.reservation_for_effect(E.UNKNOWN) is None
    assert ch.reservation_for_effect("PROVEN_ABSENT") is None  # an operator-chosen label is not a proven state
    assert ch.reservation_for_effect(None) is None


def test_settled_reservations_are_final_and_none_never_becomes_reserved_by_settlement():
    R = Reservation
    for final in (R.CONSUMED, R.RELEASED):
        for target in R:
            assert ch.settle_reservation(final, target) is final
    assert ch.settle_reservation(R.RESERVED, R.CONSUMED) is R.CONSUMED
    assert ch.settle_reservation(R.RESERVED, R.RELEASED) is R.RELEASED
    assert ch.settle_reservation(R.NONE, R.CONSUMED) is R.NONE
    assert ch.settle_reservation(R.NONE, R.RESERVED) is R.RESERVED
    with pytest.raises(ValueError):
        ch.settle_reservation("RESERVED", R.CONSUMED)


# which engine paths consume, release or keep the reservation (section 8 / 4.1)
RESERVATION_PATHS = [
    ("T7", dispatched(), Event.CALL_SUCCESS, {}, Reservation.CONSUMED),
    ("T10", unknown(), Event.RESOLVE_FOUND, {}, Reservation.CONSUMED),
    ("T14", applied(reservation=Reservation.CONSUMED), Event.VERIFY_FAILED, {}, Reservation.CONSUMED),
    ("T16 present", triage(), Event.OPERATOR_RESOLVE, {"outcome": ResolveOutcome.PRESENT_UNATTRIBUTED},
     Reservation.CONSUMED),
    ("T5x", claimed(), Event.RELEASE_CLAIM, {}, Reservation.RELEASED),
    ("T6r", applying(), Event.PERMIT_NOT_ISSUED, {}, Reservation.RELEASED),
    ("T6c", applying(Dispatch.PERMITTED), Event.CANCEL_PERMIT, {}, Reservation.RELEASED),
    ("T8", dispatched(), Event.REFUSED_BEFORE_WRITE, {}, Reservation.RELEASED),
    ("T11", unknown(), Event.RESOLVE_ABSENT, {}, Reservation.RELEASED),
    ("T15", claimed(), Event.REVOKE, {}, Reservation.RELEASED),
    ("T16 absent", triage(), Event.OPERATOR_RESOLVE, {}, Reservation.RELEASED),
    ("T9", dispatched(), Event.CALL_UNKNOWN, {}, Reservation.RESERVED),
    ("T12", unknown(), Event.AGE_LIMIT, {}, Reservation.RESERVED),
    ("T6", claimed(), Event.BEGIN_APPLY, {}, Reservation.RESERVED),
]


@pytest.mark.parametrize("label, state, event, over, expected", RESERVATION_PATHS, ids=[p[0] for p in RESERVATION_PATHS])
def test_engine_reservation_follows_the_proven_effect_state(label, state, event, over, expected):
    assert ok(step(state, event, **over)).reservation is expected


def test_ledger_invariant_holds_after_every_path_in_a_simulated_ledger():
    """reserved + consumed on the grant equals the sum over live change states, at every step of several lifecycles."""
    amount = D("10")
    g = grant(limit="100")

    def live_sums(changes):
        reserved = sum((amount for c in changes if c.reservation is Reservation.RESERVED), D(0))
        consumed = sum((amount for c in changes if c.reservation is Reservation.CONSUMED), D(0))
        return reserved, consumed

    def apply_reservation(g, before, after):
        if before.reservation is not Reservation.RESERVED and after.reservation is Reservation.RESERVED:
            g = ch.reserve(g, amount, "RUB", T0)
        elif before.reservation is Reservation.RESERVED and after.reservation is Reservation.CONSUMED:
            g = ch.consume(g, amount)
        elif before.reservation is Reservation.RESERVED and after.reservation is Reservation.RELEASED:
            g = ch.release(g, amount)
        assert type(g) is Grant
        return g

    scripts = [
        [Event.CLAIM, Event.BEGIN_APPLY, Event.ISSUE_PERMIT, Event.MARK_DISPATCHED, Event.CALL_SUCCESS, Event.VERIFY_OK],
        [Event.CLAIM, Event.RELEASE_CLAIM, Event.CLAIM, Event.BEGIN_APPLY, Event.PERMIT_NOT_ISSUED, Event.CLAIM],
        [Event.CLAIM, Event.BEGIN_APPLY, Event.ISSUE_PERMIT, Event.CANCEL_PERMIT, Event.CLAIM],
        [Event.CLAIM, Event.BEGIN_APPLY, Event.ISSUE_PERMIT, Event.MARK_DISPATCHED, Event.CALL_UNKNOWN,
         Event.AGE_LIMIT, Event.OPERATOR_RESOLVE],
        [Event.CLAIM, Event.BEGIN_APPLY, Event.ISSUE_PERMIT, Event.MARK_DISPATCHED, Event.CALL_UNKNOWN,
         Event.RESOLVE_FOUND, Event.VERIFY_FAILED],
        [Event.CLAIM, Event.BEGIN_APPLY, Event.ISSUE_PERMIT, Event.MARK_DISPATCHED, Event.REFUSED_BEFORE_WRITE],
    ]
    for script in scripts:
        a, b = approved(), approved(change_id="c2")
        changes = [a, b]
        grants = g
        now = T0
        for event in script:
            before = changes[0]
            evidence_over = {"first_attempt_at": None, "attempts": 0} if event is Event.AGE_LIMIT else {}
            now = now + timedelta(seconds=200 if event is Event.RELEASE_CLAIM else 1)
            res = step(before, event, now=now, **evidence_over) if event is not Event.AGE_LIMIT else \
                step(before, event, now=now, attempts=5, first_attempt_at=now - timedelta(minutes=20))
            if type(res) is Refusal and event is Event.CLAIM:  # a re-claim after the approval lapsed is irrelevant here
                continue
            after = ok(res)
            grants = apply_reservation(grants, before, after)
            changes[0] = after
            reserved, consumed = live_sums(changes)
            assert ch.ledger_invariant_holds(grants, reserved, consumed), (script, event)
            assert grants.reserved + grants.consumed <= grants.limit


def test_ledger_invariant_detects_a_drift():
    g = grant(reserved="10", consumed="5")
    assert ch.ledger_invariant_holds(g, D("10"), D("5"))
    assert not ch.ledger_invariant_holds(g, D("10"), D("4"))
    assert not ch.ledger_invariant_holds(g, D("11"), D("5"))
    assert not ch.ledger_invariant_holds(g, 10, 5)
    assert not ch.ledger_invariant_holds("g", D(0), D(0))
    assert not ch.ledger_invariant_holds(g, D("-1"), D("5"))


# =====================================================================================================================
# 10. locks / lease / hold matrix (section 4.1) as data
# =====================================================================================================================

def test_lock_matrix_matches_section_4_1():
    A, KP, R, NA, HO = tr_mod.LockAction.ACQUIRE, tr_mod.LockAction.KEEP, tr_mod.LockAction.RELEASE, \
        tr_mod.LockAction.NA, tr_mod.LockAction.HANDOFF
    expected = {  # key: (TL, KL, WL, reservation)
        "T5": (A, A, A, Reservation.RESERVED), "T5_REPAIR": (HO, A, A, Reservation.RESERVED),
        "T5x": (R, R, R, Reservation.RELEASED), "T6r": (R, R, R, Reservation.RELEASED),
        "T6c": (R, R, R, Reservation.RELEASED), "T6": (KP, KP, KP, None), "T6p": (KP, KP, KP, None),
        "T7": (KP, R, R, Reservation.CONSUMED), "T8": (R, R, R, Reservation.RELEASED),
        "T9": (KP, KP, KP, None), "T10": (KP, R, R, Reservation.CONSUMED), "T12": (KP, KP, KP, None),
        "T13": (R, R, NA, Reservation.CONSUMED), "T14": (KP, R, NA, Reservation.CONSUMED),
        "T15": (R, R, R, Reservation.RELEASED), "T16_ABSENT": (R, R, R, Reservation.RELEASED),
        "T16_PRESENT": (KP, R, R, Reservation.CONSUMED),
    }
    for key, (tl, kl, wl, res) in expected.items():
        row = ch.LOCK_MATRIX[key]
        assert (row.tl, row.kl, row.wl, row.reservation) == (tl, kl, wl, res), key
    HA = tr_mod.HoldAction
    assert ch.LOCK_MATRIX["T9"].hold is HA.OPEN_CALL_OWNERSHIP
    assert ch.LOCK_MATRIX["T10"].hold is HA.RELEASE_CALL_OWNERSHIP
    assert ch.LOCK_MATRIX["T12"].hold is HA.KEEP_CALL_OWNERSHIP
    assert ch.LOCK_MATRIX["T14"].hold is HA.OPEN_FAILED_VERIFY_HALT
    assert ch.LOCK_MATRIX["T17_RETRY_OK"].hold is HA.RELEASE_FAILED_VERIFY_HALT
    for key in ("T5x", "T6r", "T6c", "T8", "T15"):
        assert ch.LOCK_MATRIX[key].repair_handback is True, key
    for key in ("T9", "T7", "T10", "T12", "T13", "T14", "T6", "T6p"):
        assert ch.LOCK_MATRIX[key].repair_handback is False, key


# =====================================================================================================================
# 11. model-based test: random legal event sequences
# =====================================================================================================================

def _terminal(r: ChangeRecord) -> bool:
    return (r.lifecycle in (Lifecycle.REJECTED, Lifecycle.EXPIRED_QUEUED, Lifecycle.DUPLICATE_PARKED)
            or r.execution in (Execution.FAILED_APPLY, Execution.ROLLBACK_REFUSED)
            or r.verification is Verification.VERIFIED or r.closed
            or r.authorization in (Authorization.VOIDED, Authorization.REVOKED, Authorization.EXPIRED))


def _signature(r: ChangeRecord):
    return (r.lifecycle, r.authorization, r.execution, r.verification, r.call_ownership, r.attribution, r.dispatch,
            r.token, r.reservation, r.target_lock, r.key_lock, r.lease, r.closed, r.repair is not None,
            r.effect_known)


def _perturb(rng: random.Random, ev):
    """Flip some boolean evidence fields to the failing value and sometimes change the kill reading."""
    over = {}
    for f in dataclasses.fields(ev):
        value = getattr(ev, f.name)
        if type(value) is bool and rng.random() < 0.08:
            over[f.name] = not value
    if rng.random() < 0.1 and "kill" not in over:
        over["kill"] = rng.choice([kill(K.STOP_ADMIT), kill(K.STOP_EFFECTS), kill(K.REVOKE), UNREADABLE])
    return replace(ev, **over)


def _random_evidence(rng: random.Random, event: Event, r: ChangeRecord, now: datetime):
    over = {}
    if event is Event.RELEASE_CLAIM:
        over["reason"] = rng.choice(list(ReleaseReason))
        over["kill"] = rng.choice([SWITCH_OFF, kill(K.STOP_ADMIT), kill(K.REVOKE)])
    elif event is Event.REVOKE:
        over["cause"] = rng.choice(list(RevokeCause))
    elif event is Event.OPERATOR_RESOLVE:
        over.update(outcome=rng.choice(list(ResolveOutcome)), effect_identity_match=rng.random() < 0.5,
                    exclusivity_proven=rng.random() < 0.5,
                    proof_class=rng.choice([ProofClass.WRITER_COMPLETION, ProofClass.SESSION_END_OBSERVED,
                                            ProofClass.NONE, ProofClass.FORCED_TERMINATION]))
    elif event in (Event.RESOLVE_FOUND, Event.RESOLVE_ABSENT, Event.AGE_LIMIT):
        over.update(effect_present=rng.random() < 0.5, effect_identity_match=rng.random() < 0.5,
                    exclusivity_proven=rng.random() < 0.5, observation_complete=rng.random() < 0.8,
                    signed=rng.random() < 0.9, attempts=rng.choice([0, 4, 5]),
                    first_attempt_at=now - timedelta(minutes=rng.choice([1, 14, 16])),
                    proof_class=rng.choice([ProofClass.WRITER_COMPLETION, ProofClass.NONE,
                                            ProofClass.FORCED_TERMINATION]))
    elif event in (Event.CALL_SUCCESS, Event.REFUSED_BEFORE_WRITE, Event.CALL_UNKNOWN):
        over.update(signed=rng.random() < 0.8, call_id_matches=rng.random() < 0.9,
                    result_returned=rng.random() < 0.5,
                    stage=rng.choice([None, FailureStage.PRE_WRITE, FailureStage.WRITE_STARTED,
                                      FailureStage.UNCLASSIFIED]),
                    no_effect_proof=rng.random() < 0.7,
                    refusal_code=rng.choice([None, ErrorCode.STALE_VERSION, ErrorCode.LOCK_BUSY,
                                             ErrorCode.ROLLBACK_REFUSED, ErrorCode.WRITE_REFUSED,
                                             ErrorCode.SCHEMA_INVALID]))
    elif event in (Event.VERIFY_OK, Event.VERIFY_FAILED, Event.RETRY_VERIFY):
        over.update(matches=rng.random() < 0.5, effect_known=rng.choice(list(EffectKnown) + [None]))
        if rng.random() < 0.2:
            over["signed_kinds"] = h.VERIFY_KINDS - {rng.choice(sorted(h.VERIFY_KINDS))}
    elif event is Event.VALIDATE:
        over["key_state"] = rng.choice([h.BusinessKeyState.FREE] * 4 + list(h.BusinessKeyState))
        over["budget"] = rng.choice([BudgetCheck.OK] * 6 + list(BudgetCheck))
    elif event is Event.APPROVE:
        over["nonce"] = rng.choice(list(NonceState))
        over["approval_type"] = rng.choice(list(ApprovalType))
    elif event is Event.CLOSE_FAILED_VERIFY:
        over["operator_person_id"] = rng.choice([OPERATOR, REQUESTER])
    return _perturb(rng, good(event, r, now, **over))


def _guided_events(r: ChangeRecord):
    return [row.event for row in tr_mod.TRANSITION_TABLE
            if row.event is not Event.PROPOSE and all(getattr(r, d) in a for d, a in row.requires.items())]


def _start(rng: random.Random, flavor: str):
    if flavor == "create":
        p = h.proposal()
    elif flavor == "post":
        p = h.proposal(raw_post("POST", parent_change_id="parent9", target_ref="doc9"))
    elif flavor == "unpost":
        p = h.proposal(raw_post("UNPOST", parent_change_id="parent9", target_ref="doc9"))
    else:  # repair of parent1 under section 4.2
        p = h.proposal(raw_post("UNPOST"), change_id=REPAIR_ID)
    return ok(apply_transition(None, Event.PROPOSE, good(Event.PROPOSE, None, proposal=p)), "T1")


def _check_step(before, after, event, ev, res, flags):
    proof = getattr(ev, "proof_class", ProofClass.NONE) in (ProofClass.WRITER_COMPLETION,
                                                          ProofClass.SESSION_END_OBSERVED)
    assert ch.forbidden_transition(before, after, event, proof) is None
    # execution outcomes are only reachable through their contract transitions
    if after.execution is not before.execution:
        if after.execution is Execution.FAILED_APPLY:
            assert event in (Event.REFUSED_BEFORE_WRITE, Event.RESOLVE_ABSENT, Event.OPERATOR_RESOLVE), event
            if before.execution is Execution.APPLYING:
                assert event is Event.REFUSED_BEFORE_WRITE and ev.stage is FailureStage.PRE_WRITE \
                    and ev.no_effect_proof is True
            else:
                assert proof
        if after.execution is Execution.APPLIED:
            assert event in (Event.CALL_SUCCESS, Event.RESOLVE_FOUND, Event.OPERATOR_RESOLVE), event
            if before.execution is not Execution.APPLYING:
                assert proof
        if after.execution is Execution.APPLY_UNKNOWN:
            assert event is Event.CALL_UNKNOWN and before.dispatch is Dispatch.DISPATCHED
    if after.verification is Verification.VERIFIED and before.verification is not Verification.VERIFIED:
        assert event in (Event.VERIFY_OK, Event.RETRY_VERIFY) and before.execution is Execution.APPLIED
        assert ev.bound is True and h.VERIFY_KINDS <= ev.signed_kinds and ev.matches is True
    if event is Event.ISSUE_PERMIT:
        flags["permitted"] = True
    if event is Event.MARK_DISPATCHED:
        assert flags["permitted"]
        flags["dispatched"] = True
    if event is Event.CLAIM:
        flags["claims"] += 1
    # state invariants
    r = after
    if r.execution in (Execution.APPLY_UNKNOWN, Execution.APPLIED, Execution.FAILED_APPLY,
                       Execution.TRIAGE_REQUIRED, Execution.ROLLBACK_REFUSED):
        assert flags["dispatched"]
    if r.dispatch is Dispatch.DISPATCHED:
        assert flags["permitted"]
    assert r.claim_generation == flags["claims"]
    if r.execution in (Execution.APPLY_UNKNOWN, Execution.TRIAGE_REQUIRED):
        assert r.call_ownership is CallOwnership.POSSIBLY_EXECUTING
        assert (r.target_lock, r.key_lock, r.lease, r.reservation) == (True, True, True, Reservation.RESERVED)
    if r.execution is Execution.FAILED_APPLY:
        assert r.call_ownership is not CallOwnership.POSSIBLY_EXECUTING
    if r.execution is Execution.APPLIED:
        assert r.call_ownership is CallOwnership.PROVEN_FINISHED and r.reservation is Reservation.CONSUMED
        assert r.attribution in (Attribution.PROVEN, Attribution.UNPROVEN_OPERATOR_ATTESTED)
        assert (r.key_lock, r.lease) == (False, False)
    if r.execution in (Execution.FAILED_APPLY, Execution.ROLLBACK_REFUSED):
        assert r.reservation is Reservation.RELEASED and not (r.target_lock or r.key_lock or r.lease)
    if r.execution is Execution.APPLYING:
        assert r.reservation is Reservation.RESERVED and r.lease and r.target_lock and r.key_lock
        assert r.authorization is Authorization.CLAIMED and r.token is TokenState.CONSUMED
    if r.authorization is Authorization.CLAIMED and r.execution is Execution.NOT_STARTED:
        assert r.reservation is Reservation.RESERVED and r.token is TokenState.ISSUED and r.lease
    if r.execution is Execution.NOT_STARTED and r.authorization is not Authorization.CLAIMED:
        assert r.reservation is not Reservation.RESERVED and not (r.target_lock or r.key_lock or r.lease)
    if r.attribution is not Attribution.NOT_APPLICABLE:
        assert r.execution is Execution.APPLIED
    if r.verification is Verification.VERIFIED:
        assert r.execution is Execution.APPLIED and not (r.target_lock or r.key_lock or r.lease)
    if r.verification is Verification.FAILED_VERIFY:
        assert r.execution is Execution.APPLIED and r.effect_known is not None
    if r.repair is not None:
        assert r.repair.claim_generation == r.claim_generation and r.repair_for == "parent1"
        assert r.authorization is Authorization.CLAIMED or r.execution is not Execution.NOT_STARTED
    if {EffectKind.HAND_LOCK_BACK_TO_PARENT, EffectKind.INVALIDATE_REPAIR_AUTH} & set(res.effects):
        assert {EffectKind.HAND_LOCK_BACK_TO_PARENT, EffectKind.INVALIDATE_REPAIR_AUTH} <= set(res.effects)
        assert r.repair is None and not r.target_lock and r.reservation is Reservation.RELEASED
        assert r.dispatch is not Dispatch.DISPATCHED or r.execution is Execution.NOT_STARTED or \
            r.execution in (Execution.FAILED_APPLY, Execution.ROLLBACK_REFUSED)
    if EffectKind.OPEN_HOLD_CALL_OWNERSHIP in res.effects:
        assert r.call_ownership is CallOwnership.POSSIBLY_EXECUTING
    if EffectKind.RELEASE_HOLD_CALL_OWNERSHIP in res.effects:
        assert r.call_ownership is CallOwnership.PROVEN_FINISHED and proof


EXIT_VARIANTS = {
    Event.RELEASE_CLAIM: [{"reason": rsn, "kill": k} for rsn in ReleaseReason
                          for k in (SWITCH_OFF, kill(K.STOP_ADMIT))],
    Event.REVOKE: [{"cause": c} for c in RevokeCause],
    Event.OPERATOR_RESOLVE: [{"outcome": o, "effect_identity_match": True, "exclusivity_proven": True}
                             for o in ResolveOutcome],
    Event.PERMIT_NOT_ISSUED: [{}, {"checkpoint_unavailable": False, "hold_open": True}],
    Event.VALIDATE: [{}, {"key_state": h.BusinessKeyState.COLLISION}],
}


def _has_exit(r: ChangeRecord, now: datetime) -> list[Event]:
    exits = []
    for event in Event:
        if event is Event.PROPOSE:
            continue
        for late in (now, now + timedelta(hours=3)):
            for variant in EXIT_VARIANTS.get(event, [{}]):
                res = apply_transition(r, event, replace(good(event, r, late), **{
                    k: v for k, v in variant.items()}))
                if type(res) is Applied and res.record != r:
                    exits.append(event)
                    break
            else:
                continue
            break
    return exits


EARLY_EXITS = (Event.REJECT, Event.EXPIRE, Event.REVOKE, Event.RELEASE_CLAIM, Event.PERMIT_NOT_ISSUED,
               Event.CANCEL_PERMIT, Event.CLOSE_FAILED_VERIFY)
FLAVORS = ("create", "post", "unpost", "repair")


def test_model_based_random_sequences_never_reach_a_forbidden_state():
    rng = random.Random(20261012)
    reached: set[str] = set()
    states: dict[tuple, tuple[ChangeRecord, datetime]] = {}
    terminal_seen = 0
    for walk in range(1500):
        flavor = FLAVORS[walk % len(FLAVORS)]
        record = _start(rng, flavor)
        now = T0
        flags = {"permitted": False, "dispatched": False, "claims": 0}
        for _ in range(45):
            now = now + timedelta(seconds=rng.choice([1, 5, 20, 70, 130]))
            guided = _guided_events(record)
            forward = [e for e in guided if e not in EARLY_EXITS]
            if forward and rng.random() < 0.8:
                event = rng.choice(forward)
            elif guided and rng.random() < 0.6:
                event = rng.choice(guided)
            else:
                event = rng.choice([e for e in Event if e is not Event.PROPOSE])
            ev = _random_evidence(rng, event, record, now)
            res = apply_transition(record, event, ev)
            if type(res) is Refusal:
                assert res.code in ErrorCode and len(res.transition) <= 16
                if _terminal(record):
                    assert True  # terminal absorbs: nothing changed
                continue
            assert _terminal(record) is False, (event, record)  # a terminal state never transitions
            after = res.record
            assert after is not None
            reached.add(res.transition)
            _check_step(record, after, event, ev, res, flags)
            record = after
            sig = _signature(record)
            if sig not in states:
                states[sig] = (record, now)
            if _terminal(record):
                terminal_seen += 1
                break
    # the walks really explored every contract transition (otherwise the invariants proved little)
    reached.add("T1")
    assert {"T1"} | {f"T{i}" for i in (2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17)} \
        | {"T5x", "T6", "T6p", "T6r", "T6c"} <= reached, sorted(reached)
    assert terminal_seen > 100 and len(states) > 40
    # every non-terminal state has an exit event; terminal states have none
    for sig, (state, when) in states.items():
        exits = _has_exit(state, when)
        if _terminal(state):
            assert exits == [], (sig, exits)
        else:
            assert exits, f"no exit event from non-terminal state {sig}"
