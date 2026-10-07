#Requires -Version 5.1
<#
.SYNOPSIS
  Start THIS worktree's gateway as a second, detached instance next to the operator's gateway.

.DESCRIPTION
  Test-environment helper. It never touches the gateway on :21000. The 1C source credentials are
  read from ERP_MCP_818HA_USER / ERP_MCP_818HA_PASSWORD if already set in this shell, otherwise
  they are prompted for (password as SecureString) and exist only in the new process environment.
  Nothing secret is printed or written to disk. BAG_PUBLIC_MCP_URL stays the :21000 URL so tokens
  issued for the operator's gateway (audience http://127.0.0.1:21000/mcp) are accepted.

.PARAMETER Port            Listen port of the branch instance (default 21001).
.PARAMETER ProfilesFile    Optional provisional profiles JSON (absolute path); its sha256 is computed here.
.PARAMETER Stop            Stop a previously started branch instance and exit.
#>
[CmdletBinding()]
param(
    [int]$Port = 21001,
    [string]$ProfilesFile = '',
    [string]$TestbedDir = 'D:\ERP_MCP_Testbed\real1c_e2e',
    [string]$Python = 'D:\Repo\ERP_MCP-integration-candidate\.venv\Scripts\python.exe',
    [switch]$ReaderFromDpapi,
    [string]$ReaderSecretFile = 'D:\secrets\erp_mcp\test_reader_password.dpapi',
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$PidFile = Join-Path $TestbedDir "pids\gateway_branch_$Port.pid"

function Get-Listener([int]$P) {
    Get-NetTCPConnection -State Listen -LocalPort $P -ErrorAction SilentlyContinue | Select-Object -First 1
}

if ($Stop) {
    if (Test-Path $PidFile) {
        $target = [int](Get-Content $PidFile -Raw).Trim()
        & taskkill.exe /PID $target /T /F | Out-Null
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        Write-Host "stopped branch gateway (pid $target)"
    } else { Write-Host 'no pid file; nothing to stop' }
    return
}

if ($Port -eq 21000) { throw 'refusing to use :21000, that is the operator gateway' }
if (Get-Listener $Port) { throw "port $Port is already in use" }
if (-not (Test-Path $Python)) { throw "python not found: $Python" }
. (Join-Path $TestbedDir 'env.ps1')   # BAG_* for the real1c testbed (contains secrets; stays in this process)

if ($ReaderFromDpapi) {
    # Same identity and file the project's real-1C lane uses: DPAPI (CurrentUser) blob, decrypted in
    # this process only. Works only under the Windows account that created the blob.
    if (-not (Test-Path -LiteralPath $ReaderSecretFile)) { throw "DPAPI reader secret not found: $ReaderSecretFile" }
    Add-Type -AssemblyName System.Security
    $blob = [System.IO.File]::ReadAllBytes($ReaderSecretFile)
    $plain = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $blob, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
    $env:ERP_MCP_818HA_USER = 'ERP_MCP_TEST_READER'
    $env:ERP_MCP_818HA_PASSWORD = [System.Text.Encoding]::UTF8.GetString($plain)
    [Array]::Clear($plain, 0, $plain.Length)
}
if (-not $env:ERP_MCP_818HA_USER) {
    $env:ERP_MCP_818HA_USER = Read-Host 'ERP_MCP_818HA_USER (1C reader login)'
}
if (-not $env:ERP_MCP_818HA_PASSWORD) {
    $secure = Read-Host 'ERP_MCP_818HA_PASSWORD' -AsSecureString
    $env:ERP_MCP_818HA_PASSWORD = [System.Net.NetworkCredential]::new('', $secure).Password
}

if ($ProfilesFile) {
    if (-not [System.IO.Path]::IsPathRooted($ProfilesFile)) { throw 'ProfilesFile must be an absolute path' }
    $env:BAG_PROVISIONAL_PROFILES_FILE = $ProfilesFile
    $env:BAG_PROVISIONAL_PROFILES_SHA256 = (Get-FileHash $ProfilesFile -Algorithm SHA256).Hash.ToLower()
}

$env:PYTHONPATH = Join-Path $Root 'src'
$env:PYTHONIOENCODING = 'utf-8'
$logs = Join-Path $TestbedDir 'logs'
New-Item -ItemType Directory -Force -Path $logs, (Split-Path $PidFile) | Out-Null
$out = Join-Path $logs "gateway_branch_$Port.out.log"
$err = Join-Path $logs "gateway_branch_$Port.err.log"
$cmd = '/c ""' + $Python + '" -m uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port ' + $Port +
    ' --no-access-log > "' + $out + '" 2> "' + $err + '""'
$proc = Start-Process -FilePath $env:ComSpec -ArgumentList $cmd -WorkingDirectory $Root -WindowStyle Hidden -PassThru

# Do not let the launcher shell keep the credentials in its own environment.
Remove-Item Env:ERP_MCP_818HA_PASSWORD, Env:ERP_MCP_818HA_USER -ErrorAction SilentlyContinue
Set-Content -Path $PidFile -Value $proc.Id -Encoding ascii

$deadline = (Get-Date).AddSeconds(40)
while ((Get-Date) -lt $deadline -and -not (Get-Listener $Port)) {
    if ($proc.HasExited) { throw "branch gateway exited (code $($proc.ExitCode)); see $err" }
    Start-Sleep -Milliseconds 500
}
if (-not (Get-Listener $Port)) { throw "branch gateway did not open :$Port in time; see $err" }
Write-Host "branch gateway up on http://127.0.0.1:$Port/mcp (pid $($proc.Id)); worktree: $Root"
Write-Host "stop with: $PSCommandPath -Stop -Port $Port"
