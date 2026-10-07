"""Headless browser contract/accessibility smoke. Uses only synthetic same-origin APIs."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

ORIGIN = "https://admin.test"
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
COMPANY = "11111111-1111-4111-8111-111111111111"
PROFILE = "22222222-2222-4222-8222-222222222222"
GRANT = "33333333-3333-4333-8333-333333333333"


async def verify():
    html = Path("src/business_ai_gateway/static/admin.html").read_text(encoding="utf-8")
    javascript = Path("src/business_ai_gateway/static/admin.js").read_text(encoding="utf-8")
    requests, errors = [], []
    import re
    inline = re.findall(r"(?<![\w.])on[a-z]{3,}\s*=\s*\\?[\"']", html + javascript)
    assert not inline, f"inline event-handler attributes are blocked by the page CSP: {inline}"
    source = {"source_id": "source-1", "display_name": "<img src=x onerror=alert(1)>", "kind": "onec_auto",
              "read_only": True, "enabled": True, "row_version": 1, "base_url": "https://approved.test/odata",
              "username_secret_ref": "USER_REF", "password_secret_ref": "PASS_REF", "tags": []}
    companies = [{"company_id": COMPANY, "source_id": "source-1", "external_ref": "org-1",
                  "display_name": "Company A", "enabled": True, "row_version": 1}]
    fixtures = {
        "/admin/v1/me": {"subject": "operator", "roles": [{"role": "PLATFORM_ADMIN", "source_id": None}],
                          "mutations_enabled": True, "csrf_token": "synthetic-csrf",
                          "business_capability_enforcement_enabled": True, "platform_role_step_up_configured": True},
        "/admin/v1/overview": {"sources": 1, "companies": 1, "drifted_sources": 1},
        "/admin/v1/sources": {"items": [source]}, "/admin/v1/sources/source-1": source,
        "/admin/v1/companies": {"items": companies}, "/admin/v1/companies/" + COMPANY: companies[0],
        "/admin/v1/capabilities": {"items": [{"source_id": "source-1", "metadata_fingerprint": "current-fingerprint",
                                             "drift_status": "DRIFTED", "adapter_profile": "ODATA_JSON_V3"}]},
        "/admin/v1/grants": {"items": [{"grant_id": GRANT, "principal_kind": "subject", "principal_id": "employee",
                                        "source_id": "source-1", "company_id": COMPANY, "effect": "allow", "row_version": 1}]},
        "/admin/v1/business-roles": {"items": [{"role_id": "VIEWER", "display_name": "Viewer", "capabilities": ["accounting.read"]}]},
        "/admin/v1/platform-role-bindings": {"items": []},
        "/admin/v1/business-role-assignments": {"items": []}, "/admin/v1/capability-overrides": {"items": []},
        "/admin/v1/semantic-profiles": {"items": [{"profile_id": PROFILE, "source_id": "source-1", "profile_name": "Test profile", "status": "DRAFT", "profile_version": 1}]},
        "/admin/v1/audit": {"admin": [], "access": []},
        "/admin/v1/principals/resolve": {"principal_kind": "subject", "principal_id": "employee", "mode": "exact-id", "directory_status": "not_configured"},
        "/admin/v1/effective-access": {"mode": "exact-id", "group_membership": "not_configured", "items": [], "next_offset": None},
    }

    async with async_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("BAG_UI_BROWSER_EXECUTABLE"):
            options["executable_path"] = os.environ["BAG_UI_BROWSER_EXECUTABLE"]
        browser = await playwright.chromium.launch(**options)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append("CSP violation: " + msg.text[:200])
                if "Content Security Policy" in msg.text else None)
        attempts = 0

        async def route_handler(route):
            nonlocal attempts
            request = route.request
            path = request.url.split(ORIGIN, 1)[-1].split("?", 1)[0]
            if path == "/admin/":
                # Serve the page with the exact CSP the gateway sends so inline handlers fail here.
                await route.fulfill(status=200, content_type="text/html", body=html,
                                    headers={"Content-Security-Policy": CSP})
                return
            if path == "/admin/static/admin.js":
                await route.fulfill(status=200, content_type="text/javascript", body=javascript)
                return
            if request.method in {"POST", "PATCH"}:
                assert request.headers.get("x-csrf-token") == "synthetic-csrf"
                assert request.headers.get("idempotency-key")
                body = json.loads(request.post_data or "{}")
                requests.append((path, request.headers["idempotency-key"], body))
                if path == "/admin/v1/grants":
                    attempts += 1
                    if attempts == 1:
                        await route.fulfill(status=503, json={"error": "ADMIN_DEPENDENCY_UNAVAILABLE"})
                        return
                await route.fulfill(status=200, json={"id": GRANT, "capabilities": {"metadata_fingerprint": "fp"}})
            elif path in fixtures:
                await route.fulfill(status=200, json=fixtures[path])
            else:
                errors.append("unexpected browser route: " + path)
                await route.fulfill(status=404, json={"error": "NOT_FOUND"})

        await page.route(ORIGIN + "/**", route_handler)
        await page.goto(ORIGIN + "/admin/")
        await page.get_by_role("heading", name="Overview", exact=True).wait_for()
        await page.get_by_role("button", name="Access policies").click()
        await page.get_by_role("button", name="Create grant").click()
        await page.get_by_role("dialog").wait_for()
        await page.get_by_label("Stable IdP principal ID").fill("employee")
        await page.get_by_label("Source ID", exact=True).fill("source-1")
        await page.get_by_label("Reason", exact=True).fill("Browser contract test")
        await page.get_by_role("button", name="Submit", exact=True).click()
        await page.get_by_role("alert").filter(has_text="ADMIN_DEPENDENCY_UNAVAILABLE").wait_for()
        await page.get_by_role("button", name="Submit", exact=True).click()
        await page.get_by_role("heading", name="Access policies", exact=True).wait_for()
        assert requests[0][1] == requests[1][1], "retry must retain idempotency key"
        assert requests[0][2] == requests[1][2]
        for name in ["1C sources", "Companies", "Users & groups", "Roles & capabilities", "Semantic profiles", "Audit & evidence"]:
            await page.get_by_role("button", name=name, exact=True).click()
            await page.get_by_role("heading", name=name, exact=True, level=1).wait_for()
        await page.get_by_role("button", name="1C sources", exact=True).click()
        # Row buttons carry a row-specific aria-label ("Edit / disable <row>"), so match the prefix.
        edit_button = page.get_by_role("button", name="Edit / disable").first
        await edit_button.wait_for()
        assert await page.locator("img").count() == 0, "untrusted labels must be escaped"
        await edit_button.click()
        await page.get_by_role("dialog").wait_for()
        await page.keyboard.press("Escape")
        assert await page.get_by_role("dialog").count() == 0
        assert await page.evaluate("document.activeElement.textContent") == "Edit / disable"
        await page.set_viewport_size({"width": 390, "height": 844})
        assert await page.get_by_role("button", name="Companies", exact=True).is_visible()
        await page.evaluate("document.documentElement.style.zoom='2'")
        assert await page.get_by_role("button", name="Companies", exact=True).is_visible()
        assert await page.evaluate("Object.keys(localStorage).length + Object.keys(sessionStorage).length") == 0
        fixtures["/admin/v1/me"].update(business_capability_enforcement_enabled=False, platform_role_step_up_configured=False)
        await page.reload()
        await page.get_by_role("button", name="Roles & capabilities", exact=True).click()
        await page.get_by_text("Business capability enforcement is OFF.", exact=False).wait_for()
        assert await page.get_by_role("button", name="Assign business role", exact=True).count() == 0
        assert await page.get_by_role("button", name="Assign platform role", exact=True).count() == 0
        assert not errors, errors
        await browser.close()
    print("Admin UI browser contract: PASS (navigation, mutation retry, CSRF, escaping, dialog focus, narrow layout, 200% zoom)")


if __name__ == "__main__":
    asyncio.run(verify())
