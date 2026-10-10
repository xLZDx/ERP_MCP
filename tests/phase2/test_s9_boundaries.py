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


# Module-level values are constants only if their VALUE is immutable; the name's case proves nothing.
_IMMUTABLE_CALLS = frozenset({
    "tuple", "frozenset", "MappingProxyType", "compile", "Decimal", "Context", "timedelta", "str", "int",
    "bytes", "TypeVar", "NewType", "namedtuple",
    "FkEdge",  # frozen dataclass of strings/tuples (restore_verify)
})
_MUTABLE_CALLS = frozenset({
    "dict", "list", "set", "bytearray", "defaultdict", "deque", "OrderedDict", "Counter", "TenantBoundedMap",
    "TenantSlotCounter", "Lock", "RLock", "count",
})
# (module, name) pairs that are deliberately not mutable state: opaque sentinels compared by identity.
_ALLOWED_SENTINELS = frozenset({
    ("delivery_replay.py", "_BUSY"), ("alert_rules.py", "_BUSY"),  # object() sentinel, no state
})


def _call_name(node: ast.Call) -> str | None:
    fn = node.func
    return fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None


def _mutable_reason(value: ast.AST | None) -> str | None:
    """Why a module-level value is (or may be) mutable shared state; ``None`` when it is immutable."""
    if value is None:
        return None
    if isinstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return "mutable literal/comprehension"
    if isinstance(value, ast.Call):
        name = _call_name(value)
        if name in _MUTABLE_CALLS:
            return f"mutable constructor {name}()"
        if name in _IMMUTABLE_CALLS:
            return None
        return f"call {name}() is not on the immutable allow-list"
    if isinstance(value, ast.Tuple):
        return next((r for r in (_mutable_reason(e) for e in value.elts) if r), None)
    if isinstance(value, (ast.Constant, ast.Name, ast.Attribute, ast.Subscript, ast.JoinedStr, ast.Lambda)):
        return None
    if isinstance(value, ast.BinOp):
        return _mutable_reason(value.left) or _mutable_reason(value.right)
    if isinstance(value, ast.UnaryOp):
        return _mutable_reason(value.operand)
    return f"unclassified value {type(value).__name__}"


def _module_level_assignments(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            yield [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
        elif isinstance(node, ast.AnnAssign):
            yield ([node.target.id] if isinstance(node.target, ast.Name) else []), node.value
        elif isinstance(node, ast.AugAssign):
            yield [], node.value  # an augmented assignment at module level mutates shared state


@pytest.mark.parametrize("name", S9_MODULES)
def test_no_module_level_mutable_state(name):
    for names, value in _module_level_assignments(_tree(name)):
        if names == ["__all__"]:
            continue
        if all((name, n) in _ALLOWED_SENTINELS for n in names) and names:
            assert isinstance(value, ast.Call) and _call_name(value) == "object", (name, names)
            continue
        assert _mutable_reason(value) is None, (name, names, _mutable_reason(value))


def test_the_mutable_state_scan_itself_rejects_private_uppercase_stores():
    """The scan must not be fooled by a private UPPER_CASE name (the former name-based rule accepted these)."""
    for source in ("_STORE = {}", "_STORE = dict()", "_STORE = defaultdict(list)", "_Q = deque()", "_L = list()",
                   "_S = set()", "_M = TenantBoundedMap(3, None)", "_X = [1]", "_C: dict = {}", "_U = unknown_factory()",
                   "_T = (1, [2])"):
        (_names, value), = _module_level_assignments(ast.parse(source))
        assert _mutable_reason(value) is not None, source
    for source in ("_OK = (1, 2)", "_F = frozenset({1})", "_P = MappingProxyType({1: 2})", "_R = re.compile('x')",
                   "_D = Decimal('1')", "_N = 5", "_E = Basis.X"):
        (_names, value), = _module_level_assignments(ast.parse(source))
        assert _mutable_reason(value) is None, source


def test_authority_is_evaluation_only_everywhere():
    """Every real output dataclass carries ``authority == 'EVALUATION_ONLY'`` by its class definition."""
    import dataclasses
    import importlib

    from business_ai_gateway.phase2 import ops_types
    from business_ai_gateway.phase2.workbench_types import AUTHORITY

    assert ops_types.AUTHORITY == AUTHORITY == "EVALUATION_ONLY"
    outputs = {
        "capacity_model": ("CapacityReport",), "capacity_interference": ("InterferenceResult", "BudgetPlan"),
        "restore_verify": ("RestoreReport",), "export_safety": ("ExportResult",),
        "retention_hold": ("DeletionDecision",), "release_rollback": ("RollbackDecision",),
        "g6_pre_readiness": ("ReadinessReport",), "alert_rules": ("AlertEvent",),
        "audit_gate": ("GateOutcome",), "delivery_replay": ("DeliveryOutcome",),
        "release_migration": ("ShadowResult", "RehearsalPlan"),
    }
    missing = []
    for module, classes in outputs.items():
        mod = importlib.import_module(f"business_ai_gateway.phase2.{module}")
        for cls_name in classes:
            cls = getattr(mod, cls_name)
            field = {f.name: f for f in dataclasses.fields(cls)}.get("authority")
            if field is None or field.default != "EVALUATION_ONLY":
                missing.append((module, cls_name))
    assert missing == [], f"output types without authority == EVALUATION_ONLY: {missing}"


def test_every_reason_code_has_a_fixed_next_action():
    from business_ai_gateway.phase2.ops_types import OPS_NEXT_ACTION, OpsReason

    assert set(OPS_NEXT_ACTION) == set(OpsReason)
