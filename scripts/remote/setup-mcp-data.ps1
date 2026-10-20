<#
.SYNOPSIS
  PostgreSQL 16 + Redis for the ERP_MCP stack on a Windows host, as portable detached processes under -Root (no services).
  Actions: Init (initdb + config), Start (postgres + redis detached), Restore (roles.sql + db.sql from -Dump), Status, Stop.
  Secrets are never printed. redis.conf (with requirepass) and the dump files are supplied by the operator-side session.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Init', 'Start', 'Restore', 'Status', 'Stop')][string]$Action,
    [string]$Root = 'D:\1c\mcp',
    [int]$PgPort = 18432,
    [int]$RedisPort = 19379
)
$ErrorActionPreference = 'Stop'
$pgBin = Join-Path $Root 'runtime\pgsql\bin'
$pgData = Join-Path $Root 'data\pg'
$redisDir = Join-Path $Root 'runtime\redis'
$redisConf = Join-Path $Root 'env\redis.conf'
$logs = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $logs, (Join-Path $Root 'data'), (Join-Path $Root 'env') | Out-Null

function Test-Port([int]$Port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) }
function Start-Detached([string]$CommandLine, [string]$WorkDir) {
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $CommandLine; CurrentDirectory = $WorkDir }
    if ($r.ReturnValue -ne 0) { throw "Win32_Process.Create failed rc=$($r.ReturnValue)" }
}
function Wait-Port([int]$Port, [int]$Seconds) {
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) { if (Test-Port $Port) { return $true }; Start-Sleep -Seconds 1 }
    return $false
}

switch ($Action) {
    'Init' {
        if (-not (Test-Path (Join-Path $pgData 'PG_VERSION'))) {
            & (Join-Path $pgBin 'initdb.exe') -D $pgData -U postgres -E UTF8 --locale=C --auth-local=trust --auth-host=scram-sha-256 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'initdb failed' }
            Add-Content -Path (Join-Path $pgData 'postgresql.conf') -Value @(
                "port = $PgPort", "listen_addresses = '127.0.0.1'", 'password_encryption = scram-sha-256', 'max_connections = 100')
        }
        'initdb: ' + (Test-Path (Join-Path $pgData 'PG_VERSION'))
    }
    'Start' {
        if (-not (Test-Port $PgPort)) {
            # postgres.exe refuses to run with administrator rights; pg_ctl starts it with a restricted token.
            Start-Detached ('"' + (Join-Path $pgBin 'pg_ctl.exe') + '" start -D "' + $pgData + '" -l "' + (Join-Path $logs 'postgres.log') + '"') $Root
        }
        if (-not (Test-Port $RedisPort)) {
            if (-not (Test-Path $redisConf)) { throw "missing $redisConf" }
            Start-Detached ('cmd /c ""' + (Join-Path $redisDir 'redis-server.exe') + '" "' + $redisConf + '" >> "' + (Join-Path $logs 'redis.log') + '" 2>&1"') $redisDir
        }
        'postgres listening: ' + (Wait-Port $PgPort 40)
        'redis listening   : ' + (Wait-Port $RedisPort 20)
    }
    'Restore' {
        $psql = Join-Path $pgBin 'psql.exe'
        $dump = Join-Path $Root 'env\dump'
        # Bootstrap-only: trust the superuser on loopback while restoring, then restore the scram-only pg_hba.conf.
        $hba = Join-Path $pgData 'pg_hba.conf'
        $hbaOriginal = Get-Content $hba -Raw
        Set-Content -Path $hba -Value ("host all postgres 127.0.0.1/32 trust`r`n" + $hbaOriginal) -Encoding ASCII
        & (Join-Path $pgBin 'pg_ctl.exe') reload -D $pgData | Out-Null
        try {
        $exists = & $psql -h 127.0.0.1 -p $PgPort -U postgres -d postgres -Atc "select count(*) from pg_database where datname='business_ai'"
        if ($exists -eq '1') { 'business_ai already exists - restore skipped' }
        else {
        & $psql -h 127.0.0.1 -p $PgPort -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f (Join-Path $dump 'roles.sql') 2>&1 | Select-Object -Last 3
        & $psql -h 127.0.0.1 -p $PgPort -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f (Join-Path $dump 'db.sql') 2>&1 | Select-Object -Last 3
        'tables: ' + (& $psql -h 127.0.0.1 -p $PgPort -U postgres -d business_ai -Atc "select count(*) from information_schema.tables where table_schema='bag'")
        'sources: ' + (& $psql -h 127.0.0.1 -p $PgPort -U postgres -d business_ai -Atc 'select count(*) from bag.sources')
        }
        } finally {
            Set-Content -Path $hba -Value $hbaOriginal -Encoding ASCII -NoNewline
            & (Join-Path $pgBin 'pg_ctl.exe') reload -D $pgData | Out-Null
        }
    }
    'Status' {
        'postgres listening: ' + (Test-Port $PgPort)
        'redis listening   : ' + (Test-Port $RedisPort)
    }
    'Stop' {
        Get-Process postgres, redis-server -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Root*" } | Stop-Process -Force
        'stopped'
    }
}
