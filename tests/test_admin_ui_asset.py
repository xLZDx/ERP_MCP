import re
from pathlib import Path

import pytest

from business_ai_gateway.admin_api import AdminAPI


def test_live_admin_ui_is_packaged_and_uses_same_origin_session_api():
    html = Path("src/business_ai_gateway/static/admin.html").read_text(encoding="utf-8")
    javascript = Path("src/business_ai_gateway/static/admin.js").read_text(encoding="utf-8")
    app = html + javascript

    assert "/admin/login" in app
    assert "/admin/v1/me" in app
    assert "credentials:'same-origin'" in javascript
    assert "X-CSRF-Token" in javascript
    assert "Idempotency-Key" in javascript
    assert "localStorage" not in app
    assert "sessionStorage" not in app
    assert "password" not in app.lower() or "does not store local passwords" in app.lower()
    assert '<script src="/admin/static/admin.js" defer></script>' in html
    assert "<script>" not in html
    assert Path("src/business_ai_gateway/static/admin.js").is_file()


@pytest.mark.asyncio
async def test_admin_ui_csp_allows_only_same_origin_scripts():
    api = object.__new__(AdminAPI)
    html_response = await api.admin_ui(None)
    csp = html_response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    js_response = await api.admin_js(None)
    assert js_response.media_type == "text/javascript"


def test_live_admin_ui_keeps_source_and_company_management_separate():
    javascript = Path("src/business_ai_gateway/static/admin.js").read_text(encoding="utf-8")
    html = Path("src/business_ai_gateway/static/admin.html").read_text(encoding="utf-8")
    app = html + javascript

    assert "Connect 1C source" in app
    assert "Register company" in app
    assert "External reference" in app
    assert "Generic company-scope mappings are recorded as candidates only and do not authorize OData reads" in app
    assert "Company scope" in javascript and "Expires" in javascript
    assert "Conflict:" in javascript
    assert "/admin/v1/principals/resolve" in app


INLINE_HANDLER = re.compile(r"(?<![\w.])on[a-z]{3,}\s*=\s*\\?[\"']")


def test_no_inline_event_handler_attributes_in_served_html_or_js():
    """The CSP has no 'unsafe-inline' for scripts, so on* attributes silently do nothing."""
    html = Path("src/business_ai_gateway/static/admin.html").read_text(encoding="utf-8")
    javascript = Path("src/business_ai_gateway/static/admin.js").read_text(encoding="utf-8")
    assert INLINE_HANDLER.findall(html) == []
    assert INLINE_HANDLER.findall(javascript) == []
    assert "javascript:" not in html + javascript


def test_every_data_act_target_is_registered_in_the_delegated_dispatcher():
    javascript = Path("src/business_ai_gateway/static/admin.js").read_text(encoding="utf-8")
    block = javascript.split("const ACTIONS={", 1)[1].split("};", 1)[0]
    registered = set(re.findall(r"(\w+):", block))
    used = set(re.findall(r"data-act=\"(\w+)\"", javascript))
    used |= set(re.findall(r"modal\([^\n]*?,'(\w+)'\)", javascript))
    assert used and used <= registered, sorted(used - registered)


def test_row_action_buttons_have_row_specific_accessible_names():
    javascript = Path("src/business_ai_gateway/static/admin.js").read_text(encoding="utf-8")
    # Visible labels repeat on every row ("Edit / disable", "Revoke"); each button must carry an
    # aria-label that starts with the visible label and names the row target (WCAG 2.5.3, 2.4.6).
    assert "function rowLabel(label,item)" in javascript
    assert "return label+': '+name" in javascript
    operation = javascript[javascript.index("function operationButton"):]
    operation = operation[: operation.index("\n}")]
    assert "aria-label=\"'+esc(rowLabel(label,item))" in operation
    evidence = javascript[javascript.index("function evidenceButton"):]
    evidence = evidence[: evidence.index("\n")]
    assert "aria-label=\"'+esc(rowLabel('Evidence',item))" in evidence

