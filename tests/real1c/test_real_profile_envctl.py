"""The real local 1C stand profile (E2E_REAL1C=1) starts no Fake1C and no fake sidecar and carries no Fake1C settings."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.e2e import envctl

ROOT = Path(envctl.__file__).resolve().parents[2]
HOSTS = "127.0.0.1:8191,127.0.0.1:8192,127.0.0.1:8193"
SIDECAR = "http://127.0.0.1:21768"


@pytest.fixture
def load(monkeypatch, tmp_path):
    def _load(*, real: bool, hosts: str | None = HOSTS, sidecar: str | None = SIDECAR):
        monkeypatch.setenv("E2E_DIR", str(tmp_path))
        monkeypatch.setenv("E2E_PORT_OFFSET", "3000")
        monkeypatch.setenv("E2E_PROJECT_SUFFIX", "-real1c")
        for name, value in (("E2E_REAL1C", "1" if real else None), ("E2E_SOURCE_ALLOWED_HOSTS", hosts),
                            ("E2E_SIDECAR_URL", sidecar)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return importlib.reload(envctl)

    yield _load
    monkeypatch.undo()
    importlib.reload(envctl)


def test_real_profile_has_no_fake_secrets_env_or_urls(load, tmp_path):
    mod = load(real=True)
    mod.init_secrets()
    secrets_text = (tmp_path / "secrets.json").read_text(encoding="utf-8")
    assert "fake1c" not in secrets_text.lower()
    env = mod.env_vars()
    assert not [key for key in env if key.startswith(("FAKE1C_", "FAKE_SIDECAR"))]
    assert env["BAG_ADMIN_SOURCE_ALLOWED_HOSTS"] == HOSTS and env["BAG_ODATA_SIDECAR_URL"] == SIDECAR
    mod.write_env("bootstrap-only")
    pending = json.loads((tmp_path / "env.pending.json").read_text(encoding="utf-8"))
    assert "fake1c" not in json.dumps(pending).lower()
    assert pending["urls"]["sidecar"] == SIDECAR and pending["source_id"] is None and pending["companies"] == {}
    env_ps1 = (tmp_path / "env.ps1").read_text(encoding="utf-8")
    assert "FAKE1C_" not in env_ps1 and "FAKE_SIDECAR" not in env_ps1


@pytest.mark.parametrize("missing", ["hosts", "sidecar"])
def test_real_profile_requires_explicit_real_endpoints(load, missing):
    mod = load(real=True, hosts=None if missing == "hosts" else HOSTS, sidecar=None if missing == "sidecar" else SIDECAR)
    mod.init_secrets()
    with pytest.raises(SystemExit):
        mod.env_vars()


def test_real_profile_refuses_the_baseline_seed(load):
    mod = load(real=True)
    with pytest.raises(SystemExit):
        import asyncio

        asyncio.run(mod.seed("baseline"))


def test_default_profile_still_provides_the_fake_stand(load, tmp_path):
    mod = load(real=False, hosts=None, sidecar=None)
    mod.init_secrets()
    env = mod.env_vars()
    assert env["FAKE1C_USERNAME"] and env["FAKE1C_PASSWORD"] and env["FAKE_SIDECAR_TOKEN"]
    assert env["BAG_ADMIN_SOURCE_ALLOWED_HOSTS"].endswith(str(mod.PORTS["fake1c"]))


def test_powershell_harness_skips_the_fake_components_in_the_real_profile():
    common = (ROOT / "scripts" / "e2e" / "_common.ps1").read_text(encoding="utf-8")
    assert "$script:Real1c = ($env:E2E_REAL1C -eq '1')" in common
    assert "if ($script:Real1c) { @('idp', 'gateway') }" in common
    down = (ROOT / "scripts" / "e2e" / "down.ps1").read_text(encoding="utf-8")
    assert "$script:ProcessComponents -contains $name" in down
    status = (ROOT / "scripts" / "e2e" / "status.ps1").read_text(encoding="utf-8")
    assert "$checks.Remove('fake1c'); $checks.Remove('sidecar')" in status


def test_a_quote_in_a_configured_value_cannot_break_out_of_env_ps1(load, tmp_path):
    mod = load(real=True, sidecar="http://127.0.0.1:21768'; Remove-Item x; '")
    mod.init_secrets()
    mod.write_env("bootstrap-only")
    line = next(x for x in (tmp_path / "env.ps1").read_text(encoding="utf-8").splitlines() if "BAG_ODATA_SIDECAR_URL" in x)
    assert line == "$env:BAG_ODATA_SIDECAR_URL = 'http://127.0.0.1:21768''; Remove-Item x; '''"
    assert json.loads((tmp_path / "env.pending.json").read_text(encoding="utf-8"))["real1c"] is True


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
@pytest.mark.parametrize("component", ["fake1c", "sidecar"])
def test_the_start_primitive_refuses_fake_components_in_the_real_profile(component, tmp_path):
    script = (f". '{ROOT / 'scripts' / 'e2e' / '_common.ps1'}'; "
              f"try {{ Start-E2eComponent '{component}'; 'STARTED' }} catch {{ 'REFUSED: ' + $_.Exception.Message }}")
    env = {**os.environ, "E2E_REAL1C": "1", "E2E_DIR": str(tmp_path)}
    out = subprocess.run(["pwsh", "-NoProfile", "-Command", script], capture_output=True, text=True, env=env,
                         timeout=60, check=False).stdout
    assert "REFUSED" in out and "real local 1C profile" in out and "STARTED" not in out
