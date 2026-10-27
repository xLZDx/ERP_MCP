"""The host-side CT14 inventory script refuses every base path except the approved clone, before COM."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "remote" / "ct14_metadata_inventory_ivan.ps1"
POWERSHELL = shutil.which("powershell")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")


def _run(base_path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-BasePath", base_path],
        capture_output=True, text=True, timeout=60, check=False,
    )


@pytest.mark.parametrize("base_path", [
    r'D:\1c\env\bases\818HA_p2diff";Usr="x',          # quote and semicolon injection
    r"D:\1c\env\bases\818HA_p2diff;Usr=x",            # semicolon injection
    r"D:\1c\env\bases\818HA_test_ready",              # another, unapproved base
    r"D:\1c\env\bases\818HA_P2DIFF",                  # case variant is not the approved path
    r"\\evil-host\share\818HA_p2diff",                # UNC form
    r"..\818HA_p2diff",                               # relative form
    "",                                               # empty
])
def test_an_unapproved_base_path_is_refused_before_credentials_or_com(base_path):
    result = _run(base_path)

    assert result.returncode == 2
    assert json.loads(result.stdout) == {"error": "BASE_PATH_NOT_APPROVED"}
    assert result.stderr.strip() == ""


def test_the_script_never_prints_exception_text_from_the_credential_path():
    text = SCRIPT.read_text(encoding="ascii")

    assert "$_.Exception.Message" not in text
    assert "exception_type" in text
