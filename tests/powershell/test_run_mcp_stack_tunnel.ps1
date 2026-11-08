$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot '..\..\scripts\remote\run-mcp-stack.ps1'
$source = Get-Content -LiteralPath $scriptPath -Raw
$startMarker = "    # 7. OpenAI tunnel-client for the ChatGPT connector."
$endMarker = "    Log ('summary:"
$start = $source.IndexOf($startMarker, [StringComparison]::Ordinal)
$end = if ($start -ge 0) { $source.IndexOf($endMarker, $start, [StringComparison]::Ordinal) } else { -1 }
if ($start -lt 0 -or $end -lt 0) { throw 'Could not isolate the tunnel reconciliation section.' }
$script:tunnelSection = $source.Substring($start, $end - $start)

$script:temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('erp-mcp-tunnel-reconcile-' + [guid]::NewGuid().ToString('N'))
$Root = $script:temporaryRoot
$EnvDir = Join-Path $Root 'env'
New-Item -ItemType Directory -Path $EnvDir -Force | Out-Null
$TunnelId = 'tunnel_test_target_1'

$script:portOccupied = $false
$script:listenerPid = 4276
$script:processPath = Join-Path $Root 'tunnel\tunnel-client.exe'
$script:processCommandLine = ''
$script:listenerQueries = 0
$script:processQueries = 0
$script:disappearOnFirstProcessQuery = $false
$script:disappearAfterFirstLaunch = $false
$script:disappearAfterEveryLaunch = $false
$script:sleepCalls = 0
$script:changeIdentityOnRecheck = $false
$script:processCreationDate = [datetime]'2026-11-08T04:00:00Z'
$script:replacementCreationDate = [datetime]'2026-11-08T04:00:05Z'
$script:executableAfterStart = $null
$script:stoppedPids = @()
$script:startedNames = @()
$script:logLines = @()

function Log([string]$Message) { $script:logLines += $Message }
function Test-Port([int]$Port) { return ($Port -eq 21090 -and $script:portOccupied) }
function Get-NetTCPConnection {
    [CmdletBinding()]
    param([string]$State, [int]$LocalPort)
    $script:listenerQueries++
    if ($State -eq 'Listen' -and $LocalPort -eq 21090 -and $script:portOccupied) {
        return [pscustomobject]@{ OwningProcess = $script:listenerPid }
    }
}
function Get-CimInstance {
    [CmdletBinding()]
    param([string]$ClassName, [string]$Filter)
    $script:processQueries++
    if ($script:disappearOnFirstProcessQuery -and $script:processQueries -eq 1) {
        $script:portOccupied = $false
        return
    }
    if ($script:disappearAfterFirstLaunch -and $script:startedNames.Count -eq 1 -and $script:processQueries -eq 1) {
        $script:portOccupied = $false
        return
    }
    if ($script:disappearAfterEveryLaunch -and $script:processQueries -eq $script:startedNames.Count) {
        $script:portOccupied = $false
        return
    }
    if ($ClassName -eq 'Win32_Process' -and $Filter -eq ('ProcessId=' + $script:listenerPid)) {
        $creationDate = $script:processCreationDate
        if ($script:changeIdentityOnRecheck -and $script:processQueries -eq 2) {
            $creationDate = $script:replacementCreationDate
        }
        return [pscustomobject]@{
            ProcessId = $script:listenerPid
            ExecutablePath = $script:processPath
            CommandLine = $script:processCommandLine
            CreationDate = $creationDate
        }
    }
}
function Stop-Process {
    [CmdletBinding()]
    param([int]$Id)
    $script:stoppedPids += $Id
    $script:portOccupied = $false
}
function Start-Hidden([string]$File, [string[]]$Args2, [string]$Dir, [string]$Name) {
    $script:startedNames += $Name
    $script:portOccupied = $true
    $script:listenerPid = 5000
    $script:processPath = if ($script:executableAfterStart) { $script:executableAfterStart } else { Join-Path $Root 'tunnel\tunnel-client.exe' }
    $script:processCommandLine = 'tunnel-client.exe run --control-plane.tunnel-id ' + $TunnelId + ' --control-plane.api-key env:CONTROL_PLANE_API_KEY'
    $script:processCreationDate = (Get-Item -LiteralPath (Join-Path $EnvDir 'tunnel_api_key.dpapi')).LastWriteTime.AddSeconds(2)
}
function Wait-Port([int]$Port, [int]$Seconds) { return $true }
function Start-Sleep([int]$Seconds) { $script:sleepCalls++ }

