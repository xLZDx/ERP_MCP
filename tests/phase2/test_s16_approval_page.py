"""HTTP-boundary approval page tests over the S16 in-memory services; no listener is started."""
from __future__ import annotations

import asyncio
import hashlib
import html
import re
from dataclasses import replace
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from business_ai_gateway.phase2.change.errors import ErrorCode, render
from erp_mcp_s16.approval_page import create_approval_app
from erp_mcp_s16.contracts import ApprovalDecision, Result
from s16_helpers import ORIGIN, build_env, propose


class _SessionAuth:
    def __init__(self, session):
        self.session = session

    def authenticate(self, _scope, headers):
        return self.session if headers.get("x-test-session") == "approver-session" else None


def _client(env):
    app = create_approval_app(env.approval_service, _SessionAuth(env.session),
                              origin=ORIGIN, clock=env.clock)
    return TestClient(app, base_url=ORIGIN)


def _headers(**extra):
    return {"x-test-session": "approver-session", **extra}


def test_approval_page_renders_service_preview_and_accepts_one_origin_checked_decision():
    env = build_env()
    snapshot = propose(env, reason="<script>alert(1)</script>")
    client = _client(env)

    page = client.get(
        f"/approval/{snapshot.change_id}?lifecycle_status=REJECTED&authorization_status=APPROVED"
        "&snapshot_version=99&created_at=1999-01-01T00%3A00%3A00%2B00%3A00"
        "&approver_person_label=Attacker&decision_allowed=false",
        headers=_headers(),
    )
    assert page.status_code == 200
    assert "<dd>VALIDATED</dd>" in page.text
    assert "<dd>NONE</dd>" in page.text
    assert "<dd>1</dd>" in page.text
    assert '<time datetime="2026-10-29T12:00:00+00:00">2026-10-29T12:00:00+00:00</time>' in page.text
    assert "Approver One" in page.text
    assert "Attacker" not in page.text and "1999-01-01" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert html.escape(snapshot.canonical_preview_bytes.decode("utf-8")) in page.text
    preview_section = re.search(
        r'<section aria-labelledby="canonical-preview">(.*?)</section>',
        page.text,
        re.DOTALL,
    )
    assert preview_section is not None
    displayed_preview = re.search(r"<pre>(.*?)</pre>", preview_section.group(1), re.DOTALL)
    displayed_digest = re.search(r"SHA-256 preview digest: <code>([0-9a-f]{64})</code>",
                                  preview_section.group(1))
    assert displayed_preview is not None and displayed_digest is not None
    visible_preview_bytes = html.unescape(displayed_preview.group(1)).encode("utf-8")
    assert visible_preview_bytes == snapshot.canonical_preview_bytes
    visible_preview_digest = hashlib.sha256(visible_preview_bytes).hexdigest()
    assert displayed_digest.group(1) == visible_preview_digest == snapshot.preview_digest
    assert env.session.session_id not in page.text
    assert env.session.csrf_secret not in page.text
    decision_ref = re.search(r'name="decision_ref" value="([^"]+)"', page.text)
    assert decision_ref is not None
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert csrf_token is not None
    assert page.text.count(decision_ref.group(1)) == 2  # one form each for Approve and Reject
    forms = re.findall(r"<form\b[^>]*>.*?</form>", page.text, re.DOTALL)
    assert len(forms) == 2 and all(decision_ref.group(1) in form for form in forms)
    assert decision_ref.group(1) not in re.sub(r"<form\b[^>]*>.*?</form>", "", page.text, flags=re.DOTALL)

    form = {"decision_ref": decision_ref.group(1), "csrf_token": csrf_token.group(1),
            "decision": "APPROVE"}
    accepted = client.post(
        f"/approval/{snapshot.change_id}/decision", data=form,
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )
    assert accepted.status_code == 200
    receipt = env.store.get(snapshot.change_id)
    assert receipt.approval is not None and receipt.approval.decision == "APPROVE"
    assert env.apply_port.calls == 0

    replay = client.post(
        f"/approval/{snapshot.change_id}/decision", data=form,
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )
    assert replay.status_code == 403
    assert env.store.get(snapshot.change_id).approval == receipt.approval
    assert env.apply_port.calls == 0

    decided = client.get(f"/approval/{snapshot.change_id}", headers=_headers())
    assert decided.status_code == 403
    assert "<form" not in decided.text


