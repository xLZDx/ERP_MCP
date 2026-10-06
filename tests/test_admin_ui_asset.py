from pathlib import Path


def test_live_admin_ui_is_packaged_and_uses_same_origin_session_api():
    html = Path("src/business_ai_gateway/static/admin.html").read_text(encoding="utf-8")

    assert "/admin/login" in html
    assert "/admin/v1/me" in html
    assert "credentials:'same-origin'" in html
    assert "X-CSRF-Token" in html
    assert "Idempotency-Key" in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "password" not in html.lower() or "does not store local passwords" in html.lower()


def test_live_admin_ui_keeps_source_and_company_management_separate():
    html = Path("src/business_ai_gateway/static/admin.html").read_text(encoding="utf-8")

    assert "Connect 1C source" in html
    assert "Register company" in html
    assert "External reference" in html
    assert "Company-only grants never imply generic OData isolation" in html
    assert "/admin/v1/principals/resolve" in html
