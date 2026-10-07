#Requires -Version 5.1
<#
.SYNOPSIS
  Creates/updates a tunnel-client profile for the local ERP_MCP ChatGPT endpoint.

.NOTES
  CONTROL_PLANE_API_KEY is never persisted by this script. Set it in the current
  shell or allow this script to request it securely for this process only.
#>
[CmdletBinding()]
param(
    [string]$TunnelId = $env:OPENAI_TUNNEL_ID,
    [string]$Profile = 'erp-mcp-local',
    [string]$Endpoint = 'http://127.0.0.1:18100/mcp',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Client = Join-Path $Root '.chatgpt\bin\tunnel-client.exe'
if (-not (Test-Path $Client)) {
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'install-tunnel-client.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'tunnel-client installation failed' }
}
if (-not $TunnelId) {
    Write-Host 'ACTION REQUIRED: create/select a tunnel in OpenAI Platform tunnel settings.'
    Write-Host 'Then paste the tunnel_id below. The value is an identifier, not a secret.'
    $TunnelId = Read-Host 'Tunnel ID'
}
if ($TunnelId -notmatch '^tunnel_[A-Za-z0-9_-]+$') { throw 'invalid tunnel_id format' }

$temporaryKey = $false
if (-not $env:CONTROL_PLANE_API_KEY) {
    $secure = Read-Host 'Runtime API key (CONTROL_PLANE_API_KEY; input hidden)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $temporaryKey = $true
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}
if (-not $env:CONTROL_PLANE_API_KEY) { throw 'runtime API key is required' }

try {
    $args = @(
        'init',
        '--sample', 'sample_mcp_remote_no_auth',
        '--profile', $Profile,
        '--tunnel-id', $TunnelId,
        '--mcp-server-url', $Endpoint
    )
    if ($Force) { $args += '--force' }
    & $Client @args
    if ($LASTEXITCODE -ne 0) { throw 'tunnel-client init failed' }

    & $Client doctor --profile $Profile --explain
    if ($LASTEXITCODE -ne 0) { throw 'tunnel-client doctor failed' }

    New-Item -ItemType Directory -Force -Path (Join-Path $Root '.chatgpt') | Out-Null
    @{
        profile = $Profile
        tunnel_id = $TunnelId
        endpoint = $Endpoint
        configured_at_utc = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content -Path (Join-Path $Root '.chatgpt\tunnel.json') -Encoding UTF8

    Write-Host '[chatgpt] tunnel profile configured and doctor passed'
}
finally {
    if ($temporaryKey) { Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue }
}
