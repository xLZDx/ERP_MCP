"""S17-05 authenticated workbench journey against the disposable local Admin stack."""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import pytest
from admin_support import expect

pytestmark = [pytest.mark.admin]


def _assert_loopback(url: str) -> None:
    host = urlparse(url).hostname
    assert host in {"127.0.0.1", "localhost", "::1"}, f"refusing non-local E2E target: {host!r}"


def _wait_for_admin_ready(page) -> None:
    """The login fixture's `.content` selector can match the initial Loading shell."""
    page.locator(".head h1").wait_for()
    page.locator("#root .loading").wait_for(state="detached")


def _wait_for_intake(page) -> None:
    page.locator("#intake_manual, .content [role='alert']").wait_for()
    if page.locator("#intake_manual").count() == 0:
        pytest.fail("Intake preview could not render: " + page.locator(".content [role='alert']").inner_text())


def test_S17_authenticated_company_scoped_review_preview(
        e2e_env, world, evidence, browser_login, request):
    """Exercise real OIDC, company allow/deny, bytes-only upload and review-only output."""
    for url in (e2e_env.gateway, e2e_env.idp_url, e2e_env.fake1c_url):
        _assert_loopback(url)

    world.need("source", "company_one", "company_two")
    company_one = world.company_id("one")
    company_two = world.company_id("two")
    grant = expect(world.scratch_grant(
        world.pa, principal=world.sub("platform_admin"), company=company_one,
    ), 201, "grant preview access to only company one")

    def cleanup_grant():
        row = world.grant_row(grant.body["id"])
        if row is not None and row["revoked_at"] is None:
            expect(world.revoke_grant(world.pa, grant.body["id"], version=row["row_version"]),
                   200, "revoke synthetic preview grant during teardown")

    request.addfinalizer(cleanup_grant)
    before = evidence.snapshot()

    page = browser_login("platform_admin")
    _wait_for_admin_ready(page)
    page.locator('.nav button[data-page="intake"]').click()
    _wait_for_intake(page)
    page.locator("#intake_source").select_option(world.source_id)
    page.locator("#intake_company").select_option(company_one)

    injected_value = '<img src=x onerror="window.__s17_xss=1">'
    page.locator("#intake_manual").fill(json.dumps([
        {"key": "invoice_number", "value": injected_value},
    ]))
    page.get_by_role("button", name="Prepare manual preview").click()
    page.get_by_role("status").filter(has_text="MANUAL_VALUES_REVIEW_REQUIRED").wait_for()
    manual_output = page.locator("#intake_result")
    assert injected_value in manual_output.inner_text()
    assert manual_output.locator("img").count() == 0, "manual value was interpreted as markup"
    assert page.evaluate("window.__s17_xss === undefined")
    assert "UNCLASSIFIED" in manual_output.inner_text()
    assert "Proposal allowed: no." in manual_output.inner_text()
    assert "Apply allowed: no." in manual_output.inner_text()
    assert evidence.snapshot() == before, "manual preview changed persistent business state"

    page.locator("#intake_company").select_option(company_two)
    page.get_by_role("button", name="Prepare manual preview").click()
    denied = page.get_by_role("status")
    denied.get_by_text("You cannot preview data for this company.").wait_for()
    assert evidence.snapshot() == before, "foreign-company denial changed persistent business state"

    page.locator("#intake_company").select_option(company_one)
    page.locator("#intake_format").select_option("csv")
    csv_bytes = b"invoice_number,amount\nINV-S17-E2E,12.50\n"
    hostile_name = "../../outside-sentinel.csv"
    page.locator("#intake_file").set_input_files({
        "name": hostile_name, "mimeType": "text/csv", "buffer": csv_bytes,
    })
    with page.expect_request(re.compile(r"/admin/v1/intake/preview\?")) as request_info:
        page.get_by_role("button", name="Prepare review preview").click()
    upload_request = request_info.value
    assert upload_request.method == "POST"
    assert upload_request.headers.get("content-type") == "application/octet-stream"
    assert hostile_name not in upload_request.url
    assert upload_request.post_data_buffer == csv_bytes

    rendered = page.locator("#intake_result")
    rendered.get_by_text("INV-S17-E2E").wait_for()
    result_text = rendered.inner_text()
    assert "12.50" in result_text
    assert "REVIEW_REQUIRED" in result_text
    assert "UNCLASSIFIED" in result_text
    assert "Proposal allowed: no." in result_text
    assert "Apply allowed: no." in result_text
    assert hostile_name not in result_text
    assert evidence.snapshot() == before, "file preview changed persistent business state"

    page.locator("#intake_file").set_input_files({
        "name": "ordinary.csv", "mimeType": "text/csv", "buffer": csv_bytes,
    })
    with page.expect_request(re.compile(r"/admin/v1/intake/preview\?")):
        page.get_by_role("button", name="Prepare review preview").click()
    rendered.get_by_text("INV-S17-E2E").wait_for()
    assert rendered.inner_text() == result_text, "filename metadata changed the parsed byte result"
    assert evidence.snapshot() == before


