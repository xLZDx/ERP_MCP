<#
.SYNOPSIS
  Run on the 1C host. Reads the administrator login and password of the DISPOSABLE test base copy from STDIN (two lines),
  stores them as a CurrentUser DPAPI blob, and proves them with one COM connection to the file base (connect, read the current
  user name, disconnect). Prints only booleans. Never echoes or logs the credentials. Test copy only.
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\1c\mcp',
    [string]$BlobPath,
    [string]$BasePath = 'D:\1c\env\bases\818HA_test_ready',
    [switch]$TestOnly
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
if (-not $BlobPath) { $BlobPath = Join-Path $Root 'env\onec_admin.dpapi' }
$blobPath = $BlobPath

if (-not $TestOnly) {
    $user = [Console]::In.ReadLine()
    $pass = [Console]::In.ReadLine()
    if ([string]::IsNullOrWhiteSpace($user)) { throw 'no login on stdin' }
    $payload = @{ user = $user.Trim(); password = ($pass + '').TrimEnd("`r", "`n") } | ConvertTo-Json -Compress
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($payload)
    [IO.File]::WriteAllBytes($blobPath, [Security.Cryptography.ProtectedData]::Protect($bytes, $null, 'CurrentUser'))
    [Array]::Clear($bytes, 0, $bytes.Length)
    $payload = $null; $user = $null; $pass = $null
    'stored blob bytes : ' + (Get-Item $blobPath).Length
}

$plain = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($blobPath), $null, 'CurrentUser')
$cred = [Text.UTF8Encoding]::new($false).GetString($plain) | ConvertFrom-Json
[Array]::Clear($plain, 0, $plain.Length)
$connected = $false
$isAdmin = $null
try {
    $connector = New-Object -ComObject V83.COMConnector
    $conn = $connector.Connect('File="' + $BasePath + '";Usr="' + $cred.user + '";Pwd="' + $cred.password + '";')
    $connected = $true
    try { $isAdmin = [bool]($conn.InfoBaseUsers.CurrentUser().Name -eq $cred.user) } catch { $isAdmin = $null }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)
} catch {
    'connect error type : ' + $_.Exception.GetType().Name
    'connect error text : ' + (($_.Exception.Message -replace [regex]::Escape([string]$cred.password), '<r>') -replace '\s+', ' ').Substring(0, [Math]::Min(160, $_.Exception.Message.Length))
}
$cred = $null
'COM connect ok     : ' + $connected
'current user match : ' + $isAdmin
