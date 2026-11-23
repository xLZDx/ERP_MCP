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
$ConfigPath = Join-Path $Root 'connector.json'
$RecoveryPath = Join-Path $Root 'rotation-recovery.json'
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

function Enter-ConnectorRotationMutex([int]$TimeoutSeconds = 60) {
    $mutexName = "Global\ERP_MCP_Cloudflare_Rotate_${CurrentSid}_$TunnelName"
    $mutex = [Threading.Mutex]::new($false, $mutexName)
    $acquired = $false
    try {
        try {
            $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))
        } catch [Threading.AbandonedMutexException] {
            # The previous rotation process exited while holding the lock. This process owns it now;
            # its protected recovery record is reconciled below before a new snapshot is taken.
            $acquired = $true
        }
        if (-not $acquired) { throw 'CLOUDFLARED_ROTATION_LOCK_TIMEOUT' }
        return $mutex
    } catch {
        try {
            if ($acquired) { $mutex.ReleaseMutex() }
        } finally {
            $mutex.Dispose()
        }
        throw
    }
}

function Exit-ConnectorRotationMutex([Threading.Mutex]$Mutex) {
    if (-not $Mutex) { return }
    try { $Mutex.ReleaseMutex() } finally { $Mutex.Dispose() }
}

function Resolve-Cloudflared {
    if ($CloudflaredPath) {
        if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
            throw 'CLOUDFLARED_BINARY_NOT_FOUND'
        }
        $resolvedPath = (Resolve-Path -LiteralPath $CloudflaredPath).Path
        if ([IO.Path]::GetExtension($resolvedPath) -ne '.exe') { throw 'CLOUDFLARED_BINARY_NOT_EXECUTABLE' }
        return $resolvedPath
    }
    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
        try {
            $savedPath = (Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json).cloudflared_path
        } catch {
            throw 'CLOUDFLARED_CONFIG_INVALID'
        }
        if ([string]::IsNullOrWhiteSpace([string]$savedPath) -or
            -not (Test-Path -LiteralPath $savedPath -PathType Leaf)) {
            throw 'CLOUDFLARED_CONFIGURED_BINARY_NOT_FOUND'
        }
        $resolvedPath = (Resolve-Path -LiteralPath $savedPath).Path
        if ([IO.Path]::GetExtension($resolvedPath) -ne '.exe') { throw 'CLOUDFLARED_CONFIGURED_BINARY_NOT_EXECUTABLE' }
        return $resolvedPath
    }
    $candidate = Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\Cloudflare') `
        -Filter 'cloudflared-*.exe' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $candidate) { throw 'CLOUDFLARED_BINARY_NOT_FOUND' }
    return $candidate.FullName
}

