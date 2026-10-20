<#
.SYNOPSIS
  Downloads and unpacks PORTABLE runtimes for the ERP_MCP stack under -Root: Node 24, PostgreSQL 16 (EDB binaries zip), Redis for Windows.
  No services, no registry, no PATH, no firewall changes. Idempotent: an existing unpacked directory is kept.
#>
[CmdletBinding()]
param([string]$Root = 'D:\1c\mcp')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dl = Join-Path $Root 'dl'
New-Item -ItemType Directory -Force -Path $dl, (Join-Path $Root 'runtime') | Out-Null

function Get-File([string]$Url, [string]$Out) {
    if (Test-Path $Out) { return }
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Out -TimeoutSec 900
}

# Node 24 (latest 24.x from the official index)
$idx = Invoke-RestMethod 'https://nodejs.org/dist/index.json' -TimeoutSec 60
$nodeVer = ($idx | Where-Object { $_.version -like 'v24.*' } | Select-Object -First 1).version
$nodeZip = Join-Path $dl "node-$nodeVer-win-x64.zip"
if (-not (Test-Path (Join-Path $Root 'runtime\node'))) {
    Get-File "https://nodejs.org/dist/$nodeVer/node-$nodeVer-win-x64.zip" $nodeZip
    Expand-Archive -Path $nodeZip -DestinationPath (Join-Path $Root 'runtime') -Force
    Rename-Item (Join-Path $Root "runtime\node-$nodeVer-win-x64") 'node'
}
'node     : ' + (& (Join-Path $Root 'runtime\node\node.exe') -v)

# PostgreSQL 16 binaries (EDB zip, no installer)
$pgDir = Join-Path $Root 'runtime\pgsql'
if (-not (Test-Path $pgDir)) {
    $pgZip = $null
    foreach ($v in '16.9-1', '16.8-1', '16.6-1', '16.4-1') {
        $try = Join-Path $dl "postgresql-$v-windows-x64-binaries.zip"
        try { Get-File "https://get.enterprisedb.com/postgresql/postgresql-$v-windows-x64-binaries.zip" $try; $pgZip = $try; break } catch { Remove-Item $try -ErrorAction SilentlyContinue }
    }
    if (-not $pgZip) { throw 'no PostgreSQL 16 binaries zip could be downloaded' }
    Expand-Archive -Path $pgZip -DestinationPath (Join-Path $Root 'runtime') -Force
}
'postgres : ' + (& (Join-Path $pgDir 'bin\postgres.exe') --version)

# Redis for Windows (tporadowski build, 5.x; the Python client in use is compatible)
$redisDir = Join-Path $Root 'runtime\redis'
if (-not (Test-Path $redisDir)) {
    $rz = Join-Path $dl 'Redis-x64-5.0.14.1.zip'
    Get-File 'https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip' $rz
    Expand-Archive -Path $rz -DestinationPath $redisDir -Force
}
'redis    : ' + (& (Join-Path $redisDir 'redis-server.exe') --version)
