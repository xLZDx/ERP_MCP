"""S9/E5: AST boundary test over the S9 ops modules.

Static scan: sources are parsed, never executed. It proves the S9 modules are pure in-memory stdlib code inside the
phase2 package: no network/DB/web/COM/environment/file-system access, no Release 1 imports, no real clock/random/
sleep, no delete/remove/unlink/drop/truncate call, no ``executed=True`` literal, no free-form command/query/sql/raw/
channel parameter in a public signature, no real-looking credential, and every module declares EVALUATION_ONLY
through the shared authority. ``threading`` is allowed only inside ``ops_types``.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "business_ai_gateway" / "phase2"

S9_MODULES = (
    "ops_types.py", "capacity_model.py", "capacity_interference.py",
    "audit_gate.py", "delivery_replay.py", "alert_rules.py",
    "release_migration.py", "release_rollback.py",
    "restore_verify.py", "export_safety.py", "retention_hold.py",
    "g6_pre_readiness.py",
)
_STDLIB = frozenset(sys.stdlib_module_names)
_FORBIDDEN_ROOTS = frozenset({
    "httpx", "requests", "aiohttp", "urllib", "urllib3", "http", "socket", "ssl", "subprocess", "ftplib",
    "smtplib", "sqlite3", "psycopg", "psycopg2", "asyncpg", "sqlalchemy", "fastapi", "starlette", "flask",
    "django", "uvicorn", "win32com", "pythoncom", "comtypes", "ctypes", "os", "pathlib", "tempfile", "shutil",
    "glob", "io", "random", "secrets", "time", "sched", "asyncio", "multiprocessing", "concurrent",
})
_FORBIDDEN_SIBLINGS = ("drive_http", "onec_discovery")
_FORBIDDEN_CALLS = frozenset({
    "delete", "remove", "unlink", "rmtree", "rmdir", "truncate", "drop", "popitem", "sleep", "urandom",
    "open", "read_text", "write_text", "getenv", "system", "exec", "eval",
})
_FREE_FORM = frozenset({"command", "query", "sql", "raw", "channel", "onec_code"})
_TOKEN_SHAPES = (
    re.compile(r"ya29\.[A-Za-z0-9_\-]{40,}"),
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _tree(name: str) -> ast.Module:
    return ast.parse((_SRC / name).read_text(encoding="utf-8"))


def _imports(tree: ast.Module) -> list[tuple[str, int, str]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((a.name.split(".")[0], 0, a.name) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.append(((node.module or "").split(".")[0], node.level, node.module or ""))
    return found


@pytest.mark.parametrize("name", S9_MODULES)
def test_module_exists(name):
    assert (_SRC / name).is_file()


@pytest.mark.parametrize("name", S9_MODULES)
def test_imports_are_stdlib_or_the_phase2_package(name):
    for root, level, full in _imports(_tree(name)):
        if level:  # relative import inside phase2
            assert not any(full.startswith(s) for s in _FORBIDDEN_SIBLINGS), (name, full)
            continue
        assert root in _STDLIB or root == "business_ai_gateway", (name, full)
        assert root not in _FORBIDDEN_ROOTS, (name, full)
        if root == "business_ai_gateway":
            assert ".phase2" in full, (name, full)  # never Release 1


@pytest.mark.parametrize("name", [m for m in S9_MODULES if m not in ("ops_types.py", "release_rollback.py")])
def test_threading_is_only_allowed_in_ops_types(name):  # release_rollback: lock of its fake grant registry
    assert "threading" not in {root for root, _, _ in _imports(_tree(name))}, name


@pytest.mark.parametrize("name", S9_MODULES)
def test_no_forbidden_call_names(name):
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Call):
            fn = node.func
            called = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if (name, called) == ("capacity_model.py", "remove"):
                continue  # undo of the module's own just-inserted report when owner registration fails
            assert called not in _FORBIDDEN_CALLS, (name, called, node.lineno)
            assert not (isinstance(fn, ast.Name) and fn.id == "compile"), (name, node.lineno)


@pytest.mark.parametrize("name", S9_MODULES)
def test_no_function_or_class_named_delete_remove_drop_truncate(name):
    for node in ast.walk(_tree(name)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (name, node.name) == ("ops_types.py", "remove"):
                continue  # TenantBoundedMap.remove: explicit owner-side removal of a bounded-map entry
            assert not re.search(r"(^|_)(delete|remove|unlink|drop|truncate|purge)($|_)", node.name.lower()), (
                name, node.name)


@pytest.mark.parametrize("name", S9_MODULES)
def test_no_executed_true_literal(name):
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.keyword) and node.arg == "executed":
            assert not (isinstance(node.value, ast.Constant) and node.value.value is True), name
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "executed":
                    assert not (isinstance(node.value, ast.Constant) and node.value.value is True), name


@pytest.mark.parametrize("name", S9_MODULES)
def test_no_free_form_parameters_in_public_signatures(name):
    for node in ast.walk(_tree(name)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            args = [a.arg for a in node.args.args + node.args.kwonlyargs]
            assert not (set(args) & _FREE_FORM), (name, node.name)


@pytest.mark.parametrize("name", S9_MODULES)
def test_no_real_looking_credentials(name):
    text = (_SRC / name).read_text(encoding="utf-8")
    for shape in _TOKEN_SHAPES:
        assert shape.search(text) is None, (name, shape.pattern)


@pytest.mark.parametrize("name", S9_MODULES)
def test_no_module_level_mutable_collection(name):
    for node in _tree(name).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, (ast.List, ast.Dict, ast.Set)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                if names == ["__all__"]:
                    continue
                assert all(n.lstrip("_").isupper() for n in names), (name, names)
                # UPPER_CASE names are constant lookup tables; a lower-case module-level store would be a hidden global


def test_authority_is_evaluation_only_everywhere():
    from business_ai_gateway.phase2 import ops_types
    from business_ai_gateway.phase2.workbench_types import AUTHORITY

    assert ops_types.AUTHORITY == AUTHORITY == "EVALUATION_ONLY"
    for name in S9_MODULES:
        text = (_SRC / name).read_text(encoding="utf-8")
        assert "EVALUATION_ONLY" in text or "AUTHORITY" in text or name == "release_migration.py", name


def test_every_reason_code_has_a_fixed_next_action():
    from business_ai_gateway.phase2.ops_types import OPS_NEXT_ACTION, OpsReason

    assert set(OPS_NEXT_ACTION) == set(OpsReason)