function Save-ConnectorConfig([string]$ResolvedCloudflaredPath) {
    $temporaryConfigPath = "$ConfigPath.new"
    try {
        $configJson = @{ cloudflared_path = $ResolvedCloudflaredPath } | ConvertTo-Json -Compress
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($temporaryConfigPath, $configJson, $utf8)
        Set-PrivateAcl -Path $temporaryConfigPath -Directory $false
        Move-Item -LiteralPath $temporaryConfigPath -Destination $ConfigPath -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryConfigPath) {
            Remove-Item -LiteralPath $temporaryConfigPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Save-EncryptedToken([string]$CipherText) {
    $temporarySecretPath = "$SecretPath.new"
    try {
        [IO.File]::WriteAllText($temporarySecretPath, $CipherText, [Text.Encoding]::ASCII)
        Set-PrivateAcl -Path $temporarySecretPath -Directory $false
        Move-Item -LiteralPath $temporarySecretPath -Destination $SecretPath -Force
    } finally {
        if (Test-Path -LiteralPath $temporarySecretPath) {
            Remove-Item -LiteralPath $temporarySecretPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Save-RotationRecovery(
    [string]$CipherText,
    [string]$ResolvedCloudflaredPath,
    [string]$Phase = 'ROLLBACK_PENDING'
) {
    $temporaryRecoveryPath = "$RecoveryPath.new"
    try {
        $recoveryJson = @{
            encrypted_token = $CipherText
            cloudflared_path = $ResolvedCloudflaredPath
            rotation_phase = $Phase
        } | ConvertTo-Json -Compress
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($temporaryRecoveryPath, $recoveryJson, $utf8)
        Set-PrivateAcl -Path $temporaryRecoveryPath -Directory $false
        Move-Item -LiteralPath $temporaryRecoveryPath -Destination $RecoveryPath -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryRecoveryPath) {
            Remove-Item -LiteralPath $temporaryRecoveryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Restore-InterruptedRotation {
    if (-not (Test-Path -LiteralPath $RecoveryPath -PathType Leaf)) { return }
    try {
        $recovery = Get-Content -LiteralPath $RecoveryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $recoveryToken = [string]$recovery.encrypted_token
        $recoveryCloudflaredPath = [string]$recovery.cloudflared_path
        if ([string]::IsNullOrWhiteSpace($recoveryToken) -or
            [string]::IsNullOrWhiteSpace($recoveryCloudflaredPath) -or
            [IO.Path]::GetExtension($recoveryCloudflaredPath) -ne '.exe' -or
            -not (Test-Path -LiteralPath $recoveryCloudflaredPath -PathType Leaf)) {
            throw 'ROTATION_RECOVERY_CONTENT_INVALID'
        }
        Save-EncryptedToken -CipherText $recoveryToken
        Save-ConnectorConfig -ResolvedCloudflaredPath $recoveryCloudflaredPath
        Remove-Item -LiteralPath $RecoveryPath -Force
    } catch {
        throw 'CLOUDFLARED_ROTATION_RECOVERY_FAILED; connector startup refused'
    }
}

function Remove-RotationRecovery {
    if (Test-Path -LiteralPath $RecoveryPath -PathType Leaf) {
        Remove-Item -LiteralPath $RecoveryPath -Force
    }
}

function Prepare-ConnectorRunAfterRotation {
    if (-not (Test-Path -LiteralPath $RecoveryPath -PathType Leaf)) { return }
    try {
        $recovery = Get-Content -LiteralPath $RecoveryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$recovery.rotation_phase -ceq 'REPLACEMENT_START_PENDING') {
            Save-RotationRecovery -CipherText ([string]$recovery.encrypted_token) `
                -ResolvedCloudflaredPath ([string]$recovery.cloudflared_path) `
                -Phase 'REPLACEMENT_START_CONSUMED'
            Add-Content -LiteralPath $LogPath -Value 'Rotation replacement startup accepted' -Encoding UTF8
            return
        }
    } catch {
        throw 'CLOUDFLARED_ROTATION_STATE_INVALID; connector startup refused'
    }
    Restore-InterruptedRotation
}

function Restore-PendingRotationBeforeRetry {
    if ($Mode -ne 'Rotate' -or -not (Test-Path -LiteralPath $RecoveryPath -PathType Leaf)) { return }
    $requestedCloudflaredPath = $CloudflaredPath
    try {
        $CloudflaredPath = ''
        $currentlyConfiguredPath = Resolve-Cloudflared
    } finally {
        $CloudflaredPath = $requestedCloudflaredPath
    }
    Stop-ConnectorTask -ResolvedCloudflaredPath $currentlyConfiguredPath
    Restore-InterruptedRotation
}

function Get-ConnectorProcessTreeIds {
    $processes = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    $scriptPath = [IO.Path]::GetFullPath($PSCommandPath)
    $roots = @($processes | Where-Object {
        $_.Name -match '^(powershell|pwsh)\.exe$' -and
        $_.CommandLine -and
        $_.CommandLine.IndexOf($scriptPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $_.CommandLine -match '(?i)(^|\s)-Mode\s+Run(\s|$)' -and
        $_.CommandLine -match ('(?i)(^|\s)-TunnelName\s+' + [regex]::Escape($TunnelName) + '(\s|$)')
    })
    $ids = [Collections.Generic.HashSet[int]]::new()
    foreach ($root in $roots) { [void]$ids.Add([int]$root.ProcessId) }
    do {
        $changed = $false
        foreach ($process in $processes) {
            if ($ids.Contains([int]$process.ParentProcessId) -and $ids.Add([int]$process.ProcessId)) {
                $changed = $true
            }
        }
    } while ($changed)
    return @($ids)
}

function Get-CloudflaredProcessIdsByPath([string]$ResolvedCloudflaredPath) {
    $expectedPath = [IO.Path]::GetFullPath($ResolvedCloudflaredPath)
    $processes = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    return @($processes | Where-Object {
        $_.ExecutablePath -and
        [string]::Equals([IO.Path]::GetFullPath([string]$_.ExecutablePath), $expectedPath,
            [StringComparison]::OrdinalIgnoreCase)
    } | ForEach-Object { [int]$_.ProcessId })
}

function Get-ConnectorProcessSnapshot([int[]]$ProcessIds) {
    $requestedIds = [Collections.Generic.HashSet[int]]::new()
    foreach ($processId in $ProcessIds) { [void]$requestedIds.Add([int]$processId) }
    if ($requestedIds.Count -eq 0) { return @() }
    $processes = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    return @($processes | Where-Object { $requestedIds.Contains([int]$_.ProcessId) } | ForEach-Object {
        [pscustomobject]@{
            ProcessId = [int]$_.ProcessId
            CreationDate = [string]$_.CreationDate
            ExecutablePath = [string]$_.ExecutablePath
            CommandLine = [string]$_.CommandLine
        }
    })
}

function Get-ConnectorProcessIdentity([object]$Process) {
    return [string]$Process.CreationDate + '|' + [string]$Process.ExecutablePath + '|' + [string]$Process.CommandLine
}

function Add-TrackedConnectorProcessSnapshot([int[]]$ProcessIds, [hashtable]$IdentityByPid) {
    foreach ($process in @(Get-ConnectorProcessSnapshot -ProcessIds $ProcessIds)) {
        $processId = [int]$process.ProcessId
        $identity = Get-ConnectorProcessIdentity -Process $process
        if ($IdentityByPid.ContainsKey($processId)) {
            if ([string]$IdentityByPid[$processId] -cne $identity) {
                throw 'CLOUDFLARED_PROCESS_IDENTITY_CHANGED'
            }
        } else {
            $IdentityByPid[$processId] = $identity
        }
    }
}

function Get-LiveTrackedConnectorProcessIds([hashtable]$IdentityByPid) {
    $processIds = @($IdentityByPid.Keys | ForEach-Object { [int]$_ })
    $live = @()
    foreach ($process in @(Get-ConnectorProcessSnapshot -ProcessIds $processIds)) {
        $processId = [int]$process.ProcessId
        $identity = Get-ConnectorProcessIdentity -Process $process
        if ([string]$IdentityByPid[$processId] -cne $identity) {
            throw 'CLOUDFLARED_PROCESS_IDENTITY_CHANGED'
        }
        $live += $processId
    }
    return @($live)
}

function Stop-ConnectorTask([string]$ResolvedCloudflaredPath, [int]$TimeoutSeconds = 20) {
    $trackedProcessIds = @(Get-ConnectorProcessTreeIds)
    $trackedIds = [Collections.Generic.HashSet[int]]::new()
    foreach ($processId in $trackedProcessIds) { [void]$trackedIds.Add([int]$processId) }
    $trackedIdentities = @{}
    Add-TrackedConnectorProcessSnapshot -ProcessIds $trackedProcessIds -IdentityByPid $trackedIdentities
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        $currentTreeIds = @(Get-ConnectorProcessTreeIds)
        foreach ($processId in $currentTreeIds) { [void]$trackedIds.Add([int]$processId) }
        Add-TrackedConnectorProcessSnapshot -ProcessIds $currentTreeIds -IdentityByPid $trackedIdentities
        $unscopedCloudflaredIds = @(Get-CloudflaredProcessIdsByPath $ResolvedCloudflaredPath |
            Where-Object { -not $trackedIds.Contains([int]$_) })
        if ($unscopedCloudflaredIds.Count -gt 0) { throw 'CLOUDFLARED_PROCESS_STOP_NOT_CONFIRMED' }
        $liveIds = @(Get-LiveTrackedConnectorProcessIds -IdentityByPid $trackedIdentities)
        if ((-not $task -or [string]$task.State -ne 'Running') -and $liveIds.Count -eq 0) { return }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)

    # Task Scheduler may end the PowerShell action without ending a child executable.
    # Terminate only processes captured in this task's command-line-rooted process tree.
    $currentTreeIds = @(Get-ConnectorProcessTreeIds)
    foreach ($processId in $currentTreeIds) { [void]$trackedIds.Add([int]$processId) }
    Add-TrackedConnectorProcessSnapshot -ProcessIds $currentTreeIds -IdentityByPid $trackedIdentities
    $unscopedCloudflaredIds = @(Get-CloudflaredProcessIdsByPath $ResolvedCloudflaredPath |
        Where-Object { -not $trackedIds.Contains([int]$_) })
    if ($unscopedCloudflaredIds.Count -gt 0) { throw 'CLOUDFLARED_PROCESS_STOP_NOT_CONFIRMED' }
    $remainingIds = @(Get-LiveTrackedConnectorProcessIds -IdentityByPid $trackedIdentities)
    foreach ($processId in $remainingIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        $currentTreeIds = @(Get-ConnectorProcessTreeIds)
        foreach ($processId in $currentTreeIds) { [void]$trackedIds.Add([int]$processId) }
        Add-TrackedConnectorProcessSnapshot -ProcessIds $currentTreeIds -IdentityByPid $trackedIdentities
        $unscopedCloudflaredIds = @(Get-CloudflaredProcessIdsByPath $ResolvedCloudflaredPath |
            Where-Object { -not $trackedIds.Contains([int]$_) })
        if ($unscopedCloudflaredIds.Count -gt 0) { throw 'CLOUDFLARED_PROCESS_STOP_NOT_CONFIRMED' }
        $liveIds = @(Get-LiveTrackedConnectorProcessIds -IdentityByPid $trackedIdentities)
        if ((-not $task -or [string]$task.State -ne 'Running') -and $liveIds.Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'CLOUDFLARED_CONNECTOR_STOP_NOT_CONFIRMED'
}

function Get-LogTextAfter([long]$Offset) {
    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) { return '' }
    $stream = [IO.File]::Open($LogPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        if ($stream.Length -lt $Offset) { return '' }
        [void]$stream.Seek($Offset, [IO.SeekOrigin]::Begin)
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true, 1024, $true)
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally {
        $stream.Dispose()
    }
}

function Start-ConnectorTaskAndWait(
    [string]$ResolvedCloudflaredPath,
    [int]$TimeoutSeconds = 60,
    [string]$ExpectedRotationMarker
) {
    $logOffset = if (Test-Path -LiteralPath $LogPath -PathType Leaf) { (Get-Item -LiteralPath $LogPath).Length } else { 0L }
    Start-ScheduledTask -TaskName $TaskName
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        $treeIds = @(Get-ConnectorProcessTreeIds)
        $connectorProcessIds = @(Get-CloudflaredProcessIdsByPath $ResolvedCloudflaredPath)
        $connectorRunning = @($treeIds | Where-Object { $connectorProcessIds -contains [int]$_ }).Count -gt 0
        $newLogText = Get-LogTextAfter -Offset $logOffset
        $rotationRunAccepted = [string]::IsNullOrEmpty($ExpectedRotationMarker) -or
            $newLogText.IndexOf($ExpectedRotationMarker, [StringComparison]::Ordinal) -ge 0
        if ($newLogText -match '(?i)unauthorized|invalid tunnel token|failed to authenticate|tunnel not found') {
            throw 'CLOUDFLARED_CONNECTOR_AUTHENTICATION_FAILED'
        }
        if ($task -and [string]$task.State -eq 'Running' -and $connectorRunning -and
            $rotationRunAccepted -and $newLogText -match 'Registered tunnel connection') {
            return
        }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'CLOUDFLARED_CONNECTOR_READINESS_NOT_CONFIRMED'
}

if ($Mode -eq 'Status') {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $cloudflared = Resolve-Cloudflared
    $processName = [IO.Path]::GetFileNameWithoutExtension($cloudflared)
    $taskProcessIds = @(Get-ConnectorProcessTreeIds)
    $process = @($taskProcessIds | ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue } |
        Where-Object { $_.ProcessName -eq $processName })
    [pscustomobject]@{
        TunnelName = $TunnelName
        TaskState = if ($task) { [string]$task.State } else { 'NOT_REGISTERED' }
        ConnectorProcessPresent = ($process.Count -gt 0)
        ConnectorProcessBelongsToScheduledTask = ($process.Count -gt 0 -and [string]$task.State -eq 'Running')
        EncryptedTokenPresent = Test-Path -LiteralPath $SecretPath
    } | ConvertTo-Json -Compress
    return
}

if ($Mode -eq 'Run') {
    Prepare-ConnectorRunAfterRotation
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

$rotationMutex = $null
if ($Mode -eq 'Rotate') {
    # Serialize snapshot → stop → replace → readiness/rollback across concurrent invocations.
    $rotationMutex = Enter-ConnectorRotationMutex
}
try {
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
if ($Mode -eq 'Rotate') { Restore-PendingRotationBeforeRetry }
$previousCloudflaredPath = $null
if ($Mode -eq 'Rotate') {
    # Resolve the currently configured executable without the rotation override so rollback
    # restores the exact pre-rotation connector configuration.
    $requestedCloudflaredPath = $CloudflaredPath
    try {
        $CloudflaredPath = ''
        $previousCloudflaredPath = Resolve-Cloudflared
    } finally {
        $CloudflaredPath = $requestedCloudflaredPath
    }
}
$resolvedCloudflaredPath = Resolve-Cloudflared
$previousEncryptedToken = if ($Mode -eq 'Rotate') { Get-Content -LiteralPath $SecretPath -Raw -Encoding ASCII } else { $null }
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
} finally {
    $secureInput.Dispose()
}

if ($Mode -eq 'Install') {
    $registered = $false
    try {
        Save-EncryptedToken -CipherText $encrypted
        Save-ConnectorConfig -ResolvedCloudflaredPath $resolvedCloudflaredPath
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
        Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue
        throw
    }
    try {
        Start-ConnectorTaskAndWait -ResolvedCloudflaredPath $resolvedCloudflaredPath
    } catch {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($registered) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $SecretPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue
        throw
    }
} else {
    Save-RotationRecovery -CipherText $previousEncryptedToken -ResolvedCloudflaredPath $previousCloudflaredPath
    Stop-ConnectorTask -ResolvedCloudflaredPath $previousCloudflaredPath
    try {
        Save-EncryptedToken -CipherText $encrypted
        Save-ConnectorConfig -ResolvedCloudflaredPath $resolvedCloudflaredPath
        Save-RotationRecovery -CipherText $previousEncryptedToken `
            -ResolvedCloudflaredPath $previousCloudflaredPath -Phase 'REPLACEMENT_START_PENDING'
        Start-ConnectorTaskAndWait -ResolvedCloudflaredPath $resolvedCloudflaredPath `
            -ExpectedRotationMarker 'Rotation replacement startup accepted'
        Remove-RotationRecovery
    } catch {
        try {
            Stop-ConnectorTask -ResolvedCloudflaredPath $resolvedCloudflaredPath
        } catch {
            throw 'CLOUDFLARED_ROTATION_FAILED; replacement connector stop could not be confirmed'
        }
        try {
            Save-EncryptedToken -CipherText $previousEncryptedToken
            Save-ConnectorConfig -ResolvedCloudflaredPath $previousCloudflaredPath
            Start-ConnectorTaskAndWait -ResolvedCloudflaredPath $previousCloudflaredPath
            Remove-RotationRecovery
        } catch {
            throw 'CLOUDFLARED_ROTATION_FAILED_AND_ROLLBACK_NOT_CONFIRMED'
        }
        throw 'CLOUDFLARED_ROTATION_FAILED; previous token restored and connector readiness confirmed'
    }
}
& $PSCommandPath -Mode Status -TunnelName $TunnelName
} finally {
    Exit-ConnectorRotationMutex -Mutex $rotationMutex
}
