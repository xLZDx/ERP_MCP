#Requires -Version 5.1
[CmdletBinding()]
param([switch]$DownE2E)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PidFile = Join-Path $Root '.chatgpt\pids\gateway.pid'

if (Test-Path $PidFile) {
    $pidValue = (Get-Content $PidFile -Raw).Trim()
    if ($pidValue -match '^\d+$') {
        $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $pidValue) -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -and
            $proc.CommandLine.Contains('business_ai_gateway.app:app') -and
            $proc.CommandLine.Contains('--port 18100')) {
            & taskkill.exe /PID $pidValue /T /F | Out-Null
        } elseif ($proc) {
            throw 'recorded pid no longer belongs to the ChatGPT local gateway; refusing to kill it'
        }
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
Write-Host '[chatgpt] local gateway stopped'

if ($DownE2E) {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $Root 'scripts\e2e\down.ps1')
}
