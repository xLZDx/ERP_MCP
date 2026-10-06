# Shared settings for the functional-tester private stack (dot-source this file).
# Ports/names are private to this worktree; do not reuse other lanes' containers.
$ErrorActionPreference = 'Stop'
$script:Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:Py = Join-Path $script:Root '.venv\Scripts\python.exe'
$script:StateDir = Join-Path $script:Root 'var\ft'   # var/ is git-ignored
$script:EnvFile = Join-Path $script:StateDir 'ft.env'
$script:PgName = 'erpmcp-ft-pg'
$script:RedisName = 'erpmcp-ft-redis'
$script:PgPort = 25432
$script:RedisPort = 26379
$script:FakePort = 28766
$script:SidecarPort = 28767
$script:GwPort = 28000

function New-Secret {
    $b = New-Object byte[] 18
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($b)
    return ([BitConverter]::ToString($b) -replace '-', '').ToLower()
}

function Import-FtEnv {
    if (-not (Test-Path $script:EnvFile)) { throw "missing $script:EnvFile - run scripts\ft\setup.ps1 first" }
    foreach ($line in Get-Content $script:EnvFile) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $k, $v = $line -split '=', 2
        Set-Item -Path "Env:$k" -Value $v
    }
}

function Wait-Http([string]$Url, [int]$Seconds = 60) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    throw "timeout waiting for $Url"
}
