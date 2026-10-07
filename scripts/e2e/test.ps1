#Requires -Version 5.1
<#
.SYNOPSIS
  Run the e2e pytest suites against the running environment. Never silently skips: the
  environment must exist (ERP_MCP_E2E_NO_SKIP=1 is set).
.PARAMETER Suite
  smoke | user | admin | all
.PARAMETER Skip
  Suites (markers) to deselect; none by default.
#>
[CmdletBinding()]
param(
    [ValidateSet('user', 'admin', 'smoke', 'all')][string]$Suite = 'all',
    [string[]]$Skip = @(),
    [string[]]$PytestArgs = @()
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

if (-not (Test-Path (Join-Path $script:E2eDir 'env.json'))) { throw 'environment missing; run up.ps1' }
Initialize-PythonEnv
$expr = 'e2e'
if ($Suite -ne 'all') { $expr = 'e2e and ' + $Suite }
foreach ($s in $Skip) { $expr += ' and not ' + $s }
Import-E2eEnv
$env:ERP_MCP_E2E_NO_SKIP = '1'
Push-Location $script:Root
try {
    $arguments = @('-m', 'pytest', 'tests/e2e', '-m', $expr, '-p', 'no:cacheprovider', '-q', '-rs') + $PytestArgs
    & $script:Py @arguments
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    Clear-E2eSecretEnv
}
exit $code
