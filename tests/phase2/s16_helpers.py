"""Deterministic S16 functional fixtures. No listener, database, or writer is created."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from business_ai_gateway.phase2.change.errors import ErrorCode
from business_ai_gateway.phase2.change.killswitch import SWITCH_OFF
from business_ai_gateway.phase2.change.transitions import BeginApplyEvidence
from business_ai_gateway.phase2.change.types import CallerClass
from erp_mcp_s16.contracts import (
    AuthenticatedPrincipal,
    PrincipalRecord,
    PrincipalRole,
    TargetRecord,
    TargetScope,
    TargetVersion,
    TokenClass,
)
from erp_mcp_s16.core import S16Core
from erp_mcp_s16.fakes import (
    FakeApplyPort,
    FakeBeginApplyEvidencePort,
    FakeClock,
    FakeKillSwitch,
    FakeNonceSource,
    FakeProposalPort,
    FakeVerifyPort,
    InMemoryChangeStore,
)
from erp_mcp_s16.registries import InMemoryPrincipalRegistry, InMemoryTargetRegistry, TestIdP
from erp_mcp_s16.services import ApprovalService, ChangeService

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
SCOPE = TargetScope("tenant-1", "company-1", "org-1", "base-1", "TEST")
ORIGIN = "https://127.0.0.1:8443"


def requester(*, scope=SCOPE, principal_id="requester", person_id="person-requester",
              token_class=TokenClass.CHAT_WRITE, roles=frozenset({PrincipalRole.REQUESTER}),
              epoch=1, expires_at=NOW + timedelta(hours=1)):
    return AuthenticatedPrincipal(principal_id, person_id, roles, token_class, epoch,
                                  scope, None, expires_at)


def approver(*, scope=SCOPE, principal_id="approver", person_id="person-approver",
             token_class=TokenClass.APPROVER_SESSION, epoch=1,
             expires_at=NOW + timedelta(minutes=15)):
    return AuthenticatedPrincipal(principal_id, person_id, frozenset({PrincipalRole.APPROVER}),
                                  token_class, epoch, scope, None, expires_at, True)


@dataclass
class S16Environment:
    store: InMemoryChangeStore
    principals: InMemoryPrincipalRegistry
    targets: InMemoryTargetRegistry
    apply_port: FakeApplyPort
    verify_port: FakeVerifyPort
    kill_switch: FakeKillSwitch
    clock: FakeClock
    nonce_source: FakeNonceSource
    core: S16Core
    change_service: ChangeService
    approval_service: ApprovalService
    idp: TestIdP
    requester: AuthenticatedPrincipal
    approver: AuthenticatedPrincipal
    session: object


def positive_begin_apply_evidence():
    """Explicit test-only positive observation required for successful fake apply journeys."""
    return BeginApplyEvidence(
        now=NOW, kill=SWITCH_OFF, generation=1, caller=CallerClass.REQUESTER,
        own_change=True, epoch_deps_equal_claim_epoch=True, holds=(),
        version_equals_approved=True, fingerprint_authenticated=True,
        period_observed_open=True, state_digest_equal=True,
        writer_lock_held=True, ownership_row_committed=True,
    )


def build_env(*, permissive=False, switch=None, positive_begin_apply=True,
              begin_apply_evidence=None, store=None) -> S16Environment:
    clock = FakeClock(NOW)
    nonce_source = FakeNonceSource("functional-s16")
    req = requester()
    app = approver()
    records = (
        PrincipalRecord(req.principal_id, req.person_id, req.roles, req.epoch,
                        display_label="Requester One"),
        PrincipalRecord(app.principal_id, app.person_id, app.roles, app.epoch,
                        display_label="Approver One"),
    )
    principals = InMemoryPrincipalRegistry(records)
    target = TargetRecord(
        SCOPE, TargetVersion("v1", NOW), amount_confirmation_threshold="1000000",
        business_key_free=True, business_state_digest="a" * 64,
        qualified_currencies=frozenset({"RUB"}),
        in_scope_refs=frozenset({"org-1", "cp-1", "ct-1", "it-1", "document-1", "prior-change"}),
    )
    targets = InMemoryTargetRegistry((target,))
    store = store or InMemoryChangeStore(permissive_decisions=permissive)
    apply_port = FakeApplyPort()
    verify_port = FakeVerifyPort()
    kill_switch = FakeKillSwitch(switch) if switch is not None else FakeKillSwitch()
    evidence_port = begin_apply_evidence
    if evidence_port is None and positive_begin_apply:
        evidence_port = FakeBeginApplyEvidencePort(positive_begin_apply_evidence())
    core = S16Core(store=store, principals=principals, targets=targets,
                   kill_switch=kill_switch, apply_port=apply_port, verify_port=verify_port,
                   begin_apply_evidence=evidence_port, clock=clock)
    proposal_port = FakeProposalPort(targets, principals)
    change_service = ChangeService(core, store, proposal_port, nonce_source, clock)
    approval_service = ApprovalService(core, store, nonce_source, clock, origin=ORIGIN)
    idp = TestIdP(principals, nonce_source=nonce_source)
    session = idp.issue(app, NOW)
    assert session is not None
    return S16Environment(store, principals, targets, apply_port, verify_port, kill_switch,
                          clock, nonce_source, core, change_service, approval_service,
                          idp, req, session.principal, session)


def raw_create(**overrides):
    payload = {
        "organization_ref": "org-1", "counterparty_ref": "cp-1", "contract_ref": "ct-1",
        "supplier_document_number": "N-1", "supplier_document_date": "2026-10-01", "currency": "RUB",
        "lines": [{"item_ref": "it-1", "quantity": "2", "price": "10.50", "vat_rate_code": "VAT20",
                   "amount": "21.00", "vat_amount": "3.50"}],
        "comment": "functional fixture",
    }
    request = {"kind": "CREATE_DRAFT", "request_id": "s16-functional-1", "payload": payload,
               "reason": "functional acceptance fixture"}
    request.update(overrides)
    return request


def propose(env: S16Environment, **request_overrides):
    result = env.change_service.propose(env.requester, raw_create(**request_overrides), now=NOW)
    assert result.error is None, result.error
    return result.value


def approve(env: S16Environment, snapshot=None, *, confirmation_text=""):
    snapshot = snapshot or propose(env)
    page = env.approval_service.open_preview(env.approver, env.session, snapshot.change_id, now=NOW)
    assert page.error is None, page.error
    result = env.approval_service.submit_decision(
        env.approver, env.session, page.value.decision_ref, "APPROVE",
        confirmation_text=confirmation_text, origin=ORIGIN, referer=ORIGIN + "/approval/",
        now=NOW + timedelta(seconds=1))
    assert result.error is None, result.error
    return snapshot, page.value
