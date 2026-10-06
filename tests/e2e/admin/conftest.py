"""Fixtures for the Admin Control Center E2E suite (A01-A54).

Builds on ``tests/e2e/conftest.py`` (``e2e_env``, ``idp``, ``db``, ``_playwright``). The suite
runs against seed mode ``bootstrap-only``: everything except the single initial PLATFORM_ADMIN is
created through ``/admin/`` by the ``world`` fixture, which fails loudly (never skips) when the
environment is not pristine.
"""

from __future__ import annotations

import re

import pytest
from admin_support import Evidence, World, pace_api, pace_login


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "/e2e/admin/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.admin)


@pytest.fixture(scope="session")
def evidence(db) -> Evidence:
    return Evidence(db)


@pytest.fixture(scope="session")
def world(e2e_env, evidence, idp):
    instance = World(e2e_env, evidence, idp)
    yield instance
    instance.close()


@pytest.fixture
def browser_login(e2e_env, _playwright):
    """``browser_login(user, step_up=False, **context_options)`` -> logged-in Playwright page.

    Uses the real IdP login form. Context options (viewport, device_scale_factor, ...) pass
    through to ``browser.new_context``. Every context is closed at teardown.
    """
    contexts = []

    def login(user: str, *, step_up: bool = False, wait_app: bool = True, **options):
        pace_login()
        pace_api(user, 8)
        context = _playwright.new_context(**options)
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(20_000)
        page.goto(f"{e2e_env.gateway}/admin/login{'?step_up=1' if step_up else ''}")
        page.fill("#username", user)
        page.fill("#password", e2e_env.password(user))
        page.click("#login-submit")
        page.wait_for_url(re.compile(r".*/admin/?$"))
        if wait_app:
            page.wait_for_selector(".content, .loginbox")
        return page

    yield login
    for context in contexts:
        context.close()


@pytest.fixture
def browser_context(_playwright):
    """Raw new-context factory (no login) closed at teardown."""
    contexts = []

    def make(**options):
        context = _playwright.new_context(**options)
        contexts.append(context)
        return context

    yield make
    for context in contexts:
        context.close()
