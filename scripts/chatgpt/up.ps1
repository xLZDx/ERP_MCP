#Requires -Version 5.1
<#
.SYNOPSIS
  Starts the disposable ChatGPT-facing MCP endpoint on 127.0.0.1:18100.

.DESCRIPTION
  SYNTHETIC TEST path only. It reuses the Fake1C E2E environment, disables OAuth
  and every Admin surface for this extra gateway, and maps the tunnel to the
  fixed development-local principal. local_prepare.py refuses real sources.
#>
[CmdletBinding()]
param([switch]$SkipE2EStart)

$ErrorActionPreference = 'Stop'
if (-not $env:ComSpec) {
    $env:ComSpec = Join-Path $env:SystemRoot 'System32\cmd.exe'
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$State = Join-Path $Root '.chatgpt'
$PidDir = Join-Path $State 'pids'
$LogDir = Join-Path $State 'logs'
$PidFile = Join-Path $PidDir 'gateway.pid'
$Port = 18100
$Endpoint = "http://127.0.0.1:$Port/mcp"

# Dedicated topology: never share the default E2E ports/project with another worktree.
if (-not $env:E2E_PORT_OFFSET) { $env:E2E_PORT_OFFSET = '5000' }
if (-not $env:E2E_PROJECT_SUFFIX) { $env:E2E_PROJECT_SUFFIX = '-chatgpt' }

if (-not $SkipE2EStart) {
    & (Join-Path $Root 'scripts\e2e\up.ps1') -Seed baseline
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw 'dedicated ChatGPT E2E baseline failed to start'
    }
}

$e2eEnv = Join-Path $Root '.e2e\env.ps1'
if (-not (Test-Path $e2eEnv)) {
    throw 'E2E environment missing; run scripts\e2e\up.ps1 -Seed baseline'
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($listener) {
    if (Test-Path $PidFile) {
        Write-Host "[chatgpt] local gateway already listening on $Endpoint"
        exit 0
    }
    throw "port $Port is already held by another process"
}

New-Item -ItemType Directory -Force -Path $PidDir,$LogDir | Out-Null

Get-ChildItem Env: | Where-Object { $_.Name -like 'BAG_*' } | ForEach-Object {
    Remove-Item ('Env:' + $_.Name)
}
. $e2eEnv

# Hard safety overrides for the ChatGPT-facing local endpoint.
$env:BAG_PUBLIC_MCP_URL = $Endpoint
$env:BAG_OAUTH_ENABLED = 'false'
$env:BAG_ADMIN_API_ENABLED = 'false'
$env:BAG_ADMIN_UI_ENABLED = 'false'
$env:BAG_ADMIN_MUTATIONS_ENABLED = 'false'
$env:BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED = 'false'
$env:PYTHONPATH = Join-Path $Root 'src'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONUTF8 = '1'

$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { throw 'project venv missing; run scripts\e2e\up.ps1 first' }

Push-Location $Root
try {
    & $Py scripts\chatgpt\local_prepare.py
    if ($LASTEXITCODE -ne 0) { throw 'local_prepare.py failed' }

    $out = Join-Path $LogDir 'gateway.out.log'
    $err = Join-Path $LogDir 'gateway.err.log'
    $args = '-m uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port ' + $Port + ' --no-access-log'
    $cmd = '/c ""' + $Py + '" ' + $args + ' > "' + $out + '" 2> "' + $err + '""'
    $p = Start-Process -FilePath $env:ComSpec -ArgumentList $cmd -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Set-Content -Path $PidFile -Value ([string]$p.Id) -Encoding ascii
} finally {
    Pop-Location
    Get-ChildItem Env: | Where-Object {
        $_.Name -like 'BAG_*' -or $_.Name -like 'FAKE1C_*' -or $_.Name -like 'FAKE_SIDECAR_*'
    } | ForEach-Object { Remove-Item ('Env:' + $_.Name) }
}

$deadline = (Get-Date).AddSeconds(45)
$isReady = $false
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 2
        $ready = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/readyz" -UseBasicParsing -TimeoutSec 2
        if ($health.StatusCode -eq 200 -and $ready.StatusCode -eq 200) {
            $isReady = $true
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}
if (-not $isReady) {
    $tail = ''
    $err = Join-Path $LogDir 'gateway.err.log'
    if (Test-Path $err) { $tail = (Get-Content $err -Tail 25) -join [Environment]::NewLine }
    throw ('ChatGPT local gateway did not become ready.' + [Environment]::NewLine + $tail)
}

Write-Host "[chatgpt] local synthetic MCP ready: $Endpoint"
Write-Host '[chatgpt] Admin API/UI are disabled on this endpoint.'
Write-Host '[chatgpt] OAuth is disabled ONLY for this loopback + Secure MCP Tunnel synthetic demo path.'