function Reset-Case([string]$RunningId, [bool]$PortOpen = $true, [string]$RunningExecutable = $null) {
    $script:portOccupied = $PortOpen
    $script:listenerPid = 4276
    $script:processPath = if ($RunningExecutable) { $RunningExecutable } else { Join-Path $Root 'tunnel\tunnel-client.exe' }
    $script:processCommandLine = 'tunnel-client.exe run --control-plane.tunnel-id ' + $RunningId + ' --control-plane.api-key env:CONTROL_PLANE_API_KEY'
    $script:listenerQueries = 0
    $script:processQueries = 0
    $script:disappearOnFirstProcessQuery = $false
    $script:disappearAfterFirstLaunch = $false
    $script:disappearAfterEveryLaunch = $false
    $script:sleepCalls = 0
    $script:changeIdentityOnRecheck = $false
    $script:executableAfterStart = $null
    $script:stoppedPids = @()
    $script:startedNames = @()
    $script:logLines = @()
    Set-Content -LiteralPath (Join-Path $EnvDir 'tunnel.json') -Value (@{ tunnel_id = $TunnelId } | ConvertTo-Json -Compress)
    [IO.File]::WriteAllBytes((Join-Path $EnvDir 'tunnel_api_key.dpapi'), [byte[]]@(1, 2, 3))
    $keyLastWrite = (Get-Item -LiteralPath (Join-Path $EnvDir 'tunnel_api_key.dpapi')).LastWriteTime
    $script:processCreationDate = $keyLastWrite.AddSeconds(1)
    $script:replacementCreationDate = $script:processCreationDate.AddSeconds(5)
}
function Invoke-TunnelSection { Invoke-Expression $script:tunnelSection }
function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }

try {
    Reset-Case -RunningId $TunnelId
    Invoke-TunnelSection
    # The key file is older than this same-ID process, so the tunnel stays in place.
    Assert-True ($script:stoppedPids.Count -eq 0 -and $script:startedNames.Count -eq 0) 'Matching configured tunnel must be left running.'
    Assert-True (($script:logLines -join "`n") -match 'local listener verified for configured id .*control-plane registration is not verified') 'Matching local process must be identified without claiming control-plane registration.'

    Reset-Case -RunningId $TunnelId
    $keyPath = Join-Path $EnvDir 'tunnel_api_key.dpapi'
    (Get-Item -LiteralPath $keyPath).LastWriteTime = $script:processCreationDate.AddSeconds(5)
    Invoke-TunnelSection
    Assert-True ($script:stoppedPids.Count -eq 1 -and $script:startedNames.Count -eq 1) 'Same tunnel ID with a key file newer than process start must be restarted.'
    Assert-True (($script:logLines -join "`n") -match 'reason=runtime key file updated after process start') 'Key rotation restart reason must be logged.'

    Reset-Case -RunningId 'tunnel_old_id'
    Invoke-TunnelSection
    Assert-True ($script:stoppedPids.Count -eq 1 -and $script:stoppedPids[0] -eq 4276) 'Stale managed tunnel process must be stopped.'
    Assert-True ($script:startedNames.Count -eq 1 -and $script:startedNames[0] -eq 'tunnel') 'Configured tunnel must start after the stale process releases the port.'
    Assert-True (($script:logLines -join "`n") -match 'local listener verified for configured id .*control-plane registration is not verified') 'Replacement process identity must be checked after its port opens.'

    Reset-Case -RunningId 'tunnel_other' -RunningExecutable 'C:\unmanaged\service.exe'
    Invoke-TunnelSection
    Assert-True ($script:stoppedPids.Count -eq 0 -and $script:startedNames.Count -eq 0) 'An unrelated listener must not be stopped or replaced.'
    Assert-True (($script:logLines -join "`n") -match 'owned by an unmanaged process; leaving it untouched') 'Unmanaged listener outcome must be logged.'

    Reset-Case -RunningId '' -PortOpen $false
    Remove-Item -LiteralPath (Join-Path $EnvDir 'tunnel_api_key.dpapi')
    Invoke-TunnelSection
    Assert-True ($script:startedNames.Count -eq 0) 'Missing DPAPI key file must not start the tunnel.'
    Assert-True (($script:logLines -join "`n") -match 'runtime id or DPAPI key file missing') 'Missing credential must be visible in the log.'

    Reset-Case -RunningId '' -PortOpen $false
    Invoke-TunnelSection
    Assert-True ($script:startedNames.Count -eq 1) 'A free port must start the configured tunnel.'
    Assert-True (($script:logLines -join "`n") -match 'local listener verified for configured id .*control-plane registration is not verified') 'Startup must verify executable and tunnel ID after the port opens.'

    Reset-Case -RunningId '' -PortOpen $false
    $script:executableAfterStart = 'C:\unmanaged\racing-service.exe'
    Invoke-TunnelSection
    Assert-True ($script:startedNames.Count -eq 1) 'The configured start attempt must occur when the port was initially free.'
    Assert-True (($script:logLines -join "`n") -match 'port 21090 opened by an unmanaged process; leaving it untouched') 'A different process winning the startup race must be logged as unmanaged.'
    Assert-True (($script:logLines -join "`n") -notmatch 'local listener verified') 'An unmanaged startup-race listener must never be reported as verified.'

    Reset-Case -RunningId 'tunnel_old_id'
    $script:disappearOnFirstProcessQuery = $true
    Invoke-TunnelSection
    Assert-True ($script:stoppedPids.Count -eq 0 -and $script:startedNames.Count -eq 1) 'A listener disappearing during process lookup must cause the configured start path.'
    Assert-True (($script:logLines -join "`n") -match 'local listener verified for configured id .*control-plane registration is not verified') 'The process started after the race must be verified by executable and ID.'

    Reset-Case -RunningId '' -PortOpen $false
    $script:disappearAfterFirstLaunch = $true
    Invoke-TunnelSection
    Assert-True ($script:startedNames.Count -eq 2) 'A disappearing process after listener/CIM lookup must receive exactly one retry.'
    Assert-True (($script:logLines -join "`n") -match 'process exited during startup; one bounded retry; attempt=2') 'The single retry must be explicitly logged.'
    Assert-True (($script:logLines -join "`n") -match 'local listener verified for configured id .*control-plane registration is not verified') 'The retry process must be checked before it is locally verified.'

    Reset-Case -RunningId '' -PortOpen $false
    $script:disappearAfterEveryLaunch = $true
    Invoke-TunnelSection
    Assert-True ($script:startedNames.Count -eq 2) 'Startup must stop after the initial launch and one retry.'
    Assert-True (($script:logLines -join "`n") -match 'one bounded retry; attempt=2') 'The single permitted retry must be logged.'
    Assert-True (($script:logLines -join "`n") -notmatch 'attempt=3') 'Exhausted startup attempts must never announce a third launch.'
    Assert-True (($script:logLines -join "`n") -match 'local listener did not become ready after bounded startup attempts') 'Exhaustion must leave a clear failure diagnostic.'

    Reset-Case -RunningId 'tunnel_old_id'
    $script:changeIdentityOnRecheck = $true
    Invoke-TunnelSection
    Assert-True ($script:stoppedPids.Count -eq 0 -and $script:startedNames.Count -eq 0) 'A new process identity at the same PID must remain untouched before replacement.'
    Assert-True (($script:logLines -join "`n") -match 'listener process changed before replacement; leaving current owner untouched') 'A process identity race must be logged as an unresolved owner change.'

    'Passed 11 focused tunnel reconciliation cases.'
} finally {
    Remove-Item -LiteralPath $script:temporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
}
