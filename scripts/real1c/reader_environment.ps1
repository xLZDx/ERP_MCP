#Requires -Version 5.1
# Operator-side bootstrap for the existing 818HA reference TEST lane only.
# Functions only: dot-sourcing this file does not read or decrypt any credential.

function Test-818HAReferenceState {
    param([Parameter(Mandatory=$true)][string]$StateDirectory)
    try {
        $actual = [IO.Path]::GetFullPath($StateDirectory).TrimEnd([char[]]'\/')
        return $actual.Equals('D:\ERP_MCP_Testbed\real1c_e2e', [StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

function Read-818HAReaderPassword {
    # Same approved reader and CurrentUser DPAPI blob as lane_setup._reader_credentials.
    # Never use an administrator credential or return a secret in an MCP response.
    $encrypted = $null
    $plainBytes = $null
    try {
        Add-Type -AssemblyName System.Security -ErrorAction Stop
        $path = 'D:\secrets\erp_mcp\test_reader_password.dpapi'
        $info = New-Object IO.FileInfo($path)
        if (-not $info.Exists -or $info.Length -lt 1 -or $info.Length -gt 65536) {
            throw 'READER_BLOB_UNAVAILABLE'
        }
        $encrypted = [IO.File]::ReadAllBytes($path)
        $plainBytes = [Security.Cryptography.ProtectedData]::Unprotect(
            $encrypted, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        $decoder = New-Object Text.UTF8Encoding($false, $true)
        return $decoder.GetString($plainBytes)
    } catch {
        # Do not forward crypto/file exception details, buffers, or credential values.
        throw 'ERP_READER_SECRET_UNAVAILABLE: use the Windows account that owns the existing reader DPAPI blob.'
    } finally {
        if ($null -ne $plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
        if ($null -ne $encrypted) { [Array]::Clear($encrypted, 0, $encrypted.Length) }
    }
}

function Invoke-818HAReaderEnvironment {
    [CmdletBinding()]
    param([Parameter(Mandatory=$true)][scriptblock]$Action)

    # Do not introduce an environment-secret fallback in production or another provider.
    if ($env:BAG_ENVIRONMENT -cne 'test' -or $env:BAG_SECRET_PROVIDER -cne 'env') {
        throw 'ERP_READER_TEST_ENV_REQUIRED: this bootstrap is only for the existing test/env lane.'
    }
    $target = [EnvironmentVariableTarget]::Process
    $userName = 'ERP_MCP_818HA_USER'
    $passwordName = 'ERP_MCP_818HA_PASSWORD'
    $beforeUser = [Environment]::GetEnvironmentVariable($userName, $target)
    $beforePassword = [Environment]::GetEnvironmentVariable($passwordName, $target)
    $password = $null
    try {
        $hasUser = -not [string]::IsNullOrEmpty($beforeUser)
        $hasPassword = -not [string]::IsNullOrEmpty($beforePassword)
        if ($hasUser -ne $hasPassword) {
            throw 'ERP_READER_PARTIAL_ENV: supply both reader variables or neither; values were not changed.'
        }
        if ($hasUser) {
            if ($beforeUser -cne 'ERP_MCP_TEST_READER') {
                throw 'ERP_READER_UNEXPECTED_IDENTITY: this lane requires its dedicated read-only reader.'
            }
            $password = $beforePassword
        } else {
            try { $password = Read-818HAReaderPassword } catch {
                throw 'ERP_READER_SECRET_UNAVAILABLE: reader secret could not be loaded; gateway was not started.'
            }
        }
        if ([string]::IsNullOrEmpty($password) -or $password.IndexOf([char]0) -ge 0 -or
            $password.Contains("`r") -or $password.Contains("`n")) {
            throw 'ERP_READER_SECRET_INVALID: reader secret is empty or has invalid control characters.'
        }
        # Process-only, immediately around launch. Nothing is written to a file or registry.
        [Environment]::SetEnvironmentVariable($userName, 'ERP_MCP_TEST_READER', $target)
        [Environment]::SetEnvironmentVariable($passwordName, $password, $target)
        & $Action
    } finally {
        # The child already inherited its environment; remove our temporary copy afterwards.
        [Environment]::SetEnvironmentVariable($userName, $beforeUser, $target)
        [Environment]::SetEnvironmentVariable($passwordName, $beforePassword, $target)
        $password = $null
        $beforePassword = $null
    }
}
