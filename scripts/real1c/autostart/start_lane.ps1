#Requires -Version 5.1
<#
.SYNOPSIS
  Idempotently brings up the whole local real-1C ERP_MCP lane (ChatGPT connector ERP_MCP_REAL1) on this machine.
  Safe to run repeatedly: every component is started only when it is not already listening, so the same
  script is the logon starter for the scheduled task "ERP_MCP_Lane_Autostart". It has no periodic watchdog trigger.

  Order: Docker Desktop + lane PostgreSQL/Redis -> Apache (1C OData publication) -> lane proxies 8191-8193
         -> real sidecar 21768 -> Cloudflare Tunnel host for the test IdP -> IdP 21080 -> gateway 21000
         -> OpenAI tunnel-client (profile erp-mcp-local).

  The IdP is published through the remotely managed Cloudflare Tunnel. Tailscale remains available for private
  machine access, but this startup script never starts Funnel or changes the public issuer back to Tailscale.
  The tunnel-client profile remains a separate MCP connection and trusts the origin configured in its own profile.
#>
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$ApachePort = 18088
)
$ErrorActionPreference = 'Continue'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Lane      = 'D:\ERP_MCP_Testbed\real1c_e2e'
$laneTopology = Get-Content -LiteralPath (Join-Path $Lane 'env.json') -Raw | ConvertFrom-Json
$PostgresPort = [int]$laneTopology.ports.postgres
$RedisPort = [int]$laneTopology.ports.redis
$Runtime   = $ProjectRoot
$Py        = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$CredentialsValidator = Join-Path $ProjectRoot 'scripts\real1c\validate_e2e_credentials.py'
$IdpConfigPath = Join-Path $Lane 'idp-config.json'
$Docker    = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
$DockerUi  = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$Httpd     = 'D:\ERP_MCP_Testbed\apache24\bin\httpd.exe'
$HttpdConf = "D:/ERP_MCP_Testbed/apache24/conf/httpd-erp-mcp-test-ready-$ApachePort.conf"
$Node      = 'C:\Program Files\nodejs\node.exe'
$Sidecar   = 'D:\ERP_MCP_Testbed\real1c_sidecar_app'
$TunnelPs1 = 'D:\Repo\ERP_MCP-chatgpt\.chatgpt\start-real1c-tunnel.ps1'
$IdpEnvPath = Join-Path $Lane 'env.ps1'
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

function Stop-GatewayFailClosed([string]$Reason) {
    if (-not (Test-Port 21000)) { return $true }
    $env:E2E_DIR = $Lane
    $env:E2E_REAL1C = '1'
    & (Join-Path $Runtime 'scripts\e2e\fault.ps1') -Component 'gateway' -Action stop *> $null
    if (Test-Port 21000) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 21000 -ErrorAction SilentlyContinue |
            ForEach-Object { 'port=' + $_.LocalPort + ' pid=' + $_.OwningProcess })
        if ($listeners.Count -eq 0) { $listeners = @('port=21000 pid=unknown') }
        Log ('FAIL: gateway stop unconfirmed (' + $Reason + '); ' + ($listeners -join ', '))
        return $false
    }
    Log ('gateway stopped fail-closed (' + $Reason + ')')
    return $true
}

