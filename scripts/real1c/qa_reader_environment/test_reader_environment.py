"""Isolated PowerShell unit tests. No real secret reads and no service operations.

Run with pytest in THIS directory. The normal project pytest configuration is unchanged.
Every behavioral test replaces the DPAPI reader with a synthetic in-memory function.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "reader_environment.ps1"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(os.name != "nt" or POWERSHELL is None, reason="Windows PowerShell required")


def run_case(body: str) -> None:
    path = str(MODULE).replace("'", "''")
    prefix = f"""
$ErrorActionPreference = 'Stop'
. '{path}'
$env:BAG_ENVIRONMENT = 'test'
$env:BAG_SECRET_PROVIDER = 'env'
[Environment]::SetEnvironmentVariable('ERP_MCP_818HA_USER', $null, 'Process')
[Environment]::SetEnvironmentVariable('ERP_MCP_818HA_PASSWORD', $null, 'Process')
$script:ReaderCalls = 0
$script:ActionCalls = 0
function Read-818HAReaderPassword {{
    $script:ReaderCalls += 1
    return 'synthetic-unit-test-value'
}}
function Assert-True([bool]$Value, [string]$Message) {{
    if (-not $Value) {{ throw $Message }}
}}
"""
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", prefix + body],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=20, check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2500:]
    assert "synthetic-unit-test-value" not in completed.stdout
    assert "synthetic-unit-test-value" not in completed.stderr


def test_missing_pair_is_loaded_only_inside_action_and_cleared():
    run_case("""
$value = Invoke-818HAReaderEnvironment -Action {
    Assert-True ($env:ERP_MCP_818HA_USER -ceq 'ERP_MCP_TEST_READER') 'wrong user'
    Assert-True ($env:ERP_MCP_818HA_PASSWORD -ceq 'synthetic-unit-test-value') 'wrong password'
    return 'SAFE_RESULT'
}
Assert-True ($value -ceq 'SAFE_RESULT') 'unexpected output'
Assert-True ($script:ReaderCalls -eq 1) 'reader call count'
Assert-True ($null -eq [Environment]::GetEnvironmentVariable('ERP_MCP_818HA_USER')) 'user leaked'
Assert-True ($null -eq [Environment]::GetEnvironmentVariable('ERP_MCP_818HA_PASSWORD')) 'password leaked'
""")


def test_existing_complete_reader_pair_is_preserved_without_decryption():
    run_case("""
$env:ERP_MCP_818HA_USER = 'ERP_MCP_TEST_READER'
$env:ERP_MCP_818HA_PASSWORD = 'existing-test-value'
Invoke-818HAReaderEnvironment -Action {
    Assert-True ($env:ERP_MCP_818HA_PASSWORD -ceq 'existing-test-value') 'existing pair changed'
    $env:ERP_MCP_818HA_PASSWORD = 'changed-inside-test'
}
Assert-True ($script:ReaderCalls -eq 0) 'unnecessary decrypt'
Assert-True ($env:ERP_MCP_818HA_PASSWORD -ceq 'existing-test-value') 'old pair not restored'
""")


@pytest.mark.parametrize("name", ["ERP_MCP_818HA_USER", "ERP_MCP_818HA_PASSWORD"])
def test_partial_pair_rejected_before_read_or_action(name):
    run_case(f"""
[Environment]::SetEnvironmentVariable('{name}', 'partial-test-value', 'Process')
$failed = $false
try {{ Invoke-818HAReaderEnvironment -Action {{ $script:ActionCalls += 1 }} }} catch {{
    $failed = $_.Exception.Message.StartsWith('ERP_READER_PARTIAL_ENV:')
}}
Assert-True $failed 'partial pair accepted'
Assert-True ($script:ReaderCalls -eq 0 -and $script:ActionCalls -eq 0) 'side effect'
Assert-True ([Environment]::GetEnvironmentVariable('{name}') -ceq 'partial-test-value') 'partial value changed'
""")


@pytest.mark.parametrize("assignment", ["$env:BAG_ENVIRONMENT = 'production'", "$env:BAG_SECRET_PROVIDER = 'file'"])
def test_wrong_environment_or_provider_is_rejected(assignment):
    run_case(assignment + """
