#Requires -Version 5.1
[CmdletBinding()]
param([string]$Profile = 'erp-mcp-local')

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Client = Join-Path $Root '.chatgpt\bin\tunnel-client.exe'
$TunnelMeta = Join-Path $Root '.chatgpt\tunnel.json'
$Endpoint = 'http://127.0.0.1:18100/mcp'
$failed = $false

function Check-Http([string]$Name, [string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) {
            Write-Host ('PASS  ' + $Name)
            return
        }
    } catch {}
    Write-Host ('FAIL  ' + $Name + '  ' + $Url)
    $script:failed = $true
}

Check-Http 'ERP_MCP /healthz' 'http://127.0.0.1:18100/healthz'
Check-Http 'ERP_MCP /readyz' 'http://127.0.0.1:18100/readyz'

if (-not (Test-Path $Py)) {
    Write-Host 'FAIL  project Python environment missing'
    $failed = $true
} else {
    Push-Location $Root
    try {
        & $Py scripts\chatgpt\mcp_smoke.py --url $Endpoint
        if ($LASTEXITCODE -eq 0) { Write-Host 'PASS  MCP discovery/read-only annotations' }
        else { Write-Host 'FAIL  MCP discovery/read-only annotations'; $failed = $true }
    } finally { Pop-Location }
}

if (-not (Test-Path $Client)) {
    Write-Host 'WARN  tunnel-client not installed yet'
} elseif (-not (Test-Path $TunnelMeta)) {
    Write-Host 'WARN  tunnel profile not configured yet'
} elseif (-not $env:CONTROL_PLANE_API_KEY) {
    Write-Host 'WARN  tunnel profile exists but CONTROL_PLANE_API_KEY is not set; tunnel doctor not executed'
} else {
    & $Client doctor --profile $Profile --explain
    if ($LASTEXITCODE -eq 0) { Write-Host 'PASS  Secure MCP Tunnel doctor' }
    else { Write-Host 'FAIL  Secure MCP Tunnel doctor'; $failed = $true }
}

if ($failed) {
    Write-Host 'CHATGPT MCP: NOT READY'
    exit 1
}
if ((Test-Path $TunnelMeta) -and $env:CONTROL_PLANE_API_KEY) {
    Write-Host 'CHATGPT MCP: LOCAL + TUNNEL CHECKS PASS'
} else {
    Write-Host 'CHATGPT MCP: LOCAL READY; OPENAI TUNNEL ACTION STILL REQUIRED'
}
