# Tear down ONLY this worktree's private stack (named containers + recorded PIDs).
. (Join-Path $PSScriptRoot 'common.ps1')
$pidFile = Join-Path $script:StateDir 'pids.txt'
if (Test-Path $pidFile) {
    foreach ($line in Get-Content $pidFile) {
        $id = [int](($line -split '=')[1])
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile
}
docker rm -f $script:PgName $script:RedisName 2>$null | Out-Null
Write-Host 'private stack stopped (var\ft\ft.env and logs kept; delete var\ft yourself if desired)'
