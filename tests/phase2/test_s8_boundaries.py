"""S8/E5: AST boundary test over the S8 workbench/API modules and their tests.

Static scan: the sources are parsed, never executed (only the ``jobs_api`` endpoint tables are read at
runtime, to prove annotation coverage). It proves the S8 modules are pure in-memory stdlib code that stays
inside the phase2 package, cannot reach the network, a database, a web framework, a COM/1C client, the
environment or the file system, never touch ``drive_http.py``, expose no free-form command/query/sql/raw/
channel input in a decision signature or request type, annotate every public decision endpoint, and carry no
real-looking credential.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "business_ai_gateway" / "phase2"
_TESTS = _ROOT / "tests" / "phase2"

S8_MODULES = (
    "workbench_types.py",
    "workbench_review.py",
    "timeline_view.py",
    "coverage_view.py",
    "safe_errors.py",
    "jobs_api.py",
    "workbench_session.py",
)
S8_TESTS = (
    "test_workbench_types.py",
    "test_workbench_review.py",
    "test_timeline_view.py",
    "test_coverage_view.py",
    "test_safe_errors.py",
    "test_jobs_api.py",
    "test_jobs_api_bypass.py",
    "test_workbench_session.py",
    "test_s8_fix_jobs_api.py",
    "test_s8_fix_review.py",
    "test_s8_fix_views.py",
    "test_s8_fix_session.py",
    "test_s8_boundaries.py",
)

_STDLIB = frozenset(sys.stdlib_module_names)
_NETWORK_DB = frozenset({
    "httpx", "requests", "aiohttp", "urllib", "urllib3", "http", "socket", "ssl", "subprocess",
    "ftplib", "smtplib", "sqlite3", "psycopg", "psycopg2", "asyncpg", "aiosqlite", "sqlalchemy",
    "pymysql", "mysql", "pyodbc", "databases", "websockets", "grpc",
})
_WEB_FRAMEWORKS = frozenset({
    "fastapi", "starlette", "flask", "django", "uvicorn", "tornado", "bottle", "sanic", "pyramid",
    "falcon", "quart", "aiohttp", "werkzeug", "jinja2", "wsgiref", "socketserver", "xmlrpc",
})
_COM_ONEC = frozenset({"win32com", "pythoncom", "pywintypes", "comtypes", "win32api", "win32ui", "wmi", "ctypes"})
_ENV_FILE = frozenset({"os", "pathlib", "tempfile", "shutil", "glob", "fileinput", "dotenv", "io"})
_FILE_METHODS = frozenset({"read_text", "write_text", "read_bytes", "write_bytes", "open", "environ", "getenv"})
_FORBIDDEN_ROOTS = _NETWORK_DB | _WEB_FRAMEWORKS | _COM_ONEC | _ENV_FILE
# Pre-existing phase2 siblings that are readers/clients of an external system.
_FORBIDDEN_SIBLINGS = ("drive_http", "onec_discovery")
_FREE_FORM_NAMES = frozenset({"command", "query", "sql", "raw", "channel", "onec_code"})
# Real token shapes: Google (ya29./1//./GOCSPX-/AIza), GitHub, Slack, AWS access key, JWT, PEM private key.
_REAL_TOKEN_SHAPES = (
    re.compile(r"ya29\.[A-Za-z0-9_\-]{40,}"),
    re.compile(r"(?<![A-Za-z0-9:/])1//[A-Za-z0-9_\-]{40,}"),
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9]{32,}"),
)
# A bare 64-hex string is a sha256 digest by design (canonical digests), so it is not treated as a secret.
_DECISION_PREFIXES = ("decide_", "read_")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(name: str) -> ast.Module:
    return ast.parse(_read(_SRC / name), filename=name)


def _import_records(tree: ast.Module) -> list[tuple[str, int]]:
    """(module path, relative level) for every import; ``from . import x`` yields the imported names."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level and not base:
                out += [(a.name, node.level) for a in node.names]
            else:
                out.append((base, node.level))
                out += [(f"{base}.{a.name}", node.level) for a in node.names]
    return out


