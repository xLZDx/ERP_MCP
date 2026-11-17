$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$stackPath = Join-Path $repoRoot 'scripts\remote\run-mcp-stack.ps1'
$tokens = $null
$parseErrors = $null
$stackAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $stackPath, [ref]$tokens, [ref]$parseErrors
)
$stackText = Get-Content -Raw -Path $stackPath
$gatewaySectionStart = $stackText.IndexOf('# 6. Gateway')
$missingAddressBranchStart = $stackText.IndexOf(
    'if (-not (Wait-Address $BindIp 300)) {', $gatewaySectionStart
)
$missingAddressBranchEnd = $stackText.IndexOf(
    'elseif (Test-Port 21000) {', $missingAddressBranchStart
)
$gatewayBranchStart = $stackText.IndexOf('elseif (Test-Port 21000) {', $gatewaySectionStart)
$gatewayBranchEnd = $stackText.IndexOf('# 7. OpenAI tunnel-client', $gatewayBranchStart)
$existingListenerBranchEnd = $stackText.IndexOf('} else {', $gatewayBranchStart)
$newGatewayBranchStart = $existingListenerBranchEnd
$newGatewayBranchEnd = $gatewayBranchEnd
$helperAst = $stackAst.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Assert-RequiredGatewayReady'
}, $true)
$readinessHelper = if ($helperAst) { [scriptblock]::Create($helperAst.Extent.Text) }
$healthHelperAst = $stackAst.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Test-RequiredGatewayReady'
}, $true)
$healthHelper = if ($healthHelperAst) { [scriptblock]::Create($healthHelperAst.Extent.Text) }
$waitHelperAst = $stackAst.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Wait-RequiredGatewayReady'
}, $true)
$waitHelper = if ($waitHelperAst) { [scriptblock]::Create($waitHelperAst.Extent.Text) }
$readinessWaitModule = if ($healthHelperAst -and $waitHelperAst) {
    New-Module -Name RemoteStackReadinessTestModule `
        -ArgumentList @($healthHelperAst.Extent.Text, $waitHelperAst.Extent.Text) `
        -ScriptBlock {
            param($healthFunctionText, $waitFunctionText)
            . ([scriptblock]::Create($healthFunctionText))
            . ([scriptblock]::Create($waitFunctionText))
            Export-ModuleMember -Function Test-RequiredGatewayReady, Wait-RequiredGatewayReady
        }
}
if ($readinessWaitModule) { Import-Module $readinessWaitModule }

