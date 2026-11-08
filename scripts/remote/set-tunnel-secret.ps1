<#
.SYNOPSIS
  Run on the 1C host. Stores the OpenAI tunnel runtime API key as a CurrentUser DPAPI blob and the tunnel id in tunnel.json.
  Interactive mode (default): the key is typed into a hidden prompt.
  -FromStdin mode: the key is read from standard input (one line), so a calling session can pipe it over SSH without
  putting it on a command line. The key is never echoed, logged, or passed as an argument.
  A DPAPI blob only opens for the same Windows user on the same machine, so this must run on the host that will use it.
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\1c\mcp',
    [string]$TunnelId,
    [switch]$FromStdin
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
$envDir = Join-Path $Root 'env'
New-Item -ItemType Directory -Force -Path $envDir | Out-Null

if (-not $TunnelId) { $TunnelId = (Read-Host 'Tunnel id (starts with tunnel_)') }
$TunnelId = $TunnelId.Trim()
if ($TunnelId -notmatch '^tunnel_[A-Za-z0-9_-]+$') { throw 'The tunnel id must look like tunnel_xxxxxxxx' }

if ($FromStdin) {
    $plain = [Console]::In.ReadLine()
    if ($null -eq $plain) { throw 'no key on stdin' }
    $plain = $plain.Trim()
} else {
    $secure = Read-Host 'Runtime API key (input is hidden)' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
if ($plain.Length -lt 20) { throw 'The key looks too short' }
$bytes = [Text.UTF8Encoding]::new($false).GetBytes($plain)
$plain = $null
$blob = [Security.Cryptography.ProtectedData]::Protect($bytes, $null, 'CurrentUser')
[IO.File]::WriteAllBytes((Join-Path $envDir 'tunnel_api_key.dpapi'), $blob)
[Array]::Clear($bytes, 0, $bytes.Length)

@{ tunnel_id = $TunnelId; endpoint = 'http://100.88.71.74:21000/mcp'; configured_at_utc = (Get-Date).ToUniversalTime().ToString('o') } |
    ConvertTo-Json | Set-Content -Path (Join-Path $envDir 'tunnel.json') -Encoding UTF8
'Saved: tunnel id ' + $TunnelId + ' and an encrypted key blob (' + (Get-Item (Join-Path $envDir 'tunnel_api_key.dpapi')).Length + ' bytes).'

$StackTaskName = 'ERP_MCP_Ivan_Stack'
$ExpectedStackScript = [IO.Path]::GetFullPath((Join-Path $Root 'run-mcp-stack.ps1'))
try {
    $StackTask = Get-ScheduledTask -TaskName $StackTaskName -ErrorAction Stop
    $TaskActions = @($StackTask.Actions)
    $MatchingAction = @($TaskActions | Where-Object {
        $IsPowerShell = $_.Execute -match '(^|\\)powershell(?:\.exe)?$'
        $FileArgument = [regex]::Match([string]$_.Arguments, '(?i)^\s*-NoProfile\s+-ExecutionPolicy\s+Bypass\s+-WindowStyle\s+Hidden\s+-File\s+"([^"]+\.ps1)"\s*$')
        $IsPowerShell -and $FileArgument.Success -and
            [IO.Path]::GetFullPath($FileArgument.Groups[1].Value) -ieq $ExpectedStackScript
    })
    if (-not $StackTask.Settings.Enabled -or $TaskActions.Count -ne 1 -or $MatchingAction.Count -ne 1) {
        Write-Warning ('Secret was saved, but ' + $StackTaskName + ' was not started: task must be enabled with exactly one action targeting ' + $ExpectedStackScript + '.')
    } elseif ($StackTask.State -eq 'Running') {
        Write-Warning ('Secret was saved, but ' + $StackTaskName + ' is already running; no overlapping start was requested. Start it again after the current pass returns to Ready.')
    } else {
        Start-ScheduledTask -TaskName $StackTaskName -ErrorAction Stop
        Write-Output 'Stack start requested via enabled task ' + $StackTaskName + '; tunnel connection is not verified.'
    }
} catch {
    Write-Warning ('Secret was saved, but ' + $StackTaskName + ' could not be started: ' + $_.Exception.Message)
}
