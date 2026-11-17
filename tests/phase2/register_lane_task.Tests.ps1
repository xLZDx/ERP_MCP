$installerPath = Join-Path $PSScriptRoot '..\..\scripts\real1c\autostart\register_lane_task.ps1'
$installerPath = (Resolve-Path -LiteralPath $installerPath).Path

function New-ScheduledTaskAction {
    param([string]$Execute, [string]$Argument, [string]$WorkingDirectory)
}
function New-ScheduledTaskTrigger { param([switch]$AtLogOn, [string]$User) }
function New-ScheduledTaskSettingsSet {
    param($ExecutionTimeLimit, $MultipleInstances, [switch]$StartWhenAvailable,
        [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries)
}
function New-ScheduledTaskPrincipal { param([string]$UserId, [string]$LogonType, [string]$RunLevel) }
function Register-ScheduledTask {
    param([string]$TaskName, [object[]]$Action, [object[]]$Trigger, $Settings, $Principal, [switch]$Force)
}
function Get-ScheduledTask { param([string]$TaskName) }
function Disable-ScheduledTask { param([string]$TaskName) }

function New-RegisteredLaneTask {
    param(
        [string]$State = 'Ready',
        [object[]]$Triggers = @(),
        [object[]]$Actions = @(),
        [string]$UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name,
        [string]$LogonType = 'Interactive',
        [string]$RunLevel = 'Highest'
    )

    [pscustomobject]@{
        TaskName = 'ERP_MCP_Lane_Autostart'
        State = $State
        Triggers = $Triggers
        Actions = $Actions
        Principal = [pscustomobject]@{
            UserId = $UserId
            LogonType = $LogonType
            RunLevel = $RunLevel
        }
    }
}

function New-LogonTrigger {
    param(
        [string]$Delay = 'PT1M',
        [bool]$Enabled = $true,
        [string]$RepetitionInterval = ''
    )

    [pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskLogonTrigger' }
        Enabled = $Enabled
        Delay = $Delay
        Repetition = [pscustomobject]@{ Interval = $RepetitionInterval }
    }
}

function New-PeriodicTrigger {
    [pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskDailyTrigger' }
        Enabled = $true
        Repetition = [pscustomobject]@{ Interval = 'PT5M' }
    }
}

function Set-LaneTaskScenario {
    param(
        [object]$ReadBack,
        [switch]$RegistrationFails,
        [switch]$ReadBackFails
    )

    $global:laneTaskScenario = [pscustomobject]@{
        ReadBack = $ReadBack
        RegistrationFails = [bool]$RegistrationFails
        ReadBackFails = [bool]$ReadBackFails
        GetCalls = 0
        DisableCalls = 0
        RegisterParameters = $null
    }
}

function Invoke-LaneInstaller {
    param([string]$LaneRoot, [string]$TaskName = 'ERP_MCP_Lane_Autostart')

    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
    if ($isAdmin) {
        & $installerPath -LaneRoot $LaneRoot -TaskName $TaskName
        return
    }

    # Keep the registration/read-back code under test unchanged. In a non-elevated test
    # process, omit only the two execution gates; a separate test asserts both gates exist.
    $source = Get-Content -LiteralPath $installerPath -Raw
    $source = [regex]::Replace($source, '(?m)^#Requires .+\r?\n', '')
    $guardPattern = '(?ms)^if \(-not \$principalCheck\.IsInRole\([^\r\n]+\r?\n\s*throw ''Run this script from elevated Windows PowerShell\.''\r?\n\}'
    $guard = [regex]::Match($source, $guardPattern)
    if (-not $guard.Success) {
        throw 'Could not isolate installer body while preserving the admin-guard assertion.'
    }
    $isolatedSource = $source.Remove($guard.Index, $guard.Length)
    $isolatedScript = [scriptblock]::Create($isolatedSource)
    & $isolatedScript -LaneRoot $LaneRoot -TaskName $TaskName
}

Describe 'register_lane_task fail-closed installer contract' {
    BeforeEach {
        $laneRoot = Join-Path $TestDrive 'lane'
        $startupDirectory = Join-Path $laneRoot 'autostart'
        New-Item -ItemType Directory -Path $startupDirectory -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $startupDirectory 'start_lane.ps1') -Value '# mocked lane startup'

        Mock New-ScheduledTaskAction {
            [pscustomobject]@{
                Execute = $Execute
                Arguments = $Argument
                WorkingDirectory = $WorkingDirectory
            }
        }
        Mock New-ScheduledTaskTrigger {
            New-LogonTrigger -Delay '' -Enabled $true
        }
        Mock New-ScheduledTaskSettingsSet { [pscustomobject]@{} }
        Mock New-ScheduledTaskPrincipal {
            [pscustomobject]@{
                UserId = $UserId
                LogonType = $LogonType
                RunLevel = $RunLevel
            }
        }
        Mock Register-ScheduledTask {
            $global:laneTaskScenario.RegisterParameters = [pscustomobject]@{
                TaskName = $TaskName
                Action = @($Action)
                Trigger = @($Trigger)
                Settings = $Settings
                Principal = $Principal
                Force = $Force
            }
            if ($global:laneTaskScenario.RegistrationFails) { throw 'simulated registration failure' }
        }
        Mock Get-ScheduledTask {
            $global:laneTaskScenario.GetCalls++
            if ($global:laneTaskScenario.ReadBackFails -and $global:laneTaskScenario.GetCalls -eq 1) {
                throw 'simulated read-back failure'
            }
            return $global:laneTaskScenario.ReadBack
        }
        Mock Disable-ScheduledTask {
            $global:laneTaskScenario.DisableCalls++
            $global:laneTaskScenario.ReadBack.State = 'Disabled'
        }
        $script:laneRoot = $laneRoot
    }

    AfterEach {
        Remove-Variable laneTaskScenario -Scope Global -ErrorAction SilentlyContinue
    }

    It 'retains both the PowerShell administrator requirement and the in-script elevation guard' {
        $source = Get-Content -LiteralPath $installerPath -Raw
        $source | Should Match '(?m)^#Requires -RunAsAdministrator\s*$'
        $source | Should Match 'principalCheck\.IsInRole\(\[Security\.Principal\.WindowsBuiltInRole\]::Administrator\)'
        $source | Should Match "throw 'Run this script from elevated Windows PowerShell\.'"
    }

    It 'registers exactly one enabled delayed logon trigger, the expected action and the current interactive highest principal' {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $powerShell51 = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $startupScript = Join-Path $script:laneRoot 'autostart\start_lane.ps1'
        $action = [pscustomobject]@{
            Execute = $powerShell51
            Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $startupScript + '"'
        }
        $task = New-RegisteredLaneTask -Triggers @((New-LogonTrigger)) -Actions @($action)
        Set-LaneTaskScenario -ReadBack $task

        Invoke-LaneInstaller -LaneRoot $script:laneRoot | Out-String | Should Match 'LogonDelay\s+: PT1M'

        $global:laneTaskScenario.DisableCalls | Should Be 0
        @($global:laneTaskScenario.RegisterParameters.Trigger).Count | Should Be 1
        $global:laneTaskScenario.RegisterParameters.Trigger[0].CimClass.CimClassName | Should Be 'MSFT_TaskLogonTrigger'
        $global:laneTaskScenario.RegisterParameters.Trigger[0].Delay | Should Be 'PT1M'
        $global:laneTaskScenario.RegisterParameters.Principal.UserId | Should Be $identity.Name
        $global:laneTaskScenario.RegisterParameters.Principal.LogonType | Should Be 'Interactive'
        $global:laneTaskScenario.RegisterParameters.Principal.RunLevel | Should Be 'Highest'
        $global:laneTaskScenario.RegisterParameters.Action.Execute | Should Be $powerShell51
        $global:laneTaskScenario.RegisterParameters.Action.Arguments | Should Match ([regex]::Escape($startupScript))
        Assert-MockCalled Register-ScheduledTask -Times 1
        Assert-MockCalled Disable-ScheduledTask -Times 0
    }

    It 'fails closed after registration failure and confirms the task is disabled' {
        $task = New-RegisteredLaneTask -Triggers @((New-LogonTrigger)) -Actions @([pscustomobject]@{})
        Set-LaneTaskScenario -ReadBack $task -RegistrationFails

        $message = $null
        try { Invoke-LaneInstaller -LaneRoot $script:laneRoot } catch { $message = $_.Exception.Message }

        $message | Should Match 'registration failed'
        $task.State | Should Be 'Disabled'
        $global:laneTaskScenario.DisableCalls | Should Be 1
        Assert-MockCalled Disable-ScheduledTask -Times 1
    }

    It 'fails closed when registration succeeds but state read-back fails' {
        $task = New-RegisteredLaneTask -Triggers @((New-LogonTrigger)) -Actions @([pscustomobject]@{})
        Set-LaneTaskScenario -ReadBack $task -ReadBackFails

        $message = $null
        try { Invoke-LaneInstaller -LaneRoot $script:laneRoot } catch { $message = $_.Exception.Message }

        $message | Should Match 'could not be read back'
        $task.State | Should Be 'Disabled'
        $global:laneTaskScenario.DisableCalls | Should Be 1
    }

    It 'fails closed when read-back contains multiple triggers' {
        $task = New-RegisteredLaneTask -Triggers @((New-LogonTrigger), (New-LogonTrigger)) -Actions @([pscustomobject]@{})
        Set-LaneTaskScenario -ReadBack $task

        $message = $null
        try { Invoke-LaneInstaller -LaneRoot $script:laneRoot } catch { $message = $_.Exception.Message }

        $message | Should Match 'did not retain the expected settings'
        $task.State | Should Be 'Disabled'
        $global:laneTaskScenario.DisableCalls | Should Be 1
    }

    It 'fails closed when read-back contains a periodic trigger' {
        $task = New-RegisteredLaneTask -Triggers @((New-LogonTrigger), (New-PeriodicTrigger)) -Actions @([pscustomobject]@{})
        Set-LaneTaskScenario -ReadBack $task

        $message = $null
        try { Invoke-LaneInstaller -LaneRoot $script:laneRoot } catch { $message = $_.Exception.Message }

        $message | Should Match 'unexpected periodic triggers'
        $task.State | Should Be 'Disabled'
        $global:laneTaskScenario.DisableCalls | Should Be 1
    }

    It 'fails closed when the read-back action or principal differs from the expected contract' {
        $task = New-RegisteredLaneTask `
            -Triggers @((New-LogonTrigger -Delay 'PT2M')) `
            -Actions @([pscustomobject]@{ Execute = 'wrong.exe'; Arguments = 'wrong.ps1' }) `
            -UserId 'different-user' -LogonType 'Password' -RunLevel 'LUA'
        Set-LaneTaskScenario -ReadBack $task

        $message = $null
        try { Invoke-LaneInstaller -LaneRoot $script:laneRoot } catch { $message = $_.Exception.Message }

        $message | Should Match 'did not retain the expected settings'
        $task.State | Should Be 'Disabled'
        $global:laneTaskScenario.DisableCalls | Should Be 1
    }
}
