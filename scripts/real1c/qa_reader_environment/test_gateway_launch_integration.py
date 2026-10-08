"""Isolated tests for the real-1C gateway launch wiring in scripts/e2e/_common.ps1.

No real secret is read, no service is started or stopped. The DPAPI reader is replaced by a synthetic function
and Start-Process is never called: only the helper functions are exercised.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
COMMON = ROOT / "scripts" / "e2e" / "_common.ps1"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(os.name != "nt" or POWERSHELL is None, reason="Windows PowerShell required")


def run_case(body: str, *, state_dir: str = r"D:\ERP_MCP_Testbed\real1c_e2e", real1c: str = "1") -> str:
    common = str(COMMON).replace("'", "''")
    state = state_dir.replace("'", "''")
    prefix = f"""
$ErrorActionPreference = 'Stop'
$env:E2E_DIR = '{state}'
$env:E2E_REAL1C = '{real1c}'
$env:E2E_PORT_OFFSET = '3000'
$env:E2E_PROJECT_SUFFIX = '-real1c'
. '{common}'
$env:BAG_ENVIRONMENT = 'test'
$env:BAG_SECRET_PROVIDER = 'env'
[Environment]::SetEnvironmentVariable('ERP_MCP_818HA_USER', $null, 'Process')
[Environment]::SetEnvironmentVariable('ERP_MCP_818HA_PASSWORD', $null, 'Process')
function Read-818HAReaderPassword {{ return 'synthetic-launch-test-value' }}
function Import-E2eEnv {{ $env:BAG_ENVIRONMENT = 'test'; $env:BAG_SECRET_PROVIDER = 'env' }}
function Assert-True([bool]$Value, [string]$Message) {{ if (-not $Value) {{ throw $Message }} }}
"""
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", prefix + body],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=40, check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2500:] + completed.stdout[-1500:]
    for stream in (completed.stdout, completed.stderr):
        assert "synthetic-launch-test-value" not in stream
        assert "synthetic-ambient-secret" not in stream
    return completed.stdout


def test_only_the_real_profile_gateway_needs_the_reader():
    run_case("""
Assert-True (Test-E2eGatewayNeedsReader 'gateway') 'gateway must need the reader'
Assert-True (-not (Test-E2eGatewayNeedsReader 'idp')) 'idp must not'
""")
    run_case("Assert-True (-not (Test-E2eGatewayNeedsReader 'gateway')) 'default profile must not'", real1c="0")


def test_preflight_passes_in_the_reference_lane_and_refuses_another_state_directory():
    run_case("Assert-E2eReaderAvailable")
    run_case("""
$failed = $false
try { Assert-E2eReaderAvailable } catch { $failed = $_.Exception.Message.StartsWith('ERP_READER_STATE_MISMATCH:') }
Assert-True $failed 'foreign state directory accepted'
""", state_dir=r"D:\ERP_MCP_Testbed\other")


@pytest.mark.parametrize("setup,prefix", [
    ("$env:ERP_MCP_818HA_USER = 'NOT_THE_APPROVED_READER'; $env:ERP_MCP_818HA_PASSWORD = 'x'", "ERP_READER_UNEXPECTED_IDENTITY:"),
    ("$env:ERP_MCP_818HA_USER = 'ERP_MCP_TEST_READER'", "ERP_READER_PARTIAL_ENV:"),
])
def test_preflight_applies_the_launch_rules_so_restart_never_stops_a_gateway_it_cannot_start(setup, prefix):
    run_case(f"""
{setup}
$failed = $false
try {{ Assert-E2eReaderAvailable }} catch {{ $failed = $_.Exception.Message.StartsWith('{prefix}') }}
Assert-True $failed 'preflight accepted a launch that would fail'
""")


def test_preflight_has_no_lasting_side_effects():
    run_case("""
$env:UNRELATED_MARKER = 'keep'
Assert-E2eReaderAvailable
Assert-True ($null -eq [Environment]::GetEnvironmentVariable('ERP_MCP_818HA_USER')) 'reader user left behind'
Assert-True ($null -eq [Environment]::GetEnvironmentVariable('ERP_MCP_818HA_PASSWORD')) 'reader password left behind'
Assert-True ($null -eq $env:BAG_ENVIRONMENT) 'BAG_* left behind'
Assert-True ($env:UNRELATED_MARKER -ceq 'keep') 'unrelated variable removed'
""")


def test_preflight_failure_blocks_before_any_launch():
    run_case("""
function Read-818HAReaderPassword { throw 'ERP_READER_SECRET_UNAVAILABLE: simulated' }
$failed = $false
try { Assert-E2eReaderAvailable } catch { $failed = $_.Exception.Message.StartsWith('ERP_READER_SECRET_UNAVAILABLE:') }
Assert-True $failed 'unavailable reader not detected'
""")


def test_ambient_credentials_are_hidden_from_the_launch_and_restored_but_bag_and_reader_pair_stay():
    out = run_case("""
$env:UNRELATED_APP_PASSWORD = 'synthetic-ambient-secret'
$env:SOME_SERVICE_TOKEN = 'synthetic-ambient-secret'
$env:BAG_DATABASE_URL = 'postgresql://kept'
$seen = Invoke-818HAReaderEnvironment -Action {
    Invoke-WithoutAmbientSecrets -Action {
        [pscustomobject]@{
            Password = [bool]$env:UNRELATED_APP_PASSWORD; Token = [bool]$env:SOME_SERVICE_TOKEN
            Bag = [bool]$env:BAG_DATABASE_URL
            User = ($env:ERP_MCP_818HA_USER -ceq 'ERP_MCP_TEST_READER')
            Pair = ($env:ERP_MCP_818HA_PASSWORD -ceq 'synthetic-launch-test-value')
        }
    }
}
Assert-True (-not $seen.Password -and -not $seen.Token) 'ambient secrets leaked into the launch'
Assert-True ($seen.Bag -and $seen.User -and $seen.Pair) 'required variables were hidden'
Assert-True ($env:UNRELATED_APP_PASSWORD -ceq 'synthetic-ambient-secret') 'ambient password not restored'
Assert-True ($env:SOME_SERVICE_TOKEN -ceq 'synthetic-ambient-secret') 'ambient token not restored'
Assert-True ($null -eq [Environment]::GetEnvironmentVariable('ERP_MCP_818HA_PASSWORD')) 'reader pair leaked afterwards'
'OK'
""")
    assert "OK" in out


def run_reset(real1c: str) -> subprocess.CompletedProcess:
    script = str(ROOT / "scripts" / "e2e" / "reset.ps1")
    # The guard fires before anything else, so E2E_DIR may point to an empty directory: nothing is stopped or dropped.
    command = (f"$env:E2E_DIR = '{ROOT / 'scripts'}'; $env:E2E_REAL1C = '{real1c}'; $env:E2E_PORT_OFFSET = '3000'; "
               f"$env:E2E_PROJECT_SUFFIX = '-real1c'; & '{script}'")
    return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=40, check=False)


def test_reset_is_refused_on_the_real_profile_before_any_side_effect():
    completed = run_reset("1")
    assert completed.returncode != 0
    assert "REAL1C_RESET_REFUSED" in completed.stderr + completed.stdout


def test_reset_guard_does_not_apply_to_the_default_profile():
    completed = run_reset("0")
    # the default profile continues to the normal precondition (no secrets.json in this directory)
    assert "REAL1C_RESET_REFUSED" not in completed.stderr + completed.stdout
    assert "not initialised" in completed.stderr + completed.stdout
