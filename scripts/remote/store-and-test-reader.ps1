<#
.SYNOPSIS
  Runs on the 1C host. Reads the dedicated read-only 1C reader password from STDIN (never from the command line),
  stores it as a CurrentUser DPAPI blob, and issues one authenticated OData $metadata request to prove that the
  copied base opens and the reader works. Prints only status codes and sizes; never the password.
#>
[CmdletBinding()]
param(
    [string]$BlobPath = 'D:\1c\secrets\test_reader_password.dpapi',
    [string]$User = 'ERP_MCP_TEST_READER',
    [string]$Url = 'http://127.0.0.1:8088/erp_mcp_remote/odata/standard.odata/$metadata',
    [switch]$SkipStore
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security

if (-not $SkipStore) {
    $pw = [Console]::In.ReadToEnd().TrimEnd("`r", "`n")
    if ([string]::IsNullOrEmpty($pw)) { throw 'no password on stdin' }
    New-Item -ItemType Directory -Force -Path (Split-Path $BlobPath) | Out-Null
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($pw)
    $blob = [Security.Cryptography.ProtectedData]::Protect($bytes, $null, 'CurrentUser')
    [IO.File]::WriteAllBytes($BlobPath, $blob)
    [Array]::Clear($bytes, 0, $bytes.Length)
    'stored blob bytes : ' + $blob.Length
    $pw = $null
}

$plain = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($BlobPath), $null, 'CurrentUser')
$pair = $User + ':' + [Text.UTF8Encoding]::new($false).GetString($plain)
[Array]::Clear($plain, 0, $plain.Length)
$hdr = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)) }
$pair = $null
$sw = [Diagnostics.Stopwatch]::StartNew()
try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -Headers $hdr -TimeoutSec 600
    'odata metadata    : HTTP ' + $r.StatusCode + ', ' + $r.RawContentLength + ' bytes'
} catch {
    if ($_.Exception.Response) { 'odata metadata    : HTTP ' + [int]$_.Exception.Response.StatusCode } else { 'odata metadata    : error (no response)' }
}
'seconds           : ' + [int]$sw.Elapsed.TotalSeconds