def _check_imports(name: str, records: list[tuple[str, int]], *, allow_pytest: bool) -> None:
    assert records, "scan must see imports"
    for mod, level in records:
        low = mod.lower()
        assert "pdcc" not in low and "release1" not in low and "release_1" not in low, (name, mod)
        assert not any(s in low for s in _FORBIDDEN_SIBLINGS), (name, mod)
        root = mod.split(".")[0]
        assert root not in _FORBIDDEN_ROOTS, (name, mod)
        if level == 0:
            if root == "business_ai_gateway":
                # absolute import of this package: only the phase2 subpackage is allowed
                assert mod.startswith("business_ai_gateway.phase2"), (name, mod)
                continue
            if allow_pytest and root == "pytest":
                continue
            assert root in _STDLIB, (name, mod)
        else:
            # exactly one dot = sibling phase2 module; ``..`` would leave phase2 (Release 1 side)
            assert level == 1, (name, mod, level)


def test_every_s8_module_and_test_file_exists_including_workbench_session():
    # workbench_session.py (E4) must exist: this assertion fails loudly if it is missing at sprint end.
    missing = [n for n in S8_MODULES if not (_SRC / n).is_file()]
    assert not missing, missing
    missing_tests = [n for n in S8_TESTS if not (_TESTS / n).is_file()]
    assert not missing_tests, missing_tests
    # pre-existing readers/clients are not S8 modules and are never imported by them
    assert (_SRC / "drive_http.py").is_file()


@pytest.mark.parametrize("name", S8_MODULES)
def test_module_imports_only_stdlib_or_sibling_phase2_and_nothing_forbidden(name):
    _check_imports(name, _import_records(_tree(name)), allow_pytest=False)


@pytest.mark.parametrize("name", [n for n in S8_TESTS if n != "test_s8_boundaries.py"])
def test_s8_test_files_import_no_network_db_framework_com_or_release1(name):
    tree = ast.parse(_read(_TESTS / name), filename=name)
    for mod, level in _import_records(tree):
        low = mod.lower()
        root = mod.split(".")[0]
        assert "pdcc" not in low and "release1" not in low and "release_1" not in low, (name, mod)
        assert not any(s in low for s in _FORBIDDEN_SIBLINGS), (name, mod)
        assert root not in (_NETWORK_DB | _WEB_FRAMEWORKS | _COM_ONEC), (name, mod)
        if level == 0 and root == "business_ai_gateway":
            assert mod.startswith("business_ai_gateway.phase2"), (name, mod)


@pytest.mark.parametrize("name", S8_MODULES)
def test_module_has_no_environment_or_file_io(name):
    tree = _tree(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "__import__", "exec", "eval", "compile"}, (name, node.lineno)
        if isinstance(node, ast.Attribute):
            assert node.attr not in _FILE_METHODS, (name, node.attr, node.lineno)
        if isinstance(node, ast.Name):
            assert node.id not in {"environ", "getenv"}, (name, node.id, node.lineno)


def _all_arg_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    a = fn.args
    names = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return names


def _is_dataclass(cls: ast.ClassDef) -> bool:
    for dec in cls.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if (isinstance(target, ast.Name) and target.id == "dataclass") or (
            isinstance(target, ast.Attribute) and target.attr == "dataclass"
        ):
            return True
    return False


