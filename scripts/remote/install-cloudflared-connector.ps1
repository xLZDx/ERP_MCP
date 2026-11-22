# Installs a user-scoped Cloudflare Tunnel connector without putting its token in
# command arguments, Git, or a plaintext persistent file.
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Rotate', 'Run', 'Status')]
    [string]$Mode = 'Install',
    [Parameter(Mandatory = $true)]
    [ValidateSet('ivan', 'razer')]
    [string]$TunnelName,
    [string]$CloudflaredPath,
    [switch]$TokenFromStdin
)

$ErrorActionPreference = 'Stop'
$TaskName = "ERP_MCP_CloudflareTunnel_$TunnelName"
$Root = Join-Path $env:LOCALAPPDATA "ERP_MCP\cloudflared\$TunnelName"
$SecretPath = Join-Path $Root 'tunnel-token.dpapi'
$LogPath = Join-Path $Root 'cloudflared.log'
$PowerShellExecutable = if ($PSVersionTable.PSEdition -eq 'Core') { 'pwsh.exe' } else { 'powershell.exe' }
$PowerShellPath = Join-Path $PSHOME $PowerShellExecutable
if (-not (Test-Path -LiteralPath $PowerShellPath -PathType Leaf)) {
    throw 'POWERSHELL_EXECUTABLE_NOT_FOUND'
}
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$CurrentSid = $CurrentIdentity.User.Value
$TaskAccount = $CurrentIdentity.Name

function Set-PrivateAcl([string]$Path, [bool]$Directory) {
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    $inheritance = if ($Directory) {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    $propagation = [Security.AccessControl.PropagationFlags]::None
    foreach ($sid in @($CurrentSid, 'S-1-5-18', 'S-1-5-32-544')) {
        $identity = [Security.Principal.SecurityIdentifier]::new($sid)
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $identity,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.SetAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Resolve-Cloudflared {
    if ($CloudflaredPath) {
        if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
            throw 'CLOUDFLARED_BINARY_NOT_FOUND'
        }
        return (Resolve-Path -LiteralPath $CloudflaredPath).Path
    }
    $candidate = Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\Cloudflare') `
        -Filter 'cloudflared-*.exe' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $candidate) { throw 'CLOUDFLARED_BINARY_NOT_FOUND' }
    return $candidate.FullName
}

if ($Mode -eq 'Status') {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $cloudflared = Resolve-Cloudflared
    $processName = [IO.Path]::GetFileNameWithoutExtension($cloudflared)
    $process = Get-Process -Name $processName -ErrorAction SilentlyContinue
    [pscustomobject]@{
        TunnelName = $TunnelName
        TaskState = if ($task) { [string]$task.State } else { 'NOT_REGISTERED' }
        ConnectorProcessPresent = (@($process).Count -gt 0)
        EncryptedTokenPresent = Test-Path -LiteralPath $SecretPath
    } | ConvertTo-Json -Compress
    return
}

if ($Mode -eq 'Run') {
    if (-not (Test-Path -LiteralPath $SecretPath -PathType Leaf)) {
        throw 'ENCRYPTED_TUNNEL_TOKEN_NOT_FOUND'
    }
    $cloudflared = Resolve-Cloudflared
    $secureToken = Get-Content -LiteralPath $SecretPath -Raw | ConvertTo-SecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $env:TUNNEL_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        $runtimeToken = $env:TUNNEL_TOKEN
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $cloudflared tunnel run 2>&1 | ForEach-Object {
                $line = ([string]$_).Replace($runtimeToken, '<redacted>')
                $line = [regex]::Replace($line, 'eyJ[A-Za-z0-9_-]{30,}(?:={0,2})', '<redacted>')
                Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
            }
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        $cloudflaredExit = $LASTEXITCODE
        if ($cloudflaredExit -ne 0) { exit $cloudflaredExit }
    } finally {
        $runtimeToken = $null
        Remove-Item Env:\TUNNEL_TOKEN -ErrorAction SilentlyContinue
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        $secureToken.Dispose()
    }
    return
}

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    Set-PrivateAcl -Path $Root -Directory $true
}
$existingSecret = Test-Path -LiteralPath $SecretPath
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Mode -eq 'Install' -and ($existingSecret -or $existingTask)) {
    throw 'CONNECTOR_ALREADY_CONFIGURED; inspect Status before changing it'
}
if ($Mode -eq 'Rotate' -and (-not $existingSecret -or -not $existingTask)) {
    throw 'CONNECTOR_NOT_CONFIGURED_FOR_ROTATION'
}
$null = Resolve-Cloudflared
$secureInput = if ($TokenFromStdin) {
    $rawToken = [Console]::In.ReadLine()
    if ([string]::IsNullOrWhiteSpace($rawToken)) {
        throw 'TUNNEL_TOKEN_STDIN_EMPTY'
    }
    try {
        ConvertTo-SecureString -String $rawToken -AsPlainText -Force
    } finally {
        $rawToken = $null
    }
} else {
    Read-Host "Paste the Cloudflare connector token for $TunnelName (input is hidden)" -AsSecureString
}
if ($secureInput.Length -lt 100) {
    $secureInput.Dispose()
    throw 'TUNNEL_TOKEN_TOO_SHORT'
}
try {
    $encrypted = ConvertFrom-SecureString -SecureString $secureInput
    if ($Mode -eq 'Rotate') {
        $temporarySecretPath = "$SecretPath.new"
        Set-Content -LiteralPath $temporarySecretPath -Value $encrypted -NoNewline -Encoding ASCII
        Set-PrivateAcl -Path $temporarySecretPath -Directory $false
        Move-Item -LiteralPath $temporarySecretPath -Destination $SecretPath -Force
    } else {
        Set-Content -LiteralPath $SecretPath -Value $encrypted -NoNewline -Encoding ASCII
        Set-PrivateAcl -Path $SecretPath -Directory $false
    }
} finally {
    if ($temporarySecretPath -and (Test-Path -LiteralPath $temporarySecretPath)) {
        Remove-Item -LiteralPath $temporarySecretPath -Force -ErrorAction SilentlyContinue
    }
    $secureInput.Dispose()
}

if ($Mode -eq 'Install') {
    $registered = $false
    try {
        $actionArgs = "-NoProfile -ExecutionPolicy RemoteSigned -NonInteractive -File `"$PSCommandPath`" -Mode Run -TunnelName $TunnelName"
        $action = New-ScheduledTaskAction -Execute $PowerShellPath -Argument $actionArgs
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $TaskAccount
        $principal = New-ScheduledTaskPrincipal -UserId $TaskAccount -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
            -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 5) `
            -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings -Description 'Runs the ERP_MCP Cloudflare Tunnel connector for the signed-in user.' |
            Out-Null
        $registered = $true
    } catch {
        if ($registered) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $SecretPath -Force -ErrorAction SilentlyContinue
        throw
    }
}
try {
    Start-ScheduledTask -TaskName $TaskName
} catch {
    if ($Mode -eq 'Install' -and $registered) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    }
    if ($Mode -eq 'Install') {
        Remove-Item -LiteralPath $SecretPath -Force -ErrorAction SilentlyContinue
    }
    throw
}
Start-Sleep -Seconds 4
& $PSCommandPath -Mode Status -TunnelName $TunnelName
