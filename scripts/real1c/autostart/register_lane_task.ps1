#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Registers the local REAL1C lane startup task for interactive logon.

.DESCRIPTION
  Run from an elevated Windows PowerShell session after the lane script has been deployed to
  D:\ERP_MCP_Testbed\real1c_e2e\autostart\start_lane.ps1. The task runs as the current
  interactive user with the highest available token. It does not store credentials.
#>
[CmdletBinding()]
param(
    [string]$LaneRoot = 'D:\ERP_MCP_Testbed\real1c_e2e',
    [string]$TaskName = 'ERP_MCP_Lane_Autostart'
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $LaneRoot 'autostart\start_lane.ps1'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "Lane startup script is missing: $scriptPath"
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from elevated Windows PowerShell.'
}

$powerShell51 = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action = New-ScheduledTaskAction `
    -Execute $powerShell51 `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $scriptPath + '"') `
    -WorkingDirectory $LaneRoot

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$logonTrigger.Delay = 'PT1M'

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId $identity.Name `
    -LogonType Interactive `
    -RunLevel Highest

function Disable-TaskAndConfirm([string]$Context) {
    try {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        $disabledTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        if ($disabledTask.State -ne 'Disabled') {
            throw "Task state is $($disabledTask.State), not Disabled."
        }
    } catch {
        throw "$Context. Best-effort task disable could not be confirmed: $($_.Exception.Message)"
    }
}

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $logonTrigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
} catch {
    $registrationError = $_.Exception.Message
    $failedTask = $null
    $inspectionError = $null
    try {
        $failedTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } catch {
        $inspectionError = $_.Exception.Message
    }

    if ($null -eq $failedTask) {
        try {
            Disable-TaskAndConfirm "Task registration failed: $registrationError; task-state read-back failed: $inspectionError"
        } catch {
            throw "Task registration failed: $registrationError. Task-state read-back failed: $inspectionError. Fail-closed disable could not be confirmed: $($_.Exception.Message)"
        }
        throw "Task registration failed: $registrationError. The task was disabled because its state could not be inspected; interactive logon startup is unavailable until registration succeeds."
    }

    try {
        Disable-TaskAndConfirm "Task registration failed: $registrationError; an existing task remained"
    } catch {
        throw "Task registration failed: $registrationError. The existing task could not be confirmed disabled: $($_.Exception.Message)"
    }

    throw "Task registration failed: $registrationError. The existing task is disabled; interactive logon startup is unavailable until registration succeeds."
}

try {
    $registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
} catch {
    Disable-TaskAndConfirm "Task registration succeeded but read-back failed: $($_.Exception.Message)"
    throw "Task registration succeeded but its state could not be read back. The task is disabled to prevent an unverified periodic trigger; interactive logon startup is unavailable until registration succeeds."
}
$registeredTriggers = @($registered.Triggers)
$registeredLogonTriggers = @($registeredTriggers | Where-Object {
    $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger'
})
$registeredLogonTrigger = $registeredLogonTriggers | Select-Object -First 1
$remainingPeriodicTriggers = @($registeredTriggers | Where-Object {
    $_.CimClass.CimClassName -ne 'MSFT_TaskLogonTrigger' -or $_.Repetition.Interval
})
if ($remainingPeriodicTriggers.Count -gt 0) {
    Disable-TaskAndConfirm "Task $TaskName retained unexpected periodic triggers after registration"
    throw "Task $TaskName retained unexpected periodic triggers after registration and is now disabled; interactive logon startup is unavailable until registration succeeds."
}
$registeredActions = @($registered.Actions)
$registeredAction = $registeredActions | Select-Object -First 1
$validLogonTrigger = $false
if ($registeredLogonTriggers.Count -eq 1) {
    $validLogonTrigger = $registeredLogonTrigger.Enabled -eq $true -and
        $registeredLogonTrigger.Delay -eq 'PT1M'
}
$validPrincipal = $false
if ($null -ne $registered.Principal) {
    $validPrincipal = $registered.Principal.UserId -eq $identity.Name -and
        $registered.Principal.RunLevel -eq 'Highest' -and
        $registered.Principal.LogonType -eq 'Interactive'
}
$validAction = $false
if ($registeredActions.Count -eq 1 -and $null -ne $registeredAction) {
    $validAction = $registeredAction.Execute -eq $powerShell51 -and
        $registeredAction.Arguments -like ('*' + $scriptPath + '*')
}
if ($registeredTriggers.Count -ne 1 -or
        -not $validLogonTrigger -or
        $registered.State -eq 'Disabled' -or
        -not $validPrincipal -or
        -not $validAction) {
    Disable-TaskAndConfirm "Task $TaskName did not retain the expected elevated one-minute logon startup settings"
    throw "Task $TaskName did not retain the expected settings and is now disabled; interactive logon startup is unavailable until registration succeeds."
}

[pscustomobject]@{
    TaskName = $registered.TaskName
    UserId = $registered.Principal.UserId
    RunLevel = $registered.Principal.RunLevel
    LogonDelay = $registeredLogonTrigger.Delay
    StartupScript = $scriptPath
    State = $registered.State
} | Format-List
