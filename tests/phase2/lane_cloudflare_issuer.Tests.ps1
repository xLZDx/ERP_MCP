$laneScriptPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..\scripts\real1c\autostart\start_lane.ps1')).Path
$laneAst = [System.Management.Automation.Language.Parser]::ParseFile($laneScriptPath, [ref]$null, [ref]$null)

function Get-LaneFunctionText([string]$Name) {
    $node = $laneAst.Find({
        param($candidate)
        $candidate -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $candidate.Name -eq $Name
    }, $true)
    if (-not $node) { throw "FUNCTION_NOT_FOUND:$Name" }
    return $node.Extent.Text
}

function Get-IssuerGuardCondition {
    $node = $laneAst.Find({
        param($candidate)
        $candidate -is [System.Management.Automation.Language.IfStatementAst] -and
            $candidate.Extent.Text -match "throw 'ISSUER_CONFIG_MISMATCH'"
    }, $true)
    if (-not $node) { throw 'ISSUER_GUARD_NOT_FOUND' }
    return [string]$node.Clauses[0].Item1.Extent.Text
}

function Get-RouteFailureBranch {
    $node = $laneAst.Find({
        param($candidate)
        $candidate -is [System.Management.Automation.Language.IfStatementAst] -and
            $candidate.Extent.Text -match 'Test-CloudflareIdpRoute' -and
            $candidate.Extent.Text -match 'Stop-GatewayFailClosed'
    }, $true)
    if (-not $node) { throw 'ROUTE_FAILURE_BRANCH_NOT_FOUND' }
    # Replace process-level exit with a test sentinel while retaining the production branch logic.
    $branchText = $node.Extent.Text -replace '\bexit 1\b', "throw 'STARTUP_ABORTED'"
    return [scriptblock]::Create($branchText)
}

