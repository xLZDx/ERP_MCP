<#
.SYNOPSIS
  Idempotent starter for the ERP_MCP test stack on the 1C host: PostgreSQL, Redis, Apache (1C OData), lane proxies,
  OData sidecar, test IdP and the MCP gateway. Safe to run repeatedly: a component starts only when its port is closed.
  Intended to run from a scheduled task (so the processes outlive the SSH session). Actions: Start (default), Status.

  Secrets: the gateway env file and the 1C reader DPAPI blob stay under -Root\env (ACL: user + Administrators).
  The reader password is decrypted in-process and exists only in the gateway process environment.
#>
[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status')][string]$Action = 'Start',
    [string]$Root = 'D:\1c\mcp',
    [string]$BindIp = '100.88.71.74'
)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Security

$Logs = Join-Path $Root 'logs'
$EnvDir = Join-Path $Root 'env'
$App = Join-Path $Root 'app\gateway'
$Py = Join-Path $Root 'venv\Scripts\python.exe'
$Node = Join-Path $Root 'runtime\node\node.exe'
$Sidecar = Join-Path $Root 'app\sidecar\real1c_sidecar_app'
$Httpd = 'D:\1c\env\apache24\bin\httpd.exe'
$LogFile = Join-Path $Logs 'stack.log'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Log([string]$m) { Add-Content -Path $LogFile -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $m) -Encoding UTF8 }
function Test-Port([int]$p) { [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue) }
function Wait-Port([int]$p, [int]$s) { $e = (Get-Date).AddSeconds($s); while ((Get-Date) -lt $e) { if (Test-Port $p) { return $true }; Start-Sleep -Seconds 2 }; return $false }
function Start-Hidden([string]$File, [string[]]$Args2, [string]$Dir, [string]$Name) {
    $p = @{ FilePath = $File; WorkingDirectory = $Dir; WindowStyle = 'Hidden'; PassThru = $true
            RedirectStandardOutput = (Join-Path $Logs ($Name + '.out.log')); RedirectStandardError = (Join-Path $Logs ($Name + '.err.log')) }
    if ($Args2) { $p.ArgumentList = $Args2 }
    Start-Process @p | Out-Null
}

$ports = [ordered]@{ postgres = 18432; redis = 19379; apache = 8088; proxy8191 = 8191; proxy8192 = 8192; proxy8193 = 8193; sidecar = 21768; idp = 21080; gateway = 21000 }
if ($Action -eq 'Status') { foreach ($k in $ports.Keys) { $k + '=' + (Test-Port $ports[$k]) }; return }

$mutex = New-Object System.Threading.Mutex($false, 'Global\ERP_MCP_Ivan_Stack')
if (-not $mutex.WaitOne(0)) { Log 'another run is active, exiting'; return }
try {
    Log '=== stack pass ==='
    # 1. PostgreSQL + Redis (portable, detached through WMI by the helper)
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'setup-mcp-data.ps1') -Action Start *>> $LogFile

    # 2. Apache with the 1C OData publication
    if (-not (Test-Port 8088)) {
        Start-Hidden $Httpd @('-d', 'D:/1c/env/apache24', '-f', 'D:/1c/env/apache24/conf/httpd-erp-mcp-remote.conf') 'D:\1c\env\apache24' 'apache'
        Log ('apache: ' + (Wait-Port 8088 30))
    }

    # 3. Lane proxies (read-only GET/HEAD) in front of the OData publication
    foreach ($port in 8191, 8192, 8193) {
        if (-not (Test-Port $port)) {
            $env:PYTHONPATH = (Join-Path $App 'src') + ';' + $App
            $env:LANE_PROXY_PORT = [string]$port
            $env:LANE_PROXY_MODE = 'head_compat'
            Start-Hidden $Py @((Join-Path $App 'scripts\real1c\lane_proxy.py')) $App ('lane_proxy_' + $port)
            Log ('proxy ' + $port + ': ' + (Wait-Port $port 30))
        }
    }
    Remove-Item Env:\LANE_PROXY_PORT, Env:\LANE_PROXY_MODE, Env:\PYTHONPATH -ErrorAction SilentlyContinue

    # load the gateway env (sets $env:* for this process only)
    . (Join-Path $EnvDir 'gateway.env.ps1')

    # 4. OData sidecar (loopback only)
    if (-not (Test-Port 21768)) {
        $env:SIDECAR_TOKEN = $env:BAG_ODATA_SIDECAR_TOKEN
        $env:ONEC_ALLOWED_HOSTS = '127.0.0.1:8191,127.0.0.1:8192,127.0.0.1:8193'
        $env:ONEC_EGRESS_CIDRS = '127.0.0.1/32'
        $env:PORT = '21768'
        Start-Hidden $Node @('lane_start.mjs') $Sidecar 'sidecar'
        Remove-Item Env:\SIDECAR_TOKEN, Env:\ONEC_ALLOWED_HOSTS, Env:\ONEC_EGRESS_CIDRS, Env:\PORT -ErrorAction SilentlyContinue
        Log ('sidecar: ' + (Wait-Port 21768 30))
    }

    # 5. Test IdP (loopback; the gateway reads its JWKS locally)
    if (-not (Test-Port 21080)) {
        $env:E2E_IDP_CONFIG = Join-Path $EnvDir 'idp-config.json'
        $env:PYTHONPATH = (Join-Path $App 'src') + ';' + $App
        Start-Hidden $Py @('-m', 'testbed.idp') $App 'idp'
        Log ('idp: ' + (Wait-Port 21080 30))
        Remove-Item Env:\E2E_IDP_CONFIG -ErrorAction SilentlyContinue
    }

    # 6. Gateway (needs the reader pair in its environment before it starts)
    if (-not (Test-Port 21000)) {
        $blob = [IO.File]::ReadAllBytes((Join-Path $EnvDir 'test_reader_password.dpapi'))
        $plain = [Security.Cryptography.ProtectedData]::Unprotect($blob, $null, 'CurrentUser')
        $env:ERP_MCP_818HA_USER = 'ERP_MCP_TEST_READER'
        $env:ERP_MCP_818HA_PASSWORD = [Text.UTF8Encoding]::new($false).GetString($plain)
        [Array]::Clear($plain, 0, $plain.Length)
        $env:BAG_MACHINE_RECONCILED_SOURCES = 'onec-818ha-reference'
        $env:PYTHONPATH = (Join-Path $App 'src') + ';' + $App
        Start-Hidden $Py @('-m', 'uvicorn', 'business_ai_gateway.app:app', '--host', $BindIp, '--port', '21000', '--no-access-log') $App 'gateway'
        Remove-Item Env:\ERP_MCP_818HA_USER, Env:\ERP_MCP_818HA_PASSWORD -ErrorAction SilentlyContinue
        Log ('gateway: ' + (Wait-Port 21000 60))
    }
    Log ('summary: ' + ((($ports.Keys | ForEach-Object { $_ + '=' + (Test-Port $ports[$_]) })) -join ' '))
}
finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
