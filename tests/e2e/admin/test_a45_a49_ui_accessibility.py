"""A45-A49: Admin UI accessibility and state rendering in a real Chromium (headless).

Keyboard rows press real Tab/Enter/Escape keys; zoom and narrow rows use a real viewport and
device scale factor (200% zoom == 640x360 CSS px at scale 2, 400 px == 400x800); state rows
render loading / empty / error / 403 / 409 / stale and keep a screenshot as evidence under
``.e2e/artifacts/admin``. Responses are only stubbed where a state cannot be produced by the
real product on demand (empty list, HTTP 500, delayed response).

Finding: the page's inline ``onclick`` attributes are blocked by its own Content-Security-Policy
(``script-src 'self'``), so "Create grant", "Sign out", dialog Submit/Cancel and "Retry" do
nothing in a real browser. That is asserted strictly by ``test_A45_ui_actions_are_not_blocked_
by_the_page_csp`` and the keyboard create/revoke test; other rows that need a dialog open it by
calling the page's own functions so that their own behaviour is still measured.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest
from admin_support import expect, shot, unique, wait_until

pytestmark = [pytest.mark.admin]

PAGES = {
    "overview": "Overview", "sources": "1C sources", "companies": "Companies",
    "identities": "Users & groups", "access": "Access policies",
    "roles": "Roles & capabilities", "profiles": "Semantic profiles",
    "audit": "Audit & evidence",
}
DESCRIBE_JS = """() => { const e = document.activeElement; if (!e) return 'none';
  const all = Array.from(document.querySelectorAll('*')); const r = e.getBoundingClientRect();
  return e.tagName + '#' + (e.id || '') + '[' + ((e.getAttribute('aria-label') || e.innerText
  || e.value || '') + '').trim().slice(0, 40) + ']@' + all.indexOf(e) + ':' +
  Math.round(r.top) + ',' + Math.round(r.left); }"""
LAYOUT_JS = """() => {
  const vw = document.documentElement.clientWidth, bad = [];
  for (const e of document.querySelectorAll('button, a[href], input, select, textarea')) {
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height || e.closest('.tablewrap')) continue;
    if (r.right > vw + 1 || r.left < -1)
      bad.push((e.id || e.innerText || e.tagName).toString().slice(0, 30) + ' @' +
               Math.round(r.left) + '..' + Math.round(r.right));
  }
  return {bad, scrollWidth: document.documentElement.scrollWidth, vw,
          bodyText: document.body.innerText.length};
}"""
IN_DIALOG_JS = ("() => document.querySelector('.modal').contains(document.activeElement)"
                " && document.activeElement !== document.body")
ERROR_TEXT_JS = "() => document.querySelector('#workflow_error')?.innerText.length > 0"


def tab_to(page, selector=None, *, predicate=None, limit=200):
    """Press Tab until the focused element matches; fail on keyboard traps or exhaustion."""
    test = predicate or f"(e) => e.matches({json.dumps(selector)})"
    visited, last, same = [], None, 0
    for _ in range(limit):
        if page.evaluate(f"() => {{ const e = document.activeElement; "
                         f"return !!e && e !== document.body && ({test})(e); }}"):
            return visited
        page.keyboard.press("Tab")
        info = page.evaluate(DESCRIBE_JS)
        same = same + 1 if info == last else 0
        if same >= 3:
            pytest.fail(f"keyboard trap: focus stuck on {info} (visited {visited[-5:]})")
        last = info
        visited.append(info)
    pytest.fail(f"{selector or predicate} not reachable by keyboard in {limit} Tab presses; "
                f"last visited {visited[-8:]}")


def go_to_page(page, key):
    tab_to(page, f'.nav button[data-page="{key}"]')
    page.keyboard.press("Enter")
    page.wait_for_function("(k) => document.querySelector('.nav button.active')?.dataset.page "
                           "=== k", arg=key)
    page.wait_for_selector(".content h1")
    page.wait_for_selector(".content .loading", state="detached")


def click_page(page, key):
    page.click(f'.nav button[data-page="{key}"]')
    page.wait_for_function("(k) => document.querySelector('.nav button.active')?.dataset.page "
                           "=== k", arg=key)


def settled(page):
    page.wait_for_selector("#root .loading", state="detached")


def open_dialog(page, opener):
    """Open a workflow dialog by calling the page's own function (see module docstring)."""
    page.evaluate(f"() => {opener}()")
    page.wait_for_selector(".modal")