Describe 'Cloudflare issuer consistency and readiness contract' {
    BeforeEach {
        . ([scriptblock]::Create((Get-LaneFunctionText 'Get-LaneEnvIssuer')))
        . ([scriptblock]::Create((Get-LaneFunctionText 'Test-CloudflareIdpRoute')))
        function Log([string]$Message) { $global:laneLoggedMessages += $Message }
        $global:laneLoggedMessages = @()
        $global:publicIssuer = 'https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test'
        $global:publicDiscovery = @{
            issuer = $global:publicIssuer
            authorization_endpoint = 'https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test/protocol/openid-connect/auth'
            token_endpoint = 'https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test/protocol/openid-connect/token'
            jwks_uri = 'https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test/protocol/openid-connect/certs'
        }
        $global:localDiscovery = @{
            issuer = $global:publicIssuer
            authorization_endpoint = 'http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/auth'
            token_endpoint = 'http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/token'
            jwks_uri = 'http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/certs'
        }
        $global:laneJwks = @{ keys = @(@{
            kid = 'issuer-test-key-1'; kty = 'RSA'; n = 'fixture-modulus-1'; e = 'AQAB'
            x = $null; y = $null; crv = $null; alg = 'RS256'; use = 'sig'
        }) }
        Mock Start-Sleep {}
    }

    It 'rejects multiple distinct values of the actual BAG_OAUTH_ISSUER setting' {
        $envText = @'
$env:BAG_OAUTH_ISSUER="https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test"
$env:BAG_OAUTH_ISSUER="https://unexpected.example/realms/erp-mcp-test"
'@
        { Get-LaneEnvIssuer -Text $envText } | Should Throw 'ENV_ISSUER_AMBIGUOUS'
    }

    It 'reads the exact BAG_OAUTH_ISSUER assignment' {
        $envText = '$env:BAG_OAUTH_ISSUER = "https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test"'

        (Get-LaneEnvIssuer -Text $envText) | Should Be $global:publicIssuer
    }

    It 'rejects an issuer realm path with a suffix' {
        $envText = '$env:BAG_OAUTH_ISSUER = "https://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test-extra"'

        { Get-LaneEnvIssuer -Text $envText } | Should Throw 'ENV_ISSUER_INVALID'
    }

    It 'rejects malformed or non-HTTPS BAG_OAUTH_ISSUER values' {
        $envText = '$env:BAG_OAUTH_ISSUER = "http://razer-erp-mcp-idp.sptr.space/realms/erp-mcp-test"'

        { Get-LaneEnvIssuer -Text $envText } | Should Throw 'ENV_ISSUER_INVALID'
        { Get-LaneEnvIssuer -Text '$env:BAG_OAUTH_ISSUER = missing-quotes' } | Should Throw 'ENV_ISSUER_MISSING'
    }

    It 'uses the real preflight guard to reject a mismatched JSON issuer before startup' {
        $condition = Get-IssuerGuardCondition
        $guard = [scriptblock]::Create("param(`$idpConfig, `$envIssuer, `$targetIdpIssuer) return (`n$condition`n)")
        $matching = [pscustomobject]@{ issuer = $global:publicIssuer }
        $differentJsonIssuer = [pscustomobject]@{ issuer = 'https://other.example/realms/erp-mcp-test' }

        (& $guard $matching $global:publicIssuer $global:publicIssuer) | Should Be $false
        (& $guard $differentJsonIssuer $global:publicIssuer $global:publicIssuer) | Should Be $true
        (& $guard $matching 'https://old.example/realms/erp-mcp-test' $global:publicIssuer) | Should Be $true
        (& $guard $matching $global:publicIssuer 'https://old.example/realms/erp-mcp-test') | Should Be $true
    }

    It 'does not rewrite either IdP configuration file during startup' {
        $source = Get-Content -LiteralPath $laneScriptPath -Raw
        $source | Should Not Match 'WriteAllText\(\$envPath'
        $source | Should Not Match 'WriteAllText\(\$cfgPath'
        $source | Should Match 'ISSUER_CONFIG_MISMATCH'
    }

    It 'aborts startup and records an unconfirmed gateway stop when the public route fails' {
        $branch = Get-RouteFailureBranch
        $global:routeFailureEvents = @()
        function Test-CloudflareIdpRoute([string]$ExpectedIssuer) {
            $global:routeFailureEvents += 'route-check'
            return $false
        }
        function Stop-GatewayFailClosed([string]$Reason) {
            $global:routeFailureEvents += "stop:$Reason"
            return $false
        }
        function Log([string]$Message) { $global:routeFailureEvents += "log:$Message" }

        { & $branch } | Should Throw 'STARTUP_ABORTED'
        ($global:routeFailureEvents -join "`n") | Should Match 'route-check'
        ($global:routeFailureEvents -join "`n") | Should Match 'stop:public IdP route differs from local issuer/key set'
        ($global:routeFailureEvents -join "`n") | Should Match 'startup aborted with gateway listener still present'
        ($global:routeFailureEvents -join "`n") | Should Not Match 'gateway-start'
    }

    It 'aborts startup after a confirmed gateway stop when the public route fails' {
        $branch = Get-RouteFailureBranch
        $global:routeFailureEvents = @()
        function Test-CloudflareIdpRoute([string]$ExpectedIssuer) { return $false }
        function Stop-GatewayFailClosed([string]$Reason) {
            $global:routeFailureEvents += "stop:$Reason"
            return $true
        }
        function Log([string]$Message) { $global:routeFailureEvents += "log:$Message" }

        { & $branch } | Should Throw 'STARTUP_ABORTED'
        ($global:routeFailureEvents -join "`n") | Should Match 'stop:public IdP route differs from local issuer/key set'
        ($global:routeFailureEvents -join "`n") | Should Not Match 'gateway-start'
    }

    It 'accepts public discovery and signing keys that match the local IdP' {
        Mock Invoke-RestMethod {
            if ($Uri -eq ($global:publicIssuer + '/.well-known/openid-configuration')) { return $global:publicDiscovery }
            if ($Uri -eq 'http://127.0.0.1:21080/realms/erp-mcp-test/.well-known/openid-configuration') { return $global:localDiscovery }
            if ($Uri -eq $global:publicDiscovery.jwks_uri -or
                $Uri -eq 'http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/certs') { return $global:laneJwks }
            throw "UNEXPECTED_URI:$Uri"
        }

        (Test-CloudflareIdpRoute -ExpectedIssuer $global:publicIssuer) | Should Be $true
        Assert-MockCalled Invoke-RestMethod -Times 4
    }

    It 'refuses a public issuer that does not match the configured exact issuer' {
        $global:publicDiscovery.issuer = 'https://other.example/realms/erp-mcp-test'
        Mock Invoke-RestMethod {
            if ($Uri -eq ($global:publicIssuer + '/.well-known/openid-configuration')) { return $global:publicDiscovery }
            if ($Uri -eq 'http://127.0.0.1:21080/realms/erp-mcp-test/.well-known/openid-configuration') { return $global:localDiscovery }
            if ($Uri -eq $global:publicDiscovery.jwks_uri -or
                $Uri -eq 'http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/certs') { return $global:laneJwks }
            throw "UNEXPECTED_URI:$Uri"
        }

        (Test-CloudflareIdpRoute -ExpectedIssuer $global:publicIssuer) | Should Be $false
        Assert-MockCalled Invoke-RestMethod -Times 10
    }

    It 'refuses discovery endpoints that leave the exact configured HTTPS host' {
        $global:publicDiscovery.token_endpoint = 'https://other.example/token'
        Mock Invoke-RestMethod {
            if ($Uri -eq ($global:publicIssuer + '/.well-known/openid-configuration')) { return $global:publicDiscovery }
            if ($Uri -eq 'http://127.0.0.1:21080/realms/erp-mcp-test/.well-known/openid-configuration') { return $global:localDiscovery }
            if ($Uri -eq $global:publicDiscovery.jwks_uri -or
                $Uri -eq 'http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/certs') { return $global:laneJwks }
            throw "UNEXPECTED_URI:$Uri"
        }

        (Test-CloudflareIdpRoute -ExpectedIssuer $global:publicIssuer) | Should Be $false
        Assert-MockCalled Invoke-RestMethod -Times 10
    }

    It 'refuses a public JWKS that differs from the local IdP key set' {
        $global:publicJwks = @{ keys = @(@{
            kid = 'different-key'; kty = 'RSA'; n = 'different-modulus'; e = 'AQAB'
            x = $null; y = $null; crv = $null; alg = 'RS256'; use = 'sig'
        }) }
        Mock Invoke-RestMethod {
            if ($Uri -eq ($global:publicIssuer + '/.well-known/openid-configuration')) { return $global:publicDiscovery }
            if ($Uri -eq 'http://127.0.0.1:21080/realms/erp-mcp-test/.well-known/openid-configuration') { return $global:localDiscovery }
            if ($Uri -eq $global:publicDiscovery.jwks_uri) { return $global:publicJwks }
            if ($Uri -eq 'http://127.0.0.1:21080/realms/erp-mcp-test/protocol/openid-connect/certs') { return $global:laneJwks }
            throw "UNEXPECTED_URI:$Uri"
        }

        (Test-CloudflareIdpRoute -ExpectedIssuer $global:publicIssuer) | Should Be $false
        Assert-MockCalled Invoke-RestMethod -Times 20
    }

    It 'fails after bounded retries when the public Cloudflare issuer is unavailable' {
        Mock Invoke-RestMethod { throw 'HTTP 503' }

        (Test-CloudflareIdpRoute -ExpectedIssuer $global:publicIssuer) | Should Be $false
        Assert-MockCalled Invoke-RestMethod -Times 5
        $global:laneLoggedMessages[-1] | Should Match 'after bounded retries'
    }
}
