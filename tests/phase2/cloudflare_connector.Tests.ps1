$connectorPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\scripts\remote\install-cloudflared-connector.ps1')).Path
$connectorAst = [System.Management.Automation.Language.Parser]::ParseFile($connectorPath, [ref]$null, [ref]$null)

function Get-ConnectorAstNode([string]$Name, [type]$NodeType) {
    return $connectorAst.Find({
        param($node)
        $NodeType.IsInstanceOfType($node) -and $node.Name -eq $Name
    }, $true)
}

function Get-ConnectorFunctionScriptBlock([string]$Name) {
    $node = Get-ConnectorAstNode -Name $Name -NodeType ([System.Management.Automation.Language.FunctionDefinitionAst])
    if (-not $node) { throw "FUNCTION_NOT_FOUND:$Name" }
    return [scriptblock]::Create($node.Extent.Text)
}

function Get-ConnectorFunctionText([string]$Name) {
    $node = Get-ConnectorAstNode -Name $Name -NodeType ([System.Management.Automation.Language.FunctionDefinitionAst])
    if (-not $node) { throw "FUNCTION_NOT_FOUND:$Name" }
    return $node.Extent.Text
}

function Get-RotateElseBlock {
    $branch = $connectorAst.Find({
        param($node)
        $node -is [System.Management.Automation.Language.IfStatementAst] -and
            $node.ElseClause -and
            $node.Extent.Text -match 'if \(\$Mode -eq ''Install''\)' -and
            $node.ElseClause.Extent.Text -match 'Save-EncryptedToken'
    }, $true)
    if (-not $branch) { throw 'ROTATE_BRANCH_NOT_FOUND' }
    $body = @($branch.ElseClause.Statements | ForEach-Object { $_.Extent.Text }) -join "`n"
    return [scriptblock]::Create($body)
}

function Get-RunRecoveryFirstStatement {
    $run = $connectorAst.Find({
        param($node)
        $node -is [System.Management.Automation.Language.IfStatementAst] -and
            $node.Extent.Text -match "if \(\`$Mode -eq 'Run'\)"
    }, $true)
    if (-not $run) { throw 'RUN_BRANCH_NOT_FOUND' }
    $body = @($run.Clauses[0].Item2.Statements)
    if ($body.Count -lt 1 -or $body[0].Extent.Text -notmatch '^Prepare-ConnectorRunAfterRotation$') {
        throw 'RUN_RECOVERY_NOT_FIRST'
    }
    return [scriptblock]::Create($body[0].Extent.Text)
}