def submit_dialog(page):
    page.evaluate("() => saveWorkflow()")


def row_button(page, text, label):
    return page.locator("tr", has=page.get_by_text(text, exact=True)).get_by_role(
        "button", name=label)


# --------------------------------------------------------------------------------------- A45
def test_A45_keyboard_only_navigation_reaches_every_page(e2e_env, world, browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin")
    for key, title in PAGES.items():
        go_to_page(page, key)
        assert page.inner_text(".content h1") == title, f"page {key} did not render by keyboard"
    tab_to(page, ".top button")  # Sign out is reachable
    assert page.evaluate("() => document.activeElement.innerText") == "Sign out"


def test_A45_row_actions_are_operable_by_keyboard(e2e_env, world, browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin")
    go_to_page(page, "companies")
    tab_to(page, predicate="(e) => e.dataset.op === 'company' && "
                           "e.closest('tr').innerText.includes('Synthetic Company One')")
    page.keyboard.press("Enter")
    page.wait_for_selector(".modal")
    tab_to(page, "#wf_reason")
    page.keyboard.type("A45 keyboard typing works")
    assert page.input_value("#wf_reason") == "A45 keyboard typing works"
    page.keyboard.press("Escape")
    page.wait_for_selector(".modal", state="detached")


def test_A45_ui_actions_are_not_blocked_by_the_page_csp(e2e_env, world, browser_login):
    """Every primary action must work under the CSP the page itself sends."""
    world.need("source", "company_one")
    page = browser_login("platform_admin")
    violations = []
    page.on("console", lambda m: violations.append(m.text[:160])
            if "Content Security Policy" in m.text else None)
    go_to_page(page, "access")
    page.locator(".actions button.primary").click()
    opened = page.locator(".modal").count()
    assert violations == [] and opened == 1, (
        f"'Create grant' does nothing: modal={opened}, CSP violations={violations}")
    page.keyboard.press("Escape")
    page.wait_for_selector(".modal", state="detached")
    page.locator(".top button", has_text="Sign out").click()
    page.wait_for_selector(".loginbox")
    assert violations == [], f"CSP blocked page actions: {violations}"


def test_A45_keyboard_only_grant_create_and_revoke(e2e_env, world, evidence, browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin")
    principal = unique("e2e-kbd")
    go_to_page(page, "access")
    tab_to(page, ".actions button.primary")
    page.keyboard.press("Enter")
    page.wait_for_selector(".modal", timeout=5000)
    tab_to(page, "#wf_principal_id")
    page.keyboard.type(principal)
    tab_to(page, "#wf_source_id")
    page.keyboard.type(world.source_id)
    tab_to(page, "#wf_reason")
    page.keyboard.type("A45 keyboard-only grant")
    tab_to(page, ".modalf button.primary")
    page.keyboard.press("Enter")
    page.wait_for_selector("#toast .toast", timeout=10_000)
    assert page.inner_text("#toast").startswith("Success"), page.inner_text("#toast")
    row = evidence.one("SELECT grant_id, created_by_subject, create_reason FROM bag.access_grants "
                       "WHERE principal_id=$1", principal)
    assert row and row["created_by_subject"] == "platform_admin"
    grant_id = str(row["grant_id"])
    page.wait_for_selector(f"tr:has-text('{principal}')")
    tab_to(page, predicate="(e) => e.dataset.op === 'grant-revoke' && "
                           f"e.closest('tr').innerText.includes('{principal}')")
    page.keyboard.press("Enter")
    page.wait_for_selector(".modal")
    tab_to(page, "#wf_reason")
    page.keyboard.type("A45 keyboard revoke")
    tab_to(page, "#wf_confirm")
    page.keyboard.type(grant_id)
    tab_to(page, ".modalf button.primary")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('#toast .toast')?.innerText"
                           ".startsWith('Success')", timeout=10_000)
    after = evidence.one("SELECT revoked_at, revoked_by_subject FROM bag.access_grants "
                         "WHERE grant_id=$1", uuid.UUID(grant_id))
    assert after["revoked_at"] is not None and after["revoked_by_subject"] == "platform_admin"


# --------------------------------------------------------------------------------------- A46
def _company_edit_dialog_by_keyboard(page):
    go_to_page(page, "companies")
    tab_to(page, predicate="(e) => e.dataset.op === 'company' && "
                           "e.closest('tr').innerText.includes('Synthetic Company One')")
    opener = page.evaluate(DESCRIBE_JS)
    outline = page.evaluate("() => { const s = getComputedStyle(document.activeElement); "
                            "return [s.outlineStyle, parseFloat(s.outlineWidth)]; }")
    page.keyboard.press("Enter")
    page.wait_for_selector(".modal")
    return opener, outline


def test_A46_focus_is_visible_and_returns_logically_from_dialogs(e2e_env, world, browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin")
    opener, outline = _company_edit_dialog_by_keyboard(page)
    assert outline[0] != "none" and outline[1] >= 2, f"focus not visible: {outline}"
    dialog = page.evaluate("""() => { const d = document.querySelector('.modal');
        return {role: d.getAttribute('role'), modal: d.getAttribute('aria-modal'),
                labelled: !!document.getElementById(d.getAttribute('aria-labelledby')),
                inside: d.contains(document.activeElement)}; }""")
    assert dialog == {"role": "dialog", "modal": "true", "labelled": True, "inside": True}, dialog
    for _ in range(25):  # focus stays inside the dialog (documented trap with an Escape exit)
        page.keyboard.press("Tab")
        assert page.evaluate("() => document.querySelector('.modal').contains("
                             "document.activeElement)"), "focus escaped the open dialog"
    page.keyboard.press("Escape")
    page.wait_for_selector(".modal", state="detached")
    assert page.evaluate(DESCRIBE_JS) == opener, "focus did not return to the opener"
    shot(page, "A46-dialog-closed")


def test_A46_validation_error_keeps_focus_in_dialog(e2e_env, world, browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin")
    _company_edit_dialog_by_keyboard(page)
    submit_dialog(page)  # empty reason
    page.wait_for_function(ERROR_TEXT_JS)
    assert page.get_attribute("#workflow_error", "role") == "alert"
    assert "reason" in page.inner_text("#workflow_error").lower()
    assert page.evaluate(IN_DIALOG_JS), "focus lost on error"


def test_A46_server_error_keeps_focus_in_dialog(e2e_env, world, browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin")
    go_to_page(page, "companies")
    open_dialog(page, "companyModal")
    page.fill("#wf_source_id", world.source_id)
    page.fill("#wf_external_ref", e2e_env.raw["companies"]["one"])  # duplicate -> 409
    page.fill("#wf_display_name", "duplicate")
    page.fill("#wf_reason", "A46 server error")
    page.focus(".modalf button.primary")  # where a user's focus is when pressing Submit
    submit_dialog(page)
    page.wait_for_function(ERROR_TEXT_JS)
    assert "Conflict" in page.inner_text("#workflow_error")
    assert page.evaluate(IN_DIALOG_JS), "focus fell to <body> after a server-side error"


def test_A46_route_change_does_not_lose_focus(e2e_env, world, browser_login):
    world.need("source")
    page = browser_login("platform_admin")
    tab_to(page, '.nav button[data-page="sources"]')
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('.nav button.active')?.dataset.page "
                           "=== 'sources'")
    page.wait_for_selector(".content .loading", state="detached")
    focused = page.evaluate(DESCRIBE_JS)
    assert page.evaluate("() => document.activeElement !== document.body"), (
        f"focus was lost to <body> after a route change (activeElement={focused!r})")


# --------------------------------------------------------------------------------------- A47
def test_A47_two_hundred_percent_zoom_keeps_content_and_function(e2e_env, world, browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin", viewport={"width": 640, "height": 360},
                         device_scale_factor=2)
    assert page.evaluate("() => [innerWidth, devicePixelRatio]") == [640, 2]
    for key, title in PAGES.items():
        click_page(page, key)
        settled(page)
        assert page.inner_text(".content h1") == title
        layout = page.evaluate(LAYOUT_JS)
        assert not layout["bad"], f"{key}: clipped controls at 200%: {layout['bad']}"
        assert layout["scrollWidth"] <= layout["vw"] + 1, (
            f"{key}: horizontal page scroll at 200% ({layout})")
        shot(page, f"A47-zoom200-{key}")
    click_page(page, "access")
    settled(page)
    open_dialog(page, "grantModal")
    for selector in ("#wf_principal_id", "#wf_reason", ".modalf button.primary"):
        box = page.locator(selector)
        box.scroll_into_view_if_needed()
        assert box.is_visible() and box.bounding_box()["x"] >= 0, f"{selector} unusable at 200%"
    shot(page, "A47-zoom200-dialog")
    page.keyboard.press("Escape")
    page.wait_for_selector(".modal", state="detached")


# --------------------------------------------------------------------------------------- A48
def test_A48_four_hundred_pixel_viewport_has_no_horizontal_page_scroll(e2e_env, world,
                                                                       browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin", viewport={"width": 400, "height": 800})
    for key, title in PAGES.items():
        click_page(page, key)
        settled(page)
        assert page.inner_text(".content h1") == title
        layout = page.evaluate(LAYOUT_JS)
        assert layout["scrollWidth"] <= layout["vw"] + 1, (
            f"{key}: horizontal page scroll at 400px ({layout})")
        assert not layout["bad"], f"{key}: controls outside the 400px viewport: {layout['bad']}"
        shot(page, f"A48-narrow-{key}")
    click_page(page, "companies")
    settled(page)
    open_dialog(page, "companyModal")
    layout = page.evaluate(LAYOUT_JS)
    assert layout["scrollWidth"] <= layout["vw"] + 1 and not layout["bad"], layout
    shot(page, "A48-narrow-dialog")


# --------------------------------------------------------------------------------------- A49
def test_A49_loading_state_is_distinct(e2e_env, world, browser_login):
    world.need("source", "company_one")
    page = browser_login("platform_admin")
    held = []
    pattern = re.compile(r"/admin/v1/companies(\?|$)")
    page.route(pattern, lambda route: held.append(route))
    page.click('.nav button[data-page="companies"]')
    page.wait_for_selector("#root [role=status].loading")
    text = page.inner_text("#root [role=status].loading")
    assert "Loading" in text, text
    shot(page, "A49-loading")
    wait_until(lambda: held, timeout=10, interval=0.2, what="companies request to be held")
    for route in held:
        route.continue_()
    page.unroute(pattern)
    page.wait_for_selector(".content table")
    assert "Loading" not in page.inner_text("#root")


def test_A49_empty_state_is_text_not_colour(e2e_env, world, browser_login):
    world.need("source")
    page = browser_login("platform_admin")
    page.route(re.compile(r"/admin/v1/companies(\?|$)"), lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"items": [], "limit": 50, "offset": 0, "next_offset": null}'))
    click_page(page, "companies")
    page.wait_for_selector("td.empty")
    assert page.inner_text("td.empty") == "No records"
    assert "0 records" in page.inner_text(".cardhead small")
    shot(page, "A49-empty")


def _break_sources(page):
    pattern = re.compile(r"/admin/v1/sources(\?|$)")
    page.route(pattern, lambda route: route.fulfill(
        status=500, content_type="application/json",
        body='{"error": "ADMIN_DEPENDENCY_UNAVAILABLE"}'))
    click_page(page, "sources")
    page.wait_for_selector("[role=alert]")
    return pattern


def test_A49_error_state_has_alert_text(e2e_env, world, browser_login):
    world.need("source")
    page = browser_login("platform_admin")
    _break_sources(page)
    text = page.inner_text("[role=alert]")
    assert "Dependency unavailable" in text and "ADMIN_DEPENDENCY_UNAVAILABLE" in text, text
    assert page.get_by_text("Retry").is_visible()
    shot(page, "A49-error")


def test_A49_error_state_retry_recovers(e2e_env, world, browser_login):
    world.need("source")
    page = browser_login("platform_admin")
    pattern = _break_sources(page)
    page.unroute(pattern)
    page.get_by_text("Retry").click()
    page.wait_for_selector(".content table", timeout=5000)
    assert page.locator("[role=alert]").count() == 0


def test_A49_forbidden_state_is_explicit(e2e_env, world, browser_login):
    world.need("roles")
    page = browser_login("source_admin")
    click_page(page, "access")
    page.wait_for_selector("[role=alert]")
    text = page.inner_text("[role=alert]")
    assert "Forbidden" in text and "PLATFORM_ROLE_DENIED" in text, text
    shot(page, "A49-403")
    nobody = browser_login("admin_no_role")
    assert "Access forbidden" in nobody.inner_text("#root")
    assert "PLATFORM_ROLE_DENIED" in nobody.inner_text("[role=alert]")
    shot(nobody, "A49-403-no-role")


def test_A49_conflict_and_stale_version_states(e2e_env, world, evidence, browser_login):
    world.need("source", "company_one")
    pa = world.pa
    page = browser_login("platform_admin")
    # 409 from a duplicate registration.
    click_page(page, "companies")
    settled(page)
    open_dialog(page, "companyModal")
    page.fill("#wf_source_id", world.source_id)
    page.fill("#wf_external_ref", e2e_env.raw["companies"]["one"])
    page.fill("#wf_display_name", "duplicate")
    page.fill("#wf_reason", "A49 409")
    submit_dialog(page)
    page.wait_for_function(ERROR_TEXT_JS)
    conflict = page.inner_text("#workflow_error")
    assert "Conflict" in conflict, conflict
    shot(page, "A49-409")
    page.keyboard.press("Escape")
    page.wait_for_selector(".modal", state="detached")

    # Stale row version: another writer bumps the version while the dialog is open.
    name = unique("A49 stale company")
    created = expect(pa.post("/admin/v1/companies", {
        "source_id": world.source_id, "external_ref": unique("e2e-a49"), "display_name": name,
        "reason": "A49 stale"}), 201, "A49 scratch company")
    click_page(page, "companies")
    settled(page)
    row_button(page, name, "Edit / disable").click()
    page.wait_for_selector(".modal")
    expect(pa.patch(f"/admin/v1/companies/{created.body['id']}", {
        "expected_version": 1, "display_name": name + " (changed elsewhere)", "enabled": True,
        "is_default": False, "reason": "A49 concurrent writer"}), 200, "A49 concurrent update")
    page.fill("#wf_reason", "A49 stale submit")
    submit_dialog(page)
    page.wait_for_function(ERROR_TEXT_JS)
    stale = page.inner_text("#workflow_error")
    assert "Conflict" in stale, stale
    shot(page, "A49-stale-version")
    stored = evidence.one("SELECT display_name, row_version FROM bag.companies WHERE "
                          "company_id=$1", uuid.UUID(created.body["id"]))
    assert stored["display_name"].endswith("(changed elsewhere)") and stored["row_version"] == 2, (
        f"stale submit overwrote the concurrent update: {stored}")


def test_A49_stale_session_shows_sign_in_not_data(e2e_env, world, browser_login):
    world.need("source")
    page = browser_login("platform_admin")
    page.context.clear_cookies()
    page.click('.nav button[data-page="sources"]')
    page.wait_for_selector(".loginbox")
    assert page.locator('a[href="/admin/login"]').is_visible()
    assert "Sign in with OIDC" in page.inner_text(".loginbox")
    assert world.source_id not in page.inner_text("body"), "protected data visible without session"
    shot(page, "A49-stale-session")
