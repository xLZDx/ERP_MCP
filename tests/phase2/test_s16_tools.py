"""REQ-010..013: serialized MCP tools expose only the approved safe contract."""
import asyncio
from collections.abc import Mapping
from datetime import timedelta
from uuid import UUID

from business_ai_gateway.phase2.change.errors import ErrorCode
from erp_mcp_s16.tools import S16_TOOL_MANIFEST, register_s16_tools
from erp_mcp_s16.fakes import InMemoryChangeStore
from business_ai_gateway.phase2.change.types import Verification
from tests.phase2.s16_helpers import NOW, approve, build_env, raw_create
from erp_mcp_s15.verifier import Finding, VerificationResult, VerificationStatus
import pytest


class Server:
    def __init__(self):
        self.handlers = {}

    def register_tool(self, name, handler, schema, annotations):
        self.handlers[name] = (handler, schema, annotations)


def test_tool_list_is_exactly_five_and_annotations_are_not_read_only():
    env, server = build_env(), Server()
    register_s16_tools(server, env.change_service, lambda context: context)
    assert tuple(server.handlers) == ("propose", "status", "apply", "verify", "rollback_propose")
    assert "approve" not in server.handlers
    assert all(entry[2].get("readOnlyHint") is False for entry in server.handlers.values())


def test_real_parser_and_service_issue_proposal_and_unknown_approve_is_refused():
    env, server = build_env(), Server()
    register_s16_tools(server, env.change_service, lambda context: context)
    response = asyncio.run(server.handlers["propose"][0]({"request": raw_create()}, env.requester))
    assert response["isError"] is False
    assert len(response["result"]["preview_digest"]) == 64
    assert env.apply_port.calls == 0
    direct = asyncio.run(server.handlers["propose"][0]({"request": raw_create(), "approved": True}, env.requester))
    assert direct["isError"] is True
    assert env.apply_port.calls == 0


def test_unknown_tool_and_unexpected_service_failure_return_safe_codes_only():
    env, server = build_env(), Server()
    register_s16_tools(server, env.change_service, lambda context: context)
    # The registered surface contains no approval operation or alias.
    assert "approve" not in server.handlers
    secret = "internal-secret-detail"
    env.change_service.propose = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(secret))
    response = asyncio.run(server.handlers["propose"][0]({"request": raw_create()}, env.requester))
    rendered = repr(response)
    assert response["isError"] is True
    assert ErrorCode.AUDIT_UNAVAILABLE.value in rendered
    assert secret not in rendered


@pytest.mark.parametrize("status", list(VerificationStatus))
def test_verify_tool_passes_s15_result_through_without_changing_authorization_state(status):
    env, server = build_env(), Server()
    env.verify_port.result = VerificationResult(status, "oracle-fixture", "MACHINE_VERIFIED")
    register_s16_tools(server, env.change_service, lambda context: context)
    snap, _ = approve(env)
    applied = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert applied.value is not None
    before = env.store.get(snap.change_id).s12_record
    response = asyncio.run(server.handlers["verify"][0]({
        "change_id": str(snap.change_id), "document_ref": "fake-document",
        "expected": {"values": {}, "document_day": "", "change_id": "caller-forged",
                     "manifest_hash": "caller-forged", "includes_vat": False},
        "shape": {"operation": "POST", "document_kind": "OTHER", "line_count": 99},
    }, env.requester))
    assert response["isError"] is False
    assert response["result"]["status"] == status.value
    assert env.store.get(UUID(str(snap.change_id))).s12_record == before


def test_verify_tool_preserves_s15_findings_and_unverified_paths():
    env, server = build_env(), Server()
    env.verify_port.result = VerificationResult(
        VerificationStatus.INCONCLUSIVE, "oracle-fixture", "MACHINE_VERIFIED",
        findings=(Finding("receipt.amount", "number", "READ_ERROR", "TimeoutError"),),
        unverified_paths=("receipt.vat_amount",), typing_checked=True,
    )
    register_s16_tools(server, env.change_service, lambda context: context)
    snap, _ = approve(env)
    applied = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert applied.value is not None

    response = asyncio.run(server.handlers["verify"][0]({
        "change_id": str(snap.change_id), "document_ref": "fake-document",
        "expected": {"values": {}, "document_day": "", "change_id": "caller-forged",
                     "manifest_hash": "caller-forged", "includes_vat": False},
        "shape": {"operation": "POST", "document_kind": "OTHER", "line_count": 99},
    }, env.requester))

    assert response["isError"] is False
    assert response["result"] == {
        "status": "INCONCLUSIVE", "oracle_version": "oracle-fixture", "label": "MACHINE_VERIFIED",
        "findings": [{"path": "receipt.amount", "field_class": "number",
                      "code": "READ_ERROR", "detail": "TimeoutError"}],
        "unverified_paths": ["receipt.vat_amount"], "typing_checked": True,
    }


