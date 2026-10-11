<#
.SYNOPSIS
  Runs the OpenAI tunnel-client on the 1C host. The runtime API key is decrypted in-process from its DPAPI blob and exists only
  in this process environment. Actions: Doctor (validate configuration and reachability) or Run (long-lived daemon).
#>
[CmdletBinding()]
param(
    [ValidateSet('Doctor', 'Run')][string]$Action = 'Run',
    [string]$Root = 'D:\1c\mcp',
    [string]$McpUrl = 'http://100.88.71.74:21000/mcp',
    [string]$HealthAddr = '127.0.0.1:21090',
    [string]$IssuerOrigin = 'https://ivan.tail08f9f9.ts.net'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
$cfg = Get-Content (Join-Path $Root 'env\tunnel.json') -Raw | ConvertFrom-Json
$blob = [IO.File]::ReadAllBytes((Join-Path $Root 'env\tunnel_api_key.dpapi'))
$plain = [Security.Cryptography.ProtectedData]::Unprotect($blob, $null, 'CurrentUser')
$env:CONTROL_PLANE_API_KEY = [Text.UTF8Encoding]::new($false).GetString($plain)
[Array]::Clear($plain, 0, $plain.Length)
$client = Join-Path $Root 'tunnel\tunnel-client.exe'
$common = @('--control-plane.tunnel-id', $cfg.tunnel_id, '--control-plane.api-key', 'env:CONTROL_PLANE_API_KEY', '--mcp.server-url', $McpUrl, '--mcp.oauth-trusted-origin', $IssuerOrigin, '--harpoon.allow-plaintext-http', '--health.listen-addr', $HealthAddr)
try {
    if ($Action -eq 'Doctor') { & $client doctor @common 2>&1 | ForEach-Object { "$_" } }
    else { & $client run @common }
    exit $LASTEXITCODE
} finally { Remove-Item Env:\CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue }
