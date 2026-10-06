#Requires -Version 5.1
<#
.SYNOPSIS
  Print the localhost MCP endpoint and mint a test token for user_company_one; launch MCP
  Inspector (Streamable HTTP) when npx is available and -NoLaunch is not given.
  The token is written to .e2e/user-client-token.txt (git-ignored) and not printed unless
  -ShowToken is given.
#>
[CmdletBinding()]
param([string]$User = 'user_company_one', [switch]$NoLaunch, [switch]$ShowToken)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

if (-not (Test-Path (Join-Path $script:E2eDir 'env.json'))) { throw 'environment missing; run up.ps1' }
$mint = 'powershell -File scripts\e2e\open-user-client.ps1 -User ' + $User
Import-E2eEnv
try {
    $token = ((Invoke-Envctl @('mint', '--user', $User, '--audience', 'data') -Quiet)[0] |
        Select-Object -Last 1).Trim()
} finally { Clear-E2eSecretEnv }
$tokenFile = Join-Path $script:E2eDir 'user-client-token.txt'
Set-Content -Path $tokenFile -Value $token -Encoding ascii -NoNewline

Write-Host 'MCP endpoint (Streamable HTTP): http://127.0.0.1:18000/mcp'
Write-Host ('Identity: ' + $User + '  audience http://127.0.0.1:18000/mcp  scope onec:read (valid ~1h)')
Write-Host ('Token file: ' + $tokenFile)
Write-Host ('Re-mint: ' + $mint)
if ($ShowToken) { Write-Host ('Authorization: Bearer ' + $token) }
$npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
if ($npx -and -not $NoLaunch) {
    Write-Host 'Launching MCP Inspector (npx @modelcontextprotocol/inspector)...'
    Write-Host 'In the UI: Transport = Streamable HTTP, URL = http://127.0.0.1:18000/mcp,'
    Write-Host 'Authentication > Custom Headers: Authorization = Bearer <contents of token file>.'
    Start-Process -FilePath $npx.Source -ArgumentList @('-y', '@modelcontextprotocol/inspector')
} else {
    Write-Host 'Manual steps: install Node.js, run `npx @modelcontextprotocol/inspector`, choose'
    Write-Host 'Streamable HTTP, URL http://127.0.0.1:18000/mcp, add header'
    Write-Host 'Authorization: Bearer <contents of the token file>. Any MCP client works the same way.'
}