Describe 'Required gateway readiness assertion' {
    It 'is present as a standalone function in the stack script' {
        ($null -ne $helperAst) | Should Be $true
        $parseErrors.Count | Should Be 0
    }

    It 'accepts a ready gateway' {
        . $readinessHelper
        $result = Assert-RequiredGatewayReady -Ready $true
        $result | Should Be $true
    }

    It 'rejects an unavailable required gateway' {
        . $readinessHelper
        $message = $null
        try {
            Assert-RequiredGatewayReady -Ready $false
        } catch {
            $message = $_.Exception.Message
        }
        $message | Should Be 'GATEWAY_NOT_READY'
    }

    It 'checks the started gateway port wait through the readiness assertion' {
        ($gatewayBranchStart -ge 0 -and $gatewayBranchEnd -gt $gatewayBranchStart) | Should Be $true
        $waitAssignments = $stackAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
                $node.Extent.StartOffset -ge $gatewayBranchStart -and
                $node.Extent.EndOffset -le $gatewayBranchEnd -and
                $node.Left.Extent.Text -eq '$gatewayReady' -and
                $node.Right.Extent.Text -match 'Wait-Port\s+21000\s+60'
        }, $true)
        $readinessAssertions = $stackAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
                $node.GetCommandName() -eq 'Assert-RequiredGatewayReady' -and
                $node.Extent.StartOffset -ge $gatewayBranchStart -and
                $node.Extent.EndOffset -le $gatewayBranchEnd -and
                $node.Extent.Text -match '-Ready\s+\$gatewayReady'
        }, $true)
        ($waitAssignments.Count -gt 0) | Should Be $true
        ($readinessAssertions.Count -gt 0) | Should Be $true
    }

    It 'fails when the required gateway bind address is unavailable' {
        ($missingAddressBranchStart -ge 0 -and
            $missingAddressBranchEnd -gt $missingAddressBranchStart) | Should Be $true
        $unavailableAssertions = $stackAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
                $node.GetCommandName() -eq 'Assert-RequiredGatewayReady' -and
                $node.Extent.StartOffset -ge $missingAddressBranchStart -and
                $node.Extent.EndOffset -le $missingAddressBranchEnd -and
                $node.Extent.Text -match '-Ready\s+\$false'
        }, $true)
        ($unavailableAssertions.Count -gt 0) | Should Be $true
    }

    It 'returns true only for readyz JSON with status ready' {
        ($null -ne $healthHelperAst) | Should Be $true
        . $healthHelper
        Mock Invoke-RestMethod { return @{ status = 'ready' } }
        (Test-RequiredGatewayReady -Uri 'http://127.0.0.1:21000/readyz') | Should Be $true
        Assert-MockCalled Invoke-RestMethod -Times 1
    }

    It 'returns false for readyz JSON that is not ready' {
        ($null -ne $healthHelperAst) | Should Be $true
        . $healthHelper
        Mock Invoke-RestMethod { return @{ status = 'starting' } }
        (Test-RequiredGatewayReady -Uri 'http://127.0.0.1:21000/readyz') | Should Be $false
        Assert-MockCalled Invoke-RestMethod -Times 1
    }

    It 'returns false when readyz returns an HTTP error' {
        ($null -ne $healthHelperAst) | Should Be $true
        . $healthHelper
        Mock Invoke-RestMethod { throw 'HTTP 503' }
        (Test-RequiredGatewayReady -Uri 'http://127.0.0.1:21000/readyz') | Should Be $false
        Assert-MockCalled Invoke-RestMethod -Times 1
    }

    It 'returns false when the readyz request throws' {
        ($null -ne $healthHelperAst) | Should Be $true
        . $healthHelper
        Mock Invoke-RestMethod { throw 'request failed' }
        (Test-RequiredGatewayReady -Uri 'http://127.0.0.1:21000/readyz') | Should Be $false
        Assert-MockCalled Invoke-RestMethod -Times 1
    }

    It 'calls readyz validation for both existing and newly started gateway branches' {
        ($existingListenerBranchEnd -gt $gatewayBranchStart -and
            $newGatewayBranchStart -ge $gatewayBranchStart -and
            $newGatewayBranchEnd -gt $newGatewayBranchStart) | Should Be $true
        $existingListenerWaits = $stackAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
                $node.GetCommandName() -eq 'Wait-RequiredGatewayReady' -and
                $node.Extent.StartOffset -ge $gatewayBranchStart -and
                $node.Extent.EndOffset -le $existingListenerBranchEnd
        }, $true)
        $newGatewayWaits = $stackAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.CommandAst] -and
                $node.GetCommandName() -eq 'Wait-RequiredGatewayReady' -and
                $node.Extent.StartOffset -ge $newGatewayBranchStart -and
                $node.Extent.EndOffset -le $newGatewayBranchEnd
        }, $true)
        ($existingListenerWaits.Count -gt 0) | Should Be $true
        ($newGatewayWaits.Count -gt 0) | Should Be $true
    }

    It 'waits through transient not-ready responses until a ready response arrives' {
        ($null -ne $readinessWaitModule) | Should Be $true
        $global:erpMcpReadinessCallCount = 0
        $global:erpMcpReadinessSequence = [System.Collections.Queue]::new()
        $global:erpMcpReadinessSequence.Enqueue($false)
        $global:erpMcpReadinessSequence.Enqueue($true)
        Mock Test-RequiredGatewayReady -ModuleName RemoteStackReadinessTestModule {
            $global:erpMcpReadinessCallCount++
            return $global:erpMcpReadinessSequence.Dequeue()
        }
        Mock Start-Sleep -ModuleName RemoteStackReadinessTestModule {}
        $result = Wait-RequiredGatewayReady -Uri 'http://127.0.0.1:21000/readyz' -Attempts 3
        $result | Should Be $true
        $global:erpMcpReadinessCallCount | Should Be 2
        Assert-MockCalled Start-Sleep -ModuleName RemoteStackReadinessTestModule -Times 1
        Remove-Variable erpMcpReadinessCallCount, erpMcpReadinessSequence -Scope Global
    }

    It 'returns false after the configured number of readiness attempts' {
        ($null -ne $readinessWaitModule) | Should Be $true
        $global:erpMcpReadinessCallCount = 0
        $global:erpMcpReadinessSequence = [System.Collections.Queue]::new()
        $global:erpMcpReadinessSequence.Enqueue($false)
        $global:erpMcpReadinessSequence.Enqueue($false)
        $global:erpMcpReadinessSequence.Enqueue($false)
        Mock Test-RequiredGatewayReady -ModuleName RemoteStackReadinessTestModule {
            $global:erpMcpReadinessCallCount++
            return $global:erpMcpReadinessSequence.Dequeue()
        }
        Mock Start-Sleep -ModuleName RemoteStackReadinessTestModule {}
        $result = Wait-RequiredGatewayReady -Uri 'http://127.0.0.1:21000/readyz' -Attempts 3
        $result | Should Be $false
        $global:erpMcpReadinessCallCount | Should Be 3
        Assert-MockCalled Start-Sleep -ModuleName RemoteStackReadinessTestModule -Times 2
        Remove-Variable erpMcpReadinessCallCount, erpMcpReadinessSequence -Scope Global
    }
}
