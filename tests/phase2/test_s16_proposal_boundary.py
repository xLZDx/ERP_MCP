"""REQ-007/008: ChangeService re-parses and binds every ProposalPort result before storage."""
from dataclasses import replace
from datetime import timedelta

import pytest

from business_ai_gateway.phase2.change.errors import ErrorCode
from business_ai_gateway.phase2.change.types import Scope
from erp_mcp_s16.contracts import TokenClass
from erp_mcp_s16.fakes import InMemoryChangeStore
from tests.phase2.s16_helpers import NOW, build_env, raw_create


class CountingStore(InMemoryChangeStore):
    def __init__(self):
        super().__init__()
        self.insert_calls = 0

    def insert_proposal(self, receipt):
        self.insert_calls += 1
        return super().insert_proposal(receipt)


class MutatingProposalPort:
    def __init__(self, inner, mode):
        self.inner, self.mode = inner, mode

    def build(self, requester, raw_request, *, now, expires_at, preview_digest, change_id):
        result = self.inner.build(requester, raw_request, now=now, expires_at=expires_at,
                                  preview_digest=preview_digest, change_id=change_id)
        if type(result) is ErrorCode:
            return result
        proposal, target = result
        if self.mode == "foreign_scope":
            proposal = replace(proposal, scope=Scope("foreign-tenant", "foreign-company", "org-1", "foreign-base"))
        elif self.mode == "foreign_person":
            proposal = replace(proposal, requester_person_id="person-someone-else")
        elif self.mode == "stale_created":
            proposal = replace(proposal, created_at=now - timedelta(seconds=1))
        elif self.mode == "expired":
            proposal = replace(proposal, created_at=now - timedelta(minutes=5),
                               expires_at=now - timedelta(microseconds=1))
        elif self.mode == "foreign_principal":
            proposal = replace(proposal, requester_principal="someone-else")
        elif self.mode == "wrong_change_id":
            proposal = replace(proposal, change_id="different-change-id")
        elif self.mode == "wrong_preview_digest":
            proposal = replace(proposal, preview_digest="f" * 64)
        elif self.mode == "wrong_payload_digest":
            object.__setattr__(proposal, "payload_digest", "f" * 64)
        return proposal, target

    def rollback(self, requester, receipt, *, now, expires_at, preview_digest, change_id):
        return self.inner.rollback(requester, receipt, now=now, expires_at=expires_at,
                                   preview_digest=preview_digest, change_id=change_id)


@pytest.mark.parametrize("mode", [
    "foreign_scope", "foreign_person", "stale_created", "expired", "foreign_principal",
    "wrong_change_id", "wrong_preview_digest", "wrong_payload_digest",
])
def test_malicious_proposal_port_values_are_rejected_before_store_insert(mode):
    store = CountingStore()
    env = build_env(store=store)
    env.change_service.proposal_port = MutatingProposalPort(env.change_service.proposal_port, mode)
    result = env.change_service.propose(env.requester, raw_create(), now=NOW)
    assert result.error is ErrorCode.DIGEST_MISMATCH
    assert store.insert_calls == 0
    assert not store._receipts


def test_wrong_token_class_is_refused_before_proposal_port_or_store():
    store = CountingStore()
    env = build_env(store=store)
    wrong = replace(env.requester, token_class=TokenClass.READ_ONLY)
    result = env.change_service.propose(wrong, raw_create(), now=NOW)
    assert result.error is ErrorCode.NOT_ENTITLED
    assert store.insert_calls == 0
    assert not store._receipts


def test_foreign_request_scope_is_refused_before_proposal_port_or_store():
    store = CountingStore()
    env = build_env(store=store)
    foreign_scope = replace(env.requester.scope, tenant="foreign-tenant")
    result = env.change_service.propose(replace(env.requester, scope=foreign_scope), raw_create(), now=NOW)
    assert result.error in {ErrorCode.TARGET_REJECTED, ErrorCode.SCOPE_MISMATCH}
    assert store.insert_calls == 0
    assert not store._receipts
