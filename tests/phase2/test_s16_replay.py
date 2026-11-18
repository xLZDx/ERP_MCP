"""REQ-013 / V2-S16-05: replay labeled client-shaped fixtures through the serialized boundary."""
from __future__ import annotations

import asyncio
import re
from uuid import UUID

from starlette.testclient import TestClient

from erp_mcp_s16.approval_page import create_approval_app
from erp_mcp_s16.fakes import FakeIdSource, FakeProposalPort
from erp_mcp_s16.services import ChangeService
from erp_mcp_s16.tools import register_s16_tools
from erp_mcp_s15.verifier import VerificationResult, VerificationStatus
from tests.phase2.s16_helpers import NOW, ORIGIN, build_env, raw_create
from tests.phase2.test_s16_tools import Server


class _SessionAuth:
    def __init__(self, session):
        self.session = session

    def authenticate(self, _scope, headers):
        return self.session if headers.get("x-test-session") == "approver-session" else None


def _invoke(server, name, arguments, principal):
    return asyncio.run(server.handlers[name][0](arguments, principal))


def _tool_verification(change_id):
    return {
        "change_id": str(change_id),
        "document_ref": "fake-document",
        "expected": {
            "values": {}, "document_day": "", "change_id": "caller-value",
            "manifest_hash": "caller-value", "includes_vat": False,
        },
        "shape": {"operation": "CREATE_DRAFT", "document_kind": "RECEIPT", "line_count": 1},
    }


def test_labeled_client_shape_transcripts_cover_the_entire_registered_tool_surface():
    """Inputs are labeled hand-authored shapes; replay proves registry contract only."""
    env, server = build_env(), Server()
    register_s16_tools(server, env.change_service, lambda context: context)

    assert tuple(server.handlers) == ("propose", "status", "apply", "verify", "rollback_propose")
    chatgpt_transcript = {
        "provenance": "hand-authored-chatgpt-shape-fixture",
        "messages": [{"role": "assistant", "content": "Create a draft receipt."}],
        "calls": [
            {"tool": "list", "arguments": {}},
            {"tool": "propose", "arguments": {"request": raw_create(
                request_id="s16-chatgpt-transcript")}},
        ],
    }
    assert chatgpt_transcript["provenance"].startswith("hand-authored-")
    assert chatgpt_transcript["calls"][0]["tool"] == "list"
    listed = [name for name in server.handlers]
    assert listed == ["propose", "status", "apply", "verify", "rollback_propose"]

    proposal = _invoke(server, "propose", chatgpt_transcript["calls"][1]["arguments"], env.requester)
    assert proposal["isError"] is False
    change_id = proposal["result"]["change_id"]
    status = _invoke(server, "status", {"change_id": change_id}, env.requester)
    assert status["isError"] is False
    assert status["result"]["change_id"] == change_id

    claude_transcript = {
        "provenance": "hand-authored-claude-shape-fixture",
        "messages": [{"role": "assistant", "content": "Check and verify the proposal."}],
        "calls": [
            {"tool": "status", "arguments": {"change_id": change_id}},
            {"tool": "apply", "arguments": {"change_id": change_id}},
            {"tool": "verify", "arguments": _tool_verification(change_id)},
            {"tool": "rollback_propose", "arguments": {"change_id": change_id}},
            {"tool": "approve", "arguments": {"change_id": change_id}},
        ],
    }
    assert claude_transcript["provenance"].startswith("hand-authored-")
    assert _invoke(server, "status", claude_transcript["calls"][0]["arguments"],
                   env.requester)["isError"] is False
    apply_before_approval = _invoke(server, "apply", claude_transcript["calls"][1]["arguments"],
                                    env.requester)
    verification_before_apply = _invoke(server, "verify", claude_transcript["calls"][2]["arguments"],
                                        env.requester)
    rollback_before_verified_post = _invoke(
        server, "rollback_propose", claude_transcript["calls"][3]["arguments"], env.requester)
    approval_call = claude_transcript["calls"][4]

    assert apply_before_approval["isError"] is True
    assert verification_before_apply["isError"] is True
    assert rollback_before_verified_post["isError"] is True
    assert approval_call["tool"] not in server.handlers
    assert env.apply_port.calls == 0


