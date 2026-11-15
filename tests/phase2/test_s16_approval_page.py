"""HTTP-boundary approval page tests over the S16 in-memory services; no listener is started."""
from __future__ import annotations

import html
import re

from starlette.testclient import TestClient

from erp_mcp_s16.approval_page import create_approval_app
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