def test_rollback_propose_requires_verified_post_and_creates_distinct_unpost_preview():
    from dataclasses import replace
    from business_ai_gateway.phase2.change.errors import ErrorCode
    from business_ai_gateway.phase2.change import Event, Verification, apply_transition
    from tests.phase2 import _change_helpers as h

    env = build_env()
    target = env.targets.current(env.requester.scope)
    env.targets.put(replace(target, parent_verified=True))
    post_request = {"kind": "POST", "request_id": "post-request", "parent_change_id": "prior-change",
                    "target_ref": "document-1", "target_version": "v1", "reason": "approved post"}
    post = env.change_service.propose(env.requester, post_request, now=NOW)
    assert post.error is None, post.error
    # Seed an independently verified ledger row through the store's public insert and
    # the core's explicit issuance boundary. The transition itself must be valid S12.
    receipt = env.store.get(post.value.change_id)
    applied_parent = h.applied(
        change_id=str(post.value.change_id), kind=post.value.proposal.kind,
        scope=h.SCOPE, requester_person_id=post.value.proposal.requester_person_id,
        parent_change_id=post.value.proposal.parent_change_id,
        target_ref=post.value.proposal.target_ref,
    )
    verified = apply_transition(applied_parent, Event.VERIFY_OK, h.good(Event.VERIFY_OK, applied_parent))
    assert not hasattr(verified, "code")
    seeded_store = InMemoryChangeStore()
    seeded_receipt = replace(receipt, s12_record=verified.record, status="VERIFIED")
    seeded_store.insert_proposal(seeded_receipt)
    env = build_env(store=seeded_store)
    env.targets.put(replace(env.targets.current(env.requester.scope), parent_verified=True))
    assert env.core.anchor_issuance(seeded_receipt) is None
    before_calls = env.apply_port.calls
    rollback = env.change_service.rollback_propose(env.requester, post.value.change_id, now=NOW)
    assert rollback.error is None, rollback.error
    assert rollback.value.change_id != post.value.change_id
    assert rollback.value.proposal.kind.value == "UNPOST"
    assert rollback.value.proposal.parent_change_id == str(post.value.change_id)
    assert env.store.get(rollback.value.change_id).approval is None
    assert env.apply_port.calls == before_calls

    draft = env.change_service.propose(env.requester, raw_create(), now=NOW)
    assert draft.error is None
    refused = env.change_service.rollback_propose(env.requester, draft.value.change_id, now=NOW)
    assert refused.error is ErrorCode.ROLLBACK_REFUSED
    unpost_refused = env.change_service.rollback_propose(env.requester, rollback.value.change_id, now=NOW)
    assert unpost_refused.error is ErrorCode.ROLLBACK_REFUSED


def test_post_proposal_without_verified_current_parent_is_refused():
    from dataclasses import replace
    from business_ai_gateway.phase2.change.errors import ErrorCode

    env = build_env()
    env.targets.put(replace(env.targets.current(env.requester.scope), parent_verified=False))
    request = {"kind": "POST", "request_id": "post-request", "parent_change_id": "prior-change",
               "target_ref": "document-1", "target_version": "v1", "reason": "post"}
    result = env.change_service.propose(env.requester, request, now=NOW)
    assert result.error is ErrorCode.PARENT_NOT_VERIFIED


def test_manifest_has_no_hidden_approve_alias_or_caller_claim_fields():
    names = [spec.name for spec in S16_TOOL_MANIFEST]
    assert names == ["propose", "status", "apply", "verify", "rollback_propose"]
    assert all("approve" not in spec.name for spec in S16_TOOL_MANIFEST)
    assert set(S16_TOOL_MANIFEST[0].input_schema["properties"]) == {"request"}


def test_fastmcp_lists_exact_manifest_schemas_without_exposing_transport_context():
    from mcp.server.fastmcp import FastMCP

    def plain(value):
        if isinstance(value, Mapping):
            return {key: plain(child) for key, child in value.items()}
        if isinstance(value, (tuple, list)):
            return [plain(child) for child in value]
        return value

    env, server = build_env(), FastMCP("s16-contract")
    register_s16_tools(server, env.change_service, lambda context: context)
    listed = asyncio.run(server.list_tools())

    assert [tool.name for tool in listed] == [spec.name for spec in S16_TOOL_MANIFEST]
    assert [tool.inputSchema for tool in listed] == [plain(spec.input_schema)
                                                     for spec in S16_TOOL_MANIFEST]
    assert all("context" not in tool.inputSchema.get("properties", {}) for tool in listed)


def test_escape_expansion_argument_budget_refuses_before_calling_the_service():
    env, server = build_env(), Server()
    service_calls = []
    env.change_service.propose = lambda *args, **kwargs: service_calls.append(args)
    register_s16_tools(server, env.change_service, lambda context: context)
    request = {f"reason_{index}": "\n" * 8192 for index in range(4)}
    arguments = {"request": request}
    assert sum(len(value.encode("utf-8")) for value in request.values()) < 64 * 1024
    assert len(repr(arguments).encode("utf-8")) > 64 * 1024

    response = asyncio.run(server.handlers["propose"][0](arguments, env.requester))

    assert response["isError"] is True
    assert response["error"]["code"] == ErrorCode.SCHEMA_INVALID.value
    assert service_calls == []

