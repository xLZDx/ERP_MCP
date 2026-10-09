"""S6b E5 boundary tests (REQ21): the two S6b modules are pure (no Release 1, network, file or DB
access) and the reserved capability ``ap.account_based`` is still refused after S6b.

STATIC PROXY: an AST scan of imports, calls and attributes. It guards the obvious write/IO paths; it
does not prove absence of aliasing, getattr or indirect calls. Offline-fixture coverage only.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import ap_account_strategy, posted_receipts
from business_ai_gateway.phase2.validation_coverage import (
    Claim,
    ClaimScope,
    CoverageCode,
    CoverageStatus,
    Evidence,
    EvidenceVerdict,
    Link,
    build_matrix,
    capability_enabled,
)

STDLIB_OK = {
    "__future__", "dataclasses", "enum", "hashlib", "json", "datetime", "decimal", "typing",
    "collections", "functools",
}
# absolute imports: the stdlib allow-list above, or a submodule of collections.abc
RELATIVE_OK = {
    "_identity", "purchase_reconciliation", "reconciliation", "aliases", "comparison_snapshot",
}
BANNED_CALLS = {"open", "exec", "eval", "compile", "__import__", "input"}
BANNED_ATTRS = {
    "write_text", "write_bytes", "open", "execute", "executemany", "commit", "import_module",
    "connect", "urlopen", "request", "send", "sendall", "post", "put", "delete",
}
MODULES = [ap_account_strategy, posted_receipts]
IDS = [m.__name__.rsplit(".", 1)[-1] for m in MODULES]


def _tree(mod) -> ast.AST:
    return ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(0, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.level, node.module or ""))
    return found


@pytest.mark.parametrize("mod", MODULES, ids=IDS)
def test_modules_import_only_stdlib_pure_and_phase2_sibling_modules(mod):
    imports = _imports(_tree(mod))
    assert imports, "scan found no imports: the scanner would be vacuous"
    for level, name in imports:
        if level == 0:
            assert name.split(".")[0] in STDLIB_OK, name
        else:
            assert level == 1 and name in RELATIVE_OK, (level, name)


@pytest.mark.parametrize("mod", MODULES, ids=IDS)
def test_modules_have_no_io_or_write_primitives(mod):
    tree = _tree(mod)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & BANNED_CALLS
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & BANNED_ATTRS
    assert "validation_coverage" not in {name for _, name in _imports(tree)}


def test_scanner_would_flag_a_forbidden_import():
    # sanity check of the instrument itself: a hostile snippet must be rejected by the same rules
    tree = ast.parse("import sqlite3\nfrom ..src import release1\nopen('x')\n")
    bad = [(lv, n) for lv, n in _imports(tree)
           if (lv == 0 and n.split(".")[0] not in STDLIB_OK) or (lv != 0 and n not in RELATIVE_OK)]
    assert len(bad) == 2
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", "") in BANNED_CALLS
               for n in ast.walk(tree))


# ---------------------------------------------------------------- ap.account_based stays refused
def _h(n: int) -> str:
    return f"{n:064x}"


def test_validation_coverage_still_refuses_ap_account_based_after_s6b():
    scope = ClaimScope("t1", "companyA")
    claims = (Claim("c1", scope, "purchases", "validate"), Claim("c2", scope, "ap.account_based", "validate"))
    evidence = (Evidence("e1", scope, "s1", _h(1), EvidenceVerdict.PASS),
                Evidence("e2", scope, "s2", _h(2), EvidenceVerdict.PASS))
    result = build_matrix(claims, evidence, (Link("c1", "e1"), Link("c2", "e2")))
    assert result.status is CoverageStatus.REFUSED
    assert result.code is CoverageCode.CAPABILITY_NOT_OPENED
    assert not capability_enabled(result, scope, "ap.account_based")
    assert not capability_enabled(result, scope, "purchases")


def test_purchases_pass_evidence_does_not_open_ap_and_s6b_modules_expose_no_capability_api():
    scope = ClaimScope("t1", "companyA")
    ok = build_matrix((Claim("c1", scope, "purchases", "validate"),),
                      (Evidence("e1", scope, "s1", _h(1), EvidenceVerdict.PASS),), (Link("c1", "e1"),))
    assert ok.accepted and capability_enabled(ok, scope, "purchases")
    assert not capability_enabled(ok, scope, "ap.account_based")
    for mod in MODULES:
        assert not hasattr(mod, "capability_enabled") and not hasattr(mod, "build_matrix")
