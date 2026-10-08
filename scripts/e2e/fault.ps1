#Requires -Version 5.1
<#
.SYNOPSIS
  Outage/recovery fault injection for the disposable E2E environment only.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('fake1c', 'sidecar', 'redis', 'postgres', 'idp', 'gateway')][string]$Component,
    [Parameter(Mandatory)][ValidateSet('stop', 'start', 'restart')][string]$Action
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

function Set-Component([string]$Verb) {
    if ($Component -in 'postgres', 'redis') {
        if ($Verb -eq 'stop') { Invoke-Compose @('stop', $Component) | Out-Null }
        else { Invoke-Compose @('up', '-d', '--wait', '--wait-timeout', '120', $Component) | Out-Null }
    } else {
        if ($Verb -eq 'stop') { Stop-E2eComponent $Component }
        else { Start-E2eComponent $Component; Wait-E2eComponent $Component }
    }
}

if ((Test-E2eGatewayNeedsReader $Component) -and $Action -in 'start', 'restart') {
    # Never stop a working gateway when its replacement could not receive the reader credentials.
    Assert-E2eReaderAvailable
}

switch ($Action) {
    'stop' { Set-Component 'stop' }
    'start' { Set-Component 'start' }
    'restart' { Set-Component 'stop'; Set-Component 'start' }
}
Write-Step ($Component + ': ' + $Action + ' done')
