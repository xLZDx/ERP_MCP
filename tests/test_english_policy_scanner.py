"""Focused contract tests for the English-policy scanner's decoding and exceptions."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = REPO_ROOT / "scripts" / "check_english_policy.py"


def _run_scanner(tmp_path: Path, payload: bytes, allowlist: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Run the real scanner in a tiny temporary tracked repository."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "governance").mkdir()
    (tmp_path / "scripts" / "check_english_policy.py").write_bytes(SCANNER.read_bytes())
    (tmp_path / "governance" / "ENGLISH_POLICY_ALLOWLIST.json").write_text(
        json.dumps(allowlist or {}, separators=(",", ":")), encoding="utf-8"
    )
    (tmp_path / "fixture.txt").write_bytes(payload)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "scripts", "governance", "fixture.txt"], cwd=tmp_path, check=True, capture_output=True)
    return subprocess.run(
        [sys.executable, "scripts/check_english_policy.py"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("bom", "codec"),
    [(b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")],
)
def test_bom_marked_utf16_text_is_decoded_and_exact_exception_is_accepted(
    tmp_path: Path, bom: bytes, codec: str
) -> None:
    line = "\u043a\u043b\u044e\u0447"
    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    result = _run_scanner(
        tmp_path,
        bom + line.encode(codec),
        {"fixture.txt": {"reason": "synthetic encoding fixture", "allowed_lines": [{"line": 1, "sha256": digest}]}},
    )

    assert result.returncode == 0
    assert "unreadable text files: 0" in result.stdout
    assert "violations: 0" in result.stdout


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfe\x00\x00" + "fixture".encode("utf-32-le"),
        b"\x00\x00\xfe\xff" + "fixture".encode("utf-32-be"),
    ],
)
def test_utf32_bom_is_rejected_fail_closed(tmp_path: Path, payload: bytes) -> None:
    result = _run_scanner(tmp_path, payload)

    assert result.returncode == 2
    assert "unsupported UTF-32 BOM" in result.stdout
    assert "unreadable text files: 1" in result.stdout


@pytest.mark.parametrize(
    "payload",
    [
        b"plain\x00text",
        b"\xff\xfe" + "plain\x00text".encode("utf-16-le"),
    ],
)
def test_nul_in_unmarked_or_decoded_text_is_rejected_fail_closed(
    tmp_path: Path, payload: bytes
) -> None:
    result = _run_scanner(tmp_path, payload)

    assert result.returncode == 2
    assert "unreadable text files: 1" in result.stdout
    assert "NUL" in result.stdout


def test_allowlist_exception_is_bound_to_line_number_and_hash(tmp_path: Path) -> None:
    line = "\u043f\u043e\u0432\u0442\u043e\u0440"
    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    result = _run_scanner(
        tmp_path,
        f"{line}\n{line}\n".encode("utf-8"),
        {"fixture.txt": {"reason": "synthetic duplicate fixture", "allowed_lines": [{"line": 1, "sha256": digest}]}},
    )

    assert result.returncode == 1
    assert f"CYRILLIC fixture.txt:2: sha256={digest}" in result.stdout
    assert "CYRILLIC fixture.txt:1:" not in result.stdout
    assert "violations: 1" in result.stdout
    assert "stale line exceptions: 0" in result.stdout


def test_allowlist_entry_with_missing_occurrence_is_reported_stale(tmp_path: Path) -> None:
    line = "\u0438\u0441\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435"
    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    result = _run_scanner(
        tmp_path,
        b"English only\n",
        {"fixture.txt": {"reason": "synthetic stale fixture", "allowed_lines": [{"line": 1, "sha256": digest}]}},
    )

    assert result.returncode == 1
    assert f"STALE_ALLOWLIST_LINE fixture.txt:1: sha256={digest}" in result.stdout
    assert "stale line exceptions: 1" in result.stdout