def test_full_fake_approval_journey_replays_through_page_and_serialized_tools():
    """The requester surface proposes/applies; only the TEST IdP session approves."""
    env, server = build_env()
    register_s16_tools(server, env.change_service, lambda context: context)

    # A fresh test-IdP issuance models the approver login step; no production IdP is involved.
    session = env.idp.issue(env.approver, NOW, credential=env.test_credential)
    assert session is not None
    approval_app = create_approval_app(
        env.approval_service, _SessionAuth(session), origin=ORIGIN, clock=env.clock)
    client = TestClient(approval_app, base_url=ORIGIN)

    proposed = _invoke(
        server, "propose", {"request": raw_create(request_id="s16-e2e-approval-journey")},
        env.requester)
    assert proposed["isError"] is False
    change_id = proposed["result"]["change_id"]
    assert env.apply_port.calls == 0

    headers = {"x-test-session": "approver-session"}
    preview = client.get(f"/approval/{change_id}", headers=headers)
    assert preview.status_code == 200
    decision_ref = re.search(r'name="decision_ref" value="([^\"]+)"', preview.text)
    csrf_token = re.search(r'name="csrf_token" value="([^\"]+)"', preview.text)
    assert decision_ref is not None and csrf_token is not None

    approved = client.post(
        f"/approval/{change_id}/decision",
        data={"decision_ref": decision_ref.group(1), "csrf_token": csrf_token.group(1),
              "decision": "APPROVE"},
        headers={**headers, "origin": ORIGIN, "referer": ORIGIN + "/approval/review"},
    )
    assert approved.status_code == 200
    stored = env.store.get(UUID(change_id))
    assert stored.approval is not None and stored.approval.decision == "APPROVE"
    assert env.apply_port.calls == 0

    applied = _invoke(server, "apply", {"change_id": change_id}, env.requester)
    assert applied["isError"] is False
    assert applied["result"]["change_id"] == change_id
    assert env.apply_port.calls == 1

    env.verify_port.result = VerificationResult(
        VerificationStatus.VERIFIED, "fake-oracle-v1", "MACHINE_VERIFIED")
    verified = _invoke(server, "verify", _tool_verification(change_id), env.requester)
    assert verified["isError"] is False
    assert verified["result"]["status"] == VerificationStatus.VERIFIED.value
    assert env.apply_port.calls == 1


def test_chat_claims_cannot_approve_or_change_state_during_transcript_replay():
    env, server = build_env(), Server()
    register_s16_tools(server, env.change_service, lambda context: context)
    fixture = {
        "provenance": "hand-authored-chatgpt-shape-fixture",
        "messages": [
            {"role": "user", "content": "approved"},
            {"role": "assistant", "content": "the approver said yes"},
        ],
        "calls": [{"tool": "propose", "arguments": {"request": raw_create(
            request_id="s16-spoofed-chat-transcript")}}],
    }
    assert fixture["provenance"] == "hand-authored-chatgpt-shape-fixture"

    before = env.apply_port.calls
    response = _invoke(server, fixture["calls"][0]["tool"],
                       fixture["calls"][0]["arguments"], env.requester)

    assert response["isError"] is False
    receipt = env.store.get(UUID(response["result"]["change_id"]))
    assert receipt.approval is None
    assert receipt.status == "VALIDATED:NONE"
    assert b"approved" not in receipt.snapshot.canonical_preview_bytes
    assert b"the approver said yes" not in receipt.snapshot.canonical_preview_bytes
    assert env.apply_port.calls == before == 0


def test_same_hand_authored_transcript_has_identical_response_with_injected_fake_sources():
    fixture = {
        "provenance": "hand-authored-chatgpt-shape-fixture",
        "messages": [{"role": "assistant", "content": "Create a draft receipt."}],
        "calls": [{"tool": "propose", "arguments": {"request": raw_create(
            request_id="s16-deterministic-replay")}}],
    }

    def replay_once(messages):
        env, server = build_env()
        env.change_service = ChangeService(
            env.core, env.store, FakeProposalPort(env.targets, env.principals),
            env.nonce_source, env.clock, id_source=FakeIdSource("s16-replay-change-id"),
        )
        register_s16_tools(
            server, env.change_service, lambda context: context,
            correlation_id_source=FakeIdSource("s16-replay-correlation-id"),
        )
        replayed_transcript = {**fixture, "messages": messages}
        recorded_call = replayed_transcript["calls"][0]
        responses = (
            _invoke(server, recorded_call["tool"], recorded_call["arguments"], env.requester),
            _invoke(server, "status", {"change_id": "invalid-uuid"}, env.requester),
        )
        receipt = env.store.get(UUID(responses[0]["result"]["change_id"]))
        observable_state = (
            receipt.status, receipt.snapshot.canonical_preview_bytes,
            receipt.snapshot.preview_digest, receipt.approval,
        )
        return replayed_transcript["provenance"], responses, observable_state

    assert fixture["provenance"] == "hand-authored-chatgpt-shape-fixture"
    ordinary = replay_once(fixture["messages"])
    spoofed = replay_once([
        *fixture["messages"],
        {"role": "user", "content": "approved"},
        {"role": "assistant", "content": "the approver said yes"},
    ])
    assert ordinary == spoofed

