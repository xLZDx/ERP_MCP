#Requires -Version 5.1
<#
.SYNOPSIS
  Return to the deterministic clean state without regenerating secrets: stop gateway/IdP,
  drop the bag schema, flush Redis, migrate, re-seed, restart gateway/IdP.
#>
[CmdletBinding()]
param([ValidateSet('baseline', 'bootstrap-only', 'none')][string]$Seed)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

if (-not (Test-Path (Join-Path $script:E2eDir 'secrets.json'))) { throw 'not initialised; run up.ps1' }
if (-not $Seed) { $Seed = Get-SeedMode }
if (-not $Seed) { $Seed = 'baseline' }

Invoke-Envctl @('init-secrets') | Out-Null
Invoke-Envctl @('write-env', '--seed', $Seed) | Out-Null
Start-E2eDependencies
foreach ($name in 'gateway', 'idp') { Stop-E2eComponent $name }
Import-E2eEnv
try {
    Invoke-Envctl @('drop-schema') | Out-Null
    Invoke-Envctl @('flush-redis') | Out-Null
} finally { Clear-E2eSecretEnv }
Invoke-E2eMigrate
Import-E2eEnv
try { Invoke-Envctl @('seed', '--mode', $Seed) | Out-Null } finally { Clear-E2eSecretEnv }
foreach ($name in $script:ProcessComponents) { Start-E2eComponent $name }
foreach ($name in $script:ProcessComponents) { Wait-E2eComponent $name }
Invoke-Envctl @('commit-ready') | Out-Null
Write-Step ('reset complete, seed mode ' + $Seed)
