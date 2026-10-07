#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PidFile = Join-Path $Root '.chatgpt\pids\tunnel.pid'

if (-not (Test-Path $PidFile)) {
    Write-Host '[chatgpt] no recorded tunnel process'
    exit 0
}
$pidValue = (Get-Content $PidFile -Raw).Trim()
if ($pidValue -notmatch '^\d+$') { throw 'invalid tunnel pid file' }
$proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $pidValue) -ErrorAction SilentlyContinue
if ($proc) {
    if (-not $proc.CommandLine -or -not $proc.CommandLine.Contains('tunnel-client')) {
        throw 'recorded pid no longer belongs to tunnel-client; refusing to kill it'
    }
    & taskkill.exe /PID $pidValue /T /F | Out-Null
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host '[chatgpt] tunnel-client stopped'
