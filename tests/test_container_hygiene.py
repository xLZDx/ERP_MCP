"""The production image must not ship test doubles (static build-context check)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ignored(patterns: list[str], relative: str) -> bool:
    parts = relative.split("/")
    for pattern in patterns:
        if pattern.startswith(("#", "!")) or not pattern:
            continue
        tokens = pattern.split("/")
        if tokens[0] == "**":
            if tokens[1:] and any(
                part == tokens[1] for part in parts
            ) and len(tokens) == 2:
                return True
        elif parts[: len(tokens)] == tokens:
            return True
    return False


def test_dockerignore_excludes_package_testbed_from_the_production_context():
    patterns = [
        line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    ]
    assert _ignored(patterns, "src/business_ai_gateway/testbed/fake1c.py")
    assert _ignored(patterns, "src/business_ai_gateway/testbed/__init__.py")
    assert _ignored(patterns, "testbed/fake1c/app.py")
    assert not _ignored(patterns, "src/business_ai_gateway/server.py")


def test_dockerfile_does_not_copy_testbed_explicitly_and_src_has_no_production_import():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"^\s*COPY\b.*testbed", dockerfile, re.MULTILINE)
    assert re.search(r"^\s*COPY\s+src\s+\./src", dockerfile, re.MULTILINE)
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if "testbed" not in path.relative_to(ROOT / "src").parts[:-1]
        and re.search(r"^\s*(from|import)\s+\.*(business_ai_gateway\.)?testbed", path.read_text("utf-8"), re.MULTILINE)
    ]
    assert offenders == [], "production code imports excluded test doubles"