def test_preview_rejects_truthy_integer_independence_before_issuing_nonce():
    env = build_env()
    snapshot = propose(env, request_id="approval-independence-exact-bool")
    client = _client(env)
    before_receipt = env.store.get(snapshot.change_id)
    nonce_count_before = env.nonce_source._counter
    original_are_independent = env.principals.are_independent

    # A registry adapter must return the declared bool contract, not merely a truthy value.
    env.principals.are_independent = lambda _requester, _approver: 1
    refused = client.get(f"/approval/{snapshot.change_id}", headers=_headers())

    assert refused.status_code == 403
    assert render(ErrorCode.APPROVER_NOT_INDEPENDENT).message in refused.text
    assert "<form" not in refused.text
    assert env.nonce_source._counter == nonce_count_before
    assert env.store.get(snapshot.change_id) == before_receipt

    # The same fixture succeeds when the registry honors its exact bool contract.
    env.principals.are_independent = original_are_independent
    accepted = client.get(f"/approval/{snapshot.change_id}", headers=_headers())
    assert accepted.status_code == 200
    assert '<form' in accepted.text
    assert env.nonce_source._counter == nonce_count_before + 1
    assert env.store.get(snapshot.change_id) == before_receipt


def test_approval_page_refuses_preview_and_decision_after_approver_revocation():
    env = build_env()
    snapshot = propose(env, request_id="approval-page-approver-revoked")
    client = _client(env)
    preview = client.get(f"/approval/{snapshot.change_id}", headers=_headers())

    assert preview.status_code == 200
    decision_ref = re.search(r'name="decision_ref" value="([^"]+)"', preview.text)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', preview.text)
    assert decision_ref is not None and csrf_token is not None
    stale_form = {"decision_ref": decision_ref.group(1),
                  "csrf_token": csrf_token.group(1), "decision": "APPROVE"}
    receipt_before_revoke = env.store.get(snapshot.change_id)
    nonce_count_before_revoke = env.nonce_source._counter

    env.principals.revoke(env.approver.principal_id)

    next_preview = client.get(f"/approval/{snapshot.change_id}", headers=_headers())
    refused_decision = client.post(
        f"/approval/{snapshot.change_id}/decision",
        data=stale_form,
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )

    assert next_preview.status_code == 403
    assert "<form" not in next_preview.text
    assert refused_decision.status_code == 403
    assert "Decision recorded." not in refused_decision.text
    assert env.nonce_source._counter == nonce_count_before_revoke
    assert env.store.get(snapshot.change_id) == receipt_before_revoke
    assert env.apply_port.calls == 0


@pytest.mark.parametrize("threshold", ["Infinity", "-1", 1, True], ids=[
    "non-finite", "negative", "integer-not-string", "bool-not-string",
])
def test_preview_rejects_invalid_confirmation_threshold_before_issuing_nonce(threshold):
    env = build_env()
    snapshot = propose(env, request_id=f"approval-invalid-threshold-{threshold!r}")
    target = env.targets.current(snapshot.scope)
    env.targets.put(replace(target, amount_confirmation_threshold=threshold))
    client = _client(env)
    before_receipt = env.store.get(snapshot.change_id)
    nonce_count_before = env.nonce_source._counter

    refused = client.get(f"/approval/{snapshot.change_id}", headers=_headers())

    assert refused.status_code == 403
    assert render(ErrorCode.TARGET_REJECTED).message in refused.text
    assert "<form" not in refused.text
    assert env.nonce_source._counter == nonce_count_before
    assert env.store.get(snapshot.change_id) == before_receipt


def test_amount_equal_to_confirmation_threshold_needs_no_extra_confirmation():
    env = build_env()
    snapshot = propose(env, request_id="approval-threshold-equality")
    target = env.targets.current(snapshot.scope)
    # The fixture's independent business amount is 21.00 + 3.50 = 24.50 RUB.
    env.targets.put(replace(target, amount_confirmation_threshold="24.50"))
    client = _client(env)

    page = client.get(f"/approval/{snapshot.change_id}", headers=_headers())

    assert page.status_code == 200
    assert 'name="confirmation_text"' not in page.text
    decision_ref = re.search(r'name="decision_ref" value="([^"]+)"', page.text).group(1)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    accepted = client.post(
        f"/approval/{snapshot.change_id}/decision",
        data={"decision_ref": decision_ref, "csrf_token": csrf_token,
              "decision": "APPROVE"},
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )

    assert accepted.status_code == 200
    receipt = env.store.get(snapshot.change_id)
    assert receipt.approval is not None and receipt.approval.decision == "APPROVE"
    assert env.apply_port.calls == 0


