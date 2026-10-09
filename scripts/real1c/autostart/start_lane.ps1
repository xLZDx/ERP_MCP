#Requires -Version 5.1
<#
.SYNOPSIS
  Idempotently brings up the whole local real-1C ERP_MCP lane (ChatGPT connector ERP_MCP_REAL1) on this machine.
  Safe to run repeatedly: every component is started only when it is not already listening, so the same
  script is the logon starter and the 5-minute watchdog of the scheduled task "ERP_MCP_Lane_Autostart".

  Order: Docker Desktop + lane PostgreSQL/Redis -> Apache (1C OData publication) -> lane proxies 8191-8193
         -> real sidecar 21768 -> Cloudflare quick tunnel for the test IdP -> IdP 21080 -> gateway 21000
         -> OpenAI tunnel-client (profile erp-mcp-local).

  Known limitation: the IdP is published through a Cloudflare QUICK tunnel whose host changes whenever that
  tunnel restarts (for example after a reboot). This script rewrites the issuer host in env.ps1 and
  idp-config.json to the new host, but ChatGPT must press Reconnect once after such a change. A permanent host
  needs a named Cloudflare tunnel on a domain of the operator.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'

$Lane      = 'D:\ERP_MCP_Testbed\real1c_e2e'
$Runtime   = 'D:\Repo\ERP_MCP-supplier-debt-runtime'      # worktree that holds the gateway code and scripts\e2e
$LaneRepo  = 'D:\Repo\ERP_MCP-integration-candidate'      # owner of the venv used by the lane processes
$Py        = Join-Path $LaneRepo '.venv\Scripts\python.exe'
$Docker    = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$DockerUi  = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$Httpd     = 'D:\ERP_MCP_Testbed\apache24\bin\httpd.exe'
$HttpdConf = 'D:/ERP_MCP_Testbed/apache24/conf/httpd-erp-mcp-test-ready.conf'
$Node      = 'C:\Program Files\nodejs\node.exe'
$Sidecar   = 'D:\ERP_MCP_Testbed\real1c_sidecar_app'
$Cloudflared = 'D:\Repo\Personal_DC\vendor\tunnel-client\cloudflared.exe'
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
    if (-not (Test-Port 8088)) {
        Start-Hidden $Httpd @('-d', 'D:/ERP_MCP_Testbed/apache24', '-f', $HttpdConf) 'D:\ERP_MCP_Testbed\apache24' $null $null | Out-Null
        Log ('apache started: ' + (Wait-Port 8088 30))
    }

    # 3. Lane proxies in front of the 1C OData publication (read-only, GET/HEAD only)
    foreach ($port in 8191, 8192, 8193) {
        if (-not (Test-Port $port)) {
            $env:LANE_PROXY_PORT = [string]$port
            $env:LANE_PROXY_MODE = 'head_compat'
            Start-Hidden $Py @((Join-Path $Runtime 'scripts\real1c\lane_proxy.py')) $Runtime `
                (Join-Path $Logs ('lane_proxy_' + $port + '.out.log')) (Join-Path $Logs ('lane_proxy_' + $port + '.err.log')) | Out-Null
            Log ('lane proxy ' + $port + ' started: ' + (Wait-Port $port 30))
        }
    }
    Remove-Item Env:\LANE_PROXY_PORT, Env:\LANE_PROXY_MODE -ErrorAction SilentlyContinue

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

    # 5. Cloudflare quick tunnel for the test IdP, then align the issuer host with whatever host it got
    $idpUp = Test-Port 21080
    $tunnelLog = Join-Path $Logs 'idp_quick_tunnel.err.log'
    $running = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
        Where-Object { $_.CommandLine -match '127\.0\.0\.1:21080' }
    if (-not $running) {
        Remove-Item $tunnelLog -ErrorAction SilentlyContinue
        Start-Hidden $Cloudflared @('tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:21080') $Lane `
            (Join-Path $Logs 'idp_quick_tunnel.out.log') $tunnelLog | Out-Null
        Log 'idp quick tunnel started'
    }
    $host21080 = $null
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline -and -not $host21080) {
        if (Test-Path $tunnelLog) {
            $m = Select-String -Path $tunnelLog -Pattern 'https://([a-z0-9-]+\.trycloudflare\.com)' | Select-Object -Last 1
            if ($m) { $host21080 = $m.Matches[0].Groups[1].Value }
        }
        if (-not $host21080) { Start-Sleep -Seconds 2 }
    }
    if ($host21080) {
        $envPath = Join-Path $Lane 'env.ps1'
        $cfgPath = Join-Path $Lane 'idp-config.json'
        $envRaw = [IO.File]::ReadAllText($envPath)
        $current = [regex]::Match($envRaw, 'https://([a-z0-9-]+\.trycloudflare\.com)/realms/erp-mcp-test').Groups[1].Value
        if ($current -and $current -ne $host21080) {
            $utf8 = New-Object System.Text.UTF8Encoding($false)
            [IO.File]::WriteAllText($envPath, $envRaw.Replace($current, $host21080), $utf8)
            [IO.File]::WriteAllText($cfgPath, [IO.File]::ReadAllText($cfgPath).Replace($current, $host21080), $utf8)
            Log ('IdP public host changed ' + $current + ' -> ' + $host21080 + '; restarting IdP and gateway. ChatGPT must press Reconnect once.')
            foreach ($component in 'gateway', 'idp') {
                $env:E2E_DIR = $Lane; $env:E2E_REAL1C = '1'
                & (Join-Path $Runtime 'scripts\e2e\fault.ps1') -Component $component -Action stop *> $null
            }
        } else { Log ('IdP public host unchanged: ' + $host21080) }
    } else { Log 'WARN: quick tunnel host not detected within 60 s' }

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

    $state = foreach ($pair in @(@('postgres', 18432), @('redis', 19379), @('apache/1C', 8088), @('proxy8191', 8191), @('proxy8192', 8192),
            @('proxy8193', 8193), @('sidecar', 21768), @('idp', 21080), @('gateway', 21000))) { $pair[0] + '=' + (Test-Port $pair[1]) }
    Log ('summary: ' + ($state -join ' '))
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
