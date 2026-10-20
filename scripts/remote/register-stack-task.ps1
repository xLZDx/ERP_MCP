<#
.SYNOPSIS
  Restricts the secret directory ACL and registers the scheduled task that keeps the ERP_MCP stack running
  (logon + 1 minute delay, repeated hourly; run-mcp-stack.ps1 is idempotent). Runs as the current user, interactive logon.
#>
[CmdletBinding()]
param([string]$Root = 'D:\1c\mcp', [string]$TaskName = 'ERP_MCP_Ivan_Stack')
$ErrorActionPreference = 'Stop'
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$envDir = Join-Path $Root 'env'
& icacls.exe $envDir /inheritance:r /grant:r ($me + ':(OI)(CI)F') 'BUILTIN\Administrators:(OI)(CI)F' | Out-Null
'acl env dir ok: ' + ($LASTEXITCODE -eq 0)

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $Root 'run-mcp-stack.ps1') + '"')
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
$trigger.Delay = 'PT1M'
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)).Repetition
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
'task registered: ' + [bool](Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
