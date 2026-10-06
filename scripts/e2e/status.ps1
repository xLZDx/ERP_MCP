#Requires -Version 5.1
<#
.SYNOPSIS
  Health of each component. Exit code 1 when anything is unhealthy. -Json for machines.
#>
[CmdletBinding()]
param([switch]$Json)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

if (-not (Test-Path (Join-Path $script:E2eDir 'env.json'))) {
    if ($Json) { '{"healthy":false,"error":"not initialised"}' } else { Write-Host 'not initialised (run up.ps1)' }
    exit 1
}
$info = Get-Content (Join-Path $script:E2eDir 'env.json') -Raw | ConvertFrom-Json
$base = 'http://127.0.0.1:'
$components = [ordered]@{}

function Get-BindState([int]$Port) {
    $rows = Get-ListenerInfo $Port
    if (-not $rows) { return 'not-listening' }
    $bad = @($rows | Where-Object { $_.Address -ne '127.0.0.1' })
    if ($bad.Count -gt 0) { return 'EXPOSED:' + (($bad | ForEach-Object { $_.Address }) -join ',') }
    return 'loopback-only'
}

$db = $null
try {
    Import-E2eEnv
    $db = (Invoke-Envctl @('status-json') -Quiet)[0] | Select-Object -Last 1 | ConvertFrom-Json
} catch { $db = $null } finally { Clear-E2eSecretEnv }
foreach ($name in 'postgres', 'redis') {
    $entry = $null
    if ($db) { $entry = $db.$name }
    $ok = [bool]($entry -and $entry.ok)
    $row = [ordered]@{ healthy = $ok; port = $script:Ports[$name]; bind = (Get-BindState $script:Ports[$name]) }
    if ($ok) { $row.version = $entry.server_version }
    if ($ok -and $name -eq 'postgres') {
        $row.schema_version = $entry.schema_version
        if ($entry.schema_version -ne 14) { $row.healthy = $false }
    }
    $components[$name] = $row
}
$checks = [ordered]@{
    fake1c = ($base + '18766/odata/standard.odata/$metadata')
    idp = ($base + '18080/healthz')
    gateway = ($base + '18000/readyz')
}
foreach ($name in $checks.Keys) {
    $code = Test-Http -Url $checks[$name] -TimeoutSec 5
    $components[$name] = [ordered]@{ healthy = ($code -eq 200); port = $script:Ports[$name]
        http_status = $code; bind = (Get-BindState $script:Ports[$name]) }
}
foreach ($name in $components.Keys) {
    if ($components[$name].bind -like 'EXPOSED*') { $components[$name].healthy = $false }
}
$healthy = -not ($components.Values | Where-Object { -not $_.healthy })
$result = [ordered]@{ healthy = [bool]$healthy; project = $script:ProjectName; seed_mode = $info.seed_mode
    components = $components }
if ($Json) {
    $result | ConvertTo-Json -Depth 6
} else {
    Write-Host ('seed mode: ' + $info.seed_mode)
    foreach ($name in $components.Keys) {
        $c = $components[$name]
        $state = 'UNHEALTHY'
        if ($c.healthy) { $state = 'ok' }
        $extra = ''
        if ($c.Contains('version')) { $extra += ' version=' + $c.version }
        if ($c.Contains('pid_match')) { $extra += ' pid=' + $c.pid + ' pid_match=' + $c.pid_match }
        if ($c.Contains('schema_version')) { $extra += ' schema=' + $c.schema_version }
        Write-Host ('{0,-9} {1,-9} port={2} {3}{4}' -f $name, $state, $c.port, $c.bind, $extra)
    }
}
if ($healthy) { exit 0 } else { exit 1 }