function Wait-Port([int]$Port, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Get-LaneEnvIssuer([string]$Text) {
    $matches = [regex]::Matches($Text, '(?m)^\s*\$env:BAG_OAUTH_ISSUER\s*=\s*([''"])(?<issuer>[^''"]+)\1\s*(?:#.*)?$')
    if ($matches.Count -lt 1) { throw 'ENV_ISSUER_MISSING' }
    $issuers = @($matches | ForEach-Object { $_.Groups['issuer'].Value } | Sort-Object -Unique)
    if ($issuers.Count -ne 1) { throw 'ENV_ISSUER_AMBIGUOUS' }
    $issuer = [string]$issuers[0]
    [Uri]$issuerUri = $null
    if (-not [Uri]::TryCreate($issuer, [UriKind]::Absolute, [ref]$issuerUri) -or
            $issuerUri.Scheme -cne 'https' -or
            $issuerUri.AbsolutePath -cne '/realms/erp-mcp-test' -or
            $issuerUri.Query -or $issuerUri.Fragment) {
        throw 'ENV_ISSUER_INVALID'
    }
    return $issuer
}

function Test-CloudflareIdpRoute([string]$ExpectedIssuer) {
    $localBase = 'http://127.0.0.1:21080'
    $realmPath = '/realms/erp-mcp-test'
    $publicDiscoveryUri = $ExpectedIssuer + '/.well-known/openid-configuration'
    $localDiscoveryUri = $localBase + $realmPath + '/.well-known/openid-configuration'
    $localJwksUri = $localBase + $realmPath + '/protocol/openid-connect/certs'
    $expectedHost = ([Uri]$ExpectedIssuer).Host
    $lastFailure = 'NO_RESPONSE'

    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $publicDiscovery = Invoke-RestMethod -Uri $publicDiscoveryUri -Method Get -TimeoutSec 4 -UseBasicParsing -ErrorAction Stop
            $localDiscovery = Invoke-RestMethod -Uri $localDiscoveryUri -Method Get -TimeoutSec 4 -UseBasicParsing -ErrorAction Stop
            if ($publicDiscovery.issuer -cne $ExpectedIssuer -or $localDiscovery.issuer -cne $ExpectedIssuer) {
                throw 'ISSUER_MISMATCH'
            }

            foreach ($field in 'authorization_endpoint', 'token_endpoint', 'jwks_uri') {
                [Uri]$endpoint = $null
                if (-not [Uri]::TryCreate([string]$publicDiscovery.$field, [UriKind]::Absolute, [ref]$endpoint) -or
                        $endpoint.Scheme -ne 'https' -or $endpoint.Host -ine $expectedHost) {
                    throw 'PUBLIC_ENDPOINT_MISMATCH'
                }
            }

            $publicJwks = Invoke-RestMethod -Uri ([string]$publicDiscovery.jwks_uri) -Method Get -TimeoutSec 4 -UseBasicParsing -ErrorAction Stop
            $localJwks = Invoke-RestMethod -Uri $localJwksUri -Method Get -TimeoutSec 4 -UseBasicParsing -ErrorAction Stop
            $publicKeys = @($publicJwks.keys | Sort-Object kid | ForEach-Object {
                '{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}|{8}' -f $_.kid, $_.kty, $_.n, $_.e, $_.x, $_.y, $_.crv, $_.alg, $_.use
            })
            $localKeys = @($localJwks.keys | Sort-Object kid | ForEach-Object {
                '{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}|{8}' -f $_.kid, $_.kty, $_.n, $_.e, $_.x, $_.y, $_.crv, $_.alg, $_.use
            })
            if ($publicKeys.Count -eq 0 -or $localKeys.Count -eq 0 -or
                    (($publicKeys -join "`n") -cne ($localKeys -join "`n"))) {
                throw 'JWKS_INSTANCE_MISMATCH'
            }
            return $true
        } catch {
            $lastFailure = $_.Exception.GetType().Name
            if ($attempt -lt 5) { Start-Sleep -Seconds 2 }
        }
    }

    Log ('FAIL: Cloudflare IdP route did not match the local IdP after bounded retries (' + $lastFailure + ')')
    return $false
}

function Start-Hidden([string]$File, [string[]]$ArgumentList, [string]$WorkDir, [string]$Out, [string]$Err) {
    $params = @{ FilePath = $File; WorkingDirectory = $WorkDir; WindowStyle = 'Hidden'; PassThru = $true }
    if ($ArgumentList) { $params.ArgumentList = $ArgumentList }
    if ($Out) { $params.RedirectStandardOutput = $Out; $params.RedirectStandardError = $Err }
    return Start-Process @params
}

