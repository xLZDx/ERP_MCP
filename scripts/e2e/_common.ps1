#Requires -Version 5.1
# Shared helpers for the disposable local E2E environment (dot-source this file).
# Works on Windows PowerShell 5.1 and PowerShell 7. Never prints secrets.
#
# Topology is relocatable with ONE variable set (defaults unchanged):
#   E2E_PORT_OFFSET     integer added to every default port (default 0)
#   E2E_PROJECT_SUFFIX  appended to the compose project name, e.g. -rem (default empty)
# When neither is set, the values recorded in .e2e/env.json (or env.pending.json) are used, so
# status/fault/test run from any shell address the same environment that up.ps1 created.

Set-StrictMode -Version 2.0

$script:Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:E2eDir = Join-Path $script:Root '.e2e'
if ($env:E2E_DIR) { $script:E2eDir = $env:E2E_DIR }
$script:Py = Join-Path $script:Root '.venv\Scripts\python.exe'
$script:ComposeFile = Join-Path $script:Root 'compose.e2e.yml'
$script:BindHost = '127.0.0.1'
$script:BasePorts = [ordered]@{ postgres = 15432; redis = 16379; fake1c = 18766; sidecar = 18767
    idp = 18080; gateway = 18000 }
# Components that run as host processes (start order); stop order is the reverse.
$script:Real1c = ($env:E2E_REAL1C -eq '1')
# Real local 1C profile (E2E_REAL1C=1): no Fake1C and no fake sidecar process is started, stopped or probed.
$script:ProcessComponents = if ($script:Real1c) { @('idp', 'gateway') } else { @('fake1c', 'sidecar', 'idp', 'gateway') }

function Resolve-E2eTopology {
    $offset = $env:E2E_PORT_OFFSET
    $suffix = $env:E2E_PROJECT_SUFFIX
    $recorded = $null
    if ($null -eq $offset -and $null -eq $suffix) {
        foreach ($name in 'env.json', 'env.pending.json') {
            $file = Join-Path $script:E2eDir $name
            if (Test-Path $file) {
                try { $recorded = Get-Content $file -Raw | ConvertFrom-Json; break } catch { $recorded = $null }
            }
        }
    }
    if ($null -eq $offset) {
        $offset = 0
        if ($recorded -and ($recorded.PSObject.Properties.Name -contains 'port_offset')) { $offset = $recorded.port_offset }
    }
    if ($null -eq $suffix) {
        $suffix = ''
        if ($recorded -and ($recorded.PSObject.Properties.Name -contains 'project_suffix')) { $suffix = $recorded.project_suffix }
    }
    $offset = [int]$offset
    if ($offset -lt 0 -or ($offset + 18767) -gt 65535) { throw 'E2E_PORT_OFFSET out of range' }
    if ($suffix -notmatch '^(-[a-z0-9]+)*$') { throw 'E2E_PROJECT_SUFFIX must look like -name' }
    $script:PortOffset = $offset
    $script:ProjectSuffix = $suffix
    $script:ProjectName = 'erpmcp-e2e' + $suffix
    $script:Ports = [ordered]@{}
    foreach ($name in $script:BasePorts.Keys) { $script:Ports[$name] = $script:BasePorts[$name] + $offset }
    # Child processes (envctl.py, pytest, fault.ps1) must see the same topology.
    $env:E2E_PORT_OFFSET = [string]$offset
    $env:E2E_PROJECT_SUFFIX = $suffix
}
Resolve-E2eTopology

function Write-Step([string]$Message) { Write-Host ('[e2e] ' + $Message) }

function Invoke-Native {
    # Runs a native command, streams its output, throws (with the output tail) on non-zero exit.
    param([string]$File, [string[]]$Arguments, [switch]$AllowFail, [switch]$Quiet)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $global:LASTEXITCODE = 0   # never inherit a stale exit code from an earlier command
    try {
        $output = @(& $File @Arguments 2>&1 | ForEach-Object { $_.ToString() })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if (-not $Quiet) { $output | ForEach-Object { Write-Host $_ } }
    if ($code -ne 0 -and -not $AllowFail) {
        $tail = (@($output | Select-Object -Last 15) -join "`n")
        throw ('command failed (exit ' + $code + '): ' + $File + ' ' + ($Arguments -join ' ') + "`n" + $tail)
    }
    return , @($output, $code)
}

function Initialize-PythonEnv {
    if (-not (Test-Path $script:Py)) {
        $uv = Get-UvPath
        Write-Step 'creating project venv (uv sync --locked --all-groups --extra dev)'
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
        Push-Location $script:Root
        try { Invoke-Native $uv @('sync', '--locked', '--all-groups', '--extra', 'dev') | Out-Null }
        finally { Pop-Location }
    }
    $env:PYTHONPATH = (Join-Path $script:Root 'src')
    $env:PYTHONUNBUFFERED = '1'
    $env:PYTHONUTF8 = '1'
}

function Get-UvPath {
    $winget = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    $found = Get-ChildItem -Path $winget -Filter uv.exe -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) { return $found.FullName }
    return (Get-Command uv.exe -ErrorAction Stop).Source
}

