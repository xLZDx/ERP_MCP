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

# Refuse to start if one of OUR ports is held by something that is not our own component
# (loopback or not, with or without a pid file).
foreach ($name in $script:ProcessComponents) {
    $foreign = Get-ForeignListener $name
    if ($foreign) {
        throw ('port ' + $script:Ports[$name] + ' (' + $name + ') is held by a foreign process (pid ' +
            $foreign.Pid + ')')
    }
}

Write-Step 'generating secrets (once) and environment files'
Invoke-Envctl @('init-secrets') | Out-Null
Invoke-Envctl @('write-env', '--seed', $Seed) | Out-Null

Write-Step 'starting PostgreSQL 16 and Redis 7 (compose project ' + $script:ProjectName + ')'
Start-E2eDependencies

Write-Step 'creating login roles, migrating, verifying schema and privileges'
Invoke-E2eMigrate

Write-Step ('seeding: ' + $Seed)
Import-E2eEnv
try { Invoke-Envctl @('seed', '--mode', $Seed) | Out-Null } finally { Clear-E2eSecretEnv }

foreach ($name in $script:ProcessComponents) { Start-E2eComponent $name }
foreach ($name in $script:ProcessComponents) { Wait-E2eComponent $name }
# The ready marker (env.json) is published only after seed and health checks succeeded.
Invoke-Envctl @('commit-ready') | Out-Null

Write-Step ('environment ready. Consumers: . ' + (Join-Path $script:E2eDir 'env.ps1'))
Write-Step ('gateway http://127.0.0.1:' + $script:Ports.gateway + ' (MCP /mcp, Admin UI /admin/), IdP http://127.0.0.1:' + $script:Ports.idp +
    $(if ($script:Real1c) { ' (real local 1C profile: no Fake1C, no fake sidecar)' } else {
        ', fake sidecar :' + $script:Ports.sidecar + ' (BAG_ENVIRONMENT=test, synthetic fixture profiles)' }))