function Test-DockerDaemon([int]$TimeoutMilliseconds = 10000) {
    $process = $null
    try {
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $Docker
        $startInfo.Arguments = 'ps -q'
        $startInfo.WorkingDirectory = $Runtime
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            Log 'docker ps connectivity probe could not start'
            return $false
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            $processId = $process.Id
            $terminated = $false
            try {
                $process.Kill()
                $terminated = $process.WaitForExit(5000)
            } catch { }
            if ($terminated) {
                $stdoutTask.GetAwaiter().GetResult() | Out-Null
                $stderrTask.GetAwaiter().GetResult() | Out-Null
                Log ('docker ps connectivity probe timed out after ' + $TimeoutMilliseconds + ' ms; child ' + $processId + ' terminated')
            } else {
                $script:DockerProbeUnsafe = $true
                Log ('docker ps connectivity probe timed out after ' + $TimeoutMilliseconds + ' ms; child ' + $processId + ' termination not confirmed')
            }
            return $false
        }
        $process.WaitForExit()
        $stdoutTask.GetAwaiter().GetResult() | Out-Null
        $stderrTask.GetAwaiter().GetResult() | Out-Null
        return ($process.ExitCode -eq 0)
    } catch {
        Log ('docker ps connectivity probe failed: ' + $_.Exception.GetType().Name)
        return $false
    } finally {
        if ($null -ne $process) { $process.Dispose() }
    }
}