def _change(change_id: str) -> dict[str, str]:
    return {
        "change_id": change_id,
        "kind": "SYNTHETIC_PREVIEW",
        "lifecycle": "PENDING",
        "authorization_state": "NONE",
        "execution_state": "NONE",
        "verification_state": "NOT_RUN",
        "updated_at": "2026-11-19T10:00:00Z",
    }


def test_S17_change_status_retry_paging_and_detail_are_get_only(
        e2e_env, world, browser_login):
    """Exercise the read-only change-status UI with a synthetic ledger response."""
    for url in (e2e_env.gateway, e2e_env.idp_url):
        _assert_loopback(url)

    world.need("source", "company_one", "company_two")
    company_one = world.company_id("one")
    page = browser_login("platform_admin")
    _wait_for_admin_ready(page)
    calls: list[tuple[str, str]] = []
    list_attempts = 0

    def ledger_response(route):
        nonlocal list_attempts
        request_info = route.request
        calls.append((request_info.method, request_info.url))
        parsed = urlparse(request_info.url)
        parts = parsed.path.rstrip("/").split("/")
        if request_info.method != "GET":
            route.fulfill(status=405, json={"error": "GET_ONLY"})
            return
        if len(parts) >= 2 and parts[-2] == "changes":
            change_id = parts[-1]
            route.fulfill(status=200, json={
                "change_id": change_id,
                "kind": "SYNTHETIC_PREVIEW",
                "lifecycle": "PENDING",
                "authorization": "NONE",
                "execution": "NONE",
                "verification": "NOT_RUN",
            })
            return
        list_attempts += 1
        if list_attempts == 1:
            route.fulfill(status=503, json={"error": "SYNTHETIC_LEDGER_UNAVAILABLE"})
            return
        offset = int(dict(pair.split("=", 1) for pair in parsed.query.split("&") if "=" in pair)
                     .get("offset", "0"))
        items = ([_change(f"S17-PAGE-{index:03d}") for index in range(100)]
                 if offset == 0 else [_change("S17-PAGE-100")])
        route.fulfill(status=200, json={"items": items})

    page.route("**/admin/v1/companies/*/changes**", ledger_response)
    page.locator('.nav button[data-page="changes"]').click()
    company = page.get_by_label("Registered company")
    company.wait_for()
    company.select_option(company_one)
    page.get_by_role("alert").filter(has_text="SYNTHETIC_LEDGER_UNAVAILABLE").wait_for()

    retry = page.get_by_role("button", name="Retry read")
    retry.focus()
    retry.press("Enter")
    page.get_by_role("button", name="View status for change S17-PAGE-000").wait_for()
    assert "100 records" in page.locator("#changes_list").inner_text()
    assert page.locator("#changes_paging").get_by_role("button", name="Next").count() == 1

    page.locator("#changes_paging").get_by_role("button", name="Next").click()
    page.get_by_role("button", name="View status for change S17-PAGE-100").wait_for()
    assert "Offset 100" in page.locator("#changes_paging").inner_text()

    detail_button = page.get_by_role("button", name="View status for change S17-PAGE-100")
    detail_button.focus()
    detail_button.press("Enter")
    page.locator("#change_detail").get_by_text("S17-PAGE-100").wait_for()
    assert "PENDING" in page.locator("#change_detail").inner_text()
    assert all(method == "GET" for method, _ in calls), calls
    assert list_attempts == 3, calls


