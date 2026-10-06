#Requires -Version 5.1
# Shared helpers for the disposable local E2E environment (dot-source this file).
# Works on Windows PowerShell 5.1 and PowerShell 7. Never prints secrets.

Set-StrictMode -Version 2.0

$script:Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:E2eDir = Join-Path $script:Root '.e2e'
$script:Py = Join-Path $script:Root '.venv\Scripts\python.exe'
$script:ComposeFile = Join-Path $script:Root 'compose.e2e.yml'
$script:ProjectName = 'erpmcp-e2e'
$script:BindHost = '127.0.0.1'
$script:Ports = [ordered]@{ postgres = 15432; redis = 16379; fake1c = 18766; idp = 18080; gateway = 18000 }
$script:ProcessComponents = @('fake1c', 'idp', 'gateway')

function Write-Step([string]$Message) { Write-Host ('[e2e] ' + $Message) }

function Invoke-Native {
    # Runs a native command, streams its output, throws on non-zero exit.
    param([string]$File, [string[]]$Arguments, [switch]$AllowFail, [switch]$Quiet)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $File @Arguments 2>&1 | ForEach-Object { $_.ToString() }
    } finally {
        $ErrorActionPreference = $previous
    }
    $code = $LASTEXITCODE
    if (-not $Quiet) { $output | ForEach-Object { Write-Host $_ } }
    if ($code -ne 0 -and -not $AllowFail) {
        throw ('command failed (exit ' + $code + '): ' + $File + ' ' + ($Arguments -join ' '))
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
    Get-ChildItem Env: | Where-Object { $_.Name -like 'BAG_*' -or $_.Name -like 'FAKE1C_*' } |
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
    param([string]$Url, [int]$ExpectStatus = 200, [int]$TimeoutSec = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ((Test-Http -Url $Url -TimeoutSec 3) -eq $ExpectStatus) { return $true }
        Start-Sleep -Milliseconds 500
    }
    throw ('timeout waiting for ' + $Url)
}

function Get-PidFile([string]$Name) { Join-Path $script:E2eDir ('pids\' + $Name + '.pid') }

function Get-ComponentPid([string]$Name) {
    $file = Get-PidFile $Name
    if (-not (Test-Path $file)) { return $null }
    $value = [int](Get-Content $file -Raw)
    if (Get-Process -Id $value -ErrorAction SilentlyContinue) { return $value }
    return $null
}

function Get-ComponentCommand([string]$Name) {
    switch ($Name) {
        'fake1c' { return @('-m', 'uvicorn', 'testbed.fake1c.app:app', '--host', $script:BindHost,
            '--port', [string]$script:Ports.fake1c, '--no-access-log') }
        'idp' { return @('-m', 'testbed.idp') }
        'gateway' { return @('-m', 'uvicorn', 'business_ai_gateway.app:app', '--host', $script:BindHost,
            '--port', [string]$script:Ports.gateway, '--no-access-log') }
    }
}

function Test-ComponentUp([string]$Name) {
    $port = $script:Ports[$Name]
    return [bool](Get-ListenerInfo $port)
}

function Start-E2eComponent {
    param([ValidateSet('fake1c', 'idp', 'gateway')][string]$Name)
    if (Test-ComponentUp $Name) { Write-Step ($Name + ' already listening'); return }
    Initialize-PythonEnv
    New-Item -ItemType Directory -Force -Path (Join-Path $script:E2eDir 'pids'),
        (Join-Path $script:E2eDir 'logs') | Out-Null
    $out = Join-Path $script:E2eDir ('logs\' + $Name + '.out.log')
    $err = Join-Path $script:E2eDir ('logs\' + $Name + '.err.log')
    if ($Name -eq 'gateway') { Import-E2eEnv }
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
    Set-Content -Path (Get-PidFile $Name) -Value $process.Id -Encoding ascii
    Write-Step ('started ' + $Name + ' (pid ' + $process.Id + ', port ' + $script:Ports[$Name] + ')')
}

function Stop-E2eComponent {
    param([ValidateSet('fake1c', 'idp', 'gateway')][string]$Name)
    $port = $script:Ports[$Name]
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
    Remove-Item (Get-PidFile $Name) -ErrorAction SilentlyContinue
    if (Test-ComponentUp $Name) { throw ($Name + ' still listening on ' + $port) }
    Write-Step ('stopped ' + $Name)
}

function Wait-E2eComponent([string]$Name) {
    $base = 'http://' + $script:BindHost + ':' + $script:Ports[$Name]
    switch ($Name) {
        'fake1c' { Wait-Http ($base + '/odata/standard.odata/$metadata') | Out-Null }
        'idp' { Wait-Http ($base + '/healthz') | Out-Null }
        'gateway' { Wait-Http ($base + '/healthz') | Out-Null; Wait-Http ($base + '/readyz') | Out-Null }
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
