<#
.SYNOPSIS
  Runs on the 1C host. Mints a long-lived TEST token for the read-only test user from the local test IdP and writes ONLY the token to stdout.
  The caller must consume stdout without echoing it. Test environment only (password grant against the lane IdP).
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\1c\mcp',
    [string]$User = 'auditor',
    [long]$Ttl = 315360000,
    [string]$Audience = 'http://100.88.71.74:21000/mcp'
)
$ErrorActionPreference = 'Stop'
$cfg = Get-Content (Join-Path $Root 'env\idp-config.json') -Raw | ConvertFrom-Json
$cred = Get-Content (Join-Path $Root 'env\credentials.json') -Raw | ConvertFrom-Json
$client = $cfg.clients | Where-Object { $_.client_id -eq 'erp-mcp-headless-e2e' } | Select-Object -First 1
$pw = $cred.users.$User.password
$token = (Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/token' -Body @{
        grant_type = 'password'; client_id = $client.client_id; client_secret = $client.secret
        username = $User; password = $pw; audience = $Audience; scope = 'onec:read'; ttl = [string]$Ttl
    }).access_token
[Console]::Out.Write($token)