def test_amount_above_confirmation_threshold_requires_exact_phrase():
    env = build_env()
    snapshot = propose(env, request_id="approval-threshold-confirmation")
    target = env.targets.current(snapshot.scope)
    env.targets.put(replace(target, amount_confirmation_threshold="24.49"))
    client = _client(env)

    page = client.get(f"/approval/{snapshot.change_id}", headers=_headers())

    assert page.status_code == 200
    assert 'name="confirmation_text"' in page.text
    assert "CONFIRM CHANGE" in page.text
    decision_ref = re.search(r'name="decision_ref" value="([^"]+)"', page.text).group(1)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    missing_phrase = client.post(
        f"/approval/{snapshot.change_id}/decision",
        data={"decision_ref": decision_ref, "csrf_token": csrf_token,
              "decision": "APPROVE"},
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )
    assert missing_phrase.status_code == 403
    assert env.store.get(snapshot.change_id).approval is None
    assert env.apply_port.calls == 0

    # A fresh decision reference makes the successful exact-phrase case independent
    # of whether a future implementation consumes references on policy refusal.
    fresh_page = client.get(f"/approval/{snapshot.change_id}", headers=_headers())
    assert fresh_page.status_code == 200
    fresh_ref = re.search(r'name="decision_ref" value="([^"]+)"', fresh_page.text).group(1)
    fresh_csrf = re.search(r'name="csrf_token" value="([^"]+)"', fresh_page.text).group(1)
    accepted = client.post(
        f"/approval/{snapshot.change_id}/decision",
        data={"decision_ref": fresh_ref, "csrf_token": fresh_csrf,
              "decision": "APPROVE", "confirmation_text": "CONFIRM CHANGE"},
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )

    assert accepted.status_code == 200
    receipt = env.store.get(snapshot.change_id)
    assert receipt.approval is not None and receipt.approval.decision == "APPROVE"
    assert env.apply_port.calls == 0


def test_approval_post_rejects_target_version_changed_after_preview():
    env = build_env()
    snapshot = propose(env, request_id="approval-target-version-stale")
    client = _client(env)
    page = client.get(f"/approval/{snapshot.change_id}", headers=_headers())
    assert page.status_code == 200
    decision_ref = re.search(r'name="decision_ref" value="([^"]+)"', page.text).group(1)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    target = env.targets.current(snapshot.scope)
    env.targets.change_version(snapshot.scope, replace(target.version, value="v2"))

    refused = client.post(
        f"/approval/{snapshot.change_id}/decision",
        data={"decision_ref": decision_ref, "csrf_token": csrf_token,
              "decision": "APPROVE"},
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )

    assert refused.status_code == 403
    assert render(ErrorCode.STALE_VERSION).message in refused.text
    assert env.store.get(snapshot.change_id).approval is None
    assert env.apply_port.calls == 0


def test_approval_post_rejects_missing_or_foreign_origin_and_keeps_authorization_unchanged():
    env = build_env()
    # A pending proposal supplies a live approval page without making a decision.
    pending = propose(env, request_id="approval-origin-negative")
    page = _client(env).get(f"/approval/{pending.change_id}", headers=_headers())
    assert page.status_code == 200
    decision_ref = re.search(r'name="decision_ref" value="([^"]+)"', page.text).group(1)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    valid_form = {"decision_ref": decision_ref, "csrf_token": csrf_token, "decision": "APPROVE"}
    before = env.store.get(pending.change_id)
    client = _client(env)

    missing = client.post(f"/approval/{pending.change_id}/decision",
                          data=valid_form,
                          headers=_headers())
    foreign = client.post(f"/approval/{pending.change_id}/decision",
                          data=valid_form,
                          headers=_headers(origin=ORIGIN, referer="https://attacker.invalid/approval/"))
    invalid_csrf = ("0" if csrf_token[0] != "0" else "1") + csrf_token[1:]
    csrf_rejected = client.post(
        f"/approval/{pending.change_id}/decision",
        data={**valid_form, "csrf_token": invalid_csrf},
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )
    assert missing.status_code == foreign.status_code == csrf_rejected.status_code == 403
    assert env.store.get(pending.change_id) == before
    assert env.apply_port.calls == 0


def test_approval_post_bounds_body_bytes_and_asgi_message_count_before_service_call():
    env = build_env()
    snapshot = propose(env, request_id="approval-form-bounds")
    app = create_approval_app(env.approval_service, _SessionAuth(env.session),
                              origin=ORIGIN, clock=env.clock)
    submit_calls = []
    env.approval_service.submit_decision = lambda *args, **kwargs: submit_calls.append(args)
    scope = {
        "type": "http", "method": "POST",
        "path": f"/approval/{snapshot.change_id}/decision",
        "scheme": "https",
        "headers": [
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"origin", ORIGIN.encode("ascii")),
            (b"referer", (ORIGIN + "/approval/review").encode("ascii")),
            (b"x-test-session", b"approver-session"),
        ],
    }

    async def run_request(messages):
        pending = iter(messages)
        sent = []

        async def receive():
            return next(pending)

        async def send(message):
            sent.append(message)

        await app(scope, receive, send)
        return sent

    over_byte_limit = asyncio.run(run_request(({
        "type": "http.request", "body": b"x" * 8193, "more_body": False,
    },)))
    over_message_limit = asyncio.run(run_request(tuple(
        {"type": "http.request", "body": b"", "more_body": True}
        for _ in range(8193)
    )))

    assert [message["status"] for message in (over_byte_limit[0], over_message_limit[0])] == [400, 400]
    assert submit_calls == []


def test_malformed_http_scope_fields_return_schema_error_before_auth_or_service():
    env = build_env()
    snapshot = propose(env, request_id="approval-malformed-scope")

    class ExplodingMethod:
        def __eq__(self, _other):
            raise RuntimeError("untrusted method comparison")

    class CountingAuth:
        calls = 0

        def authenticate(self, _scope, _headers):
            self.calls += 1
            return env.session

    authenticator = CountingAuth()
    service_calls = []
    env.approval_service.open_preview = lambda *args, **kwargs: service_calls.append("preview")
    env.approval_service.submit_decision = lambda *args, **kwargs: service_calls.append("decision")
    app = create_approval_app(env.approval_service, authenticator, origin=ORIGIN, clock=env.clock)
    base_scope = {
        "type": "http", "method": "POST",
        "path": f"/approval/{snapshot.change_id}/decision",
        "scheme": "https",
        "headers": [(b"x-test-session", b"approver-session")],
    }

    async def run_request(scope):
        sent = []

        async def receive():
            raise AssertionError("malformed scope must be rejected before reading the body")

        async def send(message):
            sent.append(message)

        await app(scope, receive, send)
        return sent

    malformed_scopes = [
        {**base_scope, "type": []},
        {**base_scope, "method": ExplodingMethod()},
    ]
    for scope in malformed_scopes:
        sent = asyncio.run(run_request(scope))
        assert sent[0]["status"] == 400
        body = sent[1]["body"]
        assert b"The request is not valid." in body

    assert authenticator.calls == 0
    assert service_calls == []


def test_approval_post_rejects_success_receipt_bound_to_another_decision_ref():
    env = build_env()
    snapshot = propose(env, request_id="approval-result-ref-mismatch")
    client = _client(env)
    page = client.get(f"/approval/{snapshot.change_id}", headers=_headers())
    assert page.status_code == 200
    decision_ref = re.search(r'name="decision_ref" value="([^"]+)"', page.text).group(1)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    principal = env.session.principal
    malformed_success = ApprovalDecision(
        change_id=snapshot.change_id,
        version=snapshot.version,
        scope=snapshot.scope,
        requester_person_id=snapshot.proposal.requester_person_id,
        approver_person_id=principal.person_id,
        approver_principal_id=principal.principal_id,
        approver_epoch=principal.epoch,
        session_id=env.session.session_id,
        nonce_digest=snapshot.nonce_digest,
        decision_ref_digest=hashlib.sha256(b"different-decision-ref").hexdigest(),
        preview_digest=snapshot.preview_digest,
        approval_digest=snapshot.approval_digest,
        decision="APPROVE",
        expires_at=env.clock.now() + timedelta(minutes=5),
    )
    env.approval_service.submit_decision = lambda *args, **kwargs: Result.success(malformed_success)

    response = client.post(
        f"/approval/{snapshot.change_id}/decision",
        data={"decision_ref": decision_ref, "csrf_token": csrf_token, "decision": "APPROVE"},
        headers=_headers(origin=ORIGIN, referer=ORIGIN + "/approval/review"),
    )

    assert response.status_code == 403
    assert "Decision recorded." not in response.text
    assert env.store.get(snapshot.change_id).approval is None
    assert env.apply_port.calls == 0


@pytest.mark.parametrize("path_kind", ["approval", "css"])
def test_approval_and_css_clock_exceptions_return_safe_503_without_masking_auth_failure(path_kind):
    env = build_env()
    snapshot = propose(env, request_id=f"approval-clock-{path_kind}")
    path = (f"/approval/{snapshot.change_id}" if path_kind == "approval" else "/approval/s16.css")
    client = _client(env)

    unauthenticated = client.get(path)
    assert unauthenticated.status_code == 401

    def unavailable_clock():
        raise OSError("private clock failure detail")

    env.clock.now = unavailable_clock
    response = client.get(path, headers=_headers())

    assert response.status_code == 503
    assert render(ErrorCode.AUDIT_UNAVAILABLE).message in response.text
    assert "private clock failure detail" not in response.text