@pytest.mark.parametrize("name", S8_MODULES)
def test_no_free_form_command_query_sql_raw_channel_parameter_or_field(name):
    """No function signature (public or private) and no dataclass/class field carries a free-form input name."""
    tree = _tree(name)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bad = [n for n in _all_arg_names(node) if n.lower() in _FREE_FORM_NAMES]
            assert not bad, (name, node.name, node.lineno, bad)
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    assert stmt.target.id.lower() not in _FREE_FORM_NAMES, (name, node.name, stmt.target.id)
                if isinstance(stmt, ast.Assign):
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name):
                            assert tgt.id.lower() not in _FREE_FORM_NAMES, (name, node.name, tgt.id)
            if _is_dataclass(node):
                fields = [s.target.id for s in node.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
                assert not [f for f in fields if f.lower() in _FREE_FORM_NAMES], (name, node.name)


def _public_decision_functions(tree: ast.Module) -> list[str]:
    return [
        n.name for n in tree.body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_") and n.name.startswith(_DECISION_PREFIXES)
    ]


def test_endpoint_annotation_table_covers_every_public_decision_function():
    from business_ai_gateway.phase2 import jobs_api

    funcs = _public_decision_functions(_tree("jobs_api.py"))
    assert sorted(funcs) == ["decide_enqueue", "decide_rerun", "read_job", "read_result"], funcs
    # every public decision function is mapped to an endpoint, and every mapped endpoint is annotated
    assert set(jobs_api.DECISION_ENDPOINTS) == set(funcs)
    for fn_name, endpoint in jobs_api.DECISION_ENDPOINTS.items():
        assert endpoint in jobs_api.ENDPOINTS, (fn_name, endpoint)
    # every Endpoint member has an annotation and no stray annotation exists
    assert set(jobs_api.ENDPOINTS) == set(jobs_api.Endpoint)
    for endpoint, ann in jobs_api.ENDPOINTS.items():
        assert type(ann.read_only) is bool and type(ann.destructive) is bool
        assert type(ann.idempotent) is bool and type(ann.open_world) is bool
        assert ann.destructive is False and ann.open_world is False, endpoint
        assert ann.idempotent is True, endpoint
    # control mutations are never annotated read-only; reads always are
    for fn_name, endpoint in jobs_api.DECISION_ENDPOINTS.items():
        expect_read_only = fn_name.startswith("read_")
        assert jobs_api.ENDPOINTS[endpoint].read_only is expect_read_only, (fn_name, endpoint)
    for endpoint in (jobs_api.Endpoint.ENQUEUE_JOB, jobs_api.Endpoint.RERUN,
                     jobs_api.Endpoint.PAUSE_SOURCE, jobs_api.Endpoint.REVOKE_ATTESTATION):
        assert jobs_api.ENDPOINTS[endpoint].read_only is False, endpoint


def test_no_decision_function_takes_a_channel_or_a_caller_supplied_status_or_number():
    tree = _tree("jobs_api.py")
    forbidden = _FREE_FORM_NAMES | {"status", "verdict", "state", "validated", "amount", "delta", "numbers"}
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in {"decide_enqueue", "decide_rerun", "read_job", "read_result"}:
            assert not [a for a in _all_arg_names(fn) if a.lower() in forbidden], fn.name


def test_review_workbench_surface_has_no_number_or_verdict_parameter():
    tree = _tree("workbench_review.py")
    forbidden = {"status", "verdict", "state", "validated", "native_values", "gateway_values", "delta", "amount"}
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in {"build_cards", "request_rerun", "verify_original"}:
            assert not [a for a in _all_arg_names(fn) if a.lower() in forbidden], fn.name


def _scanned_files() -> list[Path]:
    files = [_SRC / n for n in S8_MODULES]
    files += [_TESTS / n for n in S8_TESTS if (_TESTS / n).is_file()]
    return files


@pytest.mark.parametrize("path", _scanned_files(), ids=lambda p: p.name)
def test_no_real_token_looking_literal_in_source_or_tests(path):
    tree = ast.parse(_read(path), filename=path.name)
    seen = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            seen += 1
            for shape in _REAL_TOKEN_SHAPES:
                assert not shape.search(node.value), (path.name, node.lineno, shape.pattern)
    assert seen > 0


def test_token_shape_detector_is_not_vacuous():
    # The detector must fire on real-looking shapes and stay quiet on the FAKE- convention.
    real = [
        "ya29." + "a" * 60, "1//" + "b" * 60, "GOCSPX-" + "c" * 20, "AIza" + "d" * 35,
        "ghp_" + "e" * 36, "xoxb-" + "1" * 24, "AKIA" + "Q" * 16,
        "eyJ" + "h" * 12 + ".eyJ" + "p" * 12 + "." + "s" * 12,
        "-----BEGIN " + "RSA PRIVATE KEY-----", "sk-" + "f" * 40,
    ]
    for text in real:
        assert any(s.search(text) for s in _REAL_TOKEN_SHAPES), text
    for text in ("FAKE-csrf-token-0001", "FAKE-session-0001", "ya29.short", "CORR-0001", "sha256:" + "0" * 64):
        assert not any(s.search(text) for s in _REAL_TOKEN_SHAPES), text


def test_free_form_name_detector_is_not_vacuous():
    src = "from dataclasses import dataclass\n@dataclass\nclass R:\n    command: str\ndef f(a, *, channel=None, **raw): ...\n"
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    assert sorted(n for n in _all_arg_names(fn) if n in _FREE_FORM_NAMES) == ["channel", "raw"]
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    assert _is_dataclass(cls)
    assert [s.target.id for s in cls.body if isinstance(s, ast.AnnAssign)] == ["command"]
    # the import checker must refuse a forbidden root and a parent-package relative import
    with pytest.raises(AssertionError):
        _check_imports("x", [("socket", 0)], allow_pytest=False)
    with pytest.raises(AssertionError):
        _check_imports("x", [("workbench_types", 2)], allow_pytest=False)
    with pytest.raises(AssertionError):
        _check_imports("x", [("drive_http", 1)], allow_pytest=False)
