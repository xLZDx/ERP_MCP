<#
.SYNOPSIS
  Run on the 1C host. Repoints the OData publication to another file base under D:\1c\env\bases, restarts Apache through the
  stack scheduled task, and keeps a one-time backup of the original publication descriptor so the change can be reverted.
.DESCRIPTION
  Revert with:  -BaseName 818HA_test_ready  (the backup default.vrd.bak-test_ready is only created once, from the first run).
  Touches only the publication descriptor and the Apache process of this stack. Apache started from an SSH session would die with
  it, so the restart goes through the registered task, which runs the idempotent stack starter.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BaseName,
    [string]$Alias = 'erp_mcp_ref',
    [string]$OriginalBaseName = '818HA_test_ready',
    [string]$TaskName = 'ERP_MCP_Ivan_Stack',
    [int]$Port = 8088
)
$ErrorActionPreference = 'Stop'
$basePath = Join-Path 'D:\1c\env\bases' $BaseName
if (-not (Test-Path (Join-Path $basePath '1Cv8.1CD'))) { throw "base file missing: $basePath" }
$vrd = "D:\1c\env\odata\$Alias\default.vrd"
$bak = $vrd + '.bak-' + $OriginalBaseName
if (-not (Test-Path $bak)) { Copy-Item $vrd $bak }
$new = [IO.File]::ReadAllText($bak).Replace($OriginalBaseName, $BaseName)
[IO.File]::WriteAllText($vrd, $new, [Text.UTF8Encoding]::new($false))
'vrd now points at : ' + ([regex]::Match($new, 'ib="File=([^;]+);').Groups[1].Value)
Get-Process httpd -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $TaskName
$deadline = (Get-Date).AddSeconds(90)
while (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 3 }
'apache listening  : ' + [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
