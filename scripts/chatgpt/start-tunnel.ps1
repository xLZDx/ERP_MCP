#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Profile = 'erp-mcp-local',
    [switch]$Background
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Client = Join-Path $Root '.chatgpt\bin\tunnel-client.exe'
$State = Join-Path $Root '.chatgpt'
$PidDir = Join-Path $State 'pids'
$LogDir = Join-Path $State 'logs'
$PidFile = Join-Path $PidDir 'tunnel.pid'

if (-not (Test-Path $Client)) { throw 'tunnel-client missing; run install-tunnel-client.ps1' }

$temporaryKey = $false
if (-not $env:CONTROL_PLANE_API_KEY) {
    $secure = Read-Host 'Runtime API key (CONTROL_PLANE_API_KEY; input hidden)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $env:CONTROL_PLANE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $temporaryKey = $true
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}
if (-not $env:CONTROL_PLANE_API_KEY) { throw 'runtime API key is required' }

try {
    if (-not $Background) {
        Write-Host ('[chatgpt] starting tunnel-client profile ' + $Profile + ' in foreground')
        & $Client run --profile $Profile
        exit $LASTEXITCODE
    }

    New-Item -ItemType Directory -Force -Path $PidDir,$LogDir | Out-Null
    if (Test-Path $PidFile) { throw 'tunnel pid file already exists; run stop-tunnel.ps1 first' }
    $out = Join-Path $LogDir 'tunnel.out.log'
    $err = Join-Path $LogDir 'tunnel.err.log'
    $args = 'run --profile ' + $Profile
    $cmd = '/c ""' + $Client + '" ' + $args + ' > "' + $out + '" 2> "' + $err + '""'
    $p = Start-Process -FilePath $env:ComSpec -ArgumentList $cmd -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Set-Content -Path $PidFile -Value ([string]$p.Id) -Encoding ascii
    Start-Sleep -Seconds 2
    if ($p.HasExited) {
        $tail = ''
        if (Test-Path $err) { $tail = (Get-Content $err -Tail 25) -join [Environment]::NewLine }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        throw ('tunnel-client exited during startup.' + [Environment]::NewLine + $tail)
    }
    Write-Host ('[chatgpt] tunnel-client started in background, pid ' + $p.Id)
    Write-Host '[chatgpt] run doctor.ps1 to verify tunnel readiness'
}
finally {
    if ($temporaryKey) { Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue }
}
