"""S7/E5: AST boundary test over the Drive S7 modules and their tests.

Static only: the sources are parsed, never imported or executed. It proves the S7 Drive modules are
pure in-memory stdlib code that stays inside the phase2 package, cannot reach the network, a database,
the environment or the file system, never touch the existing HTTP reader (``drive_http.py``), and that
no real-looking credential or real Google scope URL exists in the S7 sources or tests.
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

S7_MODULES = (
    "drive_port.py",
    "drive_fake.py",
    "drive_oauth.py",
    "drive_scope.py",
    "drive_baseline.py",
    "drive_cursor.py",
    "drive_revisions.py",
    "drive_membership.py",
    "drive_auth_state.py",
)
S7_TESTS = (
    "test_drive_port_fake.py",
    "test_drive_oauth.py",
    "test_drive_scope.py",
    "test_drive_baseline.py",
    "test_drive_cursor.py",
    "test_drive_revisions.py",
    "test_drive_membership.py",
    "test_drive_auth_state.py",
    "test_drive_hints.py",
    "test_s7_boundaries.py",
)

_STDLIB = frozenset(sys.stdlib_module_names)
_NETWORK_DB = frozenset({
    "httpx", "requests", "aiohttp", "urllib", "urllib3", "http", "socket", "ssl", "subprocess",
    "ftplib", "smtplib", "sqlite3", "psycopg", "psycopg2", "asyncpg", "aiosqlite", "sqlalchemy",
    "pymysql", "mysql", "pyodbc", "databases",
})
_ENV_FILE = frozenset({"os", "pathlib", "tempfile", "shutil", "glob", "fileinput", "dotenv", "io"})
_FILE_METHODS = frozenset({"read_text", "write_text", "read_bytes", "write_bytes", "open", "environ", "getenv"})
_FORBIDDEN_ROOTS = _NETWORK_DB | _ENV_FILE
_GOOGLE_URL = re.compile(r"googleapis\.com|accounts\.google\.com|/auth/drive|oauth2\.googleapis", re.IGNORECASE)
# Real token shapes (real tokens are 60+ chars; short ``ya29.SECRET-...`` canaries in tests are not tokens):
# Google access token ``ya29.<long>``, refresh token ``1//<long>``, client secret ``GOCSPX-``.
_REAL_TOKEN_SHAPES = (
    re.compile(r"ya29\.[A-Za-z0-9_\-]{40,}"),
    re.compile(r"(?<![A-Za-z0-9:/])1//[A-Za-z0-9_\-]{40,}"),
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
)
_PORT_METHODS = ["get_start_page_token", "list_changes", "get_file_meta", "list_revisions"]
_WRITE_WORDS = ("write", "create", "update", "delete", "patch", "put", "post", "permission", "keep", "forever",
                "share", "grant", "insert", "upload", "copy", "trash", "move")


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


def test_every_s7_module_and_test_file_listed_exists_except_pending_hints_and_self():
    missing = [n for n in S7_MODULES if not (_SRC / n).is_file()]
    assert not missing, missing
    # drive_http.py and drive_changes.py are the pre-existing reader/projector, not S7 modules.
    assert (_SRC / "drive_http.py").is_file()
    present_tests = [n for n in S7_TESTS if (_TESTS / n).is_file()]
    assert "test_s7_boundaries.py" in present_tests
    for required in S7_TESTS[:-2]:
        assert required in present_tests, required


@pytest.mark.parametrize("name", S7_MODULES)
def test_module_imports_only_stdlib_or_sibling_phase2_and_nothing_forbidden(name):
    records = _import_records(_tree(name))
    assert records, "scan must see imports"
    for mod, level in records:
        low = mod.lower()
        assert "pdcc" not in low and "release1" not in low and "release_1" not in low, (name, mod)
        assert "drive_http" not in low, (name, mod)
        root = mod.split(".")[0]
        if level == 0:
            if root == "business_ai_gateway":
                # absolute import of this package: only the phase2 subpackage is allowed
                assert mod.startswith("business_ai_gateway.phase2"), (name, mod)
                continue
            assert root in _STDLIB, (name, mod)
            assert root not in _FORBIDDEN_ROOTS, (name, mod)
        else:
            # relative import: exactly one dot = sibling phase2 module; ``..`` would leave phase2 (Release 1 side)
            assert level == 1, (name, mod, level)
            assert root not in _FORBIDDEN_ROOTS, (name, mod)


@pytest.mark.parametrize("name", S7_MODULES)
def test_module_has_no_environment_or_file_io(name):
    tree = _tree(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "__import__", "exec", "eval", "compile"}, (name, node.lineno)
        if isinstance(node, ast.Attribute):
            assert node.attr not in _FILE_METHODS, (name, node.attr, node.lineno)
        if isinstance(node, ast.Name):
            assert node.id not in {"environ", "getenv"}, (name, node.id, node.lineno)


@pytest.mark.parametrize("name", S7_MODULES)
def test_no_google_scope_or_endpoint_url_literal_in_module(name):
    """No real Google scope/endpoint string is passed to a call (nor kept as a constant) in S7 sources."""
    tree = _tree(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            args = list(node.args) + [k.value for k in node.keywords]
            for arg in args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        assert not _GOOGLE_URL.search(sub.value), (name, node.lineno)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not _GOOGLE_URL.search(node.value), (name, node.lineno)


def _scanned_files() -> list[Path]:
    files = [_SRC / n for n in S7_MODULES]
    files += [_TESTS / n for n in S7_TESTS if (_TESTS / n).is_file()]
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
    real = ["ya29." + "a" * 60, "1//" + "b" * 60, "GOCSPX-" + "c" * 20]
    for text in real:
        assert any(s.search(text) for s in _REAL_TOKEN_SHAPES), text
    for text in ("FAKE-access-token-0001", "FAKE-refresh-0001", "ya29.short"):
        assert not any(s.search(text) for s in _REAL_TOKEN_SHAPES), text
    assert _GOOGLE_URL.search("https://www.googleapis.com/auth/drive.file")
    assert not _GOOGLE_URL.search("drive.file")


def test_drive_port_protocol_has_exactly_the_four_read_methods():
    tree = _tree("drive_port.py")
    protocols = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "DrivePort"]
    assert len(protocols) == 1
    cls = protocols[0]
    assert any(isinstance(b, ast.Name) and b.id == "Protocol" for b in cls.bases)
    funcs = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert [f.name for f in funcs] == _PORT_METHODS
    assert all(isinstance(f, ast.AsyncFunctionDef) for f in funcs)
    # nothing else in the Protocol body besides the docstring and these methods
    others = [n for n in cls.body if n not in funcs and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    assert not others
    for fn in funcs:
        lowered = fn.name.lower()
        assert not any(w in lowered for w in _WRITE_WORDS), fn.name


def test_no_write_permission_or_keep_forever_method_on_any_port_like_class():
    for name in ("drive_port.py", "drive_fake.py"):
        tree = _tree(name)
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            if cls.name not in {"DrivePort", "FakeDrivePort"}:
                continue
            for fn in cls.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and not fn.name.startswith("_"):
                    low = fn.name.lower()
                    if cls.name == "DrivePort":
                        assert fn.name in _PORT_METHODS, fn.name
                    # the fake may script behaviour but never expose a Drive write verb
                    assert "keepforever" not in low and "keep_forever" not in low, fn.name
                    assert "permission" not in low and "upload" not in low and "delete" not in low, fn.name