# Mutex: logon startup and any manual one-shot restart must never run side by side.
$mutex = New-Object System.Threading.Mutex($false, 'Global\ERP_MCP_Lane_Autostart')
if (-not $mutex.WaitOne(0)) { Log 'another autostart run is active, exiting'; exit 0 }
try {
    $script:DockerProbeUnsafe = $false
    Log '=== lane autostart pass ==='

    # Validate test-IdP credentials before starting or changing any lane component.
    $credentialsPath = $null
    if (-not (Test-Path -LiteralPath $Py -PathType Leaf) -or
            -not (Test-Path -LiteralPath $CredentialsValidator -PathType Leaf) -or
            -not (Test-Path -LiteralPath $IdpConfigPath -PathType Leaf)) {
        Log 'FAIL: test-IdP credential preflight inputs are missing; lane components were not started'
        exit 1
    }
    try {
        $idpConfig = Get-Content -LiteralPath $IdpConfigPath -Raw | ConvertFrom-Json -ErrorAction Stop
        $idpEnvText = [IO.File]::ReadAllText($IdpEnvPath)
        $envIssuer = Get-LaneEnvIssuer $idpEnvText
        $targetIdpIssuer = 'https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test'
        if ($null -eq $idpConfig -or $idpConfig.credentials_path -isnot [string] -or
                [string]::IsNullOrWhiteSpace($idpConfig.credentials_path)) { throw 'CONFIG_INVALID' }
        if ($idpConfig.issuer -isnot [string] -or $idpConfig.issuer -cne $envIssuer -or
                $envIssuer -cne $targetIdpIssuer) { throw 'ISSUER_CONFIG_MISMATCH' }
        $credentialsPath = [IO.Path]::GetFullPath($idpConfig.credentials_path)
        $laneRoot = [IO.Path]::GetFullPath($Lane).TrimEnd('\') + '\'
        if (-not $credentialsPath.StartsWith($laneRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'CREDENTIAL_PATH_OUTSIDE_LANE'
        }
    } catch {
        Log 'FAIL: test-IdP configuration preflight failed; lane components were not started'
        if (-not (Stop-GatewayFailClosed 'issuer/credential preflight failed')) {
            Log 'FAIL: startup aborted with gateway listener still present'
            exit 1
        }
        exit 1
    }
    if (-not (Test-Path -LiteralPath $credentialsPath -PathType Leaf)) {
        Log 'FAIL: configured test-IdP credential file is missing; lane components were not started'
        exit 1
    }
    & $Py $CredentialsValidator $credentialsPath *>> $LogFile
    if ($LASTEXITCODE -ne 0) {
        Log 'FAIL: test-IdP credential preflight failed; lane components were not started'
        exit 1
    }

    # 1. Docker Desktop and the lane database / cache
    $dockerReady = Test-DockerDaemon
    if ($script:DockerProbeUnsafe) {
        Log 'FAIL: docker probe child termination is unconfirmed; refusing further probes and lane startup'
        exit 1
    }
    if (-not $dockerReady) {
        Log 'docker daemon connection failed, starting Docker Desktop'
        if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Start-Process -FilePath $DockerUi -WindowStyle Hidden
        }
        $deadline = (Get-Date).AddMinutes(4)
        do {
            Start-Sleep -Seconds 5
            $remainingMilliseconds = [int][Math]::Floor(($deadline - (Get-Date)).TotalMilliseconds)
            if ($remainingMilliseconds -le 0) { break }
            $dockerReady = Test-DockerDaemon -TimeoutMilliseconds ([Math]::Min(30000, $remainingMilliseconds))
            if ($script:DockerProbeUnsafe) { break }
        } while (-not $dockerReady -and (Get-Date) -lt $deadline)
    }
    if ($script:DockerProbeUnsafe) {
        Log 'FAIL: docker probe child termination is unconfirmed; refusing further probes and lane startup'
        exit 1
    }
    $dockerReady = Test-DockerDaemon
    if (-not $dockerReady) { Log 'FAIL: docker daemon did not come up; lane cannot start'; exit 1 }
    foreach ($name in 'erpmcp-e2e-real1c-postgres-1', 'erpmcp-e2e-real1c-redis-1') {
        & $Docker update --restart unless-stopped $name *> $null
        if (-not (& $Docker ps -q -f ("name=" + $name))) { & $Docker start $name *> $null; Log ('docker start ' + $name) }
    }
    if (-not (Wait-Port $PostgresPort 60)) { Log ('WARN: lane PostgreSQL port ' + $PostgresPort + ' is not listening') }
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

    # 5. Start the local IdP, prove the public Cloudflare route reaches this key set, then start the gateway.
    $env:E2E_DIR = $Lane
    $env:E2E_REAL1C = '1'
    if (-not (Test-Port 21080)) {
        $previousLogSuffix = $env:E2E_COMPONENT_LOG_SUFFIX
        $env:E2E_COMPONENT_LOG_SUFFIX = 'razer-21080'
        try {
            & (Join-Path $Runtime 'scripts\e2e\fault.ps1') -Component 'idp' -Action start *>> $LogFile
        } finally {
            if ($null -eq $previousLogSuffix) { Remove-Item Env:E2E_COMPONENT_LOG_SUFFIX -ErrorAction SilentlyContinue }
            else { $env:E2E_COMPONENT_LOG_SUFFIX = $previousLogSuffix }
        }
        Log ('idp started: ' + (Wait-Port 21080 30))
    }
    if (-not (Wait-Port 21080 5)) {
        Log 'FAIL: local IdP is not listening; gateway startup refused'
        if (-not (Stop-GatewayFailClosed 'local IdP unavailable')) {
            Log 'FAIL: startup aborted with gateway listener still present'
            exit 1
        }
        exit 1
    }
    if (-not (Test-CloudflareIdpRoute 'https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test')) {
        if (-not (Stop-GatewayFailClosed 'public IdP route differs from local issuer/key set')) {
            Log 'FAIL: startup aborted with gateway listener still present'
            exit 1
        }
        exit 1
    }
    Log 'Cloudflare IdP discovery and public signing keys match the local IdP'

    if (-not (Test-Port 21000)) {
        $previousLogSuffix = $env:E2E_COMPONENT_LOG_SUFFIX
        $env:E2E_COMPONENT_LOG_SUFFIX = 'razer-21000'
        try {
            & (Join-Path $Runtime 'scripts\e2e\fault.ps1') -Component 'gateway' -Action start *>> $LogFile
        } finally {
            if ($null -eq $previousLogSuffix) { Remove-Item Env:E2E_COMPONENT_LOG_SUFFIX -ErrorAction SilentlyContinue }
            else { $env:E2E_COMPONENT_LOG_SUFFIX = $previousLogSuffix }
        }
        Log ('gateway started: ' + (Wait-Port 21000 30))
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

    $state = foreach ($pair in @(@('postgres', $PostgresPort), @('redis', $RedisPort), @('apache/1C', $ApachePort), @('proxy8191', 8191), @('proxy8192', 8192),
            @('proxy8193', 8193), @('sidecar', 21768), @('idp', 21080), @('gateway', 21000))) { $pair[0] + '=' + (Test-Port $pair[1]) }
    Log ('summary: ' + ($state -join ' '))
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
