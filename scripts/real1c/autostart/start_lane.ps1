#Requires -Version 5.1
<#
.SYNOPSIS
  Idempotently brings up the whole local real-1C ERP_MCP lane (ChatGPT connector ERP_MCP_REAL1) on this machine.
  Safe to run repeatedly: every component is started only when it is not already listening, so the same
  script is the logon starter and the 5-minute watchdog of the scheduled task "ERP_MCP_Lane_Autostart".

  Order: Docker Desktop + lane PostgreSQL/Redis -> Apache (1C OData publication) -> lane proxies 8191-8193
         -> real sidecar 21768 -> Tailscale Funnel host for the test IdP -> IdP 21080 -> gateway 21000
         -> OpenAI tunnel-client (profile erp-mcp-local).

  The IdP is published through Tailscale Funnel on this machine, so its public host is stable. If the host ever
  differs from the issuer in env.ps1 and idp-config.json, this script rewrites both and restarts the IdP and
  gateway; ChatGPT must then press Reconnect once. The tunnel-client profile must trust the same origin
  (mcp.oauth_trusted_origins in the tunnel-client profile erp-mcp-local).
#>
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$ApachePort = 18088
)
$ErrorActionPreference = 'Continue'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Lane      = 'D:\ERP_MCP_Testbed\real1c_e2e'
$Runtime   = $ProjectRoot
$Py        = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Docker    = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$DockerUi  = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$Httpd     = 'D:\ERP_MCP_Testbed\apache24\bin\httpd.exe'
$HttpdConf = "D:/ERP_MCP_Testbed/apache24/conf/httpd-erp-mcp-test-ready-$ApachePort.conf"
$Node      = 'C:\Program Files\nodejs\node.exe'
$Sidecar   = 'D:\ERP_MCP_Testbed\real1c_sidecar_app'
$Tailscale = 'C:\Program Files\Tailscale\tailscale.exe'
$TunnelPs1 = 'D:\Repo\ERP_MCP-chatgpt\.chatgpt\start-real1c-tunnel.ps1'
$Logs      = Join-Path $Lane 'logs'
$LogFile   = Join-Path $Logs 'autostart.log'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Log([string]$Message) {
    $line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Port([int]$Port, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Start-Hidden([string]$File, [string[]]$ArgumentList, [string]$WorkDir, [string]$Out, [string]$Err) {
    $params = @{ FilePath = $File; WorkingDirectory = $WorkDir; WindowStyle = 'Hidden'; PassThru = $true }
    if ($ArgumentList) { $params.ArgumentList = $ArgumentList }
    if ($Out) { $params.RedirectStandardOutput = $Out; $params.RedirectStandardError = $Err }
    return Start-Process @params
}

# Mutex: the logon starter and the watchdog must never run side by side.
$mutex = New-Object System.Threading.Mutex($false, 'Global\ERP_MCP_Lane_Autostart')
if (-not $mutex.WaitOne(0)) { Log 'another autostart run is active, exiting'; exit 0 }
try {
    Log '=== lane autostart pass ==='

    # 1. Docker Desktop and the lane database / cache
    & $Docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Log 'docker daemon not reachable, starting Docker Desktop'
        if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Start-Process -FilePath $DockerUi -WindowStyle Hidden
        }
        $deadline = (Get-Date).AddMinutes(4)
        do { Start-Sleep -Seconds 5; & $Docker info *> $null } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $deadline)
    }
    & $Docker info *> $null
    if ($LASTEXITCODE -ne 0) { Log 'FAIL: docker daemon did not come up; lane cannot start'; exit 1 }
    foreach ($name in 'erpmcp-e2e-real1c-postgres-1', 'erpmcp-e2e-real1c-redis-1') {
        & $Docker update --restart unless-stopped $name *> $null
        if (-not (& $Docker ps -q -f ("name=" + $name))) { & $Docker start $name *> $null; Log ('docker start ' + $name) }
    }
    if (-not (Wait-Port 18432 60)) { Log 'WARN: lane PostgreSQL port 18432 is not listening' }
    if (-not (Wait-Port 19379 60)) { Log 'WARN: lane Redis port 19379 is not listening' }

    # 2. Apache with the 1C OData publication (file base 818HA_test_ready)
    if (-not (Test-Port $ApachePort)) {
        if (-not (Test-Path -LiteralPath $HttpdConf -PathType Leaf)) {
            Log ('FAIL: Apache configuration not found for port ' + $ApachePort)
            exit 1
        }
        Start-Hidden $Httpd @('-d', 'D:/ERP_MCP_Testbed/apache24', '-f', $HttpdConf) 'D:\ERP_MCP_Testbed\apache24' $null $null | Out-Null
        Log ('apache started on ' + $ApachePort + ': ' + (Wait-Port $ApachePort 30))
    }

    # 3. Lane proxies in front of the 1C OData publication (read-only, GET/HEAD only)
    foreach ($port in 8191, 8192, 8193) {
        if (-not (Test-Port $port)) {
            $env:LANE_PROXY_PORT = [string]$port
            $env:LANE_PROXY_MODE = 'head_compat'
            $env:LANE_PROXY_UPSTREAM = "http://127.0.0.1:$ApachePort"
            Start-Hidden $Py @((Join-Path $Runtime 'scripts\real1c\lane_proxy.py')) $Runtime `
                (Join-Path $Logs ('lane_proxy_' + $port + '.out.log')) (Join-Path $Logs ('lane_proxy_' + $port + '.err.log')) | Out-Null
            Log ('lane proxy ' + $port + ' started: ' + (Wait-Port $port 30))
        }
    }
    Remove-Item Env:\LANE_PROXY_PORT, Env:\LANE_PROXY_MODE, Env:\LANE_PROXY_UPSTREAM -ErrorAction SilentlyContinue

    # 4. Real sidecar (loopback only, reads the same token the gateway uses)
    if (-not (Test-Port 21768)) {
        $envText = Get-Content (Join-Path $Lane 'env.ps1') -Raw
        if ($envText -match "\`$env:BAG_ODATA_SIDECAR_TOKEN = '([^']*)'") {
            $env:SIDECAR_TOKEN = $Matches[1]
            $env:ONEC_ALLOWED_HOSTS = '127.0.0.1:8191,127.0.0.1:8192,127.0.0.1:8193'
            $env:ONEC_EGRESS_CIDRS = '127.0.0.1/32'
            $env:PORT = '21768'
            Start-Hidden $Node @('lane_start.mjs') $Sidecar (Join-Path $Logs 'real_sidecar.out.log') (Join-Path $Logs 'real_sidecar.err.log') | Out-Null
            Remove-Item Env:\SIDECAR_TOKEN, Env:\ONEC_ALLOWED_HOSTS, Env:\ONEC_EGRESS_CIDRS, Env:\PORT -ErrorAction SilentlyContinue
            Log ('real sidecar started: ' + (Wait-Port 21768 30))
        } else { Log 'FAIL: BAG_ODATA_SIDECAR_TOKEN not found in env.ps1' }
    }

    # 5. Stable public host for the test IdP: Tailscale Funnel on this machine (the host never changes)
    $funnelHost = $null
    try {
        $dns = ((& $Tailscale status --json 2>$null) | ConvertFrom-Json).Self.DNSName
        if ($dns) { $funnelHost = $dns.TrimEnd('.') }
    } catch { }
    if ($funnelHost) {
        $funnelState = (& $Tailscale funnel status 2>&1 | Out-String)
        if ($funnelState -notmatch '21080') {
            & $Tailscale funnel --bg 21080 *> $null
            Log ('tailscale funnel to 21080 started for ' + $funnelHost)
        }
        $envPath = Join-Path $Lane 'env.ps1'
        $cfgPath = Join-Path $Lane 'idp-config.json'
        $envRaw = [IO.File]::ReadAllText($envPath)
        $current = [regex]::Match($envRaw, 'https://([A-Za-z0-9.-]+)/realms/erp-mcp-test').Groups[1].Value
        if ($current -and $current -ne $funnelHost) {
            $utf8 = New-Object System.Text.UTF8Encoding($false)
            [IO.File]::WriteAllText($envPath, $envRaw.Replace($current, $funnelHost), $utf8)
            [IO.File]::WriteAllText($cfgPath, [IO.File]::ReadAllText($cfgPath).Replace($current, $funnelHost), $utf8)
            Log ('IdP public host changed ' + $current + ' -> ' + $funnelHost + '; restarting IdP and gateway. ChatGPT must press Reconnect once.')
            foreach ($component in 'gateway', 'idp') {
                $env:E2E_DIR = $Lane; $env:E2E_REAL1C = '1'
                & (Join-Path $Runtime 'scripts\e2e\fault.ps1') -Component $component -Action stop *> $null
            }
        } else { Log ('IdP public host unchanged: ' + $funnelHost) }
    } else { Log 'WARN: Tailscale DNS name not available; IdP host not checked' }

    # 6. IdP and gateway through the project scripts (idempotent; they refuse to start without reader credentials)
    $env:E2E_DIR = $Lane
    $env:E2E_REAL1C = '1'
    foreach ($component in 'idp', 'gateway') {
        $port = if ($component -eq 'idp') { 21080 } else { 21000 }
        if (-not (Test-Port $port)) {
            & (Join-Path $Runtime 'scripts\e2e\fault.ps1') -Component $component -Action start *>> $LogFile
            Log ($component + ' started: ' + (Test-Port $port))
        }
    }

    # 7. OpenAI tunnel-client for the ChatGPT connector
    $client = Get-CimInstance Win32_Process -Filter "Name='tunnel-client.exe'" | Where-Object { $_.CommandLine -match 'erp-mcp-local' }
    if (-not $client) {
        $out = 'D:\Repo\ERP_MCP-chatgpt\.chatgpt\logs\tunnel.out.log'
        $err = 'D:\Repo\ERP_MCP-chatgpt\.chatgpt\logs\tunnel.err.log'
        Start-Hidden 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $TunnelPs1) 'D:\Repo\ERP_MCP-chatgpt' $out $err | Out-Null
        Start-Sleep -Seconds 5
        Log ('tunnel-client started: ' + [bool](Get-CimInstance Win32_Process -Filter "Name='tunnel-client.exe'" | Where-Object { $_.CommandLine -match 'erp-mcp-local' }))
    }

    $state = foreach ($pair in @(@('postgres', 18432), @('redis', 19379), @('apache/1C', $ApachePort), @('proxy8191', 8191), @('proxy8192', 8192),
            @('proxy8193', 8193), @('sidecar', 21768), @('idp', 21080), @('gateway', 21000))) { $pair[0] + '=' + (Test-Port $pair[1]) }
    Log ('summary: ' + ($state -join ' '))
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
