#Requires -Version 5.1
<#
.SYNOPSIS
  Stop host processes and the compose project. -Purge also removes volumes and .e2e/.
  Only touches project erpmcp-e2e, its volume/network and the .e2e directory.
#>
[CmdletBinding()]
param([switch]$Purge)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

foreach ($name in 'gateway', 'idp', 'fake1c') { Stop-E2eComponent $name }
if (Test-Path (Join-Path $script:E2eDir 'compose.env')) {
    $args1 = @('down', '--remove-orphans')
    if ($Purge) { $args1 += '--volumes' }
    Invoke-Compose $args1 | Out-Null
} elseif ($Purge) {
    Invoke-Native 'docker' @('compose', '-p', $script:ProjectName, 'down', '--volumes') -AllowFail | Out-Null
}
if ($Purge -and (Test-Path $script:E2eDir)) {
    $resolved = (Resolve-Path $script:E2eDir).Path
    if ($resolved -ne (Join-Path $script:Root '.e2e')) { throw 'refusing to purge unexpected directory' }
    Remove-Item -Recurse -Force $resolved
    Write-Step 'purged volumes and .e2e/'
}
Write-Step 'down complete'
