#Requires -Version 5.1
<#
.SYNOPSIS
  Idempotently bring up the disposable local E2E environment (project erpmcp-e2e).
.PARAMETER Seed
  baseline | bootstrap-only | none (see docs/E2E_ENVIRONMENT.md).
#>
[CmdletBinding()]
param([ValidateSet('baseline', 'bootstrap-only', 'none')][string]$Seed = 'baseline')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

$existing = Get-SeedMode
if ($existing -and $existing -ne $Seed) {
    throw ('environment already initialised with seed mode "' + $existing +
        '"; run scripts/e2e/reset.ps1 -Seed ' + $Seed + ' to change it')
}

# Refuse to start if one of OUR ports is held by something that is not our own component.
foreach ($name in $script:ProcessComponents) {
    $listener = Get-ListenerInfo $script:Ports[$name]
    if ($listener -and -not (Get-ComponentPid $name) -and -not ($listener | Where-Object { $_.Address -eq '127.0.0.1' })) {
        throw ('port ' + $script:Ports[$name] + ' is held by a foreign listener')
    }
}

Write-Step 'generating secrets (once) and environment files'
Invoke-Envctl @('init-secrets') | Out-Null
Invoke-Envctl @('write-env', '--seed', $Seed) | Out-Null

Write-Step 'starting PostgreSQL 16 and Redis 7 (compose project erpmcp-e2e)'
Start-E2eDependencies

Write-Step 'creating login roles, migrating, verifying schema and privileges'
Invoke-E2eMigrate

Write-Step ('seeding: ' + $Seed)
Import-E2eEnv
try { Invoke-Envctl @('seed', '--mode', $Seed) | Out-Null } finally { Clear-E2eSecretEnv }

foreach ($name in $script:ProcessComponents) { Start-E2eComponent $name }
foreach ($name in $script:ProcessComponents) { Wait-E2eComponent $name }

Write-Step ('environment ready. Consumers: . ' + (Join-Path $script:E2eDir 'env.ps1'))
Write-Step 'gateway http://127.0.0.1:18000 (MCP /mcp, Admin UI /admin/), IdP http://127.0.0.1:18080'