Describe 'Cloudflare connector executable-path and rotation contract' {
    BeforeEach {
        $script:connectorRoot = Join-Path $TestDrive 'connector'
        New-Item -ItemType Directory -Path $script:connectorRoot -Force | Out-Null
        $script:ConfigPath = Join-Path $script:connectorRoot 'connector.json'
        $script:SecretPath = Join-Path $script:connectorRoot 'tunnel-token.dpapi'
        $script:LogPath = Join-Path $script:connectorRoot 'cloudflared.log'
        $script:RecoveryPath = Join-Path $script:connectorRoot 'rotation-recovery.json'
        $script:CloudflaredPath = ''
        $script:TunnelName = 'razer'
        $script:TaskName = 'ERP_MCP_CloudflareTunnel_razer'
        $script:PSCommandPath = $connectorPath
        function Set-PrivateAcl { param([string]$Path, [bool]$Directory) }
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Remove-RotationRecovery')))
    }

    It 'persists and resolves a custom executable path for a later Run invocation' {
        . (Get-ConnectorFunctionScriptBlock 'Save-ConnectorConfig')
        . (Get-ConnectorFunctionScriptBlock 'Resolve-Cloudflared')
        $customBinary = Join-Path $script:connectorRoot 'custom-cloudflared.exe'
        Set-Content -LiteralPath $customBinary -Value 'fake executable' -NoNewline

        Save-ConnectorConfig -ResolvedCloudflaredPath $customBinary
        $script:CloudflaredPath = ''
        $resolved = Resolve-Cloudflared

        $resolved | Should Be (Resolve-Path -LiteralPath $customBinary).Path
        (Get-Content -LiteralPath $script:ConfigPath -Raw | ConvertFrom-Json).cloudflared_path |
            Should Be (Resolve-Path -LiteralPath $customBinary).Path
    }

    It 'fails closed when the persisted custom executable is missing' {
        . (Get-ConnectorFunctionScriptBlock 'Save-ConnectorConfig')
        . (Get-ConnectorFunctionScriptBlock 'Resolve-Cloudflared')
        $customBinary = Join-Path $script:connectorRoot 'custom-cloudflared.exe'
        Set-Content -LiteralPath $customBinary -Value 'fake executable' -NoNewline
        Save-ConnectorConfig -ResolvedCloudflaredPath $customBinary
        Remove-Item -LiteralPath $customBinary -Force
        $script:CloudflaredPath = ''

        { Resolve-Cloudflared } | Should Throw 'CLOUDFLARED_CONFIGURED_BINARY_NOT_FOUND'
    }

    It 'Mode Run restores the old token and executable after a crash at either rotation write boundary' {
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Save-EncryptedToken')))
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Save-ConnectorConfig')))
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Save-RotationRecovery')))
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Restore-InterruptedRotation')))
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Prepare-ConnectorRunAfterRotation')))
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Resolve-Cloudflared')))
        (Get-Command Save-RotationRecovery).Definition | Should Match 'temporaryRecoveryPath'
        $RecoveryPath | Should Be $script:RecoveryPath
        $oldBinary = Join-Path $script:connectorRoot 'cloudflared-old.exe'
        $newBinary = Join-Path $script:connectorRoot 'cloudflared-new.exe'
        Set-Content -LiteralPath $oldBinary -Value 'old executable' -NoNewline
        Set-Content -LiteralPath $newBinary -Value 'new executable' -NoNewline
        [IO.File]::Exists($oldBinary) | Should Be $true
        [IO.File]::Exists($newBinary) | Should Be $true
        $script:CloudflaredPath = ''
        $runRecovery = Get-RunRecoveryFirstStatement
        $crashBoundaries = @('after-token-replacement', 'after-config-replacement')

        foreach ($boundary in $crashBoundaries) {
            Save-EncryptedToken -CipherText 'old-dpapi-ciphertext'
            Save-ConnectorConfig -ResolvedCloudflaredPath $oldBinary
            Save-RotationRecovery -CipherText 'old-dpapi-ciphertext' -ResolvedCloudflaredPath $oldBinary
            [IO.File]::Exists($script:RecoveryPath) | Should Be $true
            [IO.File]::Exists($oldBinary) | Should Be $true
            $savedRecovery = Get-Content -LiteralPath $script:RecoveryPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $savedRecovery.encrypted_token | Should Be 'old-dpapi-ciphertext'
            $savedRecovery.cloudflared_path | Should Be $oldBinary

            # Recreate the durable partial state left by a crash during rotation.
            Save-EncryptedToken -CipherText 'new-dpapi-ciphertext'
            if ($boundary -eq 'after-config-replacement') {
                Save-ConnectorConfig -ResolvedCloudflaredPath $newBinary
            }
            [IO.File]::Exists($oldBinary) | Should Be $true

            . $runRecovery

            (Get-Content -LiteralPath $script:SecretPath -Raw -Encoding ASCII) |
                Should Be 'old-dpapi-ciphertext'
            $restoredConfig = Get-Content -LiteralPath $script:ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $restoredConfig.cloudflared_path | Should Be $oldBinary
            [IO.File]::Exists($oldBinary) | Should Be $true
            (Resolve-Cloudflared) | Should Be (Resolve-Path -LiteralPath $oldBinary).Path
            [IO.File]::Exists($script:RecoveryPath) | Should Be $false
        }
    }

    It 'first scheduled Run consumes replacement state and a later interrupted Run restores the old token and path' {
        foreach ($helperName in @('Save-EncryptedToken', 'Save-ConnectorConfig', 'Save-RotationRecovery',
                'Restore-InterruptedRotation', 'Prepare-ConnectorRunAfterRotation', 'Resolve-Cloudflared')) {
            . ([scriptblock]::Create((Get-ConnectorFunctionText $helperName)))
        }
        $oldBinary = Join-Path $script:connectorRoot 'cloudflared-old.exe'
        $newBinary = Join-Path $script:connectorRoot 'cloudflared-new.exe'
        Set-Content -LiteralPath $oldBinary -Value 'old executable' -NoNewline
        Set-Content -LiteralPath $newBinary -Value 'new executable' -NoNewline

        Save-EncryptedToken -CipherText 'old-encrypted-token'
        Save-ConnectorConfig -ResolvedCloudflaredPath $oldBinary
        Save-RotationRecovery -CipherText 'old-encrypted-token' -ResolvedCloudflaredPath $oldBinary
        Save-EncryptedToken -CipherText 'replacement-encrypted-token'
        Save-ConnectorConfig -ResolvedCloudflaredPath $newBinary
        Save-RotationRecovery -CipherText 'old-encrypted-token' -ResolvedCloudflaredPath $oldBinary `
            -Phase 'REPLACEMENT_START_PENDING'

        # The first scheduled Run consumes, but does not discard, the rollback record.
        Prepare-ConnectorRunAfterRotation
        (Get-Content -LiteralPath $script:SecretPath -Raw -Encoding ASCII) |
            Should Be 'replacement-encrypted-token'
        (Get-Content -LiteralPath $script:ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json).cloudflared_path |
            Should Be $newBinary
        $pendingRecovery = Get-Content -LiteralPath $script:RecoveryPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $pendingRecovery.rotation_phase | Should Be 'REPLACEMENT_START_CONSUMED'
        Resolve-Cloudflared | Should Be (Resolve-Path -LiteralPath $newBinary).Path
        (Get-Content -LiteralPath $script:LogPath -Raw -Encoding UTF8) |
            Should Match 'Rotation replacement startup accepted'

        # A second Run means the replacement did not reach readiness before interruption.
        Prepare-ConnectorRunAfterRotation
        (Get-Content -LiteralPath $script:SecretPath -Raw -Encoding ASCII) |
            Should Be 'old-encrypted-token'
        (Get-Content -LiteralPath $script:ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json).cloudflared_path |
            Should Be $oldBinary
        Resolve-Cloudflared | Should Be (Resolve-Path -LiteralPath $oldBinary).Path
        [IO.File]::Exists($script:RecoveryPath) | Should Be $false
    }

    It 'restores pending rotation state before a retry and rolls a failed replacement back to the original token and path' {
        foreach ($helperName in @('Save-EncryptedToken', 'Save-ConnectorConfig', 'Save-RotationRecovery',
                'Restore-InterruptedRotation', 'Restore-PendingRotationBeforeRetry', 'Resolve-Cloudflared')) {
            . ([scriptblock]::Create((Get-ConnectorFunctionText $helperName)))
        }
        $oldBinary = Join-Path $script:connectorRoot 'cloudflared-old.exe'
        $newBinary = Join-Path $script:connectorRoot 'cloudflared-new.exe'
        Set-Content -LiteralPath $oldBinary -Value 'old executable' -NoNewline
        Set-Content -LiteralPath $newBinary -Value 'new executable' -NoNewline
        $script:Mode = 'Rotate'
        $script:CloudflaredPath = $newBinary
        $script:TaskName = 'ERP_MCP_CloudflareTunnel_razer'
        $global:connectorEvents = @()
        $global:connectorStartCalls = 0
        function Stop-ConnectorTask([string]$ResolvedCloudflaredPath) {
            $global:connectorEvents += "stop:$ResolvedCloudflaredPath"
        }
        function Start-ConnectorTaskAndWait([string]$ResolvedCloudflaredPath, [string]$ExpectedRotationMarker) {
            $global:connectorStartCalls++
            $global:connectorEvents += "start:$ResolvedCloudflaredPath"
            if ($global:connectorStartCalls -eq 1) { throw 'RETRY_REPLACEMENT_NOT_READY' }
        }

        # Simulate a crash after both replacement writes; the durable marker still holds originals.
        Save-EncryptedToken -CipherText 'interrupted-new-token'
        Save-ConnectorConfig -ResolvedCloudflaredPath $newBinary
        Save-RotationRecovery -CipherText 'original-encrypted-token' -ResolvedCloudflaredPath $oldBinary

        Restore-PendingRotationBeforeRetry

        (Get-Content -LiteralPath $script:SecretPath -Raw -Encoding ASCII) |
            Should Be 'original-encrypted-token'
        (Get-Content -LiteralPath $script:ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json).cloudflared_path |
            Should Be $oldBinary
        [IO.File]::Exists($script:RecoveryPath) | Should Be $false
        $global:connectorEvents[0] | Should Be "stop:$newBinary"

        $requestedPath = $script:CloudflaredPath
        $script:CloudflaredPath = ''
        $script:previousCloudflaredPath = Resolve-Cloudflared
        $script:CloudflaredPath = $requestedPath
        $script:previousEncryptedToken = Get-Content -LiteralPath $script:SecretPath -Raw -Encoding ASCII
        $script:resolvedCloudflaredPath = Resolve-Cloudflared
        $script:encrypted = 'retry-encrypted-token'

        { . (Get-RotateElseBlock) } | Should Throw 'previous token restored and connector readiness confirmed'

        (Get-Content -LiteralPath $script:SecretPath -Raw -Encoding ASCII) |
            Should Be 'original-encrypted-token'
        (Get-Content -LiteralPath $script:ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json).cloudflared_path |
            Should Be $oldBinary
        [IO.File]::Exists($script:RecoveryPath) | Should Be $false
    }

    It 'does not replace the saved token when stopping the prior connector is unconfirmed' {
        $rotate = Get-RotateElseBlock
        $script:Mode = 'Rotate'
        $script:encrypted = 'new-token-ciphertext'
        $script:previousEncryptedToken = 'old-token-ciphertext'
        $script:resolvedCloudflaredPath = 'C:\tools\cloudflared.exe'
        $script:previousCloudflaredPath = 'C:\tools\cloudflared.exe'
        $global:connectorEvents = @()
        function Stop-ConnectorTask([string]$ResolvedCloudflaredPath) { $global:connectorEvents += 'stop'; throw 'STOP_NOT_CONFIRMED' }
        function Save-RotationRecovery { param([string]$CipherText, [string]$ResolvedCloudflaredPath, [string]$Phase) Set-Content -LiteralPath $script:RecoveryPath -Value '{}' -NoNewline }
        function Save-EncryptedToken { param([string]$CipherText) $global:connectorEvents += "token:$CipherText" }
        function Save-ConnectorConfig { param([string]$ResolvedCloudflaredPath) $global:connectorEvents += 'config' }
        function Start-ConnectorTaskAndWait { param([string]$ResolvedCloudflaredPath, [string]$ExpectedRotationMarker) $global:connectorEvents += 'start' }

        { & $rotate } | Should Throw 'STOP_NOT_CONFIRMED'
        ($global:connectorEvents -join ',') | Should Be 'stop'
    }

    It 'starts the replacement only after the old task is stopped and both new values are saved' {
        $rotate = Get-RotateElseBlock
        $script:Mode = 'Rotate'
        $script:encrypted = 'new-token-ciphertext'
        $script:previousEncryptedToken = 'old-token-ciphertext'
        $script:resolvedCloudflaredPath = 'C:\tools\cloudflared.exe'
        $script:previousCloudflaredPath = 'C:\tools\cloudflared.exe'
        $global:connectorEvents = @()
        function Stop-ConnectorTask([string]$ResolvedCloudflaredPath) { $global:connectorEvents += 'stop' }
        function Save-RotationRecovery { param([string]$CipherText, [string]$ResolvedCloudflaredPath, [string]$Phase) Set-Content -LiteralPath $script:RecoveryPath -Value '{}' -NoNewline }
        function Save-EncryptedToken { param([string]$CipherText) $global:connectorEvents += "token:$CipherText" }
        function Save-ConnectorConfig { param([string]$ResolvedCloudflaredPath) $global:connectorEvents += "config:$ResolvedCloudflaredPath" }
        function Start-ConnectorTaskAndWait { param([string]$ResolvedCloudflaredPath, [string]$ExpectedRotationMarker) $global:connectorEvents += "start:$ResolvedCloudflaredPath" }

        & $rotate

        ($global:connectorEvents -join ',') | Should Be 'stop,token:new-token-ciphertext,config:C:\tools\cloudflared.exe,start:C:\tools\cloudflared.exe'
    }

    It 'restores the previous token and confirms old connector readiness when replacement startup fails' {
        $rotate = Get-RotateElseBlock
        $script:Mode = 'Rotate'
        $script:encrypted = 'new-token-ciphertext'
        $script:previousEncryptedToken = 'old-token-ciphertext'
        $script:resolvedCloudflaredPath = 'C:\tools\cloudflared-new.exe'
        $script:previousCloudflaredPath = 'C:\tools\cloudflared-old.exe'
        $global:connectorEvents = @()
        $global:connectorStartCalls = 0
        function Stop-ConnectorTask([string]$ResolvedCloudflaredPath) { $global:connectorEvents += 'stop' }
        function Save-RotationRecovery { param([string]$CipherText, [string]$ResolvedCloudflaredPath, [string]$Phase) Set-Content -LiteralPath $script:RecoveryPath -Value '{}' -NoNewline }
        function Save-EncryptedToken { param([string]$CipherText) $global:connectorEvents += "token:$CipherText" }
        function Save-ConnectorConfig { param([string]$ResolvedCloudflaredPath) $global:connectorEvents += "config:$ResolvedCloudflaredPath" }
        function Start-ConnectorTaskAndWait {
            param([string]$ResolvedCloudflaredPath, [string]$ExpectedRotationMarker)
            $global:connectorStartCalls++
            $global:connectorEvents += "start:$ResolvedCloudflaredPath"
            if ($global:connectorStartCalls -eq 1) { throw 'NEW_CONNECTOR_NOT_READY' }
        }

        { & $rotate } | Should Throw 'previous token restored and connector readiness confirmed'
        ($global:connectorEvents -join ',') | Should Be 'stop,token:new-token-ciphertext,config:C:\tools\cloudflared-new.exe,start:C:\tools\cloudflared-new.exe,stop,token:old-token-ciphertext,config:C:\tools\cloudflared-old.exe,start:C:\tools\cloudflared-old.exe'
    }

    It 'restores the previously configured executable path when Rotate receives a new CloudflaredPath and replacement readiness fails' {
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Resolve-Cloudflared')))
        $oldBinary = Join-Path $script:connectorRoot 'cloudflared-old.exe'
        $newBinary = Join-Path $script:connectorRoot 'cloudflared-new.exe'
        Set-Content -LiteralPath $oldBinary -Value 'old executable' -NoNewline
        Set-Content -LiteralPath $newBinary -Value 'new executable' -NoNewline
        Set-Content -LiteralPath $script:ConfigPath -Value (@{ cloudflared_path = $oldBinary } | ConvertTo-Json -Compress) -NoNewline
        Set-Content -LiteralPath $script:SecretPath -Value 'previous-encrypted-token' -NoNewline
        $script:Mode = 'Rotate'
        $script:CloudflaredPath = $newBinary

        $script:previousEncryptedToken = Get-Content -LiteralPath $script:SecretPath -Raw -Encoding ASCII
        $script:CloudflaredPath = ''
        $script:previousCloudflaredPath = Resolve-Cloudflared
        $script:CloudflaredPath = $newBinary
        $script:resolvedCloudflaredPath = Resolve-Cloudflared
        $previousEncryptedToken | Should Be 'previous-encrypted-token'
        $previousCloudflaredPath | Should Be (Resolve-Path -LiteralPath $oldBinary).Path

        $script:encrypted = 'replacement-encrypted-token'
        $global:connectorEvents = @()
        $global:connectorStartCalls = 0
        function Stop-ConnectorTask([string]$ResolvedCloudflaredPath) { $global:connectorEvents += 'stop' }
        function Save-RotationRecovery { param([string]$CipherText, [string]$ResolvedCloudflaredPath, [string]$Phase) Set-Content -LiteralPath $script:RecoveryPath -Value '{}' -NoNewline }
        function Save-EncryptedToken { param([string]$CipherText) $global:connectorEvents += "token:$CipherText" }
        function Save-ConnectorConfig { param([string]$ResolvedCloudflaredPath) $global:connectorEvents += "config:$ResolvedCloudflaredPath" }
        function Start-ConnectorTaskAndWait {
            param([string]$ResolvedCloudflaredPath, [string]$ExpectedRotationMarker)
            $global:connectorStartCalls++
            $global:connectorEvents += "start:$ResolvedCloudflaredPath"
            if ($global:connectorStartCalls -eq 1) { throw 'REPLACEMENT_READINESS_FAILED' }
        }

        { . (Get-RotateElseBlock) } | Should Throw 'previous token restored and connector readiness confirmed'
        ($global:connectorEvents -join ',') | Should Be (
            'stop,token:replacement-encrypted-token,config:' + (Resolve-Path -LiteralPath $newBinary).Path +
            ',start:' + (Resolve-Path -LiteralPath $newBinary).Path +
            ',stop,token:previous-encrypted-token,config:' + (Resolve-Path -LiteralPath $oldBinary).Path +
            ',start:' + (Resolve-Path -LiteralPath $oldBinary).Path
        )
    }

    It 'does not save a replacement token when the exact executable appears outside the task tree after stop begins' {
        foreach ($helperName in @('Get-ConnectorProcessSnapshot', 'Add-TrackedConnectorProcessSnapshot', 'Stop-ConnectorTask')) {
            . ([scriptblock]::Create((Get-ConnectorFunctionText $helperName)))
        }
        $rotate = Get-RotateElseBlock
        $script:Mode = 'Rotate'
        $script:TaskName = 'ERP_MCP_CloudflareTunnel_razer'
        $script:encrypted = 'replacement-encrypted-token'
        $script:previousEncryptedToken = 'previous-encrypted-token'
        $script:resolvedCloudflaredPath = Join-Path $script:connectorRoot 'cloudflared-new.exe'
        $script:previousCloudflaredPath = Join-Path $script:connectorRoot 'cloudflared-old.exe'
        $global:connectorEvents = @()
        $global:cloudflaredPathScans = 0
        function Get-ConnectorProcessTreeIds { return @() }
        function Get-CloudflaredProcessIdsByPath([string]$ResolvedCloudflaredPath) {
            $global:cloudflaredPathScans++
            if ($global:cloudflaredPathScans -eq 1) { return @(9021) }
            return @()
        }
        function Stop-ScheduledTask { $global:connectorEvents += 'stop-task' }
        function Get-ScheduledTask { return [pscustomobject]@{ State = 'Ready' } }
        function Get-Process { return $null }
        function Save-RotationRecovery {
            param([string]$CipherText, [string]$ResolvedCloudflaredPath, [string]$Phase)
            $global:connectorEvents += 'save-recovery'
        }
        function Save-EncryptedToken([string]$CipherText) { $global:connectorEvents += "save-token:$CipherText" }
        function Save-ConnectorConfig([string]$ResolvedCloudflaredPath) { $global:connectorEvents += 'save-config' }

        { & $rotate } | Should Throw 'CLOUDFLARED_PROCESS_STOP_NOT_CONFIRMED'
        ($global:connectorEvents -join ',') | Should Be 'save-recovery,stop-task'
        $global:cloudflaredPathScans | Should Be 1
        ($global:connectorEvents -join ',') | Should Not Match 'save-token:replacement-encrypted-token'
    }

    It 'fails closed on PID reuse and never stops the process with a different identity' {
        foreach ($helperName in @('Get-ConnectorProcessIdentity', 'Add-TrackedConnectorProcessSnapshot',
                'Stop-ConnectorTask')) {
            . ([scriptblock]::Create((Get-ConnectorFunctionText $helperName)))
        }
        $trackedBinary = Join-Path $script:connectorRoot 'cloudflared-old.exe'
        $reusedBinary = Join-Path $script:connectorRoot 'unrelated.exe'
        $script:TaskName = 'ERP_MCP_CloudflareTunnel_razer'
        $global:processSnapshotCalls = 0
        $global:stopProcessCalls = 0
        $global:connectorEvents = @()
        function Get-ConnectorProcessTreeIds { return @(733) }
        function Get-ConnectorProcessSnapshot([int[]]$ProcessIds) {
            $global:processSnapshotCalls++
            $identity = if ($global:processSnapshotCalls -eq 1) {
                @{ CreationDate = '2026-11-22T10:00:00Z'; ExecutablePath = $trackedBinary; CommandLine = 'cloudflared tunnel run old' }
            } else {
                @{ CreationDate = '2026-11-22T10:00:01Z'; ExecutablePath = $reusedBinary; CommandLine = 'unrelated process after PID reuse' }
            }
            return @([pscustomobject]@{
                ProcessId = 733
                CreationDate = $identity.CreationDate
                ExecutablePath = $identity.ExecutablePath
                CommandLine = $identity.CommandLine
            })
        }
        function Stop-ScheduledTask { $global:connectorEvents += 'stop-task' }
        function Get-ScheduledTask { return [pscustomobject]@{ State = 'Ready' } }
        function Get-CloudflaredProcessIdsByPath([string]$ResolvedCloudflaredPath) { return @() }
        function Stop-Process { $global:stopProcessCalls++ }

        { Stop-ConnectorTask -ResolvedCloudflaredPath $trackedBinary -TimeoutSeconds 0 } |
            Should Throw 'CLOUDFLARED_PROCESS_IDENTITY_CHANGED'
        $global:stopProcessCalls | Should Be 0
        ($global:connectorEvents -join ',') | Should Be 'stop-task'
        $global:processSnapshotCalls | Should Be 2
    }

    It 'confirms rotation readiness only with the exact executable and a fresh replacement-start marker' {
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Start-ConnectorTaskAndWait')))
        function Get-ConnectorProcessTreeIds { return @(421) }
        function Get-CloudflaredProcessIdsByPath([string]$ResolvedCloudflaredPath) {
            if ($ResolvedCloudflaredPath -ceq 'C:\tools\cloudflared.exe') { return @(421) }
            return @()
        }
        function Get-LogTextAfter([long]$Offset) {
            return "Rotation replacement startup accepted`nRegistered tunnel connection connIndex=0"
        }
        Mock Start-ScheduledTask {}
        Mock Get-ScheduledTask { return [pscustomobject]@{ State = 'Running' } }
        Mock Start-Sleep {}

        { Start-ConnectorTaskAndWait -ResolvedCloudflaredPath 'C:\tools\cloudflared.exe' -TimeoutSeconds 0 `
            -ExpectedRotationMarker 'Rotation replacement startup accepted' } |
            Should Not Throw
        Assert-MockCalled Start-ScheduledTask -Times 1
        (Get-LogTextAfter -Offset 0) | Should Match 'Registered tunnel connection'

        { Start-ConnectorTaskAndWait -ResolvedCloudflaredPath 'C:\tools\other.exe' -TimeoutSeconds 0 `
            -ExpectedRotationMarker 'Rotation replacement startup accepted' } |
            Should Throw 'CLOUDFLARED_CONNECTOR_READINESS_NOT_CONFIRMED'
    }

    It 'does not confirm rotation readiness without a fresh replacement-start marker' {
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Start-ConnectorTaskAndWait')))
        function Get-ConnectorProcessTreeIds { return @(421) }
        function Get-CloudflaredProcessIdsByPath([string]$ResolvedCloudflaredPath) { return @(421) }
        function Get-LogTextAfter([long]$Offset) { return 'Registered tunnel connection connIndex=0' }
        Mock Start-ScheduledTask {}
        Mock Get-ScheduledTask { return [pscustomobject]@{ State = 'Running' } }
        Mock Start-Sleep {}

        { Start-ConnectorTaskAndWait -ResolvedCloudflaredPath 'C:\tools\cloudflared.exe' -TimeoutSeconds 0 `
            -ExpectedRotationMarker 'Rotation replacement startup accepted' } |
            Should Throw 'CLOUDFLARED_CONNECTOR_READINESS_NOT_CONFIRMED'
    }

    It 'rejects a tunnel authentication error even when the task reports running' {
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Start-ConnectorTaskAndWait')))
        function Get-ConnectorProcessTreeIds { return @(421) }
        function Get-CloudflaredProcessIdsByPath([string]$ResolvedCloudflaredPath) { return @(421) }
        function Get-LogTextAfter([long]$Offset) { return 'Unauthorized: invalid tunnel token' }
        Mock Start-ScheduledTask {}
        Mock Get-ScheduledTask { return [pscustomobject]@{ State = 'Running' } }
        Mock Start-Sleep {}

        { Start-ConnectorTaskAndWait -ResolvedCloudflaredPath 'C:\tools\cloudflared.exe' -TimeoutSeconds 0 } |
            Should Throw 'CLOUDFLARED_CONNECTOR_AUTHENTICATION_FAILED'
        (Get-LogTextAfter -Offset 0) | Should Match 'Unauthorized'
    }

    It 'does not accept a running task without its cloudflared process and fresh connection evidence' {
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Start-ConnectorTaskAndWait')))
        function Get-ConnectorProcessTreeIds { return @() }
        function Get-CloudflaredProcessIdsByPath([string]$ResolvedCloudflaredPath) { return @() }
        function Get-LogTextAfter([long]$Offset) { return '' }
        Mock Start-ScheduledTask {}
        Mock Get-ScheduledTask { return [pscustomobject]@{ State = 'Running' } }
        Mock Start-Sleep {}

        { Start-ConnectorTaskAndWait -ResolvedCloudflaredPath 'C:\tools\cloudflared.exe' -TimeoutSeconds 0 } |
            Should Throw 'CLOUDFLARED_CONNECTOR_READINESS_NOT_CONFIRMED'
    }

    It 'serializes rotation mutex acquisition across runspaces until the first owner releases it' {
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Enter-ConnectorRotationMutex')))
        . ([scriptblock]::Create((Get-ConnectorFunctionText 'Exit-ConnectorRotationMutex')))
        $script:TunnelName = 'rotation-test-' + [guid]::NewGuid().ToString('N')
        $script:CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $firstMutex = Enter-ConnectorRotationMutex -TimeoutSeconds 5
        $ready = [Threading.ManualResetEvent]::new($false)
        $runspace = [RunspaceFactory]::CreateRunspace()
        $runspace.Open()
        $runspace.SessionStateProxy.SetVariable('TunnelName', $script:TunnelName)
        $runspace.SessionStateProxy.SetVariable('CurrentSid', $script:CurrentSid)
        $runspace.SessionStateProxy.SetVariable('readyEvent', $ready)
        $secondPowerShell = [PowerShell]::Create()
        $secondPowerShell.Runspace = $runspace
        $enterMutexDefinition = Get-ConnectorFunctionText 'Enter-ConnectorRotationMutex'
        $exitMutexDefinition = Get-ConnectorFunctionText 'Exit-ConnectorRotationMutex'
        [void]$secondPowerShell.AddScript($enterMutexDefinition + "`n" + $exitMutexDefinition + @'
$readyEvent.Set() | Out-Null
$secondMutex = Enter-ConnectorRotationMutex -TimeoutSeconds 5
try { 'ACQUIRED' } finally { Exit-ConnectorRotationMutex -Mutex $secondMutex }
'@)
        $async = $secondPowerShell.BeginInvoke()
        try {
            $ready.WaitOne(2000) | Should Be $true
            Start-Sleep -Milliseconds 150
            $async.IsCompleted | Should Be $false
        } finally {
            Exit-ConnectorRotationMutex -Mutex $firstMutex
        }
        try {
            $result = $secondPowerShell.EndInvoke($async)
            ($result -join '') | Should Be 'ACQUIRED'
        } finally {
            $secondPowerShell.Dispose()
            $runspace.Dispose()
            $ready.Dispose()
        }
    }

}