$failed = $false
try { Invoke-818HAReaderEnvironment -Action { $script:ActionCalls += 1 } } catch {
    $failed = $_.Exception.Message.StartsWith('ERP_READER_TEST_ENV_REQUIRED:')
}
Assert-True $failed 'wrong context accepted'
Assert-True ($script:ReaderCalls -eq 0 -and $script:ActionCalls -eq 0) 'unexpected side effect'
""")


def test_unexpected_identity_rejected():
    run_case("""
$env:ERP_MCP_818HA_USER = 'NOT_THE_APPROVED_READER'
$env:ERP_MCP_818HA_PASSWORD = 'test-only'
$failed = $false
try { Invoke-818HAReaderEnvironment -Action { $script:ActionCalls += 1 } } catch {
    $failed = $_.Exception.Message.StartsWith('ERP_READER_UNEXPECTED_IDENTITY:')
}
Assert-True $failed 'unexpected identity accepted'
Assert-True ($script:ActionCalls -eq 0) 'action ran'
""")


def test_reader_failure_is_sanitized_and_action_does_not_run():
    run_case("""
function Read-818HAReaderPassword { throw 'DO_NOT_EXPOSE_INNER_DETAIL' }
$failed = $false
try { Invoke-818HAReaderEnvironment -Action { $script:ActionCalls += 1 } } catch {
    $failed = $_.Exception.Message.StartsWith('ERP_READER_SECRET_UNAVAILABLE:')
    Assert-True (-not $_.Exception.Message.Contains('DO_NOT_EXPOSE')) 'inner details leaked'
}
Assert-True $failed 'reader failure not detected'
Assert-True ($script:ActionCalls -eq 0) 'action ran'
""")


@pytest.mark.parametrize("value", ["''", "([string][char]0)", "\"test`nvalue\""])
def test_invalid_secret_does_not_reach_action(value):
    run_case(f"""
function Read-818HAReaderPassword {{ return {value} }}
$failed = $false
try {{ Invoke-818HAReaderEnvironment -Action {{ $script:ActionCalls += 1 }} }} catch {{
    $failed = $_.Exception.Message.StartsWith('ERP_READER_SECRET_INVALID:')
}}
Assert-True $failed 'invalid secret accepted'
Assert-True ($script:ActionCalls -eq 0) 'action ran'
Assert-True ($null -eq [Environment]::GetEnvironmentVariable('ERP_MCP_818HA_PASSWORD')) 'password leaked'
""")


def test_action_failure_still_clears_temporary_environment():
    run_case("""
$failed = $false
try { Invoke-818HAReaderEnvironment -Action { throw 'SIMULATED_ACTION_FAILURE' } } catch {
    $failed = $_.Exception.Message -ceq 'SIMULATED_ACTION_FAILURE'
}
Assert-True $failed 'action failure swallowed'
Assert-True ($null -eq [Environment]::GetEnvironmentVariable('ERP_MCP_818HA_USER')) 'user leaked'
Assert-True ($null -eq [Environment]::GetEnvironmentVariable('ERP_MCP_818HA_PASSWORD')) 'password leaked'
""")


def test_exact_reference_state_guard():
    run_case(r"""
Assert-True (Test-818HAReferenceState -StateDirectory 'D:\ERP_MCP_Testbed\real1c_e2e') 'exact state denied'
Assert-True (Test-818HAReferenceState -StateDirectory 'd:\erp_mcp_testbed\real1c_e2e\') 'normalized state denied'
Assert-True (-not (Test-818HAReferenceState -StateDirectory 'D:\ERP_MCP_Testbed\other')) 'other lane allowed'
Assert-True (-not (Test-818HAReferenceState -StateDirectory 'D:\ERP_MCP_Testbed\real1c_e2e-copy')) 'prefix collision'
Assert-True ($script:ReaderCalls -eq 0) 'guard accessed secret'
""")