def test_S17_change_status_drops_a_stale_response_after_company_switch(
        e2e_env, world, browser_login):
    """A delayed company-one response cannot replace the selected company's result."""
    for url in (e2e_env.gateway, e2e_env.idp_url):
        _assert_loopback(url)

    world.need("source", "company_one", "company_two")
    company_one = world.company_id("one")
    company_two = world.company_id("two")
    page = browser_login("platform_admin")
    _wait_for_admin_ready(page)
    page.locator('.nav button[data-page="changes"]').click()
    company = page.get_by_label("Registered company")
    company.wait_for()

    page.evaluate("""([one, two]) => {
      const originalFetch = window.fetch.bind(window);
      window.__s17Calls = [];
      window.__s17AStarted = false;
      window.__s17ACompleted = false;
      let releaseA;
      const delayedA = new Promise(resolve => { releaseA = resolve; });
      window.__s17ReleaseA = releaseA;
      window.fetch = async (input, init = {}) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        const method = String(init.method || 'GET').toUpperCase();
        if (url.pathname.endsWith(`/admin/v1/companies/${one}/changes`)) {
          window.__s17Calls.push({method, company: one});
          window.__s17AStarted = true;
          await delayedA;
          window.__s17ACompleted = true;
          return new Response(JSON.stringify({items: [{
            change_id: 'S17-STALE-COMPANY-ONE', kind: 'SYNTHETIC', lifecycle: 'PENDING',
            authorization_state: 'NONE', execution_state: 'NONE',
            verification_state: 'NOT_RUN', updated_at: '2026-11-19T10:00:00Z'
          }]}), {status: 200, headers: {'Content-Type': 'application/json'}});
        }
        if (url.pathname.endsWith(`/admin/v1/companies/${two}/changes`)) {
          window.__s17Calls.push({method, company: two});
          return new Response(JSON.stringify({items: [{
            change_id: 'S17-CURRENT-COMPANY-TWO', kind: 'SYNTHETIC', lifecycle: 'PENDING',
            authorization_state: 'NONE', execution_state: 'NONE',
            verification_state: 'NOT_RUN', updated_at: '2026-11-19T10:00:00Z'
          }]}), {status: 200, headers: {'Content-Type': 'application/json'}});
        }
        return originalFetch(input, init);
      };
    }""", [company_one, company_two])

    company.select_option(company_one)
    page.wait_for_function("window.__s17AStarted === true")
    company.select_option(company_two)
    page.get_by_role("button", name="View status for change S17-CURRENT-COMPANY-TWO").wait_for()
    page.evaluate("window.__s17ReleaseA()")
    page.wait_for_function("window.__s17ACompleted === true")
    page.evaluate("""async () => {
      await new Promise(requestAnimationFrame);
      await new Promise(requestAnimationFrame);
    }""")

    current_list = page.locator("#changes_list").inner_text()
    assert "S17-CURRENT-COMPANY-TWO" in current_list
    assert "S17-STALE-COMPANY-ONE" not in current_list
    assert page.get_by_label("Registered company").input_value() == company_two
    assert page.evaluate("window.__s17Calls.every(call => call.method === 'GET')")

