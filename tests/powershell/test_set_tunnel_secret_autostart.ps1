$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot '..\..\scripts\remote\set-tunnel-secret.ps1'
$script:temporaryRoot = $null
$global:erpMcpTestTaskFound = $true
$global:erpMcpTestTaskEnabled = $true
$global:erpMcpTestTaskState = 'Ready'
$global:erpMcpTestTaskActionArguments = $null
$global:erpMcpTestTaskExtraAction = $null
$global:erpMcpTestStartCount = 0
$global:erpMcpTestStartFailure = $false
$global:erpMcpTestKeyPromptCount = 0
$global:erpMcpTestGetTaskCount = 0

function Read-Host {
    [CmdletBinding()]
    param([string]$Prompt, [switch]$AsSecureString)
    if ($Prompt -like 'Runtime API key*' -and $AsSecureString) {
        $global:erpMcpTestKeyPromptCount++
        return ConvertTo-SecureString 'test-runtime-key-1234567890-abcdefghijklmnopqrstuvwxyz' -AsPlainText -Force
    }
    throw ('Unexpected prompt: ' + $Prompt)
}

function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName, [Parameter(ValueFromRemainingArguments = $true)]$Remaining)
    $global:erpMcpTestGetTaskCount++
    if (-not $global:erpMcpTestTaskFound) { throw ('Task not found: ' + $TaskName) }
    $actions = @([pscustomobject]@{ Execute = 'powershell.exe'; Arguments = $global:erpMcpTestTaskActionArguments })
    if ($null -ne $global:erpMcpTestTaskExtraAction) { $actions += $global:erpMcpTestTaskExtraAction }
    return [pscustomobject]@{
        State = $global:erpMcpTestTaskState
        Settings = [pscustomobject]@{ Enabled = $global:erpMcpTestTaskEnabled }
        Actions = $actions
    }
}

function Start-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    $global:erpMcpTestStartCount++
    if ($global:erpMcpTestStartFailure) { throw 'simulated scheduler refusal' }
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Reset-Case {
    if ($script:temporaryRoot -and (Test-Path -LiteralPath $script:temporaryRoot)) {
        Remove-Item -LiteralPath $script:temporaryRoot -Recurse -Force
    }
    $script:temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('erp-mcp-secret-autostart-' + [guid]::NewGuid().ToString('N'))
    $global:erpMcpTestTaskFound = $true
    $global:erpMcpTestTaskEnabled = $true
    $global:erpMcpTestTaskState = 'Ready'
    $global:erpMcpTestTaskActionArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $script:temporaryRoot 'run-mcp-stack.ps1') + '"'
    $global:erpMcpTestTaskExtraAction = $null
    $global:erpMcpTestStartCount = 0
    $global:erpMcpTestStartFailure = $false
    $global:erpMcpTestKeyPromptCount = 0
    $global:erpMcpTestGetTaskCount = 0
    New-Item -ItemType Directory -Path $script:temporaryRoot -Force | Out-Null
}

function Invoke-Provisioning {
    $localWarnings = @()
    $output = & $scriptPath -Root $script:temporaryRoot -TunnelId 'tunnel_test_autostart_1' -WarningAction SilentlyContinue -WarningVariable localWarnings
    return [pscustomobject]@{ Output = @($output); Warnings = @($localWarnings) }
}

function Assert-CredentialWritten([string[]]$Output) {
    $keyPath = Join-Path $script:temporaryRoot 'env\tunnel_api_key.dpapi'
    $configPath = Join-Path $script:temporaryRoot 'env\tunnel.json'
    Assert-True (Test-Path -LiteralPath $keyPath) 'Encrypted key blob must be written before task startup.'
    Assert-True ((Get-Item -LiteralPath $keyPath).Length -gt 0) 'Encrypted key blob must not be empty.'
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    Assert-True ($config.tunnel_id -eq 'tunnel_test_autostart_1') 'Configured tunnel ID must be saved.'
    Assert-True (($Output -join "`n") -match 'Saved: tunnel id tunnel_test_autostart_1') 'Successful credential persistence must be reported.'
    Assert-True ($global:erpMcpTestKeyPromptCount -eq 1) 'The test must use exactly one fake hidden key input.'
}

try {
    Reset-Case
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 1) ('An enabled task targeting this Root must be started once; calls=' + $global:erpMcpTestStartCount + '; getCalls=' + $global:erpMcpTestGetTaskCount + '; warnings=' + ($warnings -join '|'))
    Assert-True (($output -join "`n") -match 'tunnel connection is not verified') 'Task start must not be reported as control-plane verification.'

    Reset-Case
    $global:erpMcpTestTaskFound = $false
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 0) 'A missing task must not be started.'
    Assert-True (($warnings -join "`n") -match 'could not be started') 'A missing task must produce a warning.'

    Reset-Case
    $global:erpMcpTestTaskEnabled = $false
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 0) 'A disabled task must not be started.'
    Assert-True (($warnings -join "`n") -match 'task must be enabled with exactly one action') 'A disabled task must produce a warning.'

    Reset-Case
    $global:erpMcpTestTaskActionArguments = '-File "D:\other\run-mcp-stack.ps1"'
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 0) 'A task targeting another Root must not be started.'
    Assert-True (($warnings -join "`n") -match 'task must be enabled with exactly one action') 'A mismatched task must produce a warning.'

    Reset-Case
    $expectedScript = Join-Path $script:temporaryRoot 'run-mcp-stack.ps1'
    $global:erpMcpTestTaskActionArguments = '-File "' + $expectedScript + '-malicious"'
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 0) 'A task action path with a malicious suffix must not be started.'
    Assert-True ($warnings.Count -gt 0) 'A task action path with a malicious suffix must produce a warning.'

    Reset-Case
    $expectedScript = Join-Path $script:temporaryRoot 'run-mcp-stack.ps1'
    $global:erpMcpTestTaskActionArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Write-Output bypass" -File "' + $expectedScript + '"'
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 0) 'A task action with extra -Command arguments must not be started.'
    Assert-True (($warnings -join "`n") -match 'exactly one action') 'A task action with extra -Command arguments must produce a warning.'

    Reset-Case
    $global:erpMcpTestTaskExtraAction = [pscustomobject]@{ Execute = 'cmd.exe'; Arguments = '/c unrelated-task-action' }
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 0) 'A task with an unrelated second action must not be started.'
    Assert-True (($warnings -join "`n") -match 'exactly one action') 'A task with an unrelated second action must produce a warning.'

    Reset-Case
    $global:erpMcpTestTaskState = 'Running'
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 0) 'A running task must not receive an overlapping start request.'
    Assert-True (($warnings -join "`n") -match 'is already running; no overlapping start was requested') 'A running task must produce a warning that its start was not queued.'

    Reset-Case
    $global:erpMcpTestStartFailure = $true
    $result = Invoke-Provisioning
    $output = $result.Output
    $warnings = $result.Warnings
    Assert-CredentialWritten $output
    Assert-True ($global:erpMcpTestStartCount -eq 1) 'The enabled task start must be attempted once.'
    Assert-True (($warnings -join "`n") -match 'could not be started: simulated scheduler refusal') 'A task start failure must be visible as a warning.'

    'Passed 9 focused tunnel-secret autostart cases.'
} finally {
    if ($script:temporaryRoot -and (Test-Path -LiteralPath $script:temporaryRoot)) {
        Remove-Item -LiteralPath $script:temporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