function Invoke-Envctl {
    param([string[]]$Arguments, [switch]$Quiet)
    Initialize-PythonEnv
    $script = Join-Path $script:Root 'scripts\e2e\envctl.py'
    Push-Location $script:Root
    try { return (Invoke-Native $script:Py (@($script) + $Arguments) -Quiet:$Quiet) }
    finally { Pop-Location }
}

function Invoke-Compose {
    param([string[]]$Arguments, [switch]$AllowFail, [switch]$Quiet)
    $base = @('compose', '-p', $script:ProjectName, '-f', $script:ComposeFile,
        '--env-file', (Join-Path $script:E2eDir 'compose.env'))
    return (Invoke-Native 'docker' ($base + $Arguments) -AllowFail:$AllowFail -Quiet:$Quiet)
}

function Import-E2eEnv {
    # Clears inherited BAG_* variables, then loads the generated environment.
    Get-ChildItem Env: | Where-Object { $_.Name -like 'BAG_*' } | ForEach-Object {
        Remove-Item ('Env:' + $_.Name) }
    . (Join-Path $script:E2eDir 'env.ps1')
}

function Clear-E2eSecretEnv {
    Get-ChildItem Env: | Where-Object {
        $_.Name -like 'BAG_*' -or $_.Name -like 'FAKE1C_*' -or $_.Name -like 'FAKE_SIDECAR_*' } |
        ForEach-Object { Remove-Item ('Env:' + $_.Name) }
}

function Get-ListenerInfo([int]$Port) {
    $rows = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $rows) { return $null }
    return @($rows | ForEach-Object { [pscustomobject]@{ Address = $_.LocalAddress; Pid = $_.OwningProcess } })
}

function Test-Http {
    param([string]$Url, [int]$TimeoutSec = 5)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -Method Get
        return [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return 0
    }
}

function Wait-Http {
    param([string]$Url, [int]$ExpectStatus = 200, [int]$TimeoutSec = 60, [string]$Component = '')
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ((Test-Http -Url $Url -TimeoutSec 3) -eq $ExpectStatus) { return $true }
        if ($Component -and -not (Get-ComponentPid $Component)) {
            throw ($Component + ' exited while starting' + "`n" + (Get-LogTail $Component))
        }
        Start-Sleep -Milliseconds 500
    }
    throw ('timeout waiting for ' + $Url)
}

# ---------------------------------------------------------------------------- process identity
# The pid file stores "<pid> <start-time-ticks-utc>" of the cmd.exe launcher. A pid is trusted
# only while that process still has the recorded start time (Windows reuses pids).

function Get-PidFile([string]$Name) { Join-Path $script:E2eDir ('pids\' + $Name + '.pid') }

function Get-ProcessStartTicks([int]$ProcessId) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    try { return [string]$process.StartTime.ToUniversalTime().Ticks } catch { return $null }
}

function Read-PidRecord([string]$Name) {
    $file = Get-PidFile $Name
    if (-not (Test-Path $file)) { return $null }
    $parts = @((Get-Content $file -Raw).Trim() -split '\s+')
    if ($parts.Count -lt 1 -or $parts[0] -notmatch '^\d+$') { return $null }
    $ticks = ''
    if ($parts.Count -ge 2) { $ticks = $parts[1] }
    return [pscustomobject]@{ Pid = [int]$parts[0]; Ticks = $ticks }
}

function Get-ComponentPid([string]$Name) {
    # The recorded launcher pid, only if it is alive AND is the process we started.
    $record = Read-PidRecord $Name
    if (-not $record) { return $null }
    $actual = Get-ProcessStartTicks $record.Pid
    if (-not $actual) { return $null }
    if ($record.Ticks -and $record.Ticks -ne $actual) { return $null }
    return $record.Pid
}

function Get-ProcessInfo([int]$ProcessId) {
    return Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ProcessId) -ErrorAction SilentlyContinue
}

