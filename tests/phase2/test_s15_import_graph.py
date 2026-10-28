"""S15 epic E15-2 assertion 2: oracle and verifier are import-independent (ast import walk).

The walk covers every import statement at any nesting depth (including function-local and
conditional ones), dynamic imports by string, and the transitive closure inside erp_mcp_s15.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = "erp_mcp_s15"
PKG_DIR = Path(__file__).resolve().parents[2] / "src" / PACKAGE
FORBIDDEN_ROOTS = ("erp_mcp_private_writer", "business_ai_gateway")
FORBIDDEN_WORDS = ("preview", "normaliz")  # matched against every dotted segment, lower-cased
STDLIB = set(sys.stdlib_module_names)


def imported_modules(source: str, module_name: str) -> set[str]:
    """Absolute dotted names of everything the source imports (relative imports resolved)."""
    package = module_name.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".")
                base_parts = base_parts[: len(base_parts) - (node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"}:
                found.add("<dynamic-import>")
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add(arg.value)
    return found


def violations(names: set[str]) -> list[str]:
    bad: list[str] = []
    for name in sorted(names):
        parts = name.lower().split(".")
        if name == "<dynamic-import>" or parts[0] in FORBIDDEN_ROOTS or any(word in part for part in parts for word in FORBIDDEN_WORDS):
            bad.append(name)
    return bad


def closure(module: str) -> dict[str, set[str]]:
    """Imports of ``module`` and, transitively, of every erp_mcp_s15 module it reaches."""
    seen: dict[str, set[str]] = {}
    todo = [module]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        leaf = current.split(".")[-1]
        source = (PKG_DIR / f"{leaf}.py").read_text(encoding="ascii")
        seen[current] = imported_modules(source, current)
        for name in seen[current]:
            if name.startswith(PACKAGE + ".") and (PKG_DIR / f"{name.split('.')[-1]}.py").exists():
                todo.append(name)
    return seen


# --- the walker itself must be able to fail ------------------------------------------------------

def test_walker_detects_forbidden_imports_in_every_syntactic_form():
    source = (
        "import erp_mcp_private_writer\n"
        "from business_ai_gateway.x import y\n"
        "from . import preview\n"
        "from .normalization import z\n"
        "def f():\n"
        "    import business_ai_gateway.preview_things\n"
        "    import importlib\n"
        "    importlib.import_module('erp_mcp_private_writer.core')\n"
    )
    names = imported_modules(source, "erp_mcp_s15.verifier")
    bad = violations(names)
    assert "erp_mcp_private_writer" in bad
    assert "business_ai_gateway.x" in bad
    assert "erp_mcp_s15.preview" in bad
    assert "erp_mcp_s15.normalization" in bad
    assert "business_ai_gateway.preview_things" in bad
    assert "<dynamic-import>" in bad
    assert "erp_mcp_private_writer.core" in bad


def test_walker_passes_a_clean_source():
    names = imported_modules("import re\nfrom decimal import Decimal\nfrom .oracle import x\n",
                             "erp_mcp_s15.verifier")
    assert violations(names) == []
    assert "erp_mcp_s15.oracle" in names


# --- the real modules ---------------------------------------------------------------------------------

@pytest.mark.parametrize("module", ["oracle", "verifier"])
def test_module_and_its_transitive_closure_import_no_forbidden_module(module):
    graph = closure(f"{PACKAGE}.{module}")
    assert f"{PACKAGE}.{module}" in graph
    offenders = {mod: violations(names) for mod, names in graph.items() if violations(names)}
    assert offenders == {}


@pytest.mark.parametrize("module", ["oracle", "verifier"])
def test_module_imports_only_stdlib_or_s15_siblings(module):
    names = imported_modules((PKG_DIR / f"{module}.py").read_text(encoding="ascii"),
                             f"{PACKAGE}.{module}")
    foreign = {n for n in names
               if n.split(".")[0] not in STDLIB and not n.startswith(PACKAGE)}
    assert foreign == set()


def test_oracle_imports_no_other_s15_module():
    names = imported_modules((PKG_DIR / "oracle.py").read_text(encoding="ascii"),
                             f"{PACKAGE}.oracle")
    assert {n for n in names if n.startswith(PACKAGE)} == set()


def test_verifier_reaches_only_labels_oracle_and_read_interface():
    graph = closure(f"{PACKAGE}.verifier")
    assert set(graph) == {f"{PACKAGE}.{m}" for m in ("verifier", "oracle", "labels",
                                                      "read_interface")}


def test_private_writer_and_gateway_packages_exist_so_the_check_is_meaningful():
    src = PKG_DIR.parent
    assert (src / "erp_mcp_private_writer").is_dir()
    assert (src / "business_ai_gateway").is_dir()


def test_loaded_modules_do_not_pull_in_the_writer_or_gateway():
    import subprocess

    code = (
        f"import sys; sys.path[:0] = [{str(PKG_DIR.parent)!r}]; "
        "import erp_mcp_s15.oracle, erp_mcp_s15.verifier; "
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "('erp_mcp_private_writer', 'business_ai_gateway')]; "
        "print(bad)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == "[]"
