#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Registers the local REAL1C lane startup and five-minute watchdog task.

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

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq 'Running') {
    throw "Task $TaskName is running; let the current pass finish, then rerun this installer."
}

$powerShell51 = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action = New-ScheduledTaskAction `
    -Execute $powerShell51 `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $scriptPath + '"') `
    -WorkingDirectory $LaneRoot

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$logonTrigger.Delay = 'PT1M'

$dailyStart = (Get-Date).AddMinutes(1)
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At $dailyStart
$dailyTrigger.Repetition = (New-ScheduledTaskTrigger `
    -Once `
    -At $dailyStart `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$dailyTrigger.Repetition.StopAtDurationEnd = $false

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

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $dailyTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

$registered = Get-ScheduledTask -TaskName $TaskName
$registeredLogonTriggers = @($registered.Triggers | Where-Object {
    $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger'
})
$registeredDailyTriggers = @($registered.Triggers | Where-Object {
    $_.CimClass.CimClassName -eq 'MSFT_TaskDailyTrigger'
})
$registeredLogonTrigger = $registeredLogonTriggers | Select-Object -First 1
$registeredDailyTrigger = $registeredDailyTriggers | Select-Object -First 1
if ($registered.Triggers.Count -ne 2 -or
        $registeredLogonTriggers.Count -ne 1 -or
        $registeredDailyTriggers.Count -ne 1 -or
        $registered.Principal.RunLevel -ne 'Highest' -or
        $registeredLogonTrigger.Delay -ne 'PT1M' -or
        $registeredDailyTrigger.DaysInterval -ne 1 -or
        $registeredDailyTrigger.Repetition.Interval -ne 'PT5M' -or
        $registeredDailyTrigger.Repetition.Duration -ne 'P1D' -or
        $registeredDailyTrigger.Repetition.StopAtDurationEnd -ne $false -or
        $registered.Actions[0].Execute -ne $powerShell51 -or
        $registered.Actions[0].Arguments -notlike ('*' + $scriptPath + '*')) {
    throw "Task $TaskName did not retain the expected elevated startup and one-day five-minute watchdog settings."
}

[pscustomobject]@{
    TaskName = $registered.TaskName
    UserId = $registered.Principal.UserId
    RunLevel = $registered.Principal.RunLevel
    LogonDelay = $registeredLogonTrigger.Delay
    RecurrenceDays = $registeredDailyTrigger.DaysInterval
    RepetitionInterval = $registeredDailyTrigger.Repetition.Interval
    RepetitionDuration = $registeredDailyTrigger.Repetition.Duration
    StopAtDurationEnd = $registeredDailyTrigger.Repetition.StopAtDurationEnd
    StartupScript = $scriptPath
    State = $registered.State
} | Format-List