function Test-ListenerIsOurs {
    # True when the listening process descends from our recorded launcher, or (no live record)
    # its ancestor chain carries this worktree's venv python and the component's module.
    param([string]$Name, [int]$ListenerPid)
    $recorded = Get-ComponentPid $Name
    $module = Get-ComponentModule $Name
    $current = $ListenerPid
    for ($depth = 0; $depth -lt 8 -and $current; $depth++) {
        if ($recorded -and $current -eq $recorded) { return $true }
        $info = Get-ProcessInfo $current
        if (-not $info) { return $false }
        if (-not $recorded -and $info.CommandLine -and
            $info.CommandLine.ToLower().Contains($script:Py.ToLower()) -and
            $info.CommandLine.Contains($module)) { return $true }
        $current = [int]$info.ParentProcessId
    }
    return $false
}

function Get-ForeignListener([string]$Name) {
    # The first listener on the component's port that is not ours, or $null.
    $listeners = Get-ListenerInfo $script:Ports[$Name]
    if (-not $listeners) { return $null }
    foreach ($row in $listeners) {
        if (-not (Test-ListenerIsOurs $Name $row.Pid)) { return $row }
    }
    return $null
}

function Get-ComponentModule([string]$Name) {
    switch ($Name) {
        'fake1c' { return 'testbed.fake1c.app:app' }
        'sidecar' { return 'sidecar_recording_app:app' }
        'idp' { return 'testbed.idp' }
        'gateway' { return 'business_ai_gateway.app:app' }
    }
}

function Get-ComponentCommand([string]$Name) {
    switch ($Name) {
        'fake1c' { return @('-m', 'uvicorn', 'testbed.fake1c.app:app', '--host', $script:BindHost,
            '--port', [string]$script:Ports.fake1c, '--no-access-log') }
        'sidecar' { return @('-m', 'uvicorn', 'testbed.fake1c.sidecar_recording_app:app',
            '--host', $script:BindHost, '--port', [string]$script:Ports.sidecar, '--no-access-log') }
        'idp' { return @('-m', 'testbed.idp') }
        'gateway' { return @('-m', 'uvicorn', 'business_ai_gateway.app:app', '--host', $script:BindHost,
            '--port', [string]$script:Ports.gateway, '--no-access-log') }
    }
}

