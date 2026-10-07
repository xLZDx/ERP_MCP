#Requires -Version 5.1
<#
.SYNOPSIS
  Installs a verified official OpenAI tunnel-client into .chatgpt/bin.

.DESCRIPTION
  Downloads the selected release archive and SHA256SUMS.txt directly from the
  official openai/tunnel-client GitHub release, verifies SHA-256, and installs
  tunnel-client.exe into the git-ignored local tools directory.

  The default version is the latest release verified for this branch on
  2026-10-07. Override -Version deliberately when upgrading and rerun tests.
#>
[CmdletBinding()]
param(
    [string]$Version = 'v0.0.16',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^v\d+\.\d+\.\d+$') { throw 'Version must look like v0.0.16' }

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$BinDir = Join-Path $Root '.chatgpt\bin'
$Exe = Join-Path $BinDir 'tunnel-client.exe'
$Meta = Join-Path $BinDir 'tunnel-client-install.json'

if ((Test-Path $Exe) -and -not $Force) {
    Write-Host ('[chatgpt] tunnel-client already installed: ' + $Exe)
    & $Exe --version
    exit $LASTEXITCODE
}

$archName = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
switch ($archName) {
    'X64' { $arch = 'amd64' }
    'Arm64' { $arch = 'arm64' }
    default { throw ('unsupported Windows architecture: ' + $archName) }
}

$asset = 'tunnel-client-' + $Version + '-windows-' + $arch + '.zip'
$base = 'https://github.com/openai/tunnel-client/releases/download/' + $Version
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('erp-mcp-tunnel-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

try {
    $zip = Join-Path $tmp $asset
    $sums = Join-Path $tmp 'SHA256SUMS.txt'

    & curl.exe -L --fail --silent --show-error --max-time 180 -o $sums ($base + '/SHA256SUMS.txt')
    if ($LASTEXITCODE -ne 0) { throw 'checksum download failed' }

    & curl.exe -L --fail --silent --show-error --max-time 300 -o $zip ($base + '/' + $asset)
    if ($LASTEXITCODE -ne 0) { throw 'archive download failed' }

    $escaped = [regex]::Escape($asset)
    $line = Get-Content $sums |
        Where-Object { $_ -match ('^([a-fA-F0-9]{64})\s+\*?' + $escaped + '$') } |
        Select-Object -First 1
    if (-not $line) { throw ('checksum entry missing for ' + $asset) }

    $expected = ([regex]::Match($line, '^([a-fA-F0-9]{64})')).Groups[1].Value.ToLowerInvariant()
    $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw 'tunnel-client archive SHA256 mismatch' }

    $expanded = Join-Path $tmp 'expanded'
    Expand-Archive -Path $zip -DestinationPath $expanded -Force
    $found = Get-ChildItem -Path $expanded -Filter tunnel-client.exe -Recurse | Select-Object -First 1
    if (-not $found) { throw 'tunnel-client.exe not found in verified archive' }

    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    Copy-Item -Path $found.FullName -Destination $Exe -Force
    @{
        release = $Version
        asset = $asset
        sha256 = $actual
        source = $base
        installed_at_utc = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content -Path $Meta -Encoding UTF8

    Write-Host ('[chatgpt] installed tunnel-client ' + $Version)
    Write-Host ('[chatgpt] verified SHA256 ' + $actual)
    & $Exe --version
    if ($LASTEXITCODE -ne 0) { throw 'installed tunnel-client failed version smoke' }
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