function Get-LogTail([string]$Name, [int]$Lines = 15) {
    $parts = @()
    foreach ($suffix in 'err', 'out') {
        $file = Join-Path $script:E2eDir ('logs\' + $Name + '.' + $suffix + '.log')
        if (Test-Path $file) {
            $parts += ('--- ' + $Name + '.' + $suffix + '.log (tail) ---')
            $parts += @(Get-Content $file -Tail $Lines -ErrorAction SilentlyContinue)
        }
    }
    return ($parts -join "`n")
}

function Test-ComponentUp([string]$Name) {
    return [bool](Get-ListenerInfo $script:Ports[$Name])
}

function Assert-E2eComponentAllowed([string]$Name) {
    # The real local 1C profile never starts, stops or probes the Fake1C or the fake sidecar component.
    if ($script:Real1c -and $Name -in 'fake1c', 'sidecar') {
        throw ('component ' + $Name + ' does not exist in the real local 1C profile (E2E_REAL1C=1)')
    }
}

function Start-E2eComponent {
    param([ValidateSet('fake1c', 'sidecar', 'idp', 'gateway')][string]$Name)
    Assert-E2eComponentAllowed $Name
    $foreign = Get-ForeignListener $Name
    if ($foreign) {
        throw ('port ' + $script:Ports[$Name] + ' for ' + $Name + ' is held by a foreign process (pid ' +
            $foreign.Pid + '); refusing to start or reuse it')
    }
    if (Test-ComponentUp $Name) { Write-Step ($Name + ' already listening (ours)'); return }
    Initialize-PythonEnv
    New-Item -ItemType Directory -Force -Path (Join-Path $script:E2eDir 'pids'),
        (Join-Path $script:E2eDir 'logs') | Out-Null
    $out = Join-Path $script:E2eDir ('logs\' + $Name + '.out.log')
    $err = Join-Path $script:E2eDir ('logs\' + $Name + '.err.log')
    if ($Name -in 'gateway', 'sidecar') { Import-E2eEnv }
    if ($Name -eq 'idp') { $env:E2E_IDP_CONFIG = (Join-Path $script:E2eDir 'idp-config.json') }
    # Launch through cmd.exe via ShellExecute (no -Redirect*): the service must NOT inherit the
    # caller's stdout/stderr pipes, otherwise a caller reading our output waits for EOF forever.
    $arguments = (Get-ComponentCommand $Name) -join ' '
    $commandLine = '/c ""' + $script:Py + '" ' + $arguments + ' > "' + $out + '" 2> "' + $err + '""'
    try {
        $process = Start-Process -FilePath $env:ComSpec -ArgumentList $commandLine `
            -WorkingDirectory $script:Root -WindowStyle Hidden -PassThru
    } finally {
        Clear-E2eSecretEnv
        Remove-Item Env:E2E_IDP_CONFIG -ErrorAction SilentlyContinue
    }
    $ticks = ''
    try { $ticks = [string]$process.StartTime.ToUniversalTime().Ticks } catch { $ticks = '' }
    Set-Content -Path (Get-PidFile $Name) -Value ([string]$process.Id + ' ' + $ticks) -Encoding ascii
    # Fail fast: the launcher exits at once when python cannot start or the app import fails.
    $deadline = (Get-Date).AddSeconds(2)
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) {
            throw ($Name + ' exited immediately (exit ' + $process.ExitCode + ')' + "`n" + (Get-LogTail $Name))
        }
        Start-Sleep -Milliseconds 250
    }
    Write-Step ('started ' + $Name + ' (pid ' + $process.Id + ', port ' + $script:Ports[$Name] + ')')
}

function Stop-E2eComponent {
    param([ValidateSet('fake1c', 'sidecar', 'idp', 'gateway')][string]$Name)
    Assert-E2eComponentAllowed $Name
    $port = $script:Ports[$Name]
    $foreign = Get-ForeignListener $Name
    if ($foreign) {
        throw ('port ' + $port + ' for ' + $Name + ' is held by a foreign process (pid ' + $foreign.Pid +
            '); refusing to stop it')
    }
    $targets = @()
    $recorded = Get-ComponentPid $Name
    if ($recorded) { $targets += $recorded }
    $listener = Get-ListenerInfo $port
    if ($listener) { $targets += @($listener | ForEach-Object { $_.Pid }) }
    foreach ($target in ($targets | Sort-Object -Unique)) {
        # /T kills the venv launcher's child interpreter as well.
        Invoke-Native 'taskkill.exe' @('/PID', [string]$target, '/T', '/F') -AllowFail -Quiet | Out-Null
    }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Test-ComponentUp $Name) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
    # Remove the pid record only once the port is confirmed free.
    if (Test-ComponentUp $Name) { throw ($Name + ' still listening on ' + $port + '; pid file kept') }
    Remove-Item (Get-PidFile $Name) -ErrorAction SilentlyContinue
    Write-Step ('stopped ' + $Name)
}

function Wait-E2eComponent([string]$Name) {
    Assert-E2eComponentAllowed $Name
    $base = 'http://' + $script:BindHost + ':' + $script:Ports[$Name]
    switch ($Name) {
        'fake1c' { Wait-Http ($base + '/odata/standard.odata/$metadata') -Component $Name | Out-Null }
        'sidecar' { Wait-Http ($base + '/__ft__/requests') -Component $Name | Out-Null }
        'idp' { Wait-Http ($base + '/healthz') -Component $Name | Out-Null }
        'gateway' {
            Wait-Http ($base + '/healthz') -Component $Name | Out-Null
            Wait-Http ($base + '/readyz') -Component $Name | Out-Null
        }
    }
}

function Start-E2eDependencies {
    Invoke-Compose @('up', '-d', '--wait', '--wait-timeout', '120', 'postgres', 'redis') | Out-Null
}

function Invoke-E2eMigrate {
    Import-E2eEnv
    Push-Location $script:Root
    try {
        Invoke-Envctl @('ensure-roles') | Out-Null
        Invoke-Native $script:Py @('scripts/migrate.py') -Quiet | Out-Null
        Invoke-Envctl @('verify-schema') | Out-Null
        Invoke-Native $script:Py @('scripts/check_db_privileges.py') | Out-Null
    } finally {
        Pop-Location
        Clear-E2eSecretEnv
    }
}

function Get-SeedMode {
    $file = Join-Path $script:E2eDir 'env.json'
    if (Test-Path $file) { return (Get-Content $file -Raw | ConvertFrom-Json).seed_mode }
    return $null
}
